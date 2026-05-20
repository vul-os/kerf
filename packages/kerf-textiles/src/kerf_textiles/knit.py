"""
kerf_textiles.knit
==================
Parametric knit-structure generators.

Supported structures
--------------------
- JerseyKnit       — single jersey (1×1 knit)
- RibKnit          — k×p rib (e.g. 1×1, 2×2)
- InterlockKnit    — interlock (double jersey)
- CustomKnit       — arbitrary stitch notation (loop/tuck/miss) per carrier × course

Stitch notation
---------------
Each cell in the needle×course grid holds one of:
  "loop"   — normal knit stitch (pulls yarn through previous loop)
  "tuck"   — tuck stitch (yarn held, loop not formed, accumulates)
  "miss"   — float / miss stitch (yarn carried across, not knitted)

Gauge + density
---------------
  stitch_density = wales_per_cm × courses_per_cm
  analytic: stitch_density = gauge × courses
  where gauge = needles per cm (typically 1/loop_width_cm)

The jersey-knit stitch density oracle:
  computed_density = wales * courses / (fabric_width_cm * fabric_height_cm)
  must match gauge * courses_per_cm to within 1%.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StitchType = Literal["loop", "tuck", "miss"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _density_stats(
    matrix: list[list[StitchType]],
    gauge: float,            # needles per cm
    courses_per_cm: float,   # courses per cm
) -> dict:
    """Compute stitch density and compare to analytic formula."""
    courses = len(matrix)
    needles = len(matrix[0]) if courses else 0

    # Physical size of the fabric swatch
    fabric_width_cm = needles / gauge if gauge > 0 else 0.0
    fabric_height_cm = courses / courses_per_cm if courses_per_cm > 0 else 0.0

    loop_count = sum(1 for row in matrix for cell in row if cell == "loop")
    tuck_count = sum(1 for row in matrix for cell in row if cell == "tuck")
    miss_count = sum(1 for row in matrix for cell in row if cell == "miss")

    computed_density = (loop_count / (fabric_width_cm * fabric_height_cm)
                        if (fabric_width_cm > 0 and fabric_height_cm > 0) else 0.0)
    analytic_density = gauge * courses_per_cm

    relative_error = (abs(computed_density - analytic_density) / analytic_density
                      if analytic_density > 0 else 0.0)

    return {
        "needles": needles,
        "courses": courses,
        "loop_count": loop_count,
        "tuck_count": tuck_count,
        "miss_count": miss_count,
        "gauge": gauge,
        "courses_per_cm": courses_per_cm,
        "fabric_width_cm": fabric_width_cm,
        "fabric_height_cm": fabric_height_cm,
        "computed_stitch_density": computed_density,
        "analytic_stitch_density": analytic_density,
        "relative_error": relative_error,
        "density_within_1pct": relative_error <= 0.01,
    }


def _tile_raster_knit(matrix: list[list[StitchType]], repeat_x: int = 4, repeat_y: int = 4) -> list[list[StitchType]]:
    """Tile the stitch matrix for a preview."""
    tiled: list[list[StitchType]] = []
    for _ in range(repeat_y):
        for row in matrix:
            tiled.append(row * repeat_x)
    return tiled


# ---------------------------------------------------------------------------
# Public structures
# ---------------------------------------------------------------------------

@dataclass
class KnitResult:
    """Unified result returned by every knit generator."""
    name: str
    repeat_needles: int
    repeat_courses: int
    cell_matrix: list[list[StitchType]]    # [course][needle]
    density_stats: dict
    tile_raster: list[list[StitchType]]


# ---------------------------------------------------------------------------
# Jersey knit
# ---------------------------------------------------------------------------

def jersey_knit(
    needles: int = 10,
    courses: int = 10,
    gauge: float = 5.0,          # needles per cm
    courses_per_cm: float = 7.0, # courses per cm
) -> KnitResult:
    """
    Single jersey: all loops on every needle every course.

    Stitch density = gauge × courses_per_cm (all cells are "loop").

    The oracle: computed_density == gauge * courses_per_cm to within 1%.
    """
    matrix: list[list[StitchType]] = [
        ["loop"] * needles for _ in range(courses)
    ]
    stats = _density_stats(matrix, gauge, courses_per_cm)
    return KnitResult(
        name="jersey",
        repeat_needles=1,
        repeat_courses=1,
        cell_matrix=matrix,
        density_stats=stats,
        tile_raster=_tile_raster_knit([["loop"]], repeat_x=needles, repeat_y=courses),
    )


# ---------------------------------------------------------------------------
# Rib knit
# ---------------------------------------------------------------------------

def rib_knit(
    knit_count: int = 1,
    purl_count: int = 1,
    needles: int = 8,
    courses: int = 8,
    gauge: float = 5.0,
    courses_per_cm: float = 7.0,
) -> KnitResult:
    """
    k×p rib structure.

    On a flat representation the "purl" needle columns are represented as
    "miss" (they are knitted on the opposite bed in a real double-bed machine,
    but in a 2D flat view they appear as held/miss on the face).

    Parameters
    ----------
    knit_count:  number of consecutive knit needles
    purl_count:  number of consecutive purl needles
    """
    repeat = knit_count + purl_count
    repeat_row: list[StitchType] = (
        ["loop"] * knit_count + ["miss"] * purl_count
    )
    full_repeat = repeat_row * (needles // repeat) + repeat_row[: needles % repeat]
    matrix: list[list[StitchType]] = [list(full_repeat) for _ in range(courses)]

    stats = _density_stats(matrix, gauge, courses_per_cm)
    return KnitResult(
        name=f"rib_{knit_count}x{purl_count}",
        repeat_needles=repeat,
        repeat_courses=1,
        cell_matrix=matrix,
        density_stats=stats,
        tile_raster=_tile_raster_knit([list(repeat_row)]),
    )


# ---------------------------------------------------------------------------
# Interlock knit
# ---------------------------------------------------------------------------

def interlock_knit(
    needles: int = 8,
    courses: int = 8,
    gauge: float = 5.0,
    courses_per_cm: float = 7.0,
) -> KnitResult:
    """
    Interlock (double jersey): two interlocked 1×1 rib courses.

    Course 0: loop miss loop miss ...  (bed A)
    Course 1: miss loop miss loop ...  (bed B)

    Both courses contribute loops so density = gauge × courses_per_cm for
    the combined fabric (all physical positions produce a loop somewhere).
    """
    row_a: list[StitchType] = ["loop" if c % 2 == 0 else "miss" for c in range(needles)]
    row_b: list[StitchType] = ["miss" if c % 2 == 0 else "loop" for c in range(needles)]

    # Build alternating courses
    matrix: list[list[StitchType]] = []
    for course in range(courses):
        matrix.append(list(row_a if course % 2 == 0 else row_b))

    stats = _density_stats(matrix, gauge, courses_per_cm)
    return KnitResult(
        name="interlock",
        repeat_needles=2,
        repeat_courses=2,
        cell_matrix=matrix,
        density_stats=stats,
        tile_raster=_tile_raster_knit([list(row_a), list(row_b)]),
    )


# ---------------------------------------------------------------------------
# Custom knit from stitch notation
# ---------------------------------------------------------------------------

def custom_knit(
    notation: list[list[StitchType]],
    gauge: float = 5.0,
    courses_per_cm: float = 7.0,
) -> KnitResult:
    """
    Build a KnitResult directly from a user-supplied stitch matrix.

    Parameters
    ----------
    notation : list[list[StitchType]]
        notation[course][needle] ∈ {"loop", "tuck", "miss"}
    """
    if not notation or not notation[0]:
        raise ValueError("notation must be a non-empty 2-D list")
    valid = {"loop", "tuck", "miss"}
    for r, row in enumerate(notation):
        for c, cell in enumerate(row):
            if cell not in valid:
                raise ValueError(f"notation[{r}][{c}]={cell!r} not in {valid}")

    needles = len(notation[0])
    courses = len(notation)
    stats = _density_stats(notation, gauge, courses_per_cm)
    return KnitResult(
        name="custom",
        repeat_needles=needles,
        repeat_courses=courses,
        cell_matrix=notation,
        density_stats=stats,
        tile_raster=_tile_raster_knit(notation, repeat_x=2, repeat_y=2),
    )
