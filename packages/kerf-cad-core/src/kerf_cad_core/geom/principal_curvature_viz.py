"""
BREP-FACE-PRINCIPAL-CURVATURE-VIZ
==================================
Sample the principal curvatures κ₁, κ₂ (and derived Gaussian K, mean H) over
a B-rep Face on a U×V grid, then export a false-colour SVG/PNG heatmap overlay.

Theory
------
At a regular point of a smooth surface S(u,v), the principal curvatures κ₁ ≥ κ₂
are the eigenvalues of the shape operator (Weingarten map).  Using the first and
second fundamental forms:

    First fundamental form coefficients (Mortenson §6.5 / do Carmo §3.2):
        E = S_u · S_u,   F = S_u · S_v,   G = S_v · S_v

    Second fundamental form coefficients:
        L = S_uu · n̂,   M = S_uv · n̂,   N = S_vv · n̂
        (n̂ = unit normal = (S_u × S_v) / |S_u × S_v|)

    Characteristic equation (do Carmo §3.4 / Mortenson §6.5):
        (EG − F²) κ² − (EN − 2FM + GL) κ + (LN − M²) = 0

    Hence (do Carmo §3.4):
        K  = (LN − M²) / (EG − F²)          Gaussian curvature
        H  = (EN − 2FM + GL) / (2(EG − F²))  Mean curvature
        κ₁ = H + √(H² − K)                   larger principal curvature
        κ₂ = H − √(H² − K)                   smaller principal curvature

Implementation
--------------
Uses ``surface_derivatives`` from ``geom/nurbs.py`` (Piegl-Tiller Alg. A3.6)
which returns exact analytic derivatives for any NurbsSurface (rational-correct).
If the face's underlying surface is not a NurbsSurface, finite-difference
fallback is used (step h = 1e-6 of the parameter domain width).

Grid sampling
-------------
The sampling is uniform in (u, v) parameter space over the surface's knot-domain
(or [0, 1]×[0, 1] for analytic primitives that expose ``evaluate``).  High-
curvature regions between grid points may be missed — this is the grid-sampling
honest caveat.  Use nu=nv≥40 for production confidence.

References
----------
do Carmo, M.P., "Differential Geometry of Curves and Surfaces", §3.4, 1976.
Mortenson, M.E., "Geometric Modeling", §6.5 (fundamental forms), 1985.
Pottmann, H. & Wallner, J., "Computational Line Geometry", §4, 2001.
Piegl, L. & Tiller, W., "The NURBS Book", Algorithms A3.6, A4.4, 1997.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass, field
from typing import List, Optional, Union

import numpy as np

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PrincipalCurvatureSample:
    """Per-vertex principal curvature sample at a UV grid point.

    Attributes
    ----------
    u, v : float
        Parameter values.
    kappa_1 : float
        Larger principal curvature (κ₁ = H + √(H² − K)).
        Positive → surface curves toward the normal; negative → away.
    kappa_2 : float
        Smaller principal curvature (κ₂ = H − √(H² − K)).
    gauss_K : float
        Gaussian curvature K = κ₁ · κ₂ = (LN − M²) / (EG − F²).
        K > 0 → elliptic (sphere-like);  K < 0 → hyperbolic (saddle);
        K = 0 → parabolic (cylinder / developable).
    mean_H : float
        Mean curvature H = (κ₁ + κ₂) / 2.
    is_degenerate : bool
        True when the surface normal vanished at this point (pole or
        near-degenerate tangent plane).  Curvature values are NaN.
    """

    u: float
    v: float
    kappa_1: float
    kappa_2: float
    gauss_K: float
    mean_H: float
    is_degenerate: bool = False


@dataclass
class PrincipalCurvatureVizResult:
    """Full result returned by :func:`sample_principal_curvatures`.

    Attributes
    ----------
    samples : list[PrincipalCurvatureSample]
        Flat list of nu × nv samples in row-major (u-outer, v-inner) order.
    svg_heatmap : str
        SVG source string; κ_max (|κ₁|) false-colour overlay on the UV grid.
        Empty string when ``export_svg=False``.
    png_bytes : bytes | None
        PNG bytes of the heatmap, or ``None`` when ``export_png=False``.
    honest_caveat : str
        Plain-English accuracy caveat.
    """

    samples: List[PrincipalCurvatureSample] = field(default_factory=list)
    svg_heatmap: str = ""
    png_bytes: Optional[bytes] = None
    honest_caveat: str = (
        "Grid sampling only (uniform in UV parameter space). "
        "High-curvature regions between grid points may be under-sampled. "
        "Use nu=nv≥40 for production confidence. "
        "Degenerate points (poles, |S_u × S_v| < 1e-14) are skipped (NaN). "
        "The heatmap maps |κ₁| (max absolute principal curvature) — not κ₁ signed."
    )


# ---------------------------------------------------------------------------
# Core sampling
# ---------------------------------------------------------------------------

_DEGEN_TOL = 1e-14   # |S_u × S_v| below this → degenerate
_EGF2_TOL  = 1e-20   # EG − F² below this → degenerate


def _sample_one(surface: object, u: float, v: float) -> PrincipalCurvatureSample:
    """Compute principal curvatures at a single (u, v) point.

    Handles both NurbsSurface (exact analytic, via ``surface_derivatives``)
    and any surface with an ``evaluate(u, v) → array-like`` method
    (finite-difference fallback).
    """
    # ── Try analytic path (NurbsSurface) ─────────────────────────────────────
    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives
        if isinstance(surface, NurbsSurface):
            SKL = surface_derivatives(surface, u, v, d=2)
            Su  = np.asarray(SKL[1, 0][:3], dtype=float)
            Sv  = np.asarray(SKL[0, 1][:3], dtype=float)
            Suu = np.asarray(SKL[2, 0][:3], dtype=float)
            Svv = np.asarray(SKL[0, 2][:3], dtype=float)
            Suv = np.asarray(SKL[1, 1][:3], dtype=float)
            return _curvatures_from_partials(u, v, Su, Sv, Suu, Svv, Suv)
    except ImportError:
        pass

    # ── Finite-difference fallback ────────────────────────────────────────────
    if hasattr(surface, "evaluate"):
        return _sample_fd(surface, u, v)

    # Cannot compute
    return PrincipalCurvatureSample(
        u=u, v=v,
        kappa_1=float("nan"), kappa_2=float("nan"),
        gauss_K=float("nan"), mean_H=float("nan"),
        is_degenerate=True,
    )


def _curvatures_from_partials(
    u: float, v: float,
    Su: np.ndarray, Sv: np.ndarray,
    Suu: np.ndarray, Svv: np.ndarray,
    Suv: np.ndarray,
) -> PrincipalCurvatureSample:
    """Compute κ₁, κ₂, K, H from first/second partial derivative vectors.

    Implements the shape-operator eigenvalue formula (do Carmo §3.4,
    Mortenson §6.5):

        (EG − F²) κ² − (EN − 2FM + GL) κ + (LN − M²) = 0

    Returns a degenerate sample when |S_u × S_v| < _DEGEN_TOL or
    EG − F² < _EGF2_TOL.
    """
    _nan = float("nan")
    # Unit surface normal
    cross = np.cross(Su, Sv)
    mag = float(np.linalg.norm(cross))
    if mag < _DEGEN_TOL:
        return PrincipalCurvatureSample(
            u=u, v=v, kappa_1=_nan, kappa_2=_nan,
            gauss_K=_nan, mean_H=_nan, is_degenerate=True,
        )
    n_hat = cross / mag

    # First fundamental form
    E = float(np.dot(Su, Su))
    F = float(np.dot(Su, Sv))
    G = float(np.dot(Sv, Sv))
    EGF2 = E * G - F * F
    if EGF2 < _EGF2_TOL:
        return PrincipalCurvatureSample(
            u=u, v=v, kappa_1=_nan, kappa_2=_nan,
            gauss_K=_nan, mean_H=_nan, is_degenerate=True,
        )

    # Second fundamental form (L, M, N in do Carmo notation)
    L = float(np.dot(Suu, n_hat))
    M = float(np.dot(Suv, n_hat))
    N = float(np.dot(Svv, n_hat))

    # Gaussian and mean curvature (do Carmo §3.4)
    K = (L * N - M * M) / EGF2
    H = (E * N - 2.0 * F * M + G * L) / (2.0 * EGF2)

    # Principal curvatures κ₁ = H + √(H²−K), κ₂ = H − √(H²−K)
    disc = max(0.0, H * H - K)
    sq   = math.sqrt(disc)
    k1   = H + sq   # larger
    k2   = H - sq   # smaller

    return PrincipalCurvatureSample(
        u=float(u), v=float(v),
        kappa_1=float(k1), kappa_2=float(k2),
        gauss_K=float(K), mean_H=float(H),
        is_degenerate=False,
    )


def _sample_fd(surface: object, u: float, v: float) -> PrincipalCurvatureSample:
    """Finite-difference curvature at (u, v) for non-NURBS surfaces.

    Uses a central-difference stencil with step h.  The step is chosen
    relative to the parameter domain if discoverable, else defaults to 1e-5.

    Only uses ``surface.evaluate(u, v)``.
    """
    h = 1e-5
    # Try to infer domain for a better step size
    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface  # type: ignore[import]
        if hasattr(surface, "knots_u"):
            ku = np.asarray(surface.knots_u)
            kv = np.asarray(surface.knots_v)
            span_u = float(ku[-1]) - float(ku[0])
            span_v = float(kv[-1]) - float(kv[0])
            h = min(span_u, span_v) * 1e-5
    except Exception:
        pass
    h = max(h, 1e-8)

    def ev(uu: float, vv: float) -> np.ndarray:
        return np.asarray(surface.evaluate(uu, vv), dtype=float)[:3]

    p   = ev(u, v)
    pu  = ev(u + h, v)
    pu_ = ev(u - h, v)
    pv  = ev(u, v + h)
    pv_ = ev(u, v - h)
    puu = ev(u + h, v) - 2.0 * p + ev(u - h, v)
    pvv = ev(u, v + h) - 2.0 * p + ev(u, v - h)
    puv = (ev(u + h, v + h) - ev(u + h, v - h) -
           ev(u - h, v + h) + ev(u - h, v - h)) / (4.0 * h * h)

    Su  = (pu - pu_) / (2.0 * h)
    Sv  = (pv - pv_) / (2.0 * h)
    Suu = puu / (h * h)
    Svv = pvv / (h * h)
    Suv = puv

    return _curvatures_from_partials(u, v, Su, Sv, Suu, Svv, Suv)


def _get_uv_domain(surface: object, nu: int, nv: int):
    """Return linspace arrays (us, vs) covering the surface's parameter domain."""
    u_min, u_max = 0.0, 1.0
    v_min, v_max = 0.0, 1.0

    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface  # type: ignore[import]
        if isinstance(surface, NurbsSurface):
            u_min = float(surface.knots_u[0])
            u_max = float(surface.knots_u[-1])
            v_min = float(surface.knots_v[0])
            v_max = float(surface.knots_v[-1])
    except Exception:
        pass

    us = np.linspace(u_min, u_max, nu)
    vs = np.linspace(v_min, v_max, nv)
    return us, vs


