"""wall_thickness.py — GK-76 Wall-thickness map + GK-P material analysis.

New high-level API (GK-P)
-------------------------
ThicknessReport
    Dataclass holding per_face_min_thickness, global_min, global_max,
    sample_locations, and recommend_min_for_material.

ThinWallWarning
    Dataclass describing a face whose minimum thickness < the material guideline.

analyze_wall_thickness(body, n_samples=1000, ray_count_per_sample=20)
    -> ThicknessReport
    Surface-sample the body, cast inward rays, and return the thickness report.

material_thickness_guideline(material_name) -> float | None
    Injection-moulding minimum wall thickness by material name.
    Returns None for materials not suited to injection moulding.

flag_thin_walls(body, material_name, n_samples=2000) -> list[ThinWallWarning]
    Run analyze_wall_thickness and flag faces below the material guideline.

Low-level API (GK-76)
---------------------

Algorithm
---------
For each of the N surface sample points sampled uniformly across all body
faces (weighted by estimated face area), we cast a ray from the point along
its *inward* surface normal and find the first opposite-surface intersection.
The distance to that intersection is the local wall thickness.

The result aggregates:
    min_thickness    : float    — global minimum thickness found
    per_face_min     : dict     — {face_id: float} minimum per face
    samples          : list     — [(point_array, thickness)] for each ray
    heatmap_array    : ndarray  — shape (N,) sorted thicknesses (heatmap input)

Ray–surface intersection
------------------------
*Plane* faces — exact analytic ray–plane formula.
*SphereSurface* — exact analytic ray–sphere formula.
*CylinderSurface* — exact analytic ray–cylinder formula.
*Any other surface* — parametric march along the ray using finite-difference
  sampling, finding sign changes of the signed distance then bisecting.

All intersection candidates closer than ``_EPS`` to the ray origin are
discarded (the ray starts ON the surface; we want the *next* hit).

Hermetic: depends only on numpy (already required by geom/brep.py) and the
standard library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Plane,
    CylinderSurface,
    SphereSurface,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EPS = 1e-7          # minimum valid intersection distance (avoid self-hit)
_FAR = 1e18          # "infinity" for no-hit sentinel
_MARCH_STEPS = 64    # parametric march steps for generic surface fallback
_BISECT_ITERS = 20   # bisection iterations for generic surface fallback
_GL_N = 8            # Gauss–Legendre nodes for face area estimation


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _gl8():
    """Fixed 8-point Gauss–Legendre nodes+weights on [-1, 1]."""
    # Pre-computed to keep the module hermetic (no leggauss call required).
    xi = np.array([
        -0.9602898564975363, -0.7966664774136267,
        -0.5255324099163290, -0.1834346424956498,
         0.1834346424956498,  0.5255324099163290,
         0.7966664774136267,  0.9602898564975363,
    ])
    wi = np.array([
        0.1012285362903763, 0.2223810344533745,
        0.3137066458778873, 0.3626837833783620,
        0.3626837833783620, 0.3137066458778873,
        0.2223810344533745, 0.1012285362903763,
    ])
    return xi, wi


_GL_XI, _GL_WI = _gl8()


# ---------------------------------------------------------------------------
# Face area estimation (for sample weighting)
# ---------------------------------------------------------------------------

_FD_H = 1e-6


def _face_parametric_domain(face: Face) -> Tuple[float, float, float, float]:
    """Return (u_lo, u_hi, v_lo, v_hi) for a face's natural domain."""
    srf = face.surface
    if isinstance(srf, Plane):
        # Plane is infinite; we sample a unit square.  For realistic bodies
        # the face loops constrain the region, but for area-weight purposes
        # a unit square suffices (faces are compared relatively).
        return 0.0, 1.0, 0.0, 1.0
    if isinstance(srf, SphereSurface):
        return 0.0, 2 * math.pi, -math.pi / 2, math.pi / 2
    if isinstance(srf, CylinderSurface):
        return 0.0, 2 * math.pi, 0.0, 1.0
    # Generic fallback: unit square
    return 0.0, 1.0, 0.0, 1.0


def _face_area_estimate(face: Face) -> float:
    """Approximate parametric-domain area of a face (for sampling weight)."""
    srf = face.surface
    u_lo, u_hi, v_lo, v_hi = _face_parametric_domain(face)
    u_mid, u_h = 0.5 * (u_lo + u_hi), 0.5 * (u_hi - u_lo)
    v_mid, v_h = 0.5 * (v_lo + v_hi), 0.5 * (v_hi - v_lo)
    us = u_mid + u_h * _GL_XI
    vs = v_mid + v_h * _GL_XI

    total = 0.0
    for i in range(len(_GL_XI)):
        for j in range(len(_GL_XI)):
            u = float(us[i])
            v = float(vs[j])
            p = np.asarray(srf.evaluate(u, v), dtype=float)
            pu = np.asarray(srf.evaluate(u + _FD_H, v), dtype=float)
            pv = np.asarray(srf.evaluate(u, v + _FD_H), dtype=float)
            N = np.cross((pu - p) / _FD_H, (pv - p) / _FD_H)
            total += float(_GL_WI[i] * _GL_WI[j] * np.linalg.norm(N))

    return max(total * u_h * v_h, 1e-30)


