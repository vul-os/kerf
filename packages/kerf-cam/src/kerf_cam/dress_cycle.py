"""
kerf_cam.dress_cycle — Grinding wheel dressing cycle G-code generator.

Reference standards
-------------------
* Machinery's Handbook 31e §1145 — Wheel dressing:
  Single-point diamond dresser: traverse rate 50–300 mm/min across wheel face;
  depth-per-pass (infeed) 0.005–0.025 mm (roughing) or 0.002–0.010 mm
  (finishing); total dress allowance typically 0.05–0.5 mm per dressing
  session (depends on wheel diameter and glazing extent).

  Rotary diamond roll dresser (crush/plunge or traverse): higher traverse
  rates (100–800 mm/min) are acceptable because the rotary contact distributes
  load; depth-per-pass 0.010–0.050 mm.

  Strategy (traverse dressing):
    1. Position diamond at dress_x_start_mm (X = dresser infeed axis),
       dress_z_start_mm (Z = wheel-width start).
    2. Per pass:
         a. Infeed X by depth_per_pass_mm (moves dresser into wheel periphery).
         b. Traverse Z across full wheel width at traverse_rate_mm_per_min.
         c. Rapid-retract Z to dress_z_start_mm (single-direction dressing).
    3. Repeat for num_passes = ceil(total_dress_amount / depth_per_pass).
    4. Emit G28/G91 return-to-reference after final pass.

* Sandvik Coromant CoroGrind Grinding Handbook §5 — Wheel conditioning:
  - Single-point diamond: traverse rate V_d = 0.5–3 m/min depending on
    desired wheel form sharpness; finer Ra → slower traverse.
  - Rotary diamond roll: infeed rate 5–50 μm per rev of wheel; traverse
    rate 0.5–5 m/min.
  - Typical dress overlap ratio U_d = b_d / f_d (dresser width / traverse
    per rev); U_d = 2–4 for roughing dressing, 4–8 for finishing dressing.

Honest caveats (stored in DressCycleResult.honest_caveat)
---------------------------------------------------------
- Open-loop dressing only: no in-process wheel diameter measurement or
  closed-loop correction (AE/acoustic-emission sensors, power monitoring,
  or direct roundness gauging are NOT implemented).
- Assumes traverse dressing across wheel face width in +Z direction only
  (uni-directional); bi-directional oscillating traverse is NOT generated.
- No wheel-spindle synchronisation G-code: separate dressing spindle
  speed (for rotary roll) is the user's responsibility.
- Time estimate uses constant traverse rate only; rapid Z retract is
  estimated at 3000 mm/min (conservative for a grinding-machine Z axis).
- Depth-per-pass/traverse-rate validity checks are advisory only (±30 %
  wide safe bands); verify against dresser manufacturer specification.
- G-code is generic RS-274/NGC (Fanuc 0i-PD dialect compatible); controller-
  specific dress compensation (e.g. Siemens CYCLE12x, ANCA DressPro) is
  NOT emitted.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Constants (MH 31e §1145 + CoroGrind §5)
# ---------------------------------------------------------------------------

# Safe traverse-rate bands in mm/min per dresser type
_TRAVERSE_SAFE = {
    "single_point_diamond": (50.0, 300.0),
    "rotary_diamond":       (100.0, 800.0),
}

# Safe depth-per-pass bands in mm per dresser type
_DEPTH_SAFE = {
    "single_point_diamond": (0.002, 0.025),
    "rotary_diamond":       (0.005, 0.050),
}

_VALID_DRESSER_TYPES = frozenset({"single_point_diamond", "rotary_diamond"})

# Estimated rapid Z rate on grinding machine axes (conservative, mm/min)
_RAPID_Z_MM_PER_MIN = 3000.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DressSpec:
    """Specification for a grinding wheel dressing cycle.

    All distance parameters are in millimetres.
    Rates are in mm/min.

    Parameters
    ----------
    wheel_diameter_mm
        Nominal wheel OD in mm (informational; used for caveats).
    wheel_width_mm
        Wheel face width in mm — the dresser traverses this distance per pass.
        Must be > 0.
    dresser_type
        "single_point_diamond" or "rotary_diamond".
    depth_per_pass_mm
        Radial infeed of the dresser per pass (positive, mm).
        Typical single-point: 0.005–0.025 mm.
        Typical rotary roll:  0.010–0.050 mm.
    total_dress_amount_mm
        Total radial material to remove across all passes (positive, mm).
        num_passes = ceil(total_dress_amount_mm / depth_per_pass_mm).
    traverse_rate_mm_per_min
        Feed rate of the dresser across the wheel face (mm/min, > 0).
        Typical single-point: 50–300 mm/min.
        Typical rotary roll:  100–800 mm/min.
    dress_x_start_mm
        Absolute X coordinate of the dresser at the beginning of the first
        pass (dresser just touching wheel periphery before infeed).
    dress_z_start_mm
        Absolute Z coordinate of the dresser at the start of each traverse
        (wheel-width entry side).
    """
    wheel_diameter_mm: float
    wheel_width_mm: float
    dresser_type: str
    depth_per_pass_mm: float
    total_dress_amount_mm: float
    traverse_rate_mm_per_min: float
    dress_x_start_mm: float
    dress_z_start_mm: float

    def __post_init__(self) -> None:
        if self.wheel_diameter_mm <= 0:
            raise ValueError(
                f"wheel_diameter_mm must be > 0, got {self.wheel_diameter_mm!r}"
            )
        if self.wheel_width_mm <= 0:
            raise ValueError(
                f"wheel_width_mm must be > 0, got {self.wheel_width_mm!r}"
            )
        if self.dresser_type not in _VALID_DRESSER_TYPES:
            raise ValueError(
                f"dresser_type must be one of {sorted(_VALID_DRESSER_TYPES)}, "
                f"got {self.dresser_type!r}"
            )
        if self.depth_per_pass_mm <= 0:
            raise ValueError(
                f"depth_per_pass_mm must be > 0, got {self.depth_per_pass_mm!r}"
            )
        if self.total_dress_amount_mm <= 0:
            raise ValueError(
                f"total_dress_amount_mm must be > 0, got {self.total_dress_amount_mm!r}"
            )
        if self.traverse_rate_mm_per_min <= 0:
            raise ValueError(
                f"traverse_rate_mm_per_min must be > 0, "
                f"got {self.traverse_rate_mm_per_min!r}"
            )


@dataclass
class DressCycleResult:
    """Result from ``generate_dress_cycle``.

    Attributes
    ----------
    gcode
        Complete G-code program (UTF-8 text) for the dressing cycle.
    num_passes
        Number of dressing passes generated
        = ceil(total_dress_amount_mm / depth_per_pass_mm).
    total_dress_distance_mm
        Total traverse distance covered across all passes (mm).
        = num_passes × wheel_width_mm.
    machining_time_s
        Estimated total dressing cycle time in seconds.
        Includes traverse time at traverse_rate plus rapid Z retract between
        passes.  Does NOT include spindle warm-up, coolant stabilisation, or
        controller scan time.
    recommended_traverse_rate_mm_per_min
        Midpoint of the MH 31e §1145 safe traverse-rate band for the given
        dresser_type (informational).
    honest_caveat
        Plain-English description of modelling assumptions and limitations.
    """
    gcode: str
    num_passes: int
    total_dress_distance_mm: float
    machining_time_s: float
    recommended_traverse_rate_mm_per_min: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation (≥ 1 decimal place).

    Uses 4 decimal places for mm values then strips trailing zeros,
    keeping at least one decimal place (e.g. "2.0", "-0.005", "100.0").
    """
    formatted = f"{v:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
        if "." not in formatted:
            formatted = formatted + ".0"
    return formatted


