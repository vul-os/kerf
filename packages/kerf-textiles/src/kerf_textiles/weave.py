"""
kerf_textiles.weave
===================
Parametric woven-structure generators.

Supported structures
--------------------
- PlainWeave      — interlacement repeat 1×1
- TwillWeave      — N/M right-hand or left-hand diagonal (e.g. 2/1 RH)
- SatinWeave      — regular satin with configurable shaft count + move number
- JacquardWeave   — arbitrary structure from a binary draft matrix

All generators produce:
  * ``cell_matrix``   — 2-D numpy-like (list-of-lists) bool array where
                        True = warp thread is over weft at that intersection.
  * ``float_lengths`` — warp/weft float-length distribution (analytic + sampled)
  * ``vector_paths``  — list of (x, y, "over"|"under") tuples for SVG/vector export
  * ``tile_raster``   — 2-D bool array suitable for tileable PNG preview

Float-length analytic formula
------------------------------
For an (n_warp_up / n_warp_down) balanced weave repeat of size R:
  mean_float_warp = R / n_interlacement_per_repeat_row
  mean_float_weft = R / n_interlacement_per_repeat_col

Plain weave (1/1):  mean_float = 1  (every thread alternates)
2/1 twill:          warp mean_float = 2 (over 2 weft before interlacing once)
                    weft mean_float = 1
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_run_lengths_wrapping(seq: list[bool]) -> list[int]:
    """
    Return consecutive-True run lengths in *seq*, treating it as a circular
    (wrap-around) sequence — i.e. the last element is adjacent to the first.

    This is the correct model for a weave repeat that tiles seamlessly:
    a warp thread that goes over at the end of the repeat and also over at
    the start is actually one continuous float.

    Algorithm
    ---------
    1. Find all contiguous True-runs in the linear sequence.
    2. If the first element AND last element are both True, the first and last
       runs are actually one wrap-around run — merge them.
    """
    n = len(seq)
    if n == 0:
        return []

    # Collect linear runs as (start_index, length)
    runs: list[int] = []
    cur = 0
    for v in seq:
        if v:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)

    if not runs:
        return []

    # If sequence starts with True (first run) AND ends with True (last run),
    # the two boundary runs form a single circular run — merge them.
    if seq[0] and seq[-1] and len(runs) >= 2:
        merged = runs[0] + runs[-1]
        # Replace: remove first and last, add merged at end (or beginning)
        runs = [merged] + runs[1:-1]

    return runs


def _float_stats(matrix: list[list[bool]]) -> dict:
    """
    Compute warp and weft mean float lengths from a cell matrix.

    Uses wrap-around (circular) run counting because the repeat tiles
    seamlessly — the boundary between the last and first row/column is
    not a real boundary in the fabric.
    """
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0

    # Warp floats: consecutive True values *down a column* (warp direction)
    warp_runs: list[int] = []
    for c in range(cols):
        col = [matrix[r][c] for r in range(rows)]
        warp_runs.extend(_count_run_lengths_wrapping(col))

    # Weft floats: consecutive *False* values along a row (weft on top = not True)
    weft_runs: list[int] = []
    for r in range(rows):
        row = [not matrix[r][c] for c in range(cols)]
        weft_runs.extend(_count_run_lengths_wrapping(row))

    def _mean(lst: list[int]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "warp_mean_float": _mean(warp_runs),
        "weft_mean_float": _mean(weft_runs),
        "warp_runs": warp_runs,
        "weft_runs": weft_runs,
    }


def _tile_raster(matrix: list[list[bool]], repeat_x: int = 4, repeat_y: int = 4) -> list[list[bool]]:
    """Tile *matrix* repeat_x × repeat_y times for preview."""
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    tiled: list[list[bool]] = []
    for ty in range(repeat_y):
        for r in range(rows):
            tiled_row: list[bool] = []
            for tx in range(repeat_x):
                tiled_row.extend(matrix[r])
            tiled.append(tiled_row)
    return tiled


def _vector_paths(matrix: list[list[bool]]) -> list[tuple[int, int, str]]:
    """Return (col, row, 'over'|'under') for every cell — enough for SVG rendering."""
    paths: list[tuple[int, int, str]] = []
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            paths.append((c, r, "over" if val else "under"))
    return paths


# ---------------------------------------------------------------------------
# Public structures
# ---------------------------------------------------------------------------

@dataclass
class WeaveResult:
    """Unified result returned by every weave generator."""
    name: str
    repeat_warp: int
    repeat_weft: int
    cell_matrix: list[list[bool]]          # True = warp over weft
    float_stats: dict
    vector_paths: list[tuple[int, int, str]]
    tile_raster: list[list[bool]]
    # Analytic expected values stored for test oracles
    analytic_warp_mean_float: float = 0.0
    analytic_weft_mean_float: float = 0.0


# ---------------------------------------------------------------------------
# Plain weave
# ---------------------------------------------------------------------------

def plain_weave(repeat: int = 2) -> WeaveResult:
    """
    Generate a plain (tabby) weave.

    The repeat size is always 2×2.  The *repeat* argument is accepted for
    API symmetry but the structure is fixed: warp over on (r+c) even.

    Analytic float lengths:
        warp_mean_float = 1.0
        weft_mean_float = 1.0
    """
    r = 2  # plain weave always has a 2×2 repeat
    matrix = [
        [(row + col) % 2 == 0 for col in range(r)]
        for row in range(r)
    ]
    stats = _float_stats(matrix)
    return WeaveResult(
        name="plain",
        repeat_warp=r,
        repeat_weft=r,
        cell_matrix=matrix,
        float_stats=stats,
        vector_paths=_vector_paths(matrix),
        tile_raster=_tile_raster(matrix),
        analytic_warp_mean_float=1.0,
        analytic_weft_mean_float=1.0,
    )


# ---------------------------------------------------------------------------
# Twill weave
# ---------------------------------------------------------------------------

def twill_weave(
    over: int = 2,
    under: int = 1,
    direction: Literal["RH", "LH"] = "RH",
) -> WeaveResult:
    """
    Generate an *over/under* twill.

    Parameters
    ----------
    over:       number of warp-up picks before going under
    under:      number of warp-down picks
    direction:  "RH" (right-hand, positive diagonal) or "LH" (left-hand)

    Repeat size = over + under.

    Analytic float lengths
    ----------------------
    warp_mean_float  = over          (each warp thread floats over *over* wefts)
    weft_mean_float  = under         (each weft thread floats under *under* warps)

    For 2/1 twill: warp_mean=2, weft_mean=1.
    """
    if over < 1 or under < 1:
        raise ValueError("over and under must both be ≥ 1")
    repeat = over + under
    step = 1 if direction == "RH" else -1

    matrix: list[list[bool]] = []
    for row in range(repeat):
        offset = (row * step) % repeat
        row_cells: list[bool] = []
        for col in range(repeat):
            pos = (col - offset) % repeat
            row_cells.append(pos < over)
        matrix.append(row_cells)

    stats = _float_stats(matrix)
    return WeaveResult(
        name=f"twill_{over}_{under}_{direction}",
        repeat_warp=repeat,
        repeat_weft=repeat,
        cell_matrix=matrix,
        float_stats=stats,
        vector_paths=_vector_paths(matrix),
        tile_raster=_tile_raster(matrix),
        analytic_warp_mean_float=float(over),
        analytic_weft_mean_float=float(under),
    )


# ---------------------------------------------------------------------------
# Satin weave
# ---------------------------------------------------------------------------

def satin_weave(shafts: int = 5, move: int = 2) -> WeaveResult:
    """
    Generate a regular satin with *shafts* and move number *move*.

    The move number determines the stagger between rows: each successive warp
    end is lifted *move* picks later.  Valid: gcd(shafts, move) == 1 and
    1 < move < shafts - 1.

    Repeat size = shafts × shafts.

    Analytic float lengths
    ----------------------
    warp_mean_float = shafts - 1   (one interlacement per repeat row)
    weft_mean_float = shafts - 1
    """
    if shafts < 4:
        raise ValueError("satin requires at least 4 shafts")
    if math.gcd(shafts, move) != 1:
        raise ValueError(f"gcd(shafts={shafts}, move={move}) must be 1")
    if not (1 < move < shafts - 1):
        raise ValueError(f"move={move} must satisfy 1 < move < shafts-1={shafts - 1}")

    # Warp-faced satin: every cell is warp-over EXCEPT one per column.
    # The single interlacement per warp end (the one False per column) is
    # staggered by `move` picks between successive warp ends.
    # Column c has warp-under (False) at row = (c * move) % shafts.
    matrix: list[list[bool]] = [
        [True] * shafts for _ in range(shafts)
    ]
    for col in range(shafts):
        row_under = (col * move) % shafts
        matrix[row_under][col] = False

    stats = _float_stats(matrix)
    return WeaveResult(
        name=f"satin_{shafts}_move{move}",
        repeat_warp=shafts,
        repeat_weft=shafts,
        cell_matrix=matrix,
        float_stats=stats,
        vector_paths=_vector_paths(matrix),
        tile_raster=_tile_raster(matrix),
        # Warp-faced satin: warp floats are long (shafts-1), weft floats are 1.
        analytic_warp_mean_float=float(shafts - 1),
        analytic_weft_mean_float=1.0,
    )


# ---------------------------------------------------------------------------
# Jacquard from draft
# ---------------------------------------------------------------------------

def jacquard_from_draft(
    threading: list[int],
    treadling: list[int],
    tie_up: list[list[bool]],
) -> WeaveResult:
    """
    Produce a weave structure from a loom draft.

    Parameters
    ----------
    threading : list[int]
        For each warp end (column), which shaft (0-indexed) it is threaded on.
        Length = number of warp ends = repeat_warp.
    treadling : list[int]
        For each pick (row), which treadle (0-indexed) is pressed.
        Length = number of picks = repeat_weft.
    tie_up : list[list[bool]]
        tie_up[shaft][treadle] = True means pressing that treadle lifts that shaft.
        Shape: n_shafts × n_treadles.

    Returns a WeaveResult with the derived cell matrix.
    """
    n_warps = len(threading)
    n_picks = len(treadling)
    n_shafts = len(tie_up)
    n_treadles = len(tie_up[0]) if tie_up else 0

    if n_warps == 0 or n_picks == 0:
        raise ValueError("threading and treadling must be non-empty")

    matrix: list[list[bool]] = []
    for pick_idx in range(n_picks):
        treadle = treadling[pick_idx]
        if treadle < 0 or treadle >= n_treadles:
            raise ValueError(f"treadle index {treadle} out of range (n_treadles={n_treadles})")
        row: list[bool] = []
        for warp_idx in range(n_warps):
            shaft = threading[warp_idx]
            if shaft < 0 or shaft >= n_shafts:
                raise ValueError(f"shaft index {shaft} out of range (n_shafts={n_shafts})")
            # warp is over weft if tie_up connects shaft to treadle
            row.append(tie_up[shaft][treadle])
        matrix.append(row)

    stats = _float_stats(matrix)
    return WeaveResult(
        name="jacquard",
        repeat_warp=n_warps,
        repeat_weft=n_picks,
        cell_matrix=matrix,
        float_stats=stats,
        vector_paths=_vector_paths(matrix),
        tile_raster=_tile_raster(matrix, repeat_x=2, repeat_y=2),
    )
