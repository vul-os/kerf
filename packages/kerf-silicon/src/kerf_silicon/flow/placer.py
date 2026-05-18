"""Simple row-based greedy cell placer for tape-out lite.

Mimics the outermost loop of a real IC placer:

  1. Walk cells in netlist order.
  2. Place left-to-right in the current row; start a new row when the
     next cell would exceed die_area width.
  3. Raise ValueError if the die is too small to fit all cells.

All coordinates are in microns (µm).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LefCell:
    """Minimal LEF cell descriptor (width × height in µm).

    A real LEF library carries dozens of attributes; we only need the
    bounding-box to place cells.
    """

    name: str
    width: float   # cell width in µm
    height: float  # cell height in µm (usually == row_height, but not enforced)


@dataclass
class PlacedCell:
    """One cell placed on the die.

    Attributes
    ----------
    instance_name:
        Unique identifier for this cell instance (e.g. ``"U1"``).
    cell_name:
        Name of the cell in the LEF library (e.g. ``"AND2X1"``).
    x, y:
        Lower-left corner of the placed cell in µm.
    width, height:
        Bounding-box dimensions taken from the LEF descriptor.
    """

    instance_name: str
    cell_name: str
    x: float
    y: float
    width: float
    height: float


def place_cells(
    netlist: list[dict[str, Any]],
    lef_library: dict[str, LefCell],
    die_area: tuple[float, float],
    row_height: float = 2.72,
) -> list[PlacedCell]:
    """Place *netlist* cells on a grid using row-based greedy left-to-right.

    Parameters
    ----------
    netlist:
        List of cell-instance dicts.  Each dict must have at minimum::

            {"instance": "<unique name>", "cell": "<lef cell name>"}

        Additional keys (ports, nets, …) are silently ignored.
    lef_library:
        Mapping from cell name → :class:`LefCell`.  Every cell referenced
        in *netlist* must appear here.
    die_area:
        ``(width, height)`` of the rectangular die in µm.
    row_height:
        Height of a placement row in µm.  Defaults to 2.72 µm (a common
        standard-cell library pitch).

    Returns
    -------
    list[PlacedCell]
        Placed instances in netlist order.

    Raises
    ------
    ValueError
        If a cell is not found in *lef_library*, or if the die is too small
        to accommodate all cells (insufficient width on any row *or* height
        for the number of rows needed).
    """
    die_width, die_height = die_area

    placed: list[PlacedCell] = []
    cursor_x: float = 0.0
    cursor_y: float = 0.0

    for entry in netlist:
        instance_name: str = entry["instance"]
        cell_name: str = entry["cell"]

        if cell_name not in lef_library:
            raise ValueError(
                f"Cell '{cell_name}' (instance '{instance_name}') not found "
                f"in LEF library.  Available cells: {sorted(lef_library)}"
            )

        lef_cell = lef_library[cell_name]

        if lef_cell.width > die_width:
            raise ValueError(
                f"Cell '{cell_name}' width {lef_cell.width} µm exceeds die "
                f"width {die_width} µm — cannot fit in any row."
            )

        # Advance to the next row if the cell won't fit horizontally.
        if cursor_x + lef_cell.width > die_width:
            cursor_x = 0.0
            cursor_y += row_height

        # Check vertical headroom *before* placing.
        if cursor_y + lef_cell.height > die_height:
            raise ValueError(
                f"Die area ({die_width} × {die_height} µm) is too small to "
                f"fit all {len(netlist)} cells.  Ran out of vertical space "
                f"while placing '{instance_name}' ({cell_name})."
            )

        placed.append(
            PlacedCell(
                instance_name=instance_name,
                cell_name=cell_name,
                x=cursor_x,
                y=cursor_y,
                width=lef_cell.width,
                height=lef_cell.height,
            )
        )
        cursor_x += lef_cell.width

    return placed
