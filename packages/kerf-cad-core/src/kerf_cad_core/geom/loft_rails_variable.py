"""
loft_rails_variable.py
======================
Variable rail-tangent Gordon loft (Piegl-Tiller §10.4.3).

Extends the Wave 4N Gordon loft (``network_srf.gordon_network_srf``) with
per-station tangent prescriptions on the guide rails.  When explicit tangents
are supplied the rail interpolant is replaced by a cubic Hermite spline that
satisfies the prescribed derivative at each prescribed parameter value; the
Gordon surface formula is then evaluated on top of that Hermite-augmented rail.

Theory
------
The Gordon surface interpolates two families of curves:

    G(u,v) = Σ_i L_i(v) · c_i(u)              [section family]
           + Σ_j M_j(u) · d_j(v)              [rail family]
           - Σ_i Σ_j L_i(v) · M_j(u) · P_ij  [tensor correction]

When a rail d_j is given with tangent prescriptions {(t_k, T_k)}, the plain
evaluation ``d_j(v)`` used in Term 2 is replaced by a Hermite-blended
version ``d̃_j(v)`` constructed by:

  1. Sampling the natural rail at ``grid_n`` points in [0, 1].
  2. At each prescribed parameter t_k, overriding the sample's tangent
     derivative with the prescribed tangent T_k via cubic Hermite blending
     between the nearest flanking grid samples.
  3. Fitting a B-spline through the Hermite-modified sample positions
     (Piegl & Tiller, §9.3).

This keeps the interface 100% backward-compatible: with ``rail_tangents=None``
the function delegates directly to ``gordon_network_srf`` and produces an
identical result.

Public API
----------
loft_with_rails_variable(sections, rails, rail_tangents=None, *, method='gordon_extended',
                          grid_n=30, tol=1e-6) -> NurbsSurface

extract_rail_tangents(loft_result, n_samples=10)
    -> list[list[tuple[float, np.ndarray]]]

validate_rail_tangent_compatibility(sections, rails, rail_tangents)
    -> list[str]

References
----------
- Piegl & Tiller, "The NURBS Book", 2nd ed., §10.4 + §10.4.3.
- Sabin M.A. (1969), "Conditions for second order continuity over assembly
  surfaces", Technical report.
- Várady T., Salvi P. (2010), "Multi-sided surfaces with curvature continuity",
  Comput. Aided Des., 43, 1001–1014.
"""

from __future__ import annotations

import warnings
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.network_srf import gordon_network_srf, _eval_curve_at


# ---------------------------------------------------------------------------
# Internal Hermite helpers
# ---------------------------------------------------------------------------

def _hermite_blend(p0: np.ndarray, p1: np.ndarray,
                   t0: np.ndarray, t1: np.ndarray,
                   t: float) -> np.ndarray:
    """Cubic Hermite interpolation between (p0, p1) with tangents (t0, t1).

    Hermite basis:
        h00 = 2t³ - 3t² + 1    (position blend for p0)
        h10 = t³  - 2t² + t    (tangent blend for t0, interval length=1)
        h01 = -2t³ + 3t²       (position blend for p1)
        h11 = t³  - t²         (tangent blend for t1, interval length=1)
    """
    t2, t3 = t * t, t * t * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return h00 * p0 + h10 * t0 + h01 * p1 + h11 * t1


def _natural_rail_derivative(rail: NurbsCurve, param: float) -> np.ndarray:
    """First derivative of *rail* at normalised parameter *param* in [0,1]."""
    u0 = float(rail.knots[rail.degree])
    u1 = float(rail.knots[-rail.degree - 1])
    span = u1 - u0
    if span < 1e-14:
        return np.zeros(3)
    u = max(u0, min(u1, u0 + param * span))
    raw = np.asarray(rail.derivative(u, order=1), dtype=float).ravel()
    if raw.shape[0] < 3:
        raw = np.concatenate([raw, np.zeros(3 - raw.shape[0])])
    # Chain-rule: d/d(normalised) = span * d/du
    return raw[:3] * span