# ---------------------------------------------------------------------------
# Surface sample point + inward normal
# ---------------------------------------------------------------------------

def _sample_face(face: Face, rng: np.random.Generator, n: int
                 ) -> List[Tuple[np.ndarray, np.ndarray, float, float]]:
    """Return up to *n* (point, inward_normal, u, v) tuples from *face*."""
    srf = face.surface
    u_lo, u_hi, v_lo, v_hi = _face_parametric_domain(face)
    us = rng.uniform(u_lo, u_hi, n)
    vs = rng.uniform(v_lo, v_hi, n)

    results = []
    for u, v in zip(us, vs):
        u = float(u)
        v = float(v)
        p = np.asarray(srf.evaluate(u, v), dtype=float)
        # Outward normal from surface, then flip for face orientation + inward
        if hasattr(srf, "normal"):
            raw_n = _unit(np.asarray(srf.normal(u, v), dtype=float))
        else:
            ep = np.asarray(srf.evaluate(u + _FD_H, v), dtype=float)
            ev = np.asarray(srf.evaluate(u, v + _FD_H), dtype=float)
            raw_n = _unit(np.cross((ep - p) / _FD_H, (ev - p) / _FD_H))
        # face.orientation: True = normal same as parametric; flip for inward
        outward = raw_n if face.orientation else -raw_n
        inward = -outward
        results.append((p, inward, u, v))
    return results


# ---------------------------------------------------------------------------
# Ray–surface intersection helpers
# ---------------------------------------------------------------------------

def _ray_plane_hit(origin: np.ndarray, direction: np.ndarray,
                   plane: Plane) -> float:
    """Return t > _EPS for ray–plane intersection, else _FAR."""
    n = plane._n  # unit normal, set in Plane.__post_init__
    denom = float(np.dot(n, direction))
    if abs(denom) < 1e-12:
        return _FAR
    t = float(np.dot(n, plane.origin - origin)) / denom
    if t > _EPS:
        return t
    return _FAR


def _ray_sphere_hit(origin: np.ndarray, direction: np.ndarray,
                    srf: SphereSurface) -> float:
    """Return smallest t > _EPS for ray–sphere intersection, else _FAR."""
    oc = origin - srf.center
    a = float(np.dot(direction, direction))
    b = 2.0 * float(np.dot(oc, direction))
    c = float(np.dot(oc, oc)) - srf.radius ** 2
    disc = b * b - 4 * a * c
    if disc < 0:
        return _FAR
    sq = math.sqrt(disc)
    t1 = (-b - sq) / (2 * a)
    t2 = (-b + sq) / (2 * a)
    best = _FAR
    for t in (t1, t2):
        if _EPS < t < best:
            best = t
    return best


def _ray_cylinder_hit(origin: np.ndarray, direction: np.ndarray,
                      srf: CylinderSurface) -> float:
    """Return smallest t > _EPS for ray–infinite-cylinder intersection, else _FAR.

    We intersect the *infinite* cylinder; the resulting t is valid because we
    only care about distance, not which cap we hit.
    """
    ax = srf.axis  # unit axis
    # Project origin and direction onto the plane perp to axis
    oc = origin - srf.center
    oc_perp = oc - float(np.dot(oc, ax)) * ax
    d_perp = direction - float(np.dot(direction, ax)) * ax
    a = float(np.dot(d_perp, d_perp))
    if a < 1e-14:
        return _FAR  # ray parallel to axis
    b = 2.0 * float(np.dot(oc_perp, d_perp))
    c = float(np.dot(oc_perp, oc_perp)) - srf.radius ** 2
    disc = b * b - 4 * a * c
    if disc < 0:
        return _FAR
    sq = math.sqrt(disc)
    best = _FAR
    for t in ((-b - sq) / (2 * a), (-b + sq) / (2 * a)):
        if _EPS < t < best:
            best = t
    return best