def _estimate_dress_time(spec: DressSpec, num_passes: int) -> float:
    """Estimate total dressing cycle time in seconds.

    Model:
      Per pass:
        1. Traverse Z across wheel width at traverse_rate.
        2. Rapid-retract Z to dress_z_start at _RAPID_Z_MM_PER_MIN.
      No intra-pass X infeed time (infeed is effectively instantaneous at
      grinding-machine X axis rapids ~3000 mm/min; distance = depth_per_pass ≤ 0.05 mm).

    Returns estimated time in seconds (float).
    """
    traverse_time_per_pass = (spec.wheel_width_mm / spec.traverse_rate_mm_per_min) * 60.0
    retract_time_per_pass = (spec.wheel_width_mm / _RAPID_Z_MM_PER_MIN) * 60.0
    return num_passes * (traverse_time_per_pass + retract_time_per_pass)


def _recommended_traverse(dresser_type: str) -> float:
    """Return midpoint of MH 31e §1145 safe traverse band (mm/min)."""
    lo, hi = _TRAVERSE_SAFE[dresser_type]
    return (lo + hi) / 2.0


def _dress_advisory(spec: DressSpec) -> str:
    """Return an advisory string if traverse rate or depth is outside safe band."""
    advisories = []
    tlo, thi = _TRAVERSE_SAFE[spec.dresser_type]
    if not (tlo <= spec.traverse_rate_mm_per_min <= thi):
        advisories.append(
            f"traverse_rate {spec.traverse_rate_mm_per_min} mm/min is outside "
            f"MH 31e §1145 safe band [{tlo}–{thi}] mm/min for {spec.dresser_type}"
        )
    dlo, dhi = _DEPTH_SAFE[spec.dresser_type]
    if not (dlo <= spec.depth_per_pass_mm <= dhi):
        advisories.append(
            f"depth_per_pass {spec.depth_per_pass_mm} mm is outside "
            f"MH 31e §1145 safe band [{dlo}–{dhi}] mm for {spec.dresser_type}"
        )
    return "; ".join(advisories)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_dress_cycle(spec: DressSpec) -> DressCycleResult:
    """Generate G-code for a grinding wheel dressing cycle.

    Strategy (MH 31e §1145 traverse dressing):
      1. Program preamble: G21 metric, G90 absolute, G94 feed-per-minute.
      2. Rapid to dress start position (dress_x_start_mm, dress_z_start_mm).
      3. For each pass i = 1 … num_passes:
           a. Infeed X by depth_per_pass_mm (dress depth advance).
           b. Traverse Z across wheel width at traverse_rate_mm_per_min.
           c. Rapid-retract Z back to dress_z_start_mm.
      4. G28 G91 Z0.0  — return Z axis to reference (machine home) after dressing.
      5. Program footer: M05 spindle off, M30 end.

    num_passes = ceil(total_dress_amount_mm / depth_per_pass_mm).
    X_infeed_i  = dress_x_start_mm − i × depth_per_pass_mm
                  (negative X movement = deeper into wheel periphery).
    Z_traverse  = dress_z_start_mm + wheel_width_mm (traverse to far side of wheel).

    Parameters
    ----------
    spec : DressSpec

    Returns
    -------
    DressCycleResult

    Raises
    ------
    ValueError
        If spec fields are invalid (caught by DressSpec.__post_init__).
    """
    num_passes = math.ceil(spec.total_dress_amount_mm / spec.depth_per_pass_mm)
    total_dress_distance_mm = float(num_passes * spec.wheel_width_mm)
    machining_time_s = _estimate_dress_time(spec, num_passes)
    rec_traverse = _recommended_traverse(spec.dresser_type)

    z_traverse_end = spec.dress_z_start_mm + spec.wheel_width_mm

    lines = []

    # Program header
    lines.append("%")
    lines.append("(Grinding Wheel Dressing Cycle — Kerf CAM)")
    lines.append(f"(Dresser type : {spec.dresser_type})")
    lines.append(
        f"(Wheel OD     : {_fmt(spec.wheel_diameter_mm)} mm  "
        f"Width: {_fmt(spec.wheel_width_mm)} mm)"
    )
    lines.append(
        f"(Depth/pass   : {_fmt(spec.depth_per_pass_mm)} mm  "
        f"Total dress: {_fmt(spec.total_dress_amount_mm)} mm)"
    )
    lines.append(
        f"(Traverse rate: {_fmt(spec.traverse_rate_mm_per_min)} mm/min  "
        f"Passes: {num_passes})"
    )
    lines.append(
        "(Ref: MH 31e §1145 + Sandvik CoroGrind Grinding Handbook §5)"
    )
    lines.append(
        "(CAVEAT: open-loop dressing — no AE/power closed-loop correction)"
    )
    lines.append(
        "(CAVEAT: uni-directional traverse only; bi-directional NOT implemented)"
    )
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")

    # Rapid to initial dress position
    lines.append(
        f"G00 X{_fmt(spec.dress_x_start_mm)} Z{_fmt(spec.dress_z_start_mm)}"
        "  (rapid to dress start)"
    )
    lines.append("")

    # Generate per-pass blocks
    for i in range(1, num_passes + 1):
        # Actual infeed X position: move deeper into wheel each pass
        x_infeed = spec.dress_x_start_mm - (i * spec.depth_per_pass_mm)
        lines.append(f"(Pass {i} of {num_passes})")
        lines.append(
            f"G01 X{_fmt(x_infeed)}"
            f"  (infeed {_fmt(spec.depth_per_pass_mm)} mm into wheel)"
        )
        lines.append(
            f"G01 Z{_fmt(z_traverse_end)} F{_fmt(spec.traverse_rate_mm_per_min)}"
            f"  (traverse across wheel face {_fmt(spec.wheel_width_mm)} mm)"
        )
        lines.append(
            f"G00 Z{_fmt(spec.dress_z_start_mm)}"
            "  (rapid retract Z to start)"
        )
        lines.append("")

    # Return Z axis to machine reference after dressing
    lines.append("G28 G91 Z0.0  (return Z to reference)")
    lines.append("G90  (restore absolute mode)")
    lines.append("M05  (spindle off — dressing complete)")
    lines.append("M30  (end of program)")
    lines.append("%")

    gcode = "\n".join(lines)

    # Build advisory string
    advisory = _dress_advisory(spec)

    # Build honest caveat
    caveat_parts = [
        "Open-loop dressing cycle: no in-process wheel diameter measurement or "
        "closed-loop correction (AE sensor, power monitoring, or roundness gauging "
        "are NOT implemented — MH 31e §1145 notes these are required for precision "
        "grinding applications).",
        "Uni-directional traverse only (Z+ direction per pass); bi-directional "
        "oscillating traverse is NOT generated.",
        "No wheel-spindle synchronisation G-code: rotary diamond roll dresser speed "
        "must be set separately on the dressing spindle.",
        f"Time estimate assumes constant traverse rate {_fmt(spec.traverse_rate_mm_per_min)} "
        f"mm/min and rapid Z retract at {_RAPID_Z_MM_PER_MIN} mm/min; "
        "acceleration ramps, coolant stabilisation, and controller scan time are "
        "NOT modelled (add 10–20% for real cycle).",
        f"Traverse-rate safe band for {spec.dresser_type}: "
        f"{_TRAVERSE_SAFE[spec.dresser_type][0]}–{_TRAVERSE_SAFE[spec.dresser_type][1]} mm/min "
        "(MH 31e §1145); depth-per-pass safe band: "
        f"{_DEPTH_SAFE[spec.dresser_type][0]}–{_DEPTH_SAFE[spec.dresser_type][1]} mm.",
        "G-code is RS-274/NGC / Fanuc 0i-PD compatible; controller-specific dress "
        "compensation cycles (Siemens CYCLE12x, ANCA DressPro) are NOT emitted.",
        "Refs: MH 31e §1145 (Wheel dressing); "
        "Sandvik Coromant CoroGrind Grinding Handbook §5 (Wheel conditioning).",
    ]
    if advisory:
        caveat_parts.insert(0, f"ADVISORY — {advisory}.")
    honest_caveat = "  ".join(caveat_parts)

    return DressCycleResult(
        gcode=gcode,
        num_passes=num_passes,
        total_dress_distance_mm=round(total_dress_distance_mm, 4),
        machining_time_s=round(machining_time_s, 3),
        recommended_traverse_rate_mm_per_min=round(rec_traverse, 1),
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_dress_cycle_spec = ToolSpec(
    name="cam_generate_dress_cycle",
    description=(
        "Generate G-code for a grinding wheel dressing cycle (traverse dressing) "
        "using a single-point diamond or rotary diamond roll dresser. "
        "Computes num_passes = ceil(total_dress_amount / depth_per_pass), "
        "emits one infeed + traverse + retract block per pass, and returns "
        "the complete G-code program, pass count, total traverse distance, "
        "estimated cycle time, recommended traverse rate (MH 31e §1145), and "
        "honest caveats. "
        "IMPORTANT: open-loop only — no closed-loop AE/power correction is "
        "generated. "
        "References: Machinery's Handbook 31e §1145 (Wheel dressing); "
        "Sandvik Coromant CoroGrind Grinding Handbook §5 (Wheel conditioning)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wheel_diameter_mm": {
                "type": "number",
                "description": (
                    "Nominal grinding wheel outer diameter in mm (> 0). "
                    "Informational — used in G-code header and caveats."
                ),
            },
            "wheel_width_mm": {
                "type": "number",
                "description": (
                    "Wheel face width in mm (> 0). "
                    "Dresser traverses this distance per pass."
                ),
            },
            "dresser_type": {
                "type": "string",
                "enum": ["single_point_diamond", "rotary_diamond"],
                "description": (
                    "Dresser type. "
                    "'single_point_diamond': stationary diamond nib; "
                    "traverse 50–300 mm/min, depth 0.002–0.025 mm/pass (MH 31e §1145). "
                    "'rotary_diamond': powered rotary roll; "
                    "traverse 100–800 mm/min, depth 0.005–0.050 mm/pass "
                    "(Sandvik CoroGrind §5)."
                ),
            },
            "depth_per_pass_mm": {
                "type": "number",
                "description": (
                    "Radial dresser infeed per pass in mm (> 0). "
                    "Typical single-point: 0.005–0.025 mm. "
                    "Typical rotary roll: 0.010–0.050 mm."
                ),
            },
            "total_dress_amount_mm": {
                "type": "number",
                "description": (
                    "Total radial material to remove across all passes in mm (> 0). "
                    "num_passes = ceil(total_dress_amount_mm / depth_per_pass_mm)."
                ),
            },
            "traverse_rate_mm_per_min": {
                "type": "number",
                "description": (
                    "Feed rate of the dresser across the wheel face in mm/min (> 0). "
                    "Lower rate → sharper (open) wheel form; higher → smoother/glazed. "
                    "Single-point safe band: 50–300 mm/min. "
                    "Rotary roll safe band: 100–800 mm/min."
                ),
            },
            "dress_x_start_mm": {
                "type": "number",
                "description": (
                    "Absolute X coordinate (dresser infeed axis) at the beginning "
                    "of pass 1 — dresser just tangent to wheel periphery before "
                    "first infeed. Typically negative (wheel centre on +X side)."
                ),
            },
            "dress_z_start_mm": {
                "type": "number",
                "description": (
                    "Absolute Z coordinate (wheel-width axis) at the start of each "
                    "traverse pass (entry side of wheel face). "
                    "Z traverse endpoint = dress_z_start_mm + wheel_width_mm."
                ),
            },
        },
        "required": [
            "wheel_diameter_mm",
            "wheel_width_mm",
            "dresser_type",
            "depth_per_pass_mm",
            "total_dress_amount_mm",
            "traverse_rate_mm_per_min",
            "dress_x_start_mm",
            "dress_z_start_mm",
        ],
    },
)


@register(cam_generate_dress_cycle_spec)
async def run_cam_generate_dress_cycle(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool handler for cam_generate_dress_cycle."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

    try:
        spec = DressSpec(
            wheel_diameter_mm=float(a["wheel_diameter_mm"]),
            wheel_width_mm=float(a["wheel_width_mm"]),
            dresser_type=str(a["dresser_type"]),
            depth_per_pass_mm=float(a["depth_per_pass_mm"]),
            total_dress_amount_mm=float(a["total_dress_amount_mm"]),
            traverse_rate_mm_per_min=float(a["traverse_rate_mm_per_min"]),
            dress_x_start_mm=float(a["dress_x_start_mm"]),
            dress_z_start_mm=float(a["dress_z_start_mm"]),
        )
    except KeyError as exc:
        return err_payload(f"missing required field: {exc}", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        result = generate_dress_cycle(spec)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "ERROR")

    return ok_payload({
        "gcode": result.gcode,
        "num_passes": result.num_passes,
        "total_dress_distance_mm": result.total_dress_distance_mm,
        "machining_time_s": result.machining_time_s,
        "recommended_traverse_rate_mm_per_min": result.recommended_traverse_rate_mm_per_min,
        "honest_caveat": result.honest_caveat,
    })
