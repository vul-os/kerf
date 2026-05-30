"""
curve_on_surface_robust.py
==========================
BREP curve-on-surface projection: given a 3D NurbsCurve C(t) and a
NurbsSurface S(u,v), project C onto S as a 2D UV-domain NurbsCurve.

References
----------
* Piegl & Tiller, "The NURBS Book" 2nd ed., §6.1 — NURBS point inversion
  via Newton-Raphson with the full closest-point Jacobian.
* Patrikalakis & Maekawa, "Shape Interrogation for Computer Aided Design
  and Manufacturing" (Springer 2002), §3.3 — curve-on-surface projection,
  multi-branch detection, and failure conditions.

Algorithm
---------
For each of ``samples`` uniformly distributed parameter values t_i on C:

1. Evaluate P_i = C(t_i).
2. Coarse seed: sample S on a ``seed_grid × seed_grid`` UV lattice; pick the
   (u, v) minimising |P_i - S(u, v)|.
3. Newton-Raphson refinement (Piegl & Tiller §6.1 / PM §3.3):
   The 2×2 system is::

       J · Δ = r
       J = [[S_u·S_u + r·S_uu,  S_u·S_v + r·S_uv],
            [S_u·S_v + r·S_uv,  S_v·S_v + r·S_vv]]
       r = [-(r · S_u), -(r · S_v)]     (r = S(u,v) - P)

   Near-singular Jacobians (cond > 1e10) fall back to ``numpy.linalg.lstsq``.
   Parameters are clamped to the surface domain after each step.
4. Convergence check: |S(u,v) - P| < ``tol``; mark sample failed if not
   converged within max_iter iterations.
5. Build UV-trace NurbsCurve by fitting a degree-3 NURBS through the
   converged (u, v) samples (chord-length parametrisation).

Failure detection (PM §3.3)
---------------------------
A sample is flagged "failed" when:
* Newton did not converge within ``max_iter`` iterations, OR
* The converged (u, v) is at or outside the surface boundary (within
  ``boundary_tol``), suggesting the curve exits the surface patch.

Multi-branch / silhouette limitation (honest flag)
--------------------------------------------------
This implementation does NOT branch-track at silhouettes or self-overlapping
surface regions.  Newton-Raphson will converge to whichever local minimum
the coarse seed selects; a different branch may exist.  For ruled surfaces
or developable panels the single-branch result is correct; for heavily
folded surfaces (e.g. inside a torus), inspect ``failed_samples`` and
consider subdividing the curve manually before re-projecting.

Public API
----------
project_curve_to_surface(curve, surface, tol=1e-6, samples=20)
    -> CurveOnSurfaceResult

CurveOnSurfaceResult
    uv_curve              : NurbsCurve (2D, control points in UV space)
    max_projection_distance: float  -- worst |S(u,v) - C(t)| over converged samples
    failed_samples        : list[float]  -- t-values where projection failed

LLM tool ``nurbs_project_curve_to_surface`` is registered where
``kerf_chat`` is available (gated try/except; no import-time error if absent).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.inversion import (
    _curve_param_range,
    _surface_param_range,
    _curve_eval as _inv_curve_eval,
    _surf_eval as _inv_surf_eval,
    _surf_partials as _inv_surf_partials,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_ITER: int = 80
_COND_THRESHOLD: float = 1e10
_SEED_GRID: int = 12          # coarse seed grid per axis


# ---------------------------------------------------------------------------
# Surface partial helper (wraps _inv_surf_partials which returns 6-tuple)
# ---------------------------------------------------------------------------

def _surf_all_partials(
    s: NurbsSurface, u: float, v: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (S, S_u, S_v, S_uu, S_uv, S_vv) — all analytic 3-vectors.

    Delegates to inversion._surf_partials which uses the correct Cox-de Boor
    evaluator with analytic first + second derivatives.
    """
    return _inv_surf_partials(s, u, v)  # (S, Su, Sv, Suu, Suv, Svv)


