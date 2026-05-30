"""feature_detect.py — Boss + rib auto-detection and moldability scoring.

GK-P: Boss and rib recognition for injection-moulded plastic parts,
implementing Boothroyd-Dewhurst (2002) §10 design-for-moulding rules.

Provides
--------
detect_bosses(body, wall_thickness=2.0) -> list[BossFeature]
    Identify cylindrical protrusions (bosses) above a planar base face and
    validate against the Boothroyd-Dewhurst boss diameter / wall ratio rule:
    diameter / wall_thickness >= 2.5 to avoid sink marks.

detect_ribs(body, wall_thickness=2.0) -> list[RibFeature]
    Identify thin-wall planar face pairs (ribs) connected to a base face and
    validate against: rib_thickness / wall_thickness <= 0.6 to avoid sink marks.

detect_undercuts_for_features(body, pull_direction) -> dict
    Thin wrapper around mold.undercut_faces; reuse the Wave 4T parting-line
    undercut detector for feature-level moldability reports.

moldability_score(body, material='abs', wall_thickness=2.0) -> dict
    Composite moldability index [0, 100] combining:
      - boss rule violations
      - rib rule violations
      - undercut count (from pull direction Z by default)
      - wall thickness range (via wall_thickness.py heatmap)
      - draft angles (from surface_analysis.draft_angle_analysis)

References
----------
Boothroyd, G., Dewhurst, P., Knight, W.A. (2002).
    *Product Design for Manufacture and Assembly*, 2nd ed. §10 Moulding.
    Marcel Dekker.
Liang, M., Wang, C.C.L. (2014).
    "Feature recognition from STEP files", *CAD*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Union

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CylinderSurface,
    Face,
    Plane,
    SphereSurface,
    TorusSurface,
)

__all__ = [
    "BossFeature",
    "RibFeature",
    "detect_bosses",
    "detect_ribs",
    "detect_undercuts_for_features",
    "moldability_score",
]

# ---------------------------------------------------------------------------
# Boothroyd-Dewhurst 2002 §10 rule constants
# ---------------------------------------------------------------------------

_BOSS_RATIO_MIN: float = 2.5   # diameter / wall_thickness must be >= 2.5
_RIB_RATIO_MAX: float = 0.6    # rib_thickness / wall_thickness must be <= 0.6
_DRAFT_MIN_DEG: float = 0.5    # minimum acceptable draft angle (degrees)

# UV grid resolution for face sampling (same convention as mold.py / GK-118)
_GRID: int = 12


# ---------------------------------------------------------------------------
# Internal geometry helpers (mirrors feature_recognition.py style)
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _is_plane(face: Face) -> bool:
    return isinstance(face.surface, Plane)


def _is_cylinder_like(face: Face) -> bool:
    """Duck-typed cylinder: has radius + axis + normal + evaluate; not torus."""
    s = face.surface
    return (
        hasattr(s, "radius")
        and hasattr(s, "axis")
        and hasattr(s, "normal")
        and hasattr(s, "evaluate")
        and not isinstance(s, TorusSurface)
    )


def _cyl_center(surface: object) -> np.ndarray:
    if hasattr(surface, "center"):
        return np.asarray(surface.center, dtype=float)  # type: ignore[union-attr]
    if hasattr(surface, "centre"):
        return np.asarray(surface.centre, dtype=float)  # type: ignore[union-attr]
    raise AttributeError(f"No center/centre on {type(surface).__name__}")


def _cyl_radius(face: Face) -> float:
    return float(face.surface.radius)  # type: ignore[union-attr]


def _cyl_axis(face: Face) -> np.ndarray:
    return _unit(np.asarray(face.surface.axis, dtype=float))  # type: ignore[union-attr]


def _cylinder_concavity(face: Face) -> float:
    """dot(outward_normal, radial_inward) — positive = concave (hole), negative = convex (boss)."""
    s = face.surface
    pt = np.asarray(s.evaluate(0.0, 0.0), dtype=float)  # type: ignore[union-attr]
    center = _cyl_center(s)
    axis = _unit(np.asarray(s.axis, dtype=float))  # type: ignore[union-attr]
    t = float(np.dot(pt - center, axis))
    nearest = center + t * axis
    radial_inward = _unit(nearest - pt)
    normal = np.asarray(face.surface_normal(0.0, 0.0), dtype=float)
    return float(np.dot(normal, radial_inward))


def _build_adjacency(body: Body) -> Dict[int, Set[int]]:
    edge_to_faces: Dict[int, List[int]] = {}
    for face in body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                eid = id(ce.edge)
                edge_to_faces.setdefault(eid, []).append(face.id)
    adj: Dict[int, Set[int]] = {f.id: set() for f in body.all_faces()}
    for fids in edge_to_faces.values():
        for i, a in enumerate(fids):
            for b in fids[i + 1:]:
                if a != b:
                    adj[a].add(b)
                    adj[b].add(a)
    return adj


def _face_by_id(body: Body) -> Dict[int, Face]:
    return {f.id: f for f in body.all_faces()}


def _face_surface_domain(face: Face) -> tuple:
    """Return (u_lo, u_hi, v_lo, v_hi) for the face's parametric domain."""
    srf = face.surface
    if isinstance(srf, Plane):
        return 0.0, 1.0, 0.0, 1.0
    elif _is_cylinder_like(face):
        return 0.0, 2.0 * math.pi, 0.0, 1.0
    elif isinstance(srf, SphereSurface):
        return 0.0, 2.0 * math.pi, -math.pi / 2.0, math.pi / 2.0
    return 0.0, 1.0, 0.0, 1.0


