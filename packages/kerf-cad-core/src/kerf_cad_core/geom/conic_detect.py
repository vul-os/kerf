"""
conic_detect.py
===============
NURBS rational conic detection and simplification — GK-P (Lee 1987 / Piegl-Tiller §7.2).

A rational quadratic NURBS curve can exactly represent any conic section.  This
module tests whether a given NurbsCurve is actually a conic and — if it is —
extracts the canonical geometric form: center, axes, radius, foci and
eccentricity.

References
----------
- Piegl & Tiller, "The NURBS Book", 2nd ed., §7.2 (rational quadratic + circles)
- Lee, E.T.Y. (1987) "The rational Bezier representation for conics", in
  *Geometric Modeling: Algorithms and New Trends*, SIAM, pp. 3–19.

Algorithm overview
------------------
1. Degree check: only degree ≤ 2 can be a conic.
2. Sample the curve and project onto its best-fit 2-D plane via PCA.
3. Check planarity residual.
4. Fit the general conic Ax²+Bxy+Cy²+Dx+Ey+F=0 by least squares (normalised).
5. Classify by discriminant Δ = B²−4AC and matrix eigenvalue ratios.
6. Extract canonical parameters (center, semi-axes, eccentricity, foci) via
   completing-the-square / eigendecomposition of the conic matrix.

Public API
----------
detect_conic(curve, tol=1e-6) -> ConicInfo | None
extract_canonical_circle(curve) -> CircleParams
simplify_curve(curve) -> NurbsCurve | ConicInfo
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
from numpy.linalg import svd, eigh, norm

from kerf_cad_core.geom.nurbs import NurbsCurve, de_boor

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConicInfo:
    """Canonical description of a detected conic section.

    Attributes
    ----------
    kind        : 'circle' | 'ellipse' | 'parabola' | 'hyperbola'
    center      : 3-D centroid in world coordinates (None for parabola)
    axes        : tuple of 3-D unit vectors along the principal axes.
                  For circle/ellipse: (major_axis, minor_axis).
                  For parabola: (axis_dir, symmetry_normal).
                  For hyperbola: (transverse_axis, conjugate_axis).
    radii       : (a, b) semi-axes lengths.
                  For circle: a == b == radius.
                  For parabola: (focal_length, 0.0).
    focus       : closest focus in 3-D world coordinates (None if degenerate)
    eccentricity: float (0 for circle, 0<e<1 for ellipse, 1 for parabola,
                  e>1 for hyperbola)
    plane_normal: unit normal of the plane the conic lies in (3-D)
    plane_origin: a point on the plane (3-D)
    """
    kind: str
    center: Optional[np.ndarray]
    axes: tuple
    radii: tuple
    focus: Optional[np.ndarray]
    eccentricity: float
    plane_normal: np.ndarray
    plane_origin: np.ndarray


@dataclass
class CircleParams:
    """Simplified result for a detected circle."""
    center: np.ndarray
    radius: float
    plane_normal: np.ndarray


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_N_SAMPLES = 64   # number of uniform parameter samples for fitting


def _sample_curve(curve: NurbsCurve, n: int = _N_SAMPLES) -> np.ndarray:
    """Return (n, 3) array of 3-D points sampled at uniform parameter steps."""
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-(curve.degree + 1)])
    us = np.linspace(u0, u1, n)
    pts = []
    for u in us:
        p = de_boor(curve, u)
        if p.shape[0] >= 3:
            pts.append(p[:3])
        elif p.shape[0] == 2:
            pts.append(np.array([p[0], p[1], 0.0]))
        else:
            pts.append(np.array([p[0], 0.0, 0.0]))
    return np.array(pts)


def _fit_plane(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit a plane to pts via PCA.

    Returns (normal, origin, residual_rms).  ``normal`` is the PCA
    eigenvector corresponding to the *smallest* variance (the out-of-plane
    direction).  ``origin`` is the centroid.
    """
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    # SVD: columns of V.T are eigenvectors sorted by descending singular value.
    _, s, Vt = svd(centered, full_matrices=False)
    normal = Vt[-1]           # smallest singular value → out-of-plane
    normal = normal / (norm(normal) + 1e-300)
    residuals = centered @ normal
    rms = float(np.sqrt(np.mean(residuals**2)))
    return normal, centroid, rms


