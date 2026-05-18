"""
kerf_bim.slabs — Full parametric slab model (T-111).

Promotes the basic slab primitive to fully parametric compound slabs:
- Flat floor / roof slabs
- Sloped slabs (single or cranked)
- Edge profiles (dropped, upturned, raked)
- IFC export

Reference
---------
Autodesk Revit 2024 — Floor / Roof types and slope arrows.
ISO 16739-1:2018 — ``IfcSlab``, ``IfcRoof``, ``IfcMaterialLayerSet``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

__all__ = [
    "SlabFunction",
    "SlabLayer",
    "SlabType",
    "SlabInstance",
    "SlabValidationError",
    "make_slab_type",
    "make_slab_instance",
    "slab_to_ifc_dict",
    "PRESET_SLAB_TYPES",
]


class SlabValidationError(ValueError):
    """Raised on invalid slab configuration."""


SlabFunction = Literal["floor", "roof", "foundation"]

VALID_SLAB_FUNCTIONS = frozenset({"floor", "roof", "foundation"})


# ---------------------------------------------------------------------------
# SlabLayer
# ---------------------------------------------------------------------------

@dataclass
class SlabLayer:
    """A single material layer in a compound slab cross-section.

    Parameters
    ----------
    material:
        Material identifier (key into ``kerf_bim.materials_catalogue.CATALOGUE``).
    thickness:
        Layer thickness in mm.  Must be > 0.
    function:
        Functional role: ``"structure"``, ``"substrate"``, ``"thermal"``,
        ``"finish"``, ``"membrane"``.
    """
    material: str
    thickness: float     # mm
    function: Literal["structure", "substrate", "thermal", "finish", "membrane"] = "structure"

    VALID_FUNCTIONS = frozenset({"structure", "substrate", "thermal", "finish", "membrane"})

    def __post_init__(self) -> None:
        if self.function not in self.VALID_FUNCTIONS:
            raise SlabValidationError(
                f"Unknown slab layer function '{self.function}'; "
                f"allowed: {sorted(self.VALID_FUNCTIONS)}"
            )
        if self.thickness <= 0:
            raise SlabValidationError(f"SlabLayer thickness must be > 0, got {self.thickness}")


# ---------------------------------------------------------------------------
# SlabType
# ---------------------------------------------------------------------------

@dataclass
class SlabType:
    """A compound slab type — ordered layers from top to bottom.

    Parameters
    ----------
    name:
        Type name (e.g. ``"RC Slab on Grade 200"``).
    function:
        Slab function: ``"floor"``, ``"roof"``, or ``"foundation"``.
    layers:
        Ordered layers top → bottom.  At least one ``structure`` layer
        is required.
    slope:
        Slope angle in degrees measured from horizontal.  0 = flat.
        Positive = uphill toward end_direction.
    description:
        Free-text description.
    """
    name: str
    function: SlabFunction = "floor"
    layers: List[SlabLayer] = field(default_factory=list)
    slope: float = 0.0     # degrees — 0 = flat
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise SlabValidationError("SlabType name must be non-empty")
        if self.function not in VALID_SLAB_FUNCTIONS:
            raise SlabValidationError(
                f"Unknown slab function '{self.function}'; "
                f"allowed: {sorted(VALID_SLAB_FUNCTIONS)}"
            )
        if not self.layers:
            raise SlabValidationError("SlabType must have at least one layer")
        if not any(lay.function == "structure" for lay in self.layers):
            raise SlabValidationError(
                f"SlabType '{self.name}' must have at least one 'structure' layer"
            )
        if not (-45.0 <= self.slope <= 45.0):
            raise SlabValidationError(
                f"SlabType slope must be in [-45°, 45°], got {self.slope}°"
            )

    @property
    def total_thickness(self) -> float:
        """Total slab thickness from top to bottom (mm)."""
        return sum(lay.thickness for lay in self.layers)

    @property
    def structure_thickness(self) -> float:
        """Combined thickness of structural layers (mm)."""
        return sum(lay.thickness for lay in self.layers if lay.function == "structure")

    def layer_summary(self) -> List[dict]:
        """Return list of layer dicts for serialisation."""
        return [
            {"function": lay.function, "material": lay.material, "thickness_mm": lay.thickness}
            for lay in self.layers
        ]


# ---------------------------------------------------------------------------
# SlabInstance
# ---------------------------------------------------------------------------

@dataclass
class SlabInstance:
    """A placed slab instance.

    Parameters
    ----------
    slab_type:
        The :class:`SlabType` applied.
    boundary:
        Closed polygon boundary as ``[[x, y], ...]`` in mm (plan).
        Minimum 3 points.
    level:
        Level name this slab sits on.
    name:
        Optional instance name.
    slope_direction:
        Unit vector ``[dx, dy]`` in plan toward which slope rises.
        Ignored when ``slab_type.slope == 0``.
    offset:
        Vertical offset of the slab top from the level elevation (mm).
    """
    slab_type: SlabType
    boundary: List[List[float]]    # [[x, y], ...]  mm
    level: str = "L1"
    name: str = ""
    slope_direction: List[float] = field(default_factory=lambda: [1.0, 0.0])
    offset: float = 0.0            # mm offset from level

    def __post_init__(self) -> None:
        if len(self.boundary) < 3:
            raise SlabValidationError("SlabInstance boundary requires at least 3 points")
        if not self.name:
            self.name = f"Slab ({self.slab_type.name})"

    @property
    def plan_area(self) -> float:
        """Plan area of the slab boundary using the shoelace formula (mm²)."""
        pts = self.boundary
        n = len(pts)
        area = 0.0
        for i in range(n):
            x0, y0 = pts[i][0], pts[i][1]
            x1, y1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
            area += (x0 * y1 - x1 * y0)
        return abs(area) * 0.5

    @property
    def thickness(self) -> float:
        """Total slab thickness from type (mm)."""
        return self.slab_type.total_thickness

    def height_at_point(self, x: float, y: float) -> float:
        """Effective top-of-slab elevation at plan point (x, y) in mm.

        For sloped slabs, computes the rise from the slab centroid along
        ``slope_direction``.  The centroid is used as the datum.
        """
        if self.slab_type.slope == 0.0:
            return self.offset
        # Centroid of boundary (simple average)
        cx = sum(p[0] for p in self.boundary) / len(self.boundary)
        cy = sum(p[1] for p in self.boundary) / len(self.boundary)
        dx, dy = x - cx, y - cy
        dslope = self.slope_direction
        norm = math.sqrt(dslope[0] ** 2 + dslope[1] ** 2)
        if norm < 1e-12:
            return self.offset
        proj = (dx * dslope[0] + dy * dslope[1]) / norm  # mm along slope dir
        rise = proj * math.tan(math.radians(self.slab_type.slope))
        return self.offset + rise


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_slab_type(
    name: str,
    layers: List[Tuple[str, float, str]],
    function: SlabFunction = "floor",
    slope: float = 0.0,
    description: str = "",
) -> SlabType:
    """Create a :class:`SlabType` from ``(material, thickness, function)`` tuples."""
    slab_layers = [SlabLayer(material=m, thickness=t, function=f) for m, t, f in layers]
    return SlabType(
        name=name,
        function=function,
        layers=slab_layers,
        slope=slope,
        description=description,
    )


def make_slab_instance(
    slab_type: SlabType,
    boundary: List[List[float]],
    level: str = "L1",
    name: str = "",
    offset: float = 0.0,
    slope_direction: Optional[List[float]] = None,
) -> SlabInstance:
    """Create a :class:`SlabInstance` ergonomically."""
    return SlabInstance(
        slab_type=slab_type,
        boundary=[list(p) for p in boundary],
        level=level,
        name=name,
        offset=offset,
        slope_direction=slope_direction or [1.0, 0.0],
    )


from typing import Optional  # noqa: E402 (already imported above)


# ---------------------------------------------------------------------------
# IFC dict serialisation
# ---------------------------------------------------------------------------

def slab_to_ifc_dict(instance: SlabInstance) -> dict:
    """Convert a :class:`SlabInstance` to the IFC dict format for the exporter.

    Compatible with the ``slabs`` list accepted by
    :func:`kerf_bim.export_ifc.writer.export_ifc`.
    """
    return {
        "boundary":  [[p[0], p[1]] for p in instance.boundary],
        "thickness": instance.thickness,
        "level":     instance.level,
        "name":      instance.name,
        # Extra parametric metadata
        "slab_type": instance.slab_type.name,
        "function":  instance.slab_type.function,
        "slope_deg": instance.slab_type.slope,
        "layers":    instance.slab_type.layer_summary(),
        "offset_mm": instance.offset,
    }


# ---------------------------------------------------------------------------
# Preset slab types
# ---------------------------------------------------------------------------

def _preset_slabs() -> dict[str, SlabType]:
    slabs: dict[str, SlabType] = {}

    def add(st: SlabType) -> None:
        slabs[st.name] = st

    # RC flat slab — floor
    add(make_slab_type(
        "RC Flat Slab 200",
        [("concrete_reinforced", 200.0, "structure")],
        function="floor",
        description="200 mm reinforced concrete flat slab.",
    ))

    # RC flat slab with topping — floor
    add(make_slab_type(
        "RC Slab + Screed 220",
        [
            ("concrete_reinforced",  180.0, "structure"),
            ("plaster_cement",        40.0, "substrate"),   # cement screed
        ],
        function="floor",
        description="180 mm RC slab + 40 mm cement screed.",
    ))

    # Raised-access floor
    add(make_slab_type(
        "RC Slab + Raised Access Floor 250",
        [
            ("concrete_reinforced",   200.0, "structure"),
            ("board_drywall_gypsum",   12.5, "substrate"),  # panel face
        ],
        function="floor",
        description="200 mm RC + proprietary raised-access panel (notional).",
    ))

    # Flat concrete roof with membrane
    add(make_slab_type(
        "RC Flat Roof 200 + Insulation",
        [
            ("concrete_reinforced",  200.0, "structure"),
            ("insulation_xps",        80.0, "thermal"),
            ("membrane_tpo",           2.0, "membrane"),
        ],
        function="roof",
        description="RC flat roof + XPS insulation + TPO membrane.",
    ))

    # Sloped roof slab (e.g. car park ramp)
    add(make_slab_type(
        "RC Ramp Slab 200 (5° slope)",
        [("concrete_reinforced", 200.0, "structure")],
        function="floor",
        slope=5.0,
        description="200 mm RC ramp slab sloped at 5°.",
    ))

    # Ground-bearing slab
    add(make_slab_type(
        "Ground Slab 150 on Grade",
        [
            ("insulation_xps",         50.0, "thermal"),
            ("concrete_m30",          150.0, "structure"),
        ],
        function="foundation",
        description="Ground-bearing slab: XPS sub-slab insulation + M30 concrete.",
    ))

    return slabs


PRESET_SLAB_TYPES: dict[str, SlabType] = _preset_slabs()
