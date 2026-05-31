"""
kerf_cam.tap_cycle — G84 / G74 tapping canned cycle (rigid tap).

Reference standards
-------------------
* NIST RS-274/NGC §3.8.4 — G84 right-hand tapping cycle, G74 left-hand.
  G84 format: ``G84 X<x> Y<y> Z<z> R<r> F<f>``
  G74 format: ``G74 X<x> Y<y> Z<z> R<r> F<f>``
  where
    X, Y — hole centre in the current work coordinate system
    Z     — final tap depth (signed, typically negative)
    R     — retract / clearance plane Z above work top
    F     — feed rate in mm/min; for rigid tapping: F = pitch × spindle_rpm

* Fanuc 0i/30i-series operator manual §13.3.3 (Rigid Tapping G84/G74):
  - M29 S<rpm> must precede G84/G74 to engage rigid-tap mode.
  - In rigid tap: spindle position is synchronised to Z feed; ratio must be
    exact (F = pitch × rpm).  Floating-holder dwell compensation is NOT used.
  - G74 drives spindle CCW (M04) for left-hand threads; G84 drives CW (M03).

* Machinery's Handbook 31e §1934 (Tap Drill Sizes & Feed Coupling):
  - For rigid tapping, programmed feed rate F = P × N (mm/min), where
    P = thread pitch (mm) and N = spindle speed (rpm).  This is the only
    correct relationship; no chip-load or SFM formula applies.
  - Floating tap holders allow ±0.1–0.5 mm axial compliance; this module
    models rigid tap only.

Caveats (honest_caveat in TapCycleResult)
------------------------------------------
- Feed rate is coupled to spindle speed: F = pitch × rpm.  A mismatch will
  strip the thread or break the tap — always verify against controller docs.
- Cycle time estimate assumes constant Z feed; acceleration ramps are NOT
  modelled (typical error 5–15% depending on servo dynamics).
- M29 rigid-tap engage is Fanuc convention.  Haas uses G84 with S-word on
  same block; Siemens uses CYCLE84().  LinuxCNC RS-274/NGC does not require
  M29.  Verify with your post-processor.
- Floating tap holders are NOT modelled.  If a floating holder is in use,
  the F/S coupling tolerance is widened by the holder compliance; this module
  does not model that relaxation.
- Dwell at the hole bottom (P word) is unusual in rigid tapping (the
  controller reversal is synchronised); dwell_s > 0 emits G4 after retract
  only for legacy compatibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TapHoleSpec:
    """Specification for a single tapped hole.

    All distance parameters are in millimetres (assumes G21 metric mode).

    Parameters
    ----------
    x_mm             : Hole centre X coordinate in the work coordinate system.
    y_mm             : Hole centre Y coordinate in the work coordinate system.
    depth_mm         : Total tap depth (positive value; tapped in –Z direction).
    thread_pitch_mm  : Thread pitch in mm (e.g. 1.0 for M6×1.0, 1.25 for M8×1.25).
    spindle_rpm      : Spindle speed in rpm; must be > 0.
    direction        : "right" (G84, CW spindle M03) or "left" (G74, CCW spindle M04).
    rapid_z_mm       : Rapid traverse rate in Z (mm/min) used for time estimation.
                       Typical VMC: 10 000–30 000 mm/min.
    work_top_z_mm    : Absolute Z of the work surface (default 0.0).
                       Hole bottom will be at work_top_z_mm − depth_mm.
    dwell_s          : Optional dwell time (seconds) inserted after retract for
                       legacy spindle-stop sequences.  0 = no dwell.
    """
    x_mm: float
    y_mm: float
    depth_mm: float
    thread_pitch_mm: float
    spindle_rpm: float
    direction: str          # "right" | "left"
    rapid_z_mm: float = 10000.0
    work_top_z_mm: float = 0.0
    dwell_s: float = 0.0

    def __post_init__(self):
        if self.depth_mm <= 0:
            raise ValueError(f"depth_mm must be > 0, got {self.depth_mm!r}")
        if self.thread_pitch_mm <= 0:
            raise ValueError(f"thread_pitch_mm must be > 0, got {self.thread_pitch_mm!r}")
        if self.spindle_rpm <= 0:
            raise ValueError(f"spindle_rpm must be > 0, got {self.spindle_rpm!r}")
        if self.direction not in ("right", "left"):
            raise ValueError(
                f"direction must be 'right' or 'left', got {self.direction!r}"
            )
        if self.rapid_z_mm <= 0:
            raise ValueError(f"rapid_z_mm must be > 0, got {self.rapid_z_mm!r}")
        if self.dwell_s < 0:
            raise ValueError(f"dwell_s must be >= 0, got {self.dwell_s!r}")


@dataclass
class TapCycleResult:
    """Result from ``generate_tap_cycle``.

    Attributes
    ----------
    gcode                   : Complete G-code program (UTF-8 text).
    num_holes               : Total number of tapped holes in the program.
    total_machining_time_s  : Estimated cycle time in seconds.  See honest_caveat.
    computed_feed_mm_per_min: Feed rate actually used: pitch × rpm (mm/min).
    honest_caveat           : Plain-English note on assumptions and limitations.
    """
    gcode: str
    num_holes: int
    total_machining_time_s: float
    computed_feed_mm_per_min: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation (≥ 1 decimal place).

    RS-274/NGC §3.5.1: numbers may be integers or reals; the decimal point must
    be present for reals.  We use 4 decimal places for mm values then strip
    trailing zeros, keeping at least one decimal place (e.g. "2.0").
    """
    formatted = f"{v:.{decimals}f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
        if '.' not in formatted:
            formatted = formatted + '.0'
    return formatted


