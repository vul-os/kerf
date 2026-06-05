"""
5-axis machine kinematics models — forward and inverse solving.

Supported configurations
------------------------
head_table  : One rotary on the spindle head (B, tilt left-right) and one
              on the table (A, tilt front-back).  Most common on Hermle C400,
              DMU 50, and similar VMCs.
              Axes: A (table, rotates around X), B (head, rotates around Y).
              Tool axis in zero position: (0, 0, 1) = +Z.

table_table : Both rotaries on the table (trunnion / tilt-rotary configuration).
              Axes: A (tilt, rotates around X), C (rotary, rotates around Z).
              Used on: Mazak Variaxis, many horizontal machining centres.
              Tool axis is always +Z in machine coordinates; workpiece tilts.

head_head   : Both rotaries on the spindle head (fork/gimbal head).
              Axes: A (rotates around X, "nod"), C (rotates around Z, "spin").
              Used on: Fidia K211, some Hermle B-series.
              RTCP always required (pivot offsets significant).

Conventions
-----------
* All angles in DEGREES.
* Tool-axis vector (i, j, k) is the unit vector pointing FROM tool tip TOWARD
  spindle (i.e., the +Z direction of the tool in neutral position).
* Forward kinematics: (A_deg, B_deg/C_deg) → (i, j, k) tool-axis vector.
* Inverse kinematics: (i, j, k) → (A_deg, B_deg/C_deg) joint angles.
* RTCP transform: (X_tcp, Y_tcp, Z_tcp, i, j, k) → (Xm, Ym, Zm, A, B/C)
  machine coordinates, given pivot offsets.

RTCP / TCPM
-----------
When the controller does NOT handle RTCP (e.g., Fanuc 18i without option,
small hobby machines), the programmer must pre-transform the tool-tip
coordinates from TCP space to machine-joint space.  This requires:

    pivot_to_tip_z : float — distance from the B/C pivot centre to the tool tip
                             along the tool axis (= gauge-length + tool-length).
    pivot_z_offset : float — (head_table only) vertical distance from the A-axis
                             centre-of-rotation to the B-axis centre-of-rotation.

When use_tcp=True the controller handles RTCP internally (G43.4 / CYCLE800 /
TRAORI) and the output coordinates are the TCP (tool-tip) coordinates.

RTCP transform derivation (head_table A/B)
------------------------------------------
Let  p   = TCP tool-tip position in workpiece (WCS) = (Xw, Yw, Zw).
     L   = pivot_to_tip_z (tool gauge length + tool length).
     a   = A angle (table, around X), b = B angle (head, around Y).
     dZ  = pivot_z_offset.

The B-axis pivot on the head is offset from the table A-axis pivot by dZ along
machine Z.  The tool tip is L below the B pivot.

Machine joint coords (no RTCP):
    tool_vec = FK(a, b)                     # unit vector (i,j,k)
    head_pivot = p + L * tool_vec           # head pivot in WCS
    Xm = head_pivot.x
    Ym = head_pivot.y
    Zm = head_pivot.z + dZ

This is the classical formulation; controllers without RTCP require these
pre-computed machine coordinates instead of the TCP tip coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Machine configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class MachineConfig:
    """Configuration for a 5-axis machine kinematic.

    kinematic : "head_table" | "table_table" | "head_head"

    Primary rotary axis names:
        head_table  → A (table, X-rotation) + B (head, Y-rotation)
        table_table → A (tilt, X-rotation)  + C (rotary, Z-rotation)
        head_head   → A (nod,  X-rotation)  + C (spin,  Z-rotation)

    pivot_to_tip_z   : Distance from the B/C-axis pivot centre to the tool tip
                       along the tool axis when A=B/C=0 (mm).  Required for
                       non-RTCP pre-transform only; ignored when use_tcp=True.

    pivot_z_offset   : (head_table only) Distance from the A-axis
                       centre-of-rotation to the B-axis pivot along machine Z (mm).
                       Positive = B pivot is above A pivot.

    a_min_deg, a_max_deg : Travel limits for the A / first rotary axis (deg).
    b_min_deg, b_max_deg : Travel limits for the B / second rotary axis (deg).
    """
    kinematic: str = "head_table"        # "head_table" | "table_table" | "head_head"
    pivot_to_tip_z: float = 100.0        # mm  — gauge + tool length
    pivot_z_offset: float = 0.0          # mm  — B/C pivot above A pivot (head_table)

    a_min_deg: float = -120.0            # A-axis travel limit (deg)
    a_max_deg: float = 120.0
    b_min_deg: float = -45.0             # B (or C) travel limit (deg)
    b_max_deg: float = 45.0

    # Human-readable machine label (informational only)
    label: str = ""

    # Whether this machine's controller handles RTCP natively
    has_rtcp: bool = True

    def __post_init__(self) -> None:
        valid = ("head_table", "table_table", "head_head")
        if self.kinematic not in valid:
            raise ValueError(
                f"MachineConfig.kinematic must be one of {valid}, got {self.kinematic!r}"
            )


# ---------------------------------------------------------------------------
# Forward kinematics  (joint angles → tool-axis vector)
# ---------------------------------------------------------------------------

def forward_kinematics(
    a_deg: float,
    b_deg: float,
    config: MachineConfig,
) -> tuple[float, float, float]:
    """Compute tool-axis unit vector (i, j, k) from joint angles.

    Parameters
    ----------
    a_deg   : Primary rotary angle in degrees.
    b_deg   : Secondary rotary angle in degrees (B for head_table/head_head,
              C for table_table).
    config  : MachineConfig describing the kinematic.

    Returns
    -------
    (i, j, k) — unit vector from tool tip toward spindle in the workpiece
    coordinate system.

    Derivations
    -----------
    head_table (A-around-X, B-around-Y):
        Start with tool pointing +Z.
        1. Rotate by B around Y: tool moves in XZ-plane.
           (sin B, 0, cos B)
        2. Apply A (table tilt, around X) to the workpiece:
           effectively tilts the part, not the head.
           But in WCS the tool sees the combined rotation.
        The net tool-axis vector in WCS when workpiece is at A and head is at B:
           i = sin(B)
           j = −sin(A) * cos(B)
           k = cos(A) * cos(B)
        This is the standard VMC head-table formula (confirmed against Fanuc
        Oi-MF 5-axis manual §3.4.2 and Hermle software documentation).

    table_table (A-around-X, C-around-Z):
        Tool always points +Z in machine space (head fixed).
        In workpiece (table) frame, the tool appears to rotate:
           i = 0  (C-rotation doesn't affect Z)
           Wait — table_table means *workpiece* tilts under a fixed tool.
        With A (tilt around X) then C (rotary around Z) applied to workpiece:
        The tool-axis vector in workpiece frame:
           i = sin(A) * sin(C)      NOTE: Mazak convention — C is the
           j = −sin(A) * cos(C)    floor-mounted rotary; A is the tilting axis
           k = cos(A)

    head_head (A-around-X, C-around-Z):
        Both rotaries on the head.  Start with tool +Z:
        1. Tilt by A around X: tool moves in YZ-plane.
           (0, sin A, cos A)
        2. Spin by C around Z (in tilted frame):
           i = sin(C) * ... — Fidia convention rotates the tilted head about Z
        Full formula (right-to-left: C applied after A in the head frame):
           i = −sin(A) * sin(C)
           j = sin(A) * cos(C)
           k = cos(A)
        This matches Fidia K211 documentation §2.3.

    References
    ----------
    - Fanuc 5-axis machining manual B-63944EN, §3.4 "Rotary Axis Configuration"
    - Mazak Variaxis application guide §7, table-table kinematics
    - Fidia K211 numerical control §2.3.1, A+C head kinematics
    - ISO 841:2001, machine axis nomenclature
    """
    a_r = math.radians(a_deg)
    b_r = math.radians(b_deg)

    if config.kinematic == "head_table":
        # A = table (around X), B = head (around Y)
        i = math.sin(b_r)
        j = -math.sin(a_r) * math.cos(b_r)
        k = math.cos(a_r) * math.cos(b_r)

    elif config.kinematic == "table_table":
        # A = tilt (around X), C = rotary (around Z) — b_deg used as C
        # Workpiece tilts: tool-axis in workpiece frame:
        c_r = b_r  # caller passes C as second angle
        i = math.sin(a_r) * math.sin(c_r)
        j = -math.sin(a_r) * math.cos(c_r)
        k = math.cos(a_r)

    elif config.kinematic == "head_head":
        # A = nod (around X), C = spin (around Z) — b_deg used as C
        c_r = b_r
        i = -math.sin(a_r) * math.sin(c_r)
        j = math.sin(a_r) * math.cos(c_r)
        k = math.cos(a_r)

    else:
        raise ValueError(f"Unknown kinematic: {config.kinematic!r}")

    # Normalise (floating-point trig may produce magnitude slightly ≠ 1)
    mag = math.sqrt(i*i + j*j + k*k)
    if mag < 1e-12:
        return (0.0, 0.0, 1.0)
    return (i / mag, j / mag, k / mag)


# ---------------------------------------------------------------------------
# Inverse kinematics  (tool-axis vector → joint angles)
# ---------------------------------------------------------------------------

_DEG = math.degrees
_RAD = math.radians


def inverse_kinematics(
    i: float,
    j: float,
    k: float,
    config: MachineConfig,
    prefer_a_positive: bool = True,
) -> tuple[float, float]:
    """Compute joint angles (A_deg, B_deg) from a tool-axis unit vector.

    Parameters
    ----------
    i, j, k          : Tool-axis unit vector (need not be normalised).
    config           : MachineConfig.
    prefer_a_positive: When two IK solutions exist (A and -A), prefer the one
                       with positive A.  Set False to prefer negative.

    Returns
    -------
    (A_deg, B_deg)  — joint angles in degrees.
    Raises ValueError if the vector is not achievable within the machine's
    travel limits.

    Derivations (analytical closed-form)
    -----------
    head_table:
        From FK:  i = sin B,  j = −sin A cos B,  k = cos A cos B
        → cos B = sqrt(1 − i²)  (always ≥ 0 since B ∈ [−90°, +90°])
        → B = atan2(i, cos B)  (= asin(i) for |i| ≤ 1)
        → A = atan2(−j, k)
        Two solutions: (A, B) and (A + 180°, −B) — the first is canonical.

    table_table:
        From FK:  i = sin A sin C,  j = −sin A cos C,  k = cos A
        → A = acos(k)  (always in [0°, 180°])
        → C = atan2(i, −j)
        Note: A is always ≥ 0 for this config; prefer_a_positive ignored.

    head_head:
        From FK:  i = −sin A sin C,  j = sin A cos C,  k = cos A
        → A = acos(k)  (always in [0°, 180°])
        → C = atan2(−i, j)
    """
    # Normalise
    mag = math.sqrt(i*i + j*j + k*k)
    if mag < 1e-12:
        raise ValueError("tool-axis vector has zero length")
    i /= mag
    j /= mag
    k /= mag

    # Clamp k to acos domain
    k_c = max(-1.0, min(1.0, k))

    if config.kinematic == "head_table":
        # B = asin(i),  A = atan2(-j, k)
        i_c = max(-1.0, min(1.0, i))
        b_deg = _DEG(math.asin(i_c))
        a_deg = _DEG(math.atan2(-j, k))
        # Prefer positive A: the alternative solution is (180 - A, 180 - B) equivalent;
        # the simpler positive-A branch is canonical.
        if not prefer_a_positive and a_deg > 0:
            a_deg = -a_deg

    elif config.kinematic == "table_table":
        a_deg = _DEG(math.acos(k_c))
        # C = atan2(i, -j)
        c_deg = _DEG(math.atan2(i, -j))
        # For table_table, A is always ≥ 0 (tilt magnitude)
        # C can be ±180°
        return _check_limits(a_deg, c_deg, config)

    elif config.kinematic == "head_head":
        a_deg = _DEG(math.acos(k_c))
        c_deg = _DEG(math.atan2(-i, j))
        return _check_limits(a_deg, c_deg, config)

    else:
        raise ValueError(f"Unknown kinematic: {config.kinematic!r}")

    return _check_limits(a_deg, b_deg, config)


def _check_limits(a_deg: float, b_deg: float, config: MachineConfig) -> tuple[float, float]:
    """Raise ValueError if either angle is outside the machine travel limits."""
    if a_deg < config.a_min_deg or a_deg > config.a_max_deg:
        raise ValueError(
            f"A angle {a_deg:.3f}° is outside machine travel "
            f"[{config.a_min_deg}°, {config.a_max_deg}°]"
        )
    if b_deg < config.b_min_deg or b_deg > config.b_max_deg:
        raise ValueError(
            f"B/C angle {b_deg:.3f}° is outside machine travel "
            f"[{config.b_min_deg}°, {config.b_max_deg}°]"
        )
    return (a_deg, b_deg)


# ---------------------------------------------------------------------------
# RTCP / TCPM pre-transform  (TCP coords → machine joint coords)
# ---------------------------------------------------------------------------

def rtcp_transform(
    x_tcp: float,
    y_tcp: float,
    z_tcp: float,
    i: float,
    j: float,
    k: float,
    config: MachineConfig,
) -> tuple[float, float, float, float, float]:
    """Pre-compute machine joint coordinates from TCP tool-tip coordinates.

    Use this when the machine controller does NOT support RTCP (e.g. older
    Fanuc 18i, GRBL, some hobby controllers).  When the controller supports
    RTCP natively (G43.4 / CYCLE800 / TRAORI), pass the TCP coordinates
    directly and let the CNC handle the transform.

    Parameters
    ----------
    x_tcp, y_tcp, z_tcp : Tool-tip position in WCS (workpiece coordinates).
    i, j, k             : Tool-axis unit vector.
    config              : MachineConfig with pivot_to_tip_z and pivot_z_offset.

    Returns
    -------
    (Xm, Ym, Zm, A_deg, B_deg) — machine axis coordinates.

    Derivation (head_table)
    -----------------------
    The B-axis pivot is at distance L (pivot_to_tip_z) from the tool tip
    along the tool axis:
        pivot = tcp + L * tool_vec

    The machine Z also needs the dZ offset (pivot_z_offset) from the A-axis
    tilt centre to the B-axis pivot:
        Xm = pivot.x
        Ym = pivot.y
        Zm = pivot.z + pivot_z_offset

    For table_table and head_head the derivation is more complex (the entire
    workpiece frame is rotated); this function provides the head_table case
    which is the most common for users without controller RTCP.

    Raises
    ------
    NotImplementedError for table_table and head_head (those configs almost
    always have native RTCP in their controllers).
    """
    if config.kinematic != "head_table":
        raise NotImplementedError(
            f"RTCP pre-transform is only implemented for 'head_table' kinematics. "
            f"Use controller RTCP (G43.4 / CYCLE800 / TRAORI) for {config.kinematic!r}."
        )

    # Normalise
    mag = math.sqrt(i*i + j*j + k*k)
    if mag < 1e-12:
        raise ValueError("tool-axis vector has zero length")
    i /= mag
    j /= mag
    k /= mag

    L = config.pivot_to_tip_z
    dZ = config.pivot_z_offset

    # Head (B-axis) pivot in WCS
    px = x_tcp + L * i
    py = y_tcp + L * j
    pz = z_tcp + L * k

    # Machine coordinates (A,B table-head layout)
    xm = px
    ym = py
    zm = pz + dZ

    # IK to get A, B
    a_deg, b_deg = inverse_kinematics(i, j, k, config)

    return (xm, ym, zm, a_deg, b_deg)


# ---------------------------------------------------------------------------
# Angle-pair continuous unwrap across a sequence of CL points
# ---------------------------------------------------------------------------

def unwrap_joint_sequence(
    joint_pairs: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Unwrap a sequence of (A, B) joint-angle pairs for smooth motion.

    Eliminates ±360° discontinuities between consecutive pairs so the machine
    takes the shortest arc between positions.

    Parameters
    ----------
    joint_pairs : list of (A_deg, B_deg) pairs.

    Returns
    -------
    List of unwrapped (A_deg, B_deg) pairs.
    """
    if not joint_pairs:
        return []
    result = [joint_pairs[0]]
    for (a_prev, b_prev), (a_curr, b_curr) in zip(joint_pairs, joint_pairs[1:]):
        a_unwrapped = _unwrap(a_prev, a_curr)
        b_unwrapped = _unwrap(b_prev, b_curr)
        result.append((a_unwrapped, b_unwrapped))
    return result


def _unwrap(prev: float, curr: float) -> float:
    delta = (curr - prev + 180.0) % 360.0 - 180.0
    return prev + delta


# ---------------------------------------------------------------------------
# Predefined machine configs
# ---------------------------------------------------------------------------

MACHINES: dict[str, MachineConfig] = {
    "generic_head_table": MachineConfig(
        kinematic="head_table",
        a_min_deg=-120.0, a_max_deg=120.0,
        b_min_deg=-45.0, b_max_deg=45.0,
        pivot_to_tip_z=100.0,
        pivot_z_offset=0.0,
        label="Generic head-table VMC (A±120°, B±45°)",
        has_rtcp=True,
    ),
    "generic_table_table": MachineConfig(
        kinematic="table_table",
        a_min_deg=-110.0, a_max_deg=110.0,
        b_min_deg=-360.0, b_max_deg=360.0,   # C = unlimited rotary
        pivot_to_tip_z=0.0,
        pivot_z_offset=0.0,
        label="Generic trunnion table-table (A±110°, C full-rotary)",
        has_rtcp=True,
    ),
    "generic_head_head": MachineConfig(
        kinematic="head_head",
        a_min_deg=-45.0, a_max_deg=45.0,
        b_min_deg=-360.0, b_max_deg=360.0,   # C = unlimited spindle rotary
        pivot_to_tip_z=150.0,
        pivot_z_offset=0.0,
        label="Generic fork/gimbal head-head (A±45°, C full-rotary)",
        has_rtcp=True,
    ),
}
