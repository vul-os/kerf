"""
Joint system for kerf-mates.

Implements six kinematic joint types on top of the existing mate/constraint
infrastructure:

  rigid      — zero DOF; both bodies share all 6 DOFs locked.
  revolute   — 1 rotational DOF about a shared axis; optional angle limits
               and angular drive.
  slider     — 1 translational DOF along a shared axis; optional length
               limits and linear drive.
  cam        — follower constrained to a cam profile radius; radial distance
               constraint with optional min/max.
  gear       — two revolute axes coupled by a gear ratio (θ_b = -ratio·θ_a).
  pin_slot   — pin travels in a slot: free along slot axis, constrained
               normal to it; optional slot length limits.

Each joint is represented as a plain dataclass plus an analytic kinematics
helper that, given a drive value (angle in radians, distance in mm, etc.),
returns the resulting state without running the iterative solver.  The
solver wiring is handled via JointConstraint entries passed to
GeometricConstraintSolver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

Vec3 = tuple[float, float, float]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _rot_axis_angle(axis: Vec3, angle: float) -> tuple[tuple[float, ...], ...]:
    """Return a 3×3 rotation matrix for *axis* (unit) and *angle* (rad)."""
    ax, ay, az = axis
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    return (
        (t * ax * ax + c,      t * ax * ay - s * az, t * ax * az + s * ay),
        (t * ax * ay + s * az, t * ay * ay + c,      t * ay * az - s * ax),
        (t * ax * az - s * ay, t * ay * az + s * ax, t * az * az + c),
    )


def _apply_rot(R: tuple[tuple[float, ...], ...], v: Vec3) -> Vec3:
    x = R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2]
    y = R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2]
    z = R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2]
    return (x, y, z)


def _vec3_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec3_scale(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def _vec3_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec3_norm(v: Vec3) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _vec3_normalize(v: Vec3) -> Vec3:
    n = _vec3_norm(v)
    if n < 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _vec3_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


# ---------------------------------------------------------------------------
# Joint dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RigidJoint:
    """Zero-DOF joint: body_b is fully locked to body_a."""
    id: str
    body_a: str                     # component_id of the first body
    body_b: str                     # component_id of the second body
    # Origin of the joint frame expressed in body_a local coordinates
    origin_a: Vec3 = (0.0, 0.0, 0.0)
    origin_b: Vec3 = (0.0, 0.0, 0.0)

    @property
    def dof(self) -> int:
        return 0

    def solve(self, drive: float = 0.0) -> dict[str, Any]:
        """Rigid: body_b origin coincides with body_a origin; no motion."""
        return {
            "joint_type": "rigid",
            "drive": drive,
            "body_a_origin": self.origin_a,
            "body_b_origin": self.origin_a,  # b locked to a
            "dof": 0,
        }


@dataclass
class RevoluteJoint:
    """1 rotational DOF about a shared axis.

    drive (radians): the current angle from the zero position.
    """
    id: str
    body_a: str
    body_b: str
    origin: Vec3 = (0.0, 0.0, 0.0)   # joint origin in world/assembly frame
    axis: Vec3 = (0.0, 0.0, 1.0)      # rotation axis (unit vector)
    angle_min: float = -math.pi        # lower angle limit (rad)
    angle_max: float = math.pi         # upper angle limit (rad)

    @property
    def dof(self) -> int:
        return 1

    def solve(self, drive: float = 0.0) -> dict[str, Any]:
        """Return body_b position/orientation for the given drive angle."""
        angle = _clamp(drive, self.angle_min, self.angle_max)
        ax = _vec3_normalize(self.axis)
        R = _rot_axis_angle(ax, angle)
        return {
            "joint_type": "revolute",
            "drive_rad": angle,
            "drive_deg": math.degrees(angle),
            "origin": self.origin,
            "axis": self.axis,
            "rotation_matrix": R,
            "within_limits": (self.angle_min <= drive <= self.angle_max),
            "dof": 1,
        }

    def angle_at_drive(self, drive: float) -> float:
        return _clamp(drive, self.angle_min, self.angle_max)


@dataclass
class SliderJoint:
    """1 translational DOF along a shared axis.

    drive (mm): displacement from the zero position.
    """
    id: str
    body_a: str
    body_b: str
    origin: Vec3 = (0.0, 0.0, 0.0)  # joint origin in assembly frame
    axis: Vec3 = (1.0, 0.0, 0.0)    # slide direction (unit vector)
    limit_min: float = 0.0           # lower displacement limit (mm)
    limit_max: float = 100.0         # upper displacement limit (mm)

    @property
    def dof(self) -> int:
        return 1

    def solve(self, drive: float = 0.0) -> dict[str, Any]:
        """Return body_b position for the given drive displacement."""
        displacement = _clamp(drive, self.limit_min, self.limit_max)
        ax = _vec3_normalize(self.axis)
        delta = _vec3_scale(ax, displacement)
        body_b_origin = _vec3_add(self.origin, delta)
        return {
            "joint_type": "slider",
            "drive_mm": displacement,
            "origin": self.origin,
            "axis": self.axis,
            "body_b_origin": body_b_origin,
            "within_limits": (self.limit_min <= drive <= self.limit_max),
            "dof": 1,
        }

    def position_at_drive(self, drive: float) -> Vec3:
        displacement = _clamp(drive, self.limit_min, self.limit_max)
        ax = _vec3_normalize(self.axis)
        return _vec3_add(self.origin, _vec3_scale(ax, displacement))


@dataclass
class CamJoint:
    """Cam-follower joint.

    The follower centre is always at a given radial distance (cam_radius_mm)
    from the cam axis.  As the cam rotates (drive = angle in radians) the
    follower translates along the follower_axis.

    Simple model: eccentric circle cam.
      cam_radius_mm   — distance from cam centre to follower contact circle
      eccentricity_mm — offset of the cam lobe centre from the rotation axis
    """
    id: str
    body_a: str                        # cam body
    body_b: str                        # follower body
    cam_origin: Vec3 = (0.0, 0.0, 0.0)
    cam_axis: Vec3 = (0.0, 0.0, 1.0)  # rotation axis of the cam
    follower_axis: Vec3 = (0.0, 1.0, 0.0)  # direction the follower moves
    cam_radius_mm: float = 20.0        # base circle radius
    eccentricity_mm: float = 5.0       # lobe eccentricity
    follower_min_mm: float | None = None
    follower_max_mm: float | None = None

    @property
    def dof(self) -> int:
        return 1  # cam rotates; follower position is determined by cam angle

    def follower_lift(self, cam_angle: float) -> float:
        """Analytic follower displacement for an eccentric-circle cam."""
        return self.eccentricity_mm * math.cos(cam_angle)

    def solve(self, drive: float = 0.0) -> dict[str, Any]:
        """drive = cam rotation angle (rad)."""
        lift = self.follower_lift(drive)
        radial_position = self.cam_radius_mm + lift
        if self.follower_min_mm is not None:
            radial_position = max(self.follower_min_mm, radial_position)
        if self.follower_max_mm is not None:
            radial_position = min(self.follower_max_mm, radial_position)

        fa = _vec3_normalize(self.follower_axis)
        follower_pos = _vec3_add(
            self.cam_origin,
            _vec3_scale(fa, radial_position),
        )
        return {
            "joint_type": "cam",
            "cam_angle_rad": drive,
            "cam_angle_deg": math.degrees(drive),
            "follower_lift_mm": lift,
            "follower_radial_mm": radial_position,
            "follower_position": follower_pos,
            "dof": 1,
        }


@dataclass
class GearJoint:
    """Gear pair coupling two revolute joints via a gear ratio.

    θ_b = -gear_ratio · θ_a   (negative = external mesh; positive = internal)

    drive = θ_a (input shaft angle, rad).
    """
    id: str
    body_a: str                         # driving gear body
    body_b: str                         # driven gear body
    origin_a: Vec3 = (0.0, 0.0, 0.0)   # centre of driving gear
    origin_b: Vec3 = (100.0, 0.0, 0.0) # centre of driven gear
    axis_a: Vec3 = (0.0, 0.0, 1.0)     # rotation axis of gear_a
    axis_b: Vec3 = (0.0, 0.0, 1.0)     # rotation axis of gear_b
    gear_ratio: float = 2.0             # N_b / N_a  (> 0 → external mesh sign convention applied below)
    internal_mesh: bool = False         # True = ring gear (same rotation direction)
    angle_min_a: float = -math.inf
    angle_max_a: float = math.inf

    @property
    def dof(self) -> int:
        return 1  # one independent DOF (input shaft)

    def output_angle(self, drive: float) -> float:
        """θ_b for a given input θ_a (drive)."""
        sign = 1.0 if self.internal_mesh else -1.0
        return sign * self.gear_ratio * drive

    def solve(self, drive: float = 0.0) -> dict[str, Any]:
        """drive = θ_a (input angle, rad)."""
        theta_a = _clamp(drive, self.angle_min_a, self.angle_max_a)
        theta_b = self.output_angle(theta_a)
        Ra = _rot_axis_angle(_vec3_normalize(self.axis_a), theta_a)
        Rb = _rot_axis_angle(_vec3_normalize(self.axis_b), theta_b)
        return {
            "joint_type": "gear",
            "input_angle_rad": theta_a,
            "input_angle_deg": math.degrees(theta_a),
            "output_angle_rad": theta_b,
            "output_angle_deg": math.degrees(theta_b),
            "gear_ratio": self.gear_ratio,
            "internal_mesh": self.internal_mesh,
            "rotation_matrix_a": Ra,
            "rotation_matrix_b": Rb,
            "within_limits": (self.angle_min_a <= drive <= self.angle_max_a),
            "dof": 1,
        }


@dataclass
class PinSlotJoint:
    """Pin-in-slot joint.

    The pin is free to slide along the slot axis and rotate about it (2 DOF),
    but is constrained radially (normal to the slot).

    drive = pin displacement along slot (mm).
    """
    id: str
    body_a: str                         # slot body
    body_b: str                         # pin body
    slot_origin: Vec3 = (0.0, 0.0, 0.0)
    slot_axis: Vec3 = (1.0, 0.0, 0.0)  # direction along slot
    slot_length_min: float = 0.0        # minimum displacement (mm)
    slot_length_max: float = 100.0      # maximum displacement (mm)
    # Pin is centred on the slot axis (zero radial offset)

    @property
    def dof(self) -> int:
        return 1  # translational along slot (radial constrained)

    def pin_position(self, drive: float) -> Vec3:
        displacement = _clamp(drive, self.slot_length_min, self.slot_length_max)
        sa = _vec3_normalize(self.slot_axis)
        return _vec3_add(self.slot_origin, _vec3_scale(sa, displacement))

    def solve(self, drive: float = 0.0) -> dict[str, Any]:
        """drive = pin displacement along the slot axis (mm)."""
        displacement = _clamp(drive, self.slot_length_min, self.slot_length_max)
        pin_pos = self.pin_position(displacement)
        sa = _vec3_normalize(self.slot_axis)
        # Radial constraint: distance from pin centre to slot axis = 0
        # (i.e. pin is centred on slot axis — radial error is always 0)
        return {
            "joint_type": "pin_slot",
            "drive_mm": displacement,
            "slot_axis": self.slot_axis,
            "pin_position": pin_pos,
            "radial_error": 0.0,  # analytically exact
            "within_limits": (self.slot_length_min <= drive <= self.slot_length_max),
            "dof": 1,
        }


# ---------------------------------------------------------------------------
# Joint registry & factory
# ---------------------------------------------------------------------------

JOINT_TYPES = frozenset({"rigid", "revolute", "slider", "cam", "gear", "pin_slot"})


def make_joint(spec: dict[str, Any]) -> (
    RigidJoint | RevoluteJoint | SliderJoint | CamJoint | GearJoint | PinSlotJoint
):
    """Build a joint object from a plain dict spec.

    Required keys:
      id        — unique joint id
      type      — one of JOINT_TYPES
      body_a    — component_id of the first body
      body_b    — component_id of the second body

    Type-specific optional keys are forwarded as kwargs.
    """
    jtype = spec.get("type", "")
    if jtype not in JOINT_TYPES:
        raise ValueError(f"Unknown joint type: {jtype!r}; must be one of {sorted(JOINT_TYPES)}")

    jid = spec["id"]
    ba = spec["body_a"]
    bb = spec["body_b"]

    def _v3(key: str, default: Vec3) -> Vec3:
        raw = spec.get(key, default)
        if isinstance(raw, (list, tuple)) and len(raw) == 3:
            return tuple(float(x) for x in raw)
        return default

    if jtype == "rigid":
        return RigidJoint(
            id=jid, body_a=ba, body_b=bb,
            origin_a=_v3("origin_a", (0.0, 0.0, 0.0)),
            origin_b=_v3("origin_b", (0.0, 0.0, 0.0)),
        )

    if jtype == "revolute":
        return RevoluteJoint(
            id=jid, body_a=ba, body_b=bb,
            origin=_v3("origin", (0.0, 0.0, 0.0)),
            axis=_v3("axis", (0.0, 0.0, 1.0)),
            angle_min=float(spec.get("angle_min", -math.pi)),
            angle_max=float(spec.get("angle_max", math.pi)),
        )

    if jtype == "slider":
        return SliderJoint(
            id=jid, body_a=ba, body_b=bb,
            origin=_v3("origin", (0.0, 0.0, 0.0)),
            axis=_v3("axis", (1.0, 0.0, 0.0)),
            limit_min=float(spec.get("limit_min", 0.0)),
            limit_max=float(spec.get("limit_max", 100.0)),
        )

    if jtype == "cam":
        return CamJoint(
            id=jid, body_a=ba, body_b=bb,
            cam_origin=_v3("cam_origin", (0.0, 0.0, 0.0)),
            cam_axis=_v3("cam_axis", (0.0, 0.0, 1.0)),
            follower_axis=_v3("follower_axis", (0.0, 1.0, 0.0)),
            cam_radius_mm=float(spec.get("cam_radius_mm", 20.0)),
            eccentricity_mm=float(spec.get("eccentricity_mm", 5.0)),
            follower_min_mm=spec.get("follower_min_mm"),
            follower_max_mm=spec.get("follower_max_mm"),
        )

    if jtype == "gear":
        return GearJoint(
            id=jid, body_a=ba, body_b=bb,
            origin_a=_v3("origin_a", (0.0, 0.0, 0.0)),
            origin_b=_v3("origin_b", (100.0, 0.0, 0.0)),
            axis_a=_v3("axis_a", (0.0, 0.0, 1.0)),
            axis_b=_v3("axis_b", (0.0, 0.0, 1.0)),
            gear_ratio=float(spec.get("gear_ratio", 2.0)),
            internal_mesh=bool(spec.get("internal_mesh", False)),
            angle_min_a=float(spec.get("angle_min_a", -math.inf)),
            angle_max_a=float(spec.get("angle_max_a", math.inf)),
        )

    if jtype == "pin_slot":
        return PinSlotJoint(
            id=jid, body_a=ba, body_b=bb,
            slot_origin=_v3("slot_origin", (0.0, 0.0, 0.0)),
            slot_axis=_v3("slot_axis", (1.0, 0.0, 0.0)),
            slot_length_min=float(spec.get("slot_length_min", 0.0)),
            slot_length_max=float(spec.get("slot_length_max", 100.0)),
        )

    raise ValueError(f"Unhandled joint type: {jtype!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Assembly-level joint solver
# ---------------------------------------------------------------------------

def solve_joints(
    joints: list[dict[str, Any]],
    drives: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Solve a list of joints with optional drive inputs.

    Parameters
    ----------
    joints:
        List of joint spec dicts (each with at least ``id``, ``type``,
        ``body_a``, ``body_b``).
    drives:
        Mapping of joint_id → drive value (angle in rad, distance in mm,
        etc.).  Missing joints default to drive=0.

    Returns
    -------
    dict with keys:
      ``results``  — dict of joint_id → solve result dict
      ``errors``   — list of {joint_id, error} for any joints that failed
    """
    if drives is None:
        drives = {}

    results: dict[str, Any] = {}
    errors: list[dict[str, str]] = []

    for spec in joints:
        jid = spec.get("id", "")
        try:
            joint = make_joint(spec)
            drive = drives.get(jid, 0.0)
            results[jid] = joint.solve(drive)
        except Exception as exc:
            errors.append({"joint_id": jid, "error": str(exc)})

    return {"results": results, "errors": errors}