def _hermite_rail_samples(rail: NurbsCurve,
                           prescriptions: List[Tuple[float, np.ndarray]],
                           n: int) -> np.ndarray:
    """Return an (n, 3) array of rail positions satisfying Hermite tangent constraints.

    Algorithm (Piegl-Tiller §10.4.3 variant)
    -----------------------------------------
    Build a piecewise cubic Hermite spline through the rail that:

      * Passes through the original rail endpoints (t=0 and t=1).
      * Passes through the natural rail positions at each prescribed t_k.
      * Has the prescribed tangent T_k at each t_k.
      * Matches the natural rail's tangent at t=0 and t=1 (C1 at ends).

    The construction uses the "breakpoint" sequence:
        [0, t_1, t_2, ..., t_m, 1]
    sorted in ascending order.  Each interval [t_i, t_{i+1}] is filled with a
    cubic Hermite segment whose end-point positions and derivatives come from:
      - the natural rail at the interval boundary parameters, EXCEPT
      - at prescribed parameters, the tangent is replaced by T_k (but the
        *position* is still taken from the natural rail so the rail's spatial
        path is preserved and only its rate of travel changes).

    This ensures the tangent override propagates into every sample in the
    interval around the prescription, not just at the exact t_k point.
    """
    # Build sorted breakpoint list: endpoints + prescribed params.
    t_breaks = sorted({0.0, 1.0} | {float(max(0.0, min(1.0, t_k)))
                                     for (t_k, _) in prescriptions})

    # Map each prescribed (t_k, T_k) to the break index.
    overrides: dict = {}  # t_k -> T_k (normalised)
    for t_k, T_k in prescriptions:
        t_k = float(max(0.0, min(1.0, t_k)))
        T_k = np.asarray(T_k, dtype=float).ravel()
        if T_k.shape[0] < 3:
            T_k = np.concatenate([T_k, np.zeros(3 - T_k.shape[0])])
        T_k_unit = T_k[:3]
        # Scale to match the magnitude of the natural derivative.
        nat_mag = float(np.linalg.norm(_natural_rail_derivative(rail, t_k)))
        if nat_mag > 1e-14:
            T_norm = np.linalg.norm(T_k_unit)
            if T_norm > 1e-14:
                T_k_unit = T_k_unit / T_norm * nat_mag
        overrides[t_k] = T_k_unit

    # Compute positions and (possibly overridden) derivatives at all breakpoints.
    def _pos(t: float) -> np.ndarray:
        return _eval_curve_at(rail, t)

    def _der(t: float) -> np.ndarray:
        if t in overrides:
            return overrides[t]
        return _natural_rail_derivative(rail, t)

    # Now evaluate the piecewise Hermite at n uniformly spaced samples.
    params = np.linspace(0.0, 1.0, n)
    pts_out = np.zeros((n, 3))

    for i, t in enumerate(params):
        # Find the enclosing interval [t_lo, t_hi].
        seg_hi = len(t_breaks) - 1
        for k in range(len(t_breaks) - 1):
            if t_breaks[k] <= t <= t_breaks[k + 1]:
                seg_hi = k + 1
                break
        seg_lo = seg_hi - 1
        t_lo = t_breaks[seg_lo]
        t_hi = t_breaks[seg_hi]
        interval = t_hi - t_lo
        if interval < 1e-14:
            pts_out[i] = _pos(t_lo)
            continue

        local_t = (t - t_lo) / interval

        # Positions and scaled derivatives at interval endpoints.
        p0 = _pos(t_lo)
        p1 = _pos(t_hi)
        d0 = _der(t_lo) * interval   # scaled to local [0,1]
        d1 = _der(t_hi) * interval   # scaled to local [0,1]

        pts_out[i] = _hermite_blend(p0, p1, d0, d1, local_t)

    return pts_out


