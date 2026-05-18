"""
kerf_bim.grid — Structural axis grid (T-113).

Provides a ``StructuralGrid`` that defines a regular or irregular column/beam
layout grid of named axes (like Revit's Grid / Level system and Tekla Structures
grids).  Grid intersections define column and beam snap points used by
:mod:`kerf_bim.framing`.

Reference
---------
Autodesk Revit 2024 — Structural Grids and Levels.
Tekla Structures — Grid Properties.
ISO 16739-1:2018 — ``IfcGrid``, ``IfcGridAxis``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "GridAxis",
    "StructuralGrid",
    "GridValidationError",
    "make_grid",
    "make_regular_grid",
    "grid_to_ifc_dict",
]


class GridValidationError(ValueError):
    """Raised on invalid grid configuration."""


# ---------------------------------------------------------------------------
# GridAxis
# ---------------------------------------------------------------------------

@dataclass
class GridAxis:
    """A single named grid axis (column or row line).

    Parameters
    ----------
    name:
        Axis label (e.g. ``"A"``, ``"1"``).
    coordinate:
        Position along the perpendicular axis (mm).  For X-parallel axes
        (rows) this is the Y coordinate; for Y-parallel axes (columns)
        this is the X coordinate.
    is_column_axis:
        ``True`` → axis is a vertical column line (parallel to Y in plan).
        ``False`` → axis is a horizontal row line (parallel to X in plan).
    """
    name: str
    coordinate: float        # mm
    is_column_axis: bool = True   # True = column grid (vertical), False = beam/row grid

    def __post_init__(self) -> None:
        if not self.name:
            raise GridValidationError("GridAxis name must be non-empty")


# ---------------------------------------------------------------------------
# StructuralGrid
# ---------------------------------------------------------------------------

@dataclass
class StructuralGrid:
    """A 2-D structural axis grid for snap-based column / beam placement.

    Axes are split into two groups:
    - **column_axes** (default: named with letters A, B, C…): X-coordinate lines.
    - **row_axes** (default: named 1, 2, 3…): Y-coordinate lines.

    The grid defines an ordered set of intersections at every
    (column_axis, row_axis) pair.

    Parameters
    ----------
    name:
        Grid name (e.g. ``"Grid A"``).
    column_axes:
        Vertical (X-position) axes in plan.
    row_axes:
        Horizontal (Y-position) axes in plan.
    origin:
        ``[x, y]`` origin offset of the grid in project space (mm).
    rotation_deg:
        Grid rotation in degrees from project North.
    """
    name: str
    column_axes: List[GridAxis] = field(default_factory=list)
    row_axes: List[GridAxis] = field(default_factory=list)
    origin: List[float] = field(default_factory=lambda: [0.0, 0.0])
    rotation_deg: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise GridValidationError("StructuralGrid name must be non-empty")
        if len(self.origin) < 2:
            self.origin = list(self.origin) + [0.0] * (2 - len(self.origin))

    # ---- intersection lookup -----------------------------------------------

    def intersections(self) -> List[Tuple[str, str, float, float]]:
        """Return all (col_name, row_name, x_mm, y_mm) intersection tuples.

        The returned coordinates are in project space (origin applied,
        but rotation is stored separately and applied by the placer).
        """
        pts: List[Tuple[str, str, float, float]] = []
        ox, oy = self.origin[0], self.origin[1]
        for ca in self.column_axes:
            for ra in self.row_axes:
                # column_axis.coordinate = X position; row_axis.coordinate = Y position
                x = ox + ca.coordinate
                y = oy + ra.coordinate
                pts.append((ca.name, ra.name, x, y))
        return pts

    def intersection(self, col_name: str, row_name: str) -> Tuple[float, float]:
        """Return the (x, y) mm coordinates of a named grid intersection.

        Raises :class:`GridValidationError` if either axis is not found.
        """
        ca = next((a for a in self.column_axes if a.name == col_name), None)
        ra = next((a for a in self.row_axes if a.name == row_name), None)
        if ca is None:
            raise GridValidationError(f"Column axis '{col_name}' not found in grid '{self.name}'")
        if ra is None:
            raise GridValidationError(f"Row axis '{row_name}' not found in grid '{self.name}'")
        ox, oy = self.origin[0], self.origin[1]
        return ox + ca.coordinate, oy + ra.coordinate

    # ---- dimensions --------------------------------------------------------

    @property
    def bay_widths(self) -> List[float]:
        """Sorted list of X-direction bay widths (mm) between adjacent column axes."""
        coords = sorted(a.coordinate for a in self.column_axes)
        return [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]

    @property
    def bay_depths(self) -> List[float]:
        """Sorted list of Y-direction bay depths (mm) between adjacent row axes."""
        coords = sorted(a.coordinate for a in self.row_axes)
        return [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]

    def axis_names(self) -> Dict[str, List[str]]:
        """Return ``{"columns": [...], "rows": [...]}`` axis name lists."""
        return {
            "columns": [a.name for a in self.column_axes],
            "rows":    [a.name for a in self.row_axes],
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_grid(
    name: str,
    column_positions: List[Tuple[str, float]],
    row_positions: List[Tuple[str, float]],
    origin: Optional[List[float]] = None,
    rotation_deg: float = 0.0,
) -> StructuralGrid:
    """Create a :class:`StructuralGrid` from named position lists.

    Parameters
    ----------
    name:
        Grid name.
    column_positions:
        ``[(axis_name, x_mm), ...]`` — column axes (X coordinates).
    row_positions:
        ``[(axis_name, y_mm), ...]`` — row axes (Y coordinates).
    origin:
        ``[x, y]`` project origin offset (mm).
    rotation_deg:
        Grid rotation in degrees.

    Example::

        grid = make_grid("Main Grid",
            column_positions=[("A", 0), ("B", 7200), ("C", 14400)],
            row_positions=[("1", 0), ("2", 6000), ("3", 12000)],
        )
    """
    from typing import Optional  # noqa
    col_axes = [GridAxis(name=n, coordinate=float(x), is_column_axis=True)
                for n, x in column_positions]
    row_axes = [GridAxis(name=n, coordinate=float(y), is_column_axis=False)
                for n, y in row_positions]
    return StructuralGrid(
        name=name,
        column_axes=col_axes,
        row_axes=row_axes,
        origin=list(origin) if origin else [0.0, 0.0],
        rotation_deg=rotation_deg,
    )


def make_regular_grid(
    name: str = "Regular Grid",
    bays_x: int = 3,
    bay_width: float = 7200.0,
    bays_y: int = 2,
    bay_depth: float = 6000.0,
    origin: Optional[List[float]] = None,
) -> StructuralGrid:
    """Create a regular rectangular grid with equal bay spacings.

    Column axes are labelled A, B, C … (up to Z then AA, AB, …).
    Row axes are labelled 1, 2, 3 …

    Parameters
    ----------
    name:
        Grid name.
    bays_x:
        Number of bays in the X direction.
    bay_width:
        Bay width in mm.
    bays_y:
        Number of bays in the Y direction.
    bay_depth:
        Bay depth in mm.
    origin:
        Grid origin ``[x, y]`` in mm.

    Returns
    -------
    :class:`StructuralGrid`

    Example::

        # 3-bay × 2-bay frame — as required by T-113 DoD
        grid = make_regular_grid(bays_x=3, bay_width=7200, bays_y=2, bay_depth=6000)
    """
    def _col_label(idx: int) -> str:
        """Excel-style column label: 0→A, 1→B, …, 25→Z, 26→AA, …"""
        label = ""
        n = idx
        while True:
            label = chr(ord("A") + n % 26) + label
            n = n // 26 - 1
            if n < 0:
                break
        return label

    col_positions = [(_col_label(i), float(i) * bay_width) for i in range(bays_x + 1)]
    row_positions = [(str(i + 1), float(i) * bay_depth) for i in range(bays_y + 1)]

    return make_grid(
        name=name,
        column_positions=col_positions,
        row_positions=row_positions,
        origin=origin or [0.0, 0.0],
    )


from typing import Optional  # noqa: E402 (already imported above via local scope)


# ---------------------------------------------------------------------------
# IFC dict serialisation
# ---------------------------------------------------------------------------

def grid_to_ifc_dict(grid: StructuralGrid) -> dict:
    """Convert a :class:`StructuralGrid` to an IFC-compatible dict.

    The returned dict carries ``IfcGrid`` metadata (axes + intersections)
    and is consumed by the extended IFC exporter to write ``IfcGrid`` /
    ``IfcGridAxis`` entities.

    Returns::

        {
          "kind":        "grid",
          "name":        str,
          "origin":      [x, y],
          "rotation_deg": float,
          "column_axes": [{"name": str, "coordinate": float}, ...],
          "row_axes":    [{"name": str, "coordinate": float}, ...],
          "intersections": [
            {"col": str, "row": str, "x": float, "y": float}, ...
          ],
        }
    """
    return {
        "kind": "grid",
        "name": grid.name,
        "origin": list(grid.origin),
        "rotation_deg": grid.rotation_deg,
        "column_axes": [
            {"name": a.name, "coordinate": a.coordinate}
            for a in grid.column_axes
        ],
        "row_axes": [
            {"name": a.name, "coordinate": a.coordinate}
            for a in grid.row_axes
        ],
        "intersections": [
            {"col": col, "row": row, "x": x, "y": y}
            for col, row, x, y in grid.intersections()
        ],
    }
