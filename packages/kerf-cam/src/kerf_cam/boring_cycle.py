"""
kerf_cam.boring_cycle — G85/G86/G89 boring canned cycles (single-point boring bar).

Reference standards
-------------------
* NIST RS-274/NGC §3.8.4 — Canned cycles:
  G85 format: ``G85 X<x> Y<y> Z<z> R<r> F<f>``
    On-the-way-in: rapid to R, feed to Z.
    On-the-way-out: feed back to R (spindle remains ON).
    Use case: precision bore — tool feeds in both directions, leaving the
    best possible bore finish on the wall on the outward stroke.

  G86 format: ``G86 X<x> Y<y> Z<z> R<r> F<f>``
    On-the-way-in: rapid to R, feed to Z.
    On-the-way-out: spindle STOP (M05) then rapid to R.
    Use case: single-point boring bar where the cutting edge must not drag
    on the bore wall during retract.  The stopped spindle allows the bar to
    be lifted clear without wall contact (operator must ensure sufficient
    radial clearance).

  G89 format: ``G89 X<x> Y<y> Z<z> R<r> P<dwell_us> F<f>``
    On-the-way-in: rapid to R, feed to Z, DWELL P microseconds.
    On-the-way-out: feed back to R (spindle remains ON).
    Use case: finish bore — the dwell at the bottom allows the bore bar to
    spring back to true centre before feeding out, yielding the best Ra.
    RS-274/NGC §3.5.3 / §3.8.4: P is in milliseconds for G4 but in
    **microseconds** for the G89 P-word (NIST convention, unlike Fanuc which
    uses milliseconds — see honest_caveat).

* Machinery's Handbook 31e §1162 — Boring operations:
  Surface finish guidance (single-point boring bar):
    G85 (feed-out):     Ra ≈ 0.8 μm class (fine bore)
    G86 (spindle-stop): Ra ≈ 1.6 μm class (semi-finish bore; drag marks on wall
                        if clearance geometry is not correct)
    G89 (dwell-out):    Ra ≈ 0.4 μm class (finish bore; spring-back centring
                        before feed-out gives best cylindricity)
  These are representative Ra bands for a correctly ground boring bar at
  recommended cutting data.  Actual finish depends on workpiece material,
  insert geometry, SFM, chip load, and machine rigidity.

Honest caveats
--------------
- Assumes single-point boring bar only; multi-edge boring heads (e.g.
  Sandvik CoroBore 825) require different strategies — out of scope.
- No roughing/finishing pass differentiation (single-pass model only).
- Cycle time estimate uses constant feed/rapid rates; acceleration ramps are
  NOT modelled (add 5–15% for real machine dynamics).
- G89 P-word is in microseconds per NIST RS-274/NGC §3.8.4; Fanuc 0i/30i
  uses milliseconds for the same P-word — verify with your controller before
  running.  Kerf emits microseconds (NIST convention).
- G86 spindle-stop (M05) is emitted inline; some controllers handle the
  stop automatically inside the canned cycle.  Check controller docs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Surface finish Ra class per MH 31e §1162 (single-point boring bar)
_SURFACE_FINISH_CLASS = {
    "G85": "Ra 0.8 μm (fine bore — feed-out with spindle on)",
    "G86": "Ra 1.6 μm (semi-finish bore — spindle-stop retract; may show drag marks)",
    "G89": "Ra 0.4 μm (finish bore — dwell at bottom centres bar before feed-out)",
}

_VALID_CYCLE_TYPES = frozenset({"G85", "G86", "G89"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BoreHoleSpec:
    """Specification for a single boring cycle hole.

    All distance parameters are in millimetres (assumes G21 metric mode).
    Feed rate is in mm/min.  Spindle speed is in rpm.

    Parameters
    ----------
    x_mm            : Hole centre X coordinate in the work coordinate system.
    y_mm            : Hole centre Y coordinate in the work coordinate system.
    depth_mm        : Bore depth (positive value; machined in –Z direction).
    feed_mm_per_min : Boring feed rate in mm/min (both in and out for G85/G89).
    spindle_rpm     : Spindle speed in rpm (> 0).
    rapid_z_mm      : Rapid traverse rate in Z (mm/min) used for time estimation.
                      Typical VMC: 10 000–30 000 mm/min.
    work_top_z_mm   : Absolute Z of the work surface (default 0.0).
                      Hole bottom will be at work_top_z_mm − depth_mm.
    cycle_type      : One of "G85", "G86", "G89".
                      G85 = feed-out (precision bore, Ra 0.8 μm class).
                      G86 = spindle-stop-then-rapid-out (single-point, Ra 1.6 μm class).
                      G89 = dwell-then-feed-out (finish bore, Ra 0.4 μm class).
    dwell_s         : Dwell time at hole bottom in **seconds** (G89 only; converted
                      to microseconds in emitted P-word per NIST RS-274/NGC §3.8.4).
                      Ignored for G85/G86.  Default 0.0.
    retract_mm      : Clearance height above work_top_z_mm for the R plane (mm).
                      Must be >= 0.  Default 2.0.
    """
    x_mm: float
    y_mm: float
    depth_mm: float
    feed_mm_per_min: float
    spindle_rpm: float
    rapid_z_mm: float = 10000.0
    work_top_z_mm: float = 0.0
    cycle_type: str = "G85"
    dwell_s: float = 0.0
    retract_mm: float = 2.0

    def __post_init__(self):
        if self.depth_mm <= 0:
            raise ValueError(f"depth_mm must be > 0, got {self.depth_mm!r}")
        if self.feed_mm_per_min <= 0:
            raise ValueError(f"feed_mm_per_min must be > 0, got {self.feed_mm_per_min!r}")
        if self.spindle_rpm <= 0:
            raise ValueError(f"spindle_rpm must be > 0, got {self.spindle_rpm!r}")
        if self.rapid_z_mm <= 0:
            raise ValueError(f"rapid_z_mm must be > 0, got {self.rapid_z_mm!r}")
        if self.cycle_type not in _VALID_CYCLE_TYPES:
            raise ValueError(
                f"cycle_type must be one of {sorted(_VALID_CYCLE_TYPES)}, "
                f"got {self.cycle_type!r}"
            )
        if self.dwell_s < 0:
            raise ValueError(f"dwell_s must be >= 0, got {self.dwell_s!r}")
        if self.retract_mm < 0:
            raise ValueError(f"retract_mm must be >= 0, got {self.retract_mm!r}")


@dataclass
class BoreCycleResult:
    """Result from ``generate_boring_cycle``.

    Attributes
    ----------
    gcode                  : Complete G-code program (UTF-8 text).
    num_holes              : Total number of holes in the program.
    total_machining_time_s : Estimated cycle time in seconds.  See honest_caveat.
    surface_finish_class   : Ra class string per MH 31e §1162.
    honest_caveat          : Plain-English note on assumptions and limitations.
    """
    gcode: str
    num_holes: int
    total_machining_time_s: float
    surface_finish_class: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation (≥ 1 decimal place).

    RS-274/NGC §3.5.1: numbers may be integers or reals; the decimal point must
    be present for reals.  Uses 4 decimal places for mm values then strips
    trailing zeros, keeping at least one decimal place (e.g. "2.0").
    """
    formatted = f"{v:.{decimals}f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
        if '.' not in formatted:
            formatted = formatted + '.0'
    return formatted