def _pts_to_nurbs_curve(pts: np.ndarray) -> NurbsCurve:
    """Fit a cubic B-spline through the given (n, 3) point sequence.

    Uses chord-length parameterisation + clamped uniform knot placement
    (Piegl & Tiller §9.2 global interpolation).  For n <= 3 we fall back to
    degree = n - 1 to keep the system square.
    """
    n = pts.shape[0]
    if n < 2:
        raise ValueError("Need at least 2 points to fit a NurbsCurve")
    degree = min(3, n - 1)

    # Chord-length parameters.
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = diffs.sum()
    if total < 1e-14:
        params = np.linspace(0.0, 1.0, n)
    else:
        params = np.concatenate([[0.0], np.cumsum(diffs) / total])

    # Averaged knot vector (Piegl §9.2, Eq. 9.8).
    m = n + degree + 1
    knots = np.zeros(m)
    knots[-(degree + 1):] = 1.0
    if degree < n - 1:
        for j in range(1, n - degree):
            knots[j + degree] = params[j:j + degree].sum() / degree

    # Build collocation matrix N (n x n).
    from kerf_cad_core.geom.nurbs import find_span, _basis_funcs
    N = np.zeros((n, n))
    for i in range(n):
        span = find_span(n - 1, degree, float(params[i]), knots)
        basis = _basis_funcs(span, float(params[i]), degree, knots)
        for k in range(degree + 1):
            j = span - degree + k
            if 0 <= j < n:
                N[i, j] = basis[k]

    # Solve for control points (dimension by dimension).
    cp = np.zeros((n, 3))
    for dim in range(3):
        try:
            cp[:, dim] = np.linalg.solve(N, pts[:, dim])
        except np.linalg.LinAlgError:
            cp[:, dim] = np.linalg.lstsq(N, pts[:, dim], rcond=None)[0]

    return NurbsCurve(degree=degree, control_points=cp, knots=knots)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def loft_with_rails_variable(
    sections: List[NurbsCurve],
    rails: List[NurbsCurve],
    rail_tangents: Optional[List[List[Tuple[float, np.ndarray]]]] = None,
    *,
    method: str = "gordon_extended",
    grid_n: int = 30,
    tol: float = 1e-6,
) -> NurbsSurface:
    """Variable rail-tangent Gordon loft (Piegl-Tiller §10.4.3).

    When *rail_tangents* is ``None`` this function delegates to
    :func:`gordon_network_srf` and produces an **identical** result to the
    Wave 4N basic Gordon loft — no regression.

    Parameters
    ----------
    sections : list[NurbsCurve]
        Cross-section profile curves.  At least 1 required; the Gordon
        surface interpolates all of them exactly.
    rails : list[NurbsCurve]
        Guide-rail curves running in the loft direction.  At least 1
        required.
    rail_tangents : list[list[tuple[float, array_like]]] or None
        Per-rail tangent prescriptions.  The outer list length must equal
        ``len(rails)`` when not ``None``.  Each inner list is a sequence
        of ``(param, tangent_vector)`` pairs where *param* is in [0, 1]
        (normalised rail domain) and *tangent_vector* is a 3-D direction.

        An empty inner list ``[]`` means "use natural tangents for this
        rail" — equivalent to no prescription.

        When ``None`` the function is identical to ``loft_with_rails``
        (basic Gordon surface, Piegl-Tiller §10.4).
    method : str
        ``'gordon_extended'`` (default) — Hermite-augmented Gordon surface.
        Only ``'gordon_extended'`` is currently implemented; reserved for
        future methods (e.g. ``'variational'``).
    grid_n : int
        Grid sample count per direction.  Larger values give finer
        resolution of the Hermite-modified rails at the cost of performance.
    tol : float
        Tolerance for section–rail intersection checks.

    Returns
    -------
    NurbsSurface

    Raises
    ------
    ValueError
        If the input counts are inconsistent or intersections diverge
        beyond *tol* (after Hermite modification).
    """
    if len(sections) < 1:
        raise ValueError(
            "loft_with_rails_variable: at least 1 section required"
        )
    if len(rails) < 1:
        raise ValueError(
            "loft_with_rails_variable: at least 1 rail required"
        )

    # Fast path: no tangent prescriptions — delegate to base Gordon.
    if rail_tangents is None or all(len(rt) == 0 for rt in rail_tangents):
        return gordon_network_srf(
            u_curves=list(sections),
            v_curves=list(rails),
            grid_n=grid_n,
            tol=tol,
        )

    if len(rail_tangents) != len(rails):
        raise ValueError(
            f"loft_with_rails_variable: rail_tangents length "
            f"({len(rail_tangents)}) must equal rails length ({len(rails)})"
        )

    if method != "gordon_extended":
        raise ValueError(
            f"loft_with_rails_variable: unknown method '{method}'. "
            "Only 'gordon_extended' is supported."
        )

    # Build Hermite-modified rail curves for rails that have prescriptions.
    modified_rails: List[NurbsCurve] = []
    for j, (rail, prescriptions) in enumerate(zip(rails, rail_tangents)):
        if not prescriptions:
            modified_rails.append(rail)
        else:
            pts = _hermite_rail_samples(rail, prescriptions, n=grid_n)
            modified_rails.append(_pts_to_nurbs_curve(pts))

    # Delegate to the Gordon surface with the modified rails.
    return gordon_network_srf(
        u_curves=list(sections),
        v_curves=modified_rails,
        grid_n=grid_n,
        tol=tol,
    )