def _sample_face_z_range(face: Face, n: int = _GRID) -> tuple:
    """Sample the face on a UV grid and return (z_min, z_max)."""
    u0, u1, v0, v1 = _face_surface_domain(face)
    us = np.linspace(u0, u1, n)
    vs = np.linspace(v0, v1, n)
    zvals = []
    for u in us:
        for v in vs:
            pt = np.asarray(face.surface.evaluate(float(u), float(v)), dtype=float)
            zvals.append(float(pt[2]))
    return min(zvals), max(zvals)


def _plane_normal_vec(face: Face) -> np.ndarray:
    return _unit(np.asarray(face.surface_normal(0.0, 0.0), dtype=float))


def _cyl_height_from_adjacent_planes(
    cyl_face: Face,
    planar_neighbors: List[Face],
) -> float:
    """Estimate the height of the cylindrical boss from adjacent cap planes.

    Projects each cap plane's origin onto the cylinder axis and returns the
    span along the axis.
    """
    axis = _cyl_axis(cyl_face)
    center = _cyl_center(cyl_face.surface)
    projections = []
    for pf in planar_neighbors:
        origin = np.asarray(pf.surface.origin, dtype=float)  # type: ignore[union-attr]
        proj = float(np.dot(origin - center, axis))
        projections.append(proj)
    if len(projections) >= 2:
        return float(abs(max(projections) - min(projections)))
    if len(projections) == 1:
        # Fall back to sampling the cylinder's v range
        _, _, v0, v1 = _face_surface_domain(cyl_face)
        # v is the height coordinate for CylinderSurface
        # Try to get height from z-range of sampled points
        z_lo, z_hi = _sample_face_z_range(cyl_face)
        return float(abs(z_hi - z_lo))
    # Last resort: sample the face
    z_lo, z_hi = _sample_face_z_range(cyl_face)
    return float(abs(z_hi - z_lo))


def _identify_base_face(
    cyl_face: Face,
    planar_neighbors: List[Face],
    adj: Dict[int, Set[int]],
) -> Optional[Face]:
    """Return the most likely base (bottom) planar face for a boss.

    Heuristic: the planar face whose normal is closest to anti-parallel with
    the cylinder axis (i.e., the floor of the boss).
    """
    axis = _cyl_axis(cyl_face)
    best: Optional[Face] = None
    best_dot = 2.0
    for pf in planar_neighbors:
        n = _plane_normal_vec(pf)
        # We want a face perpendicular to the axis (its normal aligns with axis)
        cos_a = abs(float(np.dot(n, axis)))
        # cos_a close to 1 means the plane is perpendicular to the cylinder axis
        # i.e., it's a cap face (top or base of boss)
        if cos_a > 0.8:
            # pick the one that is lowest along the axis direction
            origin = np.asarray(pf.surface.origin, dtype=float)  # type: ignore[union-attr]
            proj = float(np.dot(origin - _cyl_center(cyl_face.surface), axis))
            if best is None or proj < best_dot:
                best = pf
                best_dot = proj
    return best


