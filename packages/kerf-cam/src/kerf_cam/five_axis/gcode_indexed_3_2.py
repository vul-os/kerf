"""
5-axis G-code emitter for 3+2 indexed CL points (T6).

3+2 indexed means: rotate the table ONCE to a fixed orientation (one A move +
one B move), then run a pure 3-axis cut with A and B held constant.

Structure of the emitted program
---------------------------------
  1. Header  — same as T5 (G54/G90/spindle/coolant/tool comment)
  2. ONE orientation move:  G0 A<a_deg> B<b_deg>   (with optional G43.4 TCP)
  3. Rapid to safe-Z + first XY
  4. G1 plunge to first Z
  5. Pure 3-axis body: every G1 line carries X/Y/Z only; A/B stay parked
  6. Footer: rapid retract to safe-Z, G0 A0 B0 (home rotaries), M9/M5/M30

Key differences from the constant-tilt T5 emitter
----------------------------------------------------
- A/B are emitted ONCE in the orientation move, never on body G1 lines.
- CL points from T4 are already in the rotated frame — pure 3-axis coords.
- The tool-axis vector (i, j, k) is used only to compute the one orientation
  move's A/B angles.  All points in a 3+2 job share the same (i, j, k) by
  T4's construction (constant drive-face normal → same rotation everywhere).
  The emitter reads the first point's i/j/k; if a point has no i/j/k keys
  it falls back to (0, 0, 1) which maps to A=0, B=0 (axis-aligned, plain 3-axis).

Axis-aligned short-circuit (A=B=0)
------------------------------------
When the computed A=0 and B=0 (within 1e-6 deg) the orientation move is
skipped entirely and the output is plain 3-axis G-code.  This happens when
the target face is already normal to +Z.

Home-rotation at end-of-program
---------------------------------
The footer always emits ``G0 A0 B0`` to return the rotaries to home, even
when the job was axis-aligned (it's a no-op in that case).  Rationale: leaving
the table parked at a non-zero orientation after the program ends is a safety
hazard on most machines — the next program (possibly a 3-axis op) will try to
work at the skewed angle.  Returning to home is the safe default; operators
who want to leave the table indexed can comment out the ``G0 A0 B0`` line.

Both LinuxCNC and Fanuc post-processors are supported via ``emit_indexed_3_2``
functions added to the respective modules.
"""

from __future__ import annotations

import math
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from kerf_cam.five_axis.gcode_constant_tilt import PostOpts

from kerf_cam.five_axis.gcode_constant_tilt import _axis_to_ab

# Re-export CLPoint + PostOpts for callers who import from here.
CLPoint = dict  # {"x": float, "y": float, "z": float}
                # optional "i","j","k" on first point to convey orientation


# ---------------------------------------------------------------------------
# Angle extraction from CL point set
# ---------------------------------------------------------------------------

_AXIS_ALIGNED_THRESHOLD_DEG = 1e-6  # degrees; below this: skip orientation move


def _orientation_from_cl_points(cl_points: list[CLPoint]) -> tuple[float, float]:
    """Extract (A_deg, B_deg) from the first CL point's i/j/k.

    If no i/j/k keys are present, returns (0.0, 0.0) — axis-aligned.
    """
    if not cl_points:
        return 0.0, 0.0
    pt = cl_points[0]
    i = float(pt.get("i", 0.0))
    j = float(pt.get("j", 0.0))
    k = float(pt.get("k", 1.0))
    return _axis_to_ab(i, j, k)


def _is_axis_aligned(a_deg: float, b_deg: float) -> bool:
    """Return True when A and B are both within threshold of zero."""
    return abs(a_deg) < _AXIS_ALIGNED_THRESHOLD_DEG and abs(b_deg) < _AXIS_ALIGNED_THRESHOLD_DEG


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def emit_gcode_indexed_3_2(
    cl_points: list[CLPoint],
    post: str,
    opts: Optional["PostOpts"] = None,
) -> str:
    """Turn 3+2 indexed CL points into G-code.

    Parameters
    ----------
    cl_points : list of dicts with keys x, y, z.
                Optional i/j/k on the first point encodes the drive-face
                tool-axis vector (constant for the entire 3+2 op).
                Optional key "feed" or "feed_rate" on each point overrides
                opts.feed_cut_mm_min for that move.
    post      : "linuxcnc" | "fanuc"
    opts      : PostOpts (defaults applied if None)

    Returns
    -------
    str — complete G-code program.
    """
    from kerf_cam.five_axis.gcode_constant_tilt import PostOpts as _PostOpts
    if opts is None:
        opts = _PostOpts()

    opts.apply_tool_defaults()

    _SUPPORTED_KINEMATICS = ("head_table", "table_table", "head_head")
    if opts.machine_kinematic not in _SUPPORTED_KINEMATICS:
        raise NotImplementedError(
            f"machine_kinematic={opts.machine_kinematic!r} is not yet supported. "
            f"Supported: {_SUPPORTED_KINEMATICS}"
        )

    post = post.lower().strip()
    if post == "linuxcnc":
        from kerf_cam.five_axis.posts.linuxcnc_5x import emit_indexed_3_2 as _emit
    elif post == "fanuc":
        from kerf_cam.five_axis.posts.fanuc_5x import emit_indexed_3_2 as _emit
    elif post in ("heidenhain", "heidenhain_tnc", "tnc640", "tnc530"):
        from kerf_cam.five_axis.posts.heidenhain_5x import emit_indexed_3_2 as _emit
    elif post in ("siemens", "siemens_840d", "840d", "sinumerik"):
        from kerf_cam.five_axis.posts.siemens_5x import emit_indexed_3_2 as _emit
    else:
        raise ValueError(
            f"Unknown post-processor {post!r}. "
            "Choose 'linuxcnc', 'fanuc', 'heidenhain', or 'siemens'."
        )

    # Extract the single orientation (A, B) from the first CL point.
    a_deg, b_deg = _orientation_from_cl_points(cl_points)
    axis_aligned = _is_axis_aligned(a_deg, b_deg)

    warnings: list[str] = []
    if axis_aligned:
        warnings.append(
            "; INFO: drive face is axis-aligned (A=0, B=0) — orientation move "
            "skipped; emitting plain 3-axis G-code."
        )
    warnings.append(
        "; WARNING: no collision/gouge check performed — verify toolpath with "
        "CAMotics before sending to machine (5-axis R7)."
    )

    return _emit(cl_points, a_deg, b_deg, axis_aligned, opts, warnings)