def _compute_feed(pitch_mm: float, rpm: float) -> float:
    """Compute rigid-tap feed rate (mm/min).

    MH 31e §1934: F = pitch × rpm.  This is the only valid coupling for rigid
    tapping; using any other value will strip threads or break the tap.
    """
    return pitch_mm * rpm


def _estimate_tap_cycle_time(
    hole: TapHoleSpec,
    feed_mm_per_min: float,
) -> float:
    """Estimate one-hole tapping cycle time (seconds).

    Model (NIST RS-274/NGC §3.8.4):
      1. Rapid from clearance (R plane) down to work top.
      2. Feed tap down to full depth at feed_mm_per_min.
      3. Spindle reverse + feed retract back to R plane at same feed rate
         (per RS-274/NGC the retract is also at F for synchronisation).
      4. Optional dwell (dwell_s) after retract.

    Acceleration ramps are NOT modelled — see honest_caveat.

    Returns estimated time in seconds.
    """
    r_plane_abs = hole.work_top_z_mm + 2.0  # conservatively assume 2 mm clearance above top
    # 1. Rapid plunge from start position to R plane (we model the R plane here
    #    as work_top + 2 mm; the user may set work_top_z_mm differently).
    # Since we don't store an explicit retract_mm field, we model the
    # tap approach as: rapid from a high position (5 mm above work_top) to work_top.
    approach_dist = 5.0  # mm conservative model
    t_rapid_down = (approach_dist / hole.rapid_z_mm) * 60.0

    # 2. Feed plunge: full depth
    t_feed_down = (hole.depth_mm / feed_mm_per_min) * 60.0

    # 3. Synchronised retract at same feed rate
    t_feed_up = (hole.depth_mm / feed_mm_per_min) * 60.0

    # 4. Optional dwell
    t_dwell = hole.dwell_s

    return t_rapid_down + t_feed_down + t_feed_up + t_dwell


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_tap_cycle(
    holes: List[TapHoleSpec],
    rigid_tap: bool = True,
    modal_state: Optional[dict] = None,
) -> TapCycleResult:
    """Generate canonical G84/G74 tapping canned-cycle G-code for a list of holes.

    The emitted program follows NIST RS-274/NGC §3.8.4 and Fanuc rigid-tap
    conventions.  Each hole uses one canned-cycle line of the form::

        (for right-hand, rigid_tap=True)
        M29 S<rpm>
        G84 X<x> Y<y> Z<z> R<r> F<f>

        (for left-hand, rigid_tap=True)
        M29 S<rpm>
        G74 X<x> Y<y> Z<z> R<r> F<f>

    The R plane is set to ``work_top_z_mm + 2.0`` mm (2 mm clearance above the
    work surface).  The Z depth is ``work_top_z_mm − depth_mm``.

    Feed rate F = thread_pitch_mm × spindle_rpm (Fanuc/NIST rigid-tap coupling).
    All holes in the list must share the same ``direction`` and pitch/rpm combo;
    ``generate_tap_cycle`` may be called multiple times for mixed setups.

    Parameters
    ----------
    holes       : list of TapHoleSpec; must be non-empty.
    rigid_tap   : if True (default), emit ``M29 S<rpm>`` before each G84/G74
                  line to engage Fanuc rigid-tap mode.
    modal_state : optional dict — informational only; does not alter output.

    Returns
    -------
    TapCycleResult

    Raises
    ------
    ValueError  : if holes list is empty.
    """
    if not holes:
        raise ValueError("holes list must not be empty")

    lines: List[str] = []
    total_time_s = 0.0

    # All holes share the first hole's feed (may differ per hole if pitches differ;
    # we compute per-hole and record the first hole's value for the result summary).
    first_feed = _compute_feed(holes[0].thread_pitch_mm, holes[0].spindle_rpm)

    # Program header
    lines.append("%")
    lines.append("(Tapping cycle — Kerf CAM / NIST RS-274/NGC G84/G74)")
    lines.append("(Generated: kerf_cam.tap_cycle.generate_tap_cycle)")
    cycle_code = "G84" if holes[0].direction == "right" else "G74"
    lines.append(f"(Cycle: {cycle_code}; feed = pitch × rpm; rigid_tap={rigid_tap})")
    lines.append("(WARNING: time estimate excludes acceleration ramps)")
    lines.append("(WARNING: floating tap holders NOT modelled — rigid timing only)")
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")

    for i, hole in enumerate(holes):
        feed = _compute_feed(hole.thread_pitch_mm, hole.spindle_rpm)
        cycle_time = _estimate_tap_cycle_time(hole, feed)
        total_time_s += cycle_time

        # Absolute Z positions
        z_bottom = hole.work_top_z_mm - hole.depth_mm     # final tap depth (negative)
        r_plane = hole.work_top_z_mm + 2.0                # 2 mm clearance above work top

        # Canned cycle code
        g_word = "G84" if hole.direction == "right" else "G74"

        lines.append(
            f"(Hole {i + 1}: X={hole.x_mm} Y={hole.y_mm}"
            f" depth={hole.depth_mm}mm pitch={hole.thread_pitch_mm}mm"
            f" rpm={hole.spindle_rpm} F={_fmt(feed)} direction={hole.direction})"
        )

        # M29 rigid-tap engage (Fanuc convention) — must precede G84/G74
        if rigid_tap:
            lines.append(f"M29 S{_fmt(hole.spindle_rpm, decimals=0)}")

        # G84/G74 canned cycle block (NIST RS-274/NGC §3.8.4)
        gline = (
            f"{g_word}"
            f" X{_fmt(hole.x_mm)}"
            f" Y{_fmt(hole.y_mm)}"
            f" Z{_fmt(z_bottom)}"
            f" R{_fmt(r_plane)}"
            f" F{_fmt(feed)}"
        )
        lines.append(gline)

        # Optional dwell after retract (legacy sequences only; uncommon in rigid tap)
        if hole.dwell_s > 0:
            lines.append(f"G4 P{_fmt(hole.dwell_s, decimals=3)}")

        lines.append("")

    # Cancel canned cycle after all holes
    lines.append("G80  (cancel canned cycle)")
    lines.append("%")

    gcode = "\n".join(lines)

    caveat = (
        "Feed rate is rigidly coupled to spindle speed: F = pitch × rpm (MH 31e §1934). "
        "A mismatch will strip threads or break the tap — always verify F and S against "
        "controller documentation before running. "
        "Cycle time estimate assumes constant feed/rapid rates with no acceleration ramps "
        "(actual cycle time will be 5–15% longer depending on servo dynamics). "
        "M29 rigid-tap engage is Fanuc 0i/30i convention; Haas uses G84 with S on same "
        "block; LinuxCNC RS-274/NGC does not require M29; Siemens uses CYCLE84(). "
        "Floating tap holders are NOT modelled — compliance relaxation of the F/S ratio "
        "is out of scope. "
        "R plane is fixed at work_top_z + 2.0 mm; adjust if a higher clearance is required."
    )

    return TapCycleResult(
        gcode=gcode,
        num_holes=len(holes),
        total_machining_time_s=round(total_time_s, 3),
        computed_feed_mm_per_min=round(first_feed, 4),
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_tap_cycle_spec = ToolSpec(
    name="cam_generate_tap_cycle",
    description=(
        "Generate G-code for a G84 (right-hand) or G74 (left-hand) rigid tapping "
        "canned cycle for one or more holes.  Follows NIST RS-274/NGC §3.8.4 and "
        "Fanuc 0i/30i rigid-tap conventions (M29 Sxxxx before G84/G74).  Feed rate "
        "is computed as pitch × rpm per Machinery's Handbook 31e §1934.  Returns "
        "the complete G-code program, hole count, estimated cycle time, the computed "
        "feed rate, and honest caveats (floating tap holders not modelled; "
        "acceleration ramps excluded from time estimate)."
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
                            "description": "Total tap depth in mm (positive value)",
                        },
                        "thread_pitch_mm": {
                            "type": "number",
                            "description": (
                                "Thread pitch in mm (e.g. 1.0 for M6×1.0, "
                                "1.25 for M8×1.25, 1.5 for M10×1.5). "
                                "Feed = pitch × rpm per MH 31e §1934."
                            ),
                        },
                        "spindle_rpm": {
                            "type": "number",
                            "description": (
                                "Spindle speed in rpm.  For rigid tapping "
                                "typical values: 500–1500 rpm for steel, "
                                "1000–3000 rpm for aluminium."
                            ),
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["right", "left"],
                            "description": (
                                "'right' → G84 (right-hand thread, CW spindle M03); "
                                "'left' → G74 (left-hand thread, CCW spindle M04)."
                            ),
                        },
                        "rapid_z_mm": {
                            "type": "number",
                            "description": (
                                "Rapid Z rate in mm/min used for time estimation "
                                "(default 10000)."
                            ),
                        },
                        "work_top_z_mm": {
                            "type": "number",
                            "description": "Absolute Z of the work surface (default 0.0)",
                        },
                        "dwell_s": {
                            "type": "number",
                            "description": (
                                "Optional dwell time in seconds after retract "
                                "(default 0 = no dwell; unusual in rigid tapping)."
                            ),
                        },
                    },
                    "required": [
                        "x_mm", "y_mm", "depth_mm",
                        "thread_pitch_mm", "spindle_rpm", "direction",
                    ],
                },
                "description": "List of holes to tap",
            },
            "rigid_tap": {
                "type": "boolean",
                "description": (
                    "If true (default), emit M29 Sxxxx before each G84/G74 block "
                    "to engage Fanuc rigid-tap mode.  Set false for controllers that "
                    "do not require M29 (e.g. LinuxCNC RS-274/NGC)."
                ),
            },
        },
        "required": ["holes"],
    },
)