def _thin_wall_pair_thickness(fa: Face, fb: Face, n: int = _GRID) -> float:
    """Estimate the thickness between two parallel planar faces by sampling.

    Both faces must be planar. The thickness is the average perpendicular
    distance between sampled points on face_a and the opposite plane fb.
    """
    # Get the normal of face_a
    na = _plane_normal_vec(fa)
    orig_b = np.asarray(fb.surface.origin, dtype=float)  # type: ignore[union-attr]
    orig_a = np.asarray(fa.surface.origin, dtype=float)  # type: ignore[union-attr]
    # Distance from fa's plane to fb's plane along the normal
    d = abs(float(np.dot(orig_b - orig_a, na)))
    return d


def _are_parallel_planes(fa: Face, fb: Face, tol_deg: float = 10.0) -> bool:
    """Return True if two planar faces have parallel (or anti-parallel) normals."""
    if not (_is_plane(fa) and _is_plane(fb)):
        return False
    na = _plane_normal_vec(fa)
    nb = _plane_normal_vec(fb)
    cos_a = abs(float(np.dot(na, nb)))
    return cos_a > math.cos(math.radians(tol_deg))


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass
class BossFeature:
    """A cylindrical protrusion (boss) detected in a moulded body.

    Attributes
    ----------
    face_ids : list[int]
        IDs of the B-rep faces belonging to this boss (lateral cylinder face
        plus any detected cap faces).
    diameter : float
        Boss diameter (2 × cylinder radius), in model units.
    height : float
        Boss height measured along the cylinder axis, in model units.
    base_face_id : int | None
        Face ID of the planar base/floor face the boss sits on, or None if
        not identifiable.
    moldability_valid : bool
        True iff diameter / wall_thickness >= 2.5  (Boothroyd-Dewhurst §10).
    recommendation : str
        Human-readable moldability advice.
    wall_thickness : float
        The nominal wall thickness used for the check.
    """

    face_ids: List[int]
    diameter: float
    height: float
    base_face_id: Optional[int]
    moldability_valid: bool
    recommendation: str
    wall_thickness: float = 2.0


@dataclass
class RibFeature:
    """A thin-wall rib detected in a moulded body.

    Attributes
    ----------
    face_ids : list[int]
        IDs of the B-rep faces belonging to this rib (two parallel planar wall
        faces plus any connected base face).
    thickness : float
        Rib wall thickness (perpendicular distance between the two planar
        faces), in model units.
    height : float
        Rib height (extent of the rib in the normal-to-base direction),
        in model units.
    base_face_id : int | None
        Face ID of the planar base face the rib protrudes from.
    moldability_valid : bool
        True iff thickness / wall_thickness <= 0.6  (Boothroyd-Dewhurst §10).
    wall_thickness : float
        The nominal wall thickness used for the check.
    """

    face_ids: List[int]
    thickness: float
    height: float
    base_face_id: Optional[int]
    moldability_valid: bool
    wall_thickness: float = 2.0


# ---------------------------------------------------------------------------
# detect_bosses
# ---------------------------------------------------------------------------