def sample_principal_curvatures(
    face: object,
    nu: int = 20,
    nv: int = 20,
    export_svg: bool = True,
    export_png: bool = False,
) -> PrincipalCurvatureVizResult:
    """Sample principal curvatures over a B-rep Face on a U×V grid.

    Parameters
    ----------
    face : Face
        A B-rep Face object (must have a ``.surface`` attribute that is either
        a ``NurbsSurface`` or any object with an ``evaluate(u, v)`` method).
    nu, nv : int
        Grid resolution.  Clamped to [3, 200].  Default 20×20 gives
        400 samples, appropriate for real-time preview; use 40×40 or higher
        for production analysis.
    export_svg : bool
        When True (default), generate an SVG heatmap of |κ_max| = |κ₁|
        in the result.  Can be disabled for headless/batch use.
    export_png : bool
        When True, generate PNG bytes (pure-Python encoder, no Pillow).
        Default False (off) to save memory.

    Returns
    -------
    PrincipalCurvatureVizResult
        Samples list + optional SVG/PNG heatmap.

    Notes
    -----
    * The heatmap colour maps |κ₁| (max absolute principal curvature) using
      the viridis palette — dark purple = low curvature, yellow = high.
    * Degenerate sample points (poles, |S_u × S_v| < 1e-14) are skipped;
      their curvature fields carry ``NaN`` and they receive the mid-palette
      colour in the heatmap.
    * Grid sampling is uniform in UV *parameter* space, not arc-length space.
      For surfaces with strongly non-uniform parameterisation (e.g. highly
      elongated patches), the physical sample density will be uneven.

    References
    ----------
    do Carmo §3.4; Mortenson §6.5; Pottmann-Wallner §4.
    """
    nu  = int(max(3, min(200, nu)))
    nv  = int(max(3, min(200, nv)))

    # Resolve the underlying surface from the face
    surface = face
    if hasattr(face, "surface"):
        surface = face.surface  # type: ignore[union-attr]

    us, vs = _get_uv_domain(surface, nu, nv)

    samples: List[PrincipalCurvatureSample] = []
    for u in us:
        for v in vs:
            s = _sample_one(surface, float(u), float(v))
            samples.append(s)

    # Build 2-D grids for visualisation (nu rows, nv cols)
    k1_grid = np.array(
        [[samples[i * nv + j].kappa_1 for j in range(nv)] for i in range(nu)],
        dtype=float,
    )

    svg_str  = ""
    png_data: Optional[bytes] = None

    if export_svg:
        svg_str = _build_svg_heatmap(k1_grid, nu, nv)
    if export_png:
        png_data = _build_png_heatmap(k1_grid, nu, nv)

    return PrincipalCurvatureVizResult(
        samples=samples,
        svg_heatmap=svg_str,
        png_bytes=png_data,
    )


