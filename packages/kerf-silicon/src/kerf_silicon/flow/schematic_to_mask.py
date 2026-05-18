"""Schematic → mask flow: place standard cells and emit GDS-II.

This is the top-level "tape-out lite" orchestrator.  Given a netlist and a
LEF cell library it:

  1. Calls :func:`~kerf_silicon.flow.placer.place_cells` to compute (x, y)
     positions for every cell instance.
  2. Writes a GDS-II file via the T-237 ``kerf_silicon.gds.writer`` module.
     The import is guarded by ``try/except ImportError`` so the rest of the
     flow remains usable even when the GDS writer has not been installed yet.

All coordinates follow the LEF/DEF convention: microns, lower-left origin.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from kerf_silicon.flow.placer import LefCell, PlacedCell, place_cells

# ---------------------------------------------------------------------------
# Optional T-237 GDS writer — import-guarded so the flow still loads without
# it (e.g. in CI environments where only the placer is being tested).
# ---------------------------------------------------------------------------
try:
    from kerf_silicon.gds.writer import GDSWriter as _GDSWriter  # type: ignore[import]

    _HAS_GDS_WRITER = True
except ImportError:
    _GDSWriter = None  # type: ignore[assignment,misc]
    _HAS_GDS_WRITER = False


# ---------------------------------------------------------------------------
# Default die area used when the caller does not supply one.
# 100 × 100 µm — a sensible "thumbnail" die for small demo netlists.
# ---------------------------------------------------------------------------
_DEFAULT_DIE_AREA: tuple[float, float] = (100.0, 100.0)

# GDS database units: 1 internal unit = 1 nm (1e-9 m), 1 µm = 1000 units.
_GDS_UNITS_PER_UM: int = 1000


def _write_gds_fallback(
    placed: list[PlacedCell],
    output_path: str | os.PathLike[str],
    die_area: tuple[float, float],
) -> None:
    """Minimal pure-Python GDS-II writer used when T-237 is unavailable.

    Emits a structurally valid GDS-II stream containing:

    - A single top cell named ``TOP``.
    - One SREF (structure reference) per placed cell, pointing to the LEF
      cell name.  The SREF coordinates are in GDS database units (nm).
    - A BOUNDARY record for the die outline (layer 0, datatype 0).

    This is intentionally minimal — no actual cell geometry is written for
    the referenced sub-structures because LEF cells are defined externally.
    The output is suitable for import into any GDS viewer that honours SREFs.
    """
    import struct
    import datetime

    def _record(tag: int, data: bytes = b"") -> bytes:
        length = 4 + len(data)
        return struct.pack(">HH", length, tag) + data

    def _int2(values: list[int]) -> bytes:
        return struct.pack(f">{len(values)}h", *values)

    def _int4(values: list[int]) -> bytes:
        return struct.pack(f">{len(values)}i", *values)

    def _string(s: str) -> bytes:
        b = s.encode("ascii")
        if len(b) % 2:
            b += b"\x00"
        return b

    def _real8(value: float) -> bytes:
        """Convert a Python float to GDS-II 8-byte real (IBM hex float)."""
        if value == 0.0:
            return b"\x00" * 8
        import math

        sign = 0
        if value < 0:
            sign = 1
            value = -value
        exp = math.floor(math.log(value, 16)) + 1
        mantissa = value / (16.0 ** exp)
        mantissa_int = int(mantissa * (16 ** 14))
        exp_byte = exp + 64
        result = ((sign << 7) | exp_byte).to_bytes(1, "big")
        result += mantissa_int.to_bytes(7, "big")
        return result

    # --- GDS tokens ---
    HEADER = 0x0002
    BGNLIB = 0x0102
    LIBNAME = 0x0206
    UNITS = 0x0305
    ENDLIB = 0x0400
    BGNSTR = 0x0502
    STRNAME = 0x0606
    ENDSTR = 0x0700
    BOUNDARY = 0x0800
    SREF = 0x0A00
    SNAME = 0x0A06
    XY = 0x1003
    ENDEL = 0x1100
    LAYER = 0x0D02
    DATATYPE = 0x0E02
    MAG = 0x1B05
    ANGLE = 0x1C05

    now = datetime.datetime.now()
    ts = [now.year - 1900, now.month, now.day, now.hour, now.minute, now.second] * 2

    buf = bytearray()

    # Header
    buf += _record(HEADER, _int2([600]))
    buf += _record(BGNLIB, _int2(ts))
    buf += _record(LIBNAME, _string("KERF_SILICON"))
    # UNITS: 1 db unit = 1e-9 m (1 nm); user unit = 1 µm
    buf += _record(UNITS, _real8(1e-3) + _real8(1e-9))

    # Top structure
    buf += _record(BGNSTR, _int2(ts))
    buf += _record(STRNAME, _string("TOP"))

    # Die outline boundary
    dw = int(die_area[0] * _GDS_UNITS_PER_UM)
    dh = int(die_area[1] * _GDS_UNITS_PER_UM)
    die_xy = [0, 0, dw, 0, dw, dh, 0, dh, 0, 0]
    buf += _record(BOUNDARY)
    buf += _record(LAYER, _int2([0]))
    buf += _record(DATATYPE, _int2([0]))
    buf += _record(XY, _int4(die_xy))
    buf += _record(ENDEL)

    # SREFs for each placed cell
    for pc in placed:
        gx = int(pc.x * _GDS_UNITS_PER_UM)
        gy = int(pc.y * _GDS_UNITS_PER_UM)
        buf += _record(SREF)
        buf += _record(SNAME, _string(pc.cell_name))
        buf += _record(XY, _int4([gx, gy]))
        buf += _record(ENDEL)

    buf += _record(ENDSTR)
    buf += _record(ENDLIB)

    Path(output_path).write_bytes(bytes(buf))


def schematic_to_gds(
    netlist: list[dict[str, Any]],
    lef_lib: dict[str, LefCell],
    output_path: str | os.PathLike[str],
    *,
    die_area: tuple[float, float] = _DEFAULT_DIE_AREA,
    row_height: float = 2.72,
) -> list[PlacedCell]:
    """Convert a netlist to a GDS-II mask file.

    This is the main entry-point for the tape-out lite flow.

    Parameters
    ----------
    netlist:
        List of ``{"instance": str, "cell": str, …}`` dicts describing the
        circuit.  Only ``"instance"`` and ``"cell"`` keys are consumed here;
        all others are forwarded unchanged to the placer.
    lef_lib:
        Mapping from cell name → :class:`~kerf_silicon.flow.placer.LefCell`.
    output_path:
        Destination path for the ``.gds`` file.  Parent directories must
        already exist.
    die_area:
        ``(width, height)`` of the die in µm.  Defaults to 100 × 100 µm.
    row_height:
        Placement-row pitch in µm (default 2.72 µm).

    Returns
    -------
    list[PlacedCell]
        The placed-cell list produced by the placer (useful for inspection /
        downstream routing in a future phase).

    Raises
    ------
    ValueError
        Propagated from :func:`~kerf_silicon.flow.placer.place_cells` when
        the die is too small or a cell is missing from the library.
    """
    placed = place_cells(netlist, lef_lib, die_area, row_height=row_height)

    output_path = Path(output_path)

    if _HAS_GDS_WRITER:
        # Use the full T-237 GDS writer when available.
        writer = _GDSWriter(str(output_path))
        writer.begin_library("KERF_SILICON")
        writer.begin_structure("TOP")
        for pc in placed:
            writer.add_sref(
                cell_name=pc.cell_name,
                x=int(pc.x * _GDS_UNITS_PER_UM),
                y=int(pc.y * _GDS_UNITS_PER_UM),
            )
        writer.end_structure()
        writer.end_library()
    else:
        # Fall back to the built-in minimal writer.
        _write_gds_fallback(placed, output_path, die_area)

    return placed
