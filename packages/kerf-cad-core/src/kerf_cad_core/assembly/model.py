"""
kerf_cad_core.assembly.model — Component and Assembly data model.

Coordinate conventions
----------------------
- Units: mm
- Right-handed coordinate system (X right, Y forward, Z up)
- Transforms: 4x4 homogeneous matrices represented as flat list[float] of
  length 16 in row-major order:
      index 0..3   = row 0  (rotation + scale, x-component of translation at 3)
      index 4..7   = row 1
      index 8..11  = row 2
      index 12..15 = row 3  (perspective row, always [0,0,0,1] for rigid body)

  World point = T @ local_point   where T is the component's transform.

Identity transform = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
"""

from __future__ import annotations

import copy
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Tiny pure-Python 4×4 matrix helper
# ---------------------------------------------------------------------------

def _identity() -> list[float]:
    """Return a 4×4 identity matrix as flat list[float] (row-major)."""
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _mat_mul(a: list[float], b: list[float]) -> list[float]:
    """Multiply two 4×4 row-major matrices.  c = a @ b."""
    c = [0.0] * 16
    for row in range(4):
        for col in range(4):
            s = 0.0
            for k in range(4):
                s += a[row * 4 + k] * b[k * 4 + col]
            c[row * 4 + col] = s
    return c


def _transform_point(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    """Apply a 4×4 homogeneous transform to a 3-D point."""
    x, y, z = p
    w = m[12] * x + m[13] * y + m[14] * z + m[15]
    xo = (m[0] * x + m[1] * y + m[2] * z + m[3]) / w
    yo = (m[4] * x + m[5] * y + m[6] * z + m[7]) / w
    zo = (m[8] * x + m[9] * y + m[10] * z + m[11]) / w
    return (xo, yo, zo)


def _transform_vector(m: list[float], v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Apply a 4×4 transform to a free vector (ignores translation row)."""
    x, y, z = v
    xo = m[0] * x + m[1] * y + m[2] * z
    yo = m[4] * x + m[5] * y + m[6] * z
    zo = m[8] * x + m[9] * y + m[10] * z
    return (xo, yo, zo)


def _validate_transform(t: Any) -> list[float]:
    """Validate and coerce a transform to list[float] of length 16."""
    if t is None:
        return _identity()
    try:
        flat = [float(v) for v in t]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"transform must be a list of 16 numbers: {exc}") from exc
    if len(flat) != 16:
        raise ValueError(f"transform must have exactly 16 elements, got {len(flat)}")
    return flat


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

class Component:
    """
    A single instance of a part placed in an assembly.

    Attributes
    ----------
    instance_id : str
        Unique identifier for this placed instance (auto-generated UUID4).
    part_ref : str
        Reference to the part definition (file id, part number, or name).
        Does not need to exist in the DB — the assembly layer is purely
        geometric; it does not touch files.
    transform : list[float]
        4×4 homogeneous transform (row-major, 16 floats) placing this
        instance in the assembly's world coordinate frame.
    name : str | None
        Optional human-readable name.
    """

    __slots__ = ("instance_id", "part_ref", "transform", "name")

    def __init__(
        self,
        part_ref: str,
        transform: list[float] | None = None,
        name: str | None = None,
        instance_id: str | None = None,
    ) -> None:
        if not part_ref or not str(part_ref).strip():
            raise ValueError("part_ref must be a non-empty string")
        self.part_ref = str(part_ref).strip()
        self.transform: list[float] = _validate_transform(transform)
        self.name = name
        self.instance_id: str = instance_id or str(uuid.uuid4())

    # ---- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "part_ref": self.part_ref,
            "transform": self.transform,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Component":
        return cls(
            part_ref=d["part_ref"],
            transform=d.get("transform"),
            name=d.get("name"),
            instance_id=d.get("instance_id"),
        )

    def __repr__(self) -> str:
        return f"Component(instance_id={self.instance_id!r}, part_ref={self.part_ref!r})"


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

class Assembly:
    """
    A tree of placed component instances with optional sub-assemblies.

    Each top-level entry in ``components`` is a leaf component (a part
    instance).  Sub-assemblies are modelled by nesting Assembly objects
    inside the ``sub_assemblies`` list.

    The assembly does **not** hold mate/constraint data — those are stored
    in the mate list passed to ``solve_assembly`` (see mates.py).

    Attributes
    ----------
    assembly_id : str
        Unique identifier (auto-generated UUID4).
    name : str
        Human-readable name.
    components : list[Component]
        Direct part instances placed in this assembly.
    sub_assemblies : list[Assembly]
        Nested sub-assemblies (for BOM tree building).
    """

    def __init__(
        self,
        name: str = "assembly",
        assembly_id: str | None = None,
    ) -> None:
        self.assembly_id: str = assembly_id or str(uuid.uuid4())
        self.name: str = name
        self.components: list[Component] = []
        self.sub_assemblies: list["Assembly"] = []

    # ---- mutation ------------------------------------------------------------

    def add_component(self, component: Component) -> None:
        """Add a component instance.  Duplicate instance_ids are rejected."""
        existing = {c.instance_id for c in self.components}
        if component.instance_id in existing:
            raise ValueError(
                f"instance_id '{component.instance_id}' already present in assembly"
            )
        self.components.append(component)

    def add_sub_assembly(self, sub: "Assembly") -> None:
        """Nest a sub-assembly."""
        self.sub_assemblies.append(sub)

    def get_component(self, instance_id: str) -> Component | None:
        """Look up a component by instance_id (direct children only)."""
        for c in self.components:
            if c.instance_id == instance_id:
                return c
        return None

    def all_components(self) -> list[Component]:
        """Return all components: direct children + all sub-assembly children."""
        result = list(self.components)
        for sub in self.sub_assemblies:
            result.extend(sub.all_components())
        return result

    # ---- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "assembly_id": self.assembly_id,
            "name": self.name,
            "components": [c.to_dict() for c in self.components],
            "sub_assemblies": [s.to_dict() for s in self.sub_assemblies],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Assembly":
        asm = cls(name=d.get("name", "assembly"), assembly_id=d.get("assembly_id"))
        for cd in d.get("components", []):
            asm.components.append(Component.from_dict(cd))
        for sd in d.get("sub_assemblies", []):
            asm.sub_assemblies.append(Assembly.from_dict(sd))
        return asm

    def __repr__(self) -> str:
        return (
            f"Assembly(assembly_id={self.assembly_id!r}, name={self.name!r}, "
            f"components={len(self.components)})"
        )


# Re-export matrix helpers so tests and tools can use them without circular imports.
__all__ = [
    "Assembly",
    "Component",
    "_identity",
    "_mat_mul",
    "_transform_point",
    "_transform_vector",
    "_validate_transform",
]