# ---------------------------------------------------------------------------
# Visualisation helpers
# ---------------------------------------------------------------------------

# Viridis 5-anchor LUT (matplotlib canonical)
_VIRIDIS: list[tuple[float, float, float, float]] = [
    (0.000, 0.267004, 0.004874, 0.329415),
    (0.250, 0.190631, 0.407061, 0.537517),
    (0.500, 0.127568, 0.566949, 0.550556),
    (0.750, 0.369214, 0.788021, 0.382851),
    (1.000, 0.993248, 0.906157, 0.143936),
]


def _viridis_rgb(t: float) -> tuple[int, int, int]:
    """Map t ∈ [0, 1] → (R, G, B) uint8 via viridis palette."""
    t = float(np.clip(t, 0.0, 1.0))
    for k in range(len(_VIRIDIS) - 1):
        t0, r0, g0, b0 = _VIRIDIS[k]
        t1, r1, g1, b1 = _VIRIDIS[k + 1]
        if t <= t1 + 1e-10:
            span = t1 - t0
            a = (t - t0) / span if span > 1e-10 else 0.0
            return (
                int(np.clip(round((r0 + a * (r1 - r0)) * 255), 0, 255)),
                int(np.clip(round((g0 + a * (g1 - g0)) * 255), 0, 255)),
                int(np.clip(round((b0 + a * (b1 - b0)) * 255), 0, 255)),
            )
    _, r, g, b = _VIRIDIS[-1]
    return (
        int(np.clip(round(r * 255), 0, 255)),
        int(np.clip(round(g * 255), 0, 255)),
        int(np.clip(round(b * 255), 0, 255)),
    )