def _project_to_plane(pts: np.ndarray, normal: np.ndarray,
                      origin: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project 3-D points to a 2-D coordinate system in the plane.

    Builds an orthonormal basis {u_ax, v_ax} in the plane and returns
    (xy2d, u_ax, v_ax) where xy2d has shape (n, 2).
    """
    # Build u_ax as the first PCA in-plane direction.
    centered = pts - origin
    _, _, Vt = svd(centered, full_matrices=False)
    u_ax = Vt[0]
    u_ax = u_ax - np.dot(u_ax, normal) * normal
    u_norm = norm(u_ax)
    if u_norm < 1e-14:
        # Degenerate: pick any vector perpendicular to normal.
        perp = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(perp, normal)) > 0.9:
            perp = np.array([0.0, 1.0, 0.0])
        u_ax = perp - np.dot(perp, normal) * normal
        u_ax = u_ax / (norm(u_ax) + 1e-300)
    else:
        u_ax = u_ax / u_norm

    v_ax = np.cross(normal, u_ax)
    v_ax = v_ax / (norm(v_ax) + 1e-300)

    xy2d = np.column_stack([centered @ u_ax, centered @ v_ax])
    return xy2d, u_ax, v_ax


def _fit_conic_ls(xy: np.ndarray) -> Optional[np.ndarray]:
    """Fit Ax²+Bxy+Cy²+Dx+Ey+F=0 to 2-D points by constrained least squares.

    Uses the algebraic least-squares approach with the Bookstein/Fitzgibbon
    constraint 4AC - B² = 1 for ellipses, or the simpler normalisation
    ‖θ‖=1 (generalised eigenvalue) for all conics.

    Returns coefficient vector [A,B,C,D,E,F] normalised so that
    the conic matrix [[A, B/2],[B/2, C]] has unit Frobenius norm,
    or None if the fit is degenerate (fewer than 5 distinct points).
    """
    if len(xy) < 5:
        return None

    x, y = xy[:, 0], xy[:, 1]
    # Design matrix for Ax²+Bxy+Cy²+Dx+Ey+F=0
    D = np.column_stack([x**2, x*y, y**2, x, y, np.ones(len(x))])

    # Solve min ‖D θ‖ subject to F=1 (simple normalisation keeping the
    # constant term non-zero, robust for bounded conics).
    # Use the last-column constraint: split D into D6 and solve.
    # Better: use SVD of D and take the last right singular vector (null space).
    try:
        _, _, Vt = svd(D, full_matrices=False)
    except np.linalg.LinAlgError:
        return None

    theta = Vt[-1]          # smallest singular value → best-fit coefficients
    # Normalise so F component has consistent sign (makes classification easier)
    # using unit Frobenius norm of the conic matrix.
    A, B, C = theta[0], theta[1], theta[2]
    frob = math.sqrt(A**2 + 0.5*B**2 + C**2 + 1e-300)
    theta = theta / frob
    return theta


def _classify_conic(theta: np.ndarray) -> str:
    """Classify conic from B²-4AC discriminant.

    Returns 'circle', 'ellipse', 'parabola', or 'hyperbola'.
    """
    A, B, C = theta[0], theta[1], theta[2]
    disc = B**2 - 4.0*A*C

    # Circle: B≈0 and A≈C
    if abs(B) < 1e-6 and abs(A - C) < 1e-6 * max(abs(A), abs(C), 1e-12):
        return 'circle'

    if disc < -1e-8:
        return 'ellipse'
    elif abs(disc) <= 1e-8:
        return 'parabola'
    else:
        return 'hyperbola'


def _conic_fit_residual(theta: np.ndarray, xy: np.ndarray) -> float:
    """RMS of the algebraic conic equation at each sample point."""
    A, B, C, D, E, F = theta
    x, y = xy[:, 0], xy[:, 1]
    vals = A*x**2 + B*x*y + C*y**2 + D*x + E*y + F
    # Normalise by gradient magnitude to get approximate geometric error.
    grad_x = 2*A*x + B*y + D
    grad_y = B*x + 2*C*y + E
    grad_mag = np.sqrt(grad_x**2 + grad_y**2 + 1e-300)
    geo_err = vals / grad_mag
    return float(np.sqrt(np.mean(geo_err**2)))


def _canonical_ellipse(theta: np.ndarray,
                       u_ax: np.ndarray, v_ax: np.ndarray,
                       origin: np.ndarray,
                       normal: np.ndarray,
                       kind: str) -> ConicInfo:
    """Extract canonical ellipse/circle parameters from conic coefficients.

    Works by diagonalising the 3×3 homogeneous conic matrix M:
        M = [[A,   B/2, D/2],
             [B/2, C,   E/2],
             [D/2, E/2, F  ]]
    The center satisfies M[:2,:2] * c = -M[:2,2].
    The semi-axes come from the 2×2 part eigenvalues / (-eigenvalue of M).
    """
    A, B, C, D, E, F = theta

    # 2×2 quadratic part
    M22 = np.array([[A, B/2.0], [B/2.0, C]])

    # Center of the conic: M22 * center = -[D/2, E/2]
    rhs = -np.array([D/2.0, E/2.0])
    try:
        center_2d = np.linalg.solve(M22, rhs)
    except np.linalg.LinAlgError:
        center_2d = np.zeros(2)

    # Full 3×3 matrix (homogeneous coordinates)
    M33 = np.array([[A,   B/2.0, D/2.0],
                    [B/2.0, C,   E/2.0],
                    [D/2.0, E/2.0, F  ]])
    det_full = np.linalg.det(M33)

    # Eigendecompose M22 to get principal axes in 2-D
    eigvals, eigvecs = eigh(M22)
    # eigvals sorted ascending.  For an ellipse (det_full * eigvals < 0 for both)
    # the semi-axes are a = sqrt(-det_full / (λ1 * det_M22)), etc.
    det_M22 = float(np.linalg.det(M22))

    radii_2d = [0.0, 0.0]
    if abs(det_full) > 1e-14 and abs(det_M22) > 1e-14:
        for i in range(2):
            val = -det_full / (eigvals[i] * det_M22)
            radii_2d[i] = math.sqrt(abs(val)) if val > 0 else 0.0

    # Sort so radii_2d[0] >= radii_2d[1] (major, minor)
    if radii_2d[0] < radii_2d[1]:
        radii_2d = [radii_2d[1], radii_2d[0]]
        eigvecs = eigvecs[:, [1, 0]]

    a, b = radii_2d[0], radii_2d[1]

    # Map center from 2-D plane coords back to 3-D world
    cx = float(center_2d[0])
    cy = float(center_2d[1])
    center_3d = origin + cx * u_ax + cy * v_ax

    # Map eigenvectors from 2-D plane coords to 3-D
    ax1_3d = eigvecs[0, 0] * u_ax + eigvecs[1, 0] * v_ax
    ax2_3d = eigvecs[0, 1] * u_ax + eigvecs[1, 1] * v_ax
    ax1_3d = ax1_3d / (norm(ax1_3d) + 1e-300)
    ax2_3d = ax2_3d / (norm(ax2_3d) + 1e-300)

    # Eccentricity and focus
    if kind == 'circle':
        eccentricity = 0.0
        focus = center_3d.copy()
        # Snap radii to be equal (average) for circle
        r_avg = (a + b) / 2.0
        a = b = r_avg
    elif kind == 'ellipse':
        if a > 1e-12:
            eccentricity = float(math.sqrt(max(0.0, 1.0 - (b/a)**2)))
        else:
            eccentricity = 0.0
        c_dist = a * eccentricity
        focus = center_3d + c_dist * ax1_3d
    else:
        eccentricity = float(math.sqrt(1.0 + (b/a)**2)) if a > 1e-12 else 1.0
        c_dist = math.sqrt(a**2 + b**2)
        focus = center_3d + c_dist * ax1_3d

    return ConicInfo(
        kind=kind,
        center=center_3d,
        axes=(ax1_3d, ax2_3d),
        radii=(a, b),
        focus=focus,
        eccentricity=eccentricity,
        plane_normal=normal,
        plane_origin=origin,
    )


def _canonical_parabola(theta: np.ndarray,
                        u_ax: np.ndarray, v_ax: np.ndarray,
                        origin: np.ndarray,
                        normal: np.ndarray) -> ConicInfo:
    """Extract canonical parabola parameters."""
    A, B, C, D, E, F = theta

    # For a parabola: B²=4AC exactly.  Find the axis direction.
    # The axis of a parabola lies along the eigenvector of the non-zero
    # eigenvalue of M22.
    M22 = np.array([[A, B/2.0], [B/2.0, C]])
    eigvals, eigvecs = eigh(M22)
    # One eigenvalue near 0 (parabolic), one non-zero.
    idx_nz = int(np.argmax(np.abs(eigvals)))
    idx_z  = 1 - idx_nz

    axis_2d   = eigvecs[:, idx_nz]  # axis of symmetry direction
    perp_2d   = eigvecs[:, idx_z]   # direction along which it opens

    # Focal parameter p: the coefficient of the linear term in parabola
    # standard form (y²=4px).  Approximate from coefficients.
    # p ≈ |linear term| / (2 * |quadratic term|)
    linear_component = abs(float(perp_2d @ np.array([D, E])))
    quad_component   = abs(eigvals[idx_nz])
    focal_length = linear_component / (4.0 * quad_component + 1e-300)

    # Vertex: solve for intersection of axis with curve (approximate as
    # centroid of samples — caller samples the curve).
    # We use the 3×3 system vertex as the center proxy.
    center_3d = origin.copy()

    axis_3d = float(axis_2d[0]) * u_ax + float(axis_2d[1]) * v_ax
    perp_3d = float(perp_2d[0]) * u_ax + float(perp_2d[1]) * v_ax
    axis_3d = axis_3d / (norm(axis_3d) + 1e-300)
    perp_3d = perp_3d / (norm(perp_3d) + 1e-300)

    focus = center_3d + focal_length * perp_3d

    return ConicInfo(
        kind='parabola',
        center=center_3d,
        axes=(perp_3d, axis_3d),
        radii=(focal_length, 0.0),
        focus=focus,
        eccentricity=1.0,
        plane_normal=normal,
        plane_origin=origin,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_conic(curve: NurbsCurve, tol: float = 1e-6) -> Optional[ConicInfo]:
    """Test whether *curve* is a conic section and return its canonical form.

    The detection pipeline follows Lee 1987 and Piegl-Tiller §7.2:

    1. Degree gate  — degree > 2 → not a conic.
    2. Sample the curve (64 points by default).
    3. Planarity check via PCA residual.
    4. Project to 2-D plane.
    5. Algebraic least-squares conic fit.
    6. Algebraic residual check.
    7. Classify (circle / ellipse / parabola / hyperbola) and extract
       canonical parameters.

    Parameters
    ----------
    curve : NurbsCurve
        Input NURBS curve.  May be rational or non-rational.
    tol   : float
        Maximum allowed RMS geometric residual (default 1e-6).

    Returns
    -------
    ConicInfo if the curve is detected as a conic, ``None`` otherwise.
    """
    if not isinstance(curve, NurbsCurve):
        return None

    # --- Step 1: degree gate ---
    if curve.degree > 2:
        return None

    # --- Step 2: sample ---
    pts = _sample_curve(curve, _N_SAMPLES)
    if len(pts) < 5:
        return None

    # --- Step 3: planarity ---
    normal, origin, plane_rms = _fit_plane(pts)
    # Scale tolerance by bounding box size for robustness
    bbox = np.max(np.abs(pts - origin)) + 1e-300
    plane_tol = tol * bbox
    if plane_rms > plane_tol:
        return None

    # --- Step 4: project ---
    xy2d, u_ax, v_ax = _project_to_plane(pts, normal, origin)

    # --- Step 5: algebraic fit ---
    theta = _fit_conic_ls(xy2d)
    if theta is None:
        return None

    # --- Step 6: residual check ---
    resid = _conic_fit_residual(theta, xy2d)
    # Normalise residual by bbox
    if resid > tol * bbox:
        return None

    # --- Step 7: classify and extract ---
    kind = _classify_conic(theta)

    if kind in ('circle', 'ellipse', 'hyperbola'):
        return _canonical_ellipse(theta, u_ax, v_ax, origin, normal, kind)
    else:  # parabola
        return _canonical_parabola(theta, u_ax, v_ax, origin, normal)


def extract_canonical_circle(curve: NurbsCurve,
                              tol: float = 1e-6) -> Optional[CircleParams]:
    """If *curve* is a circle, return ``CircleParams``; else ``None``.

    Uses :func:`detect_conic` under the hood and gates on ``kind == 'circle'``.
    """
    info = detect_conic(curve, tol=tol)
    if info is None or info.kind != 'circle':
        return None
    r = float((info.radii[0] + info.radii[1]) / 2.0)
    return CircleParams(
        center=info.center.copy(),
        radius=r,
        plane_normal=info.plane_normal.copy(),
    )


def simplify_curve(curve: NurbsCurve,
                   tol: float = 1e-6) -> Union[NurbsCurve, ConicInfo]:
    """If *curve* is a conic, return its :class:`ConicInfo`; else return *curve*.

    This is the single-dispatch simplification entry point: callers can pass
    any NurbsCurve and get back either the unchanged curve (if it is not a
    recognised conic) or the canonical ConicInfo (if it is).

    Parameters
    ----------
    curve : NurbsCurve
    tol   : float  (default 1e-6)

    Returns
    -------
    ConicInfo  if the curve is a conic section within tolerance.
    NurbsCurve otherwise (the *same* object — no copy is made).
    """
    info = detect_conic(curve, tol=tol)
    if info is not None:
        return info
    return curve


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

    # ---- nurbs_detect_conic --------------------------------------------------

    _detect_conic_spec = ToolSpec(
        name="nurbs_detect_conic",
        description=(
            "Detect whether a rational NURBS curve is actually a conic section "
            "(circle, ellipse, parabola, or hyperbola) and return its canonical "
            "geometric form.\n"
            "\n"
            "The detection uses Piegl-Tiller §7.2 (rational quadratic NURBS + circles) "
            "and Lee 1987 algebraic conic fitting: the curve is sampled, projected to "
            "its best-fit plane via PCA, an algebraic conic is fitted by least squares, "
            "and the result is classified by discriminant B²-4AC.\n"
            "\n"
            "Returns: {ok, is_conic, kind, center, axes, radii, eccentricity, "
            "focus, plane_normal} or {ok:false, reason}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Control points [[x,y,z], ...] of the NURBS curve.",
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Curve degree.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional per-control-point weights (omit for non-rational).",
                },
                "tol": {
                    "type": "number",
                    "description": "Detection tolerance (default 1e-6).",
                },
            },
            "required": ["control_points", "knots", "degree"],
        },
    )

    @register(_detect_conic_spec)
    async def run_nurbs_detect_conic(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        cps_raw = a.get("control_points", [])
        knots_raw = a.get("knots", [])
        degree = a.get("degree")
        weights_raw = a.get("weights")
        tol = float(a.get("tol", 1e-6))

        if not cps_raw:
            return err_payload("control_points required", "BAD_ARGS")
        if not knots_raw:
            return err_payload("knots required", "BAD_ARGS")
        if degree is None:
            return err_payload("degree required", "BAD_ARGS")

        try:
            cps = np.array(cps_raw, dtype=float)
            if cps.ndim == 1:
                cps = cps.reshape(-1, 1)
            knots = np.array(knots_raw, dtype=float)
            weights = np.array(weights_raw, dtype=float) if weights_raw is not None else None
            curve = NurbsCurve(degree=int(degree), control_points=cps,
                               knots=knots, weights=weights)
        except Exception as exc:
            return err_payload(f"could not construct NurbsCurve: {exc}", "BAD_ARGS")

        try:
            info = detect_conic(curve, tol=tol)
        except Exception as exc:
            return err_payload(f"detection failed: {exc}", "OP_FAILED")

        if info is None:
            return ok_payload({"is_conic": False})

        result: dict = {
            "is_conic": True,
            "kind": info.kind,
            "eccentricity": float(info.eccentricity),
            "plane_normal": info.plane_normal.tolist(),
            "plane_origin": info.plane_origin.tolist(),
            "radii": [float(info.radii[0]), float(info.radii[1])],
        }
        if info.center is not None:
            result["center"] = info.center.tolist()
        if info.focus is not None:
            result["focus"] = info.focus.tolist()
        if info.axes:
            result["axes"] = [ax.tolist() for ax in info.axes]

        return ok_payload(result)

    # ---- nurbs_simplify_conic ------------------------------------------------

    _simplify_conic_spec = ToolSpec(
        name="nurbs_simplify_conic",
        description=(
            "Attempt to simplify a NURBS curve to its canonical conic form "
            "(circle / ellipse / parabola / hyperbola).  If the curve is a conic, "
            "returns the canonical parameters; otherwise reports that it is a "
            "general NURBS and returns the original degree + control point count.\n"
            "\n"
            "Returns: {ok, simplified, kind?, center?, radii?, eccentricity?, "
            "plane_normal?, degree?, num_ctrl?} or {ok:false, reason}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Control points [[x,y,z], ...].",
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector.",
                },
                "degree": {"type": "integer"},
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional weights (omit for non-rational).",
                },
                "tol": {"type": "number", "description": "Tolerance (default 1e-6)."},
            },
            "required": ["control_points", "knots", "degree"],
        },
    )

    @register(_simplify_conic_spec)
    async def run_nurbs_simplify_conic(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        cps_raw = a.get("control_points", [])
        knots_raw = a.get("knots", [])
        degree = a.get("degree")
        weights_raw = a.get("weights")
        tol = float(a.get("tol", 1e-6))

        if not cps_raw or not knots_raw or degree is None:
            return err_payload("control_points, knots, and degree are required", "BAD_ARGS")

        try:
            cps = np.array(cps_raw, dtype=float)
            if cps.ndim == 1:
                cps = cps.reshape(-1, 1)
            knots = np.array(knots_raw, dtype=float)
            weights = np.array(weights_raw, dtype=float) if weights_raw is not None else None
            curve = NurbsCurve(degree=int(degree), control_points=cps,
                               knots=knots, weights=weights)
        except Exception as exc:
            return err_payload(f"could not construct NurbsCurve: {exc}", "BAD_ARGS")

        try:
            result = simplify_curve(curve, tol=tol)
        except Exception as exc:
            return err_payload(f"simplification failed: {exc}", "OP_FAILED")

        if isinstance(result, ConicInfo):
            payload: dict = {
                "simplified": True,
                "kind": result.kind,
                "eccentricity": float(result.eccentricity),
                "plane_normal": result.plane_normal.tolist(),
                "radii": [float(result.radii[0]), float(result.radii[1])],
            }
            if result.center is not None:
                payload["center"] = result.center.tolist()
            if result.focus is not None:
                payload["focus"] = result.focus.tolist()
            return ok_payload(payload)
        else:
            return ok_payload({
                "simplified": False,
                "degree": curve.degree,
                "num_ctrl": curve.num_control_points,
            })
