"""
NURBS-SURFACE-CURVATURE-MAP
===========================
Sample *scalar* curvature fields (Gaussian K, mean H, abs_max |κ₁|, abs_min
|κ₂|) over a NurbsSurface UV grid and export a coloured SVG/PNG heatmap.

Distinct from ``geom/principal_curvature_viz.py``, which exports *separate*
κ₁/κ₂ fields as per-sample objects.  This module collapses the two principal
curvatures into a single user-chosen scalar field and produces a viridis or
RdBu coloured heatmap together with per-cell statistics.

Theory (do Carmo §3.3 / Mortenson §6.5)
----------------------------------------
At a regular point of a smooth surface S(u,v), let

    First fundamental form   E = S_u·S_u, F = S_u·S_v, G = S_v·S_v
    Unit normal              n̂ = (S_u × S_v) / |S_u × S_v|
    Second fundamental form  L = S_uu·n̂, M = S_uv·n̂, N = S_vv·n̂

Then:
    K  = (LN − M²) / (EG − F²)           Gaussian curvature (do Carmo §3.3)
    H  = (EN − 2FM + GL) / (2(EG − F²))  Mean curvature (do Carmo §3.3)
    κ₁ = H + √(H² − K)                   larger principal curvature
    κ₂ = H − √(H² − K)                   smaller principal curvature

Scalar fields exported by this module:
    "gauss"   → K  (signed; K>0 elliptic, K<0 hyperbolic, K=0 parabolic)
    "mean"    → H  (signed; H=0 minimal surface)
    "abs_max" → |κ₁|  (max absolute principal curvature)
    "abs_min" → |κ₂|  (min absolute principal curvature)

Colourmaps
----------
Two palettes are supported (chosen automatically by scalar field):

    viridis — perceptually uniform, dark-to-bright for non-negative scalars
              (abs_max, abs_min, and non-negative Gaussian/mean slices).
    RdBu    — diverging red–white–blue, centred on 0.0, ideal for signed
              Gaussian K or mean H which include both positive and negative values.

The caller may override via ``colormap="viridis"`` or ``colormap="rdbu"`` in the
``CurvatureMapSpec``.

Implementation
--------------
Reuses ``_curvatures_from_partials`` (local copy, not imported) to avoid
circular-import and to allow independent tolerance tuning.  Exact analytic
derivatives are used via ``surface_derivatives`` (Piegl-Tiller Alg. A3.6) for
NurbsSurface; a finite-difference fallback is used for any surface with
``evaluate(u, v)``.

PNG encoding
------------
Pure-Python PNG encoder (no Pillow); same ``_encode_png_rgb`` helper as used in
``principal_curvature_viz.py`` but reproduced locally to keep modules independent.

References
----------
do Carmo, M.P., "Differential Geometry of Curves and Surfaces", §3.3, 1976.
Mortenson, M.E., "Geometric Modeling", §6.5, 1985.
Piegl, L. & Tiller, W., "The NURBS Book", Alg. A3.6, 1997.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Public data-classes
# ---------------------------------------------------------------------------

_VALID_SCALARS = frozenset({"gauss", "mean", "abs_max", "abs_min"})
_VALID_CMAPS   = frozenset({"viridis", "rdbu"})


@dataclass
class CurvatureMapSpec:
    """Specification for a scalar surface curvature heatmap.

    Attributes
    ----------
    nu_samples : int
        Grid resolution in the u parameter direction.  Clamped to [3, 300].
        Default 30.
    nv_samples : int
        Grid resolution in the v parameter direction.  Clamped to [3, 300].
        Default 30.
    scalar_to_map : str
        Which scalar field to colour-map.  One of:
          "gauss"   — Gaussian curvature K = κ₁·κ₂ (signed).
          "mean"    — Mean curvature H = (κ₁+κ₂)/2 (signed).
          "abs_max" — |κ₁| (larger absolute principal curvature).
          "abs_min" — |κ₂| (smaller absolute principal curvature).
        Default "gauss".
    colormap : str
        "viridis" (default for abs_max/abs_min) or "rdbu" (default for
        gauss/mean).  May be overridden by caller.
        Default "" → auto-select based on scalar_to_map.
    export_png : bool
        Whether to encode PNG bytes.  Default False.
    """

    nu_samples:    int = 30
    nv_samples:    int = 30
    scalar_to_map: str = "gauss"
    colormap:      str = ""          # "" → auto
    export_png:    bool = False

    def __post_init__(self) -> None:
        if self.scalar_to_map not in _VALID_SCALARS:
            raise ValueError(
                f"scalar_to_map must be one of {sorted(_VALID_SCALARS)!r}; "
                f"got {self.scalar_to_map!r}"
            )
        if self.colormap and self.colormap.lower() not in _VALID_CMAPS:
            raise ValueError(
                f"colormap must be one of {sorted(_VALID_CMAPS)!r}; "
                f"got {self.colormap!r}"
            )
        self.nu_samples = int(max(3, min(300, self.nu_samples)))
        self.nv_samples = int(max(3, min(300, self.nv_samples)))


@dataclass
class CurvatureMapResult:
    """Result returned by :func:`sample_surface_curvature_map`.

    Attributes
    ----------
    curvature_grid : list[list[float]]
        nu_samples × nv_samples grid of the chosen scalar field values.
        Row-major (u-outer, v-inner).  NaN for degenerate sample points.
    min_value : float
        Minimum finite value in the grid.
    max_value : float
        Maximum finite value in the grid.
    mean_value : float
        Arithmetic mean of all finite values in the grid.
    svg_heatmap : str
        Complete SVG document string with the coloured heatmap.  Contains a
        viridis or RdBu false-colour grid plus legend bar.
    png_bytes : bytes | None
        PNG bytes when ``spec.export_png=True``; ``None`` otherwise.
    honest_caveat : str
        Plain-English accuracy caveat.
    """

    curvature_grid: List[List[float]] = field(default_factory=list)
    min_value:      float = float("nan")
    max_value:      float = float("nan")
    mean_value:     float = float("nan")
    svg_heatmap:    str = ""
    png_bytes:      Optional[bytes] = None
    honest_caveat:  str = (
        "Grid sampling only (uniform in UV parameter space). "
        "High-curvature regions between grid points may be under-sampled. "
        "Use nu_samples=nv_samples≥40 for production confidence. "
        "Degenerate points (poles, |S_u × S_v| < 1e-14) return NaN. "
        "The heatmap is a scalar field only — not the principal-curvature vectors. "
        "Complement to principal_curvature_viz (which exports κ₁/κ₂ per-sample). "
        "Refs: do Carmo §3.3; Mortenson §6.5."
    )


# ---------------------------------------------------------------------------
# Internal constants and tolerances
# ---------------------------------------------------------------------------

_DEGEN_TOL = 1e-14   # |S_u × S_v| threshold
_EGF2_TOL  = 1e-20   # EG − F² threshold


# ---------------------------------------------------------------------------
# Curvature computation  (mirrors principal_curvature_viz; independent copy)
# ---------------------------------------------------------------------------

def _compute_curvatures(
    u: float, v: float,
    Su: np.ndarray, Sv: np.ndarray,
    Suu: np.ndarray, Svv: np.ndarray,
    Suv: np.ndarray,
) -> tuple[float, float, float, float, bool]:
    """Compute (K, H, k1, k2, is_degenerate) from partial derivative vectors.

    Returns NaN tuples when the surface is degenerate at this point.

    Algorithm: shape-operator characteristic equation (do Carmo §3.3):
        K  = (LN − M²) / (EG − F²)
        H  = (EN − 2FM + GL) / (2(EG − F²))
        κ₁ = H + √(H² − K),  κ₂ = H − √(H² − K)
    """
    nan4 = (float("nan"), float("nan"), float("nan"), float("nan"), True)

    cross = np.cross(Su, Sv)
    mag   = float(np.linalg.norm(cross))
    if mag < _DEGEN_TOL:
        return nan4

    n_hat = cross / mag

    E = float(np.dot(Su,  Su))
    F = float(np.dot(Su,  Sv))
    G = float(np.dot(Sv,  Sv))
    EGF2 = E * G - F * F
    if EGF2 < _EGF2_TOL:
        return nan4

    L = float(np.dot(Suu, n_hat))
    M = float(np.dot(Suv, n_hat))
    N = float(np.dot(Svv, n_hat))

    K = (L * N - M * M) / EGF2
    H = (E * N - 2.0 * F * M + G * L) / (2.0 * EGF2)

    disc = max(0.0, H * H - K)
    sq   = math.sqrt(disc)
    k1   = H + sq
    k2   = H - sq

    return float(K), float(H), float(k1), float(k2), False


def _sample_at(surface: object, u: float, v: float) -> tuple[float, float, float, float, bool]:
    """Return (K, H, k1, k2, is_degenerate) at a single UV point.

    Uses exact analytic derivatives for NurbsSurface; finite-difference
    fallback for any surface with ``evaluate(u, v)``.
    """
    # ── Analytic path ─────────────────────────────────────────────────────
    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives
        if isinstance(surface, NurbsSurface):
            SKL  = surface_derivatives(surface, u, v, d=2)
            Su   = np.asarray(SKL[1, 0][:3], dtype=float)
            Sv   = np.asarray(SKL[0, 1][:3], dtype=float)
            Suu  = np.asarray(SKL[2, 0][:3], dtype=float)
            Svv  = np.asarray(SKL[0, 2][:3], dtype=float)
            Suv  = np.asarray(SKL[1, 1][:3], dtype=float)
            return _compute_curvatures(u, v, Su, Sv, Suu, Svv, Suv)
    except ImportError:
        pass

    # ── Finite-difference fallback ────────────────────────────────────────
    if not hasattr(surface, "evaluate"):
        return float("nan"), float("nan"), float("nan"), float("nan"), True

    h = 1e-5
    try:
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
    pu  = ev(u + h, v); pu_ = ev(u - h, v)
    pv  = ev(u, v + h); pv_ = ev(u, v - h)

    Su  = (pu - pu_) / (2.0 * h)
    Sv  = (pv - pv_) / (2.0 * h)
    Suu = (pu - 2.0 * p + pu_) / (h * h)
    Svv = (pv - 2.0 * p + pv_) / (h * h)
    Suv = (ev(u + h, v + h) - ev(u + h, v - h)
           - ev(u - h, v + h) + ev(u - h, v - h)) / (4.0 * h * h)

    return _compute_curvatures(u, v, Su, Sv, Suu, Svv, Suv)


# ---------------------------------------------------------------------------
# UV domain helper
# ---------------------------------------------------------------------------

def _uv_domain(surface: object, nu: int, nv: int):
    """Return (us, vs) linspace arrays covering the surface's parameter domain."""
    u_min, u_max = 0.0, 1.0
    v_min, v_max = 0.0, 1.0
    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface
        if isinstance(surface, NurbsSurface):
            u_min = float(surface.knots_u[0])
            u_max = float(surface.knots_u[-1])
            v_min = float(surface.knots_v[0])
            v_max = float(surface.knots_v[-1])
    except Exception:
        pass
    return np.linspace(u_min, u_max, nu), np.linspace(v_min, v_max, nv)


