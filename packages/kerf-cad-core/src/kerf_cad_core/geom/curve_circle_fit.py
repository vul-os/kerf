"""
kerf_cad_core.geom.curve_circle_fit — fit a circle to a 2D NurbsCurve.

Algorithms
----------
Kasa (1976)
    Algebraic: reduce to linear system x² + y² = ax + by + c.
    Fast, good for low noise, can be biased for short arcs
    (Coope 1993 bias analysis).

Taubin (1991)
    Algebraic distance fit with constraint normalization that removes the
    bias of the Kasa method.  Solves the generalized eigenvalue problem
    on the 4×4 data matrix.  Recommended for near-linear or short arcs.

References
----------
* Kasa, I. (1976). "A curve fitting procedure and its error analysis."
  IEEE Trans. Instrum. Meas. 25(1): 8–14.
* Taubin, G. (1991). "Estimation of planar curves, surfaces, and
  nonplanar space curves defined by implicit equations with applications
  to edge and range image segmentation." IEEE TPAMI 13(11): 1115–1138.
* Pratt, V. (1987). "Direct least-squares fitting of algebraic surfaces."
  SIGGRAPH Computer Graphics 21(4): 145–152.

Caveats
-------
* 2D only.  If the curve lives in 3D, project it onto a best-fit plane
  first (or pass explicit XY control points); the fit uses only x, y.
* For short arcs (sweep < ~30°) both methods can be numerically sensitive;
  Taubin is preferred in that regime.
* ``rms_residual_mm`` is the RMS of |distance_to_circle − radius|, not
  a signed curvature deviation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Union

import numpy as np


# ---------------------------------------------------------------------------
# Public data type
# ---------------------------------------------------------------------------

@dataclass
class CircleFitResult:
    """Result of fitting a circle to a 2D point set / curve.

    Attributes
    ----------
    center_xy : tuple[float, float]
        Fitted circle centre ``(cx, cy)`` in the same units as the input.
    radius : float
        Fitted radius (same units as input — assumed millimetres for CAD).
    rms_residual_mm : float
        RMS of the signed radial residuals |dist_i − R| over all sample points.
        Near-zero for exact circles; large for lines or irregular curves.
    max_residual_mm : float
        Maximum absolute radial residual over all sample points.
    fit_method : str
        ``"kasa"`` or ``"taubin"`` — whichever was used.
    honest_caveat : str
        Human-readable caveat (empty string for a well-conditioned fit).
        Populated when the fit may be unreliable (few points, near-linear
        data, very large/small radius, short arc sweep, etc.).
    """

    center_xy: tuple[float, float]
    radius: float
    rms_residual_mm: float
    max_residual_mm: float
    fit_method: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core algebraic helpers
# ---------------------------------------------------------------------------

def _kasa(pts: np.ndarray) -> tuple[float, float, float]:
    """Kasa (1976) algebraic circle fit.

    Returns ``(cx, cy, r)``.  Raises ``np.linalg.LinAlgError`` if the
    system is singular (collinear points).

    The linear system is::

        [2x  2y  1] [cx]   [x²+y²]
                    [cy] =
                    [d ]

    i.e. least-squares of  x² + y² = 2·cx·x + 2·cy·y + d
    where  d = r² - cx² - cy²,  so  r² = d + cx² + cy².
    """
    x = pts[:, 0]
    y = pts[:, 1]
    z = x * x + y * y
    ones = np.ones(len(x))
    A = np.column_stack([2.0 * x, 2.0 * y, ones])
    b = z
    result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, d = result  # d = r² - cx² - cy²
    r2 = d + cx * cx + cy * cy
    if r2 < 0.0:
        # Degenerate (collinear data): r² theoretically ≥ 0
        r2 = 0.0
    return float(cx), float(cy), float(math.sqrt(r2))


def _taubin(pts: np.ndarray) -> tuple[float, float, float]:
    """Taubin (1991) constraint-normalised algebraic circle fit.

    Solves  min ||A·a||² / ||B·a||²  where the 4-vector ``a = [A,B,C,D]``
    represents  A(x²+y²) + Bx + Cy + D = 0.  The constraint matrix B
    (Taubin's Z) eliminates the scale ambiguity that biases Kasa.

    Returns ``(cx, cy, r)``.
    """
    x = pts[:, 0]
    y = pts[:, 1]
    n = len(x)

    # Centre the data for numerical stability
    mx, my = x.mean(), y.mean()
    u = x - mx
    v = y - my

    z = u * u + v * v
    zmean = z.mean()

    # 4-column data matrix: columns [z, u, v, 1]
    Z = np.column_stack([z, u, v, np.ones(n)])

    # M = (1/n) Z^T Z
    M = (Z.T @ Z) / n

    # Constraint (normalization) matrix N (Taubin eq. 22):
    # N = [[8*zmean, 0, 0, 4],
    #      [0,       1, 0, 0],
    #      [0,       0, 1, 0],
    #      [4,       0, 0, 0]]
    N = np.array([
        [8.0 * zmean, 0.0, 0.0, 4.0],
        [0.0,         1.0, 0.0, 0.0],
        [0.0,         0.0, 1.0, 0.0],
        [4.0,         0.0, 0.0, 0.0],
    ])

    # Solve generalized eigenvalue problem M a = λ N a
    # We want the eigenvector for the eigenvalue closest to zero from above.
    # For exact data this eigenvalue is ~0; for noisy data it is the smallest
    # positive value.  Using "smallest positive with threshold > 1e-14" fails
    # for short arcs where the true λ is ≈ 0 but computed as ~1e-15.
    try:
        eigvals, eigvecs = np.linalg.eig(np.linalg.solve(N, M))
    except np.linalg.LinAlgError:
        # N singular (degenerate data) — fall back to Kasa
        return _kasa(pts)

    eigvals = eigvals.real
    eigvecs = eigvecs.real

    # Select the eigenvalue with the smallest absolute value among non-negative
    # eigenvalues (allowing a tiny negative tolerance for floating-point noise).
    non_neg_mask = eigvals >= -1e-8
    if non_neg_mask.any():
        idx = int(np.argmin(np.where(non_neg_mask, np.abs(eigvals), np.inf)))
    else:
        # All negative (fully degenerate) — fall back to Kasa
        return _kasa(pts)
    a = eigvecs[:, idx]

    A_coeff, B_coeff, C_coeff, D_coeff = a
    if abs(A_coeff) < 1e-14:
        return _kasa(pts)

    # Circle parameters from conic coefficients
    cx = -B_coeff / (2.0 * A_coeff) + mx
    cy = -C_coeff / (2.0 * A_coeff) + my
    r2 = (B_coeff * B_coeff + C_coeff * C_coeff - 4.0 * A_coeff * D_coeff) / (
        4.0 * A_coeff * A_coeff
    )
    if r2 < 0.0:
        r2 = 0.0
    return float(cx), float(cy), float(math.sqrt(r2))


# ---------------------------------------------------------------------------
# Residual helpers
# ---------------------------------------------------------------------------

def _residuals(pts: np.ndarray, cx: float, cy: float, r: float) -> np.ndarray:
    """Signed radial residuals: dist_i − r (mm if input is mm)."""
    dx = pts[:, 0] - cx
    dy = pts[:, 1] - cy
    dist = np.sqrt(dx * dx + dy * dy)
    return dist - r


# ---------------------------------------------------------------------------
# Sampling helper
# ---------------------------------------------------------------------------

def _sample_curve_2d(curve_or_points, num_samples: int) -> np.ndarray:
    """Return an (N, 2) float array of 2D points.

    Accepts:
    * A ``NurbsCurve`` — evaluated at ``num_samples`` uniformly-spaced
      parameter values on ``[knots[0], knots[-1]]``.  Only the first two
      coordinate dimensions (x, y) are used.
    * A sequence / array of 2D or 3D points — reshaped to (N, ≥2) and
      only the first two columns are returned.
    """
    # Lazy import to keep this module independent of the rest of the kernel
    try:
        from kerf_cad_core.geom.nurbs import NurbsCurve, de_boor  # type: ignore[import]
        _nurbs_available = True
    except ImportError:
        _nurbs_available = False
        NurbsCurve = None  # type: ignore[assignment,misc]

    if _nurbs_available and NurbsCurve is not None and isinstance(curve_or_points, NurbsCurve):
        curve = curve_or_points
        a = float(curve.knots[0])
        b = float(curve.knots[-1])
        us = np.linspace(a, b, num_samples)
        pts = np.array([de_boor(curve, u) for u in us], dtype=float)
        # pts may be (N, 2) or (N, 3) — take first two columns
        if pts.ndim == 2 and pts.shape[1] >= 2:
            return pts[:, :2]
        raise ValueError(
            "NurbsCurve evaluation returned unexpected shape; "
            f"got {pts.shape}, expected (N, ≥2)"
        )

    # Fall back: assume a sequence of points
    arr = np.asarray(curve_or_points, dtype=float)
    if arr.ndim == 1:
        # Flat list alternating x, y?
        if len(arr) % 2 != 0:
            raise ValueError(
                "Cannot interpret 1D array as 2D points: length is odd."
            )
        arr = arr.reshape(-1, 2)
    if arr.ndim != 2 or arr.shape[1] < 2:
        raise ValueError(
            f"Expected 2D point array of shape (N, ≥2), got {arr.shape}."
        )
    return arr[:, :2]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fit_circle_to_curve(
    curve_or_points: Union["NurbsCurve", Sequence, np.ndarray],  # type: ignore[type-arg]
    num_samples: int = 100,
    method: str = "kasa",
) -> CircleFitResult:
    """Fit a circle to a 2D NurbsCurve (or point sequence) by least squares.

    Parameters
    ----------
    curve_or_points:
        A ``NurbsCurve`` whose first two coordinate dimensions define the
        2D curve, OR a sequence / NumPy array of 2D or 3D points (only
        x, y are used).
    num_samples:
        Number of parameter samples when evaluating a NurbsCurve.
        Ignored when ``curve_or_points`` is already a point array.
        Minimum 3 (required for a unique circle fit).
    method:
        ``"kasa"`` (default) — fast, good for low noise and well-sampled
        arcs.  ``"taubin"`` — bias-corrected, better for short arcs and
        near-linear data.

    Returns
    -------
    CircleFitResult
        See :class:`CircleFitResult` docstring.  ``honest_caveat`` is
        populated whenever the fit quality or input geometry raises
        concerns.

    Notes
    -----
    * Only 2D: the x and y coordinates of the sampled points are used.
      For 3D space curves, project onto a plane first.
    * The Kasa method can be numerically biased when the arc subtends
      less than ~30°; prefer ``method='taubin'`` in that regime.
    * ``rms_residual_mm`` assumes millimetre units.  If your model uses
      metres, the residual will still be numerically correct but the
      unit label is wrong — scale accordingly.
    """
    num_samples = max(3, int(num_samples))
    method = method.lower().strip()
    if method not in ("kasa", "taubin"):
        raise ValueError(f"method must be 'kasa' or 'taubin', got {method!r}")

    # Sample 2D points
    pts = _sample_curve_2d(curve_or_points, num_samples)
    n = len(pts)
    if n < 3:
        return CircleFitResult(
            center_xy=(0.0, 0.0),
            radius=0.0,
            rms_residual_mm=float("inf"),
            max_residual_mm=float("inf"),
            fit_method=method,
            honest_caveat=(
                f"Only {n} point(s) available; need ≥ 3 for a unique circle fit."
            ),
        )

    # Run chosen algorithm
    caveats = []
    try:
        if method == "kasa":
            cx, cy, r = _kasa(pts)
        else:
            cx, cy, r = _taubin(pts)
    except (np.linalg.LinAlgError, ValueError) as exc:
        # Singular / degenerate — attempt fallback
        caveats.append(f"Primary fit singular ({exc}); using Kasa fallback.")
        try:
            cx, cy, r = _kasa(pts)
        except Exception as exc2:
            return CircleFitResult(
                center_xy=(0.0, 0.0),
                radius=0.0,
                rms_residual_mm=float("inf"),
                max_residual_mm=float("inf"),
                fit_method=method,
                honest_caveat=f"Fit failed: {exc2}",
            )

    # Compute residuals
    resid = _residuals(pts, cx, cy, r)
    rms = float(np.sqrt(np.mean(resid * resid)))
    maxr = float(np.max(np.abs(resid)))

    # Populate honest caveats
    if r < 1e-9:
        caveats.append("Fitted radius is near-zero; input may be a single point.")
    elif r > 1e9:
        caveats.append(
            "Fitted radius is extremely large; input may be nearly linear — "
            "the circle fit is valid but represents an infinite-radius approximation."
        )

    # Check if input is nearly collinear by comparing span to radius
    span = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
    if r > 1e-9 and span > 1e-9:
        # Arc half-angle (rough): sin(θ/2) ≈ span / (2r) for a chord
        sin_half = span / (2.0 * r)
        if sin_half < math.sin(math.radians(15)):
            caveats.append(
                "Arc sweep appears < 30°; Kasa may be biased — consider method='taubin'."
                if method == "kasa" else
                "Arc sweep appears < 30°; fit is valid but sensitivity to noise is higher."
            )
        if sin_half > 2.0:
            # span > 4r → cannot be a single arc; likely collinear
            caveats.append(
                "Input point spread exceeds 2× the fitted radius — data may be "
                "collinear or multi-arc; residual is large by design."
            )

    if rms > 1.0:
        caveats.append(
            f"RMS residual = {rms:.3g} mm (> 1 mm): the curve is not well-approximated "
            "by a single circle."
        )

    if n < 10:
        caveats.append(f"Only {n} sample points; accuracy may be limited.")

    caveat_str = "  ".join(caveats)
    return CircleFitResult(
        center_xy=(cx, cy),
        radius=r,
        rms_residual_mm=rms,
        max_residual_mm=maxr,
        fit_method=method,
        honest_caveat=caveat_str,
    )


# ===========================================================================
# LLM tool registration (gated — graceful no-op when registry absent)
# ===========================================================================

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811

    _nurbs_fit_circle_spec = ToolSpec(
        name="nurbs_fit_circle_to_curve",
        description=(
            "Fit a circle to a 2D NURBS curve (or a list of 2D/3D points) using "
            "least-squares algebraic fitting (Kasa 1976 or Taubin 1991).\n\n"
            "Use cases:\n"
            "• Detect circular regions in machined edges or imported geometry.\n"
            "• Snap-to-circle assist in the 2D sketcher.\n"
            "• Identify near-circular arcs in STEP/IGES imported B-rep edges.\n\n"
            "Input: a list of 2D or 3D point coordinates [[x,y], ...] (only x,y used).\n"
            "For 3D space curves, project onto a plane first.\n\n"
            "Returns: {ok, center_x, center_y, radius_mm, rms_residual_mm, "
            "max_residual_mm, fit_method, honest_caveat}\n"
            "Errors: {ok:false, reason, code}.  Never raises.\n\n"
            "CAVEAT: 2D only.  For 3D space curves use planar projection first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "description": (
                        "List of 2D or 3D points [[x, y], ...] or [[x, y, z], ...]. "
                        "Only the x and y coordinates are used."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                    },
                    "minItems": 3,
                },
                "method": {
                    "type": "string",
                    "enum": ["kasa", "taubin"],
                    "description": (
                        "Fitting algorithm: 'kasa' (fast, good for well-sampled arcs, "
                        "default) or 'taubin' (bias-corrected, better for short arcs "
                        "< 30° and near-linear data)."
                    ),
                },
            },
            "required": ["points"],
        },
    )

    @register(_nurbs_fit_circle_spec)
    async def _nurbs_fit_circle_to_curve_tool(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        points = a.get("points")
        if points is None or not isinstance(points, list) or len(points) < 3:
            return err_payload(
                "'points' must be a list of ≥ 3 [x, y] or [x, y, z] pairs.",
                "BAD_ARGS",
            )

        method = a.get("method", "kasa")
        if method not in ("kasa", "taubin"):
            return err_payload(
                f"method must be 'kasa' or 'taubin', got {method!r}", "BAD_ARGS"
            )

        try:
            result = fit_circle_to_curve(
                points, num_samples=len(points), method=method
            )
        except Exception as exc:
            return err_payload(f"fit failed: {exc}", "OP_FAILED")

        if not math.isfinite(result.rms_residual_mm):
            return err_payload(
                result.honest_caveat or "circle fit did not converge", "OP_FAILED"
            )

        return ok_payload({
            "center_x": result.center_xy[0],
            "center_y": result.center_xy[1],
            "radius_mm": result.radius,
            "rms_residual_mm": result.rms_residual_mm,
            "max_residual_mm": result.max_residual_mm,
            "fit_method": result.fit_method,
            "honest_caveat": result.honest_caveat,
        })
