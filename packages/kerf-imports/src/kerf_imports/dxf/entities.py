"""
entities.py — DXF intermediate entity model (T-5).

All coordinates in the DXF file's native units (usually mm or inches).
Z coordinates are preserved on 3-D entities but the mapper projects to XY.

Supported entity types:
  LINE        — two endpoints
  LWPOLYLINE  — R2000+ compact polyline (group code 10/20 pairs)
  POLYLINE    — R12 polyline with VERTEX records
  CIRCLE      — center + radius
  ARC         — center + radius + start/end angles (counter-clockwise)
  TEXT        — single-line text (also handles MTEXT as plain text)
  INSERT      — block reference (position, scale, rotation, block_name)
  BLOCK       — block definition (entities nested inside)

Not supported (silently skipped): DIMENSION, HATCH, SOLID, 3DFACE, SPLINE,
ELLIPSE, LEADER, MLINE, etc.  Callers receive a ``warnings`` list noting
every skipped entity type encountered.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DxfLine:
    """LINE entity."""
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "0"
    handle: str = ""


@dataclass
class DxfLwPolyline:
    """LWPOLYLINE entity (R2000+).

    ``points`` is a list of [x, y] pairs.
    ``bulge`` is a parallel list of bulge values (0.0 = straight segment).
    """
    points: list[list[float]]
    closed: bool = False
    layer: str = "0"
    handle: str = ""
    bulge: list[float] = field(default_factory=list)

    def __post_init__(self):
        # Ensure bulge list length matches points
        if len(self.bulge) < len(self.points):
            self.bulge.extend([0.0] * (len(self.points) - len(self.bulge)))


@dataclass
class DxfPolyline:
    """R12 POLYLINE entity (VERTEX/SEQEND form)."""
    points: list[list[float]]
    closed: bool = False
    layer: str = "0"
    handle: str = ""
    bulge: list[float] = field(default_factory=list)

    def __post_init__(self):
        if len(self.bulge) < len(self.points):
            self.bulge.extend([0.0] * (len(self.points) - len(self.bulge)))


@dataclass
class DxfCircle:
    """CIRCLE entity."""
    cx: float
    cy: float
    radius: float
    layer: str = "0"
    handle: str = ""


@dataclass
class DxfArc:
    """ARC entity.

    Angles in degrees, counter-clockwise from the positive X axis,
    matching DXF group codes 50/51.
    """
    cx: float
    cy: float
    radius: float
    start_angle: float
    end_angle: float
    layer: str = "0"
    handle: str = ""


@dataclass
class DxfText:
    """TEXT (or MTEXT) entity — single insertion point + string value."""
    x: float
    y: float
    value: str
    height: float = 2.5
    rotation: float = 0.0
    layer: str = "0"
    handle: str = ""


@dataclass
class DxfInsert:
    """INSERT entity — a block reference.

    ``block_name`` references a ``DxfBlock`` in the same ``DxfDocument``.
    Transformation: scale first, then rotate by ``rotation_deg``, then
    translate to ``(x, y)``.
    """
    block_name: str
    x: float
    y: float
    x_scale: float = 1.0
    y_scale: float = 1.0
    rotation_deg: float = 0.0
    layer: str = "0"
    handle: str = ""


# Type alias for the entity union
DxfEntity = DxfLine | DxfLwPolyline | DxfPolyline | DxfCircle | DxfArc | DxfText | DxfInsert


@dataclass
class DxfBlock:
    """BLOCK definition — a named collection of entities."""
    name: str
    base_x: float = 0.0
    base_y: float = 0.0
    entities: list[DxfEntity] = field(default_factory=list)
    layer: str = "0"


@dataclass
class DxfDocument:
    """Top-level document — entities in model space + block table."""
    entities: list[DxfEntity] = field(default_factory=list)
    blocks: dict[str, DxfBlock] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    units: str = "mm"  # best-effort from $INSUNITS header variable

    # $INSUNITS → human-readable label (DXF spec table 2)
    _INSUNITS: dict[int, str] = field(default_factory=lambda: {
        0: "unitless",
        1: "inches",
        2: "feet",
        4: "mm",
        5: "cm",
        6: "m",
        8: "microinches",
        10: "yards",
        14: "decimeters",
        15: "dekameters",
        16: "hectometers",
        17: "km",
        18: "US survey feet",
        19: "US survey inches",
        20: "parsecs",
        21: "light years",
    })

    def all_entities_flat(self) -> list[DxfEntity]:
        """Return model-space entities with INSERT references NOT expanded.

        Use ``expand_inserts()`` for a flat list with block content inlined.
        """
        return list(self.entities)

    def expand_inserts(
        self,
        max_depth: int = 8,
    ) -> list[DxfEntity]:
        """Return a flat list of primitives with all INSERTs expanded.

        Block references are expanded by applying the INSERT transform
        (scale + rotate + translate) to each sub-entity.  Nested blocks
        are expanded recursively up to *max_depth*.

        Entities that cannot be transformed (e.g. another INSERT) are
        returned as-is at the transformed origin.
        """
        out: list[DxfEntity] = []
        self._expand_list(self.entities, out, 1.0, 0.0, 0.0, 0.0, max_depth)
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _expand_list(
        self,
        ents: list[DxfEntity],
        out: list[DxfEntity],
        sx: float,
        sy: float,
        tx: float,
        ty: float,
        depth: int,
    ) -> None:
        for e in ents:
            if isinstance(e, DxfInsert):
                if depth <= 0:
                    self.warnings.append(
                        f"INSERT '{e.block_name}': max nesting depth reached — skipped"
                    )
                    continue
                block = self.blocks.get(e.block_name)
                if block is None:
                    self.warnings.append(
                        f"INSERT '{e.block_name}': block not found — skipped"
                    )
                    continue
                # Compose transforms: scale by INSERT's scale factors, rotate,
                # then translate to INSERT origin.
                rad = math.radians(e.rotation_deg)
                cos_r, sin_r = math.cos(rad), math.sin(rad)

                def _xform(px: float, py: float) -> tuple[float, float]:
                    # Apply block-base offset first, then scale, then rotate, then translate
                    bpx = (px - block.base_x) * e.x_scale * sx
                    bpy = (py - block.base_y) * e.y_scale * sy
                    rx = bpx * cos_r - bpy * sin_r
                    ry = bpx * sin_r + bpy * cos_r
                    return rx + tx + e.x, ry + ty + e.y

                self._expand_list(block.entities, out, e.x_scale * sx, e.y_scale * sy,
                                  tx + e.x, ty + e.y, depth - 1)
            else:
                out.append(e)
