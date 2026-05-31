"""
kerf_cam.dwell_audit — G-code G04 dwell analysis for milling programs.

Parses a G-code program and audits G04 dwell commands that may indicate:
- Over-aggressive feeds (chatter mitigation via pauses)
- Unnecessary work-piece cooling delays
- Machine warm-up dwells that inflate cycle time
- Spindle-settling pauses in boring (G89)

Returns total dwell time, count, per-dwell list, estimated cutting time,
ratio of dwell to program time, and flags suspicious long dwells.

Reference standards
-------------------
* Machinery's Handbook 31e §1140 — Dwell commands in CNC; G04 syntax
  (P-word in milliseconds for Fanuc/Haas; X-word in seconds per NIST).
* NIST RS-274/NGC §3.5 (Kramer et al. 2000) — G04 dwell: X-word in seconds,
  P-word in milliseconds; modal state carries feed rate.

G04 syntax
----------
Fanuc / Haas:  G04 P<milliseconds>   (integer, e.g. G04 P500 = 0.5 s)
NIST RS-274:   G04 X<seconds>        (float, e.g. G04 X0.5 = 0.5 s)
Some controllers also accept G04 Xnn.n without the P variant.

Cutting-time estimation
-----------------------
For each G01 block, the distance D = sqrt(ΔX² + ΔY² + ΔZ²) is accumulated
and divided by the modal feed rate F (mm/min or mm/rev) to estimate cutting
time. Modal state (F, G20/G21 inches vs mm, absolute/incremental) is
tracked line-by-line. Rapids (G00) are excluded from cutting time (they
represent positioning, not cutting).

Limitations (honest_caveat)
---------------------------
1. Feed-rate units: G94 (mm/min) assumed. G95 (mm/rev) needs spindle RPM for
   time conversion — not available in G-code alone. G95 blocks contribute 0
   to cutting-time estimate (conservative).
2. Arc moves (G02/G03) contribute 0 — arc-length calculation requires I/J/R
   parsing; excluded for simplicity. Programs heavy on circular interpolation
   will have underestimated cutting time and thus an inflated dwell ratio.
3. Tool changes, M-code waits, rigid tapping, and orientation dwells are not
   separately categorised — only explicit G04 commands are counted.
4. Some dwells are deliberate: spindle-settle in boring (G89), machine warm-up
   at program start, coolant-pressure build-up. Flag excessive=True is a
   heuristic, NOT proof of a programming error.
5. Inch mode (G20) converts to mm by × 25.4 for distance only; feed-rate in
   inch/min is converted as well (× 25.4).
6. Cutting-time estimate is ±20–40 % due to acceleration ramps, look-ahead,
   and corner deceleration (Altintas 2012 §5.7). Add 15–30 % for a realistic
   wall-clock estimate.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DwellAuditSpec:
    """Input specification for a G-code dwell audit.

    Parameters
    ----------
    gcode_text
        Raw G-code program as a string.
    max_recommended_dwell_per_op_ms
        Threshold above which a single dwell is flagged as suspicious.
        Default 500 ms (MH 31e §1140 guideline for milling operations —
        longer dwells in continuous milling are rarely necessary).
    max_total_dwell_ratio_pct
        If total_dwell / total_program_time exceeds this percentage the
        report marks excessive=True. Default 5 % — industry rule-of-thumb.
    """
    gcode_text: str
    max_recommended_dwell_per_op_ms: float = 500.0
    max_total_dwell_ratio_pct: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.gcode_text, str):
            raise TypeError("gcode_text must be a str")
        if self.max_recommended_dwell_per_op_ms <= 0:
            raise ValueError(
                f"max_recommended_dwell_per_op_ms must be > 0, "
                f"got {self.max_recommended_dwell_per_op_ms!r}"
            )
        if not (0.0 < self.max_total_dwell_ratio_pct <= 100.0):
            raise ValueError(
                f"max_total_dwell_ratio_pct must be in (0, 100], "
                f"got {self.max_total_dwell_ratio_pct!r}"
            )


@dataclass
class DwellAuditReport:
    """Result from ``audit_milling_dwells``.

    Attributes
    ----------
    total_dwell_time_ms
        Sum of all G04 dwell times in milliseconds.
    num_dwells
        Count of G04 commands found.
    dwell_per_op_ms
        Per-dwell durations in milliseconds (in parse order).
    total_program_time_estimate_s
        Heuristic estimate of total program time in seconds:
        cutting_time + rapid_time_approx + total_dwell_time_ms/1000.
        Cutting time is from G01 distance/feed; rapid time is estimated as
        total_rapid_distance / 10000 mm/min (conservative generic rapid).
    dwell_ratio_pct
        100 × total_dwell_time_ms / (total_program_time_estimate_s × 1000).
        Zero when total_program_time_estimate_s == 0.
    excessive
        True when dwell_ratio_pct > spec.max_total_dwell_ratio_pct.
    suspicious_long_dwells
        Subset of dwell_per_op_ms where the dwell exceeds
        spec.max_recommended_dwell_per_op_ms.
    honest_caveat
        Plain-English limitations of this heuristic analysis.
    """
    total_dwell_time_ms: float
    num_dwells: int
    dwell_per_op_ms: list[float]
    total_program_time_estimate_s: float
    dwell_ratio_pct: float
    excessive: bool
    suspicious_long_dwells: list[float]
    honest_caveat: str


# ---------------------------------------------------------------------------
# G-code parser helpers
# ---------------------------------------------------------------------------

# Regex to strip inline comments (parenthetical or semicolons)
_COMMENT_RE = re.compile(r'\(.*?\)|;.*')

# Match a word: letter followed by optional sign and number
_WORD_RE = re.compile(r'([A-Za-z])\s*([+-]?\s*\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?)')


def _parse_words(line: str) -> dict[str, float]:
    """Return mapping of word letter (upper) → float value for one G-code line."""
    line_clean = _COMMENT_RE.sub('', line).strip()
    words: dict[str, float] = {}
    for m in _WORD_RE.finditer(line_clean):
        letter = m.group(1).upper()
        # strip internal whitespace from number (some controllers allow "- 5.0")
        value = float(m.group(2).replace(' ', ''))
        words[letter] = value
    return words


def _distance(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
) -> float:
    dx = x1 - x0
    dy = y1 - y0
    dz = z1 - z0
    return math.sqrt(dx * dx + dy * dy + dz * dz)


# ---------------------------------------------------------------------------
# Core audit function
# ---------------------------------------------------------------------------

def audit_milling_dwells(spec: DwellAuditSpec) -> DwellAuditReport:
    """Parse G-code and audit G04 dwell commands.

    Algorithm
    ---------
    1. Scan lines; track modal state: G-mode (G00/G01), feed F (mm/min),
       position (X, Y, Z), units (G20=inch / G21=mm), distance mode
       (G90=absolute / G91=incremental), feed mode (G94=per-min / G95=per-rev).
    2. On G04: extract P (ms) or X (s) → accumulate dwell_per_op_ms.
    3. On G01: compute distance from last position; add distance/F to cutting_s.
       (G95 mode: skip because spindle RPM unknown.)
    4. On G00: accumulate rapid distance for crude rapid-time estimate.
    5. total_program_time_estimate_s = cutting_s + rapid_s + total_dwell_s.
    6. dwell_ratio_pct = 100 × total_dwell_s / total_program_time_estimate_s.
       (Zero when no motion and no dwell.)
    7. excessive = dwell_ratio_pct > spec.max_total_dwell_ratio_pct.
    8. suspicious = [d for d in dwell_per_op_ms if d > max_recommended_dwell_per_op_ms].

    Parameters
    ----------
    spec : DwellAuditSpec

    Returns
    -------
    DwellAuditReport
    """
    # --- Modal state ---
    modal_g_motion: int = 0        # 0=rapid, 1=linear, 2=CW arc, 3=CCW arc
    feed_mm_per_min: float = 0.0   # modal F (G94, mm/min)
    is_inch: bool = False           # G20 → inch, G21 → mm (default)
    is_incremental: bool = False    # G91 → incremental, G90 → absolute (default)
    is_per_rev: bool = False        # G95 → per-rev; G94 → per-min (default)

    # --- Position state ---
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0

    # --- Accumulators ---
    dwell_per_op_ms: list[float] = []
    cutting_s: float = 0.0
    rapid_distance_mm: float = 0.0

    _RAPID_RATE_MM_MIN: float = 10_000.0   # generic conservative rapid

    for raw_line in spec.gcode_text.splitlines():
        words = _parse_words(raw_line)
        if not words:
            continue

        # --- Update units ---
        if 'G' in words:
            g = int(round(words['G']))
            if g == 20:
                is_inch = True
            elif g == 21:
                is_inch = False
            elif g == 90:
                is_incremental = False
            elif g == 91:
                is_incremental = True
            elif g == 94:
                is_per_rev = False
            elif g == 95:
                is_per_rev = True
            elif g in (0, 1, 2, 3):
                modal_g_motion = g

        # --- Update feed ---
        if 'F' in words:
            raw_f = words['F']
            feed_mm_per_min = raw_f * 25.4 if is_inch else raw_f

        # --- Parse G04 dwell ---
        # G04 may appear alone on a line or combined with other codes.
        # We detect it by checking for G=4 in words OR by scanning the
        # cleaned line text for G04/G4 token (handles "G04 P500" style).
        line_upper = _COMMENT_RE.sub('', raw_line).upper()
        is_dwell = False
        if 'G' in words and int(round(words['G'])) == 4:
            is_dwell = True
        # Also catch "G04" written without the G word being the first G
        # (edge case: multiple G-codes on one line, e.g. "G90 G04 P200")
        if not is_dwell and re.search(r'\bG\s*0?4\b', line_upper):
            is_dwell = True

        if is_dwell:
            dwell_ms: float = 0.0
            if 'P' in words:
                # P in milliseconds (Fanuc/Haas/most controllers)
                dwell_ms = float(words['P'])
            elif 'X' in words:
                # X in seconds (NIST RS-274/NGC §3.5)
                dwell_ms = float(words['X']) * 1000.0
            # If neither P nor X present, treat as zero-length dwell (NOP)
            if dwell_ms > 0.0:
                dwell_per_op_ms.append(round(dwell_ms, 6))
            continue   # dwell lines don't contribute to motion

        # --- Motion commands ---
        # Determine effective G-motion for this line (may be implicit / modal)
        line_g_motion = modal_g_motion
        if 'G' in words:
            gv = int(round(words['G']))
            if gv in (0, 1, 2, 3):
                line_g_motion = gv
                modal_g_motion = gv

        # Compute new position
        has_motion = any(k in words for k in ('X', 'Y', 'Z'))
        if not has_motion:
            continue

        new_x = words.get('X', (0.0 if is_incremental else pos_x))
        new_y = words.get('Y', (0.0 if is_incremental else pos_y))
        new_z = words.get('Z', (0.0 if is_incremental else pos_z))

        if is_inch:
            new_x = new_x * 25.4
            new_y = new_y * 25.4
            new_z = new_z * 25.4

        if is_incremental:
            dest_x = pos_x + new_x
            dest_y = pos_y + new_y
            dest_z = pos_z + new_z
        else:
            dest_x = new_x
            dest_y = new_y
            dest_z = new_z

        dist = _distance(pos_x, pos_y, pos_z, dest_x, dest_y, dest_z)

        if line_g_motion == 0:
            rapid_distance_mm += dist
        elif line_g_motion == 1:
            # Linear cutting move
            if not is_per_rev and feed_mm_per_min > 0.0:
                cutting_s += (dist / feed_mm_per_min) * 60.0
            # G95 or zero feed → skip (conservative: contributes 0)
        # G02/G03 arc moves: skip (arc length not computed — see caveat)

        pos_x, pos_y, pos_z = dest_x, dest_y, dest_z

    # --- Aggregate ---
    total_dwell_ms = sum(dwell_per_op_ms)
    total_dwell_s = total_dwell_ms / 1000.0
    rapid_s = (rapid_distance_mm / _RAPID_RATE_MM_MIN) * 60.0
    total_program_time_s = cutting_s + rapid_s + total_dwell_s

    if total_program_time_s > 0.0:
        dwell_ratio_pct = 100.0 * total_dwell_s / total_program_time_s
    else:
        dwell_ratio_pct = 0.0

    excessive = dwell_ratio_pct > spec.max_total_dwell_ratio_pct
    suspicious = [
        d for d in dwell_per_op_ms
        if d > spec.max_recommended_dwell_per_op_ms
    ]

    honest_caveat = (
        "G04 dwell audit is a heuristic — some dwells are deliberate: "
        "G89 boring spindle-settle, machine warm-up at program start, "
        "coolant-pressure build, arc welding hold, or EDM spark stabilisation. "
        "Flag excessive=True is NOT proof of a programming error. "
        "Cutting-time estimate is G01 distance/feed only (G94 per-min mode); "
        "G02/G03 arc moves are excluded (arc-length not computed → "
        "cutting-time underestimated for arc-heavy programs, inflating "
        "dwell_ratio_pct). "
        "G95 (feed per rev) blocks contribute 0 to cutting time (spindle RPM "
        "unavailable in G-code). "
        "Rapid time estimated at 10 000 mm/min (conservative generic; "
        "actual machines range 5 000–40 000 mm/min). "
        "Acceleration ramps and look-ahead add 15–30 % to wall-clock time "
        "(Altintas 2012 §5.7). "
        "Treat total_program_time_estimate_s as ±30 % guidance only. "
        "References: MH 31e §1140 (Dwell commands); NIST RS-274/NGC §3.5."
    )

    return DwellAuditReport(
        total_dwell_time_ms=round(total_dwell_ms, 6),
        num_dwells=len(dwell_per_op_ms),
        dwell_per_op_ms=dwell_per_op_ms,
        total_program_time_estimate_s=round(total_program_time_s, 6),
        dwell_ratio_pct=round(dwell_ratio_pct, 4),
        excessive=excessive,
        suspicious_long_dwells=suspicious,
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_audit_milling_dwells_spec = ToolSpec(
    name="cam_audit_milling_dwells",
    description=(
        "Analyse a G-code milling program for excessive G04 dwell commands. "
        "Parses every G04 X<seconds> (NIST RS-274/NGC §3.5) and G04 P<ms> "
        "(Fanuc/Haas) dwell; estimates G01 cutting time from line-by-line "
        "distance and modal feed rate; returns total_dwell_time_ms, num_dwells, "
        "dwell_per_op_ms list, total_program_time_estimate_s, dwell_ratio_pct, "
        "excessive flag (ratio > max_total_dwell_ratio_pct), "
        "suspicious_long_dwells (> max_recommended_dwell_per_op_ms), "
        "and an honest caveat. "
        "Use to diagnose over-aggressive feeds (chatter mitigation via dwells), "
        "unnecessary work-piece cooling delays, or machine warm-up bloat. "
        "Note: some dwells are deliberate (G89 boring settle, program warm-up) — "
        "excessive=True is a heuristic flag, not a definitive error. "
        "References: MH 31e §1140; NIST RS-274/NGC §3.5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode_text": {
                "type": "string",
                "description": "Full G-code program text to analyse.",
            },
            "max_recommended_dwell_per_op_ms": {
                "type": "number",
                "description": (
                    "Threshold in ms above which a single dwell is flagged "
                    "as suspicious. Default 500 ms (MH 31e §1140 guideline "
                    "for milling)."
                ),
            },
            "max_total_dwell_ratio_pct": {
                "type": "number",
                "description": (
                    "If total_dwell / total_program_time exceeds this % the "
                    "report marks excessive=True. Default 5.0 %."
                ),
            },
        },
        "required": ["gcode_text"],
    },
)


@register(cam_audit_milling_dwells_spec)
async def run_cam_audit_milling_dwells(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    if "gcode_text" not in a:
        return err_payload("missing required field: 'gcode_text'", "BAD_ARGS")

    try:
        spec = DwellAuditSpec(
            gcode_text=str(a["gcode_text"]),
            max_recommended_dwell_per_op_ms=float(
                a.get("max_recommended_dwell_per_op_ms", 500.0)
            ),
            max_total_dwell_ratio_pct=float(
                a.get("max_total_dwell_ratio_pct", 5.0)
            ),
        )
        report = audit_milling_dwells(spec)
    except (TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "total_dwell_time_ms": report.total_dwell_time_ms,
        "num_dwells": report.num_dwells,
        "dwell_per_op_ms": report.dwell_per_op_ms,
        "total_program_time_estimate_s": report.total_program_time_estimate_s,
        "dwell_ratio_pct": report.dwell_ratio_pct,
        "excessive": report.excessive,
        "suspicious_long_dwells": report.suspicious_long_dwells,
        "honest_caveat": report.honest_caveat,
    })
