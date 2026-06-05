"""
kerf_cam.onmachine_probing — In-cycle on-machine touch-probe G-code generation.

Generates G-code for common on-machine probing (OMP) cycles used to:
  - Measure a single surface (Z or X/Y) to find actual workpiece position.
  - Find bore/boss centre and diameter via 4-point probing.
  - Find web or pocket width via 2-point probing along one axis.
  - Find a corner or edge to establish datum.
  - Set work-coordinate offset (G54..G59) from a probed datum.
  - Set tool-length offset from a probed surface.

Supported dialect styles
------------------------
Renishaw macro style (OMV / OMP / Inspection Plus):
    Uses sub-program calls O9810 (protected positioning), O9811 (surface
    measure), O9814 (bore/boss find), O9823 (tool-length measure), etc.
    The macro numbers follow the Renishaw "Fanuc Inspection Macros" naming
    convention (OMV 2009+ / Inspection Plus Rev D).  Each macro is called via
    a G65 parametric macro call: ``G65 P<nnnn> <args>``.

Fanuc G31 skip-based style:
    Uses the Fanuc G31 "skip function" in combination with G91 (incremental)
    or G90 (absolute) moves.  The probe fires when the workpiece is touched;
    the controller stores the position in machine-position registers (#5061..
    #5065 for G31 skip X/Y/Z/A/B).  WCS update is done with #nnnn arithmetic
    and G10 L2.

The implementation emits G-code blocks that are syntactically correct and
parseable; the operator is responsible for loading the correct probe tool and
ensuring probe radius / stylus length compensation is applied externally.

Honest caveats
--------------
- Renishaw macro numbers (O9810, O9814, …) match Renishaw's published
  Fanuc Inspection Macro library (OMV Rev D, Inspection Plus Rev D).
  Macro bodies must be present on the controller.  We emit the CALL;
  we do NOT embed the macro body.
- Fanuc G31 register numbers (#5061–#5069) are for Fanuc 0i-MD / 30i-B;
  other controllers (Siemens 840D, Heidenhain iTNC 530, Mazak MAZATROL)
  use different syntax and register maps — not currently supported.
- No probe radius compensation (stylus radius correction) is applied
  inside the emitted G-code; the caller must account for probe ball radius
  via the WCS offset or supply a corrected nominal position.
- Tool-length set cycle assumes the tool is already at the probe position
  and writes directly to G43 H offset via G10 L11; not all controllers
  support G10 L11 — check your Fanuc variant.
- Probe feed rate is NOT automatically derived from probe manufacturer
  specs; caller must supply a safe probing feed (typically 200–500 mm/min).
- G54..G59 (P1..P6) only; extended G54.1 Pn (Fanuc) work offsets for
  P7-P300 are out of scope.

References
----------
* Fanuc 0i-MD Operator's Manual B-64304EN §4.1.13 — G31 Skip Function.
* Renishaw Inspection Plus for Fanuc Macro B, Rev D (2020) —
  O9810 Protected Move, O9811 Measure, O9814 Bore/Boss Find, O9815 Web/Pocket,
  O9817 Pocket Corner, O9823 Tool Setter.
* NIST RS-274/NGC §3.6.9 — G10 (set work/tool offsets).
* Machinery's Handbook 31e §1173 — On-machine inspection.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Constants / types
# ---------------------------------------------------------------------------

WCS_CODES = {1: "G54", 2: "G55", 3: "G56", 4: "G57", 5: "G58", 6: "G59"}

# Renishaw Inspection Plus macro numbers (Fanuc variant, Rev D)
_RENISHAW_PROTECTED_MOVE = 9810    # O9810 — safe positioning move
_RENISHAW_MEASURE = 9811           # O9811 — single-surface measure
_RENISHAW_BORE = 9814              # O9814 — bore / boss centre-find
_RENISHAW_WEB_POCKET = 9815       # O9815 — web / pocket width-find
_RENISHAW_CORNER = 9817           # O9817 — inside corner / edge
_RENISHAW_TOOL_SETTER = 9823      # O9823 — tool-length setter


def _fmt(v: float, dp: int = 3) -> str:
    """Format float to n decimal places, stripping trailing zeros."""
    s = f"{v:.{dp}f}"
    if "." in s:
        s = s.rstrip("0")
        if s.endswith("."):
            s += "0"
    return s


# ---------------------------------------------------------------------------
# Per-operation result types
# ---------------------------------------------------------------------------

@dataclass
class MeasurementPoint:
    """A nominal probe-touch point in the work coordinate system."""
    label: str
    x: float
    y: float
    z: float
    direction: str        # "+X", "-X", "+Y", "-Y", "+Z", "-Z"
    nominal_value: float  # expected measured position on axis (mm)


@dataclass
class ProbingCycleResult:
    """Result of generating one or more probing cycles."""
    gcode: str
    measurement_points: List[MeasurementPoint]
    wcs_update_logic: str           # human-readable description of WCS update
    honest_caveat: str


# ---------------------------------------------------------------------------
# Renishaw macro emitters
# ---------------------------------------------------------------------------

class _RenishawEmitter:
    """Emit Renishaw Inspection Plus (Fanuc Macro B) probing G-code."""

    def __init__(self, probe_feed: float, retract_mm: float, safe_z: float):
        self.probe_feed = probe_feed   # mm/min
        self.retract = retract_mm      # clearance distance after touch
        self.safe_z = safe_z           # safe rapid Z height

    def protected_move(self, x: float, y: float, z: float) -> str:
        """Renishaw O9810 — protected positioning (stops if probe fires early)."""
        return (
            f"G65 P{_RENISHAW_PROTECTED_MOVE} "
            f"X{_fmt(x)} Y{_fmt(y)} Z{_fmt(z)} "
            f"F{_fmt(self.probe_feed, dp=0)}"
        )

    def measure_surface(
        self,
        x: float,
        y: float,
        z: float,
        axis: str,          # "X" | "Y" | "Z"
        distance: float,    # travel distance along axis (signed, mm)
        result_var: int,    # macro variable to receive measured value
    ) -> List[str]:
        """Renishaw O9811 — single-surface measure along one axis."""
        return [
            f"(Measure surface — axis={axis} nominal={_fmt(x if axis=='X' else y if axis=='Y' else z)})",
            self.protected_move(x, y, z),
            (
                f"G65 P{_RENISHAW_MEASURE} "
                f"{'X' if axis=='X' else 'Y' if axis=='Y' else 'Z'}"
                f"{_fmt(distance)} "
                f"F{_fmt(self.probe_feed, dp=0)} "
                f"Q{_fmt(self.retract)} "
                f"S{result_var}"   # result stored in #result_var
            ),
        ]

    def bore_boss(
        self,
        cx: float,
        cy: float,
        approach_z: float,
        bore_z: float,
        nominal_d: float,
        result_x_var: int,
        result_y_var: int,
        result_d_var: int,
        is_boss: bool = False,
    ) -> List[str]:
        """Renishaw O9814 — 4-point bore/boss centre-find."""
        cycle_mode = 1 if not is_boss else 2  # 1=bore, 2=boss
        return [
            f"({'Boss' if is_boss else 'Bore'} centre-find — nominal centre X={_fmt(cx)} Y={_fmt(cy)} D={_fmt(nominal_d)})",
            self.protected_move(cx, cy, approach_z),
            (
                f"G65 P{_RENISHAW_BORE} "
                f"X{_fmt(cx)} Y{_fmt(cy)} Z{_fmt(bore_z)} "
                f"D{_fmt(nominal_d)} "
                f"Q{_fmt(self.retract)} "
                f"F{_fmt(self.probe_feed, dp=0)} "
                f"H{cycle_mode} "   # 1=bore find, 2=boss find
                f"S{result_x_var}"  # #S=centre X, #(S+1)=centre Y, #(S+2)=diameter
            ),
        ]

    def web_pocket(
        self,
        cx: float,
        cy: float,
        probe_z: float,
        axis: str,         # "X" | "Y"
        nominal_width: float,
        approach_dist: float,
        result_centre_var: int,
        result_width_var: int,
    ) -> List[str]:
        """Renishaw O9815 — web/pocket width along X or Y."""
        half = nominal_width / 2.0
        if axis == "X":
            p1x, p1y = cx - approach_dist, cy
            p2x, p2y = cx + approach_dist, cy
        else:
            p1x, p1y = cx, cy - approach_dist
            p2x, p2y = cx, cy + approach_dist

        return [
            f"(Web/pocket width — axis={axis} nominal width={_fmt(nominal_width)} at Z={_fmt(probe_z)})",
            self.protected_move(cx, cy, probe_z + self.retract),
            (
                f"G65 P{_RENISHAW_WEB_POCKET} "
                f"X{_fmt(cx)} Y{_fmt(cy)} Z{_fmt(probe_z)} "
                f"{'X' if axis == 'X' else 'Y'}{_fmt(nominal_width)} "
                f"Q{_fmt(self.retract)} "
                f"F{_fmt(self.probe_feed, dp=0)} "
                f"S{result_centre_var}"
            ),
        ]

    def corner_edge(
        self,
        x_nom: float,
        y_nom: float,
        probe_z: float,
        axis: str,         # "X" | "Y" — axis along which corner is probed
        direction: float,  # +1 or -1 — direction to probe
        dist: float,
        result_var: int,
    ) -> List[str]:
        """Renishaw O9817 — inside corner / edge find."""
        return [
            f"(Corner/edge find — axis={axis} direction={'+'if direction>0 else '-'} at Z={_fmt(probe_z)})",
            self.protected_move(x_nom, y_nom, probe_z + self.retract),
            (
                f"G65 P{_RENISHAW_CORNER} "
                f"X{_fmt(x_nom)} Y{_fmt(y_nom)} Z{_fmt(probe_z)} "
                f"{'X' if axis == 'X' else 'Y'}{_fmt(direction * dist)} "
                f"Q{_fmt(self.retract)} "
                f"F{_fmt(self.probe_feed, dp=0)} "
                f"S{result_var}"
            ),
        ]

    def tool_length(
        self,
        tool_number: int,
        tool_z: float,
        probe_z_nominal: float,
        result_var: int,
    ) -> List[str]:
        """Renishaw O9823 — tool-length measure against table setter."""
        return [
            f"(Tool-length measure — T{tool_number} nominal setter Z={_fmt(probe_z_nominal)})",
            (
                f"G65 P{_RENISHAW_TOOL_SETTER} "
                f"T{tool_number} "
                f"Z{_fmt(probe_z_nominal)} "
                f"F{_fmt(self.probe_feed, dp=0)} "
                f"S{result_var}"
            ),
        ]


# ---------------------------------------------------------------------------
# Fanuc G31 skip-based emitters
# ---------------------------------------------------------------------------

class _FanucG31Emitter:
    """Emit Fanuc G31 skip-function probing G-code.

    Fanuc 0i-MD §4.1.13: G31 is a linear interpolation that stops when
    the skip signal (probe contact) fires.  The machine position at the
    skip point is latched into #5061 (X), #5062 (Y), #5063 (Z) etc.
    After the move completes (or skips), execution continues at the
    next block.

    WCS update: after probing, G10 L2 Pn X|Y|Z sets the WCS offset:
        G10 L2 P1 X[#5063 - #102]   ; set G54 X from probed Z datum
    (L2 = absolute, L20 = relative to current position; Fanuc 0i-MD §3.7.)
    """

    # Fanuc 0i skip register map (single G31)
    SKIP_REG_X = "#5061"
    SKIP_REG_Y = "#5062"
    SKIP_REG_Z = "#5063"

    def __init__(self, probe_feed: float, retract_mm: float, safe_z: float):
        self.probe_feed = probe_feed
        self.retract = retract_mm
        self.safe_z = safe_z

    def _g0_safe(self, x: float, y: float) -> str:
        return f"G0 G90 X{_fmt(x)} Y{_fmt(y)} Z{_fmt(self.safe_z)}"

    def measure_surface(
        self,
        x: float, y: float, probe_z_start: float,
        axis: str,
        travel: float,  # signed travel (mm) — should overshoot slightly
        nominal_var: int,
    ) -> List[str]:
        """G31 single-surface measure (Z surface or XY surface)."""
        lines = [
            f"(G31 surface measure — axis={axis})",
            self._g0_safe(x, y),
            f"G1 G90 Z{_fmt(probe_z_start)} F{_fmt(self.probe_feed, dp=0)}",
        ]
        if axis == "Z":
            lines += [
                f"G31 Z{_fmt(probe_z_start + travel)} F{_fmt(self.probe_feed, dp=0)}",
                f"#{nominal_var}={self.SKIP_REG_Z}  (save probed Z)",
                f"G0 Z{_fmt(probe_z_start + self.retract)}  (retract)",
            ]
        elif axis == "X":
            lines = [
                f"(G31 surface measure — axis=X)",
                self._g0_safe(x, y),
                f"G1 G90 Z{_fmt(probe_z_start)} F{_fmt(self.probe_feed, dp=0)}",
                f"G31 X{_fmt(x + travel)} F{_fmt(self.probe_feed, dp=0)}",
                f"#{nominal_var}={self.SKIP_REG_X}  (save probed X)",
                f"G0 X{_fmt(x + self.retract * math.copysign(1, travel))}  (retract)",
            ]
        elif axis == "Y":
            lines = [
                f"(G31 surface measure — axis=Y)",
                self._g0_safe(x, y),
                f"G1 G90 Z{_fmt(probe_z_start)} F{_fmt(self.probe_feed, dp=0)}",
                f"G31 Y{_fmt(y + travel)} F{_fmt(self.probe_feed, dp=0)}",
                f"#{nominal_var}={self.SKIP_REG_Y}  (save probed Y)",
                f"G0 Y{_fmt(y + self.retract * math.copysign(1, travel))}  (retract)",
            ]
        return lines

    def bore_centre_find(
        self,
        cx: float, cy: float, approach_z: float, bore_z: float,
        nominal_r: float,
        var_cx: int = 100, var_cy: int = 101,
    ) -> List[str]:
        """G31 4-point bore centre-find (4 G31 probes along ±X, ±Y).

        Algorithm (Renishaw OMP §4.2 method — 4-point, symmetric):
          1. Probe at +X wall → #X_hi = #5061
          2. Probe at -X wall → #X_lo = #5061
          3. centre_X = (#X_hi + #X_lo) / 2
          4. Probe at +Y wall → #Y_hi = #5062
          5. Probe at -Y wall → #Y_lo = #5062
          6. centre_Y = (#Y_hi + #Y_lo) / 2
        """
        overshoot = nominal_r + 3.0   # probe travel past nominal wall
        retract_d = self.retract

        vxhi, vxlo, vyhi, vylo = var_cx + 2, var_cx + 3, var_cx + 4, var_cx + 5

        return [
            f"(G31 4-point bore centre-find — nominal CX={_fmt(cx)} CY={_fmt(cy)} R={_fmt(nominal_r)})",
            # Move to safe Z, rapid to bore centre XY
            self._g0_safe(cx, cy),
            f"G1 G90 Z{_fmt(bore_z)} F{_fmt(self.probe_feed, dp=0)}  (plunge to probe depth)",
            # +X probe
            f"G31 X{_fmt(cx + overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe +X wall)",
            f"#{vxhi}={self.SKIP_REG_X}  (#X_hi)",
            f"G0 X{_fmt(cx)}  (retract to centre)",
            # -X probe
            f"G31 X{_fmt(cx - overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe -X wall)",
            f"#{vxlo}={self.SKIP_REG_X}  (#X_lo)",
            f"G0 X{_fmt(cx)}  (retract to centre)",
            # Compute centre X
            f"#{var_cx}=[#{vxhi}+#{vxlo}]/2  (bore centre X)",
            # +Y probe
            f"G31 Y{_fmt(cy + overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe +Y wall)",
            f"#{vyhi}={self.SKIP_REG_Y}  (#Y_hi)",
            f"G0 Y{_fmt(cy)}  (retract to centre)",
            # -Y probe
            f"G31 Y{_fmt(cy - overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe -Y wall)",
            f"#{vylo}={self.SKIP_REG_Y}  (#Y_lo)",
            f"G0 Y{_fmt(cy)}  (retract to centre)",
            # Compute centre Y
            f"#{var_cy}=[#{vyhi}+#{vylo}]/2  (bore centre Y)",
            # Retract
            f"G0 Z{_fmt(self.safe_z)}  (retract to safe Z)",
        ]

    def wcs_set_from_var(
        self,
        wcs_number: int,
        axis: str,        # "X" | "Y" | "Z"
        var: int,
        offset_mm: float = 0.0,
    ) -> List[str]:
        """G10 L2 — set WCS axis from probed variable.

        G10 L2 Pn X<value>  — set G54(n=1)..G59(n=6) X offset.
        offset_mm is added to the probed value (e.g. probe ball radius).
        """
        wcs_p = wcs_number   # G10 L2 P1 = G54, P2 = G55, …
        ax = axis.upper()
        wcs_label = WCS_CODES.get(wcs_number, f"G54+{wcs_number-1}")
        offset_expr = (
            f"[#{var}+{_fmt(offset_mm)}]" if offset_mm != 0.0
            else f"#{var}"
        )
        return [
            f"(Set {wcs_label} {ax} from probed value #{var}, offset={_fmt(offset_mm)})",
            f"G10 L2 P{wcs_p} {ax}{offset_expr}",
        ]

    def tool_length_set(
        self,
        tool_number: int,
        probe_z_var: int,
        known_setter_z: float,
    ) -> List[str]:
        """G10 L11 — set tool-length offset from probed surface.

        After probing the setter surface (stored in #probe_z_var):
            H<n> = #probe_z_var - known_setter_z
        G10 L11 P<n> Z<value> sets tool-length offset H<n>.

        Fanuc 0i-MD §3.7.4: G10 L11 P<n> R<val> sets the tool-length
        compensation memory to val.  L11 uses geometry + wear; L10 is
        geometry only.  Not all Fanuc variants support G10 L11 — verify.
        """
        h_var = probe_z_var + 10   # scratch variable for computed length
        return [
            f"(Tool-length set — T{tool_number} H{tool_number} from probed surface)",
            f"#{h_var}=[#{probe_z_var}-{_fmt(known_setter_z)}]  (compute tool length)",
            f"G10 L11 P{tool_number} R#{h_var}  (set H{tool_number} length offset)",
        ]

    def web_pocket_width(
        self,
        cx: float, cy: float, probe_z: float,
        axis: str, nominal_width: float,
        var_centre: int = 110, var_width: int = 112,
    ) -> List[str]:
        """G31 2-point web/pocket width find along X or Y."""
        half = nominal_width / 2.0
        overshoot = half + 2.0  # 2 mm past nominal wall

        if axis.upper() == "X":
            ax_reg_hi = self.SKIP_REG_X
            ax_reg_lo = self.SKIP_REG_X
            p1 = (cx + overshoot, cy)
            p2 = (cx - overshoot, cy)
            retract_dir_hi = (cx, cy)
            retract_dir_lo = (cx, cy)
            probe_hi = f"G31 X{_fmt(cx + overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe +X wall)"
            probe_lo = f"G31 X{_fmt(cx - overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe -X wall)"
        else:
            ax_reg_hi = self.SKIP_REG_Y
            ax_reg_lo = self.SKIP_REG_Y
            p1 = (cx, cy + overshoot)
            p2 = (cx, cy - overshoot)
            retract_dir_hi = (cx, cy)
            retract_dir_lo = (cx, cy)
            probe_hi = f"G31 Y{_fmt(cy + overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe +{axis} wall)"
            probe_lo = f"G31 Y{_fmt(cy - overshoot)} F{_fmt(self.probe_feed, dp=0)}  (probe -{axis} wall)"

        vhi = var_centre + 2
        vlo = var_centre + 3

        return [
            f"(G31 web/pocket width — axis={axis} nominal={_fmt(nominal_width)} at Z={_fmt(probe_z)})",
            self._g0_safe(cx, cy),
            f"G1 G90 Z{_fmt(probe_z)} F{_fmt(self.probe_feed, dp=0)}  (plunge to probe depth)",
            probe_hi,
            f"#{vhi}={ax_reg_hi}  (wall +{axis})",
            f"G0 {'X' if axis.upper()=='X' else 'Y'}{_fmt(cx if axis.upper()=='X' else cy)}  (retract to centre)",
            probe_lo,
            f"#{vlo}={ax_reg_lo}  (wall -{axis})",
            f"G0 {'X' if axis.upper()=='X' else 'Y'}{_fmt(cx if axis.upper()=='X' else cy)}  (retract to centre)",
            f"#{var_centre}=[#{vhi}+#{vlo}]/2  (pocket centre {axis})",
            f"#{var_width}=[#{vhi}-#{vlo}]  (pocket width {axis})",
            f"G0 Z{_fmt(self.safe_z)}  (retract to safe Z)",
        ]


# ---------------------------------------------------------------------------
# High-level cycle generators
# ---------------------------------------------------------------------------

def _program_header(dialect: str, title: str) -> List[str]:
    return [
        "%",
        f"(On-machine probing — {title})",
        f"(Dialect: {dialect})",
        "(Generated by kerf_cam.onmachine_probing)",
        "(CAVEAT: load touch-probe before running; verify probe-feed against mfr specs)",
        "(CAVEAT: Renishaw macro bodies must be present on the controller)",
        "(CAVEAT: G31 skip registers #5061-#5063 for Fanuc 0i-MD only)",
        "G21  (metric)",
        "G90  (absolute)",
        "G94  (feed per minute)",
        "",
    ]


def _program_footer() -> List[str]:
    return [
        "",
        "M00  (optional: pause for operator check before WCS update)",
        "M30",
        "%",
    ]


def generate_surface_measure(
    x: float, y: float, z_approach: float,
    axis: str, travel: float,
    probe_feed: float,
    retract_mm: float,
    safe_z: float,
    wcs_number: int,
    offset_mm: float,
    dialect: str,
    result_var: int = 100,
) -> ProbingCycleResult:
    """Generate a single-surface measure cycle.

    Probes one surface along the given axis and updates the WCS datum.
    """
    axis = axis.upper()
    assert axis in ("X", "Y", "Z"), f"axis must be X/Y/Z, got {axis!r}"
    assert dialect in ("renishaw", "fanuc_g31"), f"unknown dialect {dialect!r}"

    mpt = MeasurementPoint(
        label="surface",
        x=x, y=y, z=z_approach,
        direction=("+" if travel > 0 else "-") + axis,
        nominal_value=(x if axis == "X" else y if axis == "Y" else z_approach + travel),
    )

    if dialect == "renishaw":
        em = _RenishawEmitter(probe_feed, retract_mm, safe_z)
        body = em.measure_surface(x, y, z_approach, axis, travel, result_var)
        wcs_label = WCS_CODES.get(wcs_number, "G54")
        update = f"Renishaw macro stores result in #{result_var}; operator must write G10 L2 P{wcs_number} manually or use OMP routine."
    else:
        em = _FanucG31Emitter(probe_feed, retract_mm, safe_z)
        body = em.measure_surface(x, y, z_approach, axis, travel, result_var)
        wcs_body = em.wcs_set_from_var(wcs_number, axis, result_var, offset_mm)
        body += wcs_body
        wcs_label = WCS_CODES.get(wcs_number, "G54")
        update = f"G10 L2 P{wcs_number} {axis}#{result_var} sets {wcs_label} {axis} datum from probed surface (offset={offset_mm} mm)."

    lines = (
        _program_header(dialect, f"Surface Measure ({axis} axis)")
        + body
        + _program_footer()
    )

    caveat = (
        "Single-surface measure — no averaging; one probe point only. "
        f"Dialect={dialect}. Probe ball radius correction is NOT applied inline; "
        f"caller must supply offset_mm={offset_mm} as the ball-radius compensation. "
        "Ensure probe is calibrated before use."
    )

    return ProbingCycleResult(
        gcode="\n".join(lines),
        measurement_points=[mpt],
        wcs_update_logic=update,
        honest_caveat=caveat,
    )


def generate_bore_centre_find(
    cx: float, cy: float,
    approach_z: float, bore_z: float,
    nominal_diameter: float,
    probe_feed: float,
    retract_mm: float,
    safe_z: float,
    wcs_number: int,
    dialect: str,
    is_boss: bool = False,
    var_cx: int = 100,
    var_cy: int = 101,
) -> ProbingCycleResult:
    """Generate a 4-point bore (or boss) centre-find probing cycle.

    For a bore: probes 4 wall contacts (±X, ±Y) and computes centre.
    For a boss: same geometry but outside the cylinder.
    Updates WCS X and Y to the found centre.
    """
    assert dialect in ("renishaw", "fanuc_g31"), f"unknown dialect {dialect!r}"
    kind = "boss" if is_boss else "bore"
    nominal_r = nominal_diameter / 2.0

    mpts = [
        MeasurementPoint(f"{kind}_+X", cx + nominal_r, cy, bore_z, "+X", cx + nominal_r),
        MeasurementPoint(f"{kind}_-X", cx - nominal_r, cy, bore_z, "-X", cx - nominal_r),
        MeasurementPoint(f"{kind}_+Y", cx, cy + nominal_r, bore_z, "+Y", cy + nominal_r),
        MeasurementPoint(f"{kind}_-Y", cx, cy - nominal_r, bore_z, "-Y", cy - nominal_r),
    ]

    if dialect == "renishaw":
        em = _RenishawEmitter(probe_feed, retract_mm, safe_z)
        body = em.bore_boss(
            cx, cy, approach_z, bore_z, nominal_diameter,
            var_cx, var_cy, var_cy + 1,
            is_boss=is_boss,
        )
        wcs_label = WCS_CODES.get(wcs_number, "G54")
        update = (
            f"Renishaw O9814 stores centre in #{var_cx} (X) and #{var_cy+1}(Y); "
            f"diameter in #{var_cy+1}. "
            f"Operator writes G10 L2 P{wcs_number} X#{var_cx} Y#{var_cy+1} to update {wcs_label}."
        )
    else:
        em = _FanucG31Emitter(probe_feed, retract_mm, safe_z)
        body = em.bore_centre_find(
            cx, cy, approach_z, bore_z, nominal_r,
            var_cx, var_cy,
        )
        wcs_lines = (
            em.wcs_set_from_var(wcs_number, "X", var_cx, 0.0)
            + em.wcs_set_from_var(wcs_number, "Y", var_cy, 0.0)
        )
        body += wcs_lines
        wcs_label = WCS_CODES.get(wcs_number, "G54")
        update = (
            f"G31 4-point: centre X→#{var_cx}, centre Y→#{var_cy}. "
            f"G10 L2 P{wcs_number} X#{var_cx} Y#{var_cy} updates {wcs_label} X and Y."
        )

    lines = (
        _program_header(dialect, f"{'Boss' if is_boss else 'Bore'} Centre-Find")
        + list(body)
        + _program_footer()
    )

    caveat = (
        f"4-point {kind} centre-find; no eccentricity averaging (single-pass). "
        f"Probe ball radius={retract_mm} mm not applied — caller must set offset. "
        f"Dialect={dialect}. For Renishaw: O9814 macro body required on controller. "
        f"For Fanuc G31: #5061/#5062 are G31 skip registers (Fanuc 0i-MD only). "
        "Bore Z must be within the bore — caller must verify depth."
    )

    return ProbingCycleResult(
        gcode="\n".join(lines),
        measurement_points=mpts,
        wcs_update_logic=update,
        honest_caveat=caveat,
    )


def generate_web_pocket_width(
    cx: float, cy: float,
    probe_z: float,
    axis: str,
    nominal_width: float,
    probe_feed: float,
    retract_mm: float,
    safe_z: float,
    dialect: str,
    var_centre: int = 110,
    var_width: int = 112,
) -> ProbingCycleResult:
    """Generate a web or pocket width probing cycle (2-point, 1 axis)."""
    assert dialect in ("renishaw", "fanuc_g31"), f"unknown dialect {dialect!r}"
    axis = axis.upper()
    half = nominal_width / 2.0

    if axis == "X":
        mpts = [
            MeasurementPoint("wall_+X", cx + half, cy, probe_z, "+X", cx + half),
            MeasurementPoint("wall_-X", cx - half, cy, probe_z, "-X", cx - half),
        ]
    else:
        mpts = [
            MeasurementPoint("wall_+Y", cx, cy + half, probe_z, "+Y", cy + half),
            MeasurementPoint("wall_-Y", cx, cy - half, probe_z, "-Y", cy - half),
        ]

    if dialect == "renishaw":
        em = _RenishawEmitter(probe_feed, retract_mm, safe_z)
        body = em.web_pocket(
            cx, cy, probe_z, axis, nominal_width,
            approach_dist=half + 2.0,
            result_centre_var=var_centre,
            result_width_var=var_width,
        )
        update = (
            f"Renishaw O9815: pocket centre in #{var_centre}, width in #{var_width}. "
            "Operator applies WCS update manually."
        )
    else:
        em = _FanucG31Emitter(probe_feed, retract_mm, safe_z)
        body = em.web_pocket_width(
            cx, cy, probe_z, axis, nominal_width,
            var_centre, var_width,
        )
        update = (
            f"G31 2-point: pocket centre {axis}→#{var_centre}, width {axis}→#{var_width}. "
            "WCS X/Y not automatically set — caller adds G10 L2 block if needed."
        )

    lines = (
        _program_header(dialect, f"Web/Pocket Width ({axis} axis)")
        + list(body)
        + _program_footer()
    )

    caveat = (
        f"2-point web/pocket width along {axis}. No taper or angular correction. "
        f"Dialect={dialect}. Probe ball radius not compensated inline."
    )

    return ProbingCycleResult(
        gcode="\n".join(lines),
        measurement_points=mpts,
        wcs_update_logic=update,
        honest_caveat=caveat,
    )


def generate_tool_length_set(
    tool_number: int,
    setter_x: float,
    setter_y: float,
    approach_z: float,
    setter_z_nominal: float,
    probe_feed: float,
    retract_mm: float,
    safe_z: float,
    dialect: str,
    probe_z_var: int = 120,
) -> ProbingCycleResult:
    """Generate a tool-length measure and set cycle.

    Renishaw: calls O9823 (tool-setter macro).
    Fanuc G31: probes Z against setter, computes and sets H offset via G10 L11.
    """
    assert dialect in ("renishaw", "fanuc_g31"), f"unknown dialect {dialect!r}"

    mpt = MeasurementPoint(
        "tool_tip", setter_x, setter_y, setter_z_nominal, "-Z", setter_z_nominal
    )

    if dialect == "renishaw":
        em = _RenishawEmitter(probe_feed, retract_mm, safe_z)
        body = em.tool_length(tool_number, setter_z_nominal, setter_z_nominal, probe_z_var)
        update = (
            f"Renishaw O9823 sets H{tool_number} in tool-length offset table. "
            f"Result also stored in #{probe_z_var}."
        )
    else:
        em = _FanucG31Emitter(probe_feed, retract_mm, safe_z)
        # Approach + G31 Z probe
        body = em.measure_surface(
            setter_x, setter_y, approach_z, "Z",
            travel=(setter_z_nominal - approach_z - 0.5),   # overshoot by 0.5 mm
            nominal_var=probe_z_var,
        )
        body += em.tool_length_set(tool_number, probe_z_var, setter_z_nominal)
        update = (
            f"G31 probes setter at Z~{setter_z_nominal}mm; G10 L11 P{tool_number} sets H{tool_number}."
        )

    lines = (
        _program_header(dialect, f"Tool-Length Set T{tool_number}")
        + list(body)
        + _program_footer()
    )

    caveat = (
        "Tool-length set cycle. "
        "Renishaw O9823 requires the macro body present on controller. "
        "Fanuc G10 L11 not supported on all variants — verify with controller docs. "
        "Probe must be spindle-stopped (M05) before running tool-setter routine. "
        f"Setter nominal Z={setter_z_nominal}mm assumed correct; recalibrate setter regularly."
    )

    return ProbingCycleResult(
        gcode="\n".join(lines),
        measurement_points=[mpt],
        wcs_update_logic=update,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# Main entry-point (dispatches to individual generators)
# ---------------------------------------------------------------------------

_VALID_FEATURE_TYPES = frozenset({
    "surface_measure",
    "bore_centre_find",
    "boss_centre_find",
    "web_pocket_width",
    "tool_length_set",
})

_VALID_DIALECTS = frozenset({"renishaw", "fanuc_g31"})


def run_onmachine_probing(args: dict) -> dict:
    """Dispatch to the appropriate probing cycle generator.

    Returns a dict suitable for ok_payload:
      gcode             — G-code program string
      measurement_points — list of {label, x, y, z, direction, nominal_value}
      wcs_update_logic  — plain-English WCS update description
      honest_caveat     — honest limitation notes
    """
    feature_type = args.get("feature_type", "")
    if feature_type not in _VALID_FEATURE_TYPES:
        raise ValueError(
            f"feature_type must be one of {sorted(_VALID_FEATURE_TYPES)}, got {feature_type!r}"
        )

    dialect = args.get("dialect", "fanuc_g31")
    if dialect not in _VALID_DIALECTS:
        raise ValueError(
            f"dialect must be one of {sorted(_VALID_DIALECTS)}, got {dialect!r}"
        )

    probe_params = args.get("probe_params", {})
    probe_feed = float(probe_params.get("probe_feed_mm_min", 300.0))
    retract_mm = float(probe_params.get("retract_mm", 2.0))
    safe_z = float(probe_params.get("safe_z_mm", 50.0))

    nom = args.get("nominal_geometry", {})

    if feature_type == "surface_measure":
        result = generate_surface_measure(
            x=float(nom.get("x", 0.0)),
            y=float(nom.get("y", 0.0)),
            z_approach=float(nom.get("z_approach", 5.0)),
            axis=str(nom.get("axis", "Z")),
            travel=float(nom.get("travel", -10.0)),
            probe_feed=probe_feed,
            retract_mm=retract_mm,
            safe_z=safe_z,
            wcs_number=int(nom.get("wcs_number", 1)),
            offset_mm=float(nom.get("offset_mm", 0.0)),
            dialect=dialect,
            result_var=int(nom.get("result_var", 100)),
        )

    elif feature_type in ("bore_centre_find", "boss_centre_find"):
        result = generate_bore_centre_find(
            cx=float(nom.get("cx", 0.0)),
            cy=float(nom.get("cy", 0.0)),
            approach_z=float(nom.get("approach_z", 5.0)),
            bore_z=float(nom.get("bore_z", -10.0)),
            nominal_diameter=float(nom.get("nominal_diameter", 20.0)),
            probe_feed=probe_feed,
            retract_mm=retract_mm,
            safe_z=safe_z,
            wcs_number=int(nom.get("wcs_number", 1)),
            dialect=dialect,
            is_boss=(feature_type == "boss_centre_find"),
            var_cx=int(nom.get("var_cx", 100)),
            var_cy=int(nom.get("var_cy", 101)),
        )

    elif feature_type == "web_pocket_width":
        result = generate_web_pocket_width(
            cx=float(nom.get("cx", 0.0)),
            cy=float(nom.get("cy", 0.0)),
            probe_z=float(nom.get("probe_z", -5.0)),
            axis=str(nom.get("axis", "X")),
            nominal_width=float(nom.get("nominal_width", 20.0)),
            probe_feed=probe_feed,
            retract_mm=retract_mm,
            safe_z=safe_z,
            dialect=dialect,
            var_centre=int(nom.get("var_centre", 110)),
            var_width=int(nom.get("var_width", 112)),
        )

    elif feature_type == "tool_length_set":
        result = generate_tool_length_set(
            tool_number=int(nom.get("tool_number", 1)),
            setter_x=float(nom.get("setter_x", 0.0)),
            setter_y=float(nom.get("setter_y", 0.0)),
            approach_z=float(nom.get("approach_z", 50.0)),
            setter_z_nominal=float(nom.get("setter_z_nominal", 0.0)),
            probe_feed=probe_feed,
            retract_mm=retract_mm,
            safe_z=safe_z,
            dialect=dialect,
            probe_z_var=int(nom.get("probe_z_var", 120)),
        )

    else:
        raise ValueError(f"unhandled feature_type: {feature_type!r}")

    return {
        "gcode": result.gcode,
        "measurement_points": [
            {
                "label": mp.label,
                "x": mp.x,
                "y": mp.y,
                "z": mp.z,
                "direction": mp.direction,
                "nominal_value": mp.nominal_value,
            }
            for mp in result.measurement_points
        ],
        "wcs_update_logic": result.wcs_update_logic,
        "honest_caveat": result.honest_caveat,
    }


# ---------------------------------------------------------------------------
# LLM Tool spec + handler
# ---------------------------------------------------------------------------

cam_onmachine_probing_spec = ToolSpec(
    name="cam_onmachine_probing",
    description=(
        "Generate in-cycle on-machine touch-probe G-code for common probing operations. "
        "Supports single-surface measure, bore/boss 4-point centre-find, "
        "web/pocket width (2-point), and tool-length set. "
        "Two dialect styles: 'renishaw' (Inspection Plus macro calls O9810/O9811/O9814/"
        "O9815/O9823 via G65) and 'fanuc_g31' (Fanuc G31 skip function + G10 L2/L11 "
        "WCS/TLO update). "
        "Returns: probing G-code program, measurement points list (nominal positions), "
        "WCS update logic description, and honest caveats. "
        "Reference: Renishaw Inspection Plus Rev D; Fanuc 0i-MD §4.1.13; NIST RS-274/NGC §3.6.9; "
        "MH 31e §1173."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "feature_type": {
                "type": "string",
                "enum": [
                    "surface_measure",
                    "bore_centre_find",
                    "boss_centre_find",
                    "web_pocket_width",
                    "tool_length_set",
                ],
                "description": (
                    "Probing cycle type: "
                    "'surface_measure' — probe one surface to find its position; "
                    "'bore_centre_find' — 4-point probe inside bore to find centre + diameter; "
                    "'boss_centre_find' — 4-point probe around boss to find centre; "
                    "'web_pocket_width' — 2-point probe to find web or pocket width + centre; "
                    "'tool_length_set' — probe tool tip against setter to set H offset."
                ),
            },
            "dialect": {
                "type": "string",
                "enum": ["renishaw", "fanuc_g31"],
                "description": (
                    "'renishaw' — emits G65 P9810/P9811/P9814/P9815/P9823 macro calls "
                    "(Renishaw Inspection Plus for Fanuc Macro B, Rev D); "
                    "'fanuc_g31' — emits Fanuc G31 skip-function moves + G10 L2 WCS update "
                    "(Fanuc 0i-MD §4.1.13; skip registers #5061–#5063). Default: fanuc_g31."
                ),
            },
            "nominal_geometry": {
                "type": "object",
                "description": (
                    "Nominal geometry for the probing cycle — fields depend on feature_type: "
                    "surface_measure: x, y, z_approach, axis (X/Y/Z), travel (signed mm), "
                    "  wcs_number (1-6), offset_mm (ball radius), result_var (macro var #). "
                    "bore_centre_find / boss_centre_find: cx, cy, approach_z, bore_z, "
                    "  nominal_diameter (mm), wcs_number, var_cx, var_cy (macro var #s). "
                    "web_pocket_width: cx, cy, probe_z, axis (X/Y), nominal_width (mm), "
                    "  var_centre, var_width (macro var #s). "
                    "tool_length_set: tool_number, setter_x, setter_y, approach_z, "
                    "  setter_z_nominal (mm), probe_z_var (macro var #)."
                ),
                "additionalProperties": True,
            },
            "probe_params": {
                "type": "object",
                "properties": {
                    "probe_feed_mm_min": {
                        "type": "number",
                        "description": "Probing feed rate in mm/min (default 300). "
                        "Renishaw OMP recommended: 200–500 mm/min.",
                    },
                    "retract_mm": {
                        "type": "number",
                        "description": "Clearance distance to retract after touch (default 2.0 mm).",
                    },
                    "safe_z_mm": {
                        "type": "number",
                        "description": "Safe rapid Z height in WCS (default 50.0 mm).",
                    },
                },
                "description": "Probe hardware + motion parameters.",
            },
        },
        "required": ["feature_type", "nominal_geometry"],
    },
)


@register(cam_onmachine_probing_spec)
async def run_cam_onmachine_probing(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args JSON: {e}", "BAD_ARGS")

    try:
        result = run_onmachine_probing(a)
    except (KeyError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload(result)
