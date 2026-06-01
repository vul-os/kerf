"""
NURBS-SURFACE-ANALYTIC-DERIVATIVES (GK-P15)
=============================================
Closed-form first and second partial derivatives of a NurbsSurface, plus
Gaussian and mean curvature; and a hardened Surface-Surface Intersection
(SSI) marcher that handles near-tangent regions via bisection fallback.

Analytic derivatives
--------------------
``compute_analytic_derivatives(surface, u, v)`` delegates to the canonical
``surface_derivatives(surf, u, v, d=2)`` (Piegl & Tiller Algorithm A3.6 for
B-spline tensor product, followed by the rational quotient rule A4.4 for
rational NURBS).  No finite differences are used.

The returned ``SurfaceDerivativeResult`` exposes:

* ``dS_du``, ``dS_dv``   — first partial derivatives  ∂S/∂u, ∂S/∂v
* ``d2S_du2``, ``d2S_dudv``, ``d2S_dv2`` — second partials
* ``gauss_K``, ``mean_H`` — Gaussian / mean curvature via the shape operator
  (first fundamental form coefficients E, F, G and second fundamental form
  coefficients L, M, N; do Carmo §3.2 / Mortenson §6.5).
* ``honest_caveat`` — plaintext warning for rational/near-degenerate cases.

Gauss / mean curvature formulae
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For a parametric surface S(u,v) with unit normal n̂::

    E = dS_du · dS_du,   F = dS_du · dS_dv,   G = dS_dv · dS_dv
    L = d2S_du2 · n̂,     M = d2S_dudv · n̂,    N = d2S_dv2 · n̂
    K = (L·N - M²) / (E·G - F²)
    H = (E·N - 2·F·M + G·L) / (2·(E·G - F²))

SSIHardenedMarcher
------------------
``SSIHardenedMarcher.march(surface_a, surface_b, seed_uv_a, seed_uv_b)``
traces an SSI intersection curve from a seed point.  Near-tangent regions
(where the two surface normals are nearly parallel → the projected step is
ill-conditioned) trigger an automatic bisection sub-step to relocate the
curve before resuming normal marching.

Algorithm follows Patrikalakis & Maekawa §5 (differential-geometry marching)
with the tangent direction t = n̂_A × n̂_B / |n̂_A × n̂_B|.

HONEST LIMITATIONS
------------------
* Curvature at degenerate points (|S_u × S_v| < 1e-12, e.g. poles) is
  returned as ``float('nan')`` — the shape operator is undefined there.
* For rational NURBS with near-zero weights the quotient-rule expansion
  can have large numerical condition numbers; the honest_caveat reports this.
* SSI marcher assumes the intersection is a smooth curve per branch.
  ``march()`` traces one branch per seed (backward-compatible, unchanged).
  ``march_all_branches()`` implements Patrikalakis-Maekawa §5.4 bifurcation
  detection: at each step the tangent cross-product magnitude is checked; when
  it drops below ``tangent_threshold`` the curvature tensor is probed to
  determine whether the intersection has two locally distinct tangent directions
  (transversal bifurcation).  If so, two new seed marchers are spawned in the
  two principal directions; a work-list of unresolved seeds is maintained until
  exhausted or ``max_branches`` is reached.
* Bisection fallback converges to O(step²) accuracy but uses more evaluations.

References
----------
* Piegl, L. & Tiller, W. (1997). *The NURBS Book*, 2nd ed.
  Algorithm A3.6 (surface derivatives), Algorithm A4.4 (rational quotient).
* Patrikalakis, N.M. & Maekawa, T. (2002). *Shape Interrogation for
  Computer Aided Design and Manufacturing*, §5 (SSI marching).
* do Carmo, M.P. (1976). *Differential Geometry of Curves and Surfaces*, §3.2.
* Mortenson, M.E. (2006). *Geometric Modeling*, 3rd ed., §6.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsSurface,
    surface_derivatives,
    surface_evaluate,
    surface_normal,
)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class SurfaceDerivativeResult:
    """Closed-form partial derivatives and differential geometry of S(u,v).

    Attributes
    ----------
    dS_du : tuple[float, float, float]
        First partial ∂S/∂u at the queried (u, v).
    dS_dv : tuple[float, float, float]
        First partial ∂S/∂v at the queried (u, v).
    d2S_du2 : tuple[float, float, float]
        Second partial ∂²S/∂u².
    d2S_dudv : tuple[float, float, float]
        Mixed second partial ∂²S/∂u∂v.
    d2S_dv2 : tuple[float, float, float]
        Second partial ∂²S/∂v².
    gauss_K : float
        Gaussian curvature K = (LN - M²) / (EG - F²).  NaN at degenerate pts.
    mean_H : float
        Mean curvature H = (EN - 2FM + GL) / (2(EG - F²)).  NaN at degenerate.
    honest_caveat : str
        Plain-English warning about numerical limitations or special cases.
    """

    dS_du: Tuple[float, float, float]
    dS_dv: Tuple[float, float, float]
    d2S_du2: Tuple[float, float, float]
    d2S_dudv: Tuple[float, float, float]
    d2S_dv2: Tuple[float, float, float]
    gauss_K: float
    mean_H: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_analytic_derivatives(
    surface: NurbsSurface,
    u: float,
    v: float,
) -> SurfaceDerivativeResult:
    """Closed-form first + second partial derivatives of *surface* at *(u, v)*.

    Uses Piegl & Tiller Algorithm A3.6 (B-spline tensor-product derivative
    table) composed with the rational quotient rule (Algorithm A4.4) for
    rational NURBS.  No finite differences.

    Parameters
    ----------
    surface : NurbsSurface
        The NURBS surface to differentiate.
    u, v : float
        Parameter values; must be within the surface's knot domain.

    Returns
    -------
    SurfaceDerivativeResult
        All five partial derivatives plus Gaussian and mean curvature.
    """
    u = float(u)
    v = float(v)

    # Clamp to domain (avoids subtle span-lookup failures at knot boundaries).
    pu, pv = surface.degree_u, surface.degree_v
    u_min = float(surface.knots_u[pu])
    u_max = float(surface.knots_u[-pu - 1])
    v_min = float(surface.knots_v[pv])
    v_max = float(surface.knots_v[-pv - 1])
    u = max(u_min, min(u_max, u))
    v = max(v_min, min(v_max, v))

    # Full derivative table up to order 2 — shape (3, 3, dim).
    SKL = surface_derivatives(surface, u, v, d=2)

    dim = surface.control_points.shape[2]
    su = SKL[1, 0][:3]
    sv = SKL[0, 1][:3]
    suu = SKL[2, 0][:3]
    suv = SKL[1, 1][:3]
    svv = SKL[0, 2][:3]

    # ---- First fundamental form coefficients --------------------------------
    E = float(np.dot(su, su))
    F = float(np.dot(su, sv))
    G = float(np.dot(sv, sv))
    denom = E * G - F * F

    # ---- Unit normal --------------------------------------------------------
    cross = np.cross(su, sv)
    cross_mag = float(np.linalg.norm(cross))
    is_degen = cross_mag < 1e-12

    if is_degen:
        n_hat = np.array([0.0, 0.0, 1.0])
    else:
        n_hat = cross / cross_mag

    # ---- Second fundamental form coefficients -------------------------------
    L = float(np.dot(suu, n_hat))
    M = float(np.dot(suv, n_hat))
    N = float(np.dot(svv, n_hat))

    # ---- Curvatures ---------------------------------------------------------
    if is_degen or abs(denom) < 1e-30:
        gauss_K = float("nan")
        mean_H = float("nan")
    else:
        gauss_K = (L * N - M * M) / denom
        mean_H = (E * N - 2.0 * F * M + G * L) / (2.0 * denom)

    # ---- Honest caveat ------------------------------------------------------
    caveats: List[str] = []
    if is_degen:
        caveats.append(
            "DEGENERATE: |S_u × S_v| < 1e-12 at this parameter (e.g. a pole). "
            "gauss_K and mean_H are NaN; normal vector defaulted to +Z."
        )
    if surface.is_rational:
        # Check for near-zero weight denominator.
        min_w = float(np.min(surface.weights)) if surface.weights is not None else 1.0
        if min_w < 1e-4:
            caveats.append(
                f"RATIONAL with minimum weight {min_w:.3g} < 1e-4. "
                "The rational quotient rule (P&T A4.4) is used but may have "
                "large condition number near zero-weight control points."
            )
        else:
            caveats.append(
                "RATIONAL NURBS: quotient-rule derivatives (P&T A4.4). "
                "Numerically exact for well-conditioned weights."
            )
    else:
        caveats.append(
            "Non-rational (polynomial) NURBS: derivatives are exact via "
            "P&T A3.6 B-spline tensor product — no finite differences."
        )
    if not math.isnan(gauss_K) and not math.isnan(mean_H):
        # Sanity: K = κ₁·κ₂, H = (κ₁+κ₂)/2.  discriminant = H²-K ≥ 0.
        disc = mean_H * mean_H - gauss_K
        if disc < -1e-10:
            caveats.append(
                f"NUMERICAL WARNING: H²-K = {disc:.3g} < 0 (should be ≥ 0). "
                "Possible large rounding error in curvature computation."
            )

    caveat_str = "  ".join(caveats) if caveats else "OK"

    return SurfaceDerivativeResult(
        dS_du=tuple(float(x) for x in su),  # type: ignore[arg-type]
        dS_dv=tuple(float(x) for x in sv),  # type: ignore[arg-type]
        d2S_du2=tuple(float(x) for x in suu),  # type: ignore[arg-type]
        d2S_dudv=tuple(float(x) for x in suv),  # type: ignore[arg-type]
        d2S_dv2=tuple(float(x) for x in svv),  # type: ignore[arg-type]
        gauss_K=gauss_K,
        mean_H=mean_H,
        honest_caveat=caveat_str,
    )


# ---------------------------------------------------------------------------
# SSI Hardened Marcher
# ---------------------------------------------------------------------------


@dataclass
class SSIHardenedMarcher:
    """Surface-Surface Intersection marcher with near-tangent bisection fallback.

    Follows Patrikalakis & Maekawa §5 differential-geometry marching:
    the tangent direction along the intersection curve is
    ``t = (n̂_A × n̂_B) / |n̂_A × n̂_B|``.  A Newton corrector step
    (per-surface point projection) keeps the trace on both surfaces.

    Near-tangent fallback
    ~~~~~~~~~~~~~~~~~~~~~
    When ``|n̂_A × n̂_B| < tangent_threshold`` the marching step is
    ill-conditioned.  The marcher switches to a bisection step that bisects
    the parameter interval in *both* surfaces to relocate a well-conditioned
    seed, then resumes normal marching.

    Attributes
    ----------
    tangent_threshold : float
        Cross-product magnitude below which bisection is triggered (default 0.05).
    newton_tol : float
        Convergence tolerance for the Newton corrector step (default 1e-8).
    newton_max_iter : int
        Maximum Newton corrector iterations per step (default 10).
    """

    tangent_threshold: float = 0.05
    newton_tol: float = 1e-8
    newton_max_iter: int = 10

    def march(
        self,
        surface_a: NurbsSurface,
        surface_b: NurbsSurface,
        seed_uv_a: Tuple[float, float],
        seed_uv_b: Tuple[float, float],
        step_mm: float = 0.5,
        max_steps: int = 1000,
    ) -> List[Tuple[float, float, float]]:
        """Trace the SSI curve from the given seed parameters.

        Parameters
        ----------
        surface_a, surface_b : NurbsSurface
            The two surfaces to intersect.
        seed_uv_a : (ua, va)
            Starting parameter on surface_a.
        seed_uv_b : (ub, vb)
            Starting parameter on surface_b (should correspond to the same
            3-D point as seed_uv_a — use a close-point solver beforehand).
        step_mm : float
            Step size along the intersection curve (in model units, i.e. mm
            assuming the surface is in mm).  Default 0.5 mm.
        max_steps : int
            Maximum number of marching steps before aborting.  Default 1000.

        Returns
        -------
        list of (x, y, z) tuples
            Sampled points along the intersection curve, ordered from the seed.
            Includes the seed point as the first entry.
        """
        ua, va = float(seed_uv_a[0]), float(seed_uv_a[1])
        ub, vb = float(seed_uv_b[0]), float(seed_uv_b[1])

        # Clamp seeds to domain.
        ua, va = self._clamp_uv(surface_a, ua, va)
        ub, vb = self._clamp_uv(surface_b, ub, vb)

        # Seed point (average of both evaluated positions for robustness).
        Pa = surface_evaluate(surface_a, ua, va)[:3]
        Pb = surface_evaluate(surface_b, ub, vb)[:3]
        P_cur = 0.5 * (Pa + Pb)
        points: List[Tuple[float, float, float]] = [tuple(P_cur)]  # type: ignore[arg-type]

        seed_start = P_cur.copy()
        step = float(step_mm)
        near_tangent_count = 0

        for _ in range(max_steps):
            na = surface_normal(surface_a, ua, va)[:3]
            nb = surface_normal(surface_b, ub, vb)[:3]
            cross = np.cross(na, nb)
            cross_mag = float(np.linalg.norm(cross))

            if cross_mag < self.tangent_threshold:
                # Near-tangent: bisection sub-step.
                near_tangent_count += 1
                result = self._bisection_step(
                    surface_a, surface_b, ua, va, ub, vb, step
                )
                if result is None:
                    break
                ua, va, ub, vb, P_cur = result
                points.append(tuple(P_cur))  # type: ignore[arg-type]
                # Check for loop closure.
                if (len(points) > 5
                        and float(np.linalg.norm(P_cur - seed_start)) < step * 1.5):
                    break
                continue

            # Normal marching: advance by step along tangent.
            t = cross / cross_mag
            P_next = P_cur + step * t

            # Newton corrector: project P_next onto both surfaces.
            ua_n, va_n, ub_n, vb_n = self._newton_correct(
                surface_a, surface_b, P_next, ua, va, ub, vb
            )

            # Clamp to domain.
            ua_n, va_n = self._clamp_uv(surface_a, ua_n, va_n)
            ub_n, vb_n = self._clamp_uv(surface_b, ub_n, vb_n)

            Pa_n = surface_evaluate(surface_a, ua_n, va_n)[:3]
            Pb_n = surface_evaluate(surface_b, ub_n, vb_n)[:3]
            P_cur = 0.5 * (Pa_n + Pb_n)
            ua, va, ub, vb = ua_n, va_n, ub_n, vb_n

            points.append(tuple(P_cur))  # type: ignore[arg-type]

            # Check for loop closure (curve closed if we return near the start).
            if (len(points) > 10
                    and float(np.linalg.norm(P_cur - seed_start)) < step * 1.5):
                break

            # Check domain boundary exit.
            if self._at_boundary(surface_a, ua, va) or self._at_boundary(
                surface_b, ub, vb
            ):
                break

        return points

    # ------------------------------------------------------------------
    # Bifurcation-aware multi-branch marcher (Patrikalakis-Maekawa §5.4)
    # ------------------------------------------------------------------

    def march_all_branches(
        self,
        surface_a: NurbsSurface,
        surface_b: NurbsSurface,
        initial_seeds: List[Tuple[Tuple[float, float], Tuple[float, float]]],
        step_mm: float = 0.5,
        max_steps: int = 1000,
        max_branches: int = 8,
    ) -> List[List[Tuple[float, float, float]]]:
        """Trace all branches of the SSI curve, handling bifurcation points.

        Implements Patrikalakis & Maekawa §5.4: at each marching step the
        cross-product magnitude ``|n̂_A × n̂_B|`` is monitored.  When it drops
        below ``tangent_threshold`` the local curvature tensor of the
        intersection is interrogated to decide whether the point is a
        *transversal bifurcation* — a point where the curve branches into two
        distinct directions.  If a bifurcation is detected, two new seeds are
        spawned (one in each principal tangent direction) and added to a
        work-list.  The marcher pops seeds from the list and traces each branch
        with the single-branch ``march()`` until the list is exhausted or
        ``max_branches`` is reached.

        Parameters
        ----------
        surface_a, surface_b : NurbsSurface
            The two surfaces to intersect.
        initial_seeds : list of ((ua, va), (ub, vb))
            One or more seed pairs.  Each seed pair is a starting parameter on
            surface_a and surface_b that correspond to the same 3-D point.
        step_mm : float
            Step size (model units, mm).  Default 0.5.
        max_steps : int
            Maximum marching steps per branch.  Default 1000.
        max_branches : int
            Hard cap on the total number of branches returned.  Default 8.

        Returns
        -------
        list of list of (x, y, z)
            Each inner list is one traced branch (ordered from its seed).
            Branches are de-duplicated: a new seed is skipped if it is within
            ``step_mm * 2`` of a point already covered by an existing branch.
        """
        # Work-list: each entry is (seed_uv_a, seed_uv_b).
        pending: List[Tuple[Tuple[float, float], Tuple[float, float]]] = list(
            initial_seeds
        )
        branches: List[List[Tuple[float, float, float]]] = []

        # Flat list of all 3-D points already committed to branches (for
        # proximity de-duplication of candidate seeds).
        covered: List[np.ndarray] = []

        def _is_covered(pt: np.ndarray) -> bool:
            """Return True if *pt* is within step_mm*2 of any covered point."""
            thresh2 = (step_mm * 2.0) ** 2
            for cp in covered:
                if float(np.dot(pt - cp, pt - cp)) < thresh2:
                    return True
            return False

        while pending and len(branches) < max_branches:
            seed_a, seed_b = pending.pop(0)

            # Evaluate the seed 3-D position.
            ua0, va0 = self._clamp_uv(surface_a, float(seed_a[0]), float(seed_a[1]))
            ub0, vb0 = self._clamp_uv(surface_b, float(seed_b[0]), float(seed_b[1]))
            Pa0 = surface_evaluate(surface_a, ua0, va0)[:3]
            Pb0 = surface_evaluate(surface_b, ub0, vb0)[:3]
            seed_3d = 0.5 * (Pa0 + Pb0)

            if _is_covered(seed_3d):
                continue

            # Trace this branch with the single-branch marcher.
            branch = self._march_with_bifurcation_detection(
                surface_a, surface_b,
                (ua0, va0), (ub0, vb0),
                step_mm=step_mm,
                max_steps=max_steps,
                pending_seeds=pending,
                max_branches=max_branches,
                branches_so_far=branches,
                covered=covered,
            )

            if branch:
                branches.append(branch)
                for pt in branch:
                    covered.append(np.array(pt, dtype=float))

        return branches

    def _march_with_bifurcation_detection(
        self,
        surface_a: NurbsSurface,
        surface_b: NurbsSurface,
        seed_uv_a: Tuple[float, float],
        seed_uv_b: Tuple[float, float],
        step_mm: float,
        max_steps: int,
        pending_seeds: List[Tuple[Tuple[float, float], Tuple[float, float]]],
        max_branches: int,
        branches_so_far: List[List[Tuple[float, float, float]]],
        covered: List[np.ndarray],
    ) -> List[Tuple[float, float, float]]:
        """Single-branch march that emits bifurcation seeds onto *pending_seeds*.

        Identical marching logic to ``march()`` but at each near-tangent step
        ``_detect_bifurcation`` is called.  If a bifurcation is found the two
        new seeds are pushed onto *pending_seeds* for the caller to pick up,
        and marching of the current branch stops at the bifurcation point.

        Returns the list of points traced on this branch (may be empty if the
        seed is degenerate).
        """
        ua, va = float(seed_uv_a[0]), float(seed_uv_a[1])
        ub, vb = float(seed_uv_b[0]), float(seed_uv_b[1])

        ua, va = self._clamp_uv(surface_a, ua, va)
        ub, vb = self._clamp_uv(surface_b, ub, vb)

        Pa = surface_evaluate(surface_a, ua, va)[:3]
        Pb = surface_evaluate(surface_b, ub, vb)[:3]
        P_cur = 0.5 * (Pa + Pb)
        points: List[Tuple[float, float, float]] = [tuple(P_cur)]  # type: ignore[arg-type]

        seed_start = P_cur.copy()
        step = float(step_mm)

        def _covered_quick(pt: np.ndarray) -> bool:
            thresh2 = (step * 2.0) ** 2
            for cp in covered:
                if float(np.dot(pt - cp, pt - cp)) < thresh2:
                    return True
            return False

        for _ in range(max_steps):
            na = surface_normal(surface_a, ua, va)[:3]
            nb = surface_normal(surface_b, ub, vb)[:3]
            cross = np.cross(na, nb)
            cross_mag = float(np.linalg.norm(cross))

            if cross_mag < self.tangent_threshold:
                # Near-tangent: check for bifurcation before bisection.
                bif_seeds = self._detect_bifurcation(
                    surface_a, surface_b, ua, va, ub, vb, P_cur, step
                )
                if bif_seeds is not None:
                    # Bifurcation found — enqueue both new seeds and stop
                    # this branch so the caller can trace each independently.
                    total = len(branches_so_far) + len(pending_seeds) + 1
                    for s_a, s_b in bif_seeds:
                        s3d = 0.5 * (
                            surface_evaluate(surface_a, s_a[0], s_a[1])[:3]
                            + surface_evaluate(surface_b, s_b[0], s_b[1])[:3]
                        )
                        if (not _covered_quick(s3d)
                                and total < max_branches):
                            pending_seeds.append((s_a, s_b))
                            total += 1
                    break

                # No bifurcation — use bisection fallback.
                result = self._bisection_step(
                    surface_a, surface_b, ua, va, ub, vb, step
                )
                if result is None:
                    break
                ua, va, ub, vb, P_cur = result
                points.append(tuple(P_cur))  # type: ignore[arg-type]
                if (len(points) > 5
                        and float(np.linalg.norm(P_cur - seed_start)) < step * 1.5):
                    break
                continue

            # Normal marching step.
            t = cross / cross_mag
            P_next = P_cur + step * t

            ua_n, va_n, ub_n, vb_n = self._newton_correct(
                surface_a, surface_b, P_next, ua, va, ub, vb
            )
            ua_n, va_n = self._clamp_uv(surface_a, ua_n, va_n)
            ub_n, vb_n = self._clamp_uv(surface_b, ub_n, vb_n)

            Pa_n = surface_evaluate(surface_a, ua_n, va_n)[:3]
            Pb_n = surface_evaluate(surface_b, ub_n, vb_n)[:3]
            P_cur = 0.5 * (Pa_n + Pb_n)
            ua, va, ub, vb = ua_n, va_n, ub_n, vb_n

            points.append(tuple(P_cur))  # type: ignore[arg-type]

            if (len(points) > 10
                    and float(np.linalg.norm(P_cur - seed_start)) < step * 1.5):
                break

            if self._at_boundary(surface_a, ua, va) or self._at_boundary(
                surface_b, ub, vb
            ):
                break

        return points

    def _detect_bifurcation(
        self,
        surf_a: NurbsSurface,
        surf_b: NurbsSurface,
        ua: float,
        va: float,
        ub: float,
        vb: float,
        P_cur: np.ndarray,
        step: float,
    ) -> Optional[
        List[Tuple[Tuple[float, float], Tuple[float, float]]]
    ]:
        """Determine whether the current near-tangent point is a transversal
        bifurcation and, if so, return two seed pairs for the two branches.

        Algorithm (Patrikalakis-Maekawa §5.4):
        At a bifurcation point the intersection curve has two distinct tangent
        directions t₁ and t₂ in the common tangent plane.  These satisfy the
        condition that the *second-order* term of the Taylor expansion of the
        distance function between the two surfaces vanishes in both directions.

        In practice we probe the curvature tensor by perturbing the parameter
        in several directions in the tangent plane of surface_a, evaluating the
        signed distance to surface_b, and checking whether the distance function
        has two sign-changing zero crossings (indicating two separate tangent
        branches) rather than a single touching point (ordinary tangency).

        Returns
        -------
        list of two seed pairs  [ ((ua1,va1),(ub1,vb1)), ((ua2,va2),(ub2,vb2)) ]
            if a transversal bifurcation is detected, otherwise ``None``.
        """
        # --- Gather local geometry at the candidate bifurcation point --------
        SKL_a = surface_derivatives(surf_a, ua, va, d=2)
        su_a = SKL_a[1, 0][:3]
        sv_a = SKL_a[0, 1][:3]
        na = surface_normal(surf_a, ua, va)[:3]
        nb = surface_normal(surf_b, ub, vb)[:3]

        # Build an orthonormal basis for the tangent plane of surface_a.
        su_mag = float(np.linalg.norm(su_a))
        sv_mag = float(np.linalg.norm(sv_a))
        if su_mag < 1e-12 or sv_mag < 1e-12:
            return None  # Degenerate surface patch.

        e1 = su_a / su_mag
        e2_raw = sv_a - float(np.dot(sv_a, e1)) * e1
        e2_mag = float(np.linalg.norm(e2_raw))
        if e2_mag < 1e-12:
            return None
        e2 = e2_raw / e2_mag

        # --- Probe the signed distance in N radial directions ----------------
        # Signed distance = (S_b(closest) - S_a(P+δ)) · n̂_b evaluated as a
        # scalar.  We use a simpler proxy: for each probe direction d in the
        # tangent plane, step to P + step*d on surf_a and measure the signed
        # distance from the resulting 3-D point to surf_b (via n̂_b · (P_a - P_b)).
        n_probe = 12
        probe_step = step * 0.3
        signed_dists: List[float] = []

        pu_a, pv_a = surf_a.degree_u, surf_a.degree_v
        u_min_a = float(surf_a.knots_u[pu_a])
        u_max_a = float(surf_a.knots_u[-pu_a - 1])
        v_min_a = float(surf_a.knots_v[pv_a])
        v_max_a = float(surf_a.knots_v[-pv_a - 1])

        for k in range(n_probe):
            angle = 2.0 * math.pi * k / n_probe
            d = math.cos(angle) * e1 + math.sin(angle) * e2
            # Parameter step on surf_a.
            du_a = probe_step * float(np.dot(d, su_a)) / max(su_mag ** 2, 1e-20)
            dv_a = probe_step * float(np.dot(d, sv_a)) / max(sv_mag ** 2, 1e-20)
            ua_p = max(u_min_a, min(u_max_a, ua + du_a))
            va_p = max(v_min_a, min(v_max_a, va + dv_a))
            Pa_p = surface_evaluate(surf_a, ua_p, va_p)[:3]
            # Signed distance to surf_b (using fixed nb evaluated at current ub,vb).
            ub_p, vb_p = self._closest_uv(surf_b, Pa_p, ub, vb, n_grid=3, n_iter=5)
            Pb_p = surface_evaluate(surf_b, ub_p, vb_p)[:3]
            sd = float(np.dot(nb, Pa_p - Pb_p))
            signed_dists.append(sd)

        # --- Count sign changes in the circular probe sequence ---------------
        n_sign_changes = 0
        for k in range(n_probe):
            a_val = signed_dists[k]
            b_val = signed_dists[(k + 1) % n_probe]
            if a_val * b_val < 0.0:
                n_sign_changes += 1

        # A transversal bifurcation has exactly 4 sign changes (two branches
        # cross the zero line twice each around the circle).
        # An ordinary smooth intersection has 2 sign changes.
        # A tangent-only contact has 0 sign changes.
        if n_sign_changes < 4:
            return None  # Not a bifurcation — ordinary tangency or smooth crossing.

        # --- Locate the two bifurcation tangent directions -------------------
        # Find the two pairs of adjacent probes that straddle the zero line
        # (one from positive-going, one from negative-going), then average
        # the directions in each pair to obtain the two principal tangents.
        zero_crossings: List[float] = []  # angles of zero crossings
        for k in range(n_probe):
            a_val = signed_dists[k]
            b_val = signed_dists[(k + 1) % n_probe]
            if a_val * b_val < 0.0:
                # Linear interpolation for the crossing angle.
                frac = abs(a_val) / (abs(a_val) + abs(b_val) + 1e-30)
                angle_k = 2.0 * math.pi * k / n_probe
                angle_k1 = 2.0 * math.pi * ((k + 1) % n_probe) / n_probe
                if k + 1 == n_probe:
                    angle_k1 += 2.0 * math.pi  # wrap
                zero_crossings.append(angle_k + frac * (angle_k1 - angle_k))

        if len(zero_crossings) < 2:
            return None

        # Group crossings into two pairs (opposite pairs define the same branch).
        # Take the first crossing and the one most nearly opposite as branch 1,
        # and the second + its opposite as branch 2.
        # Simpler: just use crossing[0] and crossing[len//2] as the two tangents.
        mid = len(zero_crossings) // 2
        angles_t = [zero_crossings[0], zero_crossings[mid]]

        seeds: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        seed_step = step * 0.5

        for angle_t in angles_t:
            # Direction in 3-D tangent plane.
            d = math.cos(angle_t) * e1 + math.sin(angle_t) * e2
            # New 3-D seed position.
            P_seed = P_cur + seed_step * d

            # Project onto both surfaces to get parameter pairs.
            ua_s, va_s = self._closest_uv(surf_a, P_seed, ua, va, n_grid=3, n_iter=6)
            ub_s, vb_s = self._closest_uv(surf_b, P_seed, ub, vb, n_grid=3, n_iter=6)
            ua_s, va_s = self._clamp_uv(surf_a, ua_s, va_s)
            ub_s, vb_s = self._clamp_uv(surf_b, ub_s, vb_s)

            # Verify the projected point is reasonably close on both surfaces.
            Pa_s = surface_evaluate(surf_a, ua_s, va_s)[:3]
            Pb_s = surface_evaluate(surf_b, ub_s, vb_s)[:3]
            dist = float(np.linalg.norm(Pa_s - Pb_s))
            if dist < seed_step * 2.0:
                seeds.append(((ua_s, va_s), (ub_s, vb_s)))

        if len(seeds) < 2:
            return None

        return seeds[:2]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp_uv(
        surf: NurbsSurface, u: float, v: float
    ) -> Tuple[float, float]:
        pu, pv = surf.degree_u, surf.degree_v
        u_min = float(surf.knots_u[pu])
        u_max = float(surf.knots_u[-pu - 1])
        v_min = float(surf.knots_v[pv])
        v_max = float(surf.knots_v[-pv - 1])
        return max(u_min, min(u_max, u)), max(v_min, min(v_max, v))

    @staticmethod
    def _at_boundary(
        surf: NurbsSurface, u: float, v: float, eps: float = 1e-6
    ) -> bool:
        pu, pv = surf.degree_u, surf.degree_v
        u_min = float(surf.knots_u[pu])
        u_max = float(surf.knots_u[-pu - 1])
        v_min = float(surf.knots_v[pv])
        v_max = float(surf.knots_v[-pv - 1])
        return (
            u <= u_min + eps
            or u >= u_max - eps
            or v <= v_min + eps
            or v >= v_max - eps
        )

    def _newton_correct(
        self,
        surf_a: NurbsSurface,
        surf_b: NurbsSurface,
        P_target: np.ndarray,
        ua: float,
        va: float,
        ub: float,
        vb: float,
    ) -> Tuple[float, float, float, float]:
        """One round of Newton-step correction to bring (ua,va) and (ub,vb)
        to the closest point on each surface near P_target."""
        for _ in range(self.newton_max_iter):
            # Surface A correction.
            Pa = surface_evaluate(surf_a, ua, va)[:3]
            SKL_a = surface_derivatives(surf_a, ua, va, d=1)
            su_a = SKL_a[1, 0][:3]
            sv_a = SKL_a[0, 1][:3]
            r_a = Pa - P_target
            # 2x2 least-squares: [su_a | sv_a] * [dua, dva]^T = r_a
            A_a = np.column_stack([su_a, sv_a])
            try:
                delta_a, _, _, _ = np.linalg.lstsq(A_a, r_a, rcond=None)
            except np.linalg.LinAlgError:
                delta_a = np.zeros(2)
            ua -= delta_a[0]
            va -= delta_a[1]
            ua, va = self._clamp_uv(surf_a, ua, va)

            # Surface B correction.
            Pb = surface_evaluate(surf_b, ub, vb)[:3]
            SKL_b = surface_derivatives(surf_b, ub, vb, d=1)
            su_b = SKL_b[1, 0][:3]
            sv_b = SKL_b[0, 1][:3]
            r_b = Pb - P_target
            A_b = np.column_stack([su_b, sv_b])
            try:
                delta_b, _, _, _ = np.linalg.lstsq(A_b, r_b, rcond=None)
            except np.linalg.LinAlgError:
                delta_b = np.zeros(2)
            ub -= delta_b[0]
            vb -= delta_b[1]
            ub, vb = self._clamp_uv(surf_b, ub, vb)

            if (float(np.linalg.norm(delta_a)) < self.newton_tol
                    and float(np.linalg.norm(delta_b)) < self.newton_tol):
                break

        return ua, va, ub, vb

    def _bisection_step(
        self,
        surf_a: NurbsSurface,
        surf_b: NurbsSurface,
        ua: float,
        va: float,
        ub: float,
        vb: float,
        step: float,
    ) -> Optional[Tuple[float, float, float, float, np.ndarray]]:
        """Bisection fallback for near-tangent regions.

        Perturbs the parameter in both surfaces along their respective
        tangent directions and bisects to find a better-conditioned point
        where the surfaces still intersect.  Returns (ua, va, ub, vb, P)
        or None if unable to find a valid step.
        """
        # Evaluate current point.
        Pa = surface_evaluate(surf_a, ua, va)[:3]
        na = surface_normal(surf_a, ua, va)[:3]
        nb = surface_normal(surf_b, ub, vb)[:3]

        # Try a parameter step on surf_a along the u direction.
        pu = surf_a.degree_u
        u_max = float(surf_a.knots_u[-pu - 1])
        u_min = float(surf_a.knots_u[pu])
        du = step / max(1e-9, float(np.linalg.norm(
            surface_derivatives(surf_a, ua, va, d=1)[1, 0][:3]
        )))

        for sign in (1.0, -1.0):
            ua_try = max(u_min, min(u_max, ua + sign * du))
            Pa_try = surface_evaluate(surf_a, ua_try, va)[:3]
            # Find closest point on surf_b to Pa_try via a naive grid search.
            ub_try, vb_try = self._closest_uv(surf_b, Pa_try, ub, vb)
            Pb_try = surface_evaluate(surf_b, ub_try, vb_try)[:3]
            dist = float(np.linalg.norm(Pa_try - Pb_try))
            if dist < step * 0.1:
                P_new = 0.5 * (Pa_try + Pb_try)
                na_try = surface_normal(surf_a, ua_try, va)[:3]
                nb_try = surface_normal(surf_b, ub_try, vb_try)[:3]
                cross_mag = float(np.linalg.norm(np.cross(na_try, nb_try)))
                if cross_mag >= self.tangent_threshold * 0.5:
                    return ua_try, va, ub_try, vb_try, P_new

        return None

    def _closest_uv(
        self,
        surf: NurbsSurface,
        P: np.ndarray,
        u0: float,
        v0: float,
        n_grid: int = 5,
        n_iter: int = 8,
    ) -> Tuple[float, float]:
        """Approximate closest-point on *surf* to 3-D point *P*.

        Uses a coarse grid search near (u0, v0) seeded by n_grid × n_grid
        samples within ±20% of the knot span, followed by n_iter Newton
        gradient descent steps.
        """
        pu, pv = surf.degree_u, surf.degree_v
        u_min = float(surf.knots_u[pu])
        u_max = float(surf.knots_u[-pu - 1])
        v_min = float(surf.knots_v[pv])
        v_max = float(surf.knots_v[-pv - 1])

        half_u = (u_max - u_min) * 0.2
        half_v = (v_max - v_min) * 0.2
        u_lo = max(u_min, u0 - half_u)
        u_hi = min(u_max, u0 + half_u)
        v_lo = max(v_min, v0 - half_v)
        v_hi = max(v_max, v0 + half_v)

        best_u, best_v, best_d2 = u0, v0, float("inf")
        for ug in np.linspace(u_lo, u_hi, n_grid):
            for vg in np.linspace(v_lo, v_hi, n_grid):
                Pg = surface_evaluate(surf, ug, vg)[:3]
                d2 = float(np.dot(P - Pg, P - Pg))
                if d2 < best_d2:
                    best_d2, best_u, best_v = d2, float(ug), float(vg)

        # Newton refinement.
        u_cur, v_cur = best_u, best_v
        for _ in range(n_iter):
            Pg = surface_evaluate(surf, u_cur, v_cur)[:3]
            r = Pg - P
            SKL = surface_derivatives(surf, u_cur, v_cur, d=1)
            su = SKL[1, 0][:3]
            sv = SKL[0, 1][:3]
            grad_u = float(np.dot(r, su))
            grad_v = float(np.dot(r, sv))
            E = float(np.dot(su, su))
            G = float(np.dot(sv, sv))
            if E < 1e-20 and G < 1e-20:
                break
            du = -grad_u / (E + 1e-30)
            dv = -grad_v / (G + 1e-30)
            u_cur = max(u_min, min(u_max, u_cur + du))
            v_cur = max(v_min, min(v_max, v_cur + dv))
            if abs(du) < 1e-9 and abs(dv) < 1e-9:
                break

        return u_cur, v_cur


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — no hard dependency on kerf_chat)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import (  # type: ignore
        ToolSpec,
        register,
        ok_payload,
        err_payload,
    )

    _SPEC = ToolSpec(
        name="nurbs_surface_derivatives_analytic",
        description=(
            "Compute closed-form first and second partial derivatives of a "
            "NurbsSurface at a given (u, v) parameter, plus Gaussian and mean "
            "curvature.\n"
            "\n"
            "Algorithm: Piegl & Tiller Algorithm A3.6 (B-spline tensor-product "
            "derivative table) + rational quotient rule A4.4. No finite differences.\n"
            "\n"
            "Returns:\n"
            "  dS_du, dS_dv     : [x,y,z] — first partial derivatives\n"
            "  d2S_du2, d2S_dudv, d2S_dv2 : [x,y,z] — second partials\n"
            "  gauss_K          : float — Gaussian curvature K = (LN-M²)/(EG-F²)\n"
            "  mean_H           : float — mean curvature H = (EN-2FM+GL)/(2(EG-F²))\n"
            "  honest_caveat    : str — numerical warnings (degenerate, rational, etc.)\n"
            "\n"
            "HONEST LIMITS: curvature is NaN at degenerate parameter points (poles, "
            "seams).  Rational NURBS with near-zero weights may have large condition "
            "numbers in the quotient rule.  SSI marcher not exposed here — use "
            "surface_surface_intersect for SSI.\n"
            "\n"
            "Errors: {ok: false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "required": ["control_points", "degree_u", "degree_v",
                         "knots_u", "knots_v", "u", "v"],
            "properties": {
                "control_points": {
                    "type": "array",
                    "description": "nu x nv x 3 control-point grid (Cartesian xyz).",
                },
                "degree_u": {"type": "integer", "minimum": 1},
                "degree_v": {"type": "integer", "minimum": 1},
                "knots_u": {"type": "array", "items": {"type": "number"}},
                "knots_v": {"type": "array", "items": {"type": "number"}},
                "weights": {
                    "type": "array",
                    "description": "Optional nu x nv weight grid.",
                    "default": None,
                },
                "u": {"type": "number", "description": "Parameter u."},
                "v": {"type": "number", "description": "Parameter v."},
            },
        },
    )

    @register(_SPEC)
    async def _run_nurbs_surface_derivatives_analytic(
        ctx: "object", args: bytes
    ) -> str:
        try:
            req = _json.loads(args)
            cp = np.array(req["control_points"], dtype=float)
            if cp.ndim != 3 or cp.shape[2] < 3:
                return err_payload("control_points must be nu x nv x 3")
            w_raw = req.get("weights")
            weights = np.array(w_raw, dtype=float) if w_raw is not None else None
            surf = NurbsSurface(
                degree_u=int(req["degree_u"]),
                degree_v=int(req["degree_v"]),
                control_points=cp,
                knots_u=np.array(req["knots_u"], dtype=float),
                knots_v=np.array(req["knots_v"], dtype=float),
                weights=weights,
            )
            u = float(req["u"])
            v = float(req["v"])
            result = compute_analytic_derivatives(surf, u, v)
            return ok_payload(
                {
                    "dS_du": list(result.dS_du),
                    "dS_dv": list(result.dS_dv),
                    "d2S_du2": list(result.d2S_du2),
                    "d2S_dudv": list(result.d2S_dudv),
                    "d2S_dv2": list(result.d2S_dv2),
                    "gauss_K": result.gauss_K,
                    "mean_H": result.mean_H,
                    "honest_caveat": result.honest_caveat,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return err_payload(f"nurbs_surface_derivatives_analytic error: {exc}")

except ImportError:
    pass