def detect_bosses(
    body: Body,
    wall_thickness: float = 2.0,
) -> List[BossFeature]:
    """Detect cylindrical boss features in a B-rep body.

    Algorithm (Boothroyd-Dewhurst 2002 §10 + Liang-Wang 2014 heuristics)
    -----------------------------------------------------------------------
    1. Build adjacency map for all faces.
    2. For each convex cylinder-like face (outward normal away from axis):
       a. Identify adjacent planar faces (cap and base).
       b. Measure diameter = 2 × radius.
       c. Estimate height from cap-plane projections along the cylinder axis.
       d. Apply moldability rule: diameter / wall_thickness >= 2.5.
       e. Emit a BossFeature record.

    Parameters
    ----------
    body : Body
        A kerf B-rep body containing the moulded part geometry.
    wall_thickness : float
        Nominal base wall thickness in model units (default 2.0 mm).

    Returns
    -------
    list[BossFeature]
        One entry per detected boss.  Empty list if none found.
    """
    wall_thickness = float(wall_thickness)
    adj = _build_adjacency(body)
    by_id = _face_by_id(body)

    bosses: List[BossFeature] = []
    claimed: Set[int] = set()

    for face in body.all_faces():
        if face.id in claimed:
            continue
        if not _is_cylinder_like(face):
            continue

        # Convex cylinder: normal points away from axis (concavity < 0)
        concavity = _cylinder_concavity(face)
        if concavity >= 0.0:
            continue  # concave = hole, not a boss

        # Gather adjacent planar faces
        neighbor_ids = adj.get(face.id, set())
        neighbor_faces = [by_id[nid] for nid in neighbor_ids if nid in by_id]
        planar_neighbors = [f for f in neighbor_faces if _is_plane(f)]

        if not planar_neighbors:
            continue  # floating cylinder: not a boss

        r = _cyl_radius(face)
        diameter = 2.0 * r
        height = _cyl_height_from_adjacent_planes(face, planar_neighbors)
        base_face = _identify_base_face(face, planar_neighbors, adj)
        base_face_id = base_face.id if base_face is not None else None

        # Boothroyd-Dewhurst §10 boss rule
        ratio = diameter / wall_thickness if wall_thickness > 0 else 0.0
        valid = ratio >= _BOSS_RATIO_MIN

        if valid:
            rec = (
                f"Boss OK: diameter/wall = {ratio:.2f} >= {_BOSS_RATIO_MIN}. "
                "Ensure boss height <= 5× base diameter for stability."
            )
        else:
            rec = (
                f"Sink-mark risk: diameter/wall = {ratio:.2f} < {_BOSS_RATIO_MIN}. "
                f"Increase boss diameter to >= {_BOSS_RATIO_MIN * wall_thickness:.2f} "
                f"or reduce nominal wall thickness to <= {diameter / _BOSS_RATIO_MIN:.2f}."
            )

        claimed.add(face.id)
        bosses.append(
            BossFeature(
                face_ids=[face.id],
                diameter=diameter,
                height=height,
                base_face_id=base_face_id,
                moldability_valid=valid,
                recommendation=rec,
                wall_thickness=wall_thickness,
            )
        )

    return bosses


# ---------------------------------------------------------------------------
# detect_ribs
# ---------------------------------------------------------------------------