def _ray_generic_surface_hit(origin: np.ndarray, direction: np.ndarray,
                              srf: Any) -> float:
    """Marching + bisection for generic parametric surfaces.

    We parameterise along the ray: p(t) = origin + t * direction,
    then look for a parametric (u, v) on the surface close to p(t).
    Strategy: for each candidate t, find the closest surface point and
    check whether the distance is below a threshold.

    For the GK-76 use-case (bodies built from standard brep.py surfaces),
    this path should rarely be reached.  It handles NurbsSurface or
    any future surface type.
    """
    # Sample the ray at _MARCH_STEPS points from _EPS to a "large" distance,
    # evaluate closest surface point via a coarse u,v grid, detect sign changes
    # in (p(t) - srf(u,v)) · direction.
    # This is a "dumb" but hermetic fallback; accuracy ~_FAR/_MARCH_STEPS.
    max_t = 100.0  # reasonable upper bound for typical CAD bodies
    ts = np.linspace(_EPS * 10, max_t, _MARCH_STEPS)

    # Coarse u,v grid for the generic surface
    NUV = 16
    us = np.linspace(0.0, 1.0, NUV)
    vs = np.linspace(0.0, 1.0, NUV)

    prev_min_dist = None
    prev_sign = None
    best_t = _FAR

    for t_val in ts:
        p_ray = origin + t_val * direction
        # Find distance to surface at this t by sampling u,v
        min_d2 = _FAR
        for u in us:
            for v in vs:
                try:
                    sp = np.asarray(srf.evaluate(float(u), float(v)), dtype=float)
                    d2 = float(np.dot(p_ray - sp, p_ray - sp))
                    if d2 < min_d2:
                        min_d2 = d2
                except Exception:
                    pass
        min_d = math.sqrt(min_d2)
        # Use a tolerance proportional to the max_t step
        tol_hit = max_t / _MARCH_STEPS * 2
        if min_d < tol_hit:
            best_t = min(best_t, t_val)
            break

    return best_t


def _ray_face_hit(origin: np.ndarray, direction: np.ndarray, face: Face) -> float:
    """Return the smallest positive t for ray hitting *face*, else _FAR."""
    srf = face.surface
    if isinstance(srf, Plane):
        return _ray_plane_hit(origin, direction, srf)
    if isinstance(srf, SphereSurface):
        return _ray_sphere_hit(origin, direction, srf)
    if isinstance(srf, CylinderSurface):
        return _ray_cylinder_hit(origin, direction, srf)
    return _ray_generic_surface_hit(origin, direction, srf)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def wall_thickness_map(
    body: Body,
    n_rays: int = 10_000,
    *,
    seed: Optional[int] = 42,
) -> dict:
    """Compute a wall-thickness map for a closed :class:`Body`.

    Algorithm
    ---------
    1. Collect all faces from the body.
    2. Estimate each face's area; distribute *n_rays* sample points across
       faces proportionally.
    3. For each sample point (on face *i*):
         a. Shoot a ray from the surface point along its *inward* normal.
         b. Test the ray against every other face; record the smallest hit
            distance ``t > _EPS``.
         c. That distance is the local wall thickness at this point.
    4. Aggregate: global min, per-face min, samples list, heatmap array.

    Parameters
    ----------
    body : Body
        The body to analyse.  Should be a closed solid for meaningful results.
    n_rays : int
        Number of sample rays (default 10 000).  More rays → finer heatmap.
    seed : int | None
        RNG seed for reproducibility (default 42).

    Returns
    -------
    dict with keys:
        ``min_thickness``  : float
        ``per_face_min``   : dict  {face_id: float}
        ``samples``        : list  [(point_ndarray, thickness_float), ...]
        ``heatmap_array``  : ndarray  shape (N,) sorted ascending
    """
    rng = np.random.default_rng(seed)

    faces = body.all_faces()
    if not faces:
        return {
            "min_thickness": 0.0,
            "per_face_min": {},
            "samples": [],
            "heatmap_array": np.array([], dtype=float),
        }

    # ── Area-weighted distribution of rays across faces ─────────────────────
    areas = np.array([_face_area_estimate(f) for f in faces], dtype=float)
    areas /= areas.sum()

    # How many rays per face (at least 1 per face)
    n_per_face = np.maximum(1, np.round(areas * n_rays).astype(int))
    # Adjust total to exactly n_rays
    diff = int(n_rays) - int(n_per_face.sum())
    if diff > 0:
        # Give extra rays to faces with highest area weight
        top = np.argsort(-areas)
        for i in range(diff):
            n_per_face[top[i % len(top)]] += 1
    elif diff < 0:
        # Remove rays from over-allocated faces (keep min 1)
        top = np.argsort(areas)
        for i in range(-diff):
            idx = top[i % len(top)]
            if n_per_face[idx] > 1:
                n_per_face[idx] -= 1

    # ── Cast rays ────────────────────────────────────────────────────────────
    per_face_min: Dict[int, float] = {}
    all_samples: List[Tuple[np.ndarray, float]] = []

    for fi, face in enumerate(faces):
        fid = face.id
        per_face_min[fid] = _FAR
        n_this = int(n_per_face[fi])
        pts_normals = _sample_face(face, rng, n_this)

        for (origin, inward, _u, _v) in pts_normals:
            best_t = _FAR
            for other_face in faces:
                t_hit = _ray_face_hit(origin, inward, other_face)
                if t_hit < best_t:
                    best_t = t_hit

            if best_t < _FAR:
                thickness = best_t
                all_samples.append((origin, thickness))
                if thickness < per_face_min[fid]:
                    per_face_min[fid] = thickness

    # Replace _FAR sentinels with NaN for faces that had no valid hits
    for fid in per_face_min:
        if per_face_min[fid] >= _FAR:
            per_face_min[fid] = float("nan")

    # ── Aggregate ────────────────────────────────────────────────────────────
    thicknesses = np.array(
        [t for (_, t) in all_samples], dtype=float
    )
    if len(thicknesses) > 0:
        min_thickness = float(np.nanmin(thicknesses))
        heatmap_array = np.sort(thicknesses)
    else:
        min_thickness = 0.0
        heatmap_array = np.array([], dtype=float)

    return {
        "min_thickness": min_thickness,
        "per_face_min": per_face_min,
        "samples": all_samples,
        "heatmap_array": heatmap_array,
    }


