"""
kerf_cad_core.fiveaxis.kinematics — 5-axis machine-tool kinematics & post-processing.

Machine configurations
----------------------
Three classic 5-axis layouts are supported:

  TABLE_TABLE  — two rotary axes in the table (e.g. trunnion AC: A tilts around
                 X-axis, C rotates around Z-axis).  Both pivot centres are in the
                 table/workpiece frame.

  HEAD_HEAD    — two rotary axes in the spindle head (e.g. BC: B tilts around
                 Y-axis, C2 rotates around Z-axis relative to spindle).  The tool
                 tip follows the pivots.

  TABLE_HEAD   — one rotary in the table (A) and one in the head (B), mixed
                 kinematics.

All transforms are 3×3 or 4×4 homogeneous matrices hand-rolled from math.

Conventions
-----------
- All angles in radians internally; callers may use degrees — conversion helpers
  provided.
- Coordinate frame: X-right, Y-into-table, Z-up (ISO-like).
- RTCP (Rotary Tool Centre Point) / TCP compensation: the controller compensates
  the linear axes so the tool tip stays stationary on the part while rotary axes
  move.  pivot_length_mm is the distance from the rotary pivot to the tool tip.
- Positive A-rotation: right-hand-rule around X-axis.
- Positive C-rotation: right-hand-rule around Z-axis.
- Positive B-rotation: right-hand-rule around Y-axis.

Warnings (never raises)
-----------------------
All out-of-range / singularity / linearisation conditions are reported through
the Python ``warnings`` module as ``UserWarning``.

References
----------
Soons, J.A. et al. "Modelling of five-axis machine tool kinematics",
  Int. J. Mach. Tools Manuf., 2001.
Bohez, E.L.J. "Five-axis milling machine tool kinematic chain design and analysis",
  Int. J. Mach. Tools Manuf., 2002.
Tutunea-Fatan, O.R. "Singularity analysis of five-axis machine tools with non-
  orthogonal rotary axes", Int. J. Adv. Manuf. Technol., 2011.

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SINGULARITY_TOL = 1e-6   # near-zero sin(A) → gimbal-lock regime
_OVER_TRAVEL_WARN = "over_travel"
_SINGULARITY_WARN = "singularity"
_LINEARISATION_WARN = "linearisation"


# ---------------------------------------------------------------------------
# Tiny 3-D vector / matrix helpers  (pure Python, no numpy)
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]
Mat3 = Tuple[Tuple[float, float, float], ...]   # 3×3
Mat4 = List[List[float]]                         # 4×4 mutable rows


def _dot3(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross3(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm3(v: Vec3) -> float:
    return math.sqrt(_dot3(v, v))


def _normalise3(v: Vec3) -> Vec3:
    n = _norm3(v)
    if n < 1e-15:
        return (0.0, 0.0, 1.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _scale3(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def _add3(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub3(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _matvec3(M: Mat3, v: Vec3) -> Vec3:
    return (
        M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2],
        M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2],
        M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2],
    )


def _matmul3(A: Mat3, B: Mat3) -> Mat3:
    result = []
    for i in range(3):
        row = []
        for j in range(3):
            s = sum(A[i][k] * B[k][j] for k in range(3))
            row.append(s)
        result.append(tuple(row))
    return tuple(result)


def _identity3() -> Mat3:
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _rotx(a: float) -> Mat3:
    c, s = math.cos(a), math.sin(a)
    return (
        (1.0, 0.0, 0.0),
        (0.0,   c,  -s),
        (0.0,   s,   c),
    )


def _roty(a: float) -> Mat3:
    c, s = math.cos(a), math.sin(a)
    return (
        (  c, 0.0,   s),
        (0.0, 1.0, 0.0),
        ( -s, 0.0,   c),
    )


def _rotz(a: float) -> Mat3:
    c, s = math.cos(a), math.sin(a)
    return (
        (  c,  -s, 0.0),
        (  s,   c, 0.0),
        (0.0, 0.0, 1.0),
    )


def _transpose3(M: Mat3) -> Mat3:
    return (
        (M[0][0], M[1][0], M[2][0]),
        (M[0][1], M[1][1], M[2][1]),
        (M[0][2], M[1][2], M[2][2]),
    )


# ---------------------------------------------------------------------------
# Machine configuration
# ---------------------------------------------------------------------------

class MachineType(str, Enum):
    TABLE_TABLE = "table_table"   # trunnion AC: A around X, C around Z
    HEAD_HEAD   = "head_head"     # spindle BC: B around Y, C around Z
    TABLE_HEAD  = "table_head"    # A in table, B in head


@dataclass
class RotaryAxis:
    """One rotary axis: rotation axis direction + travel limits (radians)."""
    axis: Vec3            # unit vector of rotation axis in machine frame
    lo_rad: float = -math.pi
    hi_rad: float =  math.pi
    name: str = ""


@dataclass
class MachineConfig:
    """
    5-axis machine configuration.

    Parameters
    ----------
    machine_type : MachineType
    first_rotary : RotaryAxis
        For TABLE_TABLE: A (tilts around X).
        For HEAD_HEAD: B (tilts around Y).
        For TABLE_HEAD: A in table (tilts around X).
    second_rotary : RotaryAxis
        For TABLE_TABLE: C (rotates around Z).
        For HEAD_HEAD: C2 (rotates around Z, in spindle).
        For TABLE_HEAD: B in head (tilts around Y).
    pivot_length_mm : float
        Distance from the rotary pivot centre to the tool tip (TCP offset).
        Used for RTCP compensation.
    """
    machine_type: MachineType = MachineType.TABLE_TABLE
    first_rotary: RotaryAxis = field(
        default_factory=lambda: RotaryAxis(
            axis=(1.0, 0.0, 0.0),
            lo_rad=math.radians(-120.0),
            hi_rad=math.radians(30.0),
            name="A",
        )
    )
    second_rotary: RotaryAxis = field(
        default_factory=lambda: RotaryAxis(
            axis=(0.0, 0.0, 1.0),
            lo_rad=math.radians(-360.0),
            hi_rad=math.radians(360.0),
            name="C",
        )
    )
    pivot_length_mm: float = 0.0


# ---------------------------------------------------------------------------
# Rotation matrix from axis + angle (Rodrigues)
# ---------------------------------------------------------------------------

def _rot_axis_angle(axis: Vec3, angle: float) -> Mat3:
    """Rotation matrix for angle (radians) around *axis* (unit vector)."""
    ax, ay, az = _normalise3(axis)
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    return (
        (t * ax * ax + c,     t * ax * ay - s * az, t * ax * az + s * ay),
        (t * ax * ay + s * az, t * ay * ay + c,      t * ay * az - s * ax),
        (t * ax * az - s * ay, t * ay * az + s * ax, t * az * az + c),
    )


# ---------------------------------------------------------------------------
# Forward kinematics
# ---------------------------------------------------------------------------

def forward_kinematics(
    config: MachineConfig,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    first_angle_rad: float,
    second_angle_rad: float,
) -> Dict:
    """
    Forward kinematics: machine axis positions → tool tip & tool axis in part frame.

    For TABLE_TABLE (AC trunnion):
      The workpiece is rotated by A then C.  The tool tip in part frame is:
        P_part = R_C⁻¹ · R_A⁻¹ · (TCP_machine) − pivot_offset
      The tool axis in the *home* position points along –Z.  After rotating the
      table, the tool axis seen from the part frame is:
        tool_axis_part = R_C⁻¹ · R_A⁻¹ · [0,0,−1]

    For HEAD_HEAD (BC spindle):
      The tool is rotated by B then C in the head.  TCP in machine frame:
        TCP_machine = R_B · R_C · [0,0,−pivot] + [X,Y,Z]

    For TABLE_HEAD (A table, B head):
      Mixed: table rotates workpiece by A; head rotates tool by B.

    Parameters
    ----------
    config            : MachineConfig
    x_mm, y_mm, z_mm : Linear axis positions (mm).
    first_angle_rad   : First rotary angle (A or B), radians.
    second_angle_rad  : Second rotary angle (C), radians.

    Returns
    -------
    dict with:
      tip_part_mm : [x, y, z]  — tool tip in part frame (mm)
      tool_axis   : [ix,iy,iz] — unit vector of tool axis in part frame
      warnings    : list of str
    """
    warns: List[str] = []
    _check_travel(config.first_rotary,  first_angle_rad,  warns)
    _check_travel(config.second_rotary, second_angle_rad, warns)

    mt = config.machine_type
    R1 = _rot_axis_angle(config.first_rotary.axis,  first_angle_rad)
    R2 = _rot_axis_angle(config.second_rotary.axis, second_angle_rad)
    pl = config.pivot_length_mm

    if mt == MachineType.TABLE_TABLE:
        # Table rotates: R = R2 · R1 (C applied after A)
        R_table = _matmul3(R2, R1)
        R_table_T = _transpose3(R_table)
        # Tool tip in machine: [X, Y, Z]
        tool_tip_machine: Vec3 = (x_mm, y_mm, z_mm)
        # In part frame: undo table rotation
        tip_part = _matvec3(R_table_T, tool_tip_machine)
        # Tool axis in machine is always [0, 0, -1] (spindle points down)
        tool_axis_machine: Vec3 = (0.0, 0.0, -1.0)
        tool_axis_part = _matvec3(R_table_T, tool_axis_machine)

    elif mt == MachineType.HEAD_HEAD:
        # Spindle rotates tool: R = R1 · R2 (B then C in head)
        R_head = _matmul3(R1, R2)
        # Tool axis in machine: rotate home direction [0,0,-1]
        tool_axis_machine = _matvec3(R_head, (0.0, 0.0, -1.0))
        # TCP offset: pivot along -Z in head frame then rotated
        pivot_vec_head: Vec3 = (0.0, 0.0, -pl)
        pivot_vec_machine = _matvec3(R_head, pivot_vec_head)
        tip_machine_x = x_mm + pivot_vec_machine[0]
        tip_machine_y = y_mm + pivot_vec_machine[1]
        tip_machine_z = z_mm + pivot_vec_machine[2]
        tip_part = (tip_machine_x, tip_machine_y, tip_machine_z)
        tool_axis_part = tool_axis_machine

    else:  # TABLE_HEAD
        # Table rotates workpiece by R1 (A axis)
        # Head rotates tool by R2 (B axis)
        R_table_T = _transpose3(R1)
        # Tool axis in machine (head rotated)
        tool_axis_machine = _matvec3(R2, (0.0, 0.0, -1.0))
        # Tool axis in part frame: undo table rotation
        tool_axis_part = _matvec3(R_table_T, tool_axis_machine)
        # Pivot in machine
        pivot_vec_machine = _matvec3(R2, (0.0, 0.0, -pl))
        tip_machine_x = x_mm + pivot_vec_machine[0]
        tip_machine_y = y_mm + pivot_vec_machine[1]
        tip_machine_z = z_mm + pivot_vec_machine[2]
        tip_machine: Vec3 = (tip_machine_x, tip_machine_y, tip_machine_z)
        tip_part = _matvec3(R_table_T, tip_machine)

    return {
        "ok": True,
        "tip_part_mm": list(tip_part),
        "tool_axis": list(_normalise3(tool_axis_part)),
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Inverse post-processing
# ---------------------------------------------------------------------------

def _wrap_angle(a: float) -> float:
    """Wrap angle to (−π, π]."""
    a = math.fmod(a, 2.0 * math.pi)
    if a > math.pi:
        a -= 2.0 * math.pi
    elif a <= -math.pi:
        a += 2.0 * math.pi
    return a


def _shortest_path(current: float, target: float) -> float:
    """Return the angular target closest to *current* (within ±π of current)."""
    delta = _wrap_angle(target - current)
    return current + delta


def _check_travel(
    axis: RotaryAxis,
    angle_rad: float,
    warns: List[str],
) -> None:
    if angle_rad < axis.lo_rad or angle_rad > axis.hi_rad:
        msg = (
            f"{_OVER_TRAVEL_WARN}: {axis.name} angle "
            f"{math.degrees(angle_rad):.3f}° outside "
            f"[{math.degrees(axis.lo_rad):.1f}°, "
            f"{math.degrees(axis.hi_rad):.1f}°]"
        )
        warnings.warn(msg, UserWarning, stacklevel=5)
        warns.append(msg)


def _ik_table_table(
    config: MachineConfig,
    tip_part_mm: Vec3,
    tool_axis_part: Vec3,
) -> List[Tuple[float, float]]:
    """
    Inverse kinematics for TABLE_TABLE (AC trunnion).

    Tool axis in part frame = R_C^T · R_A^T · [0, 0, -1]
    => R_A · R_C · tool_axis_part = [0, 0, -1]

    For AC (A around X, C around Z):
      After algebra:
        tx, ty, tz = tool_axis_part  (unit vector pointing *away* from spindle)
      We want the part-frame tool axis expressed as T_part:
        Since tool_axis in machine = [0,0,-1],
        tool_axis_part = R_table^T · [0,0,-1]  where R_table = R_C · R_A
      Equivalently, [0,0,-1] = R_table · tool_axis_part = R_C · R_A · tool_axis_part

      Let n = -tool_axis_part (pointing +Z in machine when angles=0).
        n = R_C · R_A · [0,0,1]

      R_A = Rx(a):  Rx(a)·[0,0,1] = [0, -sin(a), cos(a)]
      R_C = Rz(c):  Rz(c)·[0,-sin(a),cos(a)] = [sin(a)sin(c), -sin(a)cos(c), cos(a)]

      So nx = sin(a)sin(c), ny = -sin(a)cos(c), nz = cos(a).

      => A = atan2(±√(nx²+ny²), nz)   (two solutions ±sin(A))
         C = atan2(-ny/sin(A), nx/sin(A)) = atan2(ny_norm, nx_norm) adjusted

    Returns list of (A_rad, C_rad) solution pairs.
    """
    tx, ty, tz = tool_axis_part
    # n = -tool_axis_part (the direction that maps to [0,0,1] after R_table)
    nx, ny, nz = -tx, -ty, -tz

    r_xy = math.sqrt(nx * nx + ny * ny)

    solutions: List[Tuple[float, float]] = []

    for sign in (+1.0, -1.0):
        sin_a = sign * r_xy
        cos_a = nz
        a = math.atan2(sin_a, cos_a)

        if abs(sin_a) < _SINGULARITY_TOL:
            # Gimbal lock: A near 0 or π; C is degenerate → set C=0
            c = 0.0
        else:
            # C: atan2(sin(C), cos(C)) from nx = sin(a)sin(c), ny = -sin(a)cos(c)
            sin_c = nx / sin_a
            cos_c = -ny / sin_a
            c = math.atan2(sin_c, cos_c)

        solutions.append((a, c))

    return solutions


def _ik_head_head(
    config: MachineConfig,
    tip_part_mm: Vec3,
    tool_axis_part: Vec3,
) -> List[Tuple[float, float]]:
    """
    Inverse kinematics for HEAD_HEAD (BC spindle).

    For BC (B around Y, C around Z in head):
      tool_axis_machine = R_B · R_C · [0,0,-1] = -R_B · R_C · [0,0,1]
      R_C · [0,0,1] = [0,0,1]  (C is rotation around Z, doesn't change Z-column)
      So tool_axis_machine = -R_B · [0,0,1] = [-sin(B), 0, -cos(B)]  (wrong — let's derive)

      Actually R_B = Ry(b):
        Ry(b)·[0,0,1] = [sin(b), 0, cos(b)]
        Ry(b)·[0,0,-1] = [-sin(b), 0, -cos(b)]

      R_C = Rz(c):  Rz(c)·[0,0,-1] = [0, 0, -1]   (Z-axis invariant under Rz)

      So tool_axis_machine = R_B · R_C · [0,0,-1] = R_B · [0,0,-1]
                            = [-sin(B), 0, -cos(B)]

      But C rotates the head around Z; for BC the second axis C is *after* B in the
      kinematic chain (B first, C second):
        R_head = R_B · R_C
        tool_axis_machine = R_B · R_C · [0,0,-1] = R_B · [0,0,-1] (C doesn't affect Z)

      For a proper BC where C precedes B:
        R_head = R_C · R_B
        tool_axis_machine = R_C · R_B · [0,0,-1]
        R_B · [0,0,-1] = [-sin(b), 0, -cos(b)]
        R_C · [-sin(b), 0, -cos(b)] = [-sin(b)cos(c), -sin(b)sin(c), ... wait

      Let's go with first_rotary = B (around Y), second_rotary = C (around Z),
      R_head = R_first · R_second = R_B · R_C.

      R_C · [0,0,-1] = [0, 0, -1]  (Rz leaves Z invariant)
      R_B · [0,0,-1] = [-sin(b), 0, -cos(b)]

      So tool_axis_machine = [-sin(b), 0, -cos(b)] regardless of C.
      C determines which direction in the XY-plane the tool points when tilted.

      More general: for the actual B·C chain:
        d = [0,0,-1] → after R_C: still [0,0,-1]
        → after R_B: [-sin(b), 0, -cos(b)]

      So B controls tilt angle, C controls rotation in XY.

      For solving B from tool axis (tx, ty, tz):
        tool_axis_part = tool_axis_machine (head–head: no table rotation)
        tx = -sin(b)  → b = atan2(-tx_in_b_plane, ...)

      Actually since C rotates first (before B in chain), we need to separate:
        tx_machine = R_B·R_C·[0,0,-1] evaluated:
          Let me do it step by step:
          v0 = [0,0,-1]
          v1 = R_C · v0 = Rz(c)·[0,0,-1] = [0,0,-1]  (Z invariant under Rz)
          v2 = R_B · v1 = Ry(b)·[0,0,-1] = [sin(b)·0 ... ]

        Ry(b) = [[cos(b), 0, sin(b)], [0,1,0], [-sin(b), 0, cos(b)]]
        Ry(b)·[0,0,-1] = [sin(b)·(-1)... ] = [-sin(b), 0, -cos(b)]  wait:
        Ry(b)·[0,0,-1]:
          x: cos(b)·0 + 0·0 + sin(b)·(-1) = -sin(b)
          y: 0
          z: -sin(b)·0 + 0·0 + cos(b)·(-1) = -cos(b)
        → tool_axis_machine = (-sin(b), 0, -cos(b))

      This is independent of C!  So C determines the XY orientation of the tilted
      plane but doesn't appear in the tool axis for this orientation convention.

      For a proper formulation where B is the tilt (around Y) and C is first rotation
      (the collar, around Z), we instead think of it as:
        The spindle home direction is [0,0,-1].
        C rotates the whole head around Z by c.
        B tilts the spindle around the (now-rotated) Y-like axis.

      Convention used here (as in many real machines):
        R_head = R_C · R_B  (C outermost: C rotates base, B tilts relative to C)
        v1 = R_B · [0,0,-1] = (-sin(b), 0, -cos(b))
        v2 = R_C · v1 = Rz(c) · (-sin(b), 0, -cos(b))
           = (-sin(b)cos(c) - 0·sin(c), -sin(b)·(-sin(c)) + 0·cos(c), -cos(b))
             wait, Rz(c) = [[cos(c),-sin(c),0],[sin(c),cos(c),0],[0,0,1]]
           = ((-sin(b))cos(c), (-sin(b))sin(c), -cos(b))

      So tx = -sin(b)cos(c), ty = -sin(b)sin(c), tz = -cos(b).

      From tz = -cos(b):  b = ±acos(-tz)
      From tx,ty: c = atan2(-ty/sin(b), -tx/sin(b))

    HEAD_HEAD uses R_head = R_C · R_B (C outermost).
    Returns list of (B_rad, C_rad) solution pairs.
    """
    tx, ty, tz = tool_axis_part

    # tz = -cos(b)  → cos(b) = -tz
    cos_b = -tz
    cos_b = max(-1.0, min(1.0, cos_b))  # clamp for acos

    solutions: List[Tuple[float, float]] = []
    for sign in (+1.0, -1.0):
        sin_b = sign * math.sqrt(max(0.0, 1.0 - cos_b ** 2))
        b = math.atan2(sin_b, cos_b)

        if abs(sin_b) < _SINGULARITY_TOL:
            # Gimbal lock: B ≈ 0 or π → C degenerate
            c = 0.0
        else:
            # tx = -sin(b)cos(c), ty = -sin(b)sin(c)
            cos_c = -tx / sin_b
            sin_c = -ty / sin_b
            c = math.atan2(sin_c, cos_c)

        solutions.append((b, c))

    return solutions


def _ik_table_head(
    config: MachineConfig,
    tip_part_mm: Vec3,
    tool_axis_part: Vec3,
) -> List[Tuple[float, float]]:
    """
    Inverse kinematics for TABLE_HEAD (A table, B head).

    tool_axis_part = R_A^T · R_B · [0,0,-1]
    Let n = -tool_axis_part, then:
        R_A · n = R_B · [0,0,1]

    R_B · [0,0,1] = [sin(b), 0, cos(b)]  (from Ry(b))
    R_A · n: use R_A = Rx(a), write n = (nx, ny, nz):
        Rx(a)·n = (nx, ny·cos(a) - nz·sin(a), ny·sin(a) + nz·cos(a))
    Set equal to [sin(b), 0, cos(b)]:
        nx = sin(b)                  ... (i)
        ny·cos(a) - nz·sin(a) = 0   ... (ii) => tan(a) = ny/nz
        ny·sin(a) + nz·cos(a) = cos(b) ... (iii)

    From (ii): a = atan2(ny, nz)  (two solutions ±a)
    Then b = atan2(nx, ny·sin(a)+nz·cos(a))

    Returns list of (A_rad, B_rad) solution pairs.
    """
    tx, ty, tz = tool_axis_part
    nx, ny, nz = -tx, -ty, -tz

    solutions: List[Tuple[float, float]] = []

    for sign in (+1.0, -1.0):
        a = math.atan2(sign * ny, sign * nz)
        cos_b = ny * math.sin(a) + nz * math.cos(a)
        sin_b = nx
        b = math.atan2(sin_b, cos_b)
        solutions.append((a, b))

    return solutions


def _rtcp_linear(
    config: MachineConfig,
    tip_part_mm: Vec3,
    first_angle_rad: float,
    second_angle_rad: float,
) -> Vec3:
    """
    RTCP compensation: compute the linear axis (X, Y, Z) positions in machine
    coordinates given the desired tool-tip position in part coordinates and the
    rotary angles.

    TABLE_TABLE (AC):
      R_table = R_C · R_A  (table rotation applied to part)
      The tool tip in machine = R_table · tip_part
      But the spindle pivot offset adds:  TCP_machine = R_table · tip_part
      (pivot_length is already included in the forward FK sense, but for RTCP
       we add the pivot back so the controller can compensate):
      X = R_table · tip_part + pivot_along_Z_in_machine

    HEAD_HEAD (BC):
      Table doesn't move; the head pivot shifts the TCP:
      tip_machine = [X,Y,Z] + R_head · [0,0,-pivot]
      => [X,Y,Z] = tip_part - R_head · [0,0,-pivot]
      (In head-head there is no table rotation; part frame = machine frame.)

    TABLE_HEAD:
      tip_machine = R_A · tip_part  (undo table rotation to get machine pos)
      [X,Y,Z] = R_A · tip_part - R_B · [0,0,-pivot]
    """
    pl = config.pivot_length_mm
    mt = config.machine_type

    R1 = _rot_axis_angle(config.first_rotary.axis,  first_angle_rad)
    R2 = _rot_axis_angle(config.second_rotary.axis, second_angle_rad)

    if mt == MachineType.TABLE_TABLE:
        R_table = _matmul3(R2, R1)
        tip_m = _matvec3(R_table, tip_part_mm)
        # Add pivot offset along machine Z (spindle is always vertical in machine)
        return (tip_m[0], tip_m[1], tip_m[2] + pl)

    elif mt == MachineType.HEAD_HEAD:
        # R_head = R_C · R_B  (C outermost)
        R_head = _matmul3(R2, R1)
        pivot_in_head = (0.0, 0.0, -pl)
        pivot_machine = _matvec3(R_head, pivot_in_head)
        return (
            tip_part_mm[0] - pivot_machine[0],
            tip_part_mm[1] - pivot_machine[1],
            tip_part_mm[2] - pivot_machine[2],
        )

    else:  # TABLE_HEAD
        tip_m = _matvec3(R1, tip_part_mm)
        R_head = R2
        pivot_machine = _matvec3(R_head, (0.0, 0.0, -pl))
        return (
            tip_m[0] - pivot_machine[0],
            tip_m[1] - pivot_machine[1],
            tip_m[2] - pivot_machine[2],
        )


def inverse_post(
    config: MachineConfig,
    tip_part_mm: Tuple[float, float, float],
    tool_axis: Tuple[float, float, float],
    prev_angles_rad: Optional[Tuple[float, float]] = None,
    avoidance_tilt_rad: float = math.radians(1.0),
) -> Dict:
    """
    Inverse post-processing: tool tip + tool axis → rotary angles + XYZ (RTCP).

    Parameters
    ----------
    config           : MachineConfig
    tip_part_mm      : (x, y, z) — desired tool-tip position in part frame (mm).
    tool_axis        : (ix, iy, iz) — desired tool axis direction (unit vector).
                       Points away from the part surface (i.e. in the direction the
                       spindle faces FROM the part).
    prev_angles_rad  : (q1, q2) previous rotary positions; used for
                       shortest-angular-path selection and C-wind avoidance.
    avoidance_tilt_rad : Small tilt applied when singularity is detected (radians).

    Returns
    -------
    dict with:
      solutions      : list of {q1_rad, q1_deg, q2_rad, q2_deg,
                                x_mm, y_mm, z_mm}
      best           : index into solutions of the preferred solution
                       (closest to prev_angles, inside travel limits)
      warnings       : list of str
      singularity    : bool
      over_travel    : bool
    """
    warns: List[str] = []
    tip = tuple(tip_part_mm)  # type: ignore[arg-type]
    axis = _normalise3(tool_axis)

    # Singularity detection: tool axis pointing straight down [-Z in part frame]
    # For TABLE_TABLE, the critical direction is the A-axis pole: axis = [0,0,1]
    # For HEAD_HEAD, it's when sin(B)=0.
    # We detect by checking the magnitude of the component perpendicular to Z.
    perp = math.sqrt(axis[0] ** 2 + axis[1] ** 2)
    is_singular = perp < _SINGULARITY_TOL

    if is_singular:
        msg = (
            f"{_SINGULARITY_WARN}: tool axis is along machine Z "
            f"(|perp|={perp:.2e}); C-axis is degenerate. "
            f"Applied avoidance tilt of {math.degrees(avoidance_tilt_rad):.2f}°."
        )
        warnings.warn(msg, UserWarning, stacklevel=3)
        warns.append(msg)
        # Apply a small tilt around X to escape the pole
        r_tilt = _rotx(avoidance_tilt_rad)
        axis = _normalise3(_matvec3(r_tilt, axis))

    mt = config.machine_type
    if mt == MachineType.TABLE_TABLE:
        raw_solutions = _ik_table_table(config, tip, axis)
    elif mt == MachineType.HEAD_HEAD:
        raw_solutions = _ik_head_head(config, tip, axis)
    else:
        raw_solutions = _ik_table_head(config, tip, axis)

    solutions = []
    over_travel = False

    for q1, q2 in raw_solutions:
        sol_warns: List[str] = []

        # Shortest path selection
        if prev_angles_rad is not None:
            q1 = _shortest_path(prev_angles_rad[0], q1)
            q2 = _shortest_path(prev_angles_rad[1], q2)

        _check_travel(config.first_rotary,  q1, sol_warns)
        _check_travel(config.second_rotary, q2, sol_warns)
        if sol_warns:
            over_travel = True
            warns.extend(sol_warns)

        # RTCP: compute machine XYZ
        x, y, z = _rtcp_linear(config, tip, q1, q2)  # type: ignore[arg-type]

        solutions.append({
            "q1_rad": q1,
            "q1_deg": math.degrees(q1),
            "q2_rad": q2,
            "q2_deg": math.degrees(q2),
            "x_mm": x,
            "y_mm": y,
            "z_mm": z,
        })

    # Best solution: prefer the one closest to prev_angles and within travel limits
    best = _select_best(solutions, config, prev_angles_rad)

    return {
        "ok": True,
        "solutions": solutions,
        "best": best,
        "singularity": is_singular,
        "over_travel": over_travel,
        "warnings": warns,
    }


def _select_best(
    solutions: List[Dict],
    config: MachineConfig,
    prev_angles: Optional[Tuple[float, float]],
) -> int:
    """Return index of the solution with smallest angular travel (or smallest
    absolute position if no prev_angles given)."""
    def _in_limits(s: Dict) -> bool:
        q1, q2 = s["q1_rad"], s["q2_rad"]
        return (
            config.first_rotary.lo_rad  <= q1 <= config.first_rotary.hi_rad and
            config.second_rotary.lo_rad <= q2 <= config.second_rotary.hi_rad
        )

    def _cost(i: int) -> float:
        s = solutions[i]
        if prev_angles is not None:
            d1 = abs(s["q1_rad"] - prev_angles[0])
            d2 = abs(s["q2_rad"] - prev_angles[1])
        else:
            d1 = abs(s["q1_rad"])
            d2 = abs(s["q2_rad"])
        # Prefer in-limits solutions
        penalty = 0.0 if _in_limits(s) else 1e9
        return d1 + d2 + penalty

    if not solutions:
        return 0
    return min(range(len(solutions)), key=_cost)


# ---------------------------------------------------------------------------
# Lead/lag & tilt to tool-axis vector
# ---------------------------------------------------------------------------

def tool_axis_from_lead_lag(
    feed_direction: Tuple[float, float, float],
    surface_normal: Tuple[float, float, float],
    lead_angle_rad: float,
    lag_angle_rad: float = 0.0,
) -> Dict:
    """
    Convert lead/lag angles + feed direction + surface normal → tool axis unit vector.

    Lead angle: tilt in the feed-direction plane (positive = lean forward).
    Lag  angle: tilt perpendicular to feed (positive = lean to the right of feed).

    The tool axis starts perpendicular to the surface (along -surface_normal),
    then is tilted by lead in the feed plane, then by lag in the cross-feed plane.

    Parameters
    ----------
    feed_direction   : Unit vector of cutter path direction.
    surface_normal   : Surface normal at the contact point (pointing away from material).
    lead_angle_rad   : Lead angle (radians, positive = lean forward).
    lag_angle_rad    : Lag/tilt angle (radians, positive = lean right).

    Returns
    -------
    dict with:
      tool_axis : [ix, iy, iz] — unit vector of tool axis (pointing away from part).
    """
    n = _normalise3(surface_normal)
    f = _normalise3(feed_direction)

    # Side vector: cross(feed, normal)
    side = _normalise3(_cross3(f, n))

    # Start tool axis perpendicular to surface (pointing opposite to normal into part)
    # In 5-axis convention, tool_axis points AWAY from part (same as normal direction here)
    # We rotate the normal by lead and lag angles.
    # Rotation for lead: around side axis (lean forward/backward)
    r_lead = _rot_axis_angle(side, -lead_angle_rad)
    # Rotation for lag:  around feed axis (lean left/right)
    r_lag  = _rot_axis_angle(f,    lag_angle_rad)

    tool_ax = _matvec3(r_lag, _matvec3(r_lead, n))
    return {
        "ok": True,
        "tool_axis": list(_normalise3(tool_ax)),
    }


# ---------------------------------------------------------------------------
# Linearisation error
# ---------------------------------------------------------------------------

def linearisation_segments(
    config: MachineConfig,
    tip_part_mm: Tuple[float, float, float],
    q1_start_rad: float,
    q1_end_rad: float,
    q2_start_rad: float,
    q2_end_rad: float,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    z_mm: float = 0.0,
    chord_tol_mm: float = 0.01,
) -> Dict:
    """
    Estimate the number of linear interpolation segments needed for a rotary move
    to keep the chord deviation of the tool-tip arc within *chord_tol_mm*.

    For a circular arc of radius R and subtended angle θ:
        chord_deviation = R · (1 − cos(θ/2))   ≈ R·θ²/8  for small θ

    The tool-tip traces an arc whose radius R is the distance from the rotary pivot
    to the tool tip.  We compute R from forward kinematics at the start position.

    Parameters
    ----------
    config         : MachineConfig
    tip_part_mm    : Tool-tip position in part frame (mm).
    q1_start_rad   : First rotary start angle (radians).
    q1_end_rad     : First rotary end angle (radians).
    q2_start_rad   : Second rotary start angle (radians).
    q2_end_rad     : Second rotary end angle (radians).
    x_mm, y_mm, z_mm : Linear axis start positions (used for arc radius).
    chord_tol_mm   : Maximum allowable chord deviation (mm, default 0.01).

    Returns
    -------
    dict with:
      n_segments : int  — number of linear segments required (≥ 1)
      arc_radius_mm : float — estimated tool-tip arc radius
      subtended_angle_rad : float
      chord_deviation_mm : float  — deviation for the given n_segments
      warnings : list of str
    """
    warns: List[str] = []

    # Use the larger of the two angular motions
    dq1 = abs(q1_end_rad - q1_start_rad)
    dq2 = abs(q2_end_rad - q2_start_rad)
    total_angle = max(dq1, dq2)

    if total_angle < 1e-12:
        return {
            "ok": True,
            "n_segments": 1,
            "arc_radius_mm": 0.0,
            "subtended_angle_rad": 0.0,
            "chord_deviation_mm": 0.0,
            "warnings": warns,
        }

    # Estimate arc radius: distance from pivot origin to tool tip
    # We approximate R as the distance of the tip from machine origin projected
    # We use the pivot_length + distance in part frame from FK.
    fk = forward_kinematics(
        config, x_mm, y_mm, z_mm, q1_start_rad, q2_start_rad
    )
    tip_m = fk["tip_part_mm"]
    # Approximate R as distance from pivot (origin) to tip
    R = math.sqrt(tip_m[0] ** 2 + tip_m[1] ** 2 + tip_m[2] ** 2)
    if R < 1e-9:
        R = config.pivot_length_mm  # fallback

    if R < 1e-9:
        return {
            "ok": True,
            "n_segments": 1,
            "arc_radius_mm": 0.0,
            "subtended_angle_rad": total_angle,
            "chord_deviation_mm": 0.0,
            "warnings": warns,
        }

    # chord_deviation per segment = R · (1 − cos(θ_seg/2))
    # For small angles: ≈ R·(θ_seg)²/8
    # Solve for n: R·(total_angle/n)²/8 ≤ chord_tol
    # n ≥ total_angle · √(R / (8·chord_tol))
    n_float = total_angle * math.sqrt(R / (8.0 * chord_tol_mm))
    n_segments = max(1, math.ceil(n_float))

    theta_seg = total_angle / n_segments
    chord_dev = R * (1.0 - math.cos(theta_seg / 2.0))

    _LINEARISATION_THRESHOLD = 100
    if n_segments > _LINEARISATION_THRESHOLD:
        msg = (
            f"{_LINEARISATION_WARN}: rotary move requires {n_segments} segments "
            f"(arc_radius={R:.2f} mm, angle={math.degrees(total_angle):.2f}°, "
            f"tol={chord_tol_mm} mm). Consider splitting the move."
        )
        warnings.warn(msg, UserWarning, stacklevel=3)
        warns.append(msg)

    return {
        "ok": True,
        "n_segments": n_segments,
        "arc_radius_mm": R,
        "subtended_angle_rad": total_angle,
        "chord_deviation_mm": chord_dev,
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Feed-rate on rotary moves
# ---------------------------------------------------------------------------

def rotary_feedrate(
    arc_radius_mm: float,
    desired_tip_speed_mm_per_min: float,
    method: str = "dpm",
) -> Dict:
    """
    Compute the rotary feed-rate for a tool-tip arc move.

    Two methods:
      'dpm'          — Degrees Per Minute.  F_dpm = V_tip · (180/π) / R
      'inverse_time' — G93 inverse-time F = V_tip / L_total  [1/min]
                       where L_total is arc-length per deg (caller scales).
                       Returns F_inverse in [1/min] for a 1-degree move arc.

    Parameters
    ----------
    arc_radius_mm             : Tool-tip arc radius (mm).  Must be > 0.
    desired_tip_speed_mm_per_min : Desired tool-tip speed (mm/min).  Must be > 0.
    method                    : 'dpm' or 'inverse_time' (default 'dpm').

    Returns
    -------
    dict with feed_dpm or feed_inverse_time (units per description above).
    """
    if arc_radius_mm <= 0.0:
        return {"ok": False, "reason": "arc_radius_mm must be > 0"}
    if desired_tip_speed_mm_per_min <= 0.0:
        return {"ok": False, "reason": "desired_tip_speed_mm_per_min must be > 0"}
    if method not in ("dpm", "inverse_time"):
        return {"ok": False, "reason": f"unknown method '{method}'; use 'dpm' or 'inverse_time'"}

    if method == "dpm":
        # V = R · ω    ω [rad/min] = V/R    F_dpm = ω·(180/π)
        omega_rad_per_min = desired_tip_speed_mm_per_min / arc_radius_mm
        feed_dpm = omega_rad_per_min * (180.0 / math.pi)
        return {"ok": True, "feed_dpm": feed_dpm, "method": "dpm"}
    else:
        # G93 inverse time: F = 1 / (arc_length_move / V_tip)
        # For one degree of arc: arc_length_1deg = R * π/180
        arc_len_1deg = arc_radius_mm * math.pi / 180.0
        feed_inv = desired_tip_speed_mm_per_min / arc_len_1deg
        return {"ok": True, "feed_inverse_time_per_min": feed_inv, "method": "inverse_time"}


# ---------------------------------------------------------------------------
# Collision cone clearance
# ---------------------------------------------------------------------------

def collision_cone_check(
    tool_axis: Tuple[float, float, float],
    half_cone_angle_rad: float,
    holder_tilt_rad: float = 0.0,
) -> Dict:
    """
    Simple tool / holder collision-cone clearance check.

    Models the holder as a cone centred on the tool axis.  The check determines
    whether the holder tilt angle (the angle between the tool axis and the
    surface normal) exceeds the clearance half-cone angle.

    A tilt larger than (π/2 − half_cone_angle) means the cone intersects the
    surface plane.

    Parameters
    ----------
    tool_axis          : Unit vector of tool axis (pointing away from part).
    half_cone_angle_rad: Half-cone angle of the holder (radians, 0…π/2).
    holder_tilt_rad    : Current tilt angle between tool axis and surface normal
                         (radians, 0 = perpendicular, π/2 = horizontal).
                         If 0.0, tilt is computed from the tool axis vs. Z-up.

    Returns
    -------
    dict with:
      clearance_ok    : bool
      clearance_angle_rad : float  — available clearance (can be negative if violation)
      half_cone_deg   : float
      tilt_deg        : float
    """
    if half_cone_angle_rad < 0.0 or half_cone_angle_rad > math.pi / 2.0:
        return {"ok": False, "reason": "half_cone_angle_rad must be in [0, π/2]"}

    ax = _normalise3(tool_axis)

    # If holder_tilt_rad is not provided, compute from tool_axis vs Z-up = [0,0,1]
    if holder_tilt_rad == 0.0:
        # tilt = angle between tool_axis and +Z
        cos_tilt = ax[2]  # dot(ax, [0,0,1])
        cos_tilt = max(-1.0, min(1.0, cos_tilt))
        tilt = math.acos(abs(cos_tilt))
    else:
        tilt = abs(holder_tilt_rad)

    # Maximum allowable tilt for clearance: π/2 − half_cone
    max_tilt = math.pi / 2.0 - half_cone_angle_rad
    clearance = max_tilt - tilt
    clearance_ok = clearance >= 0.0

    if not clearance_ok:
        msg = (
            f"collision_cone: holder tilt {math.degrees(tilt):.2f}° exceeds "
            f"clearance limit {math.degrees(max_tilt):.2f}° "
            f"(half-cone {math.degrees(half_cone_angle_rad):.2f}°)."
        )
        warnings.warn(msg, UserWarning, stacklevel=3)

    return {
        "ok": True,
        "clearance_ok": clearance_ok,
        "clearance_angle_rad": clearance,
        "clearance_angle_deg": math.degrees(clearance),
        "half_cone_deg": math.degrees(half_cone_angle_rad),
        "tilt_deg": math.degrees(tilt),
    }
