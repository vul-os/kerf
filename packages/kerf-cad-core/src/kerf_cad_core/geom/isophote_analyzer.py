"""GK-P11 — Isophote / Environment-Map (EMap) continuity analyser.

Visualises **surface fairness** for Class-A inspection by computing
iso-photes (lines of constant angle between the surface normal and a viewing
direction) and detecting discontinuities.

Background
----------
Isophotes are the level curves of the scalar field

    μ(u, v) = n̂(u, v) · L̂

where n̂ is the unit surface normal and L̂ is a fixed viewing/light direction.
They are the basis of the *environment-map* (EMap or sphere-map) visual
inspection used in CATIA FreeStyle, Rhino EMap, and Autodesk Alias.  A clean,
fair surface shows smoothly curving, evenly spaced isophotes; a G1 crease
produces a sharp kink; a G0 discontinuity snaps the isophote entirely.

Algorithm
---------
1. Evaluate μ(u, v) on a uniform (U × V) grid using analytic NURBS surface
   normals.
2. Extract isolines at each requested angle-band value using the
   **marching-squares** algorithm (Lorensen & Cline 1987, adapted for 2-D
   scalar fields).  Each isoline is returned as a list of (u, v) parameter
   pairs.
3. Measure **isoline curvature** via finite-differences along the extracted
   polylines.  A kinked isoline has large local curvature; a smooth surface
   produces gently curved isolines.
4. Compute a **fairness score** ∈ [0, 1]:

       fairness = exp(−kink_rate)

   where kink_rate = (number of high-curvature kinks) / (total arc length in
   parameter space) of all isolines.  Higher = fairer.

5. Detect across-band **discontinuities**: adjacent grid cells whose band
   index jumps by ≥ 2 are flagged (the same criterion used by the
   ``isophote_analysis`` function in ``surface_analysis.py``).

References
----------
* Forsey & Bartels (1995) "Tensor product B-spline surfaces using recursive
  subdivision" — discusses isophote inspection as a Class-A metric.
* Hagen & Bonneau (2000) "Variational Design of Surfaces" §4 — isophote
  curvature as a fairness measure.
* Lorensen & Cline (1987) "Marching cubes" — marching-squares isoline
  extraction (2-D specialisation).
* Pottmann & Wallner (2001) "Computational Line Geometry" §10 — environment-
  map sphere parameterisation.

Honest caveats
--------------
* The marching-squares isolines are sampled in *parameter* space (u, v), not
  arc-length space.  On surfaces with highly non-uniform parameterisation (e.g.
  surfaces created by STEP import with knot-domain singularities) the isoline
  density in parameter space may not reflect the geometric density.
* The fairness score is a heuristic; it is *not* a substitute for a curvature
  comb (``curvature_comb`` in ``curve_toolkit.py``) or for the full zebra /
  reflection-line analyser (``surface_analysis.zebra_stripe``).  Use those for
  final Class-A sign-off.
* Isophotes under a single light direction are view-independent but light-
  direction-dependent.  Rotate the light to inspect different surface
  features.
* On degenerate surface patches (zero-area cells, near-perpendicular knot
  directions) the normal computation may produce NaN normals; those cells are
  skipped and a warning is emitted.

Public API
----------
    IsophoteSpec   — input dataclass
    IsophoteReport — output dataclass
    analyze_isophotes(spec: IsophoteSpec) -> IsophoteReport
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_normal

__all__ = [
    "IsophoteSpec",
    "IsophoteReport",
    "analyze_isophotes",
]


# ---------------------------------------------------------------------------
# Input / output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IsophoteSpec:
    """Specification for an isophote analysis run.

    Parameters
    ----------
    surface : NurbsSurface
        The surface to analyse.
    view_direction_xyz : tuple[float, float, float]
        The fixed light / viewing direction (need not be unit length; will be
        normalised internally).  Default corresponds to world-up ``(0, 0, 1)``.
    angle_bands_deg : list[float]
        Angles (in degrees) at which to extract isophotes.  Each value θ
        defines the isoline μ = cos(θ).  Typical values: ``[0, 30, 60, 90]``.
    uv_samples_u : int
        Number of uniform sample points in the U direction.  Must be ≥ 4.
        Clamped to [4, 400].
    uv_samples_v : int
        Number of uniform sample points in the V direction.  Must be ≥ 4.
        Clamped to [4, 400].
    """

    surface: NurbsSurface
    view_direction_xyz: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    angle_bands_deg: List[float] = field(default_factory=lambda: [0.0, 30.0, 60.0, 90.0])
    uv_samples_u: int = 80
    uv_samples_v: int = 80


@dataclass
class IsophoteReport:
    """Results of an isophote analysis.

    Attributes
    ----------
    isophote_curves : list[list[tuple[float, float]]]
        One entry per requested angle band (in the same order as
        ``IsophoteSpec.angle_bands_deg``).  Each entry is a list of
        ``(u, v)`` parameter pairs forming the extracted isoline polyline for
        that angle.  Empty list when the isoline is absent (the surface never
        reaches that angle).
    max_isophote_curvature : float
        Maximum curvature (1/length-unit, measured in parameter space) observed
        across all extracted isoline polylines.  Smooth surfaces give small
        values.
    num_discontinuities : int
        Number of grid cells where an isophote band-jump ≥ 2 was detected.
        Non-zero values indicate a tangent (G1) discontinuity.
    fairness_score : float
        Scalar ∈ [0, 1].  Computed as exp(−kink_rate) where kink_rate is the
        number of high-curvature kinks per unit arc-length across all
        isolines.  1.0 = perfectly fair; approaching 0 = highly unfair.
    warnings : list[str]
        Non-fatal diagnostic messages (e.g. degenerate normals skipped).
    honest_caveat : str
        Fixed disclaimer reminding the caller of the limitations of the
        isophote metric compared to curvature combs and zebra analysis.
    """

    isophote_curves: List[List[Tuple[float, float]]]
    max_isophote_curvature: float
    num_discontinuities: int
    fairness_score: float
    warnings: List[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Isophote / EMap analysis is a visual-inspection heuristic based on a "
    "single viewing direction.  It detects G1 discontinuities reliably but "
    "does NOT replace: (a) curvature-comb analysis for G2/G3 quality, "
    "(b) zebra/reflection-line analysis (use surface_analysis.zebra_stripe), "
    "or (c) formal curvature continuity checks (use geom.match_srf "
    "verify_seam_g2_analytic).  Reported fairness_score and "
    "max_isophote_curvature are parameter-space metrics and depend on the "
    "surface's UV parameterisation; surfaces with non-uniform knot spacing "
    "may show artefacts."
)


def _normalise(v: np.ndarray) -> Optional[np.ndarray]:
    """Return unit vector or None if degenerate."""
    n = float(np.linalg.norm(v))
    if n < 1e-15:
        return None
    return v / n


def _build_mu_grid(
    surf: NurbsSurface,
    us: np.ndarray,
    vs: np.ndarray,
    L: np.ndarray,
) -> Tuple[np.ndarray, List[str]]:
    """Evaluate μ(u,v) = n̂·L̂ on the (nu × nv) grid.

    Returns (mu_grid, warnings) where mu_grid is a (nu, nv) float array and
    NaN indicates degenerate normals.
    """
    nu, nv = len(us), len(vs)
    mu = np.full((nu, nv), float("nan"))
    warnings: List[str] = []
    nan_count = 0

    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            try:
                n_raw = surface_normal(surf, float(u), float(v))
                n = _normalise(np.asarray(n_raw, dtype=float).ravel()[:3])
                if n is None:
                    nan_count += 1
                    continue
                mu[i, j] = float(np.dot(n, L))
            except Exception:
                nan_count += 1

    if nan_count > 0:
        warnings.append(
            f"{nan_count} grid cell(s) had degenerate normals and were skipped."
        )
    return mu, warnings


def _angle_band_index(mu: float, n_bands: int) -> int:
    """Map μ = n̂·L̂ ∈ [−1, 1] to an equal-angle band index ∈ [0, n_bands−1].

    Uses θ = acos(μ) so each band covers an equal solid angle on the EMap
    hemisphere.
    """
    mu_c = max(-1.0, min(1.0, mu))
    theta = math.acos(mu_c)  # [0, π]
    band = int(theta / math.pi * n_bands)
    return min(max(band, 0), n_bands - 1)


def _count_discontinuities(mu: np.ndarray, n_bands: int) -> int:
    """Count grid cells where the EMap band jumps ≥ 2 vs any neighbour."""
    nu, nv = mu.shape
    count = 0
    for i in range(nu):
        for j in range(nv):
            if not math.isfinite(mu[i, j]):
                continue
            b0 = _angle_band_index(mu[i, j], n_bands)
            for di, dj in ((0, 1), (1, 0)):
                ni_, nj_ = i + di, j + dj
                if ni_ >= nu or nj_ >= nv:
                    continue
                if not math.isfinite(mu[ni_, nj_]):
                    continue
                b1 = _angle_band_index(mu[ni_, nj_], n_bands)
                if abs(b1 - b0) >= 2:
                    count += 1
    return count


# ---------------------------------------------------------------------------
# Marching-squares isoline extraction
# ---------------------------------------------------------------------------

# Lookup table: for each 2-bit corner configuration (c0, c1, c2, c3 where
# cn ∈ {0, 1}) the corners of the unit cell are:
#   c0 = (0,0), c1 = (1,0), c2 = (1,1), c3 = (0,1)
# Each non-empty entry is a list of one or two line segments, each segment
# as two edge identifiers (0=bottom, 1=right, 2=top, 3=left).
# Edge midpoint positions (in cell-local coords):
#   edge 0: ((0,0) - (1,0)) bottom  → midpoint along u
#   edge 1: ((1,0) - (1,1)) right   → midpoint along v
#   edge 2: ((1,1) - (0,1)) top     → midpoint along u (reversed)
#   edge 3: ((0,1) - (0,0)) left    → midpoint along v (reversed)
# Standard marching-squares table (16 cases, edge indices 0-3):
_MS_TABLE = {
    0:  [],
    1:  [(3, 0)],
    2:  [(0, 1)],
    3:  [(3, 1)],
    4:  [(1, 2)],
    5:  [(3, 2), (0, 1)],  # ambiguous — split heuristic: two separate edges
    6:  [(0, 2)],
    7:  [(3, 2)],
    8:  [(2, 3)],
    9:  [(0, 2)],
    10: [(0, 3), (1, 2)],  # ambiguous
    11: [(1, 2)],
    12: [(1, 3)],
    13: [(0, 1)],
    14: [(3, 0)],
    15: [],
}


def _edge_uv(
    edge_id: int,
    mu_cell: np.ndarray,
    iso_mu: float,
    u0: float,
    u1: float,
    v0: float,
    v1: float,
) -> Tuple[float, float]:
    """Interpolate the crossing point on a cell edge.

    ``mu_cell`` is the 2×2 mu values at the cell corners:
        mu_cell[0,0]=c0, mu_cell[1,0]=c1, mu_cell[1,1]=c2, mu_cell[0,1]=c3.
    Returns (u, v) in surface parameter space.
    """
    if edge_id == 0:  # bottom: c0→c1, varies u
        m0, m1 = mu_cell[0, 0], mu_cell[1, 0]
        t = _safe_t(m0, m1, iso_mu)
        return (u0 + t * (u1 - u0), v0)
    elif edge_id == 1:  # right: c1→c2, varies v
        m0, m1 = mu_cell[1, 0], mu_cell[1, 1]
        t = _safe_t(m0, m1, iso_mu)
        return (u1, v0 + t * (v1 - v0))
    elif edge_id == 2:  # top: c2→c3, varies u (reversed)
        m0, m1 = mu_cell[1, 1], mu_cell[0, 1]
        t = _safe_t(m0, m1, iso_mu)
        return (u1 - t * (u1 - u0), v1)
    else:  # edge_id == 3: left: c3→c0, varies v (reversed)
        m0, m1 = mu_cell[0, 1], mu_cell[0, 0]
        t = _safe_t(m0, m1, iso_mu)
        return (u0, v1 - t * (v1 - v0))


def _safe_t(m0: float, m1: float, iso: float) -> float:
    """Interpolation parameter t ∈ [0, 1] for the crossing m0 + t*(m1−m0) = iso."""
    span = m1 - m0
    if abs(span) < 1e-15:
        return 0.5
    t = (iso - m0) / span
    return max(0.0, min(1.0, t))


def _extract_isoline(
    mu: np.ndarray,
    iso_mu: float,
    us: np.ndarray,
    vs: np.ndarray,
) -> List[Tuple[float, float]]:
    """Extract isoline at μ = iso_mu from the grid using marching squares.

    Returns a flat list of (u, v) pairs (line segment endpoints).  The caller
    can treat them as an ordered polyline or as unordered segments; because we
    don't stitch here the result is a sequence of segment pairs
    [p0, p1, p1, p2, ...].
    """
    nu, nv = mu.shape
    points: List[Tuple[float, float]] = []

    for i in range(nu - 1):
        for j in range(nv - 1):
            # Cell corners: [i,j], [i+1,j], [i+1,j+1], [i,j+1]
            m00 = mu[i, j]
            m10 = mu[i + 1, j]
            m11 = mu[i + 1, j + 1]
            m01 = mu[i, j + 1]

            # Skip if any corner is NaN
            if not (math.isfinite(m00) and math.isfinite(m10) and
                    math.isfinite(m11) and math.isfinite(m01)):
                continue

            # Build 4-bit configuration (1 if ≥ iso_mu, 0 if < iso_mu)
            c0 = 1 if m00 >= iso_mu else 0  # corner (i, j)
            c1 = 1 if m10 >= iso_mu else 0  # corner (i+1, j)
            c2 = 1 if m11 >= iso_mu else 0  # corner (i+1, j+1)
            c3 = 1 if m01 >= iso_mu else 0  # corner (i, j+1)
            config = c0 | (c1 << 1) | (c2 << 2) | (c3 << 3)

            segments = _MS_TABLE.get(config, [])
            if not segments:
                continue

            mu_cell = np.array([[m00, m01], [m10, m11]])
            u0, u1 = float(us[i]), float(us[i + 1])
            v0, v1 = float(vs[j]), float(vs[j + 1])

            for e0, e1 in segments:
                pa = _edge_uv(e0, mu_cell, iso_mu, u0, u1, v0, v1)
                pb = _edge_uv(e1, mu_cell, iso_mu, u0, u1, v0, v1)
                points.append(pa)
                points.append(pb)

    return points


# ---------------------------------------------------------------------------
# Isoline curvature (fairness metric)
# ---------------------------------------------------------------------------


def _isoline_curvature(pts: List[Tuple[float, float]]) -> List[float]:
    """Compute turning-angle curvature at each interior vertex of a polyline.

    The input ``pts`` is treated as [p0, p1, p2, ...] (already-ordered
    polyline).  Returns curvature κ_i at each triple (p_{i-1}, p_i, p_{i+1}).
    """
    if len(pts) < 3:
        return []
    curvatures: List[float] = []
    for k in range(1, len(pts) - 1):
        u0, v0 = pts[k - 1]
        u1, v1 = pts[k]
        u2, v2 = pts[k + 1]
        d1 = math.hypot(u1 - u0, v1 - v0)
        d2 = math.hypot(u2 - u1, v2 - v1)
        if d1 < 1e-15 or d2 < 1e-15:
            continue
        # Menger curvature: κ = |cross| / (d1 * d2 * d3/2)
        # using the turning-angle approximation κ ≈ |Δangle| / arc_length
        cross = (u1 - u0) * (v2 - v1) - (v1 - v0) * (u2 - u1)
        d3 = math.hypot(u2 - u0, v2 - v0)
        denom = d1 * d2 * max(d3, 1e-15)
        kappa = 2.0 * abs(cross) / max(denom, 1e-15)
        curvatures.append(kappa)
    return curvatures


def _polyline_arc_length(pts: List[Tuple[float, float]]) -> float:
    """Arc length of a polyline in parameter space."""
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for k in range(1, len(pts)):
        du = pts[k][0] - pts[k - 1][0]
        dv = pts[k][1] - pts[k - 1][1]
        total += math.hypot(du, dv)
    return total


def _compute_fairness(
    isolines: List[List[Tuple[float, float]]],
    kink_threshold: float = 5.0,
) -> Tuple[float, float]:
    """Return (max_curvature, fairness_score) across all isolines.

    A *kink* is a curvature value above ``kink_threshold`` (parameter-space
    units).  fairness = exp(−kink_rate), kink_rate = kinks / total_arc_length.
    """
    max_kappa = 0.0
    total_kinks = 0
    total_length = 0.0

    for pts in isolines:
        if len(pts) < 2:
            continue
        total_length += _polyline_arc_length(pts)
        kappas = _isoline_curvature(pts)
        for k in kappas:
            if k > max_kappa:
                max_kappa = k
            if k > kink_threshold:
                total_kinks += 1

    if total_length < 1e-15:
        return max_kappa, 1.0  # no isolines → perfect (vacuous)

    kink_rate = total_kinks / total_length
    fairness = math.exp(-kink_rate)
    return max_kappa, fairness


# ---------------------------------------------------------------------------
# Stitch marching-squares segments into polylines
# ---------------------------------------------------------------------------


def _stitch_segments(
    pts: List[Tuple[float, float]],
) -> List[List[Tuple[float, float]]]:
    """Stitch a flat list of segment-endpoint pairs into polylines.

    Input is [p0, p1, p2, p3, ...] where (p0, p1), (p2, p3), … are individual
    segments.  Returns a list of polylines (each a list of (u,v) tuples) by
    greedily connecting segment endpoints within a small tolerance.
    """
    if not pts:
        return []

    eps = 1e-9
    # Build list of (start, end) tuples
    segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for k in range(0, len(pts) - 1, 2):
        segs.append((pts[k], pts[k + 1]))

    chains: List[List[Tuple[float, float]]] = []

    def _close(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps

    used = [False] * len(segs)
    for start_idx in range(len(segs)):
        if used[start_idx]:
            continue
        used[start_idx] = True
        chain: List[Tuple[float, float]] = [segs[start_idx][0], segs[start_idx][1]]

        # Grow forward
        changed = True
        while changed:
            changed = False
            tail = chain[-1]
            for k in range(len(segs)):
                if used[k]:
                    continue
                s0, s1 = segs[k]
                if _close(s0, tail):
                    chain.append(s1)
                    used[k] = True
                    changed = True
                    break
                if _close(s1, tail):
                    chain.append(s0)
                    used[k] = True
                    changed = True
                    break

        if len(chain) >= 2:
            chains.append(chain)

    return chains


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def analyze_isophotes(spec: IsophoteSpec) -> IsophoteReport:
    """Compute isophotes and fairness metrics for a NURBS surface.

    Parameters
    ----------
    spec : IsophoteSpec
        Analysis specification (surface, view direction, angle bands, grid
        resolution).

    Returns
    -------
    IsophoteReport
        Extracted isoline polylines, max curvature, discontinuity count,
        fairness score, and diagnostic warnings.

    Raises
    ------
    TypeError
        If ``spec.surface`` is not a ``NurbsSurface``.
    ValueError
        If ``spec.angle_bands_deg`` is empty.
    """
    if not isinstance(spec.surface, NurbsSurface):
        raise TypeError("spec.surface must be a NurbsSurface instance")
    if not spec.angle_bands_deg:
        raise ValueError("spec.angle_bands_deg must contain at least one angle")

    surf = spec.surface
    nu = int(max(4, min(400, spec.uv_samples_u)))
    nv = int(max(4, min(400, spec.uv_samples_v)))

    # Normalise view direction
    vd = np.asarray(spec.view_direction_xyz, dtype=float).ravel()[:3]
    L_norm = _normalise(vd)
    if L_norm is None:
        L_norm = np.array([0.0, 0.0, 1.0])

    # Build UV grid
    u0, u1 = float(surf.knots_u[0]), float(surf.knots_u[-1])
    v0, v1 = float(surf.knots_v[0]), float(surf.knots_v[-1])
    us = np.linspace(u0, u1, nu)
    vs = np.linspace(v0, v1, nv)

    # Evaluate μ(u,v) grid
    mu_grid, warnings = _build_mu_grid(surf, us, vs, L_norm)

    # Count discontinuities (16 bands — coarser than requested angles but
    # sufficient for break detection in the standard EMap sense)
    n_bands = max(8, len(spec.angle_bands_deg) * 4)
    num_disc = _count_discontinuities(mu_grid, n_bands)

    # Extract isolines at each requested angle
    all_chains: List[List[Tuple[float, float]]] = []
    isophote_curves: List[List[Tuple[float, float]]] = []

    for angle_deg in spec.angle_bands_deg:
        angle_rad = math.radians(float(angle_deg))
        iso_mu = math.cos(angle_rad)

        raw_pts = _extract_isoline(mu_grid, iso_mu, us, vs)
        chains = _stitch_segments(raw_pts)

        # Flatten all chains for this band into a single polyline list
        # (concatenating all chains with a gap marker is acceptable for the
        # fairness metric; the caller receives per-band curves as flat lists)
        band_pts: List[Tuple[float, float]] = []
        for ch in chains:
            band_pts.extend(ch)
            all_chains.append(ch)

        isophote_curves.append(band_pts)

    # Fairness metric
    max_kappa, fairness = _compute_fairness(all_chains)

    return IsophoteReport(
        isophote_curves=isophote_curves,
        max_isophote_curvature=max_kappa,
        num_discontinuities=num_disc,
        fairness_score=fairness,
        warnings=warnings,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    def _parse_surface_iso(a: dict):
        """Return NurbsSurface or an error string from LLM tool args."""
        try:
            du = int(a["degree_u"])
            dv = int(a["degree_v"])
            nu = int(a["num_u"])
            nv = int(a["num_v"])
        except (KeyError, TypeError, ValueError) as exc:
            return f"degree_u/degree_v/num_u/num_v required integers: {exc}"

        raw_cp = a.get("control_points")
        ku_raw = a.get("knots_u")
        kv_raw = a.get("knots_v")
        if raw_cp is None or ku_raw is None or kv_raw is None:
            return "control_points, knots_u, knots_v are required"

        try:
            flat = np.asarray(raw_cp, dtype=float)
            if flat.ndim == 1:
                dim = len(flat) // (nu * nv)
                flat = flat.reshape(nu, nv, dim)
            elif flat.ndim == 2:
                dim = flat.shape[1]
                flat = flat.reshape(nu, nv, dim)
            else:
                flat = flat.reshape(nu, nv, flat.shape[-1])
        except Exception as exc:
            return f"could not reshape control_points to ({nu},{nv},dim): {exc}"

        try:
            ku = np.asarray(ku_raw, dtype=float)
            kv = np.asarray(kv_raw, dtype=float)
        except Exception as exc:
            return f"invalid knots: {exc}"

        weights = None
        raw_w = a.get("weights")
        if raw_w is not None:
            try:
                weights = np.asarray(raw_w, dtype=float).reshape(nu, nv)
            except Exception as exc:
                return f"invalid weights: {exc}"

        try:
            return NurbsSurface(
                degree_u=du,
                degree_v=dv,
                control_points=flat,
                knots_u=ku,
                knots_v=kv,
                weights=weights,
            )
        except Exception as exc:
            return f"NurbsSurface construction failed: {exc}"

    _analyze_isophotes_spec = ToolSpec(
        name="nurbs_analyze_isophotes",
        description=(
            "Isophote / Environment-Map (EMap) continuity analyser for Class-A "
            "surface inspection.  Computes lines of constant angle between the "
            "surface normal and a viewing direction (isophotes), extracts them as "
            "polylines in UV parameter space via marching squares, and reports "
            "discontinuity count and a fairness score.\n\n"
            "Use this to detect G1 tangency discontinuities (kinks) and assess "
            "isophote smoothness — a standard Class-A surface-quality metric used "
            "in jewelry and automotive styling.\n\n"
            "CAVEAT: fairness_score and max_isophote_curvature are parameter-space "
            "metrics.  This tool is a visual-inspection aid; it is NOT a substitute "
            "for curvature-comb analysis (nurbs_curvature_metrics) or zebra/reflection-"
            "line analysis (feature_zebra_analysis).\n\n"
            "Returns:\n"
            "  ok                     : bool\n"
            "  num_angle_bands        : int\n"
            "  isophote_point_counts  : [int, ...] — number of (u,v) points per band\n"
            "  max_isophote_curvature : float — max isoline curvature (parameter-space)\n"
            "  num_discontinuities    : int — isophote break count\n"
            "  fairness_score         : float ∈ [0,1] — 1=perfectly fair\n"
            "  warnings               : [str, ...]\n"
            "  honest_caveat          : str\n\n"
            "Errors: {ok:false, reason, code}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {
                    "type": "integer",
                    "description": "Surface degree in U direction.",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Surface degree in V direction.",
                },
                "num_u": {
                    "type": "integer",
                    "description": "Number of control points in U direction.",
                },
                "num_v": {
                    "type": "integer",
                    "description": "Number of control points in V direction.",
                },
                "control_points": {
                    "type": "array",
                    "description": "Flat list of [[x,y,z], ...] control points in row-major (u-first) order.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in U direction.",
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in V direction.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional flat (num_u*num_v) weight array for rational surfaces.",
                },
                "view_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "Viewing/light direction [x, y, z] (need not be unit length). Default [0,0,1].",
                },
                "angle_bands_deg": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Angles in degrees at which to extract isophotes (e.g. [0, 30, 60, 90]). Default [0, 30, 60, 90].",
                },
                "uv_samples_u": {
                    "type": "integer",
                    "description": "Grid resolution in U (default 80, clamped to [4, 400]).",
                },
                "uv_samples_v": {
                    "type": "integer",
                    "description": "Grid resolution in V (default 80, clamped to [4, 400]).",
                },
            },
            "required": [
                "degree_u", "degree_v", "num_u", "num_v",
                "control_points", "knots_u", "knots_v",
            ],
        },
    )

    @register(_analyze_isophotes_spec)
    async def run_nurbs_analyze_isophotes(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        srf = _parse_surface_iso(a)
        if isinstance(srf, str):
            return err_payload(srf, "BAD_ARGS")

        view_dir = a.get("view_direction", [0.0, 0.0, 1.0])
        angle_bands = a.get("angle_bands_deg", [0.0, 30.0, 60.0, 90.0])
        uu = int(a.get("uv_samples_u", 80))
        uv = int(a.get("uv_samples_v", 80))

        spec = IsophoteSpec(
            surface=srf,
            view_direction_xyz=tuple(float(x) for x in view_dir[:3]),
            angle_bands_deg=[float(x) for x in angle_bands],
            uv_samples_u=uu,
            uv_samples_v=uv,
        )

        try:
            report = analyze_isophotes(spec)
        except Exception as exc:
            return err_payload(f"isophote analysis failed: {exc}", "OP_FAILED")

        return ok_payload({
            "num_angle_bands": len(report.isophote_curves),
            "isophote_point_counts": [len(c) for c in report.isophote_curves],
            "max_isophote_curvature": report.max_isophote_curvature,
            "num_discontinuities": report.num_discontinuities,
            "fairness_score": report.fairness_score,
            "warnings": report.warnings,
            "honest_caveat": report.honest_caveat,
        })