def _dwell_s_to_p_word(dwell_s: float) -> int:
    """Convert dwell seconds to NIST RS-274/NGC G89 P-word (microseconds).

    NIST RS-274/NGC §3.8.4: the P-word in boring canned cycles (G89) is in
    microseconds.  Note: G4 (dwell word) uses P in seconds; G89 P is different.
    Returns the integer microsecond value (minimum 1 μs if dwell_s > 0).
    """
    us = int(round(dwell_s * 1_000_000))
    return max(us, 1) if dwell_s > 0 else 0


def _estimate_boring_cycle_time(hole: BoreHoleSpec) -> float:
    """Estimate one-hole boring cycle time in seconds.

    Model (NIST RS-274/NGC §3.8.4):
      1. Rapid from clearance plane (R = work_top + retract_mm) down to work top.
         (We model approach as from 5 mm above R plane — conservative.)
      2. Feed boring stroke: depth_mm / feed_mm_per_min.
      3. Dwell at bottom (G89 only): dwell_s.
      4a. G85/G89: feed retract: depth_mm / feed_mm_per_min (feed-out).
      4b. G86: spindle stop (~0.5 s typical) + rapid retract from Z to R plane.
      5. Rapid to R plane (if not already at R after step 4b).

    Acceleration ramps are NOT modelled.

    Returns estimated time in seconds.
    """
    depth = hole.depth_mm
    feed = hole.feed_mm_per_min
    rapid = hole.rapid_z_mm
    r_plane_abs = hole.work_top_z_mm + hole.retract_mm

    # Step 1: rapid approach from 5 mm above R plane to R plane
    approach_dist = 5.0
    t_rapid_down = (approach_dist / rapid) * 60.0

    # Step 2: feed boring stroke (down to depth)
    t_feed_down = (depth / feed) * 60.0

    # Step 3: dwell
    t_dwell = hole.dwell_s if hole.cycle_type == "G89" else 0.0

    # Step 4 & 5: retract
    if hole.cycle_type == "G86":
        # spindle stop estimate: ~0.5 s, then rapid from Z bottom to R plane
        t_spindle_stop = 0.5
        z_bottom_abs = hole.work_top_z_mm - depth
        retract_dist = abs(r_plane_abs - z_bottom_abs)
        t_retract = t_spindle_stop + (retract_dist / rapid) * 60.0
    else:
        # G85 / G89: feed retract from Z bottom back to R plane
        t_retract = (depth / feed) * 60.0

    return t_rapid_down + t_feed_down + t_dwell + t_retract


