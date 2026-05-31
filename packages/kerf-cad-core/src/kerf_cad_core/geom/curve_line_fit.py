"""
kerf_cad_core.geom.curve_line_fit — fit a straight line to a 2D NurbsCurve.

Algorithm
---------
Total Least Squares (TLS) via Singular Value Decomposition (SVD).

Given N sampled 2-D points {p_i}:

1. Compute the centroid  μ = (1/N) Σ p_i.
2. Form the centred matrix  A ∈ R^{N×2}  where row i = p_i − μ.
3. Compute the thin SVD  A = U Σ V^T.
4. The principal direction (right-singular vector with the *largest*
   singular value) is V[:, 0].  This is the direction along which
   variance is maximised — i.e. the least-squares line direction.
5. The perpendicular (orthogonal) residuals are the projections of
   each centred point onto the minor singular vector V[:, 1].
   RMS and max residuals are computed from those.

Why TLS?
--------
Ordinary least-squares (OLS) minimises vertical residuals and is
biased when the line is nearly vertical.  TLS minimises orthogonal
(perpendicular) distances — the geometrically correct measure for
curve fitting.  For 2-D, TLS via SVD is equivalent to fitting the
principal axis of the covariance matrix.

References
----------
* Press, Teukolsky, Vetterling & Flannery, "Numerical Recipes in C"
  3rd ed. §15.7 — Total Least Squares / PCA line fit.
* Lawson & Hanson, "Solving Least Squares Problems" (SIAM 1974/1995)
  §6 — SVD for geometric fitting.
* Golub & Van Loan, "Matrix Computations" 4th ed. §2.4 — SVD geometry.

Caveats
-------
* **2D only.**  The fit uses only the x and y coordinates.  For 3-D
  space curves, project onto a best-fit plane first (or pass explicit
  XY control points); ``is_planar_line`` is always True here because
  we operate in 2D.  For a 3D principal-axis fit you would need the
  full 3D SVD separately.
* ``rms_residual_mm`` and ``max_residual_mm`` are in the same units
  as the input points (assumed millimetres for CAD).  If your model
  uses metres the residuals will be numerically correct but the
  unit label is wrong — scale accordingly.
* The returned ``direction_xy`` is a unit vector.  The sign is chosen
  so that the x-component (or the y-component if x≈0) is positive,
  giving a canonical orientation.  The *line* is undirected.
* Uniformly-spaced parameter sampling is used; for highly irregular
  NURBS parameterisations the sample density may cluster near knots.
  If arc-length-uniform sampling matters, pre-resample the curve with
  ``resample_uniform_arc_length`` from ``geom.curve_resample_uniform``
  before calling this function.
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
class LineFitResult:
    """Result of fitting a straight line to a 2D point set / curve.

    Attributes
    ----------
    origin_xy : tuple[float, float]
        A point on the fitted line (the centroid of the sampled points).
        Units: same as input (mm for CAD).
    direction_xy : tuple[float, float]
        Unit vector along the fitted line.  Canonical: x-component ≥ 0
        (ties broken by y-component ≥ 0).  The line is undirected — both
        ``direction_xy`` and its negation describe the same geometric line.
    rms_residual_mm : float
        Root-mean-square of the perpendicular (orthogonal) distances from
        each sample point to the fitted line.  Near-zero for exact straight
        lines; proportional to noise standard deviation for noisy lines.
    max_residual_mm : float
        Maximum absolute perpendicular distance from any sample point to
        the fitted line.
    is_planar_line : bool
        Always ``True`` for this 2D implementation.  Provided as a flag so
        callers can assert the plane constraint.  A future 3D extension
        would set this to ``False`` for space-curve fits.
    honest_caveat : str
        Human-readable caveat string.  Empty for a well-conditioned fit.
        Populated when the input is poorly conditioned (too few points,
        degenerate/single-point input, large residuals suggesting a
        non-linear curve, etc.).
    """

    origin_xy: tuple[float, float]
    direction_xy: tuple[float, float]
    rms_residual_mm: float
    max_residual_mm: float
    is_planar_line: bool
    honest_caveat: str


# ---------------------------------------------------------------------------
# Sampling helper (mirrors curve_circle_fit._sample_curve_2d)
# ---------------------------------------------------------------------------

def _sample_curve_2d(curve_or_points, num_samples: int) -> np.ndarray:
    """Return an (N, 2) float64 array of 2D points.

    Accepts:
    * A ``NurbsCurve`` — evaluated at ``num_samples`` uniformly-spaced
      parameter values on ``[knots[0], knots[-1]]``.  Only the first two
      coordinate dimensions (x, y) are used.
    * A sequence / array of 2D or 3D points — reshaped to (N, ≥2) and
      only the first two columns are returned.
    """
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
        if pts.ndim == 2 and pts.shape[1] >= 2:
            return pts[:, :2]
        raise ValueError(
            "NurbsCurve evaluation returned unexpected shape; "
            f"got {pts.shape}, expected (N, ≥2)"
        )

    arr = np.asarray(curve_or_points, dtype=float)
    if arr.ndim == 1:
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
# Core TLS / SVD fit
# ---------------------------------------------------------------------------

def _tls_fit_2d(pts: np.ndarray) -> tuple[float, float, float, float]:
    """Total-least-squares line fit via SVD.

    Parameters
    ----------
    pts : ndarray, shape (N, 2)
        2D point array.  N must be ≥ 2.

    Returns
    -------
    cx, cy : float
        Centroid (the fitted line passes through this point).
    dx, dy : float
        Unit direction vector, normalised and canonicalised (dx ≥ 0;
        if dx ≈ 0 then dy ≥ 0).

    Raises
    ------
    ValueError
        If ``pts`` has fewer than 2 rows.
    """
    n = len(pts)
    if n < 2:
        raise ValueError(f"Need ≥ 2 points for line fit, got {n}.")

    cx = float(pts[:, 0].mean())
    cy = float(pts[:, 1].mean())

    # Centred matrix A ∈ R^{N×2}
    A = pts - np.array([cx, cy])

    # Thin SVD: A = U @ diag(s) @ Vt, V columns are right-singular vectors.
    # np.linalg.svd returns Vt, so V = Vt.T.
    # The direction with the *largest* singular value is the principal axis.
    _, s, Vt = np.linalg.svd(A, full_matrices=False)

    # Largest singular value → index 0 (numpy returns in descending order)
    d = Vt[0]   # shape (2,) — right-singular vector for max singular value
    dx, dy = float(d[0]), float(d[1])

    # Canonicalise: ensure dx ≥ 0; if dx ≈ 0, ensure dy ≥ 0
    if dx < 0.0 or (abs(dx) < 1e-14 and dy < 0.0):
        dx, dy = -dx, -dy

    # Normalise (SVD guarantees unit norm, but do it defensively)
    norm = math.hypot(dx, dy)
    if norm > 1e-14:
        dx /= norm
        dy /= norm

    return cx, cy, dx, dy


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fit_line_to_curve(
    curve_or_points: Union["NurbsCurve", Sequence, np.ndarray],  # type: ignore[type-arg]
    num_samples: int = 100,
) -> LineFitResult:
    """Fit a straight line to a 2D NurbsCurve (or point sequence) via TLS/SVD.

    Parameters
    ----------
    curve_or_points:
        A ``NurbsCurve`` whose first two coordinate dimensions define the
        2D curve, OR a sequence / NumPy array of 2D or 3D points (only
        x, y are used).
    num_samples:
        Number of parameter samples when evaluating a NurbsCurve.
        Ignored when ``curve_or_points`` is already a point array.
        Minimum 2 (required for a unique line fit; ≥ 10 recommended
        for reliable residual statistics).

    Returns
    -------
    LineFitResult
        See :class:`LineFitResult`.  ``honest_caveat`` is populated
        whenever the fit quality or input geometry raises concerns.

    Notes
    -----
    * **2D only**: x and y coordinates of the sampled points are used.
      For 3D space curves, project onto a plane first.
    * The principal direction returned by SVD maximises explained
      variance — equivalent to the eigenvector of the 2×2 covariance
      matrix for the largest eigenvalue.  For a perfect straight line
      this eigenvector is exact regardless of noise in the minor
      direction.
    * ``rms_residual_mm`` and ``max_residual_mm`` assume mm units.
    * For a non-linear curve (e.g. a circle) ``rms_residual_mm`` will
      be large and ``honest_caveat`` will warn accordingly.
    * The returned ``direction_xy`` is a canonical unit vector; the
      line is undirected (direction and its negation are equivalent).
    """
    num_samples = max(2, int(num_samples))
    pts = _sample_curve_2d(curve_or_points, num_samples)
    n = len(pts)

    caveats: list[str] = []

    if n < 2:
        return LineFitResult(
            origin_xy=(float(pts[0, 0]), float(pts[0, 1])) if n == 1 else (0.0, 0.0),
            direction_xy=(1.0, 0.0),
            rms_residual_mm=float("inf"),
            max_residual_mm=float("inf"),
            is_planar_line=True,
            honest_caveat=(
                f"Only {n} point(s) available; need ≥ 2 for a unique line fit."
            ),
        )

    # Degenerate: all points identical
    spread = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
    if spread < 1e-14:
        return LineFitResult(
            origin_xy=(float(pts[0, 0]), float(pts[0, 1])),
            direction_xy=(1.0, 0.0),
            rms_residual_mm=0.0,
            max_residual_mm=0.0,
            is_planar_line=True,
            honest_caveat=(
                "All sample points are identical (degenerate input); "
                "direction is undefined — returning (1,0) as a placeholder."
            ),
        )

    # Run TLS/SVD fit
    try:
        cx, cy, dx, dy = _tls_fit_2d(pts)
    except (np.linalg.LinAlgError, ValueError) as exc:
        return LineFitResult(
            origin_xy=(0.0, 0.0),
            direction_xy=(1.0, 0.0),
            rms_residual_mm=float("inf"),
            max_residual_mm=float("inf"),
            is_planar_line=True,
            honest_caveat=f"SVD line fit failed: {exc}",
        )

    # Perpendicular (orthogonal) residuals:
    # For each centred point p, the perpendicular distance to the line
    # through origin with direction (dx, dy) is |(-dy)*px + dx*py|.
    centred = pts - np.array([cx, cy])
    # Perpendicular unit vector is (-dy, dx)
    perp_resid = -dy * centred[:, 0] + dx * centred[:, 1]  # signed
    abs_resid = np.abs(perp_resid)
    rms = float(np.sqrt(np.mean(abs_resid ** 2)))
    maxr = float(np.max(abs_resid))

    # Honest caveats
    if n < 10:
        caveats.append(f"Only {n} sample points; residual statistics may be unreliable.")

    if rms > 1.0:
        caveats.append(
            f"RMS perpendicular residual = {rms:.3g} mm (> 1 mm): "
            "the curve is not well-approximated by a single straight line."
        )

    # Check how much of the total variance is explained by the principal axis.
    # Variance along principal direction vs. perpendicular direction.
    # For a perfect line the perpendicular variance → 0.
    total_var = float(np.var(centred[:, 0]) + np.var(centred[:, 1]))
    if total_var > 1e-28:
        perp_var = float(np.var(perp_resid))
        linearity_r2 = 1.0 - perp_var / total_var
        if linearity_r2 < 0.95:
            caveats.append(
                f"Linearity R² = {linearity_r2:.3f} (< 0.95): "
                "the curve deviates significantly from a straight line — "
                "line fit may not be meaningful."
            )

    caveat_str = "  ".join(caveats)
    return LineFitResult(
        origin_xy=(cx, cy),
        direction_xy=(dx, dy),
        rms_residual_mm=rms,
        max_residual_mm=maxr,
        is_planar_line=True,
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

    _nurbs_fit_line_spec = ToolSpec(
        name="nurbs_fit_line_to_curve",
        description=(
            "Fit a straight line to a 2D NURBS curve (or a list of 2D/3D points) "
            "via total least squares (TLS) / SVD.\n\n"
            "Use cases:\n"
            "• Detect linear segments in machined edges or imported CAD geometry.\n"
            "• Snap-to-line assist in the 2D sketcher.\n"
            "• Identify near-straight edges in STEP/IGES imported B-rep profiles.\n"
            "• Quality check: measure how far a nominally-straight edge deviates.\n\n"
            "Algorithm: centroid subtraction + thin SVD; principal right-singular "
            "vector gives the least-squares line direction (Press §15.7 TLS; "
            "Lawson-Hanson §6 SVD geometric fitting).\n\n"
            "Input: a list of 2D or 3D point coordinates [[x,y], ...] "
            "(only x,y used).\n"
            "For 3D space curves, project onto a plane first.\n\n"
            "Returns: {ok, origin_x, origin_y, direction_x, direction_y, "
            "rms_residual_mm, max_residual_mm, is_planar_line, honest_caveat}\n"
            "Errors: {ok:false, reason, code}.  Never raises.\n\n"
            "CAVEAT: 2D only.  For 3D space curves use planar projection first. "
            "The direction vector is a unit vector and the line is undirected."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "description": (
                        "List of 2D or 3D points [[x, y], ...] or [[x, y, z], ...]. "
                        "Only the x and y coordinates are used.  Minimum 2 points."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                    },
                    "minItems": 2,
                },
            },
            "required": ["points"],
        },
    )

    @register(_nurbs_fit_line_spec)
    async def _nurbs_fit_line_to_curve_tool(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        points = a.get("points")
        if points is None or not isinstance(points, list) or len(points) < 2:
            return err_payload(
                "'points' must be a list of ≥ 2 [x, y] or [x, y, z] pairs.",
                "BAD_ARGS",
            )

        try:
            result = fit_line_to_curve(
                points, num_samples=len(points)
            )
        except Exception as exc:
            return err_payload(f"fit failed: {exc}", "OP_FAILED")

        if not math.isfinite(result.rms_residual_mm):
            return err_payload(
                result.honest_caveat or "line fit did not converge", "OP_FAILED"
            )

        return ok_payload({
            "origin_x": result.origin_xy[0],
            "origin_y": result.origin_xy[1],
            "direction_x": result.direction_xy[0],
            "direction_y": result.direction_xy[1],
            "rms_residual_mm": result.rms_residual_mm,
            "max_residual_mm": result.max_residual_mm,
            "is_planar_line": result.is_planar_line,
            "honest_caveat": result.honest_caveat,
        })
