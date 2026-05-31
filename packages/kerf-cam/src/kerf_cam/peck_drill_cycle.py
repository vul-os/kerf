"""
kerf_cam.peck_drill_cycle — G83 deep-hole peck-drilling cycle (chip-breaking).

Reference standards
-------------------
* NIST RS-274/NGC §3.8.4 — G83 canned cycle (full retract peck drill).
  Format: ``G83 X<x> Y<y> Z<z> R<r> Q<q> F<f>``
  where
    X, Y — hole centre in the current work coordinate system
    Z     — final hole depth (signed, typically negative)
    R     — retract plane Z (clearance height above work top)
    Q     — peck increment (positive, unsigned distance per peck)
    F     — feed rate in mm/min (metric mode G21)

* Machinery's Handbook 31e §1132 — Peck drilling guidelines:
  - Rule of thumb: peck depth ≤ 1.5 × drill diameter for soft materials;
    ≤ 1.0 × D for hardened steel.
  - Full retract (chip-clearing) peck recommended when depth > 3 × D.
  - Dwell at bottom (G4) recommended for blind holes and when using
    HSS drills in abrasive materials.

Caveats (honest_caveat in PeckCycleResult)
-------------------------------------------
- Time estimates use constant feed/rapid rates; acceleration ramps are NOT
  modelled (actual cycle times will be longer by ~5–15% depending on
  machine dynamics).
- The "rapid Z" motion (retract to R plane between pecks) is computed at
  the caller-supplied ``rapid_z_mm`` (not the actual machine G0 override).
- G83 is a "full retract" cycle per RS-274/NGC; some controllers implement
  G83 as a chip-breaking peck (retract only 1–2 mm) and G83.1 or G73 as
  full retract.  Kerf emits standard RS-274/NGC G83 (full retract).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

import json


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PeckHoleSpec:
    """Specification for a single peck-drilled hole.

    All distance parameters are in millimetres (assumes G21 metric mode).
    Feed and rapid rates are in mm/min.

    Parameters
    ----------
    x_mm, y_mm      : hole centre position in the XY plane (work CS)
    depth_mm         : total hole depth (positive value; drilled in –Z direction)
    peck_depth_mm    : incremental peck depth per stroke (positive, > 0)
    retract_mm       : Z coordinate of the R (retract) plane above work top
                       (e.g. 2.0 means the tool retracts to Z = work_top_z + 2.0)
    feed_mm_per_min  : feed rate during drilling stroke (mm/min)
    dwell_s          : dwell time at hole bottom in seconds (0 = no dwell)
    rapid_z_mm       : rapid traverse rate in Z used for time estimation (mm/min)
                       Typical VMC: 10 000–30 000 mm/min.
    work_top_z_mm    : absolute Z of the work surface (default 0.0).
                       Hole bottom will be at work_top_z_mm − depth_mm.
    """
    x_mm: float
    y_mm: float
    depth_mm: float
    peck_depth_mm: float
    retract_mm: float
    feed_mm_per_min: float
    dwell_s: float = 0.0
    rapid_z_mm: float = 10000.0
    work_top_z_mm: float = 0.0

    def __post_init__(self):
        if self.depth_mm <= 0:
            raise ValueError(f"depth_mm must be > 0, got {self.depth_mm!r}")
        if self.peck_depth_mm <= 0:
            raise ValueError(f"peck_depth_mm must be > 0, got {self.peck_depth_mm!r}")
        if self.feed_mm_per_min <= 0:
            raise ValueError(f"feed_mm_per_min must be > 0, got {self.feed_mm_per_min!r}")
        if self.rapid_z_mm <= 0:
            raise ValueError(f"rapid_z_mm must be > 0, got {self.rapid_z_mm!r}")
        if self.retract_mm < 0:
            raise ValueError(f"retract_mm must be >= 0, got {self.retract_mm!r}")


@dataclass
class PeckCycleResult:
    """Result from ``generate_peck_drill_cycle``.

    Attributes
    ----------
    gcode                : Complete G-code program (UTF-8 text).
    num_pecks            : Total number of peck strokes across all holes.
    total_machining_time_s : Estimated cycle time in seconds.  See honest_caveat.
    honest_caveat        : Plain-English note on assumptions and limitations.
    """
    gcode: str
    num_pecks: int
    total_machining_time_s: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation.

    RS-274/NGC §3.5.1: numbers may be integers or reals; no trailing
    zeros are required but the decimal point must be present for reals.
    We use 4 decimal places for mm values to match common controller
    expectations (1 μm resolution).
    """
    formatted = f"{v:.{decimals}f}"
    # Remove redundant trailing zeros while keeping at least one decimal place
    # per NIST convention (e.g. "2.0000" → "2.0", "2.5000" → "2.5")
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
        if '.' not in formatted:
            formatted = formatted + '.0'
    return formatted