def _surface_finish_class(holes: List[BoreHoleSpec]) -> str:
    """Return the dominant surface finish class string.

    If all holes share the same cycle type, return that type's class.
    Otherwise return the best (finest) Ra class present (G89 > G85 > G86).
    """
    types_present = {h.cycle_type for h in holes}
    if len(types_present) == 1:
        return _SURFACE_FINISH_CLASS[types_present.pop()]
    # Mixed: report all present, sorted best-to-worst
    order = ["G89", "G85", "G86"]
    parts = [_SURFACE_FINISH_CLASS[t] for t in order if t in types_present]
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_boring_cycle(
    holes: List[BoreHoleSpec],
    modal_state: Optional[dict] = None,
) -> BoreCycleResult:
    """Generate canonical G85/G86/G89 boring canned-cycle G-code.

    The emitted program follows NIST RS-274/NGC §3.8.4.  Each hole uses
    one canned-cycle line of the form::

        (G85 — feed-out)
        G85 X<x> Y<y> Z<z> R<r> F<f>

        (G86 — spindle-stop then rapid retract)
        M03 S<rpm>
        G86 X<x> Y<y> Z<z> R<r> F<f>
        (M05 spindle-stop is handled inside the G86 cycle by the controller;
         an explicit M05 is emitted after G80 cancel for clarity)

        (G89 — dwell at bottom then feed-out)
        G89 X<x> Y<y> Z<z> R<r> P<dwell_us> F<f>

    All holes are closed with ``G80`` (cancel canned cycle) and ``M05``
    (spindle stop / end of boring session).

    Parameters
    ----------
    holes       : list of BoreHoleSpec; must be non-empty.  Mixed cycle types
                  are supported (each hole carries its own cycle_type).
    modal_state : optional dict — informational only; does not alter output.

    Returns
    -------
    BoreCycleResult

    Raises
    ------
    ValueError  : if holes list is empty.
    """
    if not holes:
        raise ValueError("holes list must not be empty")

    lines: List[str] = []
    total_time_s = 0.0

    # Determine dominant cycle type for header comment
    cycle_types_present = sorted({h.cycle_type for h in holes})

    # Program header
    lines.append("%")
    lines.append(
        f"(Boring cycle — Kerf CAM / NIST RS-274/NGC §3.8.4)"
    )
    lines.append(
        f"(Cycles: {', '.join(cycle_types_present)}; "
        "Generated: kerf_cam.boring_cycle.generate_boring_cycle)"
    )
    lines.append("(CAVEAT: single-point boring bar assumed; no roughing/finishing differentiation)")
    lines.append("(CAVEAT: G89 P-word in microseconds per NIST; Fanuc uses milliseconds — verify)")
    lines.append("(WARNING: time estimate excludes acceleration ramps)")
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")

    for i, hole in enumerate(holes):
        hole_time = _estimate_boring_cycle_time(hole)
        total_time_s += hole_time

        # Absolute Z values
        z_bottom = hole.work_top_z_mm - hole.depth_mm   # bore bottom (negative offset)
        r_plane = hole.work_top_z_mm + hole.retract_mm   # retract / clearance Z

        lines.append(
            f"(Hole {i + 1}: {hole.cycle_type} X={hole.x_mm} Y={hole.y_mm}"
            f" depth={hole.depth_mm}mm R={_fmt(r_plane)} F={_fmt(hole.feed_mm_per_min)}"
            f" S={_fmt(hole.spindle_rpm, decimals=0)} rpm)"
        )

        # Spindle on (M03) before boring cycle
        lines.append(f"M03 S{_fmt(hole.spindle_rpm, decimals=0)}")

        if hole.cycle_type == "G85":
            # G85: feed in, feed out (precision bore)
            gline = (
                f"G85"
                f" X{_fmt(hole.x_mm)}"
                f" Y{_fmt(hole.y_mm)}"
                f" Z{_fmt(z_bottom)}"
                f" R{_fmt(r_plane)}"
                f" F{_fmt(hole.feed_mm_per_min)}"
            )
            lines.append(gline)

        elif hole.cycle_type == "G86":
            # G86: feed in, spindle stop, rapid out
            gline = (
                f"G86"
                f" X{_fmt(hole.x_mm)}"
                f" Y{_fmt(hole.y_mm)}"
                f" Z{_fmt(z_bottom)}"
                f" R{_fmt(r_plane)}"
                f" F{_fmt(hole.feed_mm_per_min)}"
            )
            lines.append(gline)
            # Explicit M05 for clarity; most controllers stop spindle inside G86
            lines.append("M05  (spindle stop — G86 drag-free retract)")

        elif hole.cycle_type == "G89":
            # G89: feed in, dwell, feed out (finish bore)
            p_us = _dwell_s_to_p_word(hole.dwell_s)
            gline = (
                f"G89"
                f" X{_fmt(hole.x_mm)}"
                f" Y{_fmt(hole.y_mm)}"
                f" Z{_fmt(z_bottom)}"
                f" R{_fmt(r_plane)}"
                f" P{p_us}"
                f" F{_fmt(hole.feed_mm_per_min)}"
            )
            lines.append(gline)

        lines.append("")

    # Cancel canned cycle and stop spindle
    lines.append("G80  (cancel canned cycle)")
    lines.append("M05  (spindle stop)")
    lines.append("%")

    gcode = "\n".join(lines)

    finish_class = _surface_finish_class(holes)

    caveat = (
        "Assumes single-point boring bar only — multi-edge boring heads "
        "(e.g. Sandvik CoroBore 825) require different strategy; out of scope. "
        "No roughing/finishing pass differentiation: single-pass model only. "
        "Cycle time estimate uses constant feed/rapid rates; acceleration ramps "
        "are NOT modelled (add 5–15% for real machine dynamics). "
        "G89 P-word is in microseconds per NIST RS-274/NGC §3.8.4; "
        "Fanuc 0i/30i uses milliseconds for the same P-word — "
        "verify with your controller before running. "
        "G86 spindle-stop (M05) is emitted inline after the cycle block; "
        "some controllers handle M05 automatically inside G86 — check controller docs. "
        f"Surface finish class (MH 31e §1162): {finish_class}."
    )

    return BoreCycleResult(
        gcode=gcode,
        num_holes=len(holes),
        total_machining_time_s=round(total_time_s, 3),
        surface_finish_class=finish_class,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_boring_cycle_spec = ToolSpec(
    name="cam_generate_boring_cycle",
    description=(
        "Generate G-code for G85/G86/G89 boring canned cycles for one or more holes. "
        "G85 = feed-out (precision bore, Ra 0.8 μm class); "
        "G86 = spindle-stop-then-rapid-out (single-point boring bar, Ra 1.6 μm class); "
        "G89 = dwell-then-feed-out (finish bore, Ra 0.4 μm class). "
        "Follows NIST RS-274/NGC §3.8.4 and Machinery's Handbook 31e §1162. "
        "Returns the complete G-code program, hole count, estimated cycle time, "
        "surface finish class, and honest caveats (single-point bar assumed; "
        "G89 P-word in microseconds per NIST; acceleration ramps excluded from "
        "time estimate)."
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
                            "description": "Bore depth in mm (positive value)",
                        },
                        "feed_mm_per_min": {
                            "type": "number",
                            "description": "Boring feed rate in mm/min",
                        },
                        "spindle_rpm": {
                            "type": "number",
                            "description": (
                                "Spindle speed in rpm. "
                                "Typical boring bar: 500–3000 rpm depending on "
                                "bore diameter, material, and bar overhang."
                            ),
                        },
                        "cycle_type": {
                            "type": "string",
                            "enum": ["G85", "G86", "G89"],
                            "description": (
                                "G85 = feed-out precision bore (Ra 0.8 μm class); "
                                "G86 = spindle-stop + rapid-out (Ra 1.6 μm class); "
                                "G89 = dwell + feed-out finish bore (Ra 0.4 μm class)."
                            ),
                        },
                        "dwell_s": {
                            "type": "number",
                            "description": (
                                "Dwell time at hole bottom in seconds (G89 only; "
                                "converted to microseconds for P-word per NIST §3.8.4). "
                                "Ignored for G85/G86. Default 0.0."
                            ),
                        },
                        "retract_mm": {
                            "type": "number",
                            "description": (
                                "Clearance height above work surface for R plane in mm "
                                "(e.g. 2.0 means R = work_top_z + 2.0). Default 2.0."
                            ),
                        },
                        "rapid_z_mm": {
                            "type": "number",
                            "description": (
                                "Rapid Z traverse rate in mm/min used for time "
                                "estimation (default 10000)."
                            ),
                        },
                        "work_top_z_mm": {
                            "type": "number",
                            "description": "Absolute Z of the work surface (default 0.0)",
                        },
                    },
                    "required": [
                        "x_mm", "y_mm", "depth_mm",
                        "feed_mm_per_min", "spindle_rpm", "cycle_type",
                    ],
                },
                "description": "List of holes to bore",
            },
        },
        "required": ["holes"],
    },
)


@register(cam_generate_boring_cycle_spec)
async def run_cam_generate_boring_cycle(ctx: ProjectCtx, args: bytes) -> str:
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
            spec = BoreHoleSpec(
                x_mm=float(h["x_mm"]),
                y_mm=float(h["y_mm"]),
                depth_mm=float(h["depth_mm"]),
                feed_mm_per_min=float(h["feed_mm_per_min"]),
                spindle_rpm=float(h["spindle_rpm"]),
                cycle_type=str(h["cycle_type"]),
                dwell_s=float(h.get("dwell_s", 0.0)),
                retract_mm=float(h.get("retract_mm", 2.0)),
                rapid_z_mm=float(h.get("rapid_z_mm", 10000.0)),
                work_top_z_mm=float(h.get("work_top_z_mm", 0.0)),
            )
            holes.append(spec)
        result = generate_boring_cycle(holes)
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
        "surface_finish_class": result.surface_finish_class,
        "honest_caveat": result.honest_caveat,
    })
