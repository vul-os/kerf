"""
cam_lathe_profile — emit Fanuc-dialect RS-274 lathe G-code from a 2-D turning profile.

Algorithm & references
----------------------
Implements the canonical RS-274/NGC word-address format for turning centres
(NIST RS-274/NGC Interpreter Version 3, Kramer, Proctor & Messina 2000, §3) with
Fanuc 0i-TF/Series 30i turning-centre dialect extensions (Smid, P. "CNC Programming
Handbook", 3rd ed., Industrial Press 2008, §6):

  G71 P__ Q__ U__ W__ D__ F__ S__
       — Outer-diameter peel / rough turning cycle (Type I).
         P = first-block number of finish profile (ns); Q = last block (nf);
         U = diameter finish allowance (X, signed); W = axial finish allowance (Z);
         D = depth of cut per pass (µm integer in many Fanuc variants; mm here for
             clarity — callers should convert to controller units as needed);
         F = roughing feed (mm/rev); S = roughing spindle speed (RPM, G97 modal).
         Ref: Smid 2008 §6.4; Fanuc 0i-TF OM §14.2.

  G70 P__ Q__
       — Finishing cycle (executes profile blocks ns–nf after G71).
         F and S may be re-specified on the G70 block for a lighter finishing pass.
         Ref: Smid 2008 §6.5; Fanuc 0i-TF OM §14.3.

  G96 S__
       — Constant surface speed (CSS) mode; S = surface speed in m/min.
         Ref: Smid 2008 §6.2; NIST RS-274/NGC §3.6.

  G97 S__
       — Constant spindle speed (RPM); cancels G96.
         Ref: Smid 2008 §6.2.

  G18        — ZX plane select (required for turning; NIST RS-274 §3.9).
  G21        — metric mode.
  G40        — cancel tool-nose-radius compensation.
  G54        — work coordinate system 1 (WCS).
  M03 S__    — spindle on, CW.
  M05        — spindle stop.
  M06 T__    — tool change.
  M30        — program end + rewind.

Input model
-----------
A *profile* is a list of (Z, X_radius) tuples where:
  Z          — axial position (mm, positive towards tailstock from chuck face).
  X_radius   — radius in mm (NOT diameter; must be >= 0).

The profile must be at least 2 points.  Z values must be monotone (either
strictly increasing or strictly decreasing).

For a simple OD turning job the first point has the largest X (nearest chuck face /
largest diameter end) and Z decreases as the tool traverses towards the end of the
part.  The module does not enforce chirality; reversed profiles are also accepted.

Stock
-----
stock_x_mm  — initial stock radius (mm); must be > max(X in profile).
stock_z_mm  — optional axial overhang / facing stock (mm); default 2.0.

Cutting parameters (steel, uncoated carbide defaults)
------------------------------------------------------
sfm         — recommended surface speed (ft/min); default 600 for steel.
              Converted to m/min: css_m_per_min = sfm × 0.3048.
              Ref: Smid 2008 §6.1 Table 6-1; Machinery's Handbook 30th ed.
ipr         — feed per revolution (inch/rev) = 0.25 mm (default, light roughing).
              Ref: Smid 2008 §6.1 Table 6-2.

Emitted program structure
-------------------------
  (header comment)
  Oxxxx                — program number
  G18 G21 G40 G54      — preamble
  G28 U0.              — reference return X
  T01 M06              — tool change
  G97 S<rpm> M03       — spindle on, constant RPM
  G00 X<stock> Z<approach>   — rapid to start
  G71 P100 Q200 U<u_allow> W<w_allow> D<doc> F<feed> S<rpm>
  G70 P100 Q200 F<finish_feed>
  N100 G00 X<x0> Z<z0>       — profile start (ns block)
  N110 G01 X<x1> Z<z1> F<feed>
  ...
  N200 G01 X<xn> Z<zn>       — profile end (nf block)
  G00 X<clearance> Z<clearance>   — retract
  M05                              — spindle stop
  M30                              — program end

Honest scope limits
-------------------
* **Fanuc 0i-TF / Series 30i dialect ONLY.**
  Heidenhain TURN PLUS, Siemens ShopTurn CYCLE95/CYCLE93, Mazak SmoothTurn,
  Okuma OSP-P300L, and Mitsubishi MELDAS lathe-specific cycle codes are NOT
  emitted and are entirely out of scope.
* G71 Type II (concave profiles, undercuts) is NOT emitted.  Only Type I
  (monotone-decreasing X profile without concavities) is supported.  Concave
  profiles will produce a G71 block that references the correct profile range,
  but real controllers may reject non-monotone profiles; a warning is appended.
* G72 (facing cycle), G73 (pattern repeat cycle), G74 (peck drilling), G75
  (grooving cycle) are NOT implemented in this module — use turning.cycles
  for G72/G75 equivalents.
* G96 LIMS (max-RPM limiter for CSS mode) is not appended; callers should add
  ``G50 S<lims>`` before G96 blocks if required by the controller.
* Numbers are formatted to 4 decimal places (0.0001 mm = 0.1 µm precision).
* No cutter-nose-radius compensation (CNRC) offsets are applied; G41/G42 blocks
  must be inserted by the caller if compensation registers are set on the machine.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PI = math.pi

# Default cutting parameters — steel, uncoated carbide insert
# Smid 2008 §6.1 Table 6-1 recommends 400–800 SFM for medium-carbon steel.
_DEFAULT_SFM = 600.0          # surface feet per minute (steel recommendation)
_DEFAULT_IPR = 0.25           # mm (≈ 0.010 in/rev) roughing feed
_DEFAULT_FINISH_IPR = 0.10    # mm (≈ 0.004 in/rev) finishing feed
_DEFAULT_DOC_MM = 2.0         # radial depth of cut per pass
_DEFAULT_FINISH_ALLOW_X = 0.5 # diameter finish allowance (U word, mm)
_DEFAULT_FINISH_ALLOW_Z = 0.1 # axial finish allowance (W word, mm)
_DEFAULT_RETRACT_MM = 5.0     # rapid clearance
_DEFAULT_STOCK_Z_MM = 2.0     # facing stock overhang
_RPM_MIN = 50.0
_RPM_MAX = 4000.0

# G71 profile block numbering
_NS_BLOCK = 100  # first profile block (P word on G71)
_NF_STEP = 10    # block-number increment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float in Fanuc decimal-programming style (trailing zeros stripped).

    >>> _fmt(10.0)
    '10.'
    >>> _fmt(1.2345678)
    '1.2346'
    >>> _fmt(2000.0, 0)
    '2000'
    """
    if decimals == 0:
        return str(int(round(v)))
    s = f"{v:.{decimals}f}"
    int_part, frac_part = s.split(".")
    frac_stripped = frac_part.rstrip("0")
    return f"{int_part}.{frac_stripped}" if frac_stripped else f"{int_part}."