def extract_rail_tangents(
    loft_result: NurbsSurface,
    n_samples: int = 10,
) -> List[List[Tuple[float, np.ndarray]]]:
    """Sample tangents along the v-direction iso-curves of a loft surface.

    This is a helper for round-trip testing and interactive tangent editing:
    given an existing loft surface it extracts the v-direction derivatives at
    *n_samples* uniformly-spaced u-parameters along the v=0 iso-curve
    (first "rail" direction of the surface).

    Parameters
    ----------
    loft_result : NurbsSurface
        The lofted surface to sample.
    n_samples : int
        Number of parameter samples in [0, 1].

    Returns
    -------
    list of list of (param, tangent) tuples
        One outer list per sampled iso-curve; each inner list has one
        ``(param, tangent_vector)`` entry per sample.  In the current
        implementation a single iso-curve rail at ``u_params=[0..1]`` is
        returned; the outer list therefore has length 1.
    """
    from kerf_cad_core.geom.nurbs import surface_derivative

    u0_knot = float(loft_result.knots_u[loft_result.degree_u])
    u1_knot = float(loft_result.knots_u[-loft_result.degree_u - 1])
    v0_knot = float(loft_result.knots_v[loft_result.degree_v])
    v1_knot = float(loft_result.knots_v[-loft_result.degree_v - 1])

    samples: List[Tuple[float, np.ndarray]] = []
    for i in range(n_samples):
        t = i / max(n_samples - 1, 1)
        v = v0_knot + t * (v1_knot - v0_knot)
        u = u0_knot  # along the first iso-curve (u = domain start)
        # d/dv at this point gives the v-direction tangent (rail tangent).
        dv = surface_derivative(loft_result, float(u), float(v), ku=0, kv=1)
        dv_arr = np.asarray(dv, dtype=float).ravel()
        if dv_arr.shape[0] < 3:
            dv_arr = np.concatenate([dv_arr, np.zeros(3 - dv_arr.shape[0])])
        samples.append((t, dv_arr[:3]))

    return [samples]


