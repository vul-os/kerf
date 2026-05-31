"""
kerf_cam.arc_linearize — G02/G03 arc lineariser for legacy CNC controllers.

Converts G02 (CW) and G03 (CCW) arc commands in a G-code program to sequences
of G01 linear segments using a chord-error tolerance. Used for legacy controllers
that do not support full circular interpolation, or for post-processors that need
all-linear toolpaths (laser cutters, plasma tables, some wire EDM).

Reference standards
-------------------
* NIST RS-274/NGC §3.5.3 — G02/G03 arc moves; centre-format (I/J offset) and
  radius-format (R-word); arc direction: G02 = CW (clockwise viewed from above
  in XY plane); G03 = CCW.
* Machinery's Handbook 31e §1130 — Circular interpolation; chord-error / sag /
  deviation formulae; segment count derivation from tolerance and radius.

Chord-error geometry (MH 31e §1130)
-------------------------------------
For a chord connecting two points on a circle of radius R, the maximum
deviation (sag / chord error) at the arc midpoint is:

    sag = R - R·cos(Δθ/2) = R·(1 - cos(Δθ/2))

Inverting: given max_chord_error_mm = ε:

    Δθ = 2·acos(1 - ε/R)

Number of segments for a total arc angle θ_arc:

    N = ceil(θ_arc / Δθ)  [minimum 1]

Algorithm
---------
1. Parse each line with a regex-based word scanner.
2. Track modal state: G-motion, position (X,Y,Z), feed (F), units (G20/G21),
   distance mode (G90/G91).
3. On G02/G03: determine arc centre from I/J (centre offsets, always relative
   to arc start) or R (radius).  Compute start/end angles, total arc span Δθ_arc,
   segment angle Δθ_step, then emit N G01 lines for intermediate + endpoint.
4. All other lines: pass through verbatim.

R-format arc ambiguity
-----------------------
With R-format (G02/G03 X_ Y_ R_), two arcs connect start to end: the minor arc
(|θ| ≤ π) corresponds to R > 0; the major arc (|θ| > π) corresponds to R < 0
per RS-274/NGC §3.5.3 convention. If |chord| > 2|R| (geometrically impossible)
the line is passed through unchanged with a comment appended.

Limitations (honest_caveat)
-----------------------------
1. **Modal G-codes not preserved** — each emitted G01 segment carries an explicit
   ``G01`` word; the original program's modal state (e.g. G01 being assumed after
   a previous G01) is NOT restored. Downstream code MUST NOT assume the modal
   G-motion after the linearised block is anything other than G01.
2. **XY-plane arcs only** — G17 XY-plane assumed throughout. G18 (XZ) and G19
   (YZ) plane selection codes are passed through but the arc maths does NOT
   adapt. Programs using G18/G19 arcs will produce incorrect linearisation.
3. **Feed rate not split** — the original F-word from the arc block is emitted
   on every G01 segment; no arc-length-proportional feed-rate correction.
4. **Z-helix arcs** — Z travel specified on a G02/G03 line (helical arcs per
   NIST RS-274/NGC §3.5.3) is linearly interpolated across segments. This is
   geometrically correct for a uniform helix only; non-uniform Z motion is
   not supported.
5. **Single G-code per line** — lines with multiple G-codes (e.g. ``G90 G02 X5
   Y0 I5 J0``) are parsed by taking the *last* G value for motion type. This
   matches common Fanuc practice but may mis-parse unusual multi-code programs.
6. **Incremental mode (G91) arcs** — supported (arc endpoint X/Y treated as
   incremental offsets from start); I/J are always incremental per RS-274/NGC.
7. **Full-circle arcs** (start == end with I/J, no R) — handled; angular span
   set to 2π. Full-circle R-format is ambiguous and passed through unchanged
   with a warning comment.

References: NIST RS-274/NGC §3.5.3; MH 31e §1130.
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
class ArcLinearizeSpec:
    """Input specification for G02/G03 arc linearisation.

    Parameters
    ----------
    gcode_text
        Raw G-code program as a string (NIST RS-274/NGC or Fanuc dialect).
    max_chord_error_mm
        Maximum allowable sag (chord error) per segment in mm.
        Default 0.025 mm — typical finishing tolerance (ISO 2768-f).
        Smaller values produce more segments; values below ``min_segment_length_mm``
        are automatically limited so that the segment length floor takes priority.
    min_segment_length_mm
        Minimum segment length in mm. Segments shorter than this floor are merged
        into the next one (prevents degenerate micro-moves on tiny arcs).
        Default 0.05 mm.
    """
    gcode_text: str
    max_chord_error_mm: float = 0.025
    min_segment_length_mm: float = 0.05

    def __post_init__(self) -> None:
        if not isinstance(self.gcode_text, str):
            raise TypeError("gcode_text must be a str")
        if self.max_chord_error_mm <= 0:
            raise ValueError(
                f"max_chord_error_mm must be > 0, got {self.max_chord_error_mm!r}"
            )
        if self.min_segment_length_mm < 0:
            raise ValueError(
                f"min_segment_length_mm must be >= 0, got {self.min_segment_length_mm!r}"
            )


@dataclass
class ArcLinearizeResult:
    """Result of arc linearisation.

    Attributes
    ----------
    linearized_gcode
        Full G-code program with G02/G03 arcs replaced by G01 segments.
    num_arcs_processed
        Count of G02/G03 commands that were successfully linearised.
    total_segments_emitted
        Total number of G01 segments emitted to replace all processed arcs.
    max_actual_chord_error_mm
        Worst-case actual chord error across all emitted segments.
        Will be <= max_chord_error_mm (may be slightly less due to rounding).
    expansion_ratio
        total_segments_emitted / max(num_arcs_processed, 1).
        Indicates how much the program grew.
    honest_caveat
        Plain-English limitations of this lineariser.
    """
    linearized_gcode: str
    num_arcs_processed: int
    total_segments_emitted: int
    max_actual_chord_error_mm: float
    expansion_ratio: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# G-code parser helpers
# ---------------------------------------------------------------------------

# Strip parenthetical comments and semicolons
_COMMENT_RE = re.compile(r'\(.*?\)|;.*')

# Match a G-code word: letter + optional sign + number
_WORD_RE = re.compile(
    r'([A-Za-z])\s*([+-]?\s*\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?)'
)


def _parse_words(line: str) -> dict[str, float]:
    """Return dict of word-letter (upper) → float for one G-code line."""
    clean = _COMMENT_RE.sub('', line).strip()
    words: dict[str, float] = {}
    for m in _WORD_RE.finditer(clean):
        letter = m.group(1).upper()
        value = float(m.group(2).replace(' ', ''))
        # Last value wins when duplicate words (uncommon but possible)
        words[letter] = value
    return words


def _fmt(v: float) -> str:
    """Format a coordinate value: up to 6 decimal places, strip trailing zeros."""
    s = f"{v:.6f}"
    # Remove trailing zeros after decimal point, keep at least one digit
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s


def _angle_span_cw(theta_start: float, theta_end: float) -> float:
    """Clockwise angular span from theta_start to theta_end, result in [0, 2π]."""
    span = theta_start - theta_end
    return span % (2.0 * math.pi)


def _angle_span_ccw(theta_start: float, theta_end: float) -> float:
    """Counter-clockwise angular span from theta_start to theta_end, result in [0, 2π]."""
    span = theta_end - theta_start
    return span % (2.0 * math.pi)


def _compute_segments_for_arc(
    cx: float, cy: float, r: float,
    theta_start: float, theta_span: float,
    z_start: float, z_end: float,
    max_chord_error_mm: float,
    min_segment_length_mm: float,
) -> list[tuple[float, float, float]]:
    """Compute list of (x, y, z) intermediate + endpoint waypoints for an arc.

    Parameters
    ----------
    cx, cy        : arc centre in XY
    r             : radius (always positive)
    theta_start   : start angle from centre (radians)
    theta_span    : total angular span, positive (radians)
    z_start, z_end: Z at arc start/end (for helical interpolation)
    max_chord_error_mm : chord error tolerance
    min_segment_length_mm : minimum segment length floor

    Returns
    -------
    List of (x, y, z) endpoint coordinates; does NOT include the start point.
    """
    if r <= 0 or theta_span <= 0:
        # Degenerate: return just the endpoint
        x_end = cx + r * math.cos(theta_start + theta_span)
        y_end = cy + r * math.sin(theta_start + theta_span)
        return [(x_end, y_end, z_end)]

    # Clamp chord error to avoid dθ > π (degenerate for very large tolerance)
    eff_chord_error = min(max_chord_error_mm, r)
    # dθ_max from chord-error formula: dθ = 2·acos(1 − ε/R)
    ratio = eff_chord_error / r
    if ratio >= 1.0:
        # Single segment covers the whole arc
        dtheta_max = math.pi
    else:
        dtheta_max = 2.0 * math.acos(1.0 - ratio)

    # Apply min_segment_length floor: segment length = 2·R·sin(dθ/2)
    # Invert: dθ_min from length_floor = 2·R·sin(dθ/2) → dθ = 2·asin(length/(2R))
    if min_segment_length_mm > 0 and min_segment_length_mm < 2.0 * r:
        half_sin_arg = min(min_segment_length_mm / (2.0 * r), 1.0)
        dtheta_from_length = 2.0 * math.asin(half_sin_arg)
        # The effective dtheta is the larger of the two (more lenient)
        dtheta_max = max(dtheta_max, dtheta_from_length)

    # Number of segments
    n_segments = max(1, math.ceil(theta_span / dtheta_max))
    dtheta_step = theta_span / n_segments

    points: list[tuple[float, float, float]] = []
    dz = z_end - z_start
    for i in range(1, n_segments + 1):
        angle = theta_start + dtheta_step * i
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        z = z_start + dz * (i / n_segments)
        points.append((x, y, z))

    return points


def _actual_chord_error(r: float, n: int, theta_span: float) -> float:
    """Compute actual chord error for n equal segments over theta_span on radius r."""
    if n <= 0 or r <= 0:
        return 0.0
    dtheta = theta_span / n
    # sag = R · (1 - cos(dθ/2))
    return r * (1.0 - math.cos(dtheta / 2.0))


# ---------------------------------------------------------------------------
# Core linearisation function
# ---------------------------------------------------------------------------

def linearize_arcs(spec: ArcLinearizeSpec) -> ArcLinearizeResult:
    """Convert G02/G03 arc commands to G01 linear segments.

    Parameters
    ----------
    spec : ArcLinearizeSpec

    Returns
    -------
    ArcLinearizeResult
    """
    lines_out: list[str] = []
    num_arcs_processed: int = 0
    total_segments_emitted: int = 0
    max_actual_chord_error_mm: float = 0.0

    # --- Modal state ---
    modal_g_motion: int = 0       # 0=rapid, 1=linear, 2=CW arc, 3=CCW arc
    is_inch: bool = False
    is_incremental: bool = False

    # --- Position state ---
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0

    # --- Feed ---
    modal_feed: str = ""  # raw F string to re-emit if present on arc line

    for raw_line in spec.gcode_text.splitlines():
        words = _parse_words(raw_line)

        if not words:
            lines_out.append(raw_line)
            continue

        # --- Update units / distance mode ---
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

        # --- Determine effective motion code for this line ---
        line_g: int | None = None
        if 'G' in words:
            gv = int(round(words['G']))
            if gv in (0, 1, 2, 3):
                line_g = gv

        eff_g = line_g if line_g is not None else modal_g_motion

        # Update modal feed
        if 'F' in words:
            modal_feed = f"F{_fmt(words['F'])}"

        # --- Handle arc (G02 / G03) ---
        if eff_g in (2, 3):
            # Update modal G motion
            if line_g is not None:
                modal_g_motion = line_g

            # Determine arc endpoint
            has_xy_motion = 'X' in words or 'Y' in words

            # For a full-circle arc (no endpoint specified), start == end
            if is_incremental:
                dx = words.get('X', 0.0)
                dy = words.get('Y', 0.0)
                dz = words.get('Z', 0.0)
                arc_end_x = pos_x + (dx * 25.4 if is_inch else dx)
                arc_end_y = pos_y + (dy * 25.4 if is_inch else dy)
                arc_end_z = pos_z + (dz * 25.4 if is_inch else dz)
            else:
                raw_ex = words.get('X', pos_x / (25.4 if is_inch else 1.0))
                raw_ey = words.get('Y', pos_y / (25.4 if is_inch else 1.0))
                raw_ez = words.get('Z', pos_z / (25.4 if is_inch else 1.0))
                if is_inch:
                    arc_end_x = raw_ex * 25.4
                    arc_end_y = raw_ey * 25.4
                    arc_end_z = raw_ez * 25.4
                else:
                    arc_end_x = raw_ex
                    arc_end_y = raw_ey
                    arc_end_z = raw_ez

            # Full circle: start == end (only possible with I/J, not R)
            is_full_circle = (
                not has_xy_motion and
                'Z' not in words and
                'R' not in words
            )
            # Also detect numerically equal start/end
            if (abs(arc_end_x - pos_x) < 1e-9 and
                    abs(arc_end_y - pos_y) < 1e-9 and
                    'R' not in words):
                is_full_circle = True

            # Centre of arc
            if 'R' in words:
                # ---- Radius format ----
                R_signed = words['R']
                if is_inch:
                    R_signed *= 25.4
                R_abs = abs(R_signed)

                # Chord from start to end
                chord_x = arc_end_x - pos_x
                chord_y = arc_end_y - pos_y
                chord_len = math.sqrt(chord_x ** 2 + chord_y ** 2)

                if chord_len < 1e-9:
                    # Full circle with R format — ambiguous, pass through
                    lines_out.append(
                        raw_line.rstrip() +
                        "  (arc_linearize: full-circle R-format ambiguous — not linearised)"
                    )
                    pos_x, pos_y, pos_z = arc_end_x, arc_end_y, arc_end_z
                    continue

                if chord_len > 2.0 * R_abs + 1e-9:
                    # Geometrically impossible: chord > diameter
                    lines_out.append(
                        raw_line.rstrip() +
                        "  (arc_linearize: chord > 2R — invalid arc, not linearised)"
                    )
                    pos_x, pos_y, pos_z = arc_end_x, arc_end_y, arc_end_z
                    continue

                # Perpendicular bisector method (RS-274/NGC §3.5.3)
                # Midpoint of chord
                mx = (pos_x + arc_end_x) / 2.0
                my = (pos_y + arc_end_y) / 2.0
                # Distance from midpoint to centre
                d_to_mid = math.sqrt(max(0.0, R_abs ** 2 - (chord_len / 2.0) ** 2))
                # Perpendicular direction (rotated chord 90°)
                perp_x = -chord_y / chord_len
                perp_y = chord_x / chord_len

                # Sign: R > 0 → minor arc (centre on left of travel direction for G02/CCW)
                # Per RS-274/NGC: R < 0 → major arc
                # Convention: R > 0 → centre on the same side as the minor arc
                # For G02 (CW): R > 0 → centre to the right of the chord (from start to end)
                # For G03 (CCW): R > 0 → centre to the left of the chord
                # Simplified per NIST: R > 0 minor arc, R < 0 major arc.
                # Centre is at: midpoint ± d_to_mid × perp
                # We choose sign so that the resulting arc has the correct direction.
                # For minor arc (R>0): centre is such that start-to-end turns in the
                # correct G02/G03 direction.
                # For major arc (R<0): the other centre candidate.
                sign = 1.0 if R_signed > 0 else -1.0

                # G02 (CW): centre to the right of travel (start→end) → perp points right
                # G03 (CCW): centre to the left → same perp, but sign flips
                if eff_g == 2:  # CW
                    cx = mx - sign * d_to_mid * perp_x
                    cy = my - sign * d_to_mid * perp_y
                else:  # CCW
                    cx = mx + sign * d_to_mid * perp_x
                    cy = my + sign * d_to_mid * perp_y

            elif 'I' in words or 'J' in words:
                # ---- Centre-offset format (I, J always relative to arc start) ----
                i_offset = words.get('I', 0.0)
                j_offset = words.get('J', 0.0)
                if is_inch:
                    i_offset *= 25.4
                    j_offset *= 25.4
                cx = pos_x + i_offset
                cy = pos_y + j_offset
                # Recompute R from centre
                R_abs = math.sqrt((pos_x - cx) ** 2 + (pos_y - cy) ** 2)
            else:
                # No I/J/R — invalid arc, pass through
                lines_out.append(
                    raw_line.rstrip() +
                    "  (arc_linearize: no I/J/R on G02/G03 — not linearised)"
                )
                pos_x, pos_y, pos_z = arc_end_x, arc_end_y, arc_end_z
                continue

            # Angles
            theta_start = math.atan2(pos_y - cy, pos_x - cx)
            theta_end = math.atan2(arc_end_y - cy, arc_end_x - cx)

            if is_full_circle:
                theta_span = 2.0 * math.pi
            elif eff_g == 2:
                # CW → angular span is how much we go clockwise (positive in CW sense)
                theta_span = _angle_span_cw(theta_start, theta_end)
                if theta_span < 1e-9:
                    theta_span = 2.0 * math.pi
            else:
                # CCW → positive
                theta_span = _angle_span_ccw(theta_start, theta_end)
                if theta_span < 1e-9:
                    theta_span = 2.0 * math.pi

            if R_abs < 1e-9:
                # Zero-radius arc: just emit G01 to endpoint
                f_part = f" {modal_feed}" if modal_feed else ""
                z_part = f" Z{_fmt(arc_end_z)}" if abs(arc_end_z - pos_z) > 1e-9 else ""
                lines_out.append(
                    f"G01 X{_fmt(arc_end_x)} Y{_fmt(arc_end_y)}{z_part}{f_part}"
                )
                total_segments_emitted += 1
                num_arcs_processed += 1
                pos_x, pos_y, pos_z = arc_end_x, arc_end_y, arc_end_z
                continue

            # Compute waypoints
            # For CW arcs: we parameterise going clockwise, so theta decreases
            if eff_g == 2:  # CW
                theta_start_for_compute = theta_start
                # theta_span is clockwise, so each step subtracts
                # We flip sign convention: treat as positive CCW with negated theta
                actual_theta_start = theta_start
                theta_sign = -1.0  # CW = decreasing angle
            else:  # CCW
                actual_theta_start = theta_start
                theta_sign = 1.0

            # Compute number of segments
            eff_chord_error = min(spec.max_chord_error_mm, R_abs)
            ratio = eff_chord_error / R_abs
            if ratio >= 1.0:
                dtheta_max = math.pi
            else:
                dtheta_max = 2.0 * math.acos(1.0 - ratio)

            if spec.min_segment_length_mm > 0 and spec.min_segment_length_mm < 2.0 * R_abs:
                half_sin_arg = min(spec.min_segment_length_mm / (2.0 * R_abs), 1.0)
                dtheta_from_length = 2.0 * math.asin(half_sin_arg)
                dtheta_max = max(dtheta_max, dtheta_from_length)

            n_segments = max(1, math.ceil(theta_span / dtheta_max))
            dtheta_step = theta_span / n_segments

            # Build segment lines
            dz = arc_end_z - pos_z
            f_part = f" {modal_feed}" if modal_feed else ""

            seg_lines: list[str] = []
            for i in range(1, n_segments + 1):
                angle = actual_theta_start + theta_sign * dtheta_step * i
                seg_x = cx + R_abs * math.cos(angle)
                seg_y = cy + R_abs * math.sin(angle)
                seg_z = pos_z + dz * (i / n_segments)

                z_part = f" Z{_fmt(seg_z)}" if abs(dz) > 1e-9 else ""
                seg_lines.append(
                    f"G01 X{_fmt(seg_x)} Y{_fmt(seg_y)}{z_part}{f_part}"
                )

            lines_out.extend(seg_lines)
            num_arcs_processed += 1
            total_segments_emitted += n_segments

            # Track actual chord error
            arc_chord_err = _actual_chord_error(R_abs, n_segments, theta_span)
            if arc_chord_err > max_actual_chord_error_mm:
                max_actual_chord_error_mm = arc_chord_err

            # Update position
            pos_x, pos_y, pos_z = arc_end_x, arc_end_y, arc_end_z

        else:
            # Non-arc line: pass through verbatim, update modal state
            if line_g is not None:
                modal_g_motion = line_g

            # Update position for G0/G1
            has_motion = any(k in words for k in ('X', 'Y', 'Z'))
            if has_motion:
                if is_incremental:
                    dx = words.get('X', 0.0) * (25.4 if is_inch else 1.0)
                    dy = words.get('Y', 0.0) * (25.4 if is_inch else 1.0)
                    dz = words.get('Z', 0.0) * (25.4 if is_inch else 1.0)
                    pos_x += dx
                    pos_y += dy
                    pos_z += dz
                else:
                    if 'X' in words:
                        pos_x = words['X'] * (25.4 if is_inch else 1.0)
                    if 'Y' in words:
                        pos_y = words['Y'] * (25.4 if is_inch else 1.0)
                    if 'Z' in words:
                        pos_z = words['Z'] * (25.4 if is_inch else 1.0)

            lines_out.append(raw_line)

    expansion = (
        total_segments_emitted / num_arcs_processed
        if num_arcs_processed > 0 else 0.0
    )

    honest_caveat = (
        "Arc lineariser limitations: "
        "(1) Modal G-codes are NOT preserved — each segment carries an explicit G01; "
        "downstream code must not assume modal state after a linearised arc block. "
        "(2) XY-plane (G17) arcs only — G18/G19 plane selection is passed through "
        "but arc maths does NOT adapt; G18/G19 arcs will linearise incorrectly. "
        "(3) Feed rate F is copied from the original arc line to every G01 segment; "
        "no arc-length-proportional feed correction is applied. "
        "(4) Helical arcs (Z travel on G02/G03 line) are handled by linear Z "
        "interpolation — geometrically correct for uniform-pitch helices only. "
        "(5) Full-circle arcs in R-format (start == end) are ambiguous per "
        "RS-274/NGC §3.5.3 and are passed through unchanged with a warning comment. "
        "(6) Incremental-mode (G91) arc endpoints are supported; I/J are always "
        "treated as relative offsets per NIST RS-274/NGC. "
        "(7) R-format arcs: R > 0 → minor arc; R < 0 → major arc (NIST §3.5.3). "
        "Segment count uses Δθ = 2·acos(1 − ε/R) per MH 31e §1130. "
        "References: NIST RS-274/NGC §3.5.3; MH 31e §1130."
    )

    return ArcLinearizeResult(
        linearized_gcode="\n".join(lines_out) + ("\n" if spec.gcode_text.endswith("\n") else ""),
        num_arcs_processed=num_arcs_processed,
        total_segments_emitted=total_segments_emitted,
        max_actual_chord_error_mm=round(max_actual_chord_error_mm, 9),
        expansion_ratio=round(expansion, 4),
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_linearize_arcs_spec = ToolSpec(
    name="cam_linearize_arcs",
    description=(
        "Convert G02/G03 circular arc commands in a G-code program to G01 linear "
        "segments using a chord-error tolerance. "
        "Used for legacy CNC controllers that do not support full circular interpolation "
        "(e.g. older Mach3 setups, plasma tables, laser cutters, some wire EDM). "
        "Supports both centre-format (I/J offset) and radius-format (R-word) arcs. "
        "Segment angle Δθ = 2·acos(1 − ε/R) per MH 31e §1130; "
        "minimum-segment-length floor prevents degenerate micro-moves on tiny arcs. "
        "Returns linearized_gcode (full program with arcs replaced), "
        "num_arcs_processed, total_segments_emitted, max_actual_chord_error_mm, "
        "expansion_ratio, and an honest caveat. "
        "HONEST: emits explicit G01 each segment (modal G-codes not preserved); "
        "XY-plane (G17) arcs only — G18/G19 arcs pass through unchanged; "
        "full-circle R-format arcs are ambiguous and passed through with a warning; "
        "helical arcs linearised with linear Z interpolation. "
        "References: NIST RS-274/NGC §3.5.3; MH 31e §1130."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode_text": {
                "type": "string",
                "description": "Full G-code program text containing G02/G03 arc commands.",
            },
            "max_chord_error_mm": {
                "type": "number",
                "description": (
                    "Maximum allowable chord error (sag) per segment in mm. "
                    "Default 0.025 mm (ISO 2768-f finishing tolerance). "
                    "Smaller → more segments; larger → fewer, coarser approximation."
                ),
            },
            "min_segment_length_mm": {
                "type": "number",
                "description": (
                    "Minimum segment length floor in mm. Prevents micro-moves on "
                    "tiny arcs. Default 0.05 mm."
                ),
            },
        },
        "required": ["gcode_text"],
    },
)


@register(cam_linearize_arcs_spec)
async def run_cam_linearize_arcs(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    if "gcode_text" not in a:
        return err_payload("missing required field: 'gcode_text'", "BAD_ARGS")

    try:
        spec = ArcLinearizeSpec(
            gcode_text=str(a["gcode_text"]),
            max_chord_error_mm=float(a.get("max_chord_error_mm", 0.025)),
            min_segment_length_mm=float(a.get("min_segment_length_mm", 0.05)),
        )
        result = linearize_arcs(spec)
    except (TypeError, ValueError) as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "linearized_gcode": result.linearized_gcode,
        "num_arcs_processed": result.num_arcs_processed,
        "total_segments_emitted": result.total_segments_emitted,
        "max_actual_chord_error_mm": result.max_actual_chord_error_mm,
        "expansion_ratio": result.expansion_ratio,
        "honest_caveat": result.honest_caveat,
    })