def _sfm_to_css(sfm: float) -> float:
    """Convert surface feet per minute to metres per minute."""
    return sfm * 0.3048


def _calc_rpm(css_m_per_min: float, radius_mm: float) -> float:
    """Compute spindle RPM from constant surface speed and current radius.

    rpm = (CSS_m_per_min × 1000) / (π × diameter_mm)
        = (CSS_m_per_min × 1000) / (π × 2 × radius_mm)

    Clamped to [_RPM_MIN, _RPM_MAX].
    Ref: Smid 2008 §6.2; Machinery's Handbook 30th ed.
    """
    if radius_mm <= 0:
        return _RPM_MAX
    diam_mm = 2.0 * radius_mm
    rpm = (css_m_per_min * 1000.0) / (_PI * diam_mm)
    return max(_RPM_MIN, min(_RPM_MAX, rpm))


def _dia(radius_mm: float) -> float:
    """Radius → diameter (Fanuc lathes use diameter programming on X axis)."""
    return 2.0 * radius_mm


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class LatheProgram:
    """Container for an emitted lathe G-code program.

    Attributes
    ----------
    text        : complete G-code program as a single string (newline-terminated)
    line_count  : number of non-blank lines in ``text``
    warnings    : non-fatal notices (e.g. concave profile segments)
    css_m_per_min : computed constant surface speed used
    roughing_rpm  : initial roughing spindle RPM (at largest diameter)
    feed_mm_rev   : roughing feed per revolution (mm/rev)
    finish_feed_mm_rev : finishing feed per revolution (mm/rev)
    pass_count    : estimated number of roughing passes
    """
    text: str
    line_count: int
    warnings: list[str] = field(default_factory=list)
    css_m_per_min: float = 0.0
    roughing_rpm: float = 0.0
    feed_mm_rev: float = 0.0
    finish_feed_mm_rev: float = 0.0
    pass_count: int = 0