def validate_rail_tangent_compatibility(
    sections: List[NurbsCurve],
    rails: List[NurbsCurve],
    rail_tangents: List[List[Tuple[float, np.ndarray]]],
) -> List[str]:
    """Check that prescribed tangents are compatible with the section planes.

    A tangent T at rail parameter t_k is *compatible* with the section at
    that station if T has a non-zero projection onto the section's tangent
    plane (i.e. T is not purely normal to the section).

    For each prescription we:

    1. Identify which section parameter t_k maps to (proportional to
       section index spacing).
    2. Sample the nearest section curve at its midpoint to obtain a local
       tangent direction u_t of that section.
    3. Compute the section's approximate normal as the cross product of u_t
       with the rail direction at t_k.
    4. Check that T is not nearly parallel to that normal (within 5°).
       A tangent that is perpendicular to the section plane is *incompatible*
       because it would create a fold or cusp in the Gordon surface.

    Parameters
    ----------
    sections : list[NurbsCurve]
    rails : list[NurbsCurve]
    rail_tangents : list[list[(param, tangent)]]

    Returns
    -------
    list[str]
        Human-readable warning strings for each incompatible prescription.
        Empty if all prescriptions are compatible.
    """
    if not sections or not rails or not rail_tangents:
        return []

    warnings_out: List[str] = []
    n_sections = len(sections)

    for j, (rail, prescriptions) in enumerate(zip(rails, rail_tangents)):
        for (t_k, T_k) in prescriptions:
            t_k = float(t_k)
            T_k = np.asarray(T_k, dtype=float).ravel()
            if T_k.shape[0] < 3:
                T_k = np.concatenate([T_k, np.zeros(3 - T_k.shape[0])])
            T_k = T_k[:3]

            T_norm = np.linalg.norm(T_k)
            if T_norm < 1e-14:
                warnings_out.append(
                    f"Rail {j}, param {t_k:.4f}: prescribed tangent has zero "
                    "magnitude — ignored."
                )
                continue

            T_unit = T_k / T_norm

            # Nearest section index (proportional mapping).
            sec_idx = int(round(t_k * (n_sections - 1)))
            sec_idx = max(0, min(n_sections - 1, sec_idx))
            section = sections[sec_idx]

            # Section tangent at midpoint.
            u0 = float(section.knots[section.degree])
            u1 = float(section.knots[-section.degree - 1])
            u_mid = 0.5 * (u0 + u1)
            sec_tan = np.asarray(section.derivative(u_mid, order=1), dtype=float).ravel()
            if sec_tan.shape[0] < 3:
                sec_tan = np.concatenate([sec_tan, np.zeros(3 - sec_tan.shape[0])])
            sec_tan = sec_tan[:3]
            sec_tan_norm = np.linalg.norm(sec_tan)

            # Rail tangent at t_k.
            rail_tan = _natural_rail_derivative(rail, t_k)
            rail_tan_norm = np.linalg.norm(rail_tan)

            if sec_tan_norm < 1e-14 or rail_tan_norm < 1e-14:
                # Degenerate — skip.
                continue

            sec_tan_unit = sec_tan / sec_tan_norm
            rail_tan_unit = rail_tan / rail_tan_norm

            # Section normal ≈ cross(sec_tan, rail_tan).
            sec_normal = np.cross(sec_tan_unit, rail_tan_unit)
            sec_normal_norm = np.linalg.norm(sec_normal)
            if sec_normal_norm < 1e-14:
                # Parallel section and rail tangents — no well-defined normal.
                continue
            sec_normal_unit = sec_normal / sec_normal_norm

            # Check whether T is parallel to the section normal (incompatible).
            dot = abs(float(np.dot(T_unit, sec_normal_unit)))
            # dot ≈ 1 means T is perpendicular to the section plane.
            angle_to_normal = float(np.arccos(min(1.0, dot)))  # radians
            THRESHOLD_RAD = np.deg2rad(85.0)  # 85° to normal = 5° in-plane

            if angle_to_normal < np.deg2rad(5.0):
                # T is nearly *normal* to the section — incompatible (fold).
                warnings_out.append(
                    f"Rail {j}, param {t_k:.4f}: prescribed tangent is nearly "
                    "perpendicular to the section plane (angle to section normal "
                    f"{np.rad2deg(angle_to_normal):.1f}°). This will create a "
                    "fold/cusp in the loft."
                )

    return warnings_out