def detect_ribs(
    body: Body,
    wall_thickness: float = 2.0,
) -> List[RibFeature]:
    """Detect thin-wall rib features in a B-rep body.

    Algorithm (Boothroyd-Dewhurst 2002 §10 + Liang-Wang 2014)
    -----------------------------------------------------------
    A rib is a pair of parallel planar faces separated by a thickness
    < 0.6 × wall_thickness, both connected to a common base face that is
    perpendicular to the rib walls.

    1. Build adjacency map.
    2. For each pair of planar faces that are:
       (a) parallel to each other (normals anti-parallel ± 10°), AND
       (b) share at least one common planar neighbor (the rib base), AND
       (c) their perpendicular separation < 2 × wall_thickness (thin wall),
       emit a RibFeature.
    3. Apply moldability rule: thickness / wall_thickness <= 0.6.

    Parameters
    ----------
    body : Body
        A kerf B-rep body.
    wall_thickness : float
        Nominal base wall thickness (default 2.0 mm).

    Returns
    -------
    list[RibFeature]
        One entry per detected rib pair.  Empty list if none found.
    """
    wall_thickness = float(wall_thickness)
    adj = _build_adjacency(body)
    by_id = _face_by_id(body)

    planar_faces = [f for f in body.all_faces() if _is_plane(f)]

    ribs: List[RibFeature] = []
    claimed_pairs: Set[frozenset] = set()

    for i, fa in enumerate(planar_faces):
        na = _plane_normal_vec(fa)
        neighbors_a = adj.get(fa.id, set())

        for fb in planar_faces[i + 1:]:
            pair_key = frozenset([fa.id, fb.id])
            if pair_key in claimed_pairs:
                continue

            # Must be parallel (normals anti-parallel)
            if not _are_parallel_planes(fa, fb):
                continue

            # Compute separation
            thickness = _thin_wall_pair_thickness(fa, fb)

            # Filter: thin wall = thickness < 2 × wall_thickness
            if thickness <= 0.0 or thickness > 2.0 * wall_thickness:
                continue

            # Must share a common adjacent planar face (the base)
            neighbors_b = adj.get(fb.id, set())
            common_neighbors = (neighbors_a | {fa.id}) & (neighbors_b | {fb.id})
            # Remove the pair itself
            common_neighbors.discard(fa.id)
            common_neighbors.discard(fb.id)

            # Look for a base: a shared planar neighbor perpendicular to these walls
            base_face: Optional[Face] = None
            for nid in common_neighbors:
                nf = by_id.get(nid)
                if nf is None or not _is_plane(nf):
                    continue
                nn = _plane_normal_vec(nf)
                # base normal should be perpendicular to rib wall normals
                cos_perp = abs(float(np.dot(na, nn)))
                if cos_perp < math.cos(math.radians(70.0)):  # ~20–90° range accepted
                    base_face = nf
                    break

            # Rib height: extent of the rib walls along the base normal
            if base_face is not None:
                base_n = _plane_normal_vec(base_face)
                base_origin = np.asarray(base_face.surface.origin, dtype=float)  # type: ignore[union-attr]
                # Project rib face origins onto the base normal
                orig_a = np.asarray(fa.surface.origin, dtype=float)  # type: ignore[union-attr]
                orig_b_pt = np.asarray(fb.surface.origin, dtype=float)  # type: ignore[union-attr]
                h_a = abs(float(np.dot(orig_a - base_origin, base_n)))
                h_b = abs(float(np.dot(orig_b_pt - base_origin, base_n)))
                height = max(h_a, h_b)
            else:
                # Fall back to z-range of the thinner face
                z_lo, z_hi = _sample_face_z_range(fa)
                height = abs(z_hi - z_lo)

            ratio = thickness / wall_thickness if wall_thickness > 0 else 0.0
            valid = ratio <= _RIB_RATIO_MAX

            claimed_pairs.add(pair_key)
            ribs.append(
                RibFeature(
                    face_ids=[fa.id, fb.id],
                    thickness=thickness,
                    height=height,
                    base_face_id=base_face.id if base_face else None,
                    moldability_valid=valid,
                    wall_thickness=wall_thickness,
                )
            )

    return ribs


# ---------------------------------------------------------------------------
# detect_undercuts_for_features
# ---------------------------------------------------------------------------


def detect_undercuts_for_features(
    body: Body,
    pull_direction: Union[Sequence[float], np.ndarray],
) -> dict:
    """Detect undercut faces using the Wave 4T parting-line module.

    Thin wrapper around :func:`~kerf_cad_core.geom.mold.undercut_faces`
    (GK-121) for use in moldability scoring.

    Parameters
    ----------
    body : Body
        The B-rep body to analyse.
    pull_direction : array-like of 3 floats
        Mould pull/demould direction vector.

    Returns
    -------
    dict
        Same structure as ``mold.undercut_faces``:
        ``{undercut_faces: [...], parting_faces: [...], clear_faces: [...],
        summary: {undercut: int, parting: int, clear: int}}``.
        Returns a safe empty dict if mold module unavailable.
    """
    try:
        from kerf_cad_core.geom.mold import undercut_faces
        return undercut_faces(body, pull_direction)
    except ImportError:
        return {
            "undercut_faces": [],
            "parting_faces": [],
            "clear_faces": [],
            "summary": {"undercut": 0, "parting": 0, "clear": 0},
        }