# ---------------------------------------------------------------------------
# Main emitter
# ---------------------------------------------------------------------------

def emit_lathe_gcode(
    profile: Sequence[tuple[float, float]],
    stock_x_mm: float,
    *,
    stock_z_mm: float = _DEFAULT_STOCK_Z_MM,
    tool_id: int = 1,
    sfm: float = _DEFAULT_SFM,
    ipr: float = _DEFAULT_IPR,
    finish_ipr: float = _DEFAULT_FINISH_IPR,
    doc_mm: float = _DEFAULT_DOC_MM,
    finish_allow_x_mm: float = _DEFAULT_FINISH_ALLOW_X,
    finish_allow_z_mm: float = _DEFAULT_FINISH_ALLOW_Z,
    retract_mm: float = _DEFAULT_RETRACT_MM,
    program_number: int | None = None,
    header_comment: str = "",
) -> LatheProgram:
    """Emit a Fanuc-dialect RS-274 lathe G-code program for OD turning.

    Parameters
    ----------
    profile         : 2-D profile as a sequence of (Z_mm, X_radius_mm) pairs.
                      At least 2 points required.  Z must be monotone.
    stock_x_mm      : Initial stock radius (mm).  Must be > max(X in profile).
    stock_z_mm      : Axial facing-stock overhang (mm).  Default 2.0.
    tool_id         : Tool number (T-code, 1–99).  Default 1.
    sfm             : Cutting surface speed (ft/min).  Default 600 (steel, carbide).
                      Ref: Smid 2008 §6.1 Table 6-1.
    ipr             : Roughing feed per revolution (mm/rev).  Default 0.25.
                      Ref: Smid 2008 §6.1 Table 6-2.
    finish_ipr      : Finishing feed per revolution (mm/rev).  Default 0.10.
    doc_mm          : Radial depth of cut per roughing pass (mm).  Default 2.0.
    finish_allow_x_mm : Diametric finish allowance (U on G71 block, mm).  Default 0.5.
    finish_allow_z_mm : Axial finish allowance (W on G71 block, mm).  Default 0.1.
    retract_mm      : Rapid clearance for return moves (mm).  Default 5.0.
    program_number  : Fanuc O-number (1–9999).  Omitted when None.
    header_comment  : Optional program-header comment string.

    Returns
    -------
    LatheProgram    : dataclass with .text (G-code string) + metadata.

    Raises
    ------
    ValueError      : if profile < 2 points, stock_x_mm ≤ max profile X,
                      or profile contains non-finite values.

    Notes
    -----
    G71 Type I: profile X must be non-increasing from start to end (OD finishing
    toward smaller diameters or constant).  Concave segments (X increasing away
    from chuck) trigger a warning but do not abort.

    References
    ----------
    NIST RS-274/NGC Interpreter Version 3, Kramer et al. 2000, §3.4–3.9.
    Smid, P. CNC Programming Handbook, 3rd ed., Industrial Press 2008, §6.
    Fanuc Series 0i-TF Operator's Manual (B-64304EN), §14.2 (G71), §14.3 (G70).
    """
    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    pts = list(profile)
    if len(pts) < 2:
        raise ValueError("profile must have at least 2 points")
    for i, pt in enumerate(pts):
        if len(pt) < 2:
            raise ValueError(f"profile[{i}] must be a (Z, X_radius) pair")
        z, x = float(pt[0]), float(pt[1])
        if not (math.isfinite(z) and math.isfinite(x)):
            raise ValueError(f"profile[{i}] contains non-finite value: ({z}, {x})")
        if x < 0:
            raise ValueError(f"profile[{i}]: X_radius must be >= 0, got {x}")
    pts = [(float(z), float(x)) for z, x in pts]

    max_x = max(x for _, x in pts)
    if stock_x_mm <= max_x:
        raise ValueError(
            f"stock_x_mm ({stock_x_mm}) must be greater than max profile radius ({max_x})"
        )

    # ------------------------------------------------------------------
    # Cutting parameters
    # ------------------------------------------------------------------
    css = _sfm_to_css(sfm)  # m/min
    # Use largest diameter (stock) for initial RPM computation
    roughing_rpm = _calc_rpm(css, stock_x_mm)
    # Estimated pass count (radial stock removal / doc)
    radial_stock = stock_x_mm - max_x
    pass_count = max(1, math.ceil((radial_stock - finish_allow_x_mm / 2.0) / doc_mm))

    warnings: list[str] = []

    # Check profile monotonicity (Type I requirement)
    z_vals = [z for z, _ in pts]
    x_vals = [x for _, x in pts]
    # Detect concave segments (X increasing in direction of traversal)
    z_dir = 1 if z_vals[-1] > z_vals[0] else -1
    for i in range(len(pts) - 1):
        dz = (z_vals[i + 1] - z_vals[i]) * z_dir
        dx = x_vals[i + 1] - x_vals[i]
        if dz <= 0 and abs(dz) < 1e-9:
            warnings.append(
                f"profile[{i}]–[{i+1}]: Z does not advance — non-monotone profile; "
                "G71 Type I may reject on controller"
            )
        if dx > 1e-9:
            warnings.append(
                f"profile[{i}]–[{i+1}]: X_radius increases ({x_vals[i]:.4f} → "
                f"{x_vals[i+1]:.4f}) — concave feature not supported by G71 Type I; "
                "verify on controller before running"
            )

    # ------------------------------------------------------------------
    # Profile block numbers
    # ------------------------------------------------------------------
    ns = _NS_BLOCK
    nf = _NS_BLOCK + _NF_STEP * (len(pts) - 1)

    # ------------------------------------------------------------------
    # Approach position
    # ------------------------------------------------------------------
    # Approach Z: slightly past the face of the stock (furthest Z + stock_z_mm)
    z0_approach = z_vals[0] + stock_z_mm if z_dir < 0 else z_vals[0] - stock_z_mm

    # Clearance position
    x_clear = _dia(stock_x_mm + retract_mm)
    z_clear = z_vals[0] + stock_z_mm * 2.0 if z_dir < 0 else z_vals[0] - stock_z_mm * 2.0

    # ------------------------------------------------------------------
    # Emit lines
    # ------------------------------------------------------------------
    lines: list[str] = []

    def _e(line: str) -> None:
        if line.strip():
            lines.append(line)

    # Header
    if program_number is not None:
        _e(f"O{program_number:04d}")
    if header_comment:
        safe = header_comment.replace("(", "[").replace(")", "]")
        _e(f"({safe})")
    _e("(CAM-LATHE-PROFILE-EMIT — Fanuc dialect; G71/G70 OD turning)")
    _e("(Refs: NIST RS-274/NGC Kramer et al. 2000; Smid CNC Programming Handbook 2008 §6)")
    _e(f"(Dialect: Fanuc 0i-TF/30i ONLY — Heidenhain/Siemens/Mazak out of scope)")

    # Preamble
    _e("G18 G21 G40 G54")   # ZX plane, metric, cancel CNRC, WCS1
    _e("G28 U0.")            # machine-X reference return

    # Tool change
    _e(f"T{tool_id:02d} M06")

    # Spindle on — constant RPM mode first (G97) for initial approach
    rpm_int = int(round(roughing_rpm))
    _e(f"G97 S{rpm_int} M03")

    # Rapid to approach position (diameter programming on X)
    x_approach_dia = _dia(stock_x_mm + retract_mm)
    _e(f"G00 X{_fmt(x_approach_dia)} Z{_fmt(z0_approach)}")

    # ------------------------------------------------------------------
    # G71 rough turning cycle
    # ------------------------------------------------------------------
    # U = diametric finish allowance (positive = material left on OD)
    # W = axial finish allowance
    # D = depth of cut (Fanuc 0i uses mm value; some variants use µm integer)
    #     Smid 2008 §6.4 — "D is entered in the same unit as the axis data"
    _e(
        f"G71 P{ns} Q{nf} "
        f"U{_fmt(finish_allow_x_mm)} W{_fmt(finish_allow_z_mm)} "
        f"D{_fmt(doc_mm)} F{_fmt(ipr)} S{rpm_int}"
    )

    # ------------------------------------------------------------------
    # G70 finish turning cycle  (Smid 2008 §6.5)
    # ------------------------------------------------------------------
    # G96 = constant surface speed for finish pass (better surface finish)
    css_int = int(round(css))  # m/min
    _e(f"G96 S{css_int}")      # activate CSS before G70
    finish_rpm_int = int(round(_calc_rpm(css, max_x if max_x > 0 else stock_x_mm / 2)))
    _e(
        f"G70 P{ns} Q{nf} "
        f"F{_fmt(finish_ipr)} S{finish_rpm_int}"
    )
    # Cancel CSS; restore constant RPM for safety
    _e(f"G97 S{rpm_int}")

    # ------------------------------------------------------------------
    # Profile blocks  (ns … nf)
    # ------------------------------------------------------------------
    _e("(--- Profile definition blocks for G71/G70 ---)")
    for blk_idx, (z, x) in enumerate(pts):
        n = ns + _NF_STEP * blk_idx
        x_dia = _dia(x)
        # Smid 2008 §6.4: first profile block MUST be a G00 rapid to start position
        if blk_idx == 0:
            _e(f"N{n:03d} G00 X{_fmt(x_dia)} Z{_fmt(z)}")
        else:
            _e(f"N{n:03d} G01 X{_fmt(x_dia)} Z{_fmt(z)} F{_fmt(finish_ipr)}")

    # ------------------------------------------------------------------
    # Retract + end
    # ------------------------------------------------------------------
    _e(f"G00 X{_fmt(x_clear)} Z{_fmt(z_clear)}")
    _e("M05")   # spindle stop
    _e("M30")   # program end + rewind

    # ------------------------------------------------------------------
    # Build result
    # ------------------------------------------------------------------
    text = "\n".join(lines) + "\n"
    non_blank = sum(1 for ln in lines if ln.strip())

    return LatheProgram(
        text=text,
        line_count=non_blank,
        warnings=warnings,
        css_m_per_min=round(css, 4),
        roughing_rpm=round(roughing_rpm, 2),
        feed_mm_rev=ipr,
        finish_feed_mm_rev=finish_ipr,
        pass_count=pass_count,
    )