# ---------------------------------------------------------------------------
# Colourmap LUTs
# ---------------------------------------------------------------------------

# Viridis 5-anchor (matplotlib canonical)
_VIRIDIS_LUT: list[tuple[float, float, float, float]] = [
    (0.000, 0.267004, 0.004874, 0.329415),
    (0.250, 0.190631, 0.407061, 0.537517),
    (0.500, 0.127568, 0.566949, 0.550556),
    (0.750, 0.369214, 0.788021, 0.382851),
    (1.000, 0.993248, 0.906157, 0.143936),
]

# RdBu 5-anchor  (diverging: dark-red → white → dark-blue)
# Anchors sourced from matplotlib's RdBu_r reversed to give:
#   0.0 → deep blue (negative), 0.5 → white (zero), 1.0 → deep red (positive)
_RDBU_LUT: list[tuple[float, float, float, float]] = [
    (0.000, 0.019608, 0.188235, 0.380392),
    (0.250, 0.262745, 0.576471, 0.764706),
    (0.500, 1.000000, 1.000000, 1.000000),
    (0.750, 0.956863, 0.647059, 0.509804),
    (1.000, 0.701961, 0.070588, 0.023529),
]


def _interp_lut(lut: list[tuple[float, float, float, float]], t: float) -> tuple[int, int, int]:
    """Interpolate an LUT at t ∈ [0, 1] → (R, G, B) uint8."""
    t = float(np.clip(t, 0.0, 1.0))
    for k in range(len(lut) - 1):
        t0, r0, g0, b0 = lut[k]
        t1, r1, g1, b1 = lut[k + 1]
        if t <= t1 + 1e-10:
            span = t1 - t0
            a = (t - t0) / span if span > 1e-10 else 0.0
            return (
                int(np.clip(round((r0 + a * (r1 - r0)) * 255), 0, 255)),
                int(np.clip(round((g0 + a * (g1 - g0)) * 255), 0, 255)),
                int(np.clip(round((b0 + a * (b1 - b0)) * 255), 0, 255)),
            )
    _, r, g, b = lut[-1]
    return (
        int(np.clip(round(r * 255), 0, 255)),
        int(np.clip(round(g * 255), 0, 255)),
        int(np.clip(round(b * 255), 0, 255)),
    )