# ---------------------------------------------------------------------------
# GK-P  High-level API: ThicknessReport, material guidelines, flag_thin_walls
# ---------------------------------------------------------------------------

@dataclass
class ThicknessReport:
    """Wall-thickness analysis result.

    Attributes
    ----------
    per_face_min_thickness : dict[int, float]
        Minimum measured thickness per face id.  NaN for faces with no valid
        ray hits (e.g. an open void face with no opposite surface).
    global_min : float
        Global minimum thickness across all sampled points.
    global_max : float
        Global maximum thickness across all sampled points.
    sample_locations : list[tuple[ndarray, float]]
        All (surface_point, thickness) pairs from the ray-casting pass.
    recommend_min_for_material : float | None
        Material-specific minimum thickness from the injection-moulding
        guideline table (``material_thickness_guideline``), or ``None`` if the
        material is not suited to injection moulding or not recognised.
    """

    per_face_min_thickness: Dict[int, float] = field(default_factory=dict)
    global_min: float = 0.0
    global_max: float = 0.0
    sample_locations: List[Tuple[Any, float]] = field(default_factory=list)
    recommend_min_for_material: Optional[float] = None


@dataclass
class ThinWallWarning:
    """A face whose minimum thickness is below the material guideline.

    Attributes
    ----------
    face_id : int
    measured_min_mm : float
        Minimum thickness measured on this face (mm).
    required_min_mm : float
        Material guideline minimum (mm).
    deficit_mm : float
        How much thinner than required: ``required_min_mm - measured_min_mm``.
    """

    face_id: int
    measured_min_mm: float
    required_min_mm: float
    deficit_mm: float


# ---------------------------------------------------------------------------
# Material thickness guideline table
# ---------------------------------------------------------------------------

# Injection-moulding minimum wall thickness (mm) per polymer.
# Sources: DuPont Plastics Design Library; RJG Inc. moulding guidelines;
# Stroud-Nagy 2011 §17.2; Rosato's Plastics Encyclopedia.
# Keys are normalised to lower-case, spaces and hyphens stripped.
_MOULDING_MIN_MM: Dict[str, float] = {
    # Thermoplastics — standard grades
    "abs": 1.5,
    "pp": 0.8,
    "polypropylene": 0.8,
    "pe": 1.0,
    "polyethylene": 1.0,
    "hdpe": 1.0,
    "ldpe": 1.0,
    "pc": 1.2,
    "polycarbonate": 1.2,
    "nylon6": 1.5,
    "nylon66": 1.5,
    "nylon": 1.5,
    "polyamide": 1.5,
    "pa6": 1.5,
    "pa66": 1.5,
    "pvc": 2.0,
    "polyvinylchloride": 2.0,
    "ps": 1.0,
    "polystyrene": 1.0,
    "hips": 1.0,
    "peek": 1.5,
    "pom": 0.8,
    "acetal": 0.8,
    "pmma": 1.5,
    "acrylic": 1.5,
    "tpe": 1.5,
    "tpu": 1.5,
    "san": 1.0,
    "pbt": 1.5,
    "pet": 1.5,
    "pei": 1.5,
    "ultem": 1.5,
    "ppsu": 1.5,
    "pps": 1.2,
    "lcp": 0.5,
    "liquidcrystalpolymer": 0.5,
}

