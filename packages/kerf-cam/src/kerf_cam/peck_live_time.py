"""
kerf_cam.peck_live_time — G83 peck-drill cycle "live time" analytics.

Computes the fraction of the total G83 peck-drill cycle time during which
the cutting edge is actually engaged (feeding into material) versus the
overhead time spent retracting and dwelling.  Used for:

  - Chip-evacuation analysis: low live fractions indicate heavy retract
    overhead; heat cycling accelerates tool wear.
  - Tool-life budgeting: manufacturers quote tool life in cutting-seconds;
    this module converts cycle count → actual cutting time.
  - Process optimisation: compare peck depth and retract clearance options
    to maximise live fraction without compromising chip clearance.

Reference standards
-------------------
* Machinery's Handbook 31e §1132 — Peck drilling: retract cycles,
  chip-clearing strategy, dwell at bottom, peck depth ratios.
* Sandvik CoroPlus Drill Cycle Analytics (2024) — live-time fraction
  benchmarks; recommended minimum live fraction = 0.50 for solid carbide
  drills in steel; 0.40 for HSS in aluminium (chip-clearance dominated).
* NIST RS-274/NGC §3.8.4 — G83 canned-cycle motion model (full retract to
  R plane after each peck).

Honest caveats
--------------
- Model assumes **ideal rigid rapid** traversal at ``rapid_z_mm_per_min``
  with no acceleration ramps at peck reversals.  Real machines take 2–8 mm
  of travel to reach programmed rapid speed from rest, adding 5–20 % to
  retract time depending on servo bandwidth (Sandvik CoroPlus 2024 §Annex C).
- **Retract overhead is conservative** (full retract to R plane per peck),
  matching NIST RS-274/NGC G83.  Controllers that implement G83 as a chip-
  breaking partial-retract (e.g. Haas "G83 chip-break mode") will have
  higher live fractions than reported.
- Dwell time (G4 at hole bottom) is charged against neither cutting nor
  retract — it is reported separately.
- No spindle acceleration/deceleration modelled.  Constant surface speed
  assumed throughout.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PeckCycleParams:
    """Parameters for one G83 peck-drilling cycle (all distances in mm).

    Attributes
    ----------
    depth_mm              : Total hole depth (positive, mm).
    peck_depth_mm         : Incremental peck depth per stroke (positive, mm).
    retract_z_mm          : Clearance above the work surface to which the tool
                            retracts between pecks — the R-plane offset (mm).
                            Typically 1–5 mm.
    rapid_z_mm_per_min    : Rapid traverse rate in Z (mm/min).  Default 20 000 mm/min
                            (typical mid-range VMC; Sandvik CoroPlus 2024 §Annex C).
    feed_z_mm_per_min     : Feed rate during drilling stroke (mm/min).
    dwell_per_peck_ms     : Dwell applied after each peck stroke (ms).
                            Most controllers apply a dwell only on the final stroke
                            (NIST RS-274/NGC §3.8.4 G4 P-word); setting this > 0
                            models the worst-case per-peck dwell.  Default 0.
    """
    depth_mm: float
    peck_depth_mm: float
    retract_z_mm: float
    feed_z_mm_per_min: float
    rapid_z_mm_per_min: float = 20_000.0
    dwell_per_peck_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.depth_mm <= 0:
            raise ValueError(f"depth_mm must be > 0, got {self.depth_mm!r}")
        if self.peck_depth_mm <= 0:
            raise ValueError(f"peck_depth_mm must be > 0, got {self.peck_depth_mm!r}")
        if self.feed_z_mm_per_min <= 0:
            raise ValueError(f"feed_z_mm_per_min must be > 0, got {self.feed_z_mm_per_min!r}")
        if self.rapid_z_mm_per_min <= 0:
            raise ValueError(
                f"rapid_z_mm_per_min must be > 0, got {self.rapid_z_mm_per_min!r}"
            )
        if self.retract_z_mm < 0:
            raise ValueError(f"retract_z_mm must be >= 0, got {self.retract_z_mm!r}")
        if self.dwell_per_peck_ms < 0:
            raise ValueError(
                f"dwell_per_peck_ms must be >= 0, got {self.dwell_per_peck_ms!r}"
            )


@dataclass
class PeckLiveTimeReport:
    """Result of a G83 peck-drill live-time analysis.

    Attributes
    ----------
    num_pecks                       : Number of peck strokes (ceil(depth/peck)).
    total_cycle_time_s              : Total G83 cycle time (feed + retract + dwell), seconds.
    cutting_live_time_s             : Time the cutting edge is feeding (engaged), seconds.
    retract_time_s                  : Time spent in rapid retract traversals, seconds.
    dwell_time_s                    : Time spent in G4 dwells, seconds.
    live_time_fraction              : cutting_live_time_s / total_cycle_time_s  ∈ (0, 1].
    recommended_minimum_live_fraction : Benchmark threshold (default 0.50 per Sandvik CoroPlus).
    adequate                        : live_time_fraction >= recommended_minimum_live_fraction.
    honest_caveat                   : Plain-English note on model assumptions and limits.
    """
    num_pecks: int
    total_cycle_time_s: float
    cutting_live_time_s: float
    retract_time_s: float
    dwell_time_s: float
    live_time_fraction: float
    recommended_minimum_live_fraction: float = 0.50
    adequate: bool = field(init=False)
    honest_caveat: str = field(init=False)

    def __post_init__(self) -> None:
        self.adequate = self.live_time_fraction >= self.recommended_minimum_live_fraction
        self.honest_caveat = (
            "Live-time model assumes ideal rigid rapid (no acceleration ramps at peck "
            "reversal); real machines add 5–20 % retract overhead (Sandvik CoroPlus 2024 "
            "§Annex C servo dynamics). Full-retract G83 per NIST RS-274/NGC §3.8.4; "
            "chip-breaking partial-retract controllers (Haas G83 chip-break, G73) will "
            "yield higher actual live fractions than reported here. "
            "Dwell time is reported separately and is not charged to cutting or retract."
        )


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_peck_live_time(params: PeckCycleParams) -> PeckLiveTimeReport:
    """Compute cutting-edge live time for one G83 peck-drill cycle.

    Model (NIST RS-274/NGC §3.8.4 + MH 31e §1132)
    -----------------------------------------------
    For each peck stroke k (0-indexed, k = 0 … num_pecks-1):

      1. Rapid down from R plane to top of current bore depth.
         Distance = retract_z_mm + k × peck_depth_mm  (clearance above work
         surface plus already-drilled depth).
         *Exception*: on the first stroke (k=0) rapid distance is just
         retract_z_mm (no depth drilled yet).

      2. Feed drilling stroke of this_peck_depth mm.
         time = this_peck_depth / feed_z_mm_per_min × 60.

      3. Rapid retract to R plane.
         Distance = retract_z_mm + (k+1) × this_peck_depth  (from new hole
         bottom back to R plane above surface).

      4. Optional dwell (dwell_per_peck_ms > 0).

    The "live time" is the sum of step 2 times.
    The "retract time" is the sum of steps 1 + 3 times.

    Parameters
    ----------
    params : PeckCycleParams

    Returns
    -------
    PeckLiveTimeReport
    """
    depth = params.depth_mm
    peck = params.peck_depth_mm
    feed = params.feed_z_mm_per_min
    rapid = params.rapid_z_mm_per_min
    retract_z = params.retract_z_mm
    dwell_s_per_peck = params.dwell_per_peck_ms / 1000.0

    num_pecks = max(1, math.ceil(depth / peck))

    cutting_s = 0.0
    retract_s = 0.0
    dwell_s = 0.0

    depth_drilled = 0.0  # cumulative depth at start of each peck

    for k in range(num_pecks):
        remaining = depth - depth_drilled
        this_peck = min(peck, remaining)

        # --- Rapid down to top of current bore (from R plane) ---
        # Distance from R plane (retract_z above work surface) down to
        # the previously-drilled depth.
        rapid_down_dist = retract_z + depth_drilled  # mm
        if rapid_down_dist > 0:
            retract_s += (rapid_down_dist / rapid) * 60.0

        # --- Cutting stroke (feed) ---
        cutting_s += (this_peck / feed) * 60.0

        # --- Rapid retract to R plane ---
        # From new bottom (depth_drilled + this_peck) back to R plane.
        rapid_up_dist = retract_z + depth_drilled + this_peck  # mm
        retract_s += (rapid_up_dist / rapid) * 60.0

        # --- Dwell ---
        dwell_s += dwell_s_per_peck

        depth_drilled += this_peck

    total_s = cutting_s + retract_s + dwell_s
    if total_s <= 0:
        # Guard against degenerate inputs (should not happen after __post_init__)
        live_frac = 0.0
    else:
        live_frac = cutting_s / total_s

    return PeckLiveTimeReport(
        num_pecks=num_pecks,
        total_cycle_time_s=round(total_s, 6),
        cutting_live_time_s=round(cutting_s, 6),
        retract_time_s=round(retract_s, 6),
        dwell_time_s=round(dwell_s, 6),
        live_time_fraction=round(live_frac, 6),
        recommended_minimum_live_fraction=0.50,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_compute_peck_live_time_spec = ToolSpec(
    name="cam_compute_peck_live_time",
    description=(
        "Compute the cutting-edge 'live time' (engaged cutting time) for a G83 "
        "peck-drill cycle given depth, peck increment, retract clearance, feed, and "
        "rapid rate.  Returns num_pecks, total cycle time, cutting live time, retract "
        "time, dwell time, live-time fraction, and whether the fraction meets the "
        "Sandvik CoroPlus recommended minimum (0.50).  Used for chip-evacuation analysis "
        "and tool-life budgeting.  References: MH 31e §1132 + Sandvik CoroPlus drill "
        "cycle analytics (2024).  Honest caveat: ideal rigid-rapid assumed — no "
        "acceleration ramps at peck reversal."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "depth_mm": {
                "type": "number",
                "description": "Total hole depth in mm (positive).",
            },
            "peck_depth_mm": {
                "type": "number",
                "description": (
                    "Incremental peck depth per stroke in mm (positive). "
                    "MH §1132: ≤ 1.5 × D for soft materials, ≤ 1.0 × D for hardened steel."
                ),
            },
            "retract_z_mm": {
                "type": "number",
                "description": (
                    "R-plane clearance height above the work surface in mm (positive). "
                    "Typical value: 1–5 mm."
                ),
            },
            "feed_z_mm_per_min": {
                "type": "number",
                "description": "Feed rate during drilling stroke (mm/min).",
            },
            "rapid_z_mm_per_min": {
                "type": "number",
                "description": (
                    "Rapid traverse rate in Z (mm/min). Default 20 000 mm/min "
                    "(typical mid-range VMC)."
                ),
            },
            "dwell_per_peck_ms": {
                "type": "number",
                "description": (
                    "Dwell time per peck stroke in milliseconds. Default 0. "
                    "Models worst-case per-peck dwell; most controllers only dwell "
                    "on the final stroke (NIST RS-274/NGC §3.8.4 G4 P-word)."
                ),
            },
        },
        "required": ["depth_mm", "peck_depth_mm", "retract_z_mm", "feed_z_mm_per_min"],
    },
)


@register(cam_compute_peck_live_time_spec)
async def run_cam_compute_peck_live_time(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool handler — parse JSON args, run compute, return JSON payload."""
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        params = PeckCycleParams(
            depth_mm=float(a["depth_mm"]),
            peck_depth_mm=float(a["peck_depth_mm"]),
            retract_z_mm=float(a["retract_z_mm"]),
            feed_z_mm_per_min=float(a["feed_z_mm_per_min"]),
            rapid_z_mm_per_min=float(a.get("rapid_z_mm_per_min", 20_000.0)),
            dwell_per_peck_ms=float(a.get("dwell_per_peck_ms", 0.0)),
        )
    except KeyError as e:
        return err_payload(f"missing required field: {e}", "BAD_ARGS")
    except (TypeError, ValueError) as e:
        return err_payload(f"invalid field value: {e}", "BAD_ARGS")

    try:
        report = compute_peck_live_time(params)
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "num_pecks": report.num_pecks,
        "total_cycle_time_s": report.total_cycle_time_s,
        "cutting_live_time_s": report.cutting_live_time_s,
        "retract_time_s": report.retract_time_s,
        "dwell_time_s": report.dwell_time_s,
        "live_time_fraction": report.live_time_fraction,
        "recommended_minimum_live_fraction": report.recommended_minimum_live_fraction,
        "adequate": report.adequate,
        "honest_caveat": report.honest_caveat,
    })
