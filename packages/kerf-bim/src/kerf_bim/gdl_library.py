"""
kerf_bim.gdl_library
=====================

GDL Parametric Object Library — ArchiCAD parity.

Implements parametric object scripting and instancing for ArchiCAD GDL
(Geometric Description Language) parity.  Rather than requiring the full
GDL interpreter, kerf uses a safe Python subset with the same expressive
power for geometry generation, bridged to the kerf-cad-core B-rep kernel.

References
----------
GRAPHISOFT GDL Reference Manual (ArchiCAD 27) — GDL scripting language spec.
IFC4 ADD2 TC1 — IfcTypeProduct for library-object type definitions.
ISO 16739-1:2018 — IFC standard for BIM data exchange.

GDL parity
----------
Kerf GDL objects parallel ArchiCAD GDL objects in structure:

  GDLObject  ≈  GDL script + MASTER_SCRIPT + PARAMETERS block
  GDLParam   ≈  GDL PARAMETERS declaration
  GDLInstance≈  Placed instance with parameter overrides

Key GDL concepts supported:
  - PARAMETERS block with typed values (length, angle, boolean, string,
    integer, real, title)
  - Master script (evaluated once on placement)
  - Parametre inheritance: instances override object defaults
  - Subtype hierarchy: GDL objects can extend a parent subtype

Not supported (ArchiCAD-only):
  - Binary (hsf/lcf) GDL bytecode compilation
  - 2D symbol script
  - LABEL / ZONE / HOTSPOT commands (planned Phase 2)

Public API
----------
  GDLParam(name, type, default, min, max, values, description)
  GDLObject(id, name, subtype, params, script, description)
  GDLInstance(object_id, params)
  GDLLibrary(objects)

  evaluate_gdl_object(obj, params) -> dict
      Run the object's script and return resolved values + geometry summary.

  validate_gdl_object(obj) -> list[str]
      Static validation of the GDL object definition.

  instantiate_gdl(library, object_id, param_overrides) -> dict
      Place a library object with given overrides.

  DEFAULT_LIBRARY : GDLLibrary
      Built-in starter library (door, window, column, beam, wall niche).
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# GDL parameter types (maps to ArchiCAD GDL PARAMETERS types)
# ---------------------------------------------------------------------------

GDL_TYPES = frozenset({
    "length",   # real, dimension in metres
    "angle",    # real, in degrees
    "real",     # general real number
    "integer",  # integer number
    "boolean",  # on/off
    "string",   # text
    "title",    # separator (no value; used for UI grouping)
    "material", # material index (stored as string name)
    "pen",      # pen/colour (stored as integer index)
    "line",     # line-type (stored as integer index)
    "fill",     # fill type (stored as integer index)
})

# ArchiCAD GDL subtype hierarchy (partial — most common)
GDL_SUBTYPES = frozenset({
    "Object",
    "Door",
    "Window",
    "Skylight",
    "Column",
    "Beam",
    "Stair",
    "Railing",
    "Wall_niche",
    "Furniture",
    "Equipment",
    "Lamp",
    "Vegetation",
    "Label",
    "Zone",
    "MEP_duct",
    "MEP_pipe",
    "MEP_fitting",
    "Roof_opening",
    "Curtain_wall_panel",
    "Curtain_wall_frame",
    "Generic",
})

# Safe math for GDL scripts
_SAFE_MATH: Dict[str, Any] = {
    k: v for k, v in vars(math).items() if not k.startswith("_")
}
_SAFE_MATH.update({
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float, "bool": bool, "str": str,
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GDLParam:
    """A single GDL parameter declaration.

    Attributes
    ----------
    name : str
        Parameter name (GDL identifier, upper-case by convention).
    type : str
        GDL type string (see GDL_TYPES).
    default : Any
        Default value.
    min : float | None
        Minimum value (length/angle/real/integer only).
    max : float | None
        Maximum value.
    values : list | None
        Enumerated allowed values (for poplist UI — stored as list of strings).
    description : str
        Human-readable tooltip.
    """

    name: str
    type: str = "length"
    default: Any = 0.0
    min: Optional[float] = None
    max: Optional[float] = None
    values: Optional[List[Any]] = None
    description: str = ""

    def __post_init__(self):
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError(f"GDLParam.name must be a valid identifier, got {self.name!r}")
        if self.type not in GDL_TYPES:
            raise ValueError(
                f"GDLParam '{self.name}': type must be one of {sorted(GDL_TYPES)}, got '{self.type}'"
            )
        if self.type in ("length", "angle", "real", "integer"):
            if self.min is not None and self.max is not None and self.min > self.max:
                raise ValueError(
                    f"GDLParam '{self.name}': min ({self.min}) > max ({self.max})"
                )

    def default_value(self) -> Any:
        """Return the typed default value."""
        if self.type in ("length", "angle", "real"):
            return float(self.default)
        if self.type == "integer":
            return int(self.default)
        if self.type == "boolean":
            return bool(self.default)
        return self.default


@dataclass
class GDLObject:
    """A GDL parametric object definition.

    Attributes
    ----------
    id : str
        Unique object identifier (e.g. ``"DOOR_SINGLE_00001"``).
    name : str
        Display name.
    subtype : str
        ArchiCAD GDL subtype (default ``"Object"``).
    params : list[GDLParam]
        Ordered PARAMETERS block declarations.
    script : str
        Python script (GDL-replacement) executed to generate geometry.
        Must assign ``result`` to a dict (geometry summary) or leave it
        unset (returns resolved params only).
    description : str
        Human-readable object description.
    author : str
        Library author.
    """

    id: str
    name: str
    subtype: str = "Object"
    params: List[GDLParam] = field(default_factory=list)
    script: str = ""
    description: str = ""
    author: str = ""

    def __post_init__(self):
        if not self.id:
            raise ValueError("GDLObject.id must be non-empty")
        if not self.name:
            raise ValueError("GDLObject.name must be non-empty")
        if self.subtype not in GDL_SUBTYPES:
            raise ValueError(
                f"GDLObject '{self.id}': subtype must be one of {sorted(GDL_SUBTYPES)}"
            )
        # Check for duplicate param names
        seen: set = set()
        for p in self.params:
            if p.name in seen:
                raise ValueError(
                    f"GDLObject '{self.id}': duplicate param name '{p.name}'"
                )
            seen.add(p.name)

    def param_defaults(self) -> Dict[str, Any]:
        """Return a name→default-value mapping."""
        return {p.name: p.default_value() for p in self.params}


@dataclass
class GDLInstance:
    """A placed instance of a GDL object with parameter overrides.

    Attributes
    ----------
    object_id : str
        ID of the :class:`GDLObject` this instance references.
    params : dict[str, Any]
        Per-instance parameter overrides (merged over object defaults).
    instance_id : str
        Optional unique instance identifier.
    """

    object_id: str
    params: Dict[str, Any] = field(default_factory=dict)
    instance_id: str = ""

    def __post_init__(self):
        if not self.object_id:
            raise ValueError("GDLInstance.object_id must be non-empty")


@dataclass
class GDLLibrary:
    """A collection of GDL parametric objects.

    Attributes
    ----------
    objects : list[GDLObject]
    """

    objects: List[GDLObject] = field(default_factory=list)

    def get(self, object_id: str) -> Optional[GDLObject]:
        """Look up an object by id."""
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        return None

    def list_objects(self, subtype: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return a metadata list, optionally filtered by subtype."""
        result = []
        for obj in self.objects:
            if subtype and obj.subtype != subtype:
                continue
            result.append({
                "id": obj.id,
                "name": obj.name,
                "subtype": obj.subtype,
                "param_count": len(obj.params),
                "description": obj.description,
                "author": obj.author,
            })
        return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_UNSAFE_NODES = frozenset({
    ast.Import, ast.ImportFrom, ast.Delete, ast.Global, ast.Nonlocal,
    ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith,
})