# ---------------------------------------------------------------------------
# LLM tool registration (gated — graceful no-op when registry absent)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    _nurbs_loft_variable_spec = ToolSpec(
        name="nurbs_loft_with_rails_variable",
        description=(
            "Variable rail-tangent Gordon loft (Piegl-Tiller §10.4.3). "
            "Extends the Gordon loft with per-station tangent prescriptions "
            "on the guide rails. "
            "\n\n"
            "**When `rail_tangents` is omitted (or null)** the result is "
            "identical to the basic Gordon loft — no regression. "
            "\n\n"
            "**With explicit tangents** each rail can have one or more "
            "(param, tangent_vector) prescriptions that override the "
            "natural rail derivative at that station. The rail is rebuilt "
            "via Hermite interpolation satisfying the prescribed tangent, "
            "and the Gordon surface is computed on top. This allows the "
            "designer to control inflection, flare, or sweep angle at "
            "specific cross-sections without changing the guide-rail geometry. "
            "\n\n"
            "**Sections** are the cross-profile curves (rows); "
            "**rails** are the guide curves (columns). "
            "All section–rail intersections must agree within `tol`. "
            "\n\n"
            "Returns a serialised NurbsSurface (control_points, knots_u, "
            "knots_v, degree_u, degree_v) plus a `warnings` list from "
            "validate_rail_tangent_compatibility."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "description": (
                        "List of NURBS cross-section curves. Each curve is an object with "
                        "keys: degree (int), control_points ([[x,y,z],...]), knots ([float,...])."
                    ),
                    "items": {"type": "object"},
                },
                "rails": {
                    "type": "array",
                    "description": (
                        "List of NURBS guide-rail curves. Same schema as sections."
                    ),
                    "items": {"type": "object"},
                },
                "rail_tangents": {
                    "type": "array",
                    "description": (
                        "Optional per-rail tangent prescriptions. "
                        "Outer list length must equal len(rails). "
                        "Each entry is a list of {param: float, tangent: [tx,ty,tz]} objects. "
                        "An empty list [] means 'use natural tangents for this rail'. "
                        "Omit or pass null for the default Gordon loft."
                    ),
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "param": {"type": "number",
                                          "description": "Normalised parameter in [0,1]."},
                                "tangent": {"type": "array",
                                            "items": {"type": "number"},
                                            "description": "[tx, ty, tz] tangent vector."},
                            },
                            "required": ["param", "tangent"],
                        },
                    },
                },
                "method": {
                    "type": "string",
                    "enum": ["gordon_extended"],
                    "description": "Loft method. Only 'gordon_extended' is currently supported.",
                },
                "grid_n": {
                    "type": "integer",
                    "description": "Grid sample count per direction (default 30). Larger = finer.",
                },
                "tol": {
                    "type": "number",
                    "description": "Intersection tolerance (default 1e-6).",
                },
            },
            "required": ["sections", "rails"],
        },
    )

    def _decode_curve(obj: dict) -> NurbsCurve:
        """Decode a plain-dict NURBS curve representation."""
        degree = int(obj["degree"])
        cp = np.array(obj["control_points"], dtype=float)
        if cp.ndim == 1:
            cp = cp.reshape(-1, 3)
        knots = np.array(obj["knots"], dtype=float)
        weights = obj.get("weights")
        if weights is not None:
            weights = np.array(weights, dtype=float)
        return NurbsCurve(degree=degree, control_points=cp, knots=knots,
                          weights=weights)

    @register(_nurbs_loft_variable_spec)
    async def run_nurbs_loft_with_rails_variable(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            sections_raw = a.get("sections")
            rails_raw = a.get("rails")

            if not sections_raw or not isinstance(sections_raw, list):
                return err_payload("sections must be a non-empty array", "BAD_ARGS")
            if not rails_raw or not isinstance(rails_raw, list):
                return err_payload("rails must be a non-empty array", "BAD_ARGS")

            sections = [_decode_curve(c) for c in sections_raw]
            rails = [_decode_curve(r) for r in rails_raw]

            # Decode rail_tangents.
            rt_raw = a.get("rail_tangents")
            rail_tangents = None
            if rt_raw is not None:
                if not isinstance(rt_raw, list):
                    return err_payload(
                        "rail_tangents must be an array or null", "BAD_ARGS"
                    )
                rail_tangents = []
                for per_rail in rt_raw:
                    if not isinstance(per_rail, list):
                        return err_payload(
                            "each rail_tangents entry must be a list", "BAD_ARGS"
                        )
                    prescriptions = []
                    for item in per_rail:
                        param = float(item["param"])
                        tangent = np.array(item["tangent"], dtype=float).ravel()
                        prescriptions.append((param, tangent))
                    rail_tangents.append(prescriptions)

            method = a.get("method", "gordon_extended")
            grid_n = int(a.get("grid_n", 30))
            tol = float(a.get("tol", 1e-6))

            # Validation warnings.
            compat_warnings: list = []
            if rail_tangents is not None:
                compat_warnings = validate_rail_tangent_compatibility(
                    sections, rails, rail_tangents
                )

            srf = loft_with_rails_variable(
                sections, rails, rail_tangents,
                method=method, grid_n=grid_n, tol=tol,
            )

        except ValueError as exc:
            return err_payload(str(exc), "OP_FAILED")
        except Exception as exc:
            return err_payload(f"unexpected error: {exc}", "ERROR")

        return ok_payload({
            "degree_u": srf.degree_u,
            "degree_v": srf.degree_v,
            "control_points": srf.control_points.tolist(),
            "knots_u": srf.knots_u.tolist(),
            "knots_v": srf.knots_v.tolist(),
            "warnings": compat_warnings,
        })
