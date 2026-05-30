"""
mate_inspector.py
=================
Assembly mate inspector — validate joint geometries between two B-rep bodies.

Supported mate constraint kinds (ASME Y14.5 §11 + SolidWorks / Inventor parity)
---------------------------------------------------------------------------
concentric    — two cylindrical faces share a common axis (axes colinear).
coincident    — two planar faces share a common plane (normals antiparallel,
                orthogonal face-to-face distance < tol).
distance      — two parallel planar faces are separated by ``parameter`` (mm).
angle         — dihedral angle between two planar/axis entities matches
                ``parameter`` (radians).
tangent       — a cylindrical face is tangent to a planar face; the
                perpendicular distance from the cylinder axis to the plane
                equals the cylinder radius.
parallel      — two face normals / axes are parallel (angle ≈ 0 or π).
perpendicular — two face normals / axes are perpendicular (angle ≈ π/2).

Public API
----------
``MateConstraint`` dataclass
    Describes one joint constraint.

``validate_mate(constraint, body_a, body_b, tol=1e-4) -> MateValidation``
    Validate a single mate against the actual B-rep geometry.

``auto_detect_potential_mates(body_a, body_b) -> list[MateConstraint]``
    Suggest candidate mates by geometric similarity scan.

``validate_assembly_mates(bodies, constraints, tol=1e-4) -> AssemblyValidation``
    Validate all mates in an assembly; report over-/under-constraint.

LLM tools
---------
``brep_validate_mate``   — validate a single MateConstraint dict.
``brep_detect_mates``    — auto-detect potential mates between two bodies.

References
----------
ASME Y14.5-2018 §11 — assembly tolerance modelling.
SolidWorks 2024 Assembly Mate Reference.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, CylinderSurface, Plane

# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]


def _np(v: Any) -> np.ndarray:
    return np.asarray(v, dtype=float)


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError(f"cannot normalise zero-length vector: {v}")
    return v / n


def _dot(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MateConstraint:
    """A single assembly joint constraint between entities on two bodies.

    Parameters
    ----------
    kind:
        One of ``'concentric'``, ``'coincident'``, ``'distance'``,
        ``'angle'``, ``'tangent'``, ``'parallel'``, ``'perpendicular'``.
    entity_a:
        Face index (int) or face descriptor on *body_a*. When ``None`` the
        inspector scans all faces of the appropriate type automatically.
    entity_b:
        Face index (int) or face descriptor on *body_b*. Same convention.
    parameter:
        Scalar parameter for the constraint:
          - distance mate  → expected gap (mm, positive)
          - angle mate     → expected dihedral angle (radians)
          - tangent mate   → cylinder radius (mm; derived automatically when
            the body carries a ``CylinderSurface`` with a known radius)
        ``None`` means "infer from geometry" for non-parametric mates.
    """

    kind: str
    entity_a: Optional[int] = None
    entity_b: Optional[int] = None
    parameter: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "entity_a": self.entity_a,
            "entity_b": self.entity_b,
            "parameter": self.parameter,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MateConstraint":
        return cls(
            kind=str(d["kind"]).lower(),
            entity_a=d.get("entity_a"),
            entity_b=d.get("entity_b"),
            parameter=float(d["parameter"]) if d.get("parameter") is not None else None,
        )


@dataclass
class MateValidation:
    """Result of validating one MateConstraint.

    Attributes
    ----------
    is_valid:
        ``True`` when the residual is within the supplied tolerance.
    residual:
        Scalar measure of constraint violation (0 when perfectly satisfied).
    recommended_translation:
        3-vector (mm) that, if applied to body_b, would satisfy the
        translational part of the constraint.  ``[0, 0, 0]`` when already
        satisfied or not applicable.
    recommended_rotation:
        3-vector (axis × angle, radians) that, if applied to body_b, would
        satisfy the rotational part of the constraint.  ``[0, 0, 0]`` when
        already satisfied or not applicable.
    message:
        Human-readable explanation of the result.
    """

    is_valid: bool
    residual: float
    recommended_translation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    recommended_rotation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "residual": self.residual,
            "recommended_translation": self.recommended_translation,
            "recommended_rotation": self.recommended_rotation,
            "message": self.message,
        }


@dataclass
class AssemblyValidation:
    """Result of validating all mates in an assembly.

    Attributes
    ----------
    ok:
        ``True`` when every mate is valid and the DOF count is consistent.
    mate_results:
        Per-mate validation results (order matches input constraints list).
    dof_remaining:
        Estimated remaining degrees of freedom across all floating bodies.
    status:
        ``'fully_constrained'`` / ``'under_constrained'`` / ``'over_constrained'``.
    errors:
        List of error strings for invalid mates or structural issues.
    """

    ok: bool
    mate_results: List[dict]
    dof_remaining: int
    status: str
    errors: List[str]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "mate_results": self.mate_results,
            "dof_remaining": self.dof_remaining,
            "status": self.status,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# DOF table (conservative canonical values, mirrors assembly/mates.py)
# ---------------------------------------------------------------------------

_MATE_DOF: Dict[str, int] = {
    "coincident":    3,
    "concentric":    4,
    "parallel":      2,
    "perpendicular": 1,
    "distance":      1,
    "angle":         1,
    "tangent":       1,
}

_VALID_KINDS = set(_MATE_DOF)


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _faces(body: Body):
    """Yield all Face objects from a Body (flat traversal)."""
    for solid in body.solids:
        for shell in solid.shells:
            for face in shell.faces:
                yield face


def _face_list(body: Body) -> list:
    return list(_faces(body))


def _cylinder_faces(body: Body) -> list:
    """Return list of faces whose surface is a CylinderSurface."""
    return [f for f in _faces(body) if isinstance(f.surface, CylinderSurface)]


def _plane_faces(body: Body) -> list:
    """Return list of faces whose surface is a Plane."""
    return [f for f in _faces(body) if isinstance(f.surface, Plane)]


def _face_by_index(body: Body, idx: Optional[int]):
    """Return the idx-th face (0-based) or None."""
    fl = _face_list(body)
    if idx is None or idx < 0 or idx >= len(fl):
        return None
    return fl[idx]


def _cylinder_axis(surf: CylinderSurface) -> Tuple[np.ndarray, np.ndarray]:
    """Return (center, unit-axis) for a CylinderSurface."""
    return _np(surf.center), _unit(_np(surf.axis))


def _plane_normal(surf: Plane) -> Tuple[np.ndarray, np.ndarray]:
    """Return (origin, unit-normal) for a Plane."""
    origin = _np(surf.origin)
    n = _unit(np.cross(_np(surf.x_axis), _np(surf.y_axis)))
    return origin, n


def _point_to_plane_distance(point: np.ndarray, origin: np.ndarray, normal: np.ndarray) -> float:
    """Signed distance from a point to a plane (origin, unit-normal)."""
    return float(np.dot(point - origin, normal))


def _axis_lateral_offset(
    pt_a: np.ndarray,
    ax_a: np.ndarray,
    pt_b: np.ndarray,
    ax_b: np.ndarray,
) -> float:
    """Minimum distance between two infinite lines (closest-approach).

    Uses the closed-form formula for skew-line distance.
    When lines are parallel the distance is the component of (pt_b - pt_a)
    perpendicular to the axis direction.
    """
    d = pt_b - pt_a
    cross = np.cross(ax_a, ax_b)
    cross_norm = float(np.linalg.norm(cross))
    if cross_norm < 1e-9:
        # Lines are parallel (or anti-parallel): lateral offset is the component
        # of d perpendicular to the axis.
        along = _dot(d, ax_a) * ax_a
        lateral = d - along
        return float(np.linalg.norm(lateral))
    return abs(_dot(d, cross)) / cross_norm


# ---------------------------------------------------------------------------
# Per-kind validators
# ---------------------------------------------------------------------------

def _validate_concentric(
    face_a, face_b, tol: float
) -> MateValidation:
    """Concentric: two cylindrical faces share a common axis."""
    if not isinstance(face_a.surface, CylinderSurface):
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message="entity_a is not a cylindrical face",
        )
    if not isinstance(face_b.surface, CylinderSurface):
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message="entity_b is not a cylindrical face",
        )

    pt_a, ax_a = _cylinder_axis(face_a.surface)
    pt_b, ax_b = _cylinder_axis(face_b.surface)

    # Check axes are parallel (or anti-parallel)
    cos_angle = abs(_dot(ax_a, ax_b))
    angle_res = float(math.acos(min(1.0, cos_angle)))  # 0 = parallel, π/2 = perp
    # Lateral offset between the infinite axis lines
    lateral = _axis_lateral_offset(pt_a, ax_a, pt_b, ax_b)

    # Combined residual: weigh lateral offset strongly (positional) + small
    # angle penalty (1 rad ≈ 57°).
    residual = math.hypot(lateral, angle_res)
    is_valid = residual < tol

    # Recommended translation: eliminate lateral offset
    d = pt_b - pt_a
    along = _dot(d, ax_a) * ax_a
    lateral_vec = d - along  # vector from a-axis to b-axis at pt_a plane
    rec_trans = (-lateral_vec).tolist()

    # Recommended rotation: align ax_b onto ax_a
    cross = np.cross(ax_b, ax_a)
    cross_norm = float(np.linalg.norm(cross))
    if cross_norm > 1e-9:
        rot_axis = cross / cross_norm
        rec_rot = (rot_axis * angle_res).tolist()
    else:
        rec_rot = [0.0, 0.0, 0.0]

    return MateValidation(
        is_valid=is_valid,
        residual=residual,
        recommended_translation=rec_trans,
        recommended_rotation=rec_rot,
        message=(
            f"Concentric: lateral offset={lateral:.4g} mm, "
            f"axis angle={math.degrees(angle_res):.3g}°; "
            f"{'PASS' if is_valid else 'FAIL'}"
        ),
    )


def _validate_coincident(
    face_a, face_b, tol: float
) -> MateValidation:
    """Coincident: two planar faces share a common plane."""
    if not isinstance(face_a.surface, Plane):
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message="entity_a is not a planar face",
        )
    if not isinstance(face_b.surface, Plane):
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message="entity_b is not a planar face",
        )

    orig_a, n_a = _plane_normal(face_a.surface)
    orig_b, n_b = _plane_normal(face_b.surface)

    # For coincident: normals must be antiparallel (dot ≈ -1)
    # or parallel (dot ≈ +1, same-side contact — less common but valid).
    cos_ab = _dot(n_a, n_b)
    # Normal alignment residual: |cos_ab| should be ≈ 1
    normal_res = abs(1.0 - abs(cos_ab))

    # Plane-to-plane orthogonal distance: project orig_b onto plane of a
    dist = abs(_point_to_plane_distance(orig_b, orig_a, n_a))
    residual = math.hypot(dist, normal_res)
    is_valid = residual < tol

    # Recommended translation: move orig_b onto orig_a's plane
    sign = 1.0 if cos_ab < 0 else -1.0
    rec_trans = (sign * dist * n_a).tolist()

    # Recommended rotation: align n_b antiparallel to n_a
    target_n = -n_a if cos_ab >= 0 else n_a
    cross = np.cross(n_b, target_n)
    cross_norm = float(np.linalg.norm(cross))
    rot_angle = float(math.acos(min(1.0, abs(cos_ab))))
    if cross_norm > 1e-9 and rot_angle > 1e-9:
        rot_axis = cross / cross_norm
        rec_rot = (rot_axis * rot_angle).tolist()
    else:
        rec_rot = [0.0, 0.0, 0.0]

    return MateValidation(
        is_valid=is_valid,
        residual=residual,
        recommended_translation=rec_trans,
        recommended_rotation=rec_rot,
        message=(
            f"Coincident: face-to-face distance={dist:.4g} mm, "
            f"normal-alignment residual={normal_res:.4g}; "
            f"{'PASS' if is_valid else 'FAIL'}"
        ),
    )


def _validate_distance(
    face_a, face_b, parameter: Optional[float], tol: float
) -> MateValidation:
    """Distance mate: parallel planar faces separated by ``parameter`` mm."""
    if not isinstance(face_a.surface, Plane):
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message="entity_a is not a planar face (distance mate requires planes)",
        )
    if not isinstance(face_b.surface, Plane):
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message="entity_b is not a planar face (distance mate requires planes)",
        )

    orig_a, n_a = _plane_normal(face_a.surface)
    orig_b, n_b = _plane_normal(face_b.surface)

    # Planes must be parallel for a distance mate
    cos_ab = abs(_dot(n_a, n_b))
    normal_res = abs(1.0 - cos_ab)

    # Actual orthogonal distance (unsigned)
    actual_dist = abs(_point_to_plane_distance(orig_b, orig_a, n_a))

    if parameter is None:
        # No target — report actual distance; always valid (diagnostic mode)
        return MateValidation(
            is_valid=True,
            residual=0.0,
            message=f"Distance mate (diagnostic): actual gap={actual_dist:.4g} mm",
        )

    expected = float(parameter)
    residual = math.hypot(abs(actual_dist - expected), normal_res)
    is_valid = residual < tol

    needed_move = expected - actual_dist
    rec_trans = (needed_move * n_a).tolist()

    return MateValidation(
        is_valid=is_valid,
        residual=abs(actual_dist - expected),
        recommended_translation=rec_trans,
        recommended_rotation=[0.0, 0.0, 0.0],
        message=(
            f"Distance mate: actual={actual_dist:.4g} mm, "
            f"expected={expected:.4g} mm, "
            f"residual={abs(actual_dist - expected):.4g} mm; "
            f"{'PASS' if is_valid else 'FAIL'}"
        ),
    )


def _validate_angle(
    face_a, face_b, parameter: Optional[float], tol: float
) -> MateValidation:
    """Angle mate: dihedral angle between two planes equals ``parameter`` (rad)."""
    # Accept both Plane and CylinderSurface (axis direction) entities.
    def _get_normal(face):
        if isinstance(face.surface, Plane):
            _, n = _plane_normal(face.surface)
            return n
        if isinstance(face.surface, CylinderSurface):
            _, ax = _cylinder_axis(face.surface)
            return ax
        return None

    n_a = _get_normal(face_a)
    n_b = _get_normal(face_b)

    if n_a is None:
        return MateValidation(is_valid=False, residual=float("inf"),
                              message="entity_a has no planar/cylindrical surface")
    if n_b is None:
        return MateValidation(is_valid=False, residual=float("inf"),
                              message="entity_b has no planar/cylindrical surface")

    cos_ab = _dot(n_a, n_b)
    cos_ab = max(-1.0, min(1.0, cos_ab))
    actual_angle = float(math.acos(abs(cos_ab)))  # in [0, π/2]

    if parameter is None:
        return MateValidation(
            is_valid=True, residual=0.0,
            message=f"Angle mate (diagnostic): actual={math.degrees(actual_angle):.3g}°",
        )

    expected_angle = float(parameter)
    # Normalise expected to [0, π]
    expected_norm = abs(expected_angle) % math.pi
    residual = abs(actual_angle - expected_norm)
    is_valid = residual < tol

    # Recommended rotation: axis = cross(n_b, n_a), angle = residual
    cross = np.cross(n_b, n_a)
    cross_norm = float(np.linalg.norm(cross))
    if cross_norm > 1e-9:
        rot_axis = cross / cross_norm
        rec_rot = (rot_axis * residual).tolist()
    else:
        rec_rot = [0.0, 0.0, 0.0]

    return MateValidation(
        is_valid=is_valid,
        residual=residual,
        recommended_translation=[0.0, 0.0, 0.0],
        recommended_rotation=rec_rot,
        message=(
            f"Angle mate: actual={math.degrees(actual_angle):.3g}°, "
            f"expected={math.degrees(expected_norm):.3g}°, "
            f"residual={math.degrees(residual):.3g}°; "
            f"{'PASS' if is_valid else 'FAIL'}"
        ),
    )


def _validate_tangent(
    face_a, face_b, parameter: Optional[float], tol: float
) -> MateValidation:
    """Tangent: a cylindrical face is tangent to a planar face.

    The cylinder axis-to-plane distance must equal the cylinder radius.
    ``parameter`` overrides the radius; if ``None`` the CylinderSurface
    radius is used.
    """
    # Accept either order: (cylinder, plane) or (plane, cylinder).
    cyl_face = plane_face = None
    if isinstance(face_a.surface, CylinderSurface) and isinstance(face_b.surface, Plane):
        cyl_face, plane_face = face_a, face_b
    elif isinstance(face_a.surface, Plane) and isinstance(face_b.surface, CylinderSurface):
        cyl_face, plane_face = face_b, face_a
    else:
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message="Tangent mate requires one cylinder + one plane (any order)",
        )

    pt_cyl, ax_cyl = _cylinder_axis(cyl_face.surface)
    orig_plane, n_plane = _plane_normal(plane_face.surface)

    # Distance from cylinder axis to plane = |projection of (pt_cyl - orig_plane) onto n_plane|
    axis_to_plane = abs(_point_to_plane_distance(pt_cyl, orig_plane, n_plane))

    radius = parameter if parameter is not None else float(cyl_face.surface.radius)
    residual = abs(axis_to_plane - radius)
    is_valid = residual < tol

    # Recommended translation: move cylinder so axis_to_plane = radius
    needed = radius - axis_to_plane
    sign = float(np.sign(_point_to_plane_distance(pt_cyl, orig_plane, n_plane)))
    if sign == 0.0:
        sign = 1.0
    rec_trans = (needed * sign * n_plane).tolist()

    return MateValidation(
        is_valid=is_valid,
        residual=residual,
        recommended_translation=rec_trans,
        recommended_rotation=[0.0, 0.0, 0.0],
        message=(
            f"Tangent: axis-to-plane={axis_to_plane:.4g} mm, "
            f"radius={radius:.4g} mm, "
            f"residual={residual:.4g} mm; "
            f"{'PASS' if is_valid else 'FAIL'}"
        ),
    )


def _validate_parallel(
    face_a, face_b, tol: float
) -> MateValidation:
    """Parallel: two face normals / axes are parallel."""
    def _get_dir(face):
        if isinstance(face.surface, Plane):
            _, n = _plane_normal(face.surface)
            return n
        if isinstance(face.surface, CylinderSurface):
            _, ax = _cylinder_axis(face.surface)
            return ax
        return None

    d_a = _get_dir(face_a)
    d_b = _get_dir(face_b)

    if d_a is None:
        return MateValidation(is_valid=False, residual=float("inf"),
                              message="entity_a has no direction (not a plane or cylinder)")
    if d_b is None:
        return MateValidation(is_valid=False, residual=float("inf"),
                              message="entity_b has no direction (not a plane or cylinder)")

    cos_ab = abs(_dot(d_a, d_b))
    cos_ab = min(1.0, cos_ab)
    angle = float(math.acos(cos_ab))  # 0 = parallel
    residual = angle
    is_valid = residual < tol

    cross = np.cross(d_b, d_a)
    cross_norm = float(np.linalg.norm(cross))
    if cross_norm > 1e-9:
        rot_axis = cross / cross_norm
        rec_rot = (rot_axis * angle).tolist()
    else:
        rec_rot = [0.0, 0.0, 0.0]

    return MateValidation(
        is_valid=is_valid,
        residual=residual,
        recommended_translation=[0.0, 0.0, 0.0],
        recommended_rotation=rec_rot,
        message=(
            f"Parallel: angle between directions={math.degrees(angle):.3g}°; "
            f"{'PASS' if is_valid else 'FAIL'}"
        ),
    )


def _validate_perpendicular(
    face_a, face_b, tol: float
) -> MateValidation:
    """Perpendicular: two face normals / axes are perpendicular."""
    def _get_dir(face):
        if isinstance(face.surface, Plane):
            _, n = _plane_normal(face.surface)
            return n
        if isinstance(face.surface, CylinderSurface):
            _, ax = _cylinder_axis(face.surface)
            return ax
        return None

    d_a = _get_dir(face_a)
    d_b = _get_dir(face_b)

    if d_a is None:
        return MateValidation(is_valid=False, residual=float("inf"),
                              message="entity_a has no direction")
    if d_b is None:
        return MateValidation(is_valid=False, residual=float("inf"),
                              message="entity_b has no direction")

    cos_ab = _dot(d_a, d_b)
    cos_ab = max(-1.0, min(1.0, cos_ab))
    angle_from_perp = abs(abs(cos_ab) - 0.0)  # deviation from cos(π/2)=0
    # residual = |cos(θ_actual)| — 0: smaller is better
    residual = abs(cos_ab)
    is_valid = residual < tol

    # Rotation to make perpendicular: rotate by (π/2 - actual_angle)
    actual_angle = float(math.acos(abs(cos_ab)))
    delta = math.pi / 2.0 - actual_angle
    cross = np.cross(d_b, d_a)
    cross_norm = float(np.linalg.norm(cross))
    if cross_norm > 1e-9 and abs(delta) > 1e-9:
        rot_axis = cross / cross_norm
        rec_rot = (rot_axis * delta).tolist()
    else:
        rec_rot = [0.0, 0.0, 0.0]

    return MateValidation(
        is_valid=is_valid,
        residual=residual,
        recommended_translation=[0.0, 0.0, 0.0],
        recommended_rotation=rec_rot,
        message=(
            f"Perpendicular: |cos(θ)|={residual:.4g} (ideal 0); "
            f"{'PASS' if is_valid else 'FAIL'}"
        ),
    )


# ---------------------------------------------------------------------------
# Face auto-selection helpers
# ---------------------------------------------------------------------------

def _best_cyl_face(body: Body) -> Optional[object]:
    cyls = _cylinder_faces(body)
    return cyls[0] if cyls else None


def _best_plane_face(body: Body) -> Optional[object]:
    planes = _plane_faces(body)
    return planes[0] if planes else None


def _resolve_face(body: Body, entity_idx: Optional[int], kind: str) -> Optional[object]:
    """Resolve a face from the body by index, or auto-select by kind."""
    if entity_idx is not None:
        return _face_by_index(body, entity_idx)
    # Auto-select
    if kind in ("concentric",):
        return _best_cyl_face(body)
    if kind in ("coincident", "distance", "parallel", "perpendicular"):
        return _best_plane_face(body)
    if kind == "tangent":
        # Try cylinder first; fall back to plane
        f = _best_cyl_face(body)
        return f if f is not None else _best_plane_face(body)
    if kind == "angle":
        f = _best_plane_face(body)
        return f if f is not None else _best_cyl_face(body)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_mate(
    constraint: MateConstraint,
    body_a: Body,
    body_b: Body,
    tol: float = 1e-4,
) -> MateValidation:
    """Validate a single MateConstraint against two B-rep bodies.

    Parameters
    ----------
    constraint:
        The mate to evaluate.
    body_a:
        First B-rep body (the ``entity_a`` face lives here).
    body_b:
        Second B-rep body (the ``entity_b`` face lives here).
    tol:
        Tolerance (mm or rad); a residual below this is considered passing.

    Returns
    -------
    MateValidation
        Structured result with ``is_valid``, ``residual``, and correction hints.
        Never raises.
    """
    kind = constraint.kind.lower()
    if kind not in _VALID_KINDS:
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message=f"Unknown mate kind '{kind}'. Valid: {sorted(_VALID_KINDS)}",
        )

    try:
        face_a = _resolve_face(body_a, constraint.entity_a, kind)
        face_b = _resolve_face(body_b, constraint.entity_b, kind)
    except Exception as exc:
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message=f"Face resolution error: {exc}",
        )

    if face_a is None:
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message=f"No suitable face found on body_a for '{kind}' mate",
        )
    if face_b is None:
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message=f"No suitable face found on body_b for '{kind}' mate",
        )

    try:
        if kind == "concentric":
            return _validate_concentric(face_a, face_b, tol)
        if kind == "coincident":
            return _validate_coincident(face_a, face_b, tol)
        if kind == "distance":
            return _validate_distance(face_a, face_b, constraint.parameter, tol)
        if kind == "angle":
            return _validate_angle(face_a, face_b, constraint.parameter, tol)
        if kind == "tangent":
            return _validate_tangent(face_a, face_b, constraint.parameter, tol)
        if kind == "parallel":
            return _validate_parallel(face_a, face_b, tol)
        if kind == "perpendicular":
            return _validate_perpendicular(face_a, face_b, tol)
    except Exception as exc:  # pragma: no cover
        return MateValidation(
            is_valid=False, residual=float("inf"),
            message=f"Validation error: {exc}",
        )

    return MateValidation(is_valid=False, residual=float("inf"),
                          message=f"Unhandled kind '{kind}'")


def auto_detect_potential_mates(
    body_a: Body,
    body_b: Body,
) -> List[MateConstraint]:
    """Scan two bodies and suggest candidate MateConstraints.

    Detection rules
    ---------------
    1. **Concentric**: body_a has a cylindrical face and body_b has a
       cylindrical face with the same (or nearly equal) radius → suggest
       ``concentric``.
    2. **Parallel / Coincident**: body_a has a planar face and body_b has a
       planar face with near-parallel normals → suggest ``coincident`` if
       the face-to-face distance is within 2 × tol, else ``distance``.
    3. **Tangent**: body_a has a cylindrical face and body_b has a planar
       face (or vice versa) where the axis-to-plane distance is near the
       cylinder radius → suggest ``tangent``.

    Returns a list of MateConstraint objects (may be empty).
    """
    candidates: List[MateConstraint] = []
    _RADIUS_TOL = 0.1   # mm — same-radius check
    _PARALLEL_TOL = 0.05  # rad
    _DIST_TOL = 0.5     # mm — coincident vs distance threshold

    cyls_a = _cylinder_faces(body_a)
    cyls_b = _cylinder_faces(body_b)
    planes_a = _plane_faces(body_a)
    planes_b = _plane_faces(body_b)

    all_faces_a = _face_list(body_a)
    all_faces_b = _face_list(body_b)

    # 1. Concentric: matching-radius cylinders
    for i, fa in enumerate(cyls_a):
        for j, fb in enumerate(cyls_b):
            r_a = float(fa.surface.radius)
            r_b = float(fb.surface.radius)
            if abs(r_a - r_b) <= _RADIUS_TOL:
                idx_a = all_faces_a.index(fa)
                idx_b = all_faces_b.index(fb)
                candidates.append(
                    MateConstraint(kind="concentric", entity_a=idx_a, entity_b=idx_b)
                )

    # 2. Parallel / Coincident / Distance: plane pairs
    for i, fa in enumerate(planes_a):
        orig_a, n_a = _plane_normal(fa.surface)
        for j, fb in enumerate(planes_b):
            orig_b, n_b = _plane_normal(fb.surface)
            cos_ab = abs(_dot(n_a, n_b))
            if cos_ab >= math.cos(_PARALLEL_TOL):
                dist = abs(_point_to_plane_distance(orig_b, orig_a, n_a))
                idx_a = all_faces_a.index(fa)
                idx_b = all_faces_b.index(fb)
                if dist <= _DIST_TOL:
                    candidates.append(
                        MateConstraint(kind="coincident", entity_a=idx_a, entity_b=idx_b)
                    )
                else:
                    candidates.append(
                        MateConstraint(kind="distance", entity_a=idx_a, entity_b=idx_b,
                                       parameter=round(dist, 6))
                    )

    # 3. Tangent: cylinder + plane where axis-to-plane ≈ radius
    def _check_tangent(cyl_face, plane_face, idx_cyl, idx_plane, swap: bool):
        pt_cyl, _ = _cylinder_axis(cyl_face.surface)
        orig_p, n_p = _plane_normal(plane_face.surface)
        dist = abs(_point_to_plane_distance(pt_cyl, orig_p, n_p))
        r = float(cyl_face.surface.radius)
        if abs(dist - r) <= _RADIUS_TOL:
            if swap:
                candidates.append(
                    MateConstraint(kind="tangent", entity_a=idx_plane, entity_b=idx_cyl,
                                   parameter=r)
                )
            else:
                candidates.append(
                    MateConstraint(kind="tangent", entity_a=idx_cyl, entity_b=idx_plane,
                                   parameter=r)
                )

    for fa in cyls_a:
        idx_cyl = all_faces_a.index(fa)
        for fb in planes_b:
            idx_plane = all_faces_b.index(fb)
            _check_tangent(fa, fb, idx_cyl, idx_plane, swap=False)

    for fa in planes_a:
        idx_plane = all_faces_a.index(fa)
        for fb in cyls_b:
            idx_cyl = all_faces_b.index(fb)
            _check_tangent(fb, fa, idx_plane, idx_cyl, swap=True)

    return candidates


def validate_assembly_mates(
    bodies: Dict[str, Body],
    constraints: List[MateConstraint],
    tol: float = 1e-4,
) -> AssemblyValidation:
    """Validate all mate constraints in an assembly.

    Parameters
    ----------
    bodies:
        Mapping of ``{body_id: Body}``.  The *first* entry is treated as the
        ground (fixed, 0 DOF); all others start with 6 DOF each.
    constraints:
        List of MateConstraints.  Each constraint carries ``entity_a`` and
        ``entity_b`` as face indices; body identity is resolved by treating
        bodies as a list in insertion order: body[0] and body[1] from the
        key order of the dict.

        For a two-body assembly this is straightforward. For multi-body
        assemblies the caller should pass per-pair constraints with the
        body_ids embedded; the current implementation resolves the constraint
        against the first two bodies by default (extensible for multi-body).
    tol:
        Validation tolerance.

    Returns
    -------
    AssemblyValidation
        ``ok`` is ``True`` only if all mates pass and DOF ≥ 0.
    """
    body_ids = list(bodies.keys())
    errors: List[str] = []
    mate_results = []

    if len(body_ids) < 2:
        return AssemblyValidation(
            ok=False,
            mate_results=[],
            dof_remaining=0,
            status="under_constrained",
            errors=["Assembly requires at least 2 bodies"],
        )

    # Simple two-body DOF accounting (extensible)
    # Ground (body_ids[0]) = 0 DOF; remaining bodies start with 6 each.
    dof = {bid: (0 if i == 0 else 6) for i, bid in enumerate(body_ids)}
    body_a = bodies[body_ids[0]]
    body_b = bodies[body_ids[1]]

    for idx, c in enumerate(constraints):
        result = validate_mate(c, body_a, body_b, tol)
        mate_results.append(result.to_dict())
        if not result.is_valid:
            errors.append(
                f"Mate[{idx}] '{c.kind}': INVALID — {result.message}"
            )
        # DOF reduction: subtract from the non-ground body
        target = body_ids[1]
        dof_reduce = _MATE_DOF.get(c.kind, 0)
        if dof[target] > 0:
            actual_reduce = min(dof_reduce, dof[target])
            dof[target] -= actual_reduce
        else:
            # Over-constrained
            errors.append(
                f"Mate[{idx}] '{c.kind}': over-constrained — no DOF left on '{target}'"
            )

    total_dof = sum(dof.values())
    over = any("over-constrained" in e for e in errors)

    if over:
        status = "over_constrained"
    elif total_dof == 0 and len(errors) == 0:
        status = "fully_constrained"
    elif total_dof > 0:
        status = "under_constrained"
    else:
        status = "fully_constrained"

    ok = (len(errors) == 0)

    return AssemblyValidation(
        ok=ok,
        mate_results=mate_results,
        dof_remaining=total_dof,
        status=status,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _HAS_REGISTRY = True
except ImportError:
    _HAS_REGISTRY = False


if _HAS_REGISTRY:

    # ---- brep_validate_mate ------------------------------------------------

    _validate_spec = ToolSpec(
        name="brep_validate_mate",
        description=(
            "Validate a single assembly mate constraint between two B-rep bodies. "
            "Returns is_valid, residual, recommended_translation, recommended_rotation. "
            "\n"
            "Mate kinds: concentric, coincident, distance, angle, tangent, parallel, perpendicular. "
            "\n"
            "``body_a`` and ``body_b`` are serialised Body dicts (from brep_build tools). "
            "``entity_a`` / ``entity_b`` are face indices (0-based); omit for auto-select. "
            "``parameter``: distance (mm) for distance mate, angle (radians) for angle mate, "
            "               cylinder radius (mm) for tangent mate. Omit for auto-detect. "
            "\n"
            "Returns: {is_valid, residual, recommended_translation, recommended_rotation, message}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_a": {"type": "object", "description": "Serialised Body dict for component A."},
                "body_b": {"type": "object", "description": "Serialised Body dict for component B."},
                "kind": {
                    "type": "string",
                    "enum": sorted(_VALID_KINDS),
                    "description": "Mate constraint kind.",
                },
                "entity_a": {"type": "integer", "description": "Face index on body_a (0-based). Auto-selected if omitted."},
                "entity_b": {"type": "integer", "description": "Face index on body_b (0-based). Auto-selected if omitted."},
                "parameter": {"type": "number", "description": "Distance (mm), angle (rad), or radius (mm) depending on kind."},
                "tol": {"type": "number", "description": "Validation tolerance (mm/rad). Default 1e-4."},
            },
            "required": ["body_a", "body_b", "kind"],
        },
    )

    @register(_validate_spec, write=False)
    async def run_brep_validate_mate(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        body_a_raw = a.get("body_a")
        body_b_raw = a.get("body_b")
        kind = str(a.get("kind", "")).strip().lower()

        if not body_a_raw or not isinstance(body_a_raw, dict):
            return err_payload("body_a is required", "BAD_ARGS")
        if not body_b_raw or not isinstance(body_b_raw, dict):
            return err_payload("body_b is required", "BAD_ARGS")
        if kind not in _VALID_KINDS:
            return err_payload(f"Unknown kind '{kind}'. Valid: {sorted(_VALID_KINDS)}", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.brep import Body as _Body  # noqa: PLC0415
            body_a = _Body.from_dict(body_a_raw)
            body_b = _Body.from_dict(body_b_raw)
        except Exception as exc:
            return err_payload(f"Body deserialisation error: {exc}", "BAD_ARGS")

        constraint = MateConstraint(
            kind=kind,
            entity_a=a.get("entity_a"),
            entity_b=a.get("entity_b"),
            parameter=float(a["parameter"]) if a.get("parameter") is not None else None,
        )
        tol = float(a.get("tol", 1e-4))

        result = validate_mate(constraint, body_a, body_b, tol)
        return ok_payload(result.to_dict())

    # ---- brep_detect_mates -------------------------------------------------

    _detect_spec = ToolSpec(
        name="brep_detect_mates",
        description=(
            "Auto-detect potential assembly mate constraints between two B-rep bodies "
            "by geometric similarity scanning. "
            "\n"
            "Detection: same-radius cylinders → concentric; parallel planes → coincident/distance; "
            "cylinder + plane at axis-to-plane ≈ radius → tangent. "
            "\n"
            "Returns: {candidates: [{kind, entity_a, entity_b, parameter}]}. "
            "Each candidate can be passed to brep_validate_mate for full validation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_a": {"type": "object", "description": "Serialised Body dict for component A."},
                "body_b": {"type": "object", "description": "Serialised Body dict for component B."},
            },
            "required": ["body_a", "body_b"],
        },
    )

    @register(_detect_spec, write=False)
    async def run_brep_detect_mates(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        body_a_raw = a.get("body_a")
        body_b_raw = a.get("body_b")

        if not body_a_raw or not isinstance(body_a_raw, dict):
            return err_payload("body_a is required", "BAD_ARGS")
        if not body_b_raw or not isinstance(body_b_raw, dict):
            return err_payload("body_b is required", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.brep import Body as _Body  # noqa: PLC0415
            body_a = _Body.from_dict(body_a_raw)
            body_b = _Body.from_dict(body_b_raw)
        except Exception as exc:
            return err_payload(f"Body deserialisation error: {exc}", "BAD_ARGS")

        candidates = auto_detect_potential_mates(body_a, body_b)
        return ok_payload({
            "candidates": [c.to_dict() for c in candidates],
            "count": len(candidates),
        })


__all__ = [
    "MateConstraint",
    "MateValidation",
    "AssemblyValidation",
    "validate_mate",
    "auto_detect_potential_mates",
    "validate_assembly_mates",
]
