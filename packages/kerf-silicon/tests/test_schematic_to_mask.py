"""Tests for the kerf-silicon schematic → mask (tape-out lite) flow.

Coverage
--------
1. 3-cell synthetic netlist places without overlap.
2. All placed cells remain within die_area bounds.
3. Output GDS path exists after schematic_to_gds (mocked T-237 writer path +
   built-in fallback writer path).
4. Placer raises ValueError for a netlist whose cells don't fit in die_area.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kerf_silicon.flow.placer import LefCell, PlacedCell, place_cells
from kerf_silicon.flow.schematic_to_mask import schematic_to_gds


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def small_lef_lib() -> dict[str, LefCell]:
    """A tiny LEF library with three standard cells of different widths."""
    return {
        "AND2X1": LefCell(name="AND2X1", width=2.0, height=2.72),
        "INV1X1": LefCell(name="INV1X1", width=1.0, height=2.72),
        "OR2X1":  LefCell(name="OR2X1",  width=2.5, height=2.72),
    }


@pytest.fixture()
def three_cell_netlist() -> list[dict[str, Any]]:
    """Three-cell synthetic netlist (one of each cell type)."""
    return [
        {"instance": "U1", "cell": "AND2X1"},
        {"instance": "U2", "cell": "INV1X1"},
        {"instance": "U3", "cell": "OR2X1"},
    ]


# ---------------------------------------------------------------------------
# 1. Three-cell placement — no overlaps
# ---------------------------------------------------------------------------


def test_three_cells_no_overlap(
    three_cell_netlist: list[dict[str, Any]],
    small_lef_lib: dict[str, LefCell],
) -> None:
    """All three placed cells must have non-overlapping bounding boxes."""
    die_area = (20.0, 10.0)
    placed = place_cells(three_cell_netlist, small_lef_lib, die_area)

    assert len(placed) == 3

    # Check every pair for axis-aligned bounding-box overlap.
    for i, a in enumerate(placed):
        for j, b in enumerate(placed):
            if i >= j:
                continue
            # Two rectangles overlap iff they overlap on BOTH axes.
            x_overlap = (a.x < b.x + b.width) and (b.x < a.x + a.width)
            y_overlap = (a.y < b.y + b.height) and (b.y < a.y + a.height)
            assert not (x_overlap and y_overlap), (
                f"Cells {a.instance_name} and {b.instance_name} overlap: "
                f"{a} vs {b}"
            )


# ---------------------------------------------------------------------------
# 2. All cells within die_area
# ---------------------------------------------------------------------------


def test_all_cells_within_die_area(
    three_cell_netlist: list[dict[str, Any]],
    small_lef_lib: dict[str, LefCell],
) -> None:
    """Every placed cell must lie fully inside the die bounding box."""
    die_area = (20.0, 10.0)
    placed = place_cells(three_cell_netlist, small_lef_lib, die_area)

    for pc in placed:
        assert pc.x >= 0.0, f"{pc.instance_name}: x={pc.x} < 0"
        assert pc.y >= 0.0, f"{pc.instance_name}: y={pc.y} < 0"
        assert pc.x + pc.width <= die_area[0] + 1e-9, (
            f"{pc.instance_name}: right edge {pc.x + pc.width} > die width {die_area[0]}"
        )
        assert pc.y + pc.height <= die_area[1] + 1e-9, (
            f"{pc.instance_name}: top edge {pc.y + pc.height} > die height {die_area[1]}"
        )


# ---------------------------------------------------------------------------
# 3a. GDS output path exists — fallback writer (no T-237 installed)
# ---------------------------------------------------------------------------


def test_schematic_to_gds_creates_file_fallback(
    tmp_path: Path,
    three_cell_netlist: list[dict[str, Any]],
    small_lef_lib: dict[str, LefCell],
) -> None:
    """schematic_to_gds must create the output file via the built-in writer."""
    out = tmp_path / "out.gds"

    # Ensure T-237 GDS writer is NOT used (simulate absent optional dep).
    with patch(
        "kerf_silicon.flow.schematic_to_mask._HAS_GDS_WRITER",
        False,
    ):
        placed = schematic_to_gds(
            three_cell_netlist,
            small_lef_lib,
            out,
            die_area=(20.0, 10.0),
        )

    assert out.exists(), "GDS output file was not created"
    assert out.stat().st_size > 0, "GDS output file is empty"
    assert len(placed) == 3


def test_schematic_to_gds_creates_file_fallback_content(
    tmp_path: Path,
    three_cell_netlist: list[dict[str, Any]],
    small_lef_lib: dict[str, LefCell],
) -> None:
    """The fallback writer must produce a file beginning with a valid GDS HEADER record."""
    out = tmp_path / "out_content.gds"

    with patch(
        "kerf_silicon.flow.schematic_to_mask._HAS_GDS_WRITER",
        False,
    ):
        schematic_to_gds(
            three_cell_netlist,
            small_lef_lib,
            out,
            die_area=(20.0, 10.0),
        )

    data = out.read_bytes()
    # GDS HEADER record: first 2 bytes = record length (6), next 2 = tag 0x0002
    assert len(data) >= 6, "GDS file too short"
    _length, tag = struct.unpack(">HH", data[:4])
    assert tag == 0x0002, f"Expected GDS HEADER tag 0x0002, got 0x{tag:04x}"


# ---------------------------------------------------------------------------
# 3b. GDS output path exists — mocked T-237 writer
# ---------------------------------------------------------------------------


def test_schematic_to_gds_uses_t237_writer_when_available(
    tmp_path: Path,
    three_cell_netlist: list[dict[str, Any]],
    small_lef_lib: dict[str, LefCell],
) -> None:
    """When T-237 writer is present it is used and the output path is created."""
    out = tmp_path / "out_t237.gds"

    mock_writer_instance = MagicMock()

    # Make the mock write an empty file so Path.exists() is True.
    def _fake_begin_library(name: str) -> None:
        out.write_bytes(b"GDS_MOCK")

    mock_writer_instance.begin_library.side_effect = _fake_begin_library

    MockGDSWriter = MagicMock(return_value=mock_writer_instance)

    with (
        patch("kerf_silicon.flow.schematic_to_mask._HAS_GDS_WRITER", True),
        patch("kerf_silicon.flow.schematic_to_mask._GDSWriter", MockGDSWriter),
    ):
        placed = schematic_to_gds(
            three_cell_netlist,
            small_lef_lib,
            out,
            die_area=(20.0, 10.0),
        )

    # Writer must have been instantiated with the output path.
    MockGDSWriter.assert_called_once_with(str(out))

    # Standard lifecycle calls must appear.
    mock_writer_instance.begin_library.assert_called_once_with("KERF_SILICON")
    mock_writer_instance.begin_structure.assert_called_once_with("TOP")
    assert mock_writer_instance.add_sref.call_count == 3
    mock_writer_instance.end_structure.assert_called_once()
    mock_writer_instance.end_library.assert_called_once()

    assert out.exists()
    assert len(placed) == 3


# ---------------------------------------------------------------------------
# 4. Placer rejects netlist that doesn't fit in die_area
# ---------------------------------------------------------------------------


def test_placer_rejects_netlist_too_wide_for_die(
    small_lef_lib: dict[str, LefCell],
) -> None:
    """A single cell wider than die_area width must raise ValueError."""
    netlist = [{"instance": "U1", "cell": "OR2X1"}]  # OR2X1 width = 2.5 µm
    die_area = (1.0, 10.0)  # only 1 µm wide — too narrow

    with pytest.raises(ValueError, match="width"):
        place_cells(netlist, small_lef_lib, die_area)


def test_placer_rejects_netlist_too_tall_for_die(
    small_lef_lib: dict[str, LefCell],
) -> None:
    """Many cells that need more rows than available height must raise ValueError."""
    # AND2X1 is 2.0 µm wide; die is 3.0 µm wide → max 1 cell per row.
    # With row_height=2.72 and die_height=5.44, we can fit exactly 2 rows (2 cells).
    # Adding a 3rd cell should overflow.
    netlist = [
        {"instance": "U1", "cell": "AND2X1"},
        {"instance": "U2", "cell": "AND2X1"},
        {"instance": "U3", "cell": "AND2X1"},
    ]
    die_area = (3.0, 5.44)  # exactly 2 rows, 1 cell each

    with pytest.raises(ValueError, match="too small"):
        place_cells(netlist, small_lef_lib, die_area)


def test_placer_rejects_unknown_cell(
    small_lef_lib: dict[str, LefCell],
) -> None:
    """A cell name absent from the LEF library must raise ValueError."""
    netlist = [{"instance": "U1", "cell": "NAND3X99"}]
    die_area = (20.0, 20.0)

    with pytest.raises(ValueError, match="not found in LEF library"):
        place_cells(netlist, small_lef_lib, die_area)


# ---------------------------------------------------------------------------
# 5. Row wrapping — cells correctly advance to the next row
# ---------------------------------------------------------------------------


def test_row_wrap(small_lef_lib: dict[str, LefCell]) -> None:
    """Cells that don't fit horizontally must start a new row."""
    # Die is 3.0 µm wide. AND2X1 = 2.0 µm, INV1X1 = 1.0 µm.
    # Row 0: AND2X1 (x=0..2), INV1X1 (x=2..3) → fits exactly.
    # Row 1: AND2X1 (x=0..2) — next row because only 0 µm left after first row is full.
    netlist = [
        {"instance": "U1", "cell": "AND2X1"},
        {"instance": "U2", "cell": "INV1X1"},
        {"instance": "U3", "cell": "AND2X1"},
    ]
    die_area = (3.0, 20.0)
    placed = place_cells(netlist, small_lef_lib, die_area)

    assert placed[0].y == pytest.approx(0.0)
    assert placed[1].y == pytest.approx(0.0)
    assert placed[2].y == pytest.approx(2.72)  # second row
    assert placed[2].x == pytest.approx(0.0)   # back to left edge
