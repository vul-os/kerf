"""face_developable_check.py -- BREP-FACE-DEVELOPABLE-CHECK

Verify whether a B-rep face is *developable* — i.e. can be unrolled flat
without stretching or tearing.  Useful for sheet-metal flat patterns,
ruled-surface validation, and geometric design correctness.

Theory
------
A surface is developable if and only if its Gaussian curvature K = 0
everywhere (do Carmo §3.6 "Ruled and Developable Surfaces"; Pottmann &
Wallner, "Computational Line Geometry", §4).

  K = κ_1 · κ_2  where κ_1, κ_2 are the principal curvatures.

K = 0 at a point means at least one principal curvature vanishes — the
surface bends in at most one direction.  Canonical examples:

  * Plane:    K = 0 everywhere           → developable.
  * Cylinder: K = 0 everywhere           → developable.
  * Cone:     K = 0 along ruling lines   → developable (apex special case).
  * Sphere:   K = 1/R² > 0 everywhere   → NOT developable.
  * Torus:    K varies in sign           → NOT developable (outer belt K>0,
              inner belt K<0, mid-circle K=0).

For the ruling-line test (Pottmann-Wallner §4.1): a developable surface
is also a *ruled* surface, and one of the two principal curvatures is
identically zero along the ruling direction.  We report which principal
curvature (κ_1 or κ_2) is consistently near zero as a ruling indicator.

Algorithm
---------
1. Determine the UV domain from the surface knot vectors (fall back to
   [0,1]×[0,1] for analytic surfaces).
2. Sample the surface at an N×N grid (default N=10, yielding ≤100 points).
3. At each valid sample, query :func:`normal_curvature_at` in the (1,0)
   direction.  This also computes K, κ_1, κ_2 via the shape operator.
   Degenerate / pole points are skipped.
4. Compute max|K| and mean|K| over valid samples.
5. *is_developable* ← max|K| < tolerance.
6. *ruled_direction_if_any*: if κ_1 is zero everywhere (max|κ_1| <
   tolerance) report "kappa_1"; if κ_2 is zero everywhere report
   "kappa_2"; otherwise None.

Honest limitation
-----------------
The check is **sampling-based**.  A high-curvature region concentrated
between grid points can be missed.  For production quality: increase
``samples`` (e.g. 20–50), or use adaptive refinement near regions with
large |∇K|.  The ``max_abs_K`` value is a lower bound on the true
supremum of |K|; the honest-flag is always included in the report.

References
----------
do Carmo, M. P. (1976). *Differential Geometry of Curves and Surfaces*.
    §3.6 "Ruled and Developable Surfaces".

Pottmann, H., & Wallner, J. (2001). *Computational Line Geometry*.
    §4 "Developable Surfaces and Tangent Surfaces".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Face
from kerf_cad_core.geom.normal_curvature import normal_curvature_at
from kerf_cad_core.geom.nurbs import NurbsSurface

__all__ = [
    "DevelopabilityReport",
    "check_face_developable",
]

_DEFAULT_TOLERANCE = 1e-3
_DEFAULT_SAMPLES = 10


def _surface_uv_domain(surface) -> Tuple[float, float, float, float]:
    """Return (u_min, u_max, v_min, v_max) for the surface UV domain."""
    knots_u = getattr(surface, "knots_u", None)
    knots_v = getattr(surface, "knots_v", None)
    if knots_u is not None and knots_v is not None:
        u_min = float(knots_u[0])
        u_max = float(knots_u[-1])
        v_min = float(knots_v[0])
        v_max = float(knots_v[-1])
        if u_max <= u_min:
            u_min, u_max = 0.0, 1.0
        if v_max <= v_min:
            v_min, v_max = 0.0, 1.0
        return u_min, u_max, v_min, v_max
    return 0.0, 1.0, 0.0, 1.0


def _wrap_as_nurbs(surface) -> Optional[NurbsSurface]:
    """Return surface as NurbsSurface if it already is one; else None."""
    if isinstance(surface, NurbsSurface):
        return surface
    return None


@dataclass
class DevelopabilityReport:
    """Result of :func:`check_face_developable`.

    Attributes
    ----------
    is_developable : bool
        True when max|K| < tolerance over all valid samples.
    max_abs_K : float
        Maximum |K| observed across all valid sample points.
    mean_abs_K : float
        Mean |K| across valid samples.
    samples_valid : int
        Number of non-degenerate sample points used.
    tolerance : float
        The tolerance applied (K below this → zero for is_developable test).
    ruled_direction_if_any : str or None
        "kappa_1" if κ_1 ≈ 0 everywhere (ruling direction is principal-1
        direction); "kappa_2" if κ_2 ≈ 0 everywhere; None otherwise.
        A non-None value is a strong indicator that the face is a ruled
        developable (cylinder, cone, tangent surface — do Carmo §3.6;
        Pottmann-Wallner §4.1).
    honest_caveat : str
        Honest-flag: sampling-based check only.
    """

    is_developable: bool
    max_abs_K: float
    mean_abs_K: float
    samples_valid: int
    tolerance: float
    ruled_direction_if_any: Optional[str]
    honest_caveat: str = field(default=(
        "Sampling-based: max|K| is a lower bound on the true supremum. "
        "High-curvature regions between grid points may be missed. "
        "Increase `samples` (20-50) for higher confidence. "
        "Reference: do Carmo §3.6; Pottmann-Wallner §4."
    ))


def check_face_developable(
    face: Face,
    tolerance: float = _DEFAULT_TOLERANCE,
    samples: int = _DEFAULT_SAMPLES,
) -> DevelopabilityReport:
    """Check whether a B-rep face is developable (K = 0 everywhere).

    A surface is developable iff its Gaussian curvature K = κ_1·κ_2 = 0
    everywhere — it can be unrolled flat without stretching.  Classic
    examples: planes, cylinders, cones (all K=0); spheres (K=1/R²>0,
    not developable); tori (K varies in sign, not developable).

    This implementation samples the surface at an (N×N) UV grid, computes
    K at each point via the shape operator (second fundamental form), and
    reports max|K| and mean|K|.

    Parameters
    ----------
    face : Face
        B-rep face whose surface must implement either:
        * A NurbsSurface (queried via :mod:`normal_curvature`), or
        * Any surface with ``evaluate(u,v)→(3,) array`` and knot vectors
          on which a finite-difference curvature fallback is used.
    tolerance : float
        Gaussian curvature threshold for is_developable.
        Default 1e-3 (appropriate for CAD units in mm; tighten for
        precision sheet-metal, loosen for coarse mesh faces).
    samples : int
        Grid points per UV axis.  Total samples ≤ samples².  Min 2.

    Returns
    -------
    DevelopabilityReport

    Notes
    -----
    Theory: do Carmo §3.6; Pottmann-Wallner §4.
    K = (L·N − M²) / (E·G − F²) where E,F,G are first fundamental form
    coefficients and L,M,N are second fundamental form coefficients.

    For a NURBS cylinder of radius R: K=0 at every regular point.
    For a NURBS sphere of radius R:   K=1/R² at every point.
    For a NURBS cone:                 K=0 along every ruling line; the
    apex is a singular/degenerate point (skipped automatically).
    For a torus (R,r):                K = cos(v) / (r·(R+r·cos(v))),
    which changes sign — hence never passes the is_developable=True test
    unless the sampler only hits the K=0 circle (unlikely).
    """
    samples = max(samples, 2)
    surface = face.surface
    nurbs_srf = _wrap_as_nurbs(surface)

    u_min, u_max, v_min, v_max = _surface_uv_domain(surface)

    us = np.linspace(u_min, u_max, samples)
    vs = np.linspace(v_min, v_max, samples)

    K_values: list[float] = []
    kappa1_values: list[float] = []
    kappa2_values: list[float] = []

    for u in us:
        for v in vs:
            if nurbs_srf is not None:
                # Full shape-operator path via normal_curvature module
                try:
                    report = normal_curvature_at(nurbs_srf, float(u), float(v), (1.0, 0.0))
                    if report.is_degenerate:
                        continue
                    K_values.append(report.K)
                    kappa1_values.append(report.kappa_1)
                    kappa2_values.append(report.kappa_2)
                except Exception:
                    continue
            else:
                # Fallback: finite-difference curvature on arbitrary surface
                K_fd = _fd_gaussian_curvature(surface, float(u), float(v),
                                              u_min, u_max, v_min, v_max)
                if K_fd is None:
                    continue
                K_values.append(K_fd)
                # kappa1/2 unavailable in FD path — use NaN sentinels
                kappa1_values.append(float("nan"))
                kappa2_values.append(float("nan"))

    if not K_values:
        # No valid samples (degenerate face)
        return DevelopabilityReport(
            is_developable=True,
            max_abs_K=0.0,
            mean_abs_K=0.0,
            samples_valid=0,
            tolerance=tolerance,
            ruled_direction_if_any=None,
        )

    abs_K = [abs(k) for k in K_values]
    max_abs_K = float(max(abs_K))
    mean_abs_K = float(sum(abs_K) / len(abs_K))
    is_developable = max_abs_K < tolerance

    # Ruling direction: check if one principal curvature is consistently ~0
    ruled_direction: Optional[str] = None
    valid_k1 = [k for k in kappa1_values if not math.isnan(k)]
    valid_k2 = [k for k in kappa2_values if not math.isnan(k)]
    if valid_k1 and valid_k2:
        max_abs_k1 = max(abs(k) for k in valid_k1)
        max_abs_k2 = max(abs(k) for k in valid_k2)
        if max_abs_k1 < tolerance:
            ruled_direction = "kappa_1"
        elif max_abs_k2 < tolerance:
            ruled_direction = "kappa_2"

    return DevelopabilityReport(
        is_developable=is_developable,
        max_abs_K=max_abs_K,
        mean_abs_K=mean_abs_K,
        samples_valid=len(K_values),
        tolerance=tolerance,
        ruled_direction_if_any=ruled_direction,
    )


def _fd_gaussian_curvature(
    surface,
    u: float,
    v: float,
    u_min: float,
    u_max: float,
    v_min: float,
    v_max: float,
    h: float = 1e-5,
) -> Optional[float]:
    """Finite-difference Gaussian curvature for non-NURBS surfaces.

    Uses central differences for S_u, S_v, S_uu, S_uv, S_vv then
    applies the standard FFF/SFF formula (do Carmo §2.3, §3.3).
    Returns None on any evaluation failure or degenerate normal.
    """
    hu = h * (u_max - u_min)
    hv = h * (v_max - v_min)
    try:
        def ev(uu: float, vv: float) -> np.ndarray:
            p = surface.evaluate(uu, vv)
            return np.asarray(p, dtype=float).ravel()[:3]

        Su = (ev(u + hu, v) - ev(u - hu, v)) / (2.0 * hu)
        Sv = (ev(u, v + hv) - ev(u, v - hv)) / (2.0 * hv)
        Suu = (ev(u + hu, v) - 2.0 * ev(u, v) + ev(u - hu, v)) / (hu * hu)
        Svv = (ev(u, v + hv) - 2.0 * ev(u, v) + ev(u, v - hv)) / (hv * hv)
        Suv = (ev(u + hu, v + hv) - ev(u + hu, v - hv)
               - ev(u - hu, v + hv) + ev(u - hu, v - hv)) / (4.0 * hu * hv)

        nrm = np.cross(Su, Sv)
        mag = float(np.linalg.norm(nrm))
        if mag < 1e-12:
            return None
        n_hat = nrm / mag

        E = float(np.dot(Su, Su))
        F = float(np.dot(Su, Sv))
        G = float(np.dot(Sv, Sv))
        det_I = E * G - F * F
        if abs(det_I) < 1e-12:
            return None

        L = float(np.dot(Suu, n_hat))
        M = float(np.dot(Suv, n_hat))
        N = float(np.dot(Svv, n_hat))

        return (L * N - M * M) / det_I
    except Exception:
        return None


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
        name="brep_check_face_developable",
        description=(
            "Check whether a B-rep face (NURBS surface) is *developable* — i.e. "
            "can be unrolled flat without stretching (like a cylinder or cone, but "
            "NOT a sphere or torus).\n"
            "\n"
            "A surface is developable iff its Gaussian curvature K = κ_1·κ_2 = 0 "
            "everywhere (do Carmo §3.6; Pottmann-Wallner §4).\n"
            "\n"
            "Algorithm: sample an N×N UV grid, compute K at each point via the "
            "shape operator (second fundamental form coefficients L, M, N and first "
            "fundamental form E, F, G).  Report max|K|, mean|K|, and whether the "
            "surface is ruled (one principal curvature consistently zero).\n"
            "\n"
            "Returns:\n"
            "  is_developable          — True when max|K| < tolerance\n"
            "  max_abs_K               — maximum |K| across all valid samples\n"
            "  mean_abs_K              — mean |K| across valid samples\n"
            "  samples_valid           — non-degenerate sample count\n"
            "  ruled_direction_if_any  — 'kappa_1' or 'kappa_2' if one principal "
            "curvature is identically ~0 (ruling direction indicator); null otherwise\n"
            "\n"
            "Oracles:\n"
            "  • Cylinder R=1:  K=0 everywhere → is_developable=true\n"
            "  • Sphere R=1:    K=1.0 everywhere → is_developable=false\n"
            "  • Cone:          K=0 along rulings → is_developable=true\n"
            "  • Torus (R,r):   K varies in sign → is_developable=false\n"
            "  • Plane:         K=0 → is_developable=true\n"
            "\n"
            "HONEST CAVEAT: sampling-based. max_abs_K is a lower bound on the "
            "true supremum of |K|. High-curvature pockets between grid points "
            "may be missed. Use samples≥20 for high-confidence results.\n"
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
                "tolerance": {
                    "type": "number",
                    "description": "Gaussian curvature threshold. Default 1e-3.",
                },
                "samples": {
                    "type": "integer",
                    "description": "UV grid points per axis. Default 10. Min 2.",
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "knots_u", "knots_v"],
        },
    )

    @register(_spec)
    def _tool_brep_check_face_developable(params: dict, ctx: "ProjectCtx"):  # type: ignore[type-arg]
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
            tolerance = float(params.get("tolerance", _DEFAULT_TOLERANCE))
            samples = int(params.get("samples", _DEFAULT_SAMPLES))

            # Wrap in a minimal Face-like object
            class _FaceLike:
                def __init__(self, s):
                    self.surface = s

            result = check_face_developable(_FaceLike(srf), tolerance=tolerance, samples=samples)
            return ok_payload({
                "is_developable": result.is_developable,
                "max_abs_K": result.max_abs_K,
                "mean_abs_K": result.mean_abs_K,
                "samples_valid": result.samples_valid,
                "tolerance": result.tolerance,
                "ruled_direction_if_any": result.ruled_direction_if_any,
                "honest_caveat": result.honest_caveat,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
