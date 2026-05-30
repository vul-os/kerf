"""
NURBS-NORMAL-CURVATURE-AT-POINT
=================================
Normal curvature of a NURBS surface in a given tangent direction at (u, v).

Theory
------
References:
  do Carmo, "Differential Geometry of Curves and Surfaces", §3 (1976).
  Mortenson, "Geometric Modeling", §10.4 (2nd ed., 1997).

Meusnier's theorem (do Carmo §3.2): for any curve on the surface passing
through a point with tangent direction **t**, the normal curvature is the
projection of the curvature vector onto the surface normal.  For a surface
S(u,v) with tangent direction (du, dv) in parameter space:

  κ_n = II(t, t) / I(t, t)

where I is the first fundamental form (metric tensor, E, F, G) and II is
the second fundamental form (shape operator, L, M, N):

  I(t,t)  = E·du² + 2F·du·dv + G·dv²
  II(t,t) = L·du² + 2M·du·dv + N·dv²

Coefficients are:
  E = S_u · S_u
  F = S_u · S_v
  G = S_v · S_v
  L = S_uu · n̂   (n̂ = unit surface normal)
  M = S_uv · n̂
  N = S_vv · n̂

Principal curvatures κ_1, κ_2 are eigenvalues of the shape operator
  [FI]⁻¹ [FII]
i.e. solve det([FII] − κ [FI]) = 0 (Mortenson §10.4 Eq. 10.53):

  (E·G − F²)·κ² − (E·N − 2F·M + G·L)·κ + (L·N − M²) = 0

Gauss curvature:  K = (L·N − M²) / (E·G − F²)
Mean curvature:   H = (E·N − 2F·M + G·L) / (2·(E·G − F²))

Euler's formula (do Carmo §3.2 Prop 3):
  κ_n(θ) = κ_1·cos²(θ − φ) + κ_2·sin²(θ − φ)
where φ is the angle of the first principal direction in the (S_u, S_v) frame.

Umbilic points
--------------
At an umbilic point κ_1 = κ_2 (every direction is principal).  In this case
the shape operator is a scalar multiple of the identity in any orthonormal
basis of the tangent plane, and `principal_dirs` is set to `None` with an
`is_umbilic=True` flag.  The computed κ_n and κ_1, κ_2 values are still
valid; only the principal direction vectors are undefined.

Degenerate surface points
--------------------------
If the first fundamental form is degenerate (|S_u × S_v| ≈ 0, e.g. a pole),
the result dataclass carries `is_degenerate=True` and κ_n = 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives

# Tolerances ──────────────────────────────────────────────────────────────────
_DEGENERATE_TOL = 1e-12   # |E·G − F²| below this → degenerate
_UMBILIC_TOL = 1e-6       # |κ_1 − κ_2| below this → umbilic


@dataclass
class NormalCurvatureReport:
    """Result of :func:`normal_curvature_at`.

    Attributes
    ----------
    u, v : float
        The surface parameter point.
    direction_uv : tuple[float, float]
        The requested tangent direction (du, dv) — normalised so that I=1.
    kappa_n : float
        Normal curvature in the requested direction.
    kappa_1, kappa_2 : float
        Principal curvatures (κ_1 ≤ κ_2).
    K : float
        Gauss curvature = κ_1 · κ_2.
    H : float
        Mean curvature = (κ_1 + κ_2) / 2.
    principal_dirs : list[tuple[float, float]] | None
        The two principal directions in (du, dv) parameter space as unit
        vectors.  ``None`` at umbilic points (κ_1 = κ_2).
    is_umbilic : bool
        True when |κ_1 − κ_2| < _UMBILIC_TOL.  Principal directions are
        undefined; all tangent directions share the same normal curvature.
    is_degenerate : bool
        True when the first fundamental form determinant ≈ 0 (pole or other
        singular surface point).  All curvature values are unreliable.
    """

    u: float
    v: float
    direction_uv: Tuple[float, float]
    kappa_n: float
    kappa_1: float
    kappa_2: float
    K: float
    H: float
    principal_dirs: Optional[List[Tuple[float, float]]]
    is_umbilic: bool = field(default=False)
    is_degenerate: bool = field(default=False)


def normal_curvature_at(
    srf: NurbsSurface,
    u: float,
    v: float,
    direction_uv: Tuple[float, float],
) -> NormalCurvatureReport:
    """Normal curvature of *srf* at (u, v) in the direction (du, dv).

    Parameters
    ----------
    srf : NurbsSurface
        The NURBS surface (degree ≥ 1, any rational weighting).
    u, v : float
        Parameter values in the clamped domain.
    direction_uv : (du, dv)
        Tangent direction in parameter space.  Need not be unit-normalised;
        the formula is scale-invariant via the I(t,t) denominator.

    Returns
    -------
    NormalCurvatureReport
        See dataclass docstring.

    Notes
    -----
    Algorithm follows do Carmo §3.2 / Mortenson §10.4.

    For a unit sphere of radius R centred at the origin, κ_n = 1/R in every
    direction at every regular point.

    For a cylinder of radius R with axis along Z, evaluated at a point on the
    surface:
      - along the axis (dv direction corresponding to Z): κ_n = 0
      - across the axis (du direction corresponding to the circle): κ_n = 1/R

    Euler's formula is verified by the tests:
      κ_n(θ) = κ_1·cos²(θ−φ) + κ_2·sin²(θ−φ)
    """
    u = float(u)
    v = float(v)
    du, dv = float(direction_uv[0]), float(direction_uv[1])

    # ── step 1: second-order partial derivatives ──────────────────────────────
    # SKL[k, l] = ∂^{k+l} S / ∂u^k ∂v^l
    SKL = surface_derivatives(srf, u, v, d=2)

    Su  = SKL[1, 0][:3]
    Sv  = SKL[0, 1][:3]
    Suu = SKL[2, 0][:3]
    Suv = SKL[1, 1][:3]
    Svv = SKL[0, 2][:3]

    # ── step 2: unit surface normal ───────────────────────────────────────────
    nrm = np.cross(Su, Sv)
    mag = float(np.linalg.norm(nrm))
    if mag < _DEGENERATE_TOL:
        # Degenerate point (pole, etc.)
        return NormalCurvatureReport(
            u=u, v=v, direction_uv=(du, dv),
            kappa_n=0.0, kappa_1=0.0, kappa_2=0.0,
            K=0.0, H=0.0, principal_dirs=None,
            is_umbilic=False, is_degenerate=True,
        )
    n_hat = nrm / mag

    # ── step 3: first fundamental form (E, F, G) ─────────────────────────────
    E = float(np.dot(Su, Su))
    F = float(np.dot(Su, Sv))
    G = float(np.dot(Sv, Sv))

    det_I = E * G - F * F
    if abs(det_I) < _DEGENERATE_TOL:
        return NormalCurvatureReport(
            u=u, v=v, direction_uv=(du, dv),
            kappa_n=0.0, kappa_1=0.0, kappa_2=0.0,
            K=0.0, H=0.0, principal_dirs=None,
            is_umbilic=False, is_degenerate=True,
        )

    # ── step 4: second fundamental form (L, M, N_coeff) ──────────────────────
    L = float(np.dot(Suu, n_hat))
    M = float(np.dot(Suv, n_hat))
    N = float(np.dot(Svv, n_hat))

    # ── step 5: normal curvature κ_n (Meusnier — do Carmo §3.2) ──────────────
    I_tt  = E * du * du + 2.0 * F * du * dv + G * dv * dv
    II_tt = L * du * du + 2.0 * M * du * dv + N * dv * dv

    if abs(I_tt) < _DEGENERATE_TOL:
        # direction (du, dv) is the zero vector — undefined
        return NormalCurvatureReport(
            u=u, v=v, direction_uv=(du, dv),
            kappa_n=0.0, kappa_1=0.0, kappa_2=0.0,
            K=0.0, H=0.0, principal_dirs=None,
            is_umbilic=False, is_degenerate=True,
        )

    kappa_n = II_tt / I_tt

    # ── step 6: principal curvatures (eigenvalues of shape operator) ──────────
    # Characteristic equation (Mortenson §10.4 Eq. 10.53):
    #   det_I · κ² − (E·N − 2F·M + G·L) · κ + (L·N − M²) = 0
    a_coef = det_I
    b_coef = -(E * N - 2.0 * F * M + G * L)
    c_coef = L * N - M * M

    discriminant = b_coef * b_coef - 4.0 * a_coef * c_coef
    discriminant = max(0.0, discriminant)  # numerical guard

    sqrt_disc = math.sqrt(discriminant)
    kappa_1 = (-b_coef - sqrt_disc) / (2.0 * a_coef)
    kappa_2 = (-b_coef + sqrt_disc) / (2.0 * a_coef)
    # Ensure kappa_1 ≤ kappa_2
    if kappa_1 > kappa_2:
        kappa_1, kappa_2 = kappa_2, kappa_1

    K_gauss = c_coef / a_coef          # = κ_1 · κ_2
    H_mean  = -b_coef / (2.0 * a_coef) # = (κ_1 + κ_2) / 2

    # ── step 7: principal directions ─────────────────────────────────────────
    is_umbilic = abs(kappa_2 - kappa_1) < _UMBILIC_TOL
    principal_dirs: Optional[List[Tuple[float, float]]]

    if is_umbilic:
        principal_dirs = None
    else:
        # The principal directions satisfy (Mortenson §10.4 Eq. 10.55):
        #   (F·M − G·L) du² + (G·L − E·N) du·dv + (E·M − F·L) dv² = 0
        # ... equivalently, for each principal curvature κ_i:
        #   (L − κ_i·E) du + (M − κ_i·F) dv = 0  (first row of shape eqn)
        # So the direction for κ_i is (dv=1, du = −(M − κ_i·F)/(L − κ_i·E))
        # with a fallback to the second row when the denominator is near zero.
        dirs = []
        for kk in (kappa_1, kappa_2):
            A11 = L - kk * E
            A12 = M - kk * F
            # A21 = M - kk * F  (same)
            A22 = N - kk * G
            # Solve [A11 A12; A12 A22][du; dv] = 0 for the null vector.
            if abs(A11) > abs(A22):
                # |A11| dominates: du = -A12/A11 · dv; set dv=1
                dv_p = 1.0
                du_p = -A12 / A11 if abs(A11) > 1e-14 else 0.0
            else:
                # |A22| dominates: dv = -A12/A22 · du; set du=1
                du_p = 1.0
                dv_p = -A12 / A22 if abs(A22) > 1e-14 else 0.0
            # Normalize in metric I: ||t||_I² = E du² + 2F du dv + G dv²
            norm_sq = E * du_p * du_p + 2.0 * F * du_p * dv_p + G * dv_p * dv_p
            if norm_sq > 1e-28:
                scale = 1.0 / math.sqrt(norm_sq)
                dirs.append((du_p * scale, dv_p * scale))
            else:
                dirs.append((du_p, dv_p))
        principal_dirs = dirs

    return NormalCurvatureReport(
        u=u, v=v, direction_uv=(du, dv),
        kappa_n=float(kappa_n),
        kappa_1=float(kappa_1),
        kappa_2=float(kappa_2),
        K=float(K_gauss),
        H=float(H_mean),
        principal_dirs=principal_dirs,
        is_umbilic=is_umbilic,
        is_degenerate=False,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _spec = ToolSpec(
        name="nurbs_normal_curvature_at_point",
        description=(
            "Compute the normal curvature of a NURBS surface at a UV point in a "
            "given tangent direction (Meusnier's theorem, do Carmo §3.2 / "
            "Mortenson §10.4).\n"
            "\n"
            "Returns:\n"
            "  kappa_n       — normal curvature in the requested direction\n"
            "  kappa_1/2     — principal curvatures (κ_1 ≤ κ_2)\n"
            "  K             — Gauss curvature = κ_1 · κ_2\n"
            "  H             — mean curvature = (κ_1 + κ_2)/2\n"
            "  principal_dirs — two principal directions in (du,dv) parameter "
            "space (null at umbilic points where κ_1=κ_2)\n"
            "  is_umbilic    — true when κ_1≈κ_2 (sphere, umbilic point)\n"
            "  is_degenerate — true at poles / degenerate surface points\n"
            "\n"
            "Analytic oracles:\n"
            "  • Unit sphere → κ_n=1 in every direction, K=1, H=1, is_umbilic=true.\n"
            "  • Cylinder R → along-axis direction κ_n=0; across-axis κ_n=1/R.\n"
            "  • Saddle z=xy → mixed-sign principal curvatures.\n"
            "\n"
            "Euler's formula: κ_n(θ) = κ_1·cos²(θ-φ) + κ_2·sin²(θ-φ).\n"
            "\n"
            "Never raises — returns {ok:false, reason} for invalid inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer", "description": "B-spline degree in u."},
                "degree_v": {"type": "integer", "description": "B-spline degree in v."},
                "control_points": {
                    "type": "array",
                    "description": "Control-point grid — list of rows, each row a list of [x,y,z] points.",
                    "items": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                },
                "knots_u": {
                    "type": "array",
                    "description": "Knot vector in u.",
                    "items": {"type": "number"},
                },
                "knots_v": {
                    "type": "array",
                    "description": "Knot vector in v.",
                    "items": {"type": "number"},
                },
                "weights": {
                    "type": "array",
                    "description": "Optional (nu×nv) weight grid (rational NURBS).",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "u": {"type": "number", "description": "Parameter u."},
                "v": {"type": "number", "description": "Parameter v."},
                "direction_uv": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[du, dv] tangent direction in parameter space (need not be unit).",
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "knots_u", "knots_v", "u", "v", "direction_uv"],
        },
    )

    @register(_spec)
    def _tool_nurbs_normal_curvature(params: dict, ctx: "ProjectCtx"):  # type: ignore[type-arg]
        try:
            import numpy as _np
            deg_u = int(params["degree_u"])
            deg_v = int(params["degree_v"])
            cps_raw = params["control_points"]
            cps = _np.array(cps_raw, dtype=float)
            if cps.ndim != 3:
                raise ValueError("control_points must be 3-D array (nu x nv x dim)")
            knots_u = _np.array(params["knots_u"], dtype=float)
            knots_v = _np.array(params["knots_v"], dtype=float)
            weights = params.get("weights")
            if weights is not None:
                weights = _np.array(weights, dtype=float)
            srf = NurbsSurface(
                degree_u=deg_u, degree_v=deg_v,
                control_points=cps, knots_u=knots_u, knots_v=knots_v,
                weights=weights,
            )
            u = float(params["u"])
            v = float(params["v"])
            dir_uv = params["direction_uv"]
            result = normal_curvature_at(srf, u, v, (float(dir_uv[0]), float(dir_uv[1])))
            return ok_payload({
                "kappa_n": result.kappa_n,
                "kappa_1": result.kappa_1,
                "kappa_2": result.kappa_2,
                "K": result.K,
                "H": result.H,
                "principal_dirs": result.principal_dirs,
                "is_umbilic": result.is_umbilic,
                "is_degenerate": result.is_degenerate,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
