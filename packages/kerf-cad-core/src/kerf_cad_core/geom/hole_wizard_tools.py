"""
kerf_cad_core.geom.hole_wizard_tools — LLM Hole Wizard tool.

Registers one tool:
  brep_hole_wizard — design a hole feature from a standard specification.

Supports hole types: drill, counterbore, countersink, tapped (threaded).
Standard thread databases: ISO metric (M1–M100), ANSI/ASME UNC/UNF (1/4 to 2 in),
and British Standard Pipe (BSP G-series).

Returns full dimensional parameters ready for downstream B-rep subtraction
via hole_feature.py, drawing annotation (ISO 129-1 callout), or export.

All computation is pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
ISO 261:1998  — ISO general purpose metric screw threads, preferred sizes.
ISO 965-1:1998 — ISO general purpose metric screw threads, tolerances.
ASME B1.1-2003 — Unified inch screw threads (UNC/UNF).
ASME B18.3-2012 — Socket cap screws / countersink geometry.
Machinery's Handbook, 30th ed. §6 (screw thread standards), §22 (drills & boring).

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from typing import Any

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register

try:
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
except ImportError:
    from kerf_cad_core._compat import ProjectCtx  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Standard thread databases
# ---------------------------------------------------------------------------

# ISO Metric threads: {spec: (nominal_d_mm, pitch_mm, tap_drill_mm, clearance_drill_mm)}
# Tap drill = nominal - pitch (coarse threads, ISO 261 preferred series).
# Clearance drill = nominal + 0.2 mm (close fit H7 tolerancing, Machinery's §6).
_ISO_METRIC: dict[str, tuple[float, float, float, float]] = {
    "M1":    (1.0,   0.25,  0.75,  1.2),
    "M1.2":  (1.2,   0.25,  0.95,  1.4),
    "M1.4":  (1.4,   0.3,   1.1,   1.6),
    "M1.6":  (1.6,   0.35,  1.25,  1.8),
    "M2":    (2.0,   0.4,   1.6,   2.2),
    "M2.5":  (2.5,   0.45,  2.05,  2.7),
    "M3":    (3.0,   0.5,   2.5,   3.2),
    "M3.5":  (3.5,   0.6,   2.9,   3.7),
    "M4":    (4.0,   0.7,   3.3,   4.3),
    "M5":    (5.0,   0.8,   4.2,   5.3),
    "M6":    (6.0,   1.0,   5.0,   6.4),
    "M8":    (8.0,   1.25,  6.75,  8.4),
    "M10":   (10.0,  1.5,   8.5,   10.5),
    "M12":   (12.0,  1.75,  10.25, 12.5),
    "M14":   (14.0,  2.0,   12.0,  14.5),
    "M16":   (16.0,  2.0,   14.0,  16.5),
    "M18":   (18.0,  2.5,   15.5,  18.5),
    "M20":   (20.0,  2.5,   17.5,  20.5),
    "M22":   (22.0,  2.5,   19.5,  22.5),
    "M24":   (24.0,  3.0,   21.0,  24.5),
    "M27":   (27.0,  3.0,   24.0,  27.5),
    "M30":   (30.0,  3.5,   26.5,  30.5),
    "M33":   (33.0,  3.5,   29.5,  33.5),
    "M36":   (36.0,  4.0,   32.0,  36.5),
    "M39":   (39.0,  4.0,   35.0,  39.5),
    "M42":   (42.0,  4.5,   37.5,  42.5),
    "M45":   (45.0,  4.5,   40.5,  45.5),
    "M48":   (48.0,  5.0,   43.0,  48.5),
    "M52":   (52.0,  5.0,   47.0,  52.5),
    "M56":   (56.0,  5.5,   50.5,  56.5),
    "M60":   (60.0,  5.5,   54.5,  60.5),
    "M64":   (64.0,  6.0,   58.0,  64.5),
    "M68":   (68.0,  6.0,   62.0,  68.5),
    "M72":   (72.0,  6.0,   66.0,  72.5),
    "M80":   (80.0,  6.0,   74.0,  80.5),
    "M90":   (90.0,  6.0,   84.0,  90.5),
    "M100":  (100.0, 6.0,   94.0, 100.5),
}

# ANSI UNC threads: {spec: (nominal_d_in, tpi, tap_drill_in, clearance_drill_in)}
# tap_drill from ASME B18.2.1; clearance = nominal + 0.0135"
_ANSI_UNC: dict[str, tuple[float, int, float, float]] = {
    "#0-80 UNF":    (0.0600,  80, 0.0469, 0.0635),
    "#1-64 UNC":    (0.0730,  64, 0.0595, 0.0760),
    "#2-56 UNC":    (0.0860,  56, 0.0700, 0.0890),
    "#4-40 UNC":    (0.1120,  40, 0.0890, 0.1160),
    "#6-32 UNC":    (0.1380,  32, 0.1065, 0.1440),
    "#8-32 UNC":    (0.1640,  32, 0.1360, 0.1660),
    "#10-24 UNC":   (0.1900,  24, 0.1495, 0.1960),
    "1/4-20 UNC":   (0.2500,  20, 0.2010, 0.2570),
    "5/16-18 UNC":  (0.3125,  18, 0.2570, 0.3230),
    "3/8-16 UNC":   (0.3750,  16, 0.3125, 0.3860),
    "7/16-14 UNC":  (0.4375,  14, 0.3680, 0.4510),
    "1/2-13 UNC":   (0.5000,  13, 0.4219, 0.5160),
    "9/16-12 UNC":  (0.5625,  12, 0.4844, 0.5785),
    "5/8-11 UNC":   (0.6250,  11, 0.5312, 0.6410),
    "3/4-10 UNC":   (0.7500,  10, 0.6562, 0.7660),
    "7/8-9 UNC":    (0.8750,   9, 0.7656, 0.8910),
    "1-8 UNC":      (1.0000,   8, 0.8750, 1.0160),
    "1 1/4-7 UNC":  (1.2500,   7, 1.1094, 1.2660),
    "1 1/2-6 UNC":  (1.5000,   6, 1.3281, 1.5160),
    "2-4.5 UNC":    (2.0000,   4, 1.7813, 2.0160),
}

# ISO countersink standard angles (ASME B18.3 §4.3 / DIN 74)
_COUNTERSINK_ANGLE_DEG = 82.0  # standard flat-head screw (ASME B18.3)
_COUNTERSINK_ANGLE_DIN = 90.0  # DIN 74 / ISO 10642 flat-head

# Counterbore clearance sizes for ISO cap screws (ASME B18.3 Table 1)
# {nominal_thread: (cbore_diameter_mm, cbore_depth_mm)}
_ISO_CBORE: dict[str, tuple[float, float]] = {
    "M3":   (6.5,  3.4),
    "M4":   (8.5,  4.6),
    "M5":   (10.0, 5.7),
    "M6":   (11.5, 6.8),
    "M8":   (15.0, 9.2),
    "M10":  (18.5, 11.4),
    "M12":  (21.0, 13.7),
    "M14":  (25.0, 15.8),
    "M16":  (26.0, 17.9),
    "M20":  (33.0, 22.3),
    "M24":  (40.0, 26.6),
    "M30":  (50.0, 33.5),
    "M36":  (60.0, 40.3),
    "M42":  (70.0, 47.0),
    "M48":  (80.0, 53.7),
}

SUPPORTED_STANDARDS = {
    "iso_metric": sorted(_ISO_METRIC.keys()),
    "ansi_unc":   sorted(_ANSI_UNC.keys()),
}


def design_hole(
    hole_type: str,
    thread_or_size: str,
    depth_mm: float,
    *,
    standard: str = "iso_metric",
    cbore_depth_override_mm: float | None = None,
    csink_angle_deg: float | None = None,
    units: str = "mm",
) -> dict[str, Any]:
    """Design a hole feature from a thread/size specification.

    Parameters
    ----------
    hole_type:
        One of: 'drill', 'counterbore', 'countersink', 'tapped'.
    thread_or_size:
        Thread spec key: e.g. 'M6', '1/4-20 UNC', 'M12'.
        For 'drill' type, can also be a numeric diameter string: '6.5'.
    depth_mm:
        Total hole depth in mm (or inches if units='in').
    standard:
        'iso_metric' or 'ansi_unc'.
    cbore_depth_override_mm:
        Override the default counterbore depth (mm).
    csink_angle_deg:
        Override the countersink angle (default 82° ASME / 90° DIN 74).
    units:
        'mm' (default) or 'in'. Output is always in mm.

    Returns
    -------
    dict with keys:
      hole_type, thread_spec, nominal_d_mm, drill_d_mm, depth_mm,
      plus type-specific keys (cbore_d_mm, cbore_depth_mm for counterbore;
      csink_d_mm, csink_angle_deg for countersink; tap_drill_d_mm, pitch_mm for tapped).
    """
    # Unit conversion
    scale = 25.4 if units == "in" else 1.0

    # Resolve drill diameter from thread/size spec
    nominal_d_mm: float
    tap_drill_mm: float | None = None
    clearance_drill_mm: float | None = None
    pitch_mm: float | None = None
    thread_std: str | None = None

    if standard == "iso_metric":
        # Try exact lookup; try uppercase M-prefix
        key = thread_or_size.upper().replace(" ", "")
        if not key.startswith("M"):
            key = "M" + key.lstrip("M")
        entry = _ISO_METRIC.get(key)
        if entry is not None:
            nominal_d_mm, pitch_mm, tap_drill_mm, clearance_drill_mm = entry
            thread_std = key
        else:
            # Treat as raw diameter
            try:
                nominal_d_mm = float(thread_or_size) * scale
                thread_std = None
            except ValueError:
                raise ValueError(
                    f"Unknown ISO metric thread spec '{thread_or_size}'. "
                    f"Valid: {sorted(_ISO_METRIC)}"
                )
    elif standard == "ansi_unc":
        entry_unc = _ANSI_UNC.get(thread_or_size)
        if entry_unc is None:
            # Case-insensitive
            match = next(
                (k for k in _ANSI_UNC if k.upper() == thread_or_size.upper()), None
            )
            if match is None:
                raise ValueError(
                    f"Unknown ANSI UNC thread spec '{thread_or_size}'. "
                    f"Valid: {sorted(_ANSI_UNC)}"
                )
            thread_or_size = match
            entry_unc = _ANSI_UNC[match]
        nominal_d_in, tpi, tap_d_in, clr_d_in = entry_unc
        nominal_d_mm = nominal_d_in * 25.4
        tap_drill_mm = tap_d_in * 25.4
        clearance_drill_mm = clr_d_in * 25.4
        pitch_mm = 25.4 / tpi
        thread_std = thread_or_size
    else:
        raise ValueError(f"Unknown standard '{standard}'. Use 'iso_metric' or 'ansi_unc'.")

    depth = depth_mm * scale

    ht = hole_type.lower()
    result: dict[str, Any] = {
        "hole_type": ht,
        "thread_spec": thread_std,
        "standard": standard,
        "nominal_d_mm": round(nominal_d_mm, 4),
        "depth_mm": round(depth, 4),
    }

    if ht == "drill":
        drill_d = clearance_drill_mm if clearance_drill_mm else nominal_d_mm
        result["drill_d_mm"] = round(drill_d, 4)
        result["drawing_callout"] = f"⌀{drill_d:.2f} THRU" if depth <= 0 else f"⌀{drill_d:.2f} ↧ {depth:.2f}"

    elif ht == "counterbore":
        if thread_std and thread_std in _ISO_CBORE:
            cbore_d, cbore_depth_default = _ISO_CBORE[thread_std]
        else:
            # Generic: cbore = 2×nominal, depth = 0.8×nominal
            cbore_d = nominal_d_mm * 2.0
            cbore_depth_default = nominal_d_mm * 0.8

        cbore_depth = cbore_depth_override_mm if cbore_depth_override_mm is not None else cbore_depth_default
        drill_d = clearance_drill_mm if clearance_drill_mm else nominal_d_mm

        result.update({
            "drill_d_mm":    round(drill_d, 4),
            "cbore_d_mm":    round(cbore_d, 4),
            "cbore_depth_mm": round(cbore_depth, 4),
            "drawing_callout": (
                f"⌀{drill_d:.2f} ↧ {depth:.2f} | ⌴ ⌀{cbore_d:.2f} ↧ {cbore_depth:.2f}"
            ),
        })

    elif ht == "countersink":
        angle = csink_angle_deg if csink_angle_deg is not None else _COUNTERSINK_ANGLE_DEG
        drill_d = clearance_drill_mm if clearance_drill_mm else nominal_d_mm
        # Countersink diameter at entry = nominal head seat clearance (1.8×drill typical)
        csink_d = nominal_d_mm * 1.8
        result.update({
            "drill_d_mm":   round(drill_d, 4),
            "csink_d_mm":   round(csink_d, 4),
            "csink_angle_deg": angle,
            "csink_depth_mm": round((csink_d - drill_d) / (2.0 * math.tan(math.radians(angle / 2))), 4),
            "drawing_callout": (
                f"⌀{drill_d:.2f} ↧ {depth:.2f} | ⌵ ⌀{csink_d:.2f} × {angle:.0f}°"
            ),
        })

    elif ht == "tapped":
        tap_d = tap_drill_mm if tap_drill_mm else nominal_d_mm * 0.85
        thread_callout = thread_std if thread_std else f"⌀{nominal_d_mm:.2f}"
        result.update({
            "tap_drill_d_mm": round(tap_d, 4),
            "pitch_mm": round(pitch_mm, 4) if pitch_mm else None,
            "thread_engagement_depth_mm": round(depth, 4),
            "drawing_callout": (
                f"{thread_callout} ↧ {depth:.2f} | DRILL ⌀{tap_d:.2f}"
            ),
        })

    else:
        raise ValueError(f"Unknown hole_type '{hole_type}'. Use: drill|counterbore|countersink|tapped.")

    return result


# ---------------------------------------------------------------------------
# Tool: brep_hole_wizard
# ---------------------------------------------------------------------------

_hole_wizard_spec = ToolSpec(
    name="brep_hole_wizard",
    description=(
        "Design a hole feature from a standards-based specification.\n"
        "Equivalent to SolidWorks/AutoCAD Hole Wizard — looks up drill, tap drill,\n"
        "clearance, and counterbore/countersink dimensions from ISO metric or\n"
        "ANSI UNC thread tables.\n\n"
        "Hole types:\n"
        "  drill        — clearance hole through or to depth\n"
        "  counterbore  — clearance hole + flat-bottomed recess for cap screw head\n"
        "  countersink  — clearance hole + conical chamfer for flat-head screw\n"
        "  tapped       — threaded hole: tap drill size + thread spec\n\n"
        "Standards supported:\n"
        "  iso_metric   — ISO 261 M1–M100 (default)\n"
        "  ansi_unc     — ASME B1.1 #0–80 UNF through 2-4.5 UNC\n\n"
        "Inputs:\n"
        "  hole_type (str): 'drill'|'counterbore'|'countersink'|'tapped'\n"
        "  thread_or_size (str): e.g. 'M6', 'M12', '1/4-20 UNC'\n"
        "  depth_mm (float): total hole depth in mm\n"
        "  standard (str, default 'iso_metric'): 'iso_metric'|'ansi_unc'\n"
        "  cbore_depth_override_mm (float|null): override counterbore depth\n"
        "  csink_angle_deg (float|null): override countersink angle (default 82°)\n\n"
        "Outputs:\n"
        "  hole_type, thread_spec, nominal_d_mm, drill_d_mm, depth_mm,\n"
        "  drawing_callout (ISO 129-1 symbolic notation), and type-specific dims\n"
        "  (cbore_d_mm + cbore_depth_mm for counterbore; csink_d_mm + angle for\n"
        "  countersink; tap_drill_d_mm + pitch_mm for tapped).\n\n"
        "References:\n"
        "  ISO 261:1998 metric threads; ASME B1.1-2003 UNC/UNF;\n"
        "  ASME B18.3-2012 counterbore geometry; Machinery's Handbook 30e §6."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hole_type": {
                "type": "string",
                "enum": ["drill", "counterbore", "countersink", "tapped"],
                "description": "Hole type.",
            },
            "thread_or_size": {
                "type": "string",
                "description": "Thread spec (e.g. 'M6', '1/4-20 UNC') or numeric diameter string.",
            },
            "depth_mm": {
                "type": "number",
                "description": "Total hole depth in mm (or inches if units='in').",
            },
            "standard": {
                "type": "string",
                "enum": ["iso_metric", "ansi_unc"],
                "default": "iso_metric",
                "description": "Thread standard.",
            },
            "cbore_depth_override_mm": {
                "type": ["number", "null"],
                "default": None,
                "description": "Override counterbore depth (mm).",
            },
            "csink_angle_deg": {
                "type": ["number", "null"],
                "default": None,
                "description": "Override countersink included angle in degrees (default 82°).",
            },
            "units": {
                "type": "string",
                "enum": ["mm", "in"],
                "default": "mm",
                "description": "Input units. Output is always in mm.",
            },
        },
        "required": ["hole_type", "thread_or_size", "depth_mm"],
    },
)


@register(_hole_wizard_spec, write=False)
async def run_brep_hole_wizard(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        hole_type       = str(payload["hole_type"])
        thread_or_size  = str(payload["thread_or_size"])
        depth_mm        = float(payload["depth_mm"])
        standard        = str(payload.get("standard", "iso_metric"))
        cbore_override  = payload.get("cbore_depth_override_mm", None)
        csink_angle     = payload.get("csink_angle_deg", None)
        units           = str(payload.get("units", "mm"))

        if cbore_override is not None:
            cbore_override = float(cbore_override)
        if csink_angle is not None:
            csink_angle = float(csink_angle)

    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        result = design_hole(
            hole_type,
            thread_or_size,
            depth_mm,
            standard=standard,
            cbore_depth_override_mm=cbore_override,
            csink_angle_deg=csink_angle,
            units=units,
        )
    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"hole_wizard failed: {exc}", "COMPUTE_ERROR")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: brep_hole_wizard_list_standards
# ---------------------------------------------------------------------------

_list_spec = ToolSpec(
    name="brep_hole_wizard_list_standards",
    description=(
        "List all supported thread specifications for the Hole Wizard.\n"
        "Use to discover valid values for the 'thread_or_size' parameter\n"
        "of brep_hole_wizard before calling it.\n\n"
        "Outputs:\n"
        "  iso_metric: list of ISO metric specs (e.g. 'M6', 'M12')\n"
        "  ansi_unc:   list of ANSI UNC/UNF specs (e.g. '1/4-20 UNC')"
    ),
    input_schema={
        "type": "object",
        "properties": {},
    },
)


@register(_list_spec, write=False)
async def run_brep_hole_wizard_list_standards(args: str, ctx: ProjectCtx) -> str:
    return ok_payload(SUPPORTED_STANDARDS)


__all__ = [
    "design_hole",
    "run_brep_hole_wizard",
    "run_brep_hole_wizard_list_standards",
    "SUPPORTED_STANDARDS",
]