# ---------------------------------------------------------------------------
# moldability_score
# ---------------------------------------------------------------------------

# Material-specific minimum wall thickness guidelines (mm) per Boothroyd-Dewhurst
_MATERIAL_MIN_WALL: Dict[str, float] = {
    "abs": 1.5,
    "pp": 0.8,
    "pc": 2.5,
    "pe": 1.0,
    "ps": 1.5,
    "pom": 1.5,
    "pa": 1.5,
    "pbt": 1.5,
}


def moldability_score(
    body: Body,
    material: str = "abs",
    wall_thickness: float = 2.0,
    pull_direction: Optional[Union[Sequence[float], np.ndarray]] = None,
) -> Dict[str, Any]:
    """Composite moldability index for injection-moulded parts.

    Combines Boothroyd-Dewhurst §10 boss/rib rules, undercut count, wall
    thickness range, and draft angles into a single [0, 100] score.

    Scoring breakdown (maximum contribution)
    -----------------------------------------
    * Boss violations:    up to −10 per violation   (max −30 capped)
    * Rib violations:     up to −10 per violation   (max −30 capped)
    * Undercut count:     up to −10 per undercut     (max −20 capped)
    * Wall uniformity:    −5 if range > 3× min wall (sink-mark risk)
    * Draft presence:     −5 if average draft < 0.5°

    Parameters
    ----------
    body : Body
        The B-rep body to analyse.
    material : str
        Material code (e.g. 'abs', 'pp', 'pc'). Used for min-wall lookup.
    wall_thickness : float
        Nominal wall thickness in model units.
    pull_direction : array-like of 3 floats, optional
        Mould pull direction for undercut analysis. Defaults to [0, 0, 1].

    Returns
    -------
    dict with keys:
        score            : float in [0, 100]
        boss_violations  : int — number of bosses failing the D/W >= 2.5 rule
        rib_violations   : int — number of ribs failing the T/W <= 0.6 rule
        undercut_count   : int — number of undercut faces
        recommendations  : list[str] — actionable advice items
        boss_features    : list[dict] — serialised BossFeature records
        rib_features     : list[dict] — serialised RibFeature records
        material         : str
        wall_thickness   : float
    """
    if pull_direction is None:
        pull_direction = [0.0, 0.0, 1.0]

    recommendations: List[str] = []

    # --- Boss analysis ---
    bosses = detect_bosses(body, wall_thickness=wall_thickness)
    boss_violations = sum(1 for b in bosses if not b.moldability_valid)
    for b in bosses:
        if not b.moldability_valid:
            recommendations.append(b.recommendation)

    # --- Rib analysis ---
    ribs = detect_ribs(body, wall_thickness=wall_thickness)
    rib_violations = sum(1 for r in ribs if not r.moldability_valid)
    for r in ribs:
        if not r.moldability_valid:
            recommendations.append(
                f"Rib sink-mark risk: thickness/wall = "
                f"{r.thickness / wall_thickness:.2f} > {_RIB_RATIO_MAX}. "
                f"Reduce rib thickness to <= {_RIB_RATIO_MAX * wall_thickness:.2f}."
            )

    # --- Undercut analysis ---
    undercut_result = detect_undercuts_for_features(body, pull_direction)
    undercut_count = int(
        undercut_result.get("summary", {}).get("undercut", 0)
    )
    if undercut_count > 0:
        recommendations.append(
            f"{undercut_count} undercut face(s) detected along pull direction "
            f"{list(pull_direction)}. Add side-actions or redesign geometry."
        )

    # --- Wall thickness uniformity ---
    wall_penalty = 0.0
    try:
        from kerf_cad_core.geom.wall_thickness import wall_thickness_map
        wt_result = wall_thickness_map(body, n_samples=64)
        if wt_result and "min_thickness" in wt_result:
            t_min = float(wt_result["min_thickness"])
            # Use heatmap range if available
            heatmap = wt_result.get("heatmap_array")
            if heatmap is not None and len(heatmap) > 0:
                t_max = float(np.max(heatmap))
                if t_min > 1e-9 and t_max / t_min > 3.0:
                    wall_penalty = 5.0
                    recommendations.append(
                        f"Wall thickness variation too high: "
                        f"max/min = {t_max / t_min:.1f}× (target ≤ 3×). "
                        "Uniform wall thickness reduces warp and cycle time."
                    )
    except (ImportError, Exception):
        pass  # non-fatal: skip wall-uniformity term

    # --- Draft angle check ---
    draft_penalty = 0.0
    try:
        from kerf_cad_core.geom.surface_analysis import draft_angle_analysis
        from kerf_cad_core.geom.nurbs import NurbsSurface

        all_draft_angles: List[float] = []
        pull_hat = _unit(np.asarray(pull_direction, dtype=float).ravel()[:3])
        for face in body.all_faces():
            srf = face.surface
            if not isinstance(srf, NurbsSurface):
                continue
            result = draft_angle_analysis(srf, pull_hat.tolist(), 8, 8, _DRAFT_MIN_DEG)
            if result.get("ok"):
                # result["per_sample"] is list of dicts with "angle_deg"
                for s in result.get("per_sample", []):
                    all_draft_angles.append(float(s.get("angle_deg", 0.0)))

        if all_draft_angles:
            avg_draft = float(np.mean(all_draft_angles))
            if avg_draft < _DRAFT_MIN_DEG:
                draft_penalty = 5.0
                recommendations.append(
                    f"Average draft angle {avg_draft:.2f}° < {_DRAFT_MIN_DEG}°. "
                    "Increase draft angles to ease part ejection."
                )
    except (ImportError, Exception):
        pass  # non-fatal: analytic surfaces don't use draft_angle_analysis

    # --- Material wall guidance ---
    mat_lower = material.lower().strip()
    min_wall = _MATERIAL_MIN_WALL.get(mat_lower, 1.5)
    if wall_thickness < min_wall:
        recommendations.append(
            f"Nominal wall {wall_thickness:.2f} < minimum for {mat_lower.upper()} "
            f"({min_wall:.2f}). Risk of incomplete fill / short shot."
        )

    # --- Composite score ---
    score = 100.0
    score -= min(boss_violations * 10.0, 30.0)
    score -= min(rib_violations * 10.0, 30.0)
    score -= min(undercut_count * 10.0, 20.0)
    score -= wall_penalty
    score -= draft_penalty
    score = max(0.0, min(100.0, score))

    return {
        "score": float(score),
        "boss_violations": boss_violations,
        "rib_violations": rib_violations,
        "undercut_count": undercut_count,
        "recommendations": recommendations,
        "boss_features": [
            {
                "face_ids": b.face_ids,
                "diameter": b.diameter,
                "height": b.height,
                "base_face_id": b.base_face_id,
                "moldability_valid": b.moldability_valid,
                "recommendation": b.recommendation,
            }
            for b in bosses
        ],
        "rib_features": [
            {
                "face_ids": r.face_ids,
                "thickness": r.thickness,
                "height": r.height,
                "base_face_id": r.base_face_id,
                "moldability_valid": r.moldability_valid,
            }
            for r in ribs
        ],
        "material": mat_lower,
        "wall_thickness": wall_thickness,
    }


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors solid_features.py / trim_curve.py)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ── brep_detect_features ──────────────────────────────────────────────

    _detect_features_spec = ToolSpec(
        name="brep_detect_features",
        description=(
            "Detect manufacturing features (bosses and ribs) in a B-rep body "
            "for injection-moulding analysis (Boothroyd-Dewhurst 2002 §10).\n"
            "\n"
            "Bosses are cylindrical protrusions for screw inserts. Valid if "
            "diameter / wall_thickness >= 2.5. Ribs are thin stiffening walls; "
            "valid if rib_thickness / wall_thickness <= 0.6.\n"
            "\n"
            "Returns: ok, bosses (list of boss records), ribs (list of rib records), "
            "boss_count, rib_count, boss_violations, rib_violations.\n"
            "Errors: {ok:false, reason}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_id": {
                    "type": "string",
                    "description": "Project body/solid ID to analyse.",
                },
                "wall_thickness": {
                    "type": "number",
                    "description": (
                        "Nominal base wall thickness in mm (default 2.0). "
                        "Used for boss diameter/wall and rib thickness/wall checks."
                    ),
                },
            },
            "required": ["body_id"],
        },
    )

    @register(_detect_features_spec)
    async def run_brep_detect_features(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_id = a.get("body_id")
        if not body_id:
            return err_payload("body_id is required", "BAD_ARGS")

        wt = float(a.get("wall_thickness", 2.0))

        try:
            body = ctx.get_body(body_id)  # type: ignore[attr-defined]
        except Exception as exc:
            return err_payload(f"could not load body: {exc}", "NOT_FOUND")

        try:
            bosses = detect_bosses(body, wall_thickness=wt)
            ribs = detect_ribs(body, wall_thickness=wt)
        except Exception as exc:
            return err_payload(f"feature detection failed: {exc}", "OP_FAILED")

        return ok_payload({
            "boss_count": len(bosses),
            "rib_count": len(ribs),
            "boss_violations": sum(1 for b in bosses if not b.moldability_valid),
            "rib_violations": sum(1 for r in ribs if not r.moldability_valid),
            "bosses": [
                {
                    "face_ids": b.face_ids,
                    "diameter": b.diameter,
                    "height": b.height,
                    "base_face_id": b.base_face_id,
                    "moldability_valid": b.moldability_valid,
                    "recommendation": b.recommendation,
                }
                for b in bosses
            ],
            "ribs": [
                {
                    "face_ids": r.face_ids,
                    "thickness": r.thickness,
                    "height": r.height,
                    "base_face_id": r.base_face_id,
                    "moldability_valid": r.moldability_valid,
                }
                for r in ribs
            ],
        })

    # ── brep_moldability_score ────────────────────────────────────────────

    _moldability_spec = ToolSpec(
        name="brep_moldability_score",
        description=(
            "Compute a composite moldability score [0–100] for an injection-"
            "moulded B-rep body.\n"
            "\n"
            "Combines: boss violations (−10 each, max −30), rib violations "
            "(−10 each, max −30), undercut count (−10 each, max −20), "
            "wall-uniformity penalty (−5), draft-angle penalty (−5).\n"
            "\n"
            "Returns: ok, score, boss_violations, rib_violations, undercut_count, "
            "recommendations (actionable list), boss_features, rib_features.\n"
            "Errors: {ok:false, reason}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_id": {
                    "type": "string",
                    "description": "Project body/solid ID to score.",
                },
                "material": {
                    "type": "string",
                    "description": (
                        "Material code: abs (default), pp, pc, pe, ps, pom, pa, pbt."
                    ),
                },
                "wall_thickness": {
                    "type": "number",
                    "description": "Nominal base wall thickness in mm (default 2.0).",
                },
                "pull_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "3-vector mould pull direction (default [0, 0, 1]). "
                        "Used for undercut detection."
                    ),
                },
            },
            "required": ["body_id"],
        },
    )

    @register(_moldability_spec)
    async def run_brep_moldability_score(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_id = a.get("body_id")
        if not body_id:
            return err_payload("body_id is required", "BAD_ARGS")

        try:
            body = ctx.get_body(body_id)  # type: ignore[attr-defined]
        except Exception as exc:
            return err_payload(f"could not load body: {exc}", "NOT_FOUND")

        wt = float(a.get("wall_thickness", 2.0))
        mat = str(a.get("material", "abs"))
        pull = a.get("pull_direction", [0.0, 0.0, 1.0])

        try:
            result = moldability_score(
                body, material=mat, wall_thickness=wt, pull_direction=pull
            )
        except Exception as exc:
            return err_payload(f"moldability scoring failed: {exc}", "OP_FAILED")

        return ok_payload(result)
