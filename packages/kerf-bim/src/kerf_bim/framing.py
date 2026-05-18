"""
kerf_bim.framing — Structural framing snapped to a grid (T-113).

Provides column and beam placement snapped to a :class:`~kerf_bim.grid.StructuralGrid`,
connection node generation, and rebar attachment — matching the scope of
Revit Structure / Autodesk Robot / Tekla Structures.

IFC mapping
-----------
Columns → ``IfcColumn``; Beams → ``IfcBeam``; Connections → informational
``IfcStructuralPointConnection``; Rebar → ``IfcReinforcingBar``.

Reference
---------
Autodesk Revit 2024 — Structural Framing and Columns.
ISO 16739-1:2018 — ``IfcColumn``, ``IfcBeam``, ``IfcReinforcingBar``,
``IfcStructuralPointConnection``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from kerf_bim.grid import StructuralGrid, GridValidationError

__all__ = [
    "ColumnMember",
    "BeamMember",
    "ConnectionNode",
    "RebarAttachment",
    "FramingLayout",
    "FramingValidationError",
    "make_column_at",
    "make_beam_between",
    "make_frame_on_grid",
    "framing_to_ifc_dict",
]


class FramingValidationError(ValueError):
    """Raised when framing geometry is invalid."""


# ---------------------------------------------------------------------------
# Column
# ---------------------------------------------------------------------------

@dataclass
class ColumnMember:
    """A structural column snapped to a grid intersection.

    Parameters
    ----------
    id:
        Unique member identifier.
    grid_col:
        Column-axis name (e.g. ``"A"``).
    grid_row:
        Row-axis name (e.g. ``"1"``).
    x, y:
        Plan position in mm (from grid intersection).
    base_level:
        Level name at base of column.
    top_level:
        Level name at top of column.
    height_mm:
        Column height (mm).
    section:
        Section designation string (e.g. ``"W250x73"`` or ``"400×400"``).
    material:
        Material id (from catalogue).
    width_mm, depth_mm:
        Section width and depth in mm.
    has_base_plate:
        Whether a base plate is modelled.
    rebar:
        Optional rebar attachment for concrete columns.
    """
    id: str
    grid_col: str
    grid_row: str
    x: float                   # mm
    y: float                   # mm
    base_level: str = "L1"
    top_level: str = "L2"
    height_mm: float = 3600.0
    section: str = "W250x73"
    material: str = "steel_s355"
    width_mm: float = 254.0
    depth_mm: float = 253.0
    has_base_plate: bool = True
    rebar: Optional["RebarAttachment"] = None


@dataclass
class BeamMember:
    """A structural beam spanning between two grid intersections.

    Parameters
    ----------
    id:
        Unique member identifier.
    start_col, start_row:
        Grid intersection at the start (I-end) of the beam.
    end_col, end_row:
        Grid intersection at the end (J-end) of the beam.
    start_pt, end_pt:
        Plan positions in mm (derived from grid lookup by
        :func:`make_frame_on_grid`; can be set directly).
    level:
        Level name of the beam.
    section:
        Section designation string.
    material:
        Material id.
    width_mm, depth_mm:
        Section dimensions in mm.
    camber_mm:
        Fabricated camber (mm).
    """
    id: str
    start_col: str
    start_row: str
    end_col: str
    end_row: str
    start_pt: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    end_pt: List[float] = field(default_factory=lambda: [7200.0, 0.0, 0.0])
    level: str = "L1"
    section: str = "W360x51"
    material: str = "steel_s355"
    width_mm: float = 140.0
    depth_mm: float = 355.0
    camber_mm: float = 0.0

    @property
    def length_mm(self) -> float:
        dx = self.end_pt[0] - self.start_pt[0]
        dy = self.end_pt[1] - self.start_pt[1]
        dz = self.end_pt[2] - self.start_pt[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass
class ConnectionNode:
    """A structural connection point at a grid intersection / beam end.

    Minimal representation — carries position and connected member IDs
    for informational export to ``IfcStructuralPointConnection``.
    """
    id: str
    position: List[float]       # [x, y, z] mm
    member_ids: List[str] = field(default_factory=list)


@dataclass
class RebarAttachment:
    """Rebar specification attached to a concrete column or beam.

    Parameters
    ----------
    bar_count:
        Number of main longitudinal bars.
    bar_diameter_mm:
        Diameter of main bars in mm.
    tie_spacing_mm:
        Tie/stirrup spacing in mm.
    cover_mm:
        Concrete cover to rebar (mm).
    """
    bar_count: int = 8
    bar_diameter_mm: float = 20.0
    tie_spacing_mm: float = 200.0
    cover_mm: float = 40.0

    def designation(self) -> str:
        """Human-readable designation, e.g. ``"8T20 @ 200 c/c"``."""
        return f"{self.bar_count}T{int(self.bar_diameter_mm)} @ {int(self.tie_spacing_mm)} c/c"


# ---------------------------------------------------------------------------
# FramingLayout — the complete structural frame
# ---------------------------------------------------------------------------

@dataclass
class FramingLayout:
    """A complete structural frame layout for one or more storeys.

    Parameters
    ----------
    name:
        Layout name.
    grid:
        The axis grid this frame is snapped to.
    columns:
        All :class:`ColumnMember` instances.
    beams:
        All :class:`BeamMember` instances.
    connections:
        :class:`ConnectionNode` objects (auto-generated by
        :func:`make_frame_on_grid`).
    """
    name: str
    grid: StructuralGrid
    columns: List[ColumnMember] = field(default_factory=list)
    beams: List[BeamMember] = field(default_factory=list)
    connections: List[ConnectionNode] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_column_at(
    grid: StructuralGrid,
    col_axis: str,
    row_axis: str,
    height_mm: float = 3600.0,
    base_level: str = "L1",
    top_level: str = "L2",
    section: str = "W250x73",
    material: str = "steel_s355",
    width_mm: float = 254.0,
    depth_mm: float = 253.0,
    column_id: Optional[str] = None,
) -> ColumnMember:
    """Create a :class:`ColumnMember` snapped to a named grid intersection.

    Raises :class:`FramingValidationError` if the axis names are not in
    the grid.
    """
    try:
        x, y = grid.intersection(col_axis, row_axis)
    except GridValidationError as exc:
        raise FramingValidationError(str(exc)) from exc

    cid = column_id or f"COL-{col_axis}{row_axis}"
    return ColumnMember(
        id=cid,
        grid_col=col_axis,
        grid_row=row_axis,
        x=x,
        y=y,
        base_level=base_level,
        top_level=top_level,
        height_mm=height_mm,
        section=section,
        material=material,
        width_mm=width_mm,
        depth_mm=depth_mm,
    )


def make_beam_between(
    grid: StructuralGrid,
    start_col: str, start_row: str,
    end_col: str, end_row: str,
    level: str = "L1",
    level_z_mm: float = 0.0,
    section: str = "W360x51",
    material: str = "steel_s355",
    width_mm: float = 140.0,
    depth_mm: float = 355.0,
    beam_id: Optional[str] = None,
) -> BeamMember:
    """Create a :class:`BeamMember` spanning between two grid intersections."""
    try:
        sx, sy = grid.intersection(start_col, start_row)
        ex, ey = grid.intersection(end_col, end_row)
    except GridValidationError as exc:
        raise FramingValidationError(str(exc)) from exc

    bid = beam_id or f"BM-{start_col}{start_row}-{end_col}{end_row}"
    return BeamMember(
        id=bid,
        start_col=start_col,
        start_row=start_row,
        end_col=end_col,
        end_row=end_row,
        start_pt=[sx, sy, level_z_mm],
        end_pt=[ex, ey, level_z_mm],
        level=level,
        section=section,
        material=material,
        width_mm=width_mm,
        depth_mm=depth_mm,
    )


def make_frame_on_grid(
    grid: StructuralGrid,
    storey_heights: List[float],
    column_section: str = "W250x73",
    column_material: str = "steel_s355",
    column_width_mm: float = 254.0,
    column_depth_mm: float = 253.0,
    beam_section: str = "W360x51",
    beam_material: str = "steel_s355",
    beam_width_mm: float = 140.0,
    beam_depth_mm: float = 355.0,
    name: Optional[str] = None,
) -> FramingLayout:
    """Generate a complete multi-storey frame snapped to a grid.

    Creates one column per grid intersection per storey and beams
    connecting every adjacent intersection along X and Y per storey.

    The level elevations are computed from ``storey_heights`` (mm), with
    the ground floor at z = 0 and each subsequent level at the cumulative
    sum of heights.

    Parameters
    ----------
    grid:
        The structural grid.
    storey_heights:
        List of storey heights in mm (one per storey).  The number of
        floors = len(storey_heights); columns span from storey to storey.
    column_section, beam_section:
        Section designations.
    column_material, beam_material:
        Material ids.
    column_width_mm, column_depth_mm, beam_width_mm, beam_depth_mm:
        Section dimensions.
    name:
        Layout name.  Defaults to ``"<grid.name> Frame"``.

    Returns
    -------
    :class:`FramingLayout`

    Example::

        # T-113 DoD: 3-bay × 2-storey frame on a grid
        grid = make_regular_grid(bays_x=3, bay_width=7200, bays_y=2, bay_depth=6000)
        frame = make_frame_on_grid(grid, storey_heights=[3600.0, 3600.0])
    """
    frame_name = name or f"{grid.name} Frame"
    columns: List[ColumnMember] = []
    beams: List[BeamMember] = []
    connections: List[ConnectionNode] = []

    n_storeys = len(storey_heights)
    if n_storeys < 1:
        raise FramingValidationError("storey_heights must have at least one entry")

    # Level elevations: L1 = 0, L2 = h[0], L3 = h[0]+h[1], ...
    level_z: List[float] = [0.0]
    for h in storey_heights:
        level_z.append(level_z[-1] + h)

    level_names = [f"L{i + 1}" for i in range(n_storeys + 1)]

    # Generate columns at every grid intersection for every storey
    for storey_idx, h in enumerate(storey_heights):
        base_level = level_names[storey_idx]
        top_level = level_names[storey_idx + 1]
        base_z = level_z[storey_idx]

        for ca in grid.column_axes:
            for ra in grid.row_axes:
                ox, oy = grid.origin[0], grid.origin[1]
                x = ox + ca.coordinate
                y = oy + ra.coordinate
                cid = f"COL-{ca.name}{ra.name}-S{storey_idx + 1}"
                col = ColumnMember(
                    id=cid,
                    grid_col=ca.name,
                    grid_row=ra.name,
                    x=x,
                    y=y,
                    base_level=base_level,
                    top_level=top_level,
                    height_mm=h,
                    section=column_section,
                    material=column_material,
                    width_mm=column_width_mm,
                    depth_mm=column_depth_mm,
                )
                columns.append(col)

                # Connection node at top of each column
                conn_z = base_z + h
                conn_id = f"CN-{ca.name}{ra.name}-S{storey_idx + 1}"
                conn = ConnectionNode(
                    id=conn_id,
                    position=[x, y, conn_z],
                    member_ids=[cid],
                )
                connections.append(conn)

    # Generate beams at each floor level (top of each storey)
    for storey_idx, h in enumerate(storey_heights):
        level = level_names[storey_idx + 1]
        beam_z = level_z[storey_idx + 1]
        col_axes = grid.column_axes
        row_axes = grid.row_axes

        # X-direction beams: connect adjacent column axes along each row axis
        for ra in row_axes:
            for i in range(len(col_axes) - 1):
                ca_start = col_axes[i]
                ca_end = col_axes[i + 1]
                ox, oy = grid.origin[0], grid.origin[1]
                bid = f"BM-X-{ca_start.name}{ra.name}-{ca_end.name}{ra.name}-S{storey_idx + 1}"
                bm = BeamMember(
                    id=bid,
                    start_col=ca_start.name,
                    start_row=ra.name,
                    end_col=ca_end.name,
                    end_row=ra.name,
                    start_pt=[ox + ca_start.coordinate, oy + ra.coordinate, beam_z],
                    end_pt=[ox + ca_end.coordinate,   oy + ra.coordinate, beam_z],
                    level=level,
                    section=beam_section,
                    material=beam_material,
                    width_mm=beam_width_mm,
                    depth_mm=beam_depth_mm,
                )
                beams.append(bm)

        # Y-direction beams: connect adjacent row axes along each column axis
        for ca in col_axes:
            for i in range(len(row_axes) - 1):
                ra_start = row_axes[i]
                ra_end = row_axes[i + 1]
                ox, oy = grid.origin[0], grid.origin[1]
                bid = f"BM-Y-{ca.name}{ra_start.name}-{ca.name}{ra_end.name}-S{storey_idx + 1}"
                bm = BeamMember(
                    id=bid,
                    start_col=ca.name,
                    start_row=ra_start.name,
                    end_col=ca.name,
                    end_row=ra_end.name,
                    start_pt=[ox + ca.coordinate, oy + ra_start.coordinate, beam_z],
                    end_pt=[ox + ca.coordinate, oy + ra_end.coordinate,   beam_z],
                    level=level,
                    section=beam_section,
                    material=beam_material,
                    width_mm=beam_width_mm,
                    depth_mm=beam_depth_mm,
                )
                beams.append(bm)

    return FramingLayout(
        name=frame_name,
        grid=grid,
        columns=columns,
        beams=beams,
        connections=connections,
    )


# ---------------------------------------------------------------------------
# IFC dict serialisation
# ---------------------------------------------------------------------------

def framing_to_ifc_dict(layout: FramingLayout) -> dict:
    """Convert a :class:`FramingLayout` to the IFC-exporter dict format.

    Returns a dict with:
    - ``columns`` — list of column dicts for the IFC exporter's
      ``columns`` key (compatible with ``_emit_column``).
    - ``beams`` — list of beam dicts for the ``beams`` key.
    - ``connections`` — informational connection-node dicts.
    - Grid metadata for ``IfcGrid`` generation.
    """
    from kerf_bim.grid import grid_to_ifc_dict

    return {
        "kind": "framing",
        "name": layout.name,
        "grid": grid_to_ifc_dict(layout.grid),
        "columns": [
            {
                "name":     col.id,
                "level":    col.base_level,
                "position": [col.x, col.y, 0.0],
                "width":    col.width_mm,
                "depth":    col.depth_mm,
                "height":   col.height_mm,
                "section":  col.section,
                "material": col.material,
                "has_base_plate": col.has_base_plate,
                "rebar":    col.rebar.designation() if col.rebar else None,
            }
            for col in layout.columns
        ],
        "beams": [
            {
                "name":     bm.id,
                "level":    bm.level,
                "start":    list(bm.start_pt),
                "end":      list(bm.end_pt),
                "width":    bm.width_mm,
                "height":   bm.depth_mm,
                "section":  bm.section,
                "material": bm.material,
                "camber_mm": bm.camber_mm,
            }
            for bm in layout.beams
        ],
        "connections": [
            {
                "id":       conn.id,
                "position": list(conn.position),
                "members":  list(conn.member_ids),
            }
            for conn in layout.connections
        ],
    }