def _viridis_rgb(t: float) -> tuple[int, int, int]:
    return _interp_lut(_VIRIDIS_LUT, t)


def _rdbu_rgb(t: float) -> tuple[int, int, int]:
    return _interp_lut(_RDBU_LUT, t)


# ---------------------------------------------------------------------------
# Normalisation for heatmap
# ---------------------------------------------------------------------------

def _normalise_grid(
    grid: np.ndarray, cmap_name: str
) -> tuple[np.ndarray, float, float]:
    """Return (norm_grid in [0,1], vmin, vmax).

    For RdBu (diverging): centre 0 symmetrically so that 0.5 maps to 0.
    For viridis (sequential): map |finite| range to [0, 1].
    """
    finite_mask = np.isfinite(grid)
    finite_vals = grid[finite_mask]

    if finite_vals.size == 0:
        return np.full_like(grid, 0.5), 0.0, 1.0

    vmin = float(finite_vals.min())
    vmax = float(finite_vals.max())

    if cmap_name == "rdbu":
        # Symmetric about zero
        abs_extreme = max(abs(vmin), abs(vmax), 1e-10)
        vmin_sym = -abs_extreme
        vmax_sym =  abs_extreme
        span = vmax_sym - vmin_sym
        norm = np.where(finite_mask, (grid - vmin_sym) / span, 0.5)
        return np.clip(norm, 0.0, 1.0), float(vmin_sym), float(vmax_sym)
    else:
        # viridis — sequential
        span = vmax - vmin
        if span < 1e-30:
            centre = vmin
            half   = max(1e-6, abs(centre) * 0.5)
            vmin   = centre - half
            vmax   = centre + half
            span   = vmax - vmin
        norm = np.where(finite_mask, (grid - vmin) / span, 0.5)
        return np.clip(norm, 0.0, 1.0), vmin, vmax


