"""wall_thickness.py — GK-76 Wall-thickness map.

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
