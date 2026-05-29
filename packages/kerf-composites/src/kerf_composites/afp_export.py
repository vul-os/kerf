"""
kerf_composites.afp_export — CNC export for AFP tape-path courses.

Two target formats:

  G-code (generic 5-axis)
  -----------------------
  Industry AFP machines (Coriolis, MAG, Electroimpact) consume G-code with
  OEM-specific M-code extensions for fibre handling.  This module emits a
  *generic* dialect that maps cleanly to a majority of interpreters; OEM
  post-processor adaption is a follow-on task.

  M-code assignments used here (GE Automation / common convention):
    M200 — Fibre start (begin tow feed)
    M201 — Fibre stop (end tow feed)
    M202 — Tape cut
    M203 — Compaction roller down (engage)
    M204 — Compaction roller up (disengage)
    M205 F{force} — Set compaction roller force in N

  APT / CL (Cutter Location)
  --------------------------
  APT/CL (ISO 3592) is the language of record for NC tool-path programs.
  This emitter produces a subset sufficient for 5-axis AFP heads:
    FROM, GOTO, FEDRAT, RAPID, END.
  Each course is a FROM/GOTO pair with FEDRAT feed-rate setting.

Public API
----------
  afp_to_gcode(courses, machine_config=None) -> str
  afp_to_apt(courses, feedrate_mmpm=None) -> str

Course dict schema (from routes_composites_mfg.py)
---------------------------------------------------
  {
    "course_id":    int,
    "angle_deg":    float,
    "start_x":      float,  # mm
    "start_y":      float,  # mm
    "end_x":        float,  # mm
    "end_y":        float,  # mm
    "tow_width_mm": float,
    "length_mm":    float,
  }

machine_config dict (optional, all values have sensible defaults)
  {
    "feedrate_mmpm":          float   (default 3000)
    "rapid_feedrate_mmpm":    float   (default 9000)
    "z_laydown":              float   (default 0.0, mm — surface Z)
    "z_clearance":            float   (default 10.0, mm — travel height)
    "compaction_force_N":     float   (default 150.0)
    "program_number":         int     (default 1)
    "machine_name":           str     (default "GENERIC_AFP")
    "coordinate_precision":   int     (default 3, decimal places)
  }
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_MACHINE: dict[str, Any] = {
    "feedrate_mmpm": 3000.0,
    "rapid_feedrate_mmpm": 9000.0,
    "z_laydown": 0.0,
    "z_clearance": 10.0,
    "compaction_force_N": 150.0,
    "program_number": 1,
    "machine_name": "GENERIC_AFP",
    "coordinate_precision": 3,
}


def _cfg(machine_config: dict | None, key: str) -> Any:
    """Return a config value, falling back to defaults."""
    if machine_config and key in machine_config:
        return machine_config[key]
    return _DEFAULT_MACHINE[key]


# ---------------------------------------------------------------------------
# afp_to_gcode
# ---------------------------------------------------------------------------

def afp_to_gcode(courses: list[dict], machine_config: dict | None = None) -> str:
    """Convert AFP courses to generic 5-axis G-code.

    Each course produces:
      - Rapid to clearance height above start point (G00)
      - Rapid to start XY at clearance height
      - M203 (roller down), M200 (fibre start), M205 F{force} (roller force)
      - Feed move to end XY at laydown Z (G01)
      - M201 (fibre stop), M202 (tape cut), M204 (roller up)
      - Rapid back to clearance height

    A-axis (rotation about X) is set to match the course angle so the head
    is perpendicular to the tow direction.  C-axis (spindle / rotation about Z)
    tracks the lay angle.

    Parameters
    ----------
    courses : list[dict]
        AFP courses as returned by the backend path-plan route.
    machine_config : dict, optional
        Machine configuration overrides (see module docstring for keys).

    Returns
    -------
    str
        Multi-line G-code program.
    """
    if not courses:
        raise ValueError("courses list is empty; nothing to export")

    feed = float(_cfg(machine_config, "feedrate_mmpm"))
    rapid_feed = float(_cfg(machine_config, "rapid_feedrate_mmpm"))
    z_lay = float(_cfg(machine_config, "z_laydown"))
    z_clr = float(_cfg(machine_config, "z_clearance"))
    force = float(_cfg(machine_config, "compaction_force_N"))
    prog_no = int(_cfg(machine_config, "program_number"))
    machine_name = str(_cfg(machine_config, "machine_name"))
    prec = int(_cfg(machine_config, "coordinate_precision"))

    fmt = f".{prec}f"

    def _f(v: float) -> str:
        return format(v, fmt)

    lines: list[str] = []

    # Program header
    lines.append(f"% (AFP G-CODE — {machine_name})")
    lines.append(f"O{prog_no:04d}")
    lines.append(f"({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC)")
    lines.append(f"(COURSES: {len(courses)})")
    lines.append("G17 G21 G40 G49 G80 G90  (metric, abs, cancel offsets)")
    lines.append("G28 G91 Z0.0             (home Z)")
    lines.append("G90                      (absolute mode)")
    lines.append(f"G00 Z{_f(z_clr)}        (safe height)")
    lines.append("")

    for course in courses:
        cid = course["course_id"]
        angle = float(course["angle_deg"])
        sx = float(course["start_x"])
        sy = float(course["start_y"])
        ex = float(course["end_x"])
        ey = float(course["end_y"])
        length = float(course["length_mm"])
        tow_w = float(course["tow_width_mm"])

        # C-axis = lay angle; A-axis = head tilt (0 for flat surface)
        c_axis = angle % 360.0
        a_axis = 0.0

        lines.append(f"(--- COURSE {cid}  angle={angle:.1f}deg  len={length:.1f}mm"
                     f"  tow={tow_w:.2f}mm ---)")
        lines.append(f"G00 Z{_f(z_clr)}")
        lines.append(f"G00 X{_f(sx)} Y{_f(sy)} C{_f(c_axis)} A{_f(a_axis)}"
                     f"  F{_f(rapid_feed)}")
        lines.append(f"G00 Z{_f(z_lay)}")
        lines.append("M203                     (compaction roller down)")
        lines.append(f"M205 F{_f(force)}       (set roller force)")
        lines.append("M200                     (fibre start)")
        lines.append(f"G01 X{_f(ex)} Y{_f(ey)} Z{_f(z_lay)}"
                     f" C{_f(c_axis)} A{_f(a_axis)}  F{_f(feed)}")
        lines.append("M201                     (fibre stop)")
        lines.append("M202                     (tape cut)")
        lines.append("M204                     (compaction roller up)")
        lines.append(f"G00 Z{_f(z_clr)}")
        lines.append("")

    # Program footer
    lines.append("G28 G91 Z0.0             (home Z)")
    lines.append("G28 G91 X0.0 Y0.0        (home XY)")
    lines.append("M30                      (program end + rewind)")
    lines.append("%")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# afp_to_apt
# ---------------------------------------------------------------------------

def afp_to_apt(courses: list[dict], feedrate_mmpm: float | None = None) -> str:
    """Convert AFP courses to APT/CL (Cutter Location) output.

    Produces a syntactically valid APT program with:
      PARTNO, MACHIN, FROM, RAPID, GOTO, FEDRAT, END statements.

    Each course is written as:
      FROM  / start point
      FEDRAT/ feed_rate, IPM  (or MMPM)
      GOTO  / end point
    with a RAPID move to clearance height between courses.

    Parameters
    ----------
    courses : list[dict]
        AFP courses as returned by the backend path-plan route.
    feedrate_mmpm : float, optional
        Feed rate in mm/min (default 3000).

    Returns
    -------
    str
        Multi-line APT/CL program text.
    """
    if not courses:
        raise ValueError("courses list is empty; nothing to export")

    feed = float(feedrate_mmpm) if feedrate_mmpm is not None else 3000.0
    # APT FEDRAT command uses IPM by convention; convert mm/min → IPM
    feed_ipm = feed / 25.4
    z_lay = 0.0
    z_clr = 10.0

    lines: list[str] = []

    # Header
    lines.append("PARTNO/AFP TAPE PATH")
    lines.append("MACHIN/AFP5AX, 1")
    lines.append("UNITS/MM")
    lines.append(f"$$ COURSES: {len(courses)}")
    lines.append(f"$$ GENERATED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Initial rapid to safe height
    lines.append("RAPID")
    lines.append(f"GOTO/{_apt_pt(0.0, 0.0, z_clr)}")
    lines.append("")

    for course in courses:
        cid = course["course_id"]
        angle = float(course["angle_deg"])
        sx = float(course["start_x"])
        sy = float(course["start_y"])
        ex = float(course["end_x"])
        ey = float(course["end_y"])
        length = float(course["length_mm"])
        tow_w = float(course["tow_width_mm"])

        # Unit vector in course direction for APT TLAXIS (tool-axis vector)
        rad = math.radians(angle)
        i = round(math.cos(rad), 6)
        j = round(math.sin(rad), 6)

        lines.append(f"$$ COURSE {cid}  ANGLE={angle:.2f}  LENGTH={length:.2f}  TOW={tow_w:.2f}")
        # Move to start at clearance height
        lines.append("RAPID")
        lines.append(f"GOTO/{_apt_pt(sx, sy, z_clr)}")
        # Descend to laydown Z
        lines.append(f"GOTO/{_apt_pt(sx, sy, z_lay)}")
        # Set tool axis and start tow
        lines.append(f"TLAXIS/{i}, {j}, 0.0")
        lines.append(f"FEDRAT/{feed_ipm:.4f}, IPM")
        # Start-of-tow marker
        lines.append("AUXFUN/200")
        # Cut move to end of course
        lines.append(f"GOTO/{_apt_pt(ex, ey, z_lay)}")
        # End-of-tow marker
        lines.append("AUXFUN/201")
        # Cut tape
        lines.append("AUXFUN/202")
        # Lift to clearance
        lines.append("RAPID")
        lines.append(f"GOTO/{_apt_pt(ex, ey, z_clr)}")
        lines.append("")

    # Footer
    lines.append("RAPID")
    lines.append(f"GOTO/{_apt_pt(0.0, 0.0, z_clr)}")
    lines.append("END")

    return "\n".join(lines)


def _apt_pt(x: float, y: float, z: float) -> str:
    """Format a point for an APT GOTO statement."""
    return f"{x:.4f}, {y:.4f}, {z:.4f}"