@register(cam_generate_tap_cycle_spec)
async def run_cam_generate_tap_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    raw_holes = a.get("holes", [])
    if not raw_holes:
        return err_payload("holes list must not be empty", "BAD_ARGS")

    rigid_tap = bool(a.get("rigid_tap", True))

    try:
        holes = []
        for h in raw_holes:
            spec = TapHoleSpec(
                x_mm=float(h["x_mm"]),
                y_mm=float(h["y_mm"]),
                depth_mm=float(h["depth_mm"]),
                thread_pitch_mm=float(h["thread_pitch_mm"]),
                spindle_rpm=float(h["spindle_rpm"]),
                direction=str(h["direction"]),
                rapid_z_mm=float(h.get("rapid_z_mm", 10000.0)),
                work_top_z_mm=float(h.get("work_top_z_mm", 0.0)),
                dwell_s=float(h.get("dwell_s", 0.0)),
            )
            holes.append(spec)
        result = generate_tap_cycle(holes, rigid_tap=rigid_tap)
    except (KeyError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "gcode": result.gcode,
        "num_holes": result.num_holes,
        "total_machining_time_s": result.total_machining_time_s,
        "computed_feed_mm_per_min": result.computed_feed_mm_per_min,
        "honest_caveat": result.honest_caveat,
    })