# ---------------------------------------------------------------------------
# SVG heatmap builder
# ---------------------------------------------------------------------------

def _build_svg(
    norm: np.ndarray, nu: int, nv: int,
    vmin: float, vmax: float,
    title: str, cmap_name: str,
    cell_size: int = 8,
) -> str:
    """Build a complete SVG heatmap document for the given normalised grid.

    Parameters
    ----------
    norm : ndarray shape (nu, nv)
        Normalised values in [0, 1] (NaN → 0.5).
    nu, nv : int
        Grid dimensions.
    vmin, vmax : float
        Original value range (for legend labels).
    title : str
        Heatmap title text.
    cmap_name : str
        "viridis" or "rdbu".
    cell_size : int
        SVG pixel size per grid cell.
    """
    lut_fn = _rdbu_rgb if cmap_name == "rdbu" else _viridis_rgb
    cs     = max(1, cell_size)
    legend_w = 60
    title_h  = 30
    bottom_h = 16
    svg_w    = nv * cs + legend_w
    svg_h    = nu * cs + title_h + bottom_h

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (f'<svg xmlns="http://www.w3.org/2000/svg"'
         f' width="{svg_w}" height="{svg_h}"'
         f' viewBox="0 0 {svg_w} {svg_h}">'),
        f'  <title>{title}</title>',
        '  <g id="heatmap">',
    ]

    for i in range(nu):
        for j in range(nv):
            t = float(norm[i, j]) if np.isfinite(norm[i, j]) else 0.5
            r, g, b = lut_fn(t)
            x = j * cs
            y = i * cs + title_h
            lines.append(
                f'    <rect x="{x}" y="{y}" width="{cs}" height="{cs}"'
                f' fill="rgb({r},{g},{b})"/>'
            )

    lines.append("  </g>")

    # Title text
    lines.append(
        f'  <text x="{nv * cs // 2}" y="20" text-anchor="middle"'
        f' font-family="monospace" font-size="10" fill="#333">'
        f'{title}</text>'
    )

    # Legend bar (right side, 16 px wide)
    legend_x = nv * cs + 8
    heatmap_h = nu * cs
    n_steps   = max(4, heatmap_h)
    for step in range(n_steps):
        t_leg = 1.0 - step / (n_steps - 1)
        r, g, b = lut_fn(t_leg)
        y_leg   = title_h + int(step * heatmap_h / n_steps)
        h_step  = max(1, int(heatmap_h / n_steps) + 1)
        lines.append(
            f'  <rect x="{legend_x}" y="{y_leg}" width="16" height="{h_step}"'
            f' fill="rgb({r},{g},{b})"/>'
        )

    # Legend labels
    lines.append(
        f'  <text x="{legend_x + 18}" y="{title_h + 10}"'
        f' font-family="monospace" font-size="8" fill="#333">{vmax:.3g}</text>'
    )
    lines.append(
        f'  <text x="{legend_x + 18}" y="{title_h + heatmap_h - 4}"'
        f' font-family="monospace" font-size="8" fill="#333">{vmin:.3g}</text>'
    )

    lines.append("</svg>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure-Python PNG encoder
# ---------------------------------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc    = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return length + chunk_type + data + struct.pack(">I", crc)


def _encode_png_rgb(rgb: np.ndarray) -> bytes:
    """Encode (H, W, 3) uint8 RGB array as PNG bytes (pure Python, no Pillow)."""
    H, W, _ = rgb.shape
    ihdr_data = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    raw = bytearray()
    for row in range(H):
        raw.append(0)           # filter-type None
        raw.extend(rgb[row].tobytes())

    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return _PNG_SIG + ihdr + idat + iend


def _build_png(
    norm: np.ndarray, nu: int, nv: int, cmap_name: str
) -> bytes:
    """Build a PNG heatmap from the normalised (nu × nv) grid."""
    lut_fn = _rdbu_rgb if cmap_name == "rdbu" else _viridis_rgb
    rgb = np.zeros((nu, nv, 3), dtype=np.uint8)
    for i in range(nu):
        for j in range(nv):
            t = float(norm[i, j]) if np.isfinite(norm[i, j]) else 0.5
            r, g, b = lut_fn(t)
            rgb[i, j] = [r, g, b]
    return _encode_png_rgb(rgb)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sample_surface_curvature_map(
    surface: object,
    spec: CurvatureMapSpec,
) -> CurvatureMapResult:
    """Sample a scalar curvature field over a NurbsSurface UV grid.

    Parameters
    ----------
    surface : NurbsSurface | any surface with evaluate(u,v)
        The surface to analyse.  A B-rep Face with a ``.surface`` attribute
        is also accepted (the underlying surface is resolved automatically).
    spec : CurvatureMapSpec
        Sampling and export specification.

    Returns
    -------
    CurvatureMapResult
        Grid of scalar curvature values + SVG heatmap + optional PNG bytes.

    Notes
    -----
    * The scalar is one of: "gauss" (K), "mean" (H), "abs_max" (|κ₁|),
      "abs_min" (|κ₂|) — chosen via ``spec.scalar_to_map``.
    * SVG colourmap: RdBu for signed scalars ("gauss", "mean") unless overridden;
      viridis for non-negative scalars ("abs_max", "abs_min").
    * Degenerate UV points (poles, |S_u×S_v| < 1e-14) emit NaN and receive
      the mid-palette colour in the heatmap.
    * Distinct from ``principal_curvature_viz``, which exports per-sample
      κ₁/κ₂ objects; this module produces a *scalar field* useful for
      zone-colour shading (e.g. K-coloured mould analysis).

    References
    ----------
    do Carmo §3.3; Mortenson §6.5; Piegl & Tiller Alg. A3.6.
    """
    # Resolve underlying surface from a B-rep Face if needed
    srf = surface
    if hasattr(surface, "surface"):
        srf = surface.surface  # type: ignore[union-attr]

    nu = spec.nu_samples
    nv = spec.nv_samples

    us, vs = _uv_domain(srf, nu, nv)

    # Sample curvature grid ─────────────────────────────────────────────────
    grid_raw: list[list[float]] = []
    for i, u in enumerate(us):
        row: list[float] = []
        for j, v in enumerate(vs):
            K, H, k1, k2, degen = _sample_at(srf, float(u), float(v))
            if degen:
                row.append(float("nan"))
            elif spec.scalar_to_map == "gauss":
                row.append(K)
            elif spec.scalar_to_map == "mean":
                row.append(H)
            elif spec.scalar_to_map == "abs_max":
                row.append(abs(k1))
            else:  # abs_min
                row.append(abs(k2))
        grid_raw.append(row)

    grid_np = np.array(grid_raw, dtype=float)

    # Statistics ────────────────────────────────────────────────────────────
    finite_vals = grid_np[np.isfinite(grid_np)]
    if finite_vals.size > 0:
        vmin_stat = float(finite_vals.min())
        vmax_stat = float(finite_vals.max())
        vmean     = float(finite_vals.mean())
    else:
        vmin_stat = vmax_stat = vmean = float("nan")

    # Colormap selection ────────────────────────────────────────────────────
    cmap_name = spec.colormap.lower() if spec.colormap else (
        "rdbu" if spec.scalar_to_map in ("gauss", "mean") else "viridis"
    )

    # Normalise ─────────────────────────────────────────────────────────────
    norm, vmin_norm, vmax_norm = _normalise_grid(grid_np, cmap_name)

    # SVG title ─────────────────────────────────────────────────────────────
    _titles = {
        "gauss":   "Gaussian curvature K",
        "mean":    "Mean curvature H",
        "abs_max": "|κ₁| (max principal curvature)",
        "abs_min": "|κ₂| (min principal curvature)",
    }
    title = f"{_titles[spec.scalar_to_map]} ({nu}×{nv} grid, {cmap_name})"

    # SVG ───────────────────────────────────────────────────────────────────
    svg_str = _build_svg(norm, nu, nv, vmin_norm, vmax_norm, title, cmap_name)

    # PNG (optional) ────────────────────────────────────────────────────────
    png_data: Optional[bytes] = None
    if spec.export_png:
        png_data = _build_png(norm, nu, nv, cmap_name)

    return CurvatureMapResult(
        curvature_grid=grid_raw,
        min_value=vmin_stat,
        max_value=vmax_stat,
        mean_value=vmean,
        svg_heatmap=svg_str,
        png_bytes=png_data,
    )


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
        name="nurbs_sample_surface_curvature_map",
        description=(
            "Sample a scalar curvature field (Gaussian K, mean H, |κ₁|, or |κ₂|) "
            "over a NurbsSurface on a UV grid and export a coloured SVG/PNG heatmap.\n"
            "\n"
            "Complementary to brep_face_principal_curvature_viz (which exports per-sample "
            "κ₁/κ₂ objects); this tool collapses the two principal curvatures into a "
            "single scalar field for zone-colour mould analysis, fairness QC, or "
            "topology inspection.\n"
            "\n"
            "Theory (do Carmo §3.3 / Mortenson §6.5):\n"
            "  K  = (LN − M²) / (EG − F²)           Gaussian curvature\n"
            "  H  = (EN − 2FM + GL) / (2(EG − F²))  Mean curvature\n"
            "  κ₁ = H + √(H²−K),   κ₂ = H − √(H²−K)\n"
            "\n"
            "scalar_to_map choices:\n"
            "  'gauss'   → K (K>0 elliptic, K<0 hyperbolic, K=0 developable)\n"
            "  'mean'    → H (H=0 minimal surface)\n"
            "  'abs_max' → |κ₁| (max absolute principal curvature; severity map)\n"
            "  'abs_min' → |κ₂| (min absolute principal curvature)\n"
            "\n"
            "Colourmaps:\n"
            "  viridis — perceptually uniform dark→bright for non-negative scalars\n"
            "  rdbu    — diverging red–white–blue for signed scalars (default for K/H)\n"
            "\n"
            "Returns:\n"
            "  curvature_grid — nu×nv grid of scalar values (row-major, NaN=degenerate)\n"
            "  min_value/max_value/mean_value — statistics of finite grid values\n"
            "  svg_heatmap   — complete SVG string\n"
            "  png_b64       — base-64 PNG (null when export_png=false)\n"
            "  honest_caveat — accuracy caveat\n"
            "\n"
            "Analytic oracles:\n"
            "  Unit sphere R=1 → K=1 everywhere (uniform map)\n"
            "  Cylinder R=2 → K=0, H=0.25 (uniform zero Gaussian)\n"
            "  Saddle z=xy → K<0 (hyperbolic everywhere)\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  • Uniform UV grid — high-curvature pockets may be missed.\n"
            "  • Scalar export only — not κ₁/κ₂ vectors.\n"
            "  • Degenerate points (poles) emit NaN.\n"
            "  • PNG encodes scalar field at grid resolution only.\n"
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
                    "description": "Control-point grid: list of nu rows, each a list of nv points [x,y,z].",
                    "items": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                },
                "knots_u": {
                    "type": "array", "description": "Knot vector in u.",
                    "items": {"type": "number"},
                },
                "knots_v": {
                    "type": "array", "description": "Knot vector in v.",
                    "items": {"type": "number"},
                },
                "weights": {
                    "type": "array",
                    "description": "Optional nu×nv rational weight grid.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "scalar_to_map": {
                    "type": "string",
                    "enum": ["gauss", "mean", "abs_max", "abs_min"],
                    "description": "Which scalar curvature field to map.",
                    "default": "gauss",
                },
                "nu_samples": {
                    "type": "integer",
                    "description": "Sample count in u direction (default 30, max 300).",
                    "default": 30,
                },
                "nv_samples": {
                    "type": "integer",
                    "description": "Sample count in v direction (default 30, max 300).",
                    "default": 30,
                },
                "colormap": {
                    "type": "string",
                    "enum": ["viridis", "rdbu", ""],
                    "description": "Colourmap: 'viridis', 'rdbu', or '' (auto).",
                    "default": "",
                },
                "export_png": {
                    "type": "boolean",
                    "description": "Whether to generate PNG bytes (default false).",
                    "default": False,
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "knots_u", "knots_v"],
        },
    )

    @register(_spec)
    def _tool_nurbs_sample_surface_curvature_map(
        params: dict, ctx: "ProjectCtx"  # type: ignore[type-arg]
    ) -> dict:
        try:
            import base64
            from kerf_cad_core.geom.nurbs import NurbsSurface

            deg_u  = int(params["degree_u"])
            deg_v  = int(params["degree_v"])
            cps    = np.array(params["control_points"], dtype=float)
            if cps.ndim != 3:
                raise ValueError("control_points must be 3-D (nu × nv × 3)")
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

            spec = CurvatureMapSpec(
                nu_samples=int(params.get("nu_samples", 30)),
                nv_samples=int(params.get("nv_samples", 30)),
                scalar_to_map=str(params.get("scalar_to_map", "gauss")),
                colormap=str(params.get("colormap", "")),
                export_png=bool(params.get("export_png", False)),
            )

            result = sample_surface_curvature_map(srf, spec)

            png_b64: Optional[str] = None
            if result.png_bytes is not None:
                png_b64 = base64.b64encode(result.png_bytes).decode("ascii")

            return ok_payload({
                "curvature_grid":  result.curvature_grid,
                "min_value":       result.min_value,
                "max_value":       result.max_value,
                "mean_value":      result.mean_value,
                "svg_heatmap":     result.svg_heatmap,
                "png_b64":         png_b64,
                "honest_caveat":   result.honest_caveat,
            })

        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
