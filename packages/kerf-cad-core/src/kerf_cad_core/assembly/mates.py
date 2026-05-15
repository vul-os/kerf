"""
kerf_cad_core.assembly.mates — Mate types and deterministic DOF solver.

Mate types supported
--------------------
coincident    — face-to-face contact; aligns two planes so they share the same
                surface (normal antiparallel, a point on each face coplanar).
                Removes 3 DOF (1 translation + 2 rotations).
concentric    — axis-to-axis alignment; the two cylindrical axes become
                colinear.  Removes 4 DOF (2 translations + 2 rotations).
parallel      — two axes / planes become parallel; normals align.
                Removes 2 DOF (2 rotations).
perpendicular — two axes / planes become perpendicular.
                Removes 1 DOF (1 rotation).
distance      — offset between two faces/axes along a direction.
                Removes 1 DOF (1 translation) for translational offset,
                or 0 if used as an angular limiter.
angle         — angle between two axes / planes.
                Removes 1 DOF (1 rotation).
tangent       — surface tangency between a cylinder and a plane.
                Removes 1 DOF (1 translation).
lock          — fully constrains all remaining DOF (sets to 0).

DOF model
---------
A free rigid body in 3-D space has 6 DOF (3 translation + 3 rotation).
Each mate removes some DOF; the solver tracks running ``dof_remaining``.
One component in the assembly is always fixed (the first component added,
or any component with a lock mate).  The fixed component has 0 DOF.

Status:
  fully_constrained  — dof_remaining == 0 for all components
  under_constrained  — dof_remaining > 0 for some component
  over_constrained   — a mate attempts to remove a DOF already eliminated

Solver strategy
---------------
This is a closed-form constraint propagation solver, not a full non-linear
numeric solver (no scipy/numpy needed).  For the canonical mate set the
transforms can be computed analytically:

  1. The first component placed is the "ground" (identity transform, 0 DOF).
  2. Each mate relates exactly two components (instance_id_a, instance_id_b).
  3. For each mate the solver computes the transform delta that satisfies the
     geometric constraint and applies it to the *free* component.
  4. DOF counting is maintained separately from the transform; the transforms
     returned are the analytically resolved placements.

Geometric inputs per mate
-------------------------
Each mate carries optional geometry hints used by the solver:
  ``point_a``  / ``point_b``  — 3-D point on the entity (mm)
  ``normal_a`` / ``normal_b`` — unit normal / axis direction (dimensionless)
  ``offset``   — scalar distance (mm) for distance mates
  ``angle_deg`` — target angle (degrees) for angle mates

Determinism
-----------
For equal inputs the solver always produces the same transforms.  No random
seed is required.  The solver applies mates in the order they were added.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from kerf_cad_core.assembly.model import (
    Assembly,
    Component,
    _identity,
    _mat_mul,
    _transform_point,
    _transform_vector,
)


# ---------------------------------------------------------------------------
# MateType enum
# ---------------------------------------------------------------------------

class MateType(str, Enum):
    COINCIDENT    = "coincident"
    CONCENTRIC    = "concentric"
    PARALLEL      = "parallel"
    PERPENDICULAR = "perpendicular"
    DISTANCE      = "distance"
    ANGLE         = "angle"
    TANGENT       = "tangent"
    LOCK          = "lock"


# DOF removed by each mate type
# (conservative canonical values; over-constrained detection uses these)
_MATE_DOF: dict[MateType, int] = {
    MateType.COINCIDENT:    3,   # 1 translation + 2 rotations
    MateType.CONCENTRIC:    4,   # 2 translations + 2 rotations
    MateType.PARALLEL:      2,   # 2 rotations
    MateType.PERPENDICULAR: 1,   # 1 rotation
    MateType.DISTANCE:      1,   # 1 translation
    MateType.ANGLE:         1,   # 1 rotation
    MateType.TANGENT:       1,   # 1 translation
    MateType.LOCK:          6,   # all remaining DOF
}


# ---------------------------------------------------------------------------
# Mate data class
# ---------------------------------------------------------------------------

class Mate:
    """
    A geometric constraint between two component instances.

    Parameters
    ----------
    mate_type : MateType | str
    instance_id_a : str
        Instance id of the first component.
    instance_id_b : str
        Instance id of the second component.
    point_a : tuple[float, float, float] | None
        A point on the feature of component A (in A's local coordinate frame).
    normal_a : tuple[float, float, float] | None
        The outward normal / axis direction of the feature on A (local frame).
    point_b : tuple[float, float, float] | None
        A point on the feature of component B (in B's local coordinate frame).
    normal_b : tuple[float, float, float] | None
        The outward normal / axis direction of the feature on B (local frame).
    offset : float
        Signed distance offset for distance mates (mm).  0 = flush.
    angle_deg : float
        Target angle between the two entities (degrees) for angle mates.
    mate_id : str | None
        Optional explicit identifier; auto-generated if omitted.
    """

    __slots__ = (
        "mate_id",
        "mate_type",
        "instance_id_a",
        "instance_id_b",
        "point_a",
        "normal_a",
        "point_b",
        "normal_b",
        "offset",
        "angle_deg",
    )

    def __init__(
        self,
        mate_type: "MateType | str",
        instance_id_a: str,
        instance_id_b: str,
        point_a: "tuple[float, float, float] | None" = None,
        normal_a: "tuple[float, float, float] | None" = None,
        point_b: "tuple[float, float, float] | None" = None,
        normal_b: "tuple[float, float, float] | None" = None,
        offset: float = 0.0,
        angle_deg: float = 0.0,
        mate_id: "str | None" = None,
    ) -> None:
        if isinstance(mate_type, str):
            mate_type = MateType(mate_type.lower())
        self.mate_type: MateType = mate_type
        self.instance_id_a = str(instance_id_a)
        self.instance_id_b = str(instance_id_b)
        self.point_a: "tuple[float, float, float] | None" = _coerce_vec(point_a)
        self.normal_a: "tuple[float, float, float] | None" = _coerce_vec(normal_a)
        self.point_b: "tuple[float, float, float] | None" = _coerce_vec(point_b)
        self.normal_b: "tuple[float, float, float] | None" = _coerce_vec(normal_b)
        self.offset = float(offset)
        self.angle_deg = float(angle_deg)
        import uuid as _uuid
        self.mate_id: str = mate_id or str(_uuid.uuid4())

    def to_dict(self) -> dict:
        return {
            "mate_id": self.mate_id,
            "mate_type": self.mate_type.value,
            "instance_id_a": self.instance_id_a,
            "instance_id_b": self.instance_id_b,
            "point_a": list(self.point_a) if self.point_a else None,
            "normal_a": list(self.normal_a) if self.normal_a else None,
            "point_b": list(self.point_b) if self.point_b else None,
            "normal_b": list(self.normal_b) if self.normal_b else None,
            "offset": self.offset,
            "angle_deg": self.angle_deg,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Mate":
        return cls(
            mate_type=d["mate_type"],
            instance_id_a=d["instance_id_a"],
            instance_id_b=d["instance_id_b"],
            point_a=d.get("point_a"),
            normal_a=d.get("normal_a"),
            point_b=d.get("point_b"),
            normal_b=d.get("normal_b"),
            offset=d.get("offset", 0.0),
            angle_deg=d.get("angle_deg", 0.0),
            mate_id=d.get("mate_id"),
        )

    def __repr__(self) -> str:
        return (
            f"Mate({self.mate_type.value!r}, "
            f"a={self.instance_id_a!r}, b={self.instance_id_b!r})"
        )


# ---------------------------------------------------------------------------
# Private geometry helpers
# ---------------------------------------------------------------------------

def _coerce_vec(
    v: Any,
) -> "tuple[float, float, float] | None":
    """Parse a 3-vector from various container types.  Returns None if v is None."""
    if v is None:
        return None
    try:
        seq = list(v)
        return (float(seq[0]), float(seq[1]), float(seq[2]))
    except (TypeError, IndexError, ValueError) as exc:
        raise ValueError(f"expected 3-vector, got {v!r}: {exc}") from exc


def _norm(v: tuple[float, float, float]) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = _norm(v)
    if n < 1e-12:
        raise ValueError(f"cannot normalise zero-length vector {v}")
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _rotation_from_axis_angle(
    axis: tuple[float, float, float], angle_rad: float
) -> list[float]:
    """
    Build a 4×4 rotation matrix (row-major) from an axis and angle using
    Rodrigues' rotation formula.
    """
    ax, ay, az = _unit(axis)
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    t = 1.0 - c
    # Row-major 4×4
    return [
        t * ax * ax + c,      t * ax * ay - s * az, t * ax * az + s * ay, 0.0,
        t * ax * ay + s * az, t * ay * ay + c,       t * ay * az - s * ax, 0.0,
        t * ax * az - s * ay, t * ay * az + s * ax,  t * az * az + c,      0.0,
        0.0,                  0.0,                   0.0,                  1.0,
    ]


def _translation_matrix(
    tx: float, ty: float, tz: float
) -> list[float]:
    """Build a 4×4 pure-translation matrix (row-major)."""
    return [
        1.0, 0.0, 0.0, tx,
        0.0, 1.0, 0.0, ty,
        0.0, 0.0, 1.0, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def _rotation_align_vectors(
    src: tuple[float, float, float],
    dst: tuple[float, float, float],
) -> list[float]:
    """
    Build a 4×4 rotation matrix that rotates unit vector ``src`` onto ``dst``.
    Uses Rodrigues' formula; handles the antiparallel case.
    """
    us = _unit(src)
    ud = _unit(dst)
    d = _dot(us, ud)

    if d > 1.0 - 1e-9:
        # Already aligned — identity
        return _identity()

    if d < -1.0 + 1e-9:
        # Antiparallel — rotate 180° around an arbitrary perpendicular axis
        perp = _find_perpendicular(us)
        return _rotation_from_axis_angle(perp, math.pi)

    axis = _cross(us, ud)
    angle = math.acos(max(-1.0, min(1.0, d)))
    return _rotation_from_axis_angle(axis, angle)


def _find_perpendicular(
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Return a unit vector perpendicular to v."""
    ax, ay, az = v
    if abs(ax) <= abs(ay) and abs(ax) <= abs(az):
        candidate = (1.0, 0.0, 0.0)
    elif abs(ay) <= abs(az):
        candidate = (0.0, 1.0, 0.0)
    else:
        candidate = (0.0, 0.0, 1.0)
    c = _cross(v, candidate)
    return _unit(c)


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve_assembly(
    assembly: Assembly,
    mates: list[Mate],
) -> dict:
    """
    Solve an assembly given a list of mates.

    Returns a dict:
    {
        "ok": bool,
        "components": [
            {
                "instance_id": str,
                "part_ref": str,
                "transform": list[float],   # 16-element row-major 4×4
                "dof_remaining": int,
            },
            ...
        ],
        "dof_remaining": int,               # total across all non-ground components
        "status": "fully_constrained" | "under_constrained" | "over_constrained",
        "errors": [str, ...],
    }

    The first component added to the assembly is the "ground" (fixed, 0 DOF).
    Its transform is respected as-is (typically identity).

    Never raises.
    """
    errors: list[str] = []
    all_comps = assembly.all_components()

    if not all_comps:
        return {
            "ok": True,
            "components": [],
            "dof_remaining": 0,
            "status": "fully_constrained",
            "errors": [],
        }

    # Build mutable state: transform + remaining DOF per instance
    transforms: dict[str, list[float]] = {}
    dof: dict[str, int] = {}
    part_refs: dict[str, str] = {}

    for i, comp in enumerate(all_comps):
        transforms[comp.instance_id] = list(comp.transform)
        dof[comp.instance_id] = 0 if i == 0 else 6   # ground = 0 DOF
        part_refs[comp.instance_id] = comp.part_ref

    # Track which DOF "slots" have been consumed per component
    # We use a simple integer decrement with over-constraint detection.
    _locked_dof: dict[str, int] = {iid: (6 - d) for iid, d in dof.items()}

    def _apply_dof_reduction(iid: str, n: int, mate_desc: str) -> bool:
        """Returns False on over-constraint."""
        available = dof.get(iid, 0)
        if n > available:
            errors.append(
                f"Over-constrained: mate '{mate_desc}' tries to remove {n} DOF "
                f"from '{iid}' but only {available} remain"
            )
            return False
        dof[iid] -= n
        return True

    # Process each mate
    for mate in mates:
        iid_a = mate.instance_id_a
        iid_b = mate.instance_id_b

        # Validate instance ids
        if iid_a not in transforms:
            errors.append(
                f"Mate '{mate.mate_id}': instance_id_a '{iid_a}' not found in assembly"
            )
            continue
        if iid_b not in transforms:
            errors.append(
                f"Mate '{mate.mate_id}': instance_id_b '{iid_b}' not found in assembly"
            )
            continue

        # Determine which component is free (non-ground)
        dof_a = dof[iid_a]
        dof_b = dof[iid_b]

        # The free component is the one with more DOF; if equal, prefer b.
        free_iid = iid_b if dof_b >= dof_a else iid_a
        fixed_iid = iid_a if free_iid == iid_b else iid_b

        T_fixed = transforms[fixed_iid]
        T_free = transforms[free_iid]
        mt = mate.mate_type
        n_dof = _MATE_DOF[mt]
        mate_desc = f"{mt.value}({iid_a},{iid_b})"

        # ── LOCK ────────────────────────────────────────────────────────────
        if mt == MateType.LOCK:
            # Set free component's transform to match fixed component.
            # Lock always claims to remove 6 DOF; if fewer remain that is
            # over-constrained (e.g. a second lock on an already-locked part).
            remaining = dof[free_iid]
            if remaining == 0:
                errors.append(
                    f"Over-constrained: mate '{mate_desc}' (lock) tries to remove "
                    f"DOF from '{free_iid}' but 0 remain"
                )
                continue
            dof[free_iid] = 0
            transforms[free_iid] = list(T_fixed)
            continue

        # ── COINCIDENT ──────────────────────────────────────────────────────
        if mt == MateType.COINCIDENT:
            # Align the free component so that:
            #   - normal_b (in world) = -normal_a (in world)   [antiparallel normals]
            #   - point_b (in world) = point_a (in world) + offset * normal_a_world
            #
            # With no geometry hints: translate point_b of free onto point_a of fixed.
            _apply_dof_reduction(free_iid, n_dof, mate_desc)
            T_free_new = _solve_coincident(
                T_fixed, T_free,
                free_is_b=(free_iid == iid_b),
                point_a=mate.point_a,
                normal_a=mate.normal_a,
                point_b=mate.point_b,
                normal_b=mate.normal_b,
                offset=mate.offset,
            )
            transforms[free_iid] = T_free_new
            continue

        # ── CONCENTRIC ──────────────────────────────────────────────────────
        if mt == MateType.CONCENTRIC:
            # Align axes: the axis of the free component (defined by point_b + normal_b)
            # becomes colinear with the axis of the fixed component (point_a + normal_a).
            _apply_dof_reduction(free_iid, n_dof, mate_desc)
            T_free_new = _solve_concentric(
                T_fixed, T_free,
                free_is_b=(free_iid == iid_b),
                point_a=mate.point_a,
                normal_a=mate.normal_a,
                point_b=mate.point_b,
                normal_b=mate.normal_b,
            )
            transforms[free_iid] = T_free_new
            continue

        # ── PARALLEL ────────────────────────────────────────────────────────
        if mt == MateType.PARALLEL:
            _apply_dof_reduction(free_iid, n_dof, mate_desc)
            T_free_new = _solve_parallel(
                T_fixed, T_free,
                free_is_b=(free_iid == iid_b),
                normal_a=mate.normal_a,
                normal_b=mate.normal_b,
            )
            transforms[free_iid] = T_free_new
            continue

        # ── PERPENDICULAR ───────────────────────────────────────────────────
        if mt == MateType.PERPENDICULAR:
            _apply_dof_reduction(free_iid, n_dof, mate_desc)
            T_free_new = _solve_perpendicular(
                T_fixed, T_free,
                free_is_b=(free_iid == iid_b),
                normal_a=mate.normal_a,
                normal_b=mate.normal_b,
            )
            transforms[free_iid] = T_free_new
            continue

        # ── DISTANCE ────────────────────────────────────────────────────────
        if mt == MateType.DISTANCE:
            _apply_dof_reduction(free_iid, n_dof, mate_desc)
            T_free_new = _solve_distance(
                T_fixed, T_free,
                free_is_b=(free_iid == iid_b),
                point_a=mate.point_a,
                normal_a=mate.normal_a,
                point_b=mate.point_b,
                offset=mate.offset,
            )
            transforms[free_iid] = T_free_new
            continue

        # ── ANGLE ───────────────────────────────────────────────────────────
        if mt == MateType.ANGLE:
            _apply_dof_reduction(free_iid, n_dof, mate_desc)
            T_free_new = _solve_angle(
                T_fixed, T_free,
                free_is_b=(free_iid == iid_b),
                normal_a=mate.normal_a,
                normal_b=mate.normal_b,
                angle_deg=mate.angle_deg,
            )
            transforms[free_iid] = T_free_new
            continue

        # ── TANGENT ─────────────────────────────────────────────────────────
        if mt == MateType.TANGENT:
            _apply_dof_reduction(free_iid, n_dof, mate_desc)
            T_free_new = _solve_tangent(
                T_fixed, T_free,
                free_is_b=(free_iid == iid_b),
                point_a=mate.point_a,
                normal_a=mate.normal_a,
                point_b=mate.point_b,
                offset=mate.offset,
            )
            transforms[free_iid] = T_free_new
            continue

        errors.append(f"Unknown mate type '{mt}'")

    # ── Build result ──────────────────────────────────────────────────────────
    total_dof = sum(dof.values())
    over = any(
        msg.startswith("Over-constrained") for msg in errors
    )

    if over:
        status = "over_constrained"
    elif total_dof == 0:
        status = "fully_constrained"
    else:
        status = "under_constrained"

    component_results = [
        {
            "instance_id": iid,
            "part_ref": part_refs[iid],
            "transform": transforms[iid],
            "dof_remaining": dof[iid],
        }
        for iid in (comp.instance_id for comp in all_comps)
    ]

    return {
        "ok": len(errors) == 0,
        "components": component_results,
        "dof_remaining": total_dof,
        "status": status,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Per-mate solvers (closed-form, pure-Python)
# ---------------------------------------------------------------------------

def _world_normal(
    T: list[float],
    local_normal: "tuple[float, float, float] | None",
    default: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> tuple[float, float, float]:
    """Transform a local normal into world space via T."""
    n = local_normal if local_normal is not None else default
    return _unit(_transform_vector(T, n))


def _world_point(
    T: list[float],
    local_point: "tuple[float, float, float] | None",
    default: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[float, float, float]:
    """Transform a local point into world space via T."""
    p = local_point if local_point is not None else default
    return _transform_point(T, p)


# ---- coincident ----

def _solve_coincident(
    T_fixed: list[float],
    T_free: list[float],
    free_is_b: bool,
    point_a: "tuple[float, float, float] | None",
    normal_a: "tuple[float, float, float] | None",
    point_b: "tuple[float, float, float] | None",
    normal_b: "tuple[float, float, float] | None",
    offset: float,
) -> list[float]:
    """
    Solve a face-face coincident mate.

    Strategy:
    1. Align the free component's face normal to be antiparallel to the fixed
       component's face normal.
    2. Translate the free component so that its face point lands on the fixed
       component's face plane (with optional offset along the fixed normal).
    """
    if free_is_b:
        # Free = B, Fixed = A
        wn_fixed = _world_normal(T_fixed, normal_a)
        wp_fixed = _world_point(T_fixed, point_a)
        wn_free_local = normal_b if normal_b is not None else (0.0, 0.0, 1.0)
    else:
        # Free = A, Fixed = B
        wn_fixed = _world_normal(T_fixed, normal_b)
        wp_fixed = _world_point(T_fixed, point_b)
        wn_free_local = normal_a if normal_a is not None else (0.0, 0.0, 1.0)

    # Target world normal for the free face = antiparallel to fixed normal
    target_wn_free = (-wn_fixed[0], -wn_fixed[1], -wn_fixed[2])

    # Current world normal of free face
    cur_wn_free = _unit(_transform_vector(T_free, wn_free_local))

    # Rotation to align free normal to target
    R = _rotation_align_vectors(cur_wn_free, target_wn_free)
    T_rotated = _mat_mul(R, T_free)  # rotate T_free about world origin

    # After rotation: compute world position of free face point
    free_pt_local = point_b if (free_is_b and point_b is not None) else (
        point_a if (not free_is_b and point_a is not None) else (0.0, 0.0, 0.0)
    )
    wp_free_after_rot = _world_point(T_rotated, free_pt_local)

    # Target position for free face point = fixed face point + offset * fixed_normal
    target_wp = (
        wp_fixed[0] + offset * wn_fixed[0],
        wp_fixed[1] + offset * wn_fixed[1],
        wp_fixed[2] + offset * wn_fixed[2],
    )

    # Translation delta
    dx = target_wp[0] - wp_free_after_rot[0]
    dy = target_wp[1] - wp_free_after_rot[1]
    dz = target_wp[2] - wp_free_after_rot[2]

    T_trans = _translation_matrix(dx, dy, dz)
    return _mat_mul(T_trans, T_rotated)


# ---- concentric ----

def _solve_concentric(
    T_fixed: list[float],
    T_free: list[float],
    free_is_b: bool,
    point_a: "tuple[float, float, float] | None",
    normal_a: "tuple[float, float, float] | None",
    point_b: "tuple[float, float, float] | None",
    normal_b: "tuple[float, float, float] | None",
) -> list[float]:
    """
    Solve a concentric (axis-axis) mate.

    Aligns the free component's axis so it is colinear with the fixed
    component's axis.

    Strategy:
    1. Align free axis direction to match fixed axis direction.
    2. Translate so that the free axis passes through the fixed axis's
       reference point (making them colinear, not merely parallel).
    """
    if free_is_b:
        wn_fixed = _world_normal(T_fixed, normal_a)
        wp_fixed = _world_point(T_fixed, point_a)
        free_n_local = normal_b if normal_b is not None else (0.0, 0.0, 1.0)
        free_p_local = point_b if point_b is not None else (0.0, 0.0, 0.0)
    else:
        wn_fixed = _world_normal(T_fixed, normal_b)
        wp_fixed = _world_point(T_fixed, point_b)
        free_n_local = normal_a if normal_a is not None else (0.0, 0.0, 1.0)
        free_p_local = point_a if point_a is not None else (0.0, 0.0, 0.0)

    # Current world axis direction of free component
    cur_wn_free = _unit(_transform_vector(T_free, free_n_local))

    # Align free axis to match fixed axis direction (parallel, same direction)
    R = _rotation_align_vectors(cur_wn_free, wn_fixed)
    T_rotated = _mat_mul(R, T_free)

    # After rotation: compute the world position of free axis reference point
    wp_free_after_rot = _world_point(T_rotated, free_p_local)

    # Project wp_free_after_rot onto the fixed axis; compute lateral offset
    # and translate to eliminate it, making axes colinear.
    #
    # Component of (wp_free - wp_fixed) along fixed axis:
    delta = (
        wp_free_after_rot[0] - wp_fixed[0],
        wp_free_after_rot[1] - wp_fixed[1],
        wp_free_after_rot[2] - wp_fixed[2],
    )
    along = _dot(delta, wn_fixed)
    lateral = (
        delta[0] - along * wn_fixed[0],
        delta[1] - along * wn_fixed[1],
        delta[2] - along * wn_fixed[2],
    )
    # Translate free component to eliminate lateral offset
    T_trans = _translation_matrix(-lateral[0], -lateral[1], -lateral[2])
    return _mat_mul(T_trans, T_rotated)


# ---- parallel ----

def _solve_parallel(
    T_fixed: list[float],
    T_free: list[float],
    free_is_b: bool,
    normal_a: "tuple[float, float, float] | None",
    normal_b: "tuple[float, float, float] | None",
) -> list[float]:
    """
    Rotate the free component so its normal becomes parallel to the fixed normal.
    """
    if free_is_b:
        wn_fixed = _world_normal(T_fixed, normal_a)
        free_n_local = normal_b if normal_b is not None else (0.0, 0.0, 1.0)
    else:
        wn_fixed = _world_normal(T_fixed, normal_b)
        free_n_local = normal_a if normal_a is not None else (0.0, 0.0, 1.0)

    cur_wn_free = _unit(_transform_vector(T_free, free_n_local))
    R = _rotation_align_vectors(cur_wn_free, wn_fixed)
    return _mat_mul(R, T_free)


# ---- perpendicular ----

def _solve_perpendicular(
    T_fixed: list[float],
    T_free: list[float],
    free_is_b: bool,
    normal_a: "tuple[float, float, float] | None",
    normal_b: "tuple[float, float, float] | None",
) -> list[float]:
    """
    Rotate the free component so its normal becomes perpendicular to the fixed normal.

    Strategy: find the cross product of the two normals in the plane they define,
    then rotate the free normal to point along that cross product.
    """
    if free_is_b:
        wn_fixed = _world_normal(T_fixed, normal_a)
        free_n_local = normal_b if normal_b is not None else (0.0, 1.0, 0.0)
    else:
        wn_fixed = _world_normal(T_fixed, normal_b)
        free_n_local = normal_a if normal_a is not None else (0.0, 1.0, 0.0)

    cur_wn_free = _unit(_transform_vector(T_free, free_n_local))

    # Find a target direction perpendicular to wn_fixed but close to cur_wn_free.
    # Use the component of cur_wn_free perpendicular to wn_fixed.
    d = _dot(cur_wn_free, wn_fixed)
    proj = (d * wn_fixed[0], d * wn_fixed[1], d * wn_fixed[2])
    perp_component = (
        cur_wn_free[0] - proj[0],
        cur_wn_free[1] - proj[1],
        cur_wn_free[2] - proj[2],
    )
    try:
        target = _unit(perp_component)
    except ValueError:
        # If cur_wn_free is already parallel to wn_fixed, pick any perpendicular
        target = _find_perpendicular(wn_fixed)

    R = _rotation_align_vectors(cur_wn_free, target)
    return _mat_mul(R, T_free)


# ---- distance ----

def _solve_distance(
    T_fixed: list[float],
    T_free: list[float],
    free_is_b: bool,
    point_a: "tuple[float, float, float] | None",
    normal_a: "tuple[float, float, float] | None",
    point_b: "tuple[float, float, float] | None",
    offset: float,
) -> list[float]:
    """
    Translate the free component so that the signed distance between
    point_b and the plane defined by (point_a, normal_a) equals ``offset``.
    """
    wn_fixed = _world_normal(T_fixed, normal_a)
    wp_fixed = _world_point(T_fixed, point_a)

    if free_is_b:
        free_p_local = point_b if point_b is not None else (0.0, 0.0, 0.0)
    else:
        free_p_local = point_a if point_a is not None else (0.0, 0.0, 0.0)

    wp_free = _world_point(T_free, free_p_local)

    # Signed distance from wp_free to plane (wp_fixed, wn_fixed)
    delta = (
        wp_free[0] - wp_fixed[0],
        wp_free[1] - wp_fixed[1],
        wp_free[2] - wp_fixed[2],
    )
    current_dist = _dot(delta, wn_fixed)
    needed_move = offset - current_dist

    T_trans = _translation_matrix(
        needed_move * wn_fixed[0],
        needed_move * wn_fixed[1],
        needed_move * wn_fixed[2],
    )
    return _mat_mul(T_trans, T_free)


# ---- angle ----

def _solve_angle(
    T_fixed: list[float],
    T_free: list[float],
    free_is_b: bool,
    normal_a: "tuple[float, float, float] | None",
    normal_b: "tuple[float, float, float] | None",
    angle_deg: float,
) -> list[float]:
    """
    Rotate the free component so the angle between its normal and the fixed
    normal equals ``angle_deg``.
    """
    if free_is_b:
        wn_fixed = _world_normal(T_fixed, normal_a)
        free_n_local = normal_b if normal_b is not None else (0.0, 0.0, 1.0)
    else:
        wn_fixed = _world_normal(T_fixed, normal_b)
        free_n_local = normal_a if normal_a is not None else (0.0, 0.0, 1.0)

    cur_wn_free = _unit(_transform_vector(T_free, free_n_local))

    # Target: rotate cur_wn_free to make angle_deg with wn_fixed.
    # Strategy: find the rotation axis = cross(cur_wn_free, wn_fixed),
    # then rotate cur_wn_free by (current_angle - desired_angle).
    current_angle_rad = math.acos(max(-1.0, min(1.0, _dot(cur_wn_free, wn_fixed))))
    target_angle_rad = math.radians(angle_deg)
    delta_rad = target_angle_rad - current_angle_rad

    rot_axis = _cross(cur_wn_free, wn_fixed)
    try:
        rot_axis = _unit(rot_axis)
    except ValueError:
        # Vectors are parallel/antiparallel — pick arbitrary perpendicular axis
        rot_axis = _find_perpendicular(wn_fixed)

    R = _rotation_from_axis_angle(rot_axis, delta_rad)
    return _mat_mul(R, T_free)


# ---- tangent ----

def _solve_tangent(
    T_fixed: list[float],
    T_free: list[float],
    free_is_b: bool,
    point_a: "tuple[float, float, float] | None",
    normal_a: "tuple[float, float, float] | None",
    point_b: "tuple[float, float, float] | None",
    offset: float,
) -> list[float]:
    """
    Tangent: a cylinder surface is tangent to a plane.
    ``offset`` is the cylinder radius (the distance from the axis to the plane).
    Equivalent to a distance mate with offset = cylinder radius.
    """
    return _solve_distance(
        T_fixed, T_free, free_is_b,
        point_a=point_a,
        normal_a=normal_a,
        point_b=point_b,
        offset=offset,
    )


__all__ = [
    "MateType",
    "Mate",
    "solve_assembly",
]