# ---------------------------------------------------------------------------
# LLM tool — registered in plugin._TOOL_MODULES
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401

    _cam_lathe_spec = ToolSpec(
        name="cam_emit_lathe_gcode",
        description=(
            "Emit a complete Fanuc RS-274 lathe G-code program (G71 rough turning + "
            "G70 finish turning) from a 2-D axis-symmetric profile.\n"
            "\n"
            "Profile: list of [Z_mm, X_radius_mm] pairs (Z axial, X radius, not diameter).\n"
            "stock_x_mm: initial stock radius (must exceed max profile X).\n"
            "\n"
            "Returns the G-code string plus metadata (RPM, feed, pass count, warnings).\n"
            "\n"
            "Includes: G71 rough cycle, G70 finish cycle, G96 CSS, G97 constant-RPM, "
            "M03/M05 spindle on/off, M06 tool change.\n"
            "\n"
            "Dialect: Fanuc 0i-TF/30i ONLY. Heidenhain, Siemens, Mazak, Okuma lathe "
            "cycles are out of scope.\n"
            "\n"
            "Refs: NIST RS-274/NGC (Kramer et al. 2000); Smid CNC Programming Handbook "
            "(2008) §6.\n"
            "\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "description": (
                        "2-D turning profile: list of [Z_mm, X_radius_mm] pairs. "
                        "Z = axial (mm, positive towards tailstock). "
                        "X = radius in mm (not diameter). Must be ≥ 0. "
                        "Minimum 2 points; Z must be monotone."
                    ),
                    "minItems": 2,
                },
                "stock_x_mm": {
                    "type": "number",
                    "description": "Initial stock radius (mm). Must be > max profile X.",
                },
                "stock_z_mm": {
                    "type": "number",
                    "description": "Axial facing-stock overhang (mm). Default 2.0.",
                },
                "tool_id": {
                    "type": "integer",
                    "description": "Tool number (T-code, 1–99). Default 1.",
                    "minimum": 1,
                    "maximum": 99,
                },
                "sfm": {
                    "type": "number",
                    "description": (
                        "Surface cutting speed in ft/min. Default 600 (steel, carbide). "
                        "Smid 2008 §6.1: 400–800 SFM for medium-carbon steel."
                    ),
                },
                "ipr": {
                    "type": "number",
                    "description": (
                        "Roughing feed per revolution (mm/rev). Default 0.25. "
                        "Smid 2008 §6.1: 0.15–0.50 mm/rev roughing range."
                    ),
                },
                "finish_ipr": {
                    "type": "number",
                    "description": "Finishing feed per revolution (mm/rev). Default 0.10.",
                },
                "doc_mm": {
                    "type": "number",
                    "description": "Radial depth of cut per roughing pass (mm). Default 2.0.",
                },
                "finish_allow_x_mm": {
                    "type": "number",
                    "description": (
                        "Diametric finish allowance left for G70 (U word on G71, mm). "
                        "Default 0.5."
                    ),
                },
                "finish_allow_z_mm": {
                    "type": "number",
                    "description": (
                        "Axial finish allowance (W word on G71, mm). Default 0.1."
                    ),
                },
                "retract_mm": {
                    "type": "number",
                    "description": "Rapid clearance for return moves (mm). Default 5.0.",
                },
                "program_number": {
                    "type": "integer",
                    "description": "Fanuc O-number (1–9999). Omitted when absent.",
                    "minimum": 1,
                    "maximum": 9999,
                },
                "header_comment": {
                    "type": "string",
                    "description": "Optional program header comment.",
                },
            },
            "required": ["profile", "stock_x_mm"],
        },
    )

    @register(_cam_lathe_spec, write=False)
    async def run_cam_emit_lathe_gcode(ctx: ProjectCtx, args: bytes) -> str:
        """LLM tool entry point — emit lathe G-code from a turning profile."""
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        raw_profile = a.get("profile")
        if raw_profile is None:
            return err_payload("profile is required", "BAD_ARGS")
        if not isinstance(raw_profile, list) or len(raw_profile) < 2:
            return err_payload(
                "profile must be a JSON array of at least 2 [Z, X] pairs", "BAD_ARGS"
            )
        try:
            profile = [(float(pt[0]), float(pt[1])) for pt in raw_profile]
        except Exception as exc:
            return err_payload(f"profile contains invalid values: {exc}", "BAD_ARGS")

        stock_x = a.get("stock_x_mm")
        if stock_x is None:
            return err_payload("stock_x_mm is required", "BAD_ARGS")
        try:
            stock_x = float(stock_x)
        except Exception:
            return err_payload("stock_x_mm must be a number", "BAD_ARGS")

        kwargs: dict = {}
        for key in (
            "stock_z_mm", "tool_id", "sfm", "ipr", "finish_ipr", "doc_mm",
            "finish_allow_x_mm", "finish_allow_z_mm", "retract_mm",
            "program_number", "header_comment",
        ):
            if key in a:
                kwargs[key] = a[key]

        try:
            result = emit_lathe_gcode(profile, stock_x, **kwargs)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"internal error: {exc}", "INTERNAL_ERROR")

        return _json.dumps({
            "ok": True,
            "gcode": result.text,
            "line_count": result.line_count,
            "pass_count": result.pass_count,
            "css_m_per_min": result.css_m_per_min,
            "roughing_rpm": result.roughing_rpm,
            "feed_mm_rev": result.feed_mm_rev,
            "finish_feed_mm_rev": result.finish_feed_mm_rev,
            "warnings": result.warnings,
        })

except ImportError:
    # Running outside the Kerf service (e.g. plain pytest) — skip registration.
    pass