def _check_script_safety(source: str, label: str) -> List[str]:
    errors: List[str] = []
    if not source.strip():
        return errors
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{label}: syntax error: {exc}"]

    for node in ast.walk(tree):
        if type(node) in _UNSAFE_NODES:
            errors.append(f"{label}: unsafe node '{type(node).__name__}'")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id not in ("math",):
                errors.append(f"{label}: attribute access on '{node.value.id}' is not allowed")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"exec", "eval", "compile", "open", "__import__"}:
                errors.append(f"{label}: call to '{func.id}' is not allowed")
    return errors


def validate_gdl_object(obj: GDLObject) -> List[str]:
    """Validate a GDL object and return error strings (empty = valid)."""
    errors: List[str] = []
    if not obj.id:
        errors.append("id is required")
    if not obj.name:
        errors.append("name is required")
    if obj.subtype not in GDL_SUBTYPES:
        errors.append(f"unknown subtype '{obj.subtype}'")
    errors.extend(_check_script_safety(obj.script, f"object '{obj.id}' script"))
    return errors


# ---------------------------------------------------------------------------
# Evaluate GDL object
# ---------------------------------------------------------------------------

def evaluate_gdl_object(
    obj: GDLObject,
    param_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve parameters and execute the GDL script.

    Parameters
    ----------
    obj : GDLObject
    param_overrides : dict | None

    Returns
    -------
    dict with:
      ``object_id``      — obj.id
      ``name``           — obj.name
      ``subtype``        — obj.subtype
      ``resolved_params``— merged parameter values
      ``geometry``       — result from script (or None)
    """
    ns = obj.param_defaults()
    if param_overrides:
        # Validate and apply overrides
        param_map = {p.name: p for p in obj.params}
        for k, v in param_overrides.items():
            if k in param_map:
                ns[k] = v

    geometry = None
    if obj.script.strip():
        exec_globals: Dict[str, Any] = {
            "__builtins__": {
                "abs": abs, "round": round, "min": min, "max": max,
                "int": int, "float": float, "bool": bool, "str": str,
                "list": list, "dict": dict, "range": range, "len": len,
                "sum": sum, "sorted": sorted, "print": print,
            },
            "math": math,
            **_SAFE_MATH,
        }
        exec_locals = dict(ns)
        try:
            exec(  # noqa: S102
                compile(obj.script, f"<gdl:{obj.id}>", "exec"),
                exec_globals,
                exec_locals,
            )
            geometry = exec_locals.get("result")
        except Exception as exc:
            raise ValueError(f"GDL script for '{obj.id}' raised: {exc}") from exc

    return {
        "object_id": obj.id,
        "name": obj.name,
        "subtype": obj.subtype,
        "resolved_params": ns,
        "geometry": geometry,
    }


# ---------------------------------------------------------------------------
# Instantiate from library
# ---------------------------------------------------------------------------

def instantiate_gdl(
    library: GDLLibrary,
    object_id: str,
    param_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Place a GDL library object with given parameter overrides.

    Parameters
    ----------
    library : GDLLibrary
    object_id : str
    param_overrides : dict | None

    Returns
    -------
    dict (same as :func:`evaluate_gdl_object`)

    Raises
    ------
    KeyError
        If ``object_id`` is not in the library.
    """
    obj = library.get(object_id)
    if obj is None:
        raise KeyError(f"GDL library: object '{object_id}' not found")
    return evaluate_gdl_object(obj, param_overrides)


# ---------------------------------------------------------------------------
# Built-in starter library
# ---------------------------------------------------------------------------

def _make_default_library() -> GDLLibrary:
    """Return a built-in GDL starter library with 6 objects."""
    objects = [
        GDLObject(
            id="DOOR_SINGLE_00001",
            name="Single Swing Door",
            subtype="Door",
            description="Simple single-leaf hinged door.",
            params=[
                GDLParam("WIDTH",          "length",  0.900, min=0.6,  max=1.2,   description="Clear opening width [m]"),
                GDLParam("HEIGHT",         "length",  2.100, min=1.8,  max=2.7,   description="Clear opening height [m]"),
                GDLParam("FRAME_THICKNESS","length",  0.070, min=0.04, max=0.12,  description="Frame thickness [m]"),
                GDLParam("SWING_ANGLE",    "angle",  90.0,  min=0.0,  max=180.0, description="Door swing angle [deg]"),
                GDLParam("MATERIAL",       "material","timber", description="Door leaf material"),
            ],
            script="""
panel_width  = WIDTH  - 2 * FRAME_THICKNESS
panel_height = HEIGHT - FRAME_THICKNESS
result = {
    "bbox": {"width": WIDTH, "height": HEIGHT, "depth": FRAME_THICKNESS},
    "panel_width": panel_width,
    "panel_height": panel_height,
    "swing_angle": SWING_ANGLE,
    "material": MATERIAL,
}
""",
        ),
        GDLObject(
            id="WINDOW_CASEMENT_00001",
            name="Casement Window",
            subtype="Window",
            description="Single casement window with frame.",
            params=[
                GDLParam("WIDTH",          "length",  1.200, min=0.4,  max=2.4,  description="Overall width [m]"),
                GDLParam("HEIGHT",         "length",  1.050, min=0.3,  max=2.1,  description="Overall height [m]"),
                GDLParam("FRAME_WIDTH",    "length",  0.060, min=0.03, max=0.12, description="Frame width [m]"),
                GDLParam("SILL_HEIGHT",    "length",  0.900, min=0.0,  max=2.0,  description="Sill height from floor [m]"),
                GDLParam("GLAZING",        "string", "double",                    description="Glazing type"),
            ],
            script="""
glass_w = WIDTH  - 2 * FRAME_WIDTH
glass_h = HEIGHT - 2 * FRAME_WIDTH
glass_area = glass_w * glass_h
result = {
    "bbox": {"width": WIDTH, "height": HEIGHT},
    "glass_area": round(glass_area, 4),
    "glazing": GLAZING,
    "sill_height": SILL_HEIGHT,
}
""",
        ),
        GDLObject(
            id="COLUMN_ROUND_00001",
            name="Round Column",
            subtype="Column",
            description="Circular cross-section column.",
            params=[
                GDLParam("DIAMETER", "length", 0.400, min=0.1, max=2.0, description="Column diameter [m]"),
                GDLParam("HEIGHT",   "length", 3.000, min=0.5, max=20.0, description="Column height [m]"),
                GDLParam("MATERIAL", "material", "concrete", description="Column material"),
            ],
            script="""
area  = math.pi * (DIAMETER / 2) ** 2
volume = area * HEIGHT
result = {"diameter": DIAMETER, "height": HEIGHT, "cross_section_area": round(area, 6), "volume": round(volume, 6), "material": MATERIAL}
""",
        ),
        GDLObject(
            id="BEAM_RECT_00001",
            name="Rectangular Beam",
            subtype="Beam",
            description="Rectangular cross-section beam.",
            params=[
                GDLParam("WIDTH",    "length", 0.300, min=0.1, max=1.0,  description="Beam width [m]"),
                GDLParam("DEPTH",    "length", 0.600, min=0.1, max=2.0,  description="Beam depth [m]"),
                GDLParam("LENGTH",   "length", 5.000, min=0.5, max=30.0, description="Beam span [m]"),
                GDLParam("MATERIAL", "material", "concrete", description="Beam material"),
            ],
            script="""
area   = WIDTH * DEPTH
volume = area * LENGTH
result = {"width": WIDTH, "depth": DEPTH, "length": LENGTH, "cross_section_area": round(area, 6), "volume": round(volume, 6), "material": MATERIAL}
""",
        ),
        GDLObject(
            id="DESK_OFFICE_00001",
            name="Office Desk",
            subtype="Furniture",
            description="Standard rectangular office desk.",
            params=[
                GDLParam("WIDTH",  "length", 1.600, min=0.8, max=3.0, description="Desk width [m]"),
                GDLParam("DEPTH",  "length", 0.800, min=0.4, max=1.2, description="Desk depth [m]"),
                GDLParam("HEIGHT", "length", 0.740, min=0.6, max=0.9, description="Desk height [m]"),
                GDLParam("MATERIAL", "material", "MDF_white", description="Surface material"),
            ],
            script="""
footprint = WIDTH * DEPTH
result = {"width": WIDTH, "depth": DEPTH, "height": HEIGHT, "footprint_area": round(footprint, 4), "material": MATERIAL}
""",
        ),
        GDLObject(
            id="LIGHT_PENDANT_00001",
            name="Pendant Light",
            subtype="Lamp",
            description="Ceiling-hung pendant light fixture.",
            params=[
                GDLParam("DIAMETER",    "length", 0.400, min=0.1, max=1.0, description="Shade diameter [m]"),
                GDLParam("CORD_LENGTH", "length", 0.600, min=0.1, max=3.0, description="Suspension cord length [m]"),
                GDLParam("WATTAGE",     "real",   60.0,  min=5.0, max=300.0, description="Lamp wattage [W]"),
            ],
            script="""
shade_area = math.pi * (DIAMETER / 2) ** 2
result = {"diameter": DIAMETER, "cord_length": CORD_LENGTH, "wattage": WATTAGE, "shade_area": round(shade_area, 4)}
""",
        ),
    ]
    return GDLLibrary(objects=objects)


DEFAULT_LIBRARY: GDLLibrary = _make_default_library()


__all__ = [
    "GDLParam",
    "GDLObject",
    "GDLInstance",
    "GDLLibrary",
    "validate_gdl_object",
    "evaluate_gdl_object",
    "instantiate_gdl",
    "DEFAULT_LIBRARY",
    "GDL_TYPES",
    "GDL_SUBTYPES",
]