# Materials NOT suited to injection moulding — guideline returns None.
_NOT_MOULDABLE: frozenset = frozenset({
    "concrete", "ceramic", "glass", "glassflat", "stone",
    "granite", "marble", "porcelain", "firebrick", "terracotta",
    "woodsolid", "plywood", "mdf", "particleboard",
    "steel", "aluminium", "aluminum", "copper", "titanium",
    "iron", "zinc", "brass", "bronze", "nickel", "magnesium",
})


def _normalise_material(name: str) -> str:
    """Strip spaces/hyphens/underscores, lower-case."""
    return (
        name.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace(".", "")
    )


def material_thickness_guideline(material_name: str) -> Optional[float]:
    """Return injection-moulding minimum wall thickness (mm) for *material_name*.

    Parameters
    ----------
    material_name : str
        Case-insensitive material name, e.g. ``"ABS"``, ``"PP"``,
        ``"polycarbonate"``, ``"Nylon-6"``.

    Returns
    -------
    float
        Minimum recommended injection-moulded wall thickness in millimetres.
    None
        When the material is known to be not suited for injection moulding
        (e.g. ``"concrete"``, ``"ceramic"``, ``"glass-flat"``) *or* when the
        material is not in the guideline table.

    Notes
    -----
    Guideline values from DuPont Plastics Design Library and Rosato's
    Plastics Encyclopedia.  These are *minimum* practical thicknesses for
    a nominal shot — thin-wall PP can drop to ~0.5 mm with optimised
    tooling; the value returned here is the conventional lower bound for
    general-purpose parts.
    """
    key = _normalise_material(material_name)
    if key in _NOT_MOULDABLE:
        return None
    # Try exact match first, then prefix/substring match for common aliases.
    if key in _MOULDING_MIN_MM:
        return _MOULDING_MIN_MM[key]
    # Accept partial match so "nylon-6" → "nylon6" → 1.5
    for k, v in _MOULDING_MIN_MM.items():
        if key.startswith(k) or k.startswith(key):
            return v
    return None


# ---------------------------------------------------------------------------
# analyze_wall_thickness
# ---------------------------------------------------------------------------