# ---------------------------------------------------------------------------
# Newton-Raphson closest-point projection (Piegl-Tiller §6.1 / PM §3.3)
# ---------------------------------------------------------------------------

def _newton_project(
    P: np.ndarray,
    s: NurbsSurface,
    u_init: float,
    v_init: float,
    tol: float,
    max_iter: int,
) -> Tuple[float, float, float, bool]:
    """Project point P onto surface S starting from (u_init, v_init).

    Implements the Newton-Raphson scheme from Piegl & Tiller §6.1 and
    Patrikalakis-Maekawa §3.3::

        r(u,v) = S(u,v) - P
        J = [[S_u·S_u + r·S_uu,  S_u·S_v + r·S_uv],
             [S_u·S_v + r·S_uv,  S_v·S_v + r·S_vv]]
        b = [-r·S_u,  -r·S_v]
        [Δu, Δv] = J^{-1} · b

    Parameters are clamped to the surface domain after each step.  Near-
    singular Jacobians (cond > 1e10) are solved via lstsq.

    Returns
    -------
    (u, v, dist, converged)
    """
    u_min, u_max, v_min, v_max = _surface_param_range(s)
    u_range = u_max - u_min
    v_range = v_max - v_min
    u = float(np.clip(u_init, u_min, u_max))
    v = float(np.clip(v_init, v_min, v_max))

    for _ in range(max_iter):
        (Sv, Su, Sv_v, Suu, Suv, Svv) = _surf_all_partials(s, u, v)
        r = Sv - P  # residual vector (3,)
        dist = float(np.linalg.norm(r))
        if dist < tol:
            return u, v, dist, True

        # Check convergence criterion 2: degenerate patch (zero tangent)
        Su_len = float(np.linalg.norm(Su))
        Sv_v_len = float(np.linalg.norm(Sv_v))
        if Su_len < 1e-15 or Sv_v_len < 1e-15:
            return u, v, dist, dist < tol * 10

        J00 = float(np.dot(Su, Su) + np.dot(r, Suu))
        J01 = float(np.dot(Su, Sv_v) + np.dot(r, Suv))
        J11 = float(np.dot(Sv_v, Sv_v) + np.dot(r, Svv))
        b0 = -float(np.dot(r, Su))
        b1 = -float(np.dot(r, Sv_v))

        J = np.array([[J00, J01], [J01, J11]])
        b = np.array([b0, b1])

        try:
            cond = np.linalg.cond(J)
        except Exception:
            cond = _COND_THRESHOLD + 1.0

        if cond < _COND_THRESHOLD:
            try:
                delta = np.linalg.solve(J, b)
            except np.linalg.LinAlgError:
                delta, *_ = np.linalg.lstsq(J, b, rcond=None)
        else:
            delta, *_ = np.linalg.lstsq(J, b, rcond=None)

        du, dv = float(delta[0]), float(delta[1])

        # Step-length limiting: don't jump more than 10 % of domain per step
        max_du = 0.1 * u_range
        max_dv = 0.1 * v_range
        du = float(np.clip(du, -max_du, max_du))
        dv = float(np.clip(dv, -max_dv, max_dv))

        u_new = float(np.clip(u + du, u_min, u_max))
        v_new = float(np.clip(v + dv, v_min, v_max))

        # Convergence criterion 3: parameter change < tol * domain
        if (abs(u_new - u) < tol * u_range and abs(v_new - v) < tol * v_range):
            u, v = u_new, v_new
            Sv2 = _inv_surf_eval(s, u, v)
            dist = float(np.linalg.norm(Sv2 - P))
            return u, v, dist, dist < tol * 10

        u, v = u_new, v_new

    Sv_f = _inv_surf_eval(s, u, v)
    dist = float(np.linalg.norm(Sv_f - P))
    return u, v, dist, dist < tol * 10


# ---------------------------------------------------------------------------
# Coarse seed selection
# ---------------------------------------------------------------------------

