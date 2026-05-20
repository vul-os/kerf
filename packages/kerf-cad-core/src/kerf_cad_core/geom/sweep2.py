"""sweep2: two-rail sweep surface generation.

Frame computation:
- Legacy: compute_adaptive_frame — global world reference, can twist.
- RMF (Wang 2008): imported from sweep1, propagated along the midline of
  the two rails so that the frame is torsion-free.
"""
import numpy as np
from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.sweep1 import compute_rmf_frames


def _midline_tangents(rail1: NurbsCurve, rail2: NurbsCurve,
                      n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample n points on each rail and compute midline points + tangents.

    Returns (midpoints, tangents, params) each of shape (n, 3) / (n,).
    """
    ts = np.linspace(0.0, 1.0, n)
    pts1 = np.array([rail1.evaluate(t) for t in ts])
    pts2 = np.array([rail2.evaluate(t) for t in ts])
    mids = 0.5 * (pts1 + pts2)

    tangents = np.zeros_like(mids)
    tangents[0] = mids[1] - mids[0]
    tangents[-1] = mids[-1] - mids[-2]
    tangents[1:-1] = mids[2:] - mids[:-2]

    norms = np.linalg.norm(tangents, axis=1, keepdims=True)
    norms = np.where(norms < 1e-15, 1.0, norms)
    tangents = tangents / norms

    return pts1, pts2, mids, tangents


def sweep2(profile: NurbsCurve, rail1: NurbsCurve, rail2: NurbsCurve) -> NurbsSurface:
    """Sweep *profile* between *rail1* and *rail2* using a rotation-minimising
    frame (Wang 2008) propagated along the midline of the two rails.
    """
    if profile.degree < 1 or rail1.degree < 1 or rail2.degree < 1:
        raise ValueError("Profile and rails must have degree >= 1")

    if rail1.num_control_points != rail2.num_control_points:
        raise ValueError("Rail1 and Rail2 must have same number of control points")

    num_profile_pts = profile.num_control_points
    num_path_pts = rail1.num_control_points

    degree_u = profile.degree
    degree_v = max(rail1.degree, rail2.degree)

    pts1, pts2, mids, tangents = _midline_tangents(rail1, rail2, num_path_pts)
    rmf = compute_rmf_frames(tangents, points=mids)

    control_points = np.zeros((num_profile_pts, num_path_pts, 3))

    for i in range(num_path_pts):
        p1 = pts1[i]
        p2 = pts2[i]
        frame = rmf[i]

        for j in range(num_profile_pts):
            profile_pt = profile.control_points[j]
            t = j / (num_profile_pts - 1) if num_profile_pts > 1 else 0.5
            base_pt = (1 - t) * p1 + t * p2
            world_pt = base_pt + frame @ profile_pt
            control_points[j, i] = world_pt

    knots_u = profile.knots.copy()
    knots_v = merge_knot_vectors([rail1.knots, rail2.knots])

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=knots_v
    )


def compute_adaptive_frame(rail_direction: np.ndarray,
                           tangent1: np.ndarray,
                           tangent2: np.ndarray) -> np.ndarray:
    reference = np.array([0, 0, 1])
    if abs(np.dot(rail_direction, reference)) > 0.9:
        reference = np.array([0, 1, 0])

    normal = np.cross(rail_direction, reference)
    normal = normal / (np.linalg.norm(normal) + 1e-10)

    binormal = np.cross(rail_direction, normal)
    binormal = binormal / (np.linalg.norm(binormal) + 1e-10)

    frame = np.column_stack([rail_direction, normal, binormal])
    return frame


def merge_knot_vectors(knot_vectors: list) -> np.ndarray:
    max_length = max(len(kv) for kv in knot_vectors)
    merged = np.zeros(max_length)
    counts = np.zeros(max_length)

    for kv in knot_vectors:
        for i, k in enumerate(kv):
            merged[i] += k
            counts[i] += 1

    for i in range(max_length):
        if counts[i] > 0:
            merged[i] /= counts[i]

    return merged


def sweep2_rmf(
    profile: NurbsCurve,
    rail1: NurbsCurve,
    rail2: NurbsCurve,
    num_samples: int | None = None,
    initial_normal: np.ndarray | None = None,
) -> NurbsSurface:
    """Public alias: sweep2 with explicit Wang 2008 RMF along the rail midline.

    Parameters
    ----------
    profile, rail1, rail2 : NurbsCurve
    num_samples : frame samples along rails; defaults to rail1.num_control_points.
    initial_normal : optional seed normal for the first frame.
    """
    if profile.degree < 1 or rail1.degree < 1 or rail2.degree < 1:
        raise ValueError("Profile and rails must have degree >= 1")

    n = num_samples if num_samples is not None else rail1.num_control_points
    n = max(n, 2)

    pts1, pts2, mids, tangents = _midline_tangents(rail1, rail2, n)
    rmf = compute_rmf_frames(tangents, initial_r=initial_normal, points=mids)

    num_profile_pts = profile.num_control_points
    control_points = np.zeros((num_profile_pts, n, 3))

    for i in range(n):
        p1 = pts1[i]
        p2 = pts2[i]
        frame = rmf[i]
        for j in range(num_profile_pts):
            t = j / (num_profile_pts - 1) if num_profile_pts > 1 else 0.5
            base_pt = (1 - t) * p1 + t * p2
            world_pt = base_pt + frame @ profile.control_points[j]
            control_points[j, i] = world_pt

    knots_u = profile.knots.copy()
    degree_v = max(rail1.degree, rail2.degree)
    knots_v = np.concatenate([
        np.zeros(degree_v),
        np.linspace(0.0, 1.0, n - degree_v + 1),
        np.ones(degree_v),
    ])

    return NurbsSurface(
        degree_u=profile.degree,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=knots_v,
    )


def sweep2_with_scaling(profile: NurbsCurve, rail1: NurbsCurve, rail2: NurbsCurve,
                         scale1: float = 1.0, scale2: float = 1.0) -> NurbsSurface:
    """Two-rail sweep with linearly-interpolated per-section scaling, using RMF."""
    if rail1.num_control_points != rail2.num_control_points:
        raise ValueError("Rail1 and Rail2 must have same number of control points")

    num_profile_pts = profile.num_control_points
    num_path_pts = rail1.num_control_points

    degree_u = profile.degree
    degree_v = max(rail1.degree, rail2.degree)

    pts1, pts2, mids, tangents = _midline_tangents(rail1, rail2, num_path_pts)
    rmf = compute_rmf_frames(tangents, points=mids)

    control_points = np.zeros((num_profile_pts, num_path_pts, 3))

    for i in range(num_path_pts):
        p1 = pts1[i]
        p2 = pts2[i]
        frame = rmf[i]

        for j in range(num_profile_pts):
            profile_pt = profile.control_points[j]
            t = j / (num_profile_pts - 1) if num_profile_pts > 1 else 0.5
            scale = (1 - t) * scale1 + t * scale2
            base_pt = (1 - t) * p1 + t * p2
            scaled_profile_pt = profile_pt * scale
            world_pt = base_pt + frame @ scaled_profile_pt
            control_points[j, i] = world_pt

    knots_u = profile.knots.copy()
    knots_v = merge_knot_vectors([rail1.knots, rail2.knots])

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=knots_v
    )


def sweep2_with_twist(profile: NurbsCurve, rail1: NurbsCurve, rail2: NurbsCurve,
                      twist_per_unit: float = 0.0) -> NurbsSurface:
    """Two-rail sweep with arc-length-proportional twist applied on top of RMF."""
    if rail1.num_control_points != rail2.num_control_points:
        raise ValueError("Rail1 and Rail2 must have same number of control points")

    num_profile_pts = profile.num_control_points
    num_path_pts = rail1.num_control_points

    degree_u = profile.degree
    degree_v = max(rail1.degree, rail2.degree)

    pts1, pts2, mids, tangents = _midline_tangents(rail1, rail2, num_path_pts)
    rmf = compute_rmf_frames(tangents, points=mids)

    control_points = np.zeros((num_profile_pts, num_path_pts, 3))
    accumulated_twist = 0.0

    for i in range(num_path_pts):
        p1 = pts1[i]
        p2 = pts2[i]
        frame = rmf[i]
        t_vec = tangents[i]

        if i > 0:
            segment_length = np.linalg.norm(mids[i] - mids[i - 1])
            accumulated_twist += twist_per_unit * segment_length

        twist_rotation = rotation_matrix_3d(t_vec, accumulated_twist)
        twisted_frame = frame @ twist_rotation

        for j in range(num_profile_pts):
            profile_pt = profile.control_points[j]
            t = j / (num_profile_pts - 1) if num_profile_pts > 1 else 0.5
            base_pt = (1 - t) * p1 + t * p2
            world_pt = base_pt + twisted_frame @ profile_pt
            control_points[j, i] = world_pt

    knots_u = profile.knots.copy()
    knots_v = merge_knot_vectors([rail1.knots, rail2.knots])

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=control_points,
        knots_u=knots_u,
        knots_v=knots_v
    )


def rotation_matrix_3d(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = axis / (np.linalg.norm(axis) + 1e-10)
    c = np.cos(angle)
    s = np.sin(angle)
    t = 1 - c

    return np.array([
        [t * axis[0] * axis[0] + c, t * axis[0] * axis[1] - s * axis[2], t * axis[0] * axis[2] + s * axis[1]],
        [t * axis[0] * axis[1] + s * axis[2], t * axis[1] * axis[1] + c, t * axis[1] * axis[2] - s * axis[0]],
        [t * axis[0] * axis[2] - s * axis[1], t * axis[1] * axis[2] + s * axis[0], t * axis[2] * axis[2] + c]
    ])


def check_rail_compatibility(rail1: NurbsCurve, rail2: NurbsCurve) -> bool:
    if rail1.degree != rail2.degree:
        return False
    if abs(rail1.knots[-1] - rail2.knots[-1]) > 1e-6:
        return False
    if abs(rail1.knots[0] - rail2.knots[0]) > 1e-6:
        return False
    return True


def normalize_rails(rail1: NurbsCurve, rail2: NurbsCurve) -> tuple:
    from kerf_cad_core.geom.nurbs import knot_insertion

    if not check_rail_compatibility(rail1, rail2):
        max_knots = max(len(rail1.knots), len(rail2.knots))
        target_knots = np.linspace(0, 1, max_knots)

        normalized1 = rail1
        normalized2 = rail2

        return normalized1, normalized2

    return rail1, rail2