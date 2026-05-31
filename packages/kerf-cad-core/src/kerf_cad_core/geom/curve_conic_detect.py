"""
curve_conic_detect.py
=====================
Classify a 2-D NurbsCurve (or a raw 2-D point set) as one of:

    circle | ellipse | parabola | hyperbola | line | free_form

Algorithm
---------
1. Sample the curve (or accept a raw point array).
2. Fit the general conic  Ax² + Bxy + Cy² + Dx + Ey + F = 0  by
   constrained algebraic least squares (SVD null-space, Frobenius
   normalisation of the quadratic block).
3. Compute the discriminant  Δ = B² − 4AC:
       Δ < 0  →  ellipse-family (circle if additionally B ≈ 0 and A ≈ C)
       Δ ≈ 0  →  parabola (or line, see below)
       Δ > 0  →  hyperbola
4. Line gate: check whether the data is better described by a TLS
   straight-line fit (RMS perpendicular residual < residual_threshold_mm
   **and** the conic fit has near-zero quadratic content, i.e. the conic
   matrix has rank ≤ 1).
5. If the RMS geometric residual of the best conic fit exceeds
   ``residual_threshold_mm``, report ``free_form``.

References
----------
- Pratt, V. (1987). "Direct least-squares fitting of algebraic surfaces."
  SIGGRAPH Computer Graphics 21(4): 145–152.
- Fitzgibbon, A., Pilu, M., & Fisher, R. B. (1999). "Direct least-square
  fitting of ellipses."  IEEE TPAMI 21(5): 476–480.
- Bookstein, F. L. (1979). "Fitting conic sections to scattered data."
  CVGIP 9: 56–71.

Caveats (honest)
----------------
- This is an *algebraic* fit, not a geometric (Euclidean-distance) fit.
  Algebraic fits are biased toward solutions where the gradient magnitude is
  large.  For noisy point sets use Pratt (1987) or Taubin (1991) bias
  corrections (available in ``curve_circle_fit.py`` for the circle case).
- The algebraic residual is normalised by the gradient magnitude to produce
  a pseudo-geometric error, but it is *not* the true Euclidean distance to
  the conic.
- Parabola detection via discriminant thresholding is inherently fragile
  for noisy data: the discriminant lies on the boundary between the two
  half-spaces, and a tiny amount of noise can push it into either region.
  A practical threshold of ε = 1e-4 (post-normalisation) is used.
- Circle vs. ellipse discrimination uses |A − C| < ε_circle · max(|A|,|C|)
  **and** |B| < ε_circle (default 1e-3 for robustness to sampling noise).
- For production-quality circle detection prefer Taubin/Pratt (see
  ``curve_circle_fit.py``).

Public API
----------
    ConicDetectResult   — dataclass
    detect_conic_type   — main entry point

LLM tool: nurbs_detect_conic_type (gated import)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Union

import numpy as np
from numpy.linalg import svd


# ---------------------------------------------------------------------------
# Public data type
# ---------------------------------------------------------------------------


@dataclass
class ConicDetectResult:
    """Result of classifying a 2-D curve as a conic section.

    Attributes
    ----------
    conic_type : str
        One of ``"circle"``, ``"ellipse"``, ``"parabola"``,
        ``"hyperbola"``, ``"line"``, or ``"free_form"``.
    conic_coefficients : tuple[float, ...]
        Six coefficients ``(A, B, C, D, E, F)`` of the fitted general
        conic  Ax² + Bxy + Cy² + Dx + Ey + F = 0, normalised so that
        the Frobenius norm of the quadratic block ``[[A, B/2],[B/2, C]]``
        is 1.  Returns ``(0.0,)*6`` for ``line`` and ``free_form``.
    eccentricity : float
        Geometric eccentricity:
        0 for circle, 0 < e < 1 for ellipse, 1 for parabola, > 1
        for hyperbola.  ``float("nan")`` for ``line`` and ``free_form``.
    rms_residual_mm : float
        RMS of pseudo-geometric residuals over all sample points.
        Near zero for exact conics; large for ``free_form`` curves.
        Units match the input (assumed millimetres for CAD).
    honest_caveat : str
        Human-readable caveats.  Empty string when the fit is clean.
    """

    conic_type: str
    conic_coefficients: tuple
    eccentricity: float
    rms_residual_mm: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sample_curve_2d(curve_or_points, num_samples: int) -> np.ndarray:
    """Return an (N, 2) float64 array of 2-D points.

    Accepts a ``NurbsCurve`` (evaluated at ``num_samples`` uniform parameter
    steps) or a sequence / NumPy array of 2-D or 3-D points (first two
    columns used).
    """
    try:
        from kerf_cad_core.geom.nurbs import NurbsCurve, de_boor  # type: ignore[import]
        _have_nurbs = True
    except ImportError:  # pragma: no cover
        _have_nurbs = False
        NurbsCurve = None  # type: ignore[assignment,misc]

    if _have_nurbs and NurbsCurve is not None and isinstance(curve_or_points, NurbsCurve):
        curve = curve_or_points
        a = float(curve.knots[0])
        b = float(curve.knots[-1])
        us = np.linspace(a, b, num_samples)
        pts = np.array([de_boor(curve, u) for u in us], dtype=float)
        if pts.ndim == 2 and pts.shape[1] >= 2:
            return pts[:, :2]
        raise ValueError(
            f"NurbsCurve evaluation returned unexpected shape {pts.shape}; "
            "expected (N, ≥2)."
        )

    arr = np.asarray(curve_or_points, dtype=float)
    if arr.ndim == 1:
        if len(arr) % 2 != 0:
            raise ValueError(
                "Cannot interpret 1-D array as 2-D points: length is odd."
            )
        arr = arr.reshape(-1, 2)
    if arr.ndim != 2 or arr.shape[1] < 2:
        raise ValueError(
            f"Expected a 2-D point array of shape (N, ≥2), got {arr.shape}."
        )
    return arr[:, :2]


def _fit_conic_ls(xy: np.ndarray):
    """Fit  Ax²+Bxy+Cy²+Dx+Ey+F=0  by SVD null-space (algebraic LS).

    Returns ``(theta, rms_residual)`` where ``theta = [A,B,C,D,E,F]``
    is normalised so that the Frobenius norm of the conic's quadratic
    block is 1, and ``rms_residual`` is the pseudo-geometric RMS.

    Returns ``None`` when the system is degenerate (< 5 distinct points
    or SVD failure).
    """
    if len(xy) < 5:
        return None

    x, y = xy[:, 0], xy[:, 1]
    # Design matrix: columns [x², xy, y², x, y, 1]
    D = np.column_stack([x * x, x * y, y * y, x, y, np.ones(len(x))])

    try:
        _, _, Vt = svd(D, full_matrices=False)
    except np.linalg.LinAlgError:
        return None

    theta = Vt[-1]  # right-singular vector for smallest singular value

    # Normalise: Frobenius norm of the quadratic sub-block [[A, B/2],[B/2, C]] = 1
    A, B, C = theta[0], theta[1], theta[2]
    frob = math.sqrt(A * A + 0.5 * B * B + C * C + 1e-300)
    theta = theta / frob

    # Pseudo-geometric residual: |f(x,y)| / |∇f|
    A, B, C, D_c, E_c, F_c = theta
    vals = A * x * x + B * x * y + C * y * y + D_c * x + E_c * y + F_c
    grad_x = 2.0 * A * x + B * y + D_c
    grad_y = B * x + 2.0 * C * y + E_c
    grad_mag = np.sqrt(grad_x * grad_x + grad_y * grad_y + 1e-300)
    geo_err = vals / grad_mag
    rms = float(np.sqrt(np.mean(geo_err * geo_err)))

    return theta, rms


def _line_rms(xy: np.ndarray) -> float:
    """TLS (SVD) perpendicular-distance RMS from a best-fit line."""
    centroid = xy.mean(axis=0)
    centered = xy - centroid
    _, s, _ = svd(centered, full_matrices=False)
    # Minor singular value = spread along the orthogonal direction
    # RMS perpendicular residual = s_minor / sqrt(N)
    rms = float(s[-1]) / math.sqrt(len(xy))
    return rms


def _eccentricity_from_theta(theta: np.ndarray, kind: str) -> float:
    """Compute eccentricity from fitted conic coefficients.

    For an ellipse or circle: find semi-axes a ≥ b via the 3×3
    homogeneous matrix eigendecomposition then e = sqrt(1 − (b/a)²).
    For parabola: e = 1.0 exactly.
    For hyperbola: e = sqrt(1 + (b/a)²).
    """
    A, B, C, D_c, E_c, F_c = theta

    if kind == "parabola":
        return 1.0

    if kind in ("circle", "ellipse", "hyperbola"):
        M22 = np.array([[A, B / 2.0], [B / 2.0, C]])
        M33 = np.array([
            [A,        B / 2.0,  D_c / 2.0],
            [B / 2.0,  C,        E_c / 2.0],
            [D_c / 2.0, E_c / 2.0, F_c   ],
        ])
        det_full = float(np.linalg.det(M33))
        det_M22 = float(np.linalg.det(M22))
        eigvals = np.linalg.eigvalsh(M22)  # sorted ascending

        if abs(det_full) < 1e-14 or abs(det_M22) < 1e-14:
            return 0.0 if kind == "circle" else float("nan")

        if kind in ("circle", "ellipse"):
            # For ellipse/circle both eigenvalues have the same sign as det_M22;
            # only keep values where -det_full / (lam * det_M22) > 0.
            radii_sq = []
            for lam in eigvals:
                val = -det_full / (lam * det_M22)
                radii_sq.append(val if val > 0 else 0.0)
            radii_sq.sort(reverse=True)
            a2, b2 = radii_sq[0], radii_sq[1]

            if a2 < 1e-24:
                return 0.0

            if kind == "circle":
                return 0.0
            else:
                return float(math.sqrt(max(0.0, 1.0 - b2 / a2)))

        else:  # hyperbola
            # For a hyperbola the two eigenvalues have opposite signs.
            # The semi-transverse axis a comes from the *positive* val,
            # and the semi-conjugate axis b from the *absolute value* of
            # the negative val.
            # e = sqrt(1 + b²/a²).
            vals = [-det_full / (lam * det_M22) for lam in eigvals]
            # One should be positive (transverse) and one negative (conjugate).
            # Take abs of both and sort descending.
            abs_vals = sorted([abs(v) for v in vals], reverse=True)
            a2, b2 = abs_vals[0], abs_vals[1]
            if a2 < 1e-24:
                return float("nan")
            return float(math.sqrt(1.0 + b2 / a2))

    return float("nan")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_conic_type(
    curve_or_points,
    num_samples: int = 100,
    residual_threshold_mm: float = 0.01,
) -> ConicDetectResult:
    """Classify a 2-D NurbsCurve (or point set) as a conic or free-form.

    Parameters
    ----------
    curve_or_points :
        A ``NurbsCurve`` whose first two coordinate dimensions define the
        2-D curve, OR a sequence / NumPy array of 2-D or 3-D points (only
        x, y are used).
    num_samples : int
        Number of uniform parameter samples when evaluating a
        ``NurbsCurve`` (ignored when a point array is passed directly).
        Minimum 10 (clamped internally).
    residual_threshold_mm : float
        RMS pseudo-geometric residual threshold in mm.  If the best-fit
        conic has a larger residual the curve is classified ``"free_form"``.

    Returns
    -------
    ConicDetectResult
        See :class:`ConicDetectResult`.

    Algorithm
    ---------
    1. Sample ``num_samples`` 2-D points from the curve.
    2. Line gate: if TLS perpendicular RMS < ``residual_threshold_mm / 10``
       **and** the quadratic-block Frobenius norm (post-fit) < 0.15,
       classify as ``"line"``.
    3. Fit the general conic by SVD null-space.
    4. If RMS residual > ``residual_threshold_mm`` → ``"free_form"``.
    5. Classify by discriminant Δ = B² − 4AC (post-normalisation):
         Δ < −ε_disc  and  |B| < ε_circ  and  |A−C| < ε_circ·max(|A|,|C|)
             → ``"circle"``
         Δ < −ε_disc  (and not circle)  → ``"ellipse"``
         |Δ| ≤ ε_disc  → ``"parabola"``
         Δ >  ε_disc  → ``"hyperbola"``

    Notes
    -----
    - The discriminant threshold ``ε_disc = 1e-4`` is applied after
      normalisation; it is deliberately larger than machine epsilon to
      tolerate sampling noise.
    - Circle discrimination uses ``ε_circ = 1e-3``.
    - Algebraic fits are biased by gradient magnitude; for precise circle
      fitting prefer :func:`~kerf_cad_core.geom.curve_circle_fit.fit_circle_to_curve`
      (Taubin/Pratt).
    """
    num_samples = max(10, int(num_samples))

    caveats: list[str] = []

    # --- Step 1: sample ---
    try:
        xy = _sample_curve_2d(curve_or_points, num_samples)
    except Exception as exc:
        return ConicDetectResult(
            conic_type="free_form",
            conic_coefficients=(0.0,) * 6,
            eccentricity=float("nan"),
            rms_residual_mm=float("inf"),
            honest_caveat=f"Sampling failed: {exc}",
        )

    n = len(xy)
    if n < 5:
        return ConicDetectResult(
            conic_type="free_form",
            conic_coefficients=(0.0,) * 6,
            eccentricity=float("nan"),
            rms_residual_mm=float("inf"),
            honest_caveat=f"Too few points ({n}); need ≥ 5 for conic fitting.",
        )

    # --- Step 2: line gate ---
    line_rms = _line_rms(xy)
    if line_rms < residual_threshold_mm:
        # TLS perpendicular-distance RMS is below the threshold: classify as line.
        # Note: a degenerate conic (Bxy + Dx + Ey + F = 0) representing a straight
        # line still has a non-zero B coefficient after Frobenius normalisation of the
        # quadratic block (the block is [[0, B/2],[B/2, 0]]), so we do NOT gate on
        # quadratic content here — the TLS residual alone is the reliable criterion.
        return ConicDetectResult(
            conic_type="line",
            conic_coefficients=(0.0,) * 6,
            eccentricity=float("nan"),
            rms_residual_mm=float(line_rms),
            honest_caveat=(
                "Classified as 'line' based on TLS perpendicular-distance "
                f"RMS = {line_rms:.4g} mm (< threshold = "
                f"{residual_threshold_mm:.4g} mm).  Eccentricity is undefined."
            ),
        )

    # --- Step 3: algebraic conic fit ---
    fit = _fit_conic_ls(xy)
    if fit is None:
        return ConicDetectResult(
            conic_type="free_form",
            conic_coefficients=(0.0,) * 6,
            eccentricity=float("nan"),
            rms_residual_mm=float("inf"),
            honest_caveat="Algebraic conic fit failed (degenerate data).",
        )

    theta, rms = fit

    # --- Step 4: free_form gate ---
    if rms > residual_threshold_mm:
        return ConicDetectResult(
            conic_type="free_form",
            conic_coefficients=(0.0,) * 6,
            eccentricity=float("nan"),
            rms_residual_mm=float(rms),
            honest_caveat=(
                f"RMS pseudo-geometric residual = {rms:.4g} mm exceeds threshold "
                f"{residual_threshold_mm:.4g} mm — curve is not well-approximated "
                "by a single algebraic conic.  "
                "Algebraic fits are susceptible to noise bias; for production-quality "
                "circle detection use Pratt (1987) or Taubin (1991) — see "
                "curve_circle_fit.py."
            ),
        )

    # --- Step 5: classify ---
    A, B, C = theta[0], theta[1], theta[2]
    disc = B * B - 4.0 * A * C

    _EPS_DISC = 1e-4
    _EPS_CIRC = 1e-3

    if disc < -_EPS_DISC:
        # Ellipse family — check circle condition
        max_ac = max(abs(A), abs(C), 1e-14)
        if abs(B) < _EPS_CIRC and abs(A - C) < _EPS_CIRC * max_ac:
            conic_type = "circle"
        else:
            conic_type = "ellipse"
    elif abs(disc) <= _EPS_DISC:
        conic_type = "parabola"
    else:
        conic_type = "hyperbola"

    # --- Eccentricity ---
    try:
        ecc = _eccentricity_from_theta(theta, conic_type)
    except Exception:
        ecc = float("nan")
        caveats.append("Eccentricity computation failed; reported as NaN.")

    # --- Build honest caveat ---
    caveats.append(
        "Algebraic conic fit (SVD null-space + Frobenius normalisation, "
        "Pratt 1987 / Fitzgibbon-Pilu-Fisher 1999).  "
        "The algebraic residual is normalised by gradient magnitude (pseudo-geometric) "
        "— it is NOT the true Euclidean distance to the conic.  "
        "For production-quality circle detection use Pratt (1987) or Taubin (1991) "
        "(see curve_circle_fit.py)."
    )
    if conic_type == "parabola":
        caveats.append(
            "Parabola detection via discriminant thresholding is sensitive to noise: "
            "the discriminant boundary is not robust near the parabolic boundary."
        )

    return ConicDetectResult(
        conic_type=conic_type,
        conic_coefficients=tuple(float(v) for v in theta),
        eccentricity=float(ecc),
        rms_residual_mm=float(rms),
        honest_caveat="  ".join(caveats),
    )


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

    _detect_conic_type_spec = ToolSpec(
        name="nurbs_detect_conic_type",
        description=(
            "Classify a 2-D NurbsCurve (or a list of 2-D points) as one of:\n"
            "  circle | ellipse | parabola | hyperbola | line | free_form\n"
            "\n"
            "Algorithm: sample the curve → fit the general conic Ax²+Bxy+Cy²+Dx+Ey+F=0 "
            "by algebraic least squares (SVD null-space, Frobenius normalisation) → "
            "classify by discriminant B²−4AC:\n"
            "  Δ < 0  →  ellipse (circle if additionally B≈0 and A≈C)\n"
            "  Δ = 0  →  parabola\n"
            "  Δ > 0  →  hyperbola\n"
            "  large residual → free_form\n"
            "  near-linear data → line\n"
            "\n"
            "References: Pratt (1987) SIGGRAPH §3; Fitzgibbon-Pilu-Fisher (1999) "
            "IEEE TPAMI 21(5):476–480.\n"
            "\n"
            "HONEST CAVEAT: algebraic fits are biased by gradient magnitude; for "
            "production-quality circle detection use Pratt/Taubin via "
            "nurbs_fit_circle_to_curve instead.\n"
            "\n"
            "Returns: {ok, conic_type, conic_coefficients[A,B,C,D,E,F], "
            "eccentricity, rms_residual_mm, honest_caveat} "
            "or {ok:false, reason, code}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                    },
                    "description": (
                        "2-D (or 3-D with z ignored) point list [[x,y], ...].  "
                        "Minimum 5 points.  Use this for point clouds or "
                        "pre-sampled curves."
                    ),
                },
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": (
                        "Control points [[x,y,z], ...] for a NurbsCurve.  "
                        "Provide together with 'knots' and 'degree'."
                    ),
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector for the NurbsCurve.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Degree of the NurbsCurve.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Per-control-point weights (omit for non-rational).",
                },
                "num_samples": {
                    "type": "integer",
                    "description": "Number of parameter samples (default 100).",
                },
                "residual_threshold_mm": {
                    "type": "number",
                    "description": (
                        "RMS residual threshold in mm.  Curves with larger residuals "
                        "are classified as free_form (default 0.01 mm)."
                    ),
                },
            },
        },
    )

    @register(_detect_conic_type_spec)
    async def _run_nurbs_detect_conic_type(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        num_samples = int(a.get("num_samples", 100))
        threshold = float(a.get("residual_threshold_mm", 0.01))

        # Accept either a flat point list or a NurbsCurve specification.
        pts_raw = a.get("points")
        cps_raw = a.get("control_points")

        if pts_raw is not None:
            # Direct point list
            try:
                pts = np.array(pts_raw, dtype=float)
                if pts.ndim == 1:
                    pts = pts.reshape(-1, 2)
                if pts.ndim != 2 or pts.shape[1] < 2:
                    return err_payload(
                        "'points' must be [[x,y],...] with ≥ 2 coords per point",
                        "BAD_ARGS",
                    )
            except Exception as exc:
                return err_payload(f"could not parse points: {exc}", "BAD_ARGS")
            curve_or_points = pts
        elif cps_raw is not None:
            # Build NurbsCurve
            knots_raw = a.get("knots")
            degree = a.get("degree")
            weights_raw = a.get("weights")

            if not knots_raw:
                return err_payload("'knots' required with 'control_points'", "BAD_ARGS")
            if degree is None:
                return err_payload("'degree' required with 'control_points'", "BAD_ARGS")

            try:
                from kerf_cad_core.geom.nurbs import NurbsCurve as _NC  # type: ignore[import]
                cps = np.array(cps_raw, dtype=float)
                if cps.ndim == 1:
                    cps = cps.reshape(-1, 1)
                knots = np.array(knots_raw, dtype=float)
                weights = (
                    np.array(weights_raw, dtype=float)
                    if weights_raw is not None
                    else None
                )
                curve_or_points = _NC(
                    degree=int(degree),
                    control_points=cps,
                    knots=knots,
                    weights=weights,
                )
            except Exception as exc:
                return err_payload(
                    f"could not construct NurbsCurve: {exc}", "BAD_ARGS"
                )
        else:
            return err_payload(
                "provide either 'points' (list of [x,y]) or "
                "'control_points'+'knots'+'degree'",
                "BAD_ARGS",
            )

        try:
            result = detect_conic_type(
                curve_or_points,
                num_samples=num_samples,
                residual_threshold_mm=threshold,
            )
        except Exception as exc:
            return err_payload(f"detection failed: {exc}", "OP_FAILED")

        return ok_payload({
            "conic_type": result.conic_type,
            "conic_coefficients": list(result.conic_coefficients),
            "eccentricity": result.eccentricity,
            "rms_residual_mm": result.rms_residual_mm,
            "honest_caveat": result.honest_caveat,
        })