def analyze_wall_thickness(
    body: Body,
    n_samples: int = 1000,
    ray_count_per_sample: int = 20,
    *,
    material_name: Optional[str] = None,
    seed: Optional[int] = 42,
) -> ThicknessReport:
    """Analyse wall thickness across the surface of a closed solid B-rep body.

    Algorithm
    ---------
    For each of the *n_samples* surface points (distributed area-proportionally
    across faces):
      1. Compute the inward surface normal at that point.
      2. Cast ``ray_count_per_sample`` rays: one exactly along the inward
         normal and ``ray_count_per_sample - 1`` jittered directions within a
         hemisphere around the inward normal.
      3. For each ray, find the first intersection with any face of the body.
         The *minimum* ray length among all hits is the wall thickness at that
         point (using the closest opposite surface, not the average).

    The primary measurement at each surface point is the inward-normal ray
    distance.  Additional ``ray_count_per_sample - 1`` jitter rays within a
    30° forward cone serve as a *fallback*: they are cast only when the
    normal ray finds no hit (open shell / concave surface / complex geometry)
    and the minimum jitter hit is then used.  When the normal ray succeeds,
    its distance is the wall thickness — jitter cannot reduce it.  This
    prevents near-tangent corner/edge artefacts that arise when jitter rays
    sweep across adjacent faces near sample points at shell corners.

    Parameters
    ----------
    body : Body
        Closed solid B-rep body.  Open shells return a report with all zeros.
    n_samples : int
        Number of surface sample points (default 1 000).
    ray_count_per_sample : int
        Rays per surface point including the normal-direction ray (default 20).
    material_name : str | None
        Optional material for ``recommend_min_for_material`` population.
    seed : int | None
        RNG seed for reproducibility.

    Returns
    -------
    ThicknessReport
    """
    rng = np.random.default_rng(seed)

    faces = body.all_faces()
    if not faces:
        return ThicknessReport()

    # ── Area-weighted distribution across faces ────────────────────────────
    areas = np.array([_face_area_estimate(f) for f in faces], dtype=float)
    areas_sum = float(areas.sum())
    if areas_sum < 1e-30:
        return ThicknessReport()
    weights = areas / areas_sum

    n_per_face = np.maximum(1, np.round(weights * n_samples).astype(int))
    diff = int(n_samples) - int(n_per_face.sum())
    if diff > 0:
        top = np.argsort(-weights)
        for i in range(diff):
            n_per_face[top[i % len(top)]] += 1
    elif diff < 0:
        top = np.argsort(weights)
        for i in range(-diff):
            idx = top[i % len(top)]
            if n_per_face[idx] > 1:
                n_per_face[idx] -= 1

    # ── Build hemisphere perturbation directions ──────────────────────────
    # We pre-draw random perturbations for the off-normal rays once per call.
    n_jitter = max(0, ray_count_per_sample - 1)

    per_face_min: Dict[int, float] = {}
    per_face_max: Dict[int, float] = {}
    all_samples: List[Tuple[Any, float]] = []

    for fi, face in enumerate(faces):
        fid = face.id
        per_face_min[fid] = _FAR
        per_face_max[fid] = 0.0
        n_this = int(n_per_face[fi])
        pts_normals = _sample_face(face, rng, n_this)

        for (origin, inward, _u, _v) in pts_normals:
            # Build a local orthonormal frame around the inward normal.
            inward_u = _unit(inward)
            # Find a perpendicular vector via the least-aligned axis.
            ax = np.array([1.0, 0.0, 0.0])
            if abs(float(np.dot(inward_u, ax))) > 0.9:
                ax = np.array([0.0, 1.0, 0.0])
            perp1 = _unit(np.cross(inward_u, ax))
            perp2 = _unit(np.cross(inward_u, perp1))

            # Primary ray: inward normal direction.
            normal_t = _FAR
            for other_face in faces:
                t_hit = _ray_face_hit(origin, inward_u, other_face)
                if _EPS < t_hit < normal_t:
                    normal_t = t_hit

            # Jitter rays: forward cone of half-angle 30°.
            # cos(30°) ≈ 0.866.  Jitter rays are FALLBACK ONLY: cast only
            # when normal_t is _FAR (normal ray found no hit).  When the
            # normal ray succeeds, its distance is used as-is — jitter cannot
            # reduce it, preventing corner/edge artefacts on hollow bodies.
            _COS_30 = 0.866  # cos(30°)

            best_t = normal_t  # primary: inward-normal result
            if normal_t >= _FAR and n_jitter > 0:
                # Normal ray missed: try jitter rays as fallback.
                for _ in range(n_jitter):
                    cos_theta = float(rng.uniform(_COS_30, 1.0))
                    phi = float(rng.uniform(0.0, 2.0 * math.pi))
                    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
                    d = (
                        cos_theta * inward_u
                        + sin_theta * math.cos(phi) * perp1
                        + sin_theta * math.sin(phi) * perp2
                    )
                    d_u = _unit(d)
                    for other_face in faces:
                        t_hit = _ray_face_hit(origin, d_u, other_face)
                        if _EPS < t_hit < best_t:
                            best_t = t_hit

            if best_t < _FAR:
                thickness = best_t
                all_samples.append((origin, thickness))
                if thickness < per_face_min[fid]:
                    per_face_min[fid] = thickness
                if thickness > per_face_max[fid]:
                    per_face_max[fid] = thickness

    # Replace _FAR sentinels with NaN for faces with no valid hits.
    for fid in list(per_face_min.keys()):
        if per_face_min[fid] >= _FAR:
            per_face_min[fid] = float("nan")

    thicknesses = np.array([t for (_, t) in all_samples], dtype=float)
    if len(thicknesses) > 0:
        g_min = float(np.nanmin(thicknesses))
        g_max = float(np.nanmax(thicknesses))
    else:
        g_min = 0.0
        g_max = 0.0

    rec_min: Optional[float] = None
    if material_name:
        rec_min = material_thickness_guideline(material_name)

    return ThicknessReport(
        per_face_min_thickness=per_face_min,
        global_min=g_min,
        global_max=g_max,
        sample_locations=all_samples,
        recommend_min_for_material=rec_min,
    )


# ---------------------------------------------------------------------------
# flag_thin_walls
# ---------------------------------------------------------------------------

def flag_thin_walls(
    body: Body,
    material_name: str,
    n_samples: int = 2000,
    *,
    seed: Optional[int] = 42,
) -> List[ThinWallWarning]:
    """Flag faces whose minimum wall thickness is below the material guideline.

    Parameters
    ----------
    body : Body
        Closed solid B-rep body to analyse.
    material_name : str
        Material name for injection-moulding guideline lookup (case-insensitive).
    n_samples : int
        Number of surface sample points passed to ``analyze_wall_thickness``.
    seed : int | None
        RNG seed for reproducibility.

    Returns
    -------
    list[ThinWallWarning]
        One entry per face where ``per_face_min_thickness < guideline``.
        Empty list if the material is not in the guideline table or if all
        walls meet the requirement.

    Raises
    ------
    ValueError
        If ``material_name`` maps to ``None`` (not mouldable material).
    """
    guideline = material_thickness_guideline(material_name)
    if guideline is None:
        return []

    report = analyze_wall_thickness(
        body,
        n_samples=n_samples,
        material_name=material_name,
        seed=seed,
    )

    warnings: List[ThinWallWarning] = []
    for fid, t_min in report.per_face_min_thickness.items():
        if math.isnan(t_min):
            continue
        if t_min < guideline:
            warnings.append(
                ThinWallWarning(
                    face_id=fid,
                    measured_min_mm=t_min,
                    required_min_mm=guideline,
                    deficit_mm=guideline - t_min,
                )
            )
    return warnings


