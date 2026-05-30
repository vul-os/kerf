"""
cam_gcode_emit — emit Fanuc-compatible RS-274 G-code from a CAM toolpath.

Algorithm & references
----------------------
Implements the canonical RS-274/NGC word-address format (NIST RS-274/NGC
Interpreter Version 3, Kramer, Proctor & Messina 2000) with Fanuc 0i-series
dialect extensions (Smid, P. "CNC Programming Handbook", 3rd ed., Industrial
Press 2008, §3):

  G00  — rapid positioning (no coordinated feed)
  G01  — linear interpolation at programmed feedrate F
  G02  — circular interpolation, CW  (I/J centre offsets, XY plane)
  G03  — circular interpolation, CCW (I/J centre offsets, XY plane)
  M03  — spindle on CW (speed S)
  M05  — spindle stop
  M06  — tool change (T word precedes on same block, Fanuc convention)
  M02  — program end
  F    — feedrate modal word (mm/min or in/min)
  S    — spindle speed modal word (RPM)
  T    — tool number (selects tool; M06 performs the change)

Toolpath input model
--------------------
A *toolpath* is a list of ``Waypoint`` dicts (or dataclass instances):

  {
    "type":     "rapid" | "linear" | "arc_cw" | "arc_ccw"
                | "spindle_on" | "spindle_off" | "tool_change" | "comment",
    "x":        float   (mm, target X — required for motion types),
    "y":        float   (mm, target Y — required for motion types),
    "z":        float   (mm, target Z — required for motion types),
    "f":        float   (feedrate mm/min — for linear/arc; omit → inherit modal),
    "s":        float   (spindle RPM    — for spindle_on),
    "tool":     int     (tool number    — for tool_change),
    "i":        float   (X offset to arc centre relative to arc start — arc types),
    "j":        float   (Y offset to arc centre relative to arc start — arc types),
    "comment":  str     (inline comment — emitted in parentheses),
  }

Honest scope limits
-------------------
* **Fanuc / generic RS-274 dialect only.**  LinuxCNC percent-sign conventions,
  Heidenhain TCPM/PLANE SPATIAL, Siemens G17-G19 with TRAORI, Mazak Smooth, or
  Okuma OSP extensions are NOT emitted.  Programs produced here are safe for
  Fanuc 0i/18i/21i/30i, Haas (Fanuc-compatible), and GRBL (≥ v1.1).
* Arc interpolation is XY-plane (G17) only.  G18/G19 arcs require a separate
  plane-select word; the caller must insert those as ``comment`` blocks or
  implement the extension.
* No canned cycles (G81/G82/G83) are emitted; callers should expand drills to
  explicit G00/G01 sequences (see ``gcode.post.expand_drill_cycles``).
* Numbers are formatted to 4 decimal places — adequate for metric toolpaths
  (0.0001 mm = 0.1 µm precision).  Use ``coord_decimals`` to adjust.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class GcodeProgram:
    """Container for an emitted G-code program.

    Attributes
    ----------
    text        : complete G-code program as a string (newline-terminated)
    line_count  : number of non-blank lines in ``text``
    warnings    : list of non-fatal notices (e.g. missing F on first feed move)
    """
    text: str
    line_count: int
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float dropping trailing zeros after the decimal point.

    For coordinate words (decimals=4), trailing fractional zeros are stripped
    and the decimal point is preserved (Fanuc decimal-programming mode).

    For integer words (decimals=0, e.g. spindle RPM), no decimal point is
    emitted and the value is rendered as a plain integer.

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
    # Strip trailing fractional zeros; keep the decimal point (Fanuc convention
    # requires it in decimal-programming mode — Smid 2008 §3.2).
    integer_part, frac_part = s.split(".")
    frac_stripped = frac_part.rstrip("0")
    return f"{integer_part}.{frac_stripped}" if frac_stripped else f"{integer_part}."


def _coord_word(letter: str, value: float, decimals: int = 4) -> str:
    return f"{letter}{_fmt(value, decimals)}"


def _close_enough(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) < tol


# ---------------------------------------------------------------------------
# Main emitter
# ---------------------------------------------------------------------------

def emit_gcode(
    toolpath: Sequence[dict[str, Any]],
    header_comment: str = "",
    program_number: int | None = None,
    coord_decimals: int = 4,
    rapid_z_clearance: float | None = None,
) -> GcodeProgram:
    """Emit Fanuc-compatible RS-274 G-code from a waypoint toolpath.

    Parameters
    ----------
    toolpath        : sequence of waypoint dicts (see module docstring)
    header_comment  : optional program-header comment (no parentheses needed)
    program_number  : Fanuc O-number (1–9999); omitted when None
    coord_decimals  : decimal places for X/Y/Z/I/J words (default 4)
    rapid_z_clearance : unused reserved parameter for future safe-Z insertion

    Returns
    -------
    GcodeProgram with .text (the G-code string) and .warnings list.

    References
    ----------
    NIST RS-274/NGC Interpreter Version 3 (Kramer et al. 2000), §3.4–3.8.
    Smid (2008) CNC Programming Handbook §3 "G-code programming".
    """
    lines: list[str] = []
    warnings: list[str] = []

    # Modal state — mirrors controller's modal registers
    modal_f: float | None = None   # current feedrate
    modal_s: float | None = None   # current spindle speed
    modal_t: int | None = None     # current tool
    modal_motion: str | None = None  # G00 / G01 / G02 / G03

    def _emit(line: str) -> None:
        if line.strip():
            lines.append(line)

    # ── Program header ───────────────────────────────────────────────────────
    if program_number is not None:
        _emit(f"O{program_number:04d}")
    if header_comment:
        safe_comment = header_comment.replace("(", "[").replace(")", "]")
        _emit(f"({safe_comment})")

    # NIST §3.4: startup defaults — absolute mode, mm, XY plane
    _emit("G17 G21 G90 G94")  # XY plane, metric, absolute, feed per min

    # ── Waypoint loop ────────────────────────────────────────────────────────
    for idx, wp in enumerate(toolpath):
        wtype = str(wp.get("type", "linear")).lower()

        # ── comment ──────────────────────────────────────────────────────────
        if wtype == "comment":
            txt = str(wp.get("comment", "")).replace("(", "[").replace(")", "]")
            if txt:
                _emit(f"({txt})")
            continue

        # ── spindle on ───────────────────────────────────────────────────────
        if wtype == "spindle_on":
            s_val = float(wp.get("s", modal_s or 0.0))
            modal_s = s_val
            _emit(f"S{_fmt(s_val, 0)} M03")
            continue

        # ── spindle off ──────────────────────────────────────────────────────
        if wtype == "spindle_off":
            _emit("M05")
            continue

        # ── tool change ──────────────────────────────────────────────────────
        if wtype == "tool_change":
            t_num = int(wp.get("tool", modal_t or 1))
            # Fanuc convention: M06 follows T on the same block; spindle must
            # be stopped before tool change (Smid 2008 §3.12).
            _emit("M05")
            _emit(f"T{t_num:02d} M06")
            modal_t = t_num
            modal_motion = None  # force re-emit of G-word after tool change
            continue

        # ── motion types: rapid, linear, arc_cw, arc_ccw ────────────────────
        if wtype not in ("rapid", "linear", "arc_cw", "arc_ccw"):
            warnings.append(
                f"Waypoint {idx}: unknown type {wtype!r} — skipped"
            )
            continue

        # Coordinates (required)
        if "x" not in wp and "y" not in wp and "z" not in wp:
            warnings.append(
                f"Waypoint {idx}: type={wtype!r} has no X/Y/Z coords — skipped"
            )
            continue

        parts: list[str] = []

        # ── G-word ───────────────────────────────────────────────────────────
        if wtype == "rapid":
            g_word = "G00"
        elif wtype == "linear":
            g_word = "G01"
        elif wtype == "arc_cw":
            g_word = "G02"
        else:  # arc_ccw
            g_word = "G03"

        # Modal motion suppression (NIST §3.5 — re-emit when changed)
        if g_word != modal_motion:
            parts.append(g_word)
            modal_motion = g_word

        # ── X / Y / Z ────────────────────────────────────────────────────────
        if "x" in wp:
            parts.append(_coord_word("X", float(wp["x"]), coord_decimals))
        if "y" in wp:
            parts.append(_coord_word("Y", float(wp["y"]), coord_decimals))
        if "z" in wp:
            parts.append(_coord_word("Z", float(wp["z"]), coord_decimals))

        # ── I / J centre offsets for arcs ────────────────────────────────────
        if wtype in ("arc_cw", "arc_ccw"):
            # I and J are the offsets from the arc-start point to the centre.
            # They are optional (default 0) but should be explicit for clarity
            # (Smid 2008 §3.8; NIST §3.7.2).
            i_val = float(wp.get("i", 0.0))
            j_val = float(wp.get("j", 0.0))
            parts.append(_coord_word("I", i_val, coord_decimals))
            parts.append(_coord_word("J", j_val, coord_decimals))

        # ── F feedrate ────────────────────────────────────────────────────────
        if wtype in ("linear", "arc_cw", "arc_ccw"):
            f_val = wp.get("f")
            if f_val is not None:
                f_val = float(f_val)
                if not _close_enough(f_val, modal_f or 0.0):
                    parts.append(f"F{_fmt(f_val, 1)}")
                    modal_f = f_val
            elif modal_f is None:
                warnings.append(
                    f"Waypoint {idx}: feed move with no F word and no modal F "
                    f"— controller will use F0 (alarm on most machines)"
                )

        # ── S spindle (optional inline spindle speed) ─────────────────────────
        s_val = wp.get("s")
        if s_val is not None:
            s_val = float(s_val)
            if not _close_enough(s_val, modal_s or 0.0):
                parts.append(f"S{_fmt(s_val, 0)}")
                modal_s = s_val

        # ── inline comment ────────────────────────────────────────────────────
        cmt = wp.get("comment", "")
        if cmt:
            safe_cmt = str(cmt).replace("(", "[").replace(")", "]")
            parts.append(f"({safe_cmt})")

        _emit(" ".join(parts))

    # ── Program end ───────────────────────────────────────────────────────────
    _emit("M05")   # ensure spindle off at end
    _emit("M02")   # program end (Fanuc; M30 rewinds — caller can override)

    text = "\n".join(lines) + "\n"
    return GcodeProgram(
        text=text,
        line_count=len(lines),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Convenience: build a Waypoint dict
# ---------------------------------------------------------------------------

def rapid(x: float, y: float, z: float, comment: str = "") -> dict[str, Any]:
    """Return a rapid-positioning waypoint dict."""
    d: dict[str, Any] = {"type": "rapid", "x": x, "y": y, "z": z}
    if comment:
        d["comment"] = comment
    return d


def linear(
    x: float, y: float, z: float,
    f: float | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Return a linear-feed waypoint dict."""
    d: dict[str, Any] = {"type": "linear", "x": x, "y": y, "z": z}
    if f is not None:
        d["f"] = f
    if comment:
        d["comment"] = comment
    return d