def _normalise_field(field: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Return (norm_field in [0,1], vmin, vmax) using |field| for heatmap."""
    abs_field = np.abs(field)
    finite = abs_field[np.isfinite(abs_field)]
    if finite.size == 0:
        return np.full_like(abs_field, 0.5), 0.0, 1.0
    vmin = float(finite.min())
    vmax = float(finite.max())
    span = vmax - vmin
    if span < 1e-30:
        # Constant curvature (e.g. sphere) — use value range ±10% of value
        centre = vmin
        half   = max(1e-6, abs(centre) * 0.5)
        vmin   = centre - half
        vmax   = centre + half
        span   = vmax - vmin
    norm = np.where(np.isfinite(abs_field), (abs_field - vmin) / span, 0.5)
    norm = np.clip(norm, 0.0, 1.0)
    return norm, vmin, vmax


def _build_svg_heatmap(k1_grid: np.ndarray, nu: int, nv: int,
                        cell_size: int = 8) -> str:
    """Build an SVG false-colour heatmap of |κ₁| over a nu×nv grid.

    Each sample cell is rendered as a coloured ``<rect>`` element.
    The colour maps |κ₁| via the viridis palette.  A legend bar with
    the min/max annotation is appended on the right side.

    Parameters
    ----------
    k1_grid : ndarray shape (nu, nv)
        κ₁ values (NaN for degenerate points).
    nu, nv : int
        Grid dimensions.
    cell_size : int
        SVG pixel size per cell (default 8).

    Returns
    -------
    str — complete SVG document.
    """
    norm, vmin, vmax = _normalise_field(k1_grid)
    cs = max(1, cell_size)
    svg_w = nv * cs + 60   # extra 60 px for legend
    svg_h = nu * cs + 40   # extra 40 px for title + bottom margin

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (f'<svg xmlns="http://www.w3.org/2000/svg"'
         f' width="{svg_w}" height="{svg_h}"'
         f' viewBox="0 0 {svg_w} {svg_h}">'),
        (f'  <title>B-rep Face |κ₁| heatmap'
         f' ({nu}×{nv} grid, viridis)</title>'),
        '  <g id="heatmap">',
    ]

    for i in range(nu):
        for j in range(nv):
            t  = float(norm[i, j])
            r, g, b = _viridis_rgb(t)
            x  = j * cs
            y  = i * cs + 30   # 30 px title bar
            lines.append(
                f'    <rect x="{x}" y="{y}" width="{cs}" height="{cs}"'
                f' fill="rgb({r},{g},{b})"/>'
            )

    lines.append("  </g>")

    # Title
    lines.append(
        f'  <text x="{nv * cs // 2}" y="20" '
        f'text-anchor="middle" font-family="monospace" font-size="11" '
        f'fill="#333">|κ₁| principal curvature heatmap</text>'
    )

    # Legend bar (20 px wide, right of heatmap)
    legend_x = nv * cs + 8
    legend_h = max(4, nu * cs)
    n_steps  = max(4, nu * cs)
    for step in range(n_steps):
        t_leg = 1.0 - step / (n_steps - 1)   # top = high curvature
        r, g, b = _viridis_rgb(t_leg)
        y_leg   = 30 + int(step * nu * cs / n_steps)
        h_step  = max(1, int(nu * cs / n_steps) + 1)
        lines.append(
            f'  <rect x="{legend_x}" y="{y_leg}" width="16" height="{h_step}"'
            f' fill="rgb({r},{g},{b})"/>'
        )

    # Legend labels
    lines.append(
        f'  <text x="{legend_x + 18}" y="35" font-family="monospace"'
        f' font-size="9" fill="#333">{vmax:.3g}</text>'
    )
    lines.append(
        f'  <text x="{legend_x + 18}" y="{30 + legend_h - 4}"'
        f' font-family="monospace" font-size="9" fill="#333">{vmin:.3g}</text>'
    )

    lines.append("</svg>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure-Python PNG encoder (no Pillow; PNG 1.2 spec W3C 2003)
# ---------------------------------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc    = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return length + chunk_type + data + struct.pack(">I", crc)


def _encode_png_rgb(rgb: np.ndarray) -> bytes:
    """Encode (H, W, 3) uint8 RGB array as PNG bytes (pure Python)."""
    H, W, _ = rgb.shape
    ihdr_data = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    raw = bytearray()
    for row in range(H):
        raw.append(0)   # filter type None
        raw.extend(rgb[row].tobytes())

    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return _PNG_SIG + ihdr + idat + iend


def _build_png_heatmap(k1_grid: np.ndarray, nu: int, nv: int) -> bytes:
    """Build a PNG heatmap of |κ₁|.  Returns PNG bytes."""
    norm, _, _ = _normalise_field(k1_grid)
    # Build (nu × nv × 3) uint8 RGB image
    rgb = np.zeros((nu, nv, 3), dtype=np.uint8)
    for i in range(nu):
        for j in range(nv):
            r, g, b = _viridis_rgb(float(norm[i, j]))
            rgb[i, j] = [r, g, b]
    return _encode_png_rgb(rgb)


# ---------------------------------------------------------------------------
# LLM tool registration (gated import)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _spec = ToolSpec(
        name="brep_face_principal_curvature_viz",
        description=(
            "Sample the principal curvatures κ₁, κ₂ (and Gaussian K, mean H) "
            "over a B-rep Face on a U×V parameter grid, and produce a "
            "false-colour SVG heatmap of |κ_max| = |κ₁|.\n"
            "\n"
            "Theory (do Carmo §3.4 / Mortenson §6.5 / Pottmann-Wallner §4):\n"
            "  κ₁ = H + √(H²−K),   κ₂ = H − √(H²−K)\n"
            "  K  = (LN − M²) / (EG − F²)    Gaussian curvature\n"
            "  H  = (EN − 2FM + GL) / (2(EG−F²))  Mean curvature\n"
            "where E, F, G are first-fundamental-form coefficients and\n"
            "L, M, N are second-fundamental-form coefficients (shape operator).\n"
            "\n"
            "Returns:\n"
            "  samples       — list of {u,v,kappa_1,kappa_2,gauss_K,mean_H} dicts\n"
            "  svg_heatmap   — SVG string (viridis false-colour of |κ₁|)\n"
            "  png_b64       — base-64 PNG (null when export_png=false)\n"
            "  k1_min/max    — finite range of κ₁ over the grid\n"
            "  k2_min/max    — finite range of κ₂ over the grid\n"
            "  K_min/max     — finite range of Gaussian K\n"
            "  H_min/max     — finite range of mean H\n"
            "  n_degenerate  — count of degenerate (pole/singular) samples\n"
            "  honest_caveat — accuracy caveat\n"
            "\n"
            "Analytic oracles:\n"
            "  • Unit sphere R=1 → κ₁ = κ₂ = 1 everywhere, K=1, H=1.\n"
            "  • Cylinder R=2 → κ₁ = 1/R = 0.5, κ₂ = 0.\n"
            "  • Plane → κ₁ = κ₂ = 0, K = 0, H = 0.\n"
            "  • Torus (R, r): outer rim κ₁ ≈ 2/(R+r), inner rim κ₁ ≈ 2/(R−r).\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  • Uniform UV-grid sampling — high-curvature pockets between sample "
            "points may be missed (lower bound on max|κ|).\n"
            "  • Degenerate points (poles) emit NaN curvatures.\n"
            "  • PNG export encodes |κ₁| at the same grid resolution as samples.\n"
            "\n"
            "Never raises — returns {ok:false, reason} for invalid inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {
                    "type": "integer",
                    "description": "B-spline degree in u direction.",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "B-spline degree in v direction.",
                },
                "control_points": {
                    "type": "array",
                    "description": (
                        "Control-point grid: list of nu rows, each a list of nv "
                        "points [x, y, z]."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
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
                    "description": "Optional nu×nv rational weight grid.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "nu": {
                    "type": "integer",
                    "description": "Sample count in u direction (default 20, max 200).",
                    "default": 20,
                },
                "nv": {
                    "type": "integer",
                    "description": "Sample count in v direction (default 20, max 200).",
                    "default": 20,
                },
                "export_svg": {
                    "type": "boolean",
                    "description": "Whether to generate SVG heatmap (default true).",
                    "default": True,
                },
                "export_png": {
                    "type": "boolean",
                    "description": "Whether to generate PNG bytes (default false).",
                    "default": False,
                },
            },
            "required": [
                "degree_u", "degree_v", "control_points", "knots_u", "knots_v"
            ],
        },
    )

    @register(_spec)
    def _tool_brep_face_principal_curvature_viz(
        params: dict, ctx: "ProjectCtx"  # type: ignore[type-arg]
    ) -> dict:
        try:
            import base64
            from kerf_cad_core.geom.nurbs import NurbsSurface

            deg_u = int(params["degree_u"])
            deg_v = int(params["degree_v"])
            cps   = np.array(params["control_points"], dtype=float)
            if cps.ndim != 3:
                raise ValueError("control_points must be 3-D (nu x nv x 3)")
            knots_u = np.array(params["knots_u"], dtype=float)
            knots_v = np.array(params["knots_v"], dtype=float)
            weights_raw = params.get("weights")
            weights = (np.array(weights_raw, dtype=float)
                       if weights_raw is not None else None)

            srf = NurbsSurface(
                degree_u=deg_u, degree_v=deg_v,
                control_points=cps,
                knots_u=knots_u, knots_v=knots_v,
                weights=weights,
            )

            nu_p  = int(params.get("nu", 20))
            nv_p  = int(params.get("nv", 20))
            do_svg = bool(params.get("export_svg", True))
            do_png = bool(params.get("export_png", False))

            # Pass the NurbsSurface directly (sample_principal_curvatures
            # handles objects with or without .surface attribute).
            result = sample_principal_curvatures(
                srf,
                nu=nu_p, nv=nv_p,
                export_svg=do_svg,
                export_png=do_png,
            )

            # Aggregate statistics
            k1_vals = [s.kappa_1 for s in result.samples if not s.is_degenerate]
            k2_vals = [s.kappa_2 for s in result.samples if not s.is_degenerate]
            K_vals  = [s.gauss_K for s in result.samples if not s.is_degenerate]
            H_vals  = [s.mean_H  for s in result.samples if not s.is_degenerate]
            n_degen = sum(1 for s in result.samples if s.is_degenerate)

            def _safe_range(vals: list) -> tuple[float, float]:
                finite = [v for v in vals if math.isfinite(v)]
                if not finite:
                    return float("nan"), float("nan")
                return min(finite), max(finite)

            k1_min, k1_max = _safe_range(k1_vals)
            k2_min, k2_max = _safe_range(k2_vals)
            K_min,  K_max  = _safe_range(K_vals)
            H_min,  H_max  = _safe_range(H_vals)

            png_b64: Optional[str] = None
            if result.png_bytes is not None:
                png_b64 = base64.b64encode(result.png_bytes).decode("ascii")

            # Compact sample list (omit degenerate details to keep payload small)
            compact_samples = [
                {
                    "u": s.u, "v": s.v,
                    "kappa_1": s.kappa_1, "kappa_2": s.kappa_2,
                    "gauss_K": s.gauss_K, "mean_H": s.mean_H,
                    "is_degenerate": s.is_degenerate,
                }
                for s in result.samples
            ]

            return ok_payload({
                "samples":      compact_samples,
                "svg_heatmap":  result.svg_heatmap,
                "png_b64":      png_b64,
                "k1_min":       k1_min,
                "k1_max":       k1_max,
                "k2_min":       k2_min,
                "k2_max":       k2_max,
                "K_min":        K_min,
                "K_max":        K_max,
                "H_min":        H_min,
                "H_max":        H_max,
                "n_degenerate": n_degen,
                "honest_caveat": result.honest_caveat,
            })

        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