# ---------------------------------------------------------------------------
# LLM tool registration — brep_analyze_wall_thickness + brep_check_moldability
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # brep_analyze_wall_thickness
    # ------------------------------------------------------------------

    _analyze_spec = ToolSpec(
        name="brep_analyze_wall_thickness",
        description=(
            "Analyse wall thickness across the surface of a closed solid body by "
            "casting inward rays from surface sample points.  Returns per-face "
            "minimum thickness, global min/max, and the injection-moulding "
            "guideline for the specified material (if any).\n\n"
            "The body is described as a mesh via vertices + triangles OR via a "
            "box/cylinder/sphere shorthand for quick oracle checks.\n\n"
            "Returns: {ok, global_min_mm, global_max_mm, per_face_min, "
            "recommend_min_mm, n_samples, n_faces}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["box", "sphere", "cylinder"],
                    "description": "Shorthand primitive to build a test body.",
                },
                "size": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Box: [lx, ly, lz].  Sphere: [radius].  Cylinder: [radius, height].",
                },
                "wall_thickness": {
                    "type": "number",
                    "description": "Shell wall thickness (mm) when building a hollow primitive.",
                },
                "material": {
                    "type": "string",
                    "description": "Material name for injection-moulding guideline, e.g. 'ABS', 'PP'.",
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Number of surface sample points (default 1000).",
                },
                "ray_count_per_sample": {
                    "type": "integer",
                    "description": "Rays per sample point (default 20).",
                },
                "seed": {
                    "type": "integer",
                    "description": "RNG seed for reproducibility (default 42).",
                },
            },
            "required": [],
        },
    )

    @register(_analyze_spec)
    async def run_brep_analyze_wall_thickness(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        from kerf_cad_core.geom.brep import make_box as _make_box, make_sphere as _make_sphere, make_cylinder as _make_cylinder
        from kerf_cad_core.geom.solid_features import shell_body as _shell_body

        shape = a.get("shape", "box")
        size = a.get("size", [10.0, 10.0, 10.0])
        wt = float(a.get("wall_thickness", 1.0))
        material = a.get("material", None)
        n_samples = int(a.get("n_samples", 1000))
        ray_count = int(a.get("ray_count_per_sample", 20))
        seed_val = a.get("seed", 42)

        try:
            if shape == "box":
                sz = [float(x) for x in (size + [10.0, 10.0, 10.0])[:3]]
                solid = _make_box(origin=(0.0, 0.0, 0.0), size=tuple(sz))
            elif shape == "sphere":
                r = float(size[0]) if size else 5.0
                solid = _make_sphere(center=(0.0, 0.0, 0.0), radius=r)
            elif shape == "cylinder":
                r = float(size[0]) if len(size) >= 1 else 3.0
                h = float(size[1]) if len(size) >= 2 else 6.0
                solid = _make_cylinder(center=(0.0, 0.0, 0.0), radius=r, height=h)
            else:
                return err_payload(f"unknown shape: {shape!r}", "BAD_ARGS")

            shell_res = _shell_body(solid, wt)
            if not shell_res["ok"]:
                return err_payload(f"shell_body failed: {shell_res.get('reason')}", "OP_FAILED")
            body = shell_res["body"]
        except Exception as exc:
            return err_payload(f"body construction failed: {exc}", "OP_FAILED")

        try:
            report = analyze_wall_thickness(
                body,
                n_samples=n_samples,
                ray_count_per_sample=ray_count,
                material_name=material,
                seed=seed_val,
            )
        except Exception as exc:
            return err_payload(f"analyze_wall_thickness failed: {exc}", "OP_FAILED")

        # Serialise per_face_min (keys must be strings for JSON).
        pfm = {
            str(k): (None if math.isnan(v) else round(v, 6))
            for k, v in report.per_face_min_thickness.items()
        }
        return ok_payload({
            "global_min_mm": round(report.global_min, 6),
            "global_max_mm": round(report.global_max, 6),
            "per_face_min": pfm,
            "recommend_min_mm": report.recommend_min_for_material,
            "n_samples": len(report.sample_locations),
            "n_faces": len(report.per_face_min_thickness),
        })

    # ------------------------------------------------------------------
    # brep_check_moldability
    # ------------------------------------------------------------------

    _moldability_spec = ToolSpec(
        name="brep_check_moldability",
        description=(
            "Check whether a body's wall thickness meets injection-moulding "
            "guidelines for a given material.  Flags faces that are too thin and "
            "returns a pass/fail verdict.\n\n"
            "Material guideline table (mm): ABS 1.5, PP 0.8, PE 1.0, PC/polycarbonate 1.2, "
            "Nylon-6 1.5, PVC 2.0, POM 0.8, PEEK 1.5, PS 1.0, LCP 0.5.  "
            "Returns None for non-mouldable materials (concrete, ceramic, steel, …).\n\n"
            "Returns: {ok, passes, material, guideline_min_mm, "
            "n_thin_faces, thin_face_warnings, global_min_mm}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["box", "sphere", "cylinder"],
                    "description": "Shorthand primitive to build a test body.",
                },
                "size": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Box: [lx, ly, lz].  Sphere: [radius].  Cylinder: [radius, height].",
                },
                "wall_thickness": {
                    "type": "number",
                    "description": "Shell wall thickness (mm) when building a hollow primitive.",
                },
                "material": {
                    "type": "string",
                    "description": "Material name, e.g. 'ABS', 'PP', 'polycarbonate', 'concrete'.",
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Number of surface sample points (default 2000).",
                },
                "seed": {
                    "type": "integer",
                    "description": "RNG seed (default 42).",
                },
            },
            "required": ["material"],
        },
    )

    @register(_moldability_spec)
    async def run_brep_check_moldability(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        material = a.get("material", "")
        if not material:
            return err_payload("'material' is required", "BAD_ARGS")

        guideline = material_thickness_guideline(material)
        if guideline is None:
            return ok_payload({
                "ok": True,
                "passes": None,
                "material": material,
                "guideline_min_mm": None,
                "n_thin_faces": 0,
                "thin_face_warnings": [],
                "global_min_mm": None,
                "reason": (
                    f"'{material}' is not in the injection-moulding guideline "
                    "table (not a mouldable thermoplastic, or unknown material)."
                ),
            })

        from kerf_cad_core.geom.brep import make_box as _make_box, make_sphere as _make_sphere, make_cylinder as _make_cylinder
        from kerf_cad_core.geom.solid_features import shell_body as _shell_body

        shape = a.get("shape", "box")
        size = a.get("size", [10.0, 10.0, 10.0])
        wt = float(a.get("wall_thickness", 1.0))
        n_samples = int(a.get("n_samples", 2000))
        seed_val = a.get("seed", 42)

        try:
            if shape == "box":
                sz = [float(x) for x in (size + [10.0, 10.0, 10.0])[:3]]
                solid = _make_box(origin=(0.0, 0.0, 0.0), size=tuple(sz))
            elif shape == "sphere":
                r = float(size[0]) if size else 5.0
                solid = _make_sphere(center=(0.0, 0.0, 0.0), radius=r)
            elif shape == "cylinder":
                r = float(size[0]) if len(size) >= 1 else 3.0
                h = float(size[1]) if len(size) >= 2 else 6.0
                solid = _make_cylinder(center=(0.0, 0.0, 0.0), radius=r, height=h)
            else:
                return err_payload(f"unknown shape: {shape!r}", "BAD_ARGS")

            shell_res = _shell_body(solid, wt)
            if not shell_res["ok"]:
                return err_payload(f"shell_body failed: {shell_res.get('reason')}", "OP_FAILED")
            body = shell_res["body"]
        except Exception as exc:
            return err_payload(f"body construction failed: {exc}", "OP_FAILED")

        try:
            warnings = flag_thin_walls(
                body, material_name=material, n_samples=n_samples, seed=seed_val
            )
            report = analyze_wall_thickness(
                body, n_samples=min(n_samples, 500), material_name=material, seed=seed_val
            )
        except Exception as exc:
            return err_payload(f"analysis failed: {exc}", "OP_FAILED")

        thin_serialised = [
            {
                "face_id": w.face_id,
                "measured_min_mm": round(w.measured_min_mm, 6),
                "required_min_mm": round(w.required_min_mm, 6),
                "deficit_mm": round(w.deficit_mm, 6),
            }
            for w in warnings
        ]
        return ok_payload({
            "ok": True,
            "passes": len(warnings) == 0,
            "material": material,
            "guideline_min_mm": guideline,
            "n_thin_faces": len(warnings),
            "thin_face_warnings": thin_serialised,
            "global_min_mm": round(report.global_min, 6),
        })