def arc_cw(
    x: float, y: float, z: float,
    i: float, j: float,
    f: float | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Return a G02 clockwise arc waypoint dict.

    I, J are X and Y offsets from the arc *start* point to the arc *centre*
    (Fanuc incremental I/J mode — the default).

    References: NIST RS-274/NGC §3.7.2; Smid (2008) §3.8.
    """
    d: dict[str, Any] = {"type": "arc_cw", "x": x, "y": y, "z": z, "i": i, "j": j}
    if f is not None:
        d["f"] = f
    if comment:
        d["comment"] = comment
    return d


def arc_ccw(
    x: float, y: float, z: float,
    i: float, j: float,
    f: float | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Return a G03 counter-clockwise arc waypoint dict."""
    d: dict[str, Any] = {"type": "arc_ccw", "x": x, "y": y, "z": z, "i": i, "j": j}
    if f is not None:
        d["f"] = f
    if comment:
        d["comment"] = comment
    return d


def spindle_on(rpm: float) -> dict[str, Any]:
    """Return a spindle-on (M03) waypoint dict."""
    return {"type": "spindle_on", "s": rpm}


def spindle_off() -> dict[str, Any]:
    """Return a spindle-off (M05) waypoint dict."""
    return {"type": "spindle_off"}


def tool_change(tool_number: int) -> dict[str, Any]:
    """Return a tool-change (T.. M06) waypoint dict."""
    return {"type": "tool_change", "tool": tool_number}


def comment(text: str) -> dict[str, Any]:
    """Return a comment waypoint dict."""
    return {"type": "comment", "comment": text}


# ---------------------------------------------------------------------------
# LLM tool — cam_emit_gcode
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    _spec = ToolSpec(
        name="cam_emit_gcode",
        description=(
            "Emit Fanuc-compatible RS-274 G-code from a CAM toolpath (list of waypoints).\n\n"
            "Supported waypoint types:\n"
            "  rapid        — G00 rapid positioning\n"
            "  linear       — G01 linear interpolation at feedrate F\n"
            "  arc_cw       — G02 clockwise arc (I/J centre offsets from arc start)\n"
            "  arc_ccw      — G03 counter-clockwise arc (I/J centre offsets from arc start)\n"
            "  spindle_on   — M03 spindle on CW (field: s = RPM)\n"
            "  spindle_off  — M05 spindle stop\n"
            "  tool_change  — M05 + T.. M06 tool change (field: tool = number)\n"
            "  comment      — inline comment in parentheses (field: comment = text)\n\n"
            "Each motion waypoint has: x, y, z (mm), optional f (feedrate mm/min), "
            "optional s (spindle RPM).  Arc waypoints additionally require i, j "
            "(X/Y offsets from arc start to arc centre).\n\n"
            "Returns: {gcode, line_count, warnings[]}.\n\n"
            "Dialect: Fanuc 0i/18i/21i/30i + Haas (Fanuc-compatible) + GRBL ≥ 1.1.\n"
            "Out of scope: LinuxCNC %, Heidenhain TCPM, Siemens TRAORI, Mazak Smooth.\n\n"
            "References:\n"
            "  NIST RS-274/NGC Interpreter Version 3 (Kramer et al. 2000) §3.4–3.8.\n"
            "  Smid, P. CNC Programming Handbook (2008) §3."
        ),
        input_schema={
            "type": "object",
            "required": ["toolpath"],
            "properties": {
                "toolpath": {
                    "type": "array",
                    "description": "Ordered list of waypoint dicts.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "rapid", "linear", "arc_cw", "arc_ccw",
                                    "spindle_on", "spindle_off", "tool_change", "comment",
                                ],
                            },
                            "x": {"type": "number", "description": "X coordinate (mm)"},
                            "y": {"type": "number", "description": "Y coordinate (mm)"},
                            "z": {"type": "number", "description": "Z coordinate (mm)"},
                            "f": {"type": "number", "description": "Feedrate (mm/min)"},
                            "s": {"type": "number", "description": "Spindle RPM"},
                            "i": {"type": "number", "description": "Arc centre X offset from start (mm)"},
                            "j": {"type": "number", "description": "Arc centre Y offset from start (mm)"},
                            "tool": {"type": "integer", "description": "Tool number for tool_change"},
                            "comment": {"type": "string", "description": "Comment text"},
                        },
                        "required": ["type"],
                    },
                    "minItems": 1,
                },
                "header_comment": {
                    "type": "string",
                    "description": "Optional program header comment (no parentheses needed).",
                },
                "program_number": {
                    "type": "integer",
                    "description": "Fanuc O-number 1–9999 (optional; omitted when not set).",
                    "minimum": 1,
                    "maximum": 9999,
                },
                "coord_decimals": {
                    "type": "integer",
                    "description": "Decimal places for X/Y/Z/I/J words (default 4).",
                    "default": 4,
                    "minimum": 1,
                    "maximum": 6,
                },
            },
        },
    )

    @register(_spec, write=False)
    async def _run_cam_emit_gcode(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        toolpath = a.get("toolpath")
        if not toolpath or not isinstance(toolpath, list):
            return err_payload("toolpath is required (non-empty list)", "BAD_ARGS")

        header_comment = str(a.get("header_comment", ""))
        program_number = a.get("program_number")
        if program_number is not None:
            try:
                program_number = int(program_number)
            except (TypeError, ValueError) as exc:
                return err_payload(f"program_number must be integer: {exc}", "BAD_ARGS")

        coord_decimals = int(a.get("coord_decimals", 4))

        try:
            prog = emit_gcode(
                toolpath,
                header_comment=header_comment,
                program_number=program_number,
                coord_decimals=coord_decimals,
            )
        except Exception as exc:
            return err_payload(str(exc), "EMIT_ERROR")

        return ok_payload({
            "gcode": prog.text,
            "line_count": prog.line_count,
            "warnings": prog.warnings,
            "dialect": "Fanuc RS-274/Haas/GRBL",
            "reference": (
                "NIST RS-274/NGC (Kramer et al. 2000); "
                "Smid CNC Programming Handbook (2008) §3"
            ),
        })

except ImportError:
    pass  # kerf_chat not installed (e.g. unit-test environment)