def _count_pecks(depth_mm: float, peck_depth_mm: float) -> int:
    """Return the number of peck strokes needed.

    Each stroke advances the tool by ``peck_depth_mm`` (or less for the final
    partial stroke).  Per MH §1132, when depth ≤ peck_depth the hole is
    drilled in a single stroke — no G83 nesting.

    >>> _count_pecks(10.0, 2.0)
    5
    >>> _count_pecks(2.0, 2.0)
    1
    >>> _count_pecks(1.5, 2.0)
    1
    >>> _count_pecks(10.0, 3.0)
    4
    """
    return max(1, math.ceil(depth_mm / peck_depth_mm))


def _estimate_cycle_time(
    hole: PeckHoleSpec,
    num_pecks: int,
) -> float:
    """Estimate the G83 cycle time for one hole (seconds).

    Model (per NIST RS-274/NGC §3.8.4 + MH §1132):
      For each peck stroke k (1-indexed):
        • Rapid down to previous peck depth + clearance (R plane or prior
          depth if controller uses incremental rapid).
          Kerf models the *conservative* case: rapid from R plane each time.
        • Feed drill stroke: peck_depth_mm / feed
        • Rapid retract to R plane
        • Dwell at bottom (only on the last stroke per NIST §3.8.4)

    Acceleration ramps are NOT modelled — see honest_caveat.

    Returns estimated time in seconds.
    """
    depth = hole.depth_mm
    peck = hole.peck_depth_mm
    feed = hole.feed_mm_per_min
    rapid = hole.rapid_z_mm
    retract_z_abs = hole.work_top_z_mm + hole.retract_mm   # R plane absolute Z

    total_s = 0.0
    current_depth = 0.0  # depth already drilled (positive = drilled distance)

    for k in range(num_pecks):
        remaining = depth - current_depth
        this_peck = min(peck, remaining)

        # Previous drill tip Z (absolute): work_top - current_depth
        prev_tip_z = hole.work_top_z_mm - current_depth
        # New tip Z after this stroke
        new_tip_z = prev_tip_z - this_peck

        # Rapid down from R plane to just above previous depth
        # Conservative model: always retract to R, always plunge from R
        rapid_dist_down = retract_z_abs - prev_tip_z
        if rapid_dist_down > 0:
            total_s += (rapid_dist_down / rapid) * 60.0

        # Feed drilling stroke
        total_s += (this_peck / feed) * 60.0

        # Dwell at bottom on last peck
        if k == num_pecks - 1 and hole.dwell_s > 0:
            total_s += hole.dwell_s

        # Rapid retract to R plane
        retract_dist = abs(new_tip_z - retract_z_abs)
        total_s += (retract_dist / rapid) * 60.0

        current_depth += this_peck

    return total_s


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_peck_drill_cycle(
    holes: List[PeckHoleSpec],
    modal_state: Optional[dict] = None,
) -> PeckCycleResult:
    """Generate canonical G83 peck-drilling G-code for a list of holes.

    The emitted program follows NIST RS-274/NGC §3.8.4.  Each hole uses
    one G83 canned-cycle line of the form::

        G83 X<x> Y<y> Z<z> R<r> Q<q> F<f>

    followed by ``G4 P<dwell>`` if dwell_s > 0, and closed by ``G80``
    (cancel canned cycle) after the last hole.

    Parameters
    ----------
    holes        : list of PeckHoleSpec; must be non-empty.
    modal_state  : optional dict of pre-existing modal codes (e.g.
                   ``{"feed_rate": 500.0, "units": "G21"}``).
                   Currently informational only; does not alter output.

    Returns
    -------
    PeckCycleResult

    Raises
    ------
    ValueError   : if holes list is empty.
    """
    if not holes:
        raise ValueError("holes list must not be empty")

    lines: List[str] = []
    total_pecks = 0
    total_time_s = 0.0

    # Program header
    lines.append("%")
    lines.append("(Peck-drill cycle — Kerf CAM / NIST RS-274/NGC G83)")
    lines.append("(Generated: kerf_cam.peck_drill_cycle.generate_peck_drill_cycle)")
    lines.append("(WARNING: time estimate excludes acceleration ramps)")
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")

    for i, hole in enumerate(holes):
        num_pecks = _count_pecks(hole.depth_mm, hole.peck_depth_mm)
        hole_time = _estimate_cycle_time(hole, num_pecks)
        total_pecks += num_pecks
        total_time_s += hole_time

        # Absolute Z values
        z_bottom = hole.work_top_z_mm - hole.depth_mm   # final hole depth (negative)
        r_plane = hole.work_top_z_mm + hole.retract_mm   # retract / clearance Z

        lines.append(f"(Hole {i + 1}: X={hole.x_mm} Y={hole.y_mm}"
                     f" depth={hole.depth_mm}mm peck={hole.peck_depth_mm}mm"
                     f" pecks={num_pecks})")

        # G83 block — canonical NIST RS-274/NGC §3.8.4 format
        # Q must be positive (peck increment magnitude)
        gline = (
            f"G83"
            f" X{_fmt(hole.x_mm)}"
            f" Y{_fmt(hole.y_mm)}"
            f" Z{_fmt(z_bottom)}"
            f" R{_fmt(r_plane)}"
            f" Q{_fmt(hole.peck_depth_mm)}"
            f" F{_fmt(hole.feed_mm_per_min)}"
        )
        lines.append(gline)

        # Optional dwell at hole bottom (G4 Pn where n = dwell in seconds)
        # RS-274/NGC §3.5.3: G4 P<dwell_s>
        if hole.dwell_s > 0:
            lines.append(f"G4 P{_fmt(hole.dwell_s, decimals=3)}")

        lines.append("")

    # Cancel canned cycle after all holes
    lines.append("G80  (cancel canned cycle)")
    lines.append("%")

    gcode = "\n".join(lines)

    caveat = (
        "Time estimate assumes constant feed/rapid rates with no acceleration ramps "
        "(actual cycle time will be 5–15% longer on a real machine depending on "
        "servo dynamics and peck count). "
        "G83 here is NIST RS-274/NGC full-retract peck; some controllers use G73 "
        "for chip-breaking (partial retract) — verify with your post-processor. "
        "Q (peck depth) is always positive per RS-274/NGC §3.8.4."
    )

    return PeckCycleResult(
        gcode=gcode,
        num_pecks=total_pecks,
        total_machining_time_s=round(total_time_s, 3),
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_peck_drill_cycle_spec = ToolSpec(
    name="cam_generate_peck_drill_cycle",
    description=(
        "Generate G-code for a G83 deep-hole peck-drilling cycle (chip-breaking) "
        "for one or more holes.  Follows NIST RS-274/NGC §3.8.4 and Machinery's "
        "Handbook 31e §1132 peck-drilling guidelines.  Returns the complete G-code "
        "program, total peck count, estimated cycle time, and honest caveats about "
        "the time model (acceleration ramps are not included)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "holes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "x_mm": {
                            "type": "number",
                            "description": "Hole centre X coordinate (mm)",
                        },
                        "y_mm": {
                            "type": "number",
                            "description": "Hole centre Y coordinate (mm)",
                        },
                        "depth_mm": {
                            "type": "number",
                            "description": "Total hole depth in mm (positive value)",
                        },
                        "peck_depth_mm": {
                            "type": "number",
                            "description": (
                                "Incremental peck depth per stroke in mm (positive). "
                                "MH §1132: typically 1.0–1.5 × drill diameter for soft "
                                "materials, ≤ 1.0 × D for hardened steel."
                            ),
                        },
                        "retract_mm": {
                            "type": "number",
                            "description": (
                                "R-plane clearance height above work surface in mm "
                                "(e.g. 2.0 means the tool retracts to Z = work_top + 2.0)."
                            ),
                        },
                        "feed_mm_per_min": {
                            "type": "number",
                            "description": "Drilling feed rate in mm/min",
                        },
                        "dwell_s": {
                            "type": "number",
                            "description": "Dwell time at hole bottom in seconds (0 = none; default 0)",
                        },
                        "rapid_z_mm": {
                            "type": "number",
                            "description": "Rapid Z rate in mm/min used for time estimation (default 10000)",
                        },
                        "work_top_z_mm": {
                            "type": "number",
                            "description": "Absolute Z of the work surface (default 0.0)",
                        },
                    },
                    "required": [
                        "x_mm", "y_mm", "depth_mm",
                        "peck_depth_mm", "retract_mm", "feed_mm_per_min",
                    ],
                },
                "description": "List of holes to drill",
            },
        },
        "required": ["holes"],
    },
)


@register(cam_generate_peck_drill_cycle_spec)
async def run_cam_generate_peck_drill_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    raw_holes = a.get("holes", [])
    if not raw_holes:
        return err_payload("holes list must not be empty", "BAD_ARGS")

    try:
        holes = []
        for h in raw_holes:
            spec = PeckHoleSpec(
                x_mm=float(h["x_mm"]),
                y_mm=float(h["y_mm"]),
                depth_mm=float(h["depth_mm"]),
                peck_depth_mm=float(h["peck_depth_mm"]),
                retract_mm=float(h["retract_mm"]),
                feed_mm_per_min=float(h["feed_mm_per_min"]),
                dwell_s=float(h.get("dwell_s", 0.0)),
                rapid_z_mm=float(h.get("rapid_z_mm", 10000.0)),
                work_top_z_mm=float(h.get("work_top_z_mm", 0.0)),
            )
            holes.append(spec)
        result = generate_peck_drill_cycle(holes)
    except (KeyError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "gcode": result.gcode,
        "num_pecks": result.num_pecks,
        "total_machining_time_s": result.total_machining_time_s,
        "honest_caveat": result.honest_caveat,
    })