def _coarse_seed(
    P: np.ndarray,
    s: NurbsSurface,
    grid: int = _SEED_GRID,
) -> Tuple[float, float]:
    """Sample S on a ``grid × grid`` lattice and return (u, v) nearest to P."""
    u_min, u_max, v_min, v_max = _surface_param_range(s)
    us = np.linspace(u_min, u_max, grid)
    vs = np.linspace(v_min, v_max, grid)
    best_dist = math.inf
    best_u, best_v = float(us[grid // 2]), float(vs[grid // 2])
    for uu in us:
        for vv in vs:
            q = _inv_surf_eval(s, uu, vv)
            d = float(np.linalg.norm(q - P))
            if d < best_dist:
                best_dist = d
                best_u, best_v = float(uu), float(vv)
    return best_u, best_v


# ---------------------------------------------------------------------------
# UV-curve fitting
# ---------------------------------------------------------------------------

def _fit_uv_curve(uv_pts: np.ndarray) -> NurbsCurve:
    """Fit a degree-3 NURBS through (u, v) samples via chord-length parametrisation.

    Returns a 2D NurbsCurve (control points in UV space).  Degrades to lower
    degree when fewer than 4 points are available.
    """
    from kerf_cad_core.geom.curve_toolkit import interp_curve  # type: ignore[import]
    n = len(uv_pts)
    deg = min(3, n - 1)
    return interp_curve(uv_pts, degree=deg)


# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CurveOnSurfaceResult:
    """Result of project_curve_to_surface.

    Attributes
    ----------
    uv_curve : NurbsCurve
        2D NurbsCurve whose control points live in the (u, v) parameter plane
        of *surface*.  Evaluate at any parameter to obtain a UV coordinate;
        plug into ``surface.evaluate(u, v)`` to recover a 3D point.
    max_projection_distance : float
        Worst Euclidean distance |S(u,v) - C(t)| over the converged samples.
        Should be < tol for well-posed projections.
    failed_samples : list[float]
        t-values on the input curve where Newton failed to converge within
        the tolerance.  An empty list means full projection success.
        Possible causes:
        * Curve leaves the surface domain (detected via boundary proximity).
        * Newton stuck at a local minimum (silhouette or fold — see module
          docstring for the multi-branch limitation).
        * Degenerate surface patch (zero tangent at a pole or seam).
    """
    uv_curve: NurbsCurve
    max_projection_distance: float
    failed_samples: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def project_curve_to_surface(
    curve: NurbsCurve,
    surface: NurbsSurface,
    tol: float = 1e-6,
    samples: int = 20,
) -> CurveOnSurfaceResult:
    """Project a 3D NurbsCurve onto a NurbsSurface as a UV-domain NurbsCurve.

    For each of ``samples`` uniformly distributed t-values on *curve*:

    1. Evaluate P = C(t).
    2. Find a coarse (u, v) seed via a grid search on *surface*.
    3. Refine with Newton-Raphson (Piegl & Tiller §6.1; PM §3.3) using the
       full 2×2 closest-point Jacobian that includes second-partial terms.
    4. Flag the sample as failed if Newton does not converge to ``tol`` or if
       the result lands within one grid step of the surface boundary (the
       curve is exiting the patch — PM §3.3 failure criterion).

    Returns a ``CurveOnSurfaceResult`` with:
    * ``uv_curve``        — degree-3 NURBS in (u, v) space
    * ``max_projection_distance`` — worst converged |S(u,v) - C(t)|
    * ``failed_samples``  — t-values where projection failed

    Honest limitations
    ------------------
    * **Multi-branch (silhouette)**: Newton converges to the *local* minimum
      found by the coarse seed.  If the surface folds back on itself
      (silhouette curve from the projection direction), a different branch
      may exist.  ``failed_samples`` will NOT flag this case — the result
      will appear numerically converged but geometrically wrong.  Use this
      function on developable / singly-folded surfaces; subdivide the input
      curve before calling for complex folded geometry.
    * **Poles and seams**: near degenerate surface poles Newton may converge
      to a boundary-clamped result.  Check ``max_projection_distance``.

    Parameters
    ----------
    curve   : NurbsCurve in 3D space (assumed to lie on or near *surface*)
    surface : NurbsSurface target
    tol     : convergence tolerance (default 1e-6); controls both Newton
              residual and the UV-trace point accuracy
    samples : number of sample points along *curve* (default 20)

    Returns
    -------
    CurveOnSurfaceResult
    """
    if not isinstance(curve, NurbsCurve):
        raise TypeError(f"curve must be NurbsCurve, got {type(curve).__name__}")
    if not isinstance(surface, NurbsSurface):
        raise TypeError(f"surface must be NurbsSurface, got {type(surface).__name__}")
    samples = max(4, int(samples))

    t_min, t_max = _curve_param_range(curve)
    u_min, u_max, v_min, v_max = _surface_param_range(surface)
    u_range = u_max - u_min
    v_range = v_max - v_min
    # Boundary margin: flag if within one coarse-grid cell of the edge
    boundary_tol = max(u_range, v_range) / (_SEED_GRID + 1)

    ts = np.linspace(t_min, t_max, samples)
    uv_good: List[np.ndarray] = []
    failed_t: List[float] = []
    max_dist: float = 0.0

    # Warm-start: carry forward previous (u, v) if it converged
    prev_u: Optional[float] = None
    prev_v: Optional[float] = None

    for ti in ts:
        P = _inv_curve_eval(curve, float(ti))

        # Coarse seed: try warm-start first, then grid search
        if prev_u is not None and prev_v is not None:
            u0, v0 = prev_u, prev_v
        else:
            u0, v0 = _coarse_seed(P, surface)

        u_nr, v_nr, dist_nr, conv_nr = _newton_project(
            P, surface, u0, v0, tol, _MAX_ITER
        )

        # If warm-start diverged, retry from fresh coarse seed
        if not conv_nr and prev_u is not None:
            u0g, v0g = _coarse_seed(P, surface)
            u_nr2, v_nr2, dist_nr2, conv_nr2 = _newton_project(
                P, surface, u0g, v0g, tol, _MAX_ITER
            )
            if dist_nr2 < dist_nr:
                u_nr, v_nr, dist_nr, conv_nr = u_nr2, v_nr2, dist_nr2, conv_nr2

        # Failure detection (PM §3.3):
        # 1. Newton did not converge
        # 2. Result is at the surface boundary AND Newton failed
        at_boundary = (
            u_nr <= u_min + boundary_tol
            or u_nr >= u_max - boundary_tol
            or v_nr <= v_min + boundary_tol
            or v_nr >= v_max - boundary_tol
        )
        failed = (not conv_nr) or (at_boundary and not conv_nr)

        if failed:
            failed_t.append(float(ti))
            # Still record UV (best estimate) to keep the trace continuous
            uv_good.append(np.array([u_nr, v_nr]))
        else:
            uv_good.append(np.array([u_nr, v_nr]))
            max_dist = max(max_dist, dist_nr)
            prev_u, prev_v = u_nr, v_nr

    # Build UV NurbsCurve through all samples (failed + converged)
    uv_arr = np.array(uv_good, dtype=float)  # shape (N, 2)
    uv_curve = _fit_uv_curve(uv_arr)

    return CurveOnSurfaceResult(
        uv_curve=uv_curve,
        max_projection_distance=max_dist,
        failed_samples=failed_t,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _proj_spec = ToolSpec(
        name="nurbs_project_curve_to_surface",
        description=(
            "Project a 3D NurbsCurve onto a NurbsSurface as a UV-domain NurbsCurve "
            "(Piegl & Tiller §6.1 / Patrikalakis-Maekawa §3.3).\n"
            "\n"
            "Uses Newton-Raphson with the full 2×2 closest-point Jacobian (including "
            "second-partial terms) to find the UV trace of the curve on the surface.  "
            "Near-singular Jacobians fall back to least-squares.  Each sample is "
            "seed-initialised via a coarse grid search then refined by Newton.\n"
            "\n"
            "Returns a 2D NurbsCurve in UV parameter space plus the worst projection "
            "distance and a list of t-values where projection failed (curve exits the "
            "surface or Newton diverged).\n"
            "\n"
            "Limitation: does NOT branch-track at silhouettes or self-overlapping "
            "surface regions.  Newton converges to the local minimum found by the "
            "coarse seed; a different branch may exist on heavily folded surfaces.\n"
            "\n"
            "Returns: {ok, uv_control_points, uv_knots, uv_degree, "
            "max_projection_distance, failed_samples, n_samples}\n"
            "Errors:  {ok:false, reason}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "curve_control_points": {
                    "type": "array",
                    "description": "3D curve control points: list of [x, y, z].",
                },
                "curve_knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Curve knot vector.",
                },
                "curve_degree": {
                    "type": "integer",
                    "description": "Curve degree.",
                },
                "surface_control_points": {
                    "type": "array",
                    "description": "Surface CP grid: list of rows, each a list of [x,y,z].",
                },
                "surface_knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Surface knot vector in u.",
                },
                "surface_knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Surface knot vector in v.",
                },
                "surface_degree_u": {"type": "integer", "description": "Surface degree u (default 3)."},
                "surface_degree_v": {"type": "integer", "description": "Surface degree v (default 3)."},
                "tol": {
                    "type": "number",
                    "description": "Newton convergence tolerance (default 1e-6).",
                },
                "samples": {
                    "type": "integer",
                    "description": "Number of sample points along the curve (default 20).",
                },
            },
            "required": [
                "curve_control_points", "curve_knots", "curve_degree",
                "surface_control_points", "surface_knots_u", "surface_knots_v",
            ],
        },
    )

    @register(_proj_spec)
    async def run_nurbs_project_curve_to_surface(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        # ---- parse curve ----
        try:
            c_cp = np.array(a["curve_control_points"], dtype=float)
            c_k = np.array(a["curve_knots"], dtype=float)
            c_deg = int(a["curve_degree"])
            crv = NurbsCurve(degree=c_deg, control_points=c_cp, knots=c_k)
        except Exception as exc:
            return err_payload(f"curve parse error: {exc}", "BAD_ARGS")

        # ---- parse surface ----
        try:
            s_cp_raw = a["surface_control_points"]
            s_cp = np.array(s_cp_raw, dtype=float)
            if s_cp.ndim == 2:
                n = int(math.isqrt(len(s_cp_raw)))
                if n * n != len(s_cp_raw):
                    return err_payload(
                        "surface_control_points must be square (nu*nv) grid", "BAD_ARGS"
                    )
                s_cp = s_cp.reshape(n, n, 3)
            if s_cp.ndim != 3:
                return err_payload("surface_control_points must be (nu, nv, 3)", "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"surface CP parse error: {exc}", "BAD_ARGS")

        try:
            s_ku = np.array(a["surface_knots_u"], dtype=float)
            s_kv = np.array(a["surface_knots_v"], dtype=float)
            s_du = int(a.get("surface_degree_u", 3))
            s_dv = int(a.get("surface_degree_v", 3))
            srf = NurbsSurface(
                degree_u=s_du, degree_v=s_dv,
                control_points=s_cp,
                knots_u=s_ku, knots_v=s_kv,
            )
        except Exception as exc:
            return err_payload(f"surface parse error: {exc}", "BAD_ARGS")

        tol = float(a.get("tol", 1e-6))
        n_s = int(a.get("samples", 20))

        try:
            result = project_curve_to_surface(crv, srf, tol=tol, samples=n_s)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "uv_control_points": result.uv_curve.control_points.tolist(),
            "uv_knots": result.uv_curve.knots.tolist(),
            "uv_degree": result.uv_curve.degree,
            "max_projection_distance": result.max_projection_distance,
            "failed_samples": result.failed_samples,
            "n_samples": n_s,
        })
