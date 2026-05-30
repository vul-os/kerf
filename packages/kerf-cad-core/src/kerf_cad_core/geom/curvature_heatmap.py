"""
curvature_heatmap.py
====================
NURBS curvature heatmap PNG/SVG export (GK-P / Wave 4DD extension).

Provides
--------
render_curvature_heatmap(surface, kind, n_samples, palette, range)
    Sample Gaussian / mean / max-principal curvature on an n_samples×n_samples
    UV grid and encode as an (H, W, 3) uint8 RGB array.

export_heatmap_png(surface, path, kind, n_samples, palette)
    Write the heatmap to a PNG file using a pure-Python PNG encoder
    (no Pillow dependency — implements IHDR + IDAT + IEND per PNG 1.2 spec).

export_heatmap_svg(surface, path, kind, n_samples, palette)
    Write the heatmap as an SVG where each UV sample becomes a coloured rect.

generate_curvature_legend(palette, n_steps)
    Return an (n_steps, 1, 3) uint8 legend bar for the given palette.

Palettes
--------
'viridis'           — perceptually-uniform sequential (dark purple → yellow)
'diverging_blue_red' — blue–white–red for signed quantities (K < 0, K > 0)

References
----------
Matplotlib viridis LUT is approximated here as a 5-key-frame polynomial
interpolation through the canonical anchor colours from matplotlib's colormap
specification (matplotlib.org/stable/gallery/color/colormap_reference.html).

PNG 1.2 spec: W3C Portable Network Graphics Specification, 2nd edition, 2003.
  https://www.w3.org/TR/PNG/
  Chunk layout: 8-byte signature, IHDR, IDAT (zlib-compressed), IEND.

No third-party dependencies beyond numpy (already a kerf-cad-core requirement)
and the Python standard library (struct, zlib, pathlib, xml.etree.ElementTree).
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Union

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_analysis import curvature_heatmap as _curvature_heatmap

# ---------------------------------------------------------------------------
# Palette definitions
# ---------------------------------------------------------------------------

# Viridis: 5 anchor points (t in [0, 1]) → (R, G, B) in [0, 1]
# Derived from the matplotlib viridis LUT anchor colours.
_VIRIDIS_ANCHORS: list[tuple[float, float, float, float]] = [
    (0.000, 0.267004, 0.004874, 0.329415),
    (0.250, 0.190631, 0.407061, 0.537517),
    (0.500, 0.127568, 0.566949, 0.550556),
    (0.750, 0.369214, 0.788021, 0.382851),
    (1.000, 0.993248, 0.906157, 0.143936),
]

# Diverging blue–white–red: blue (negative) → white (zero) → red (positive)
_DIVERGING_BWR_ANCHORS: list[tuple[float, float, float, float]] = [
    (0.000, 0.017, 0.173, 0.633),
    (0.250, 0.450, 0.620, 0.960),
    (0.500, 1.000, 1.000, 1.000),
    (0.750, 0.960, 0.480, 0.380),
    (1.000, 0.613, 0.008, 0.007),
]


def _interp_palette(anchors: list[tuple[float, float, float, float]], t: float) -> tuple[int, int, int]:
    """Linear interpolation between anchor points; t in [0, 1] → (R, G, B) uint8."""
    t = float(np.clip(t, 0.0, 1.0))
    # Find surrounding anchors
    for k in range(len(anchors) - 1):
        t0, r0, g0, b0 = anchors[k]
        t1, r1, g1, b1 = anchors[k + 1]
        if t <= t1 + 1e-10:
            span = t1 - t0
            alpha = (t - t0) / span if span > 1e-10 else 0.0
            r = r0 + alpha * (r1 - r0)
            g = g0 + alpha * (g1 - g0)
            b = b0 + alpha * (b1 - b0)
            return (
                int(np.clip(round(r * 255), 0, 255)),
                int(np.clip(round(g * 255), 0, 255)),
                int(np.clip(round(b * 255), 0, 255)),
            )
    # t == 1.0 exactly
    _, r, g, b = anchors[-1]
    return (
        int(np.clip(round(r * 255), 0, 255)),
        int(np.clip(round(g * 255), 0, 255)),
        int(np.clip(round(b * 255), 0, 255)),
    )


def _build_lut(palette: str, n: int = 256) -> np.ndarray:
    """Build a (n, 3) uint8 LUT for the given palette name."""
    if palette == "viridis":
        anchors = _VIRIDIS_ANCHORS
    elif palette in ("diverging_blue_red", "bwr"):
        anchors = _DIVERGING_BWR_ANCHORS
    else:
        raise ValueError(f"Unknown palette {palette!r}. Choose 'viridis' or 'diverging_blue_red'.")

    lut = np.empty((n, 3), dtype=np.uint8)
    for i in range(n):
        t = i / (n - 1)
        r, g, b = _interp_palette(anchors, t)
        lut[i] = [r, g, b]
    return lut


def _scalar_field_to_rgb(
    field: np.ndarray,
    palette: str,
    vmin: float,
    vmax: float,
) -> np.ndarray:
    """Map a 2-D scalar field to (H, W, 3) uint8 via LUT.

    NaN / Inf values are mapped to the LUT mid-point (index 127).
    """
    lut = _build_lut(palette, 256)
    H, W = field.shape

    # Normalise to [0, 1]
    span = vmax - vmin
    if span < 1e-30:
        # Constant field → all mid-palette
        norm = np.full_like(field, 0.5)
    else:
        norm = (field - vmin) / span

    # Replace non-finite with 0.5 (mid palette)
    finite_mask = np.isfinite(norm)
    norm = np.where(finite_mask, norm, 0.5)
    norm = np.clip(norm, 0.0, 1.0)

    indices = (norm * 255).astype(np.int32)
    indices = np.clip(indices, 0, 255)

    rgb = lut[indices]   # (H, W, 3)
    return rgb.astype(np.uint8)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_curvature_heatmap(
    surface: NurbsSurface,
    kind: str = "gaussian",
    n_samples: int = 256,
    palette: str = "viridis",
    value_range: Union[str, tuple[float, float]] = "auto",
) -> np.ndarray:
    """Sample curvature on a UV grid and encode as (H, W, 3) uint8 RGB.

    Parameters
    ----------
    surface : NurbsSurface
        Surface to analyse.
    kind : str
        Which curvature to visualise.  One of:
        ``'gaussian'`` (K = eg − f²) / (EG − F²)),
        ``'mean'``     (H = (eG − 2fF + gE) / (2(EG − F²))),
        ``'max_principal'``  (κ₁ = H + √(H² − K)).
    n_samples : int
        Grid resolution (clamped to [4, 512]).  Produces an
        n_samples × n_samples pixel image.
    palette : str
        ``'viridis'`` or ``'diverging_blue_red'``.
    value_range : ``'auto'`` or (vmin, vmax) tuple
        Range mapped to the full palette.  ``'auto'`` uses the finite
        min / max of the sampled field.

    Returns
    -------
    numpy.ndarray  shape (n_samples, n_samples, 3), dtype uint8
        RGB image ready for PNG/SVG export.

    Raises
    ------
    ValueError
        On unknown ``kind`` or ``palette``.
    RuntimeError
        If curvature sampling fails (propagates the surface_analysis reason).
    """
    n = int(np.clip(n_samples, 4, 512))

    result = _curvature_heatmap(surface, nu=n, nv=n)
    if not result["ok"]:
        raise RuntimeError(f"curvature_heatmap failed: {result['reason']}")

    if kind == "gaussian":
        field: np.ndarray = result["gaussian"]
    elif kind == "mean":
        field = result["mean"]
    elif kind == "max_principal":
        field = result["principal_k1"]
    else:
        raise ValueError(f"Unknown kind {kind!r}. Choose 'gaussian', 'mean', or 'max_principal'.")

    if value_range == "auto":
        finite = field[np.isfinite(field)]
        if finite.size == 0:
            vmin, vmax = -1.0, 1.0
        elif (float(finite.max()) - float(finite.min())) < 1e-30:
            # Constant field (e.g. flat plane K=0): centre palette on the value
            centre = float(finite[0])
            half = max(1e-6, abs(centre))
            vmin, vmax = centre - half, centre + half
        else:
            vmin, vmax = float(finite.min()), float(finite.max())
    else:
        vmin, vmax = float(value_range[0]), float(value_range[1])

    return _scalar_field_to_rgb(field, palette, vmin, vmax)


def generate_curvature_legend(palette: str = "viridis", n_steps: int = 256) -> np.ndarray:
    """Return a (n_steps, 1, 3) uint8 vertical legend bar.

    The bar runs from the *high* end of the palette (top, index 0)
    to the *low* end (bottom, index n_steps-1), matching the convention
    of most CAD false-colour bars.

    Parameters
    ----------
    palette : str
        ``'viridis'`` or ``'diverging_blue_red'``.
    n_steps : int
        Height of the legend bar in pixels (clamped to [2, 1024]).

    Returns
    -------
    numpy.ndarray  shape (n_steps, 1, 3), dtype uint8
    """
    n = int(np.clip(n_steps, 2, 1024))
    lut = _build_lut(palette, n)
    # High at top (index 0) → low at bottom (index n-1)
    bar = lut[::-1].copy().reshape(n, 1, 3)
    return bar.astype(np.uint8)


# ---------------------------------------------------------------------------
# Pure-Python PNG encoder (no Pillow)
# PNG 1.2 spec: https://www.w3.org/TR/PNG/
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build one PNG chunk: length (4B big-endian) + type (4B) + data + CRC (4B)."""
    length = struct.pack(">I", len(data))
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return length + chunk_type + data + struct.pack(">I", crc)


def _encode_png(rgb: np.ndarray) -> bytes:
    """Encode an (H, W, 3) uint8 RGB array as PNG bytes.

    Implements the minimal PNG subset required by the spec:
    - 8-byte signature
    - IHDR (width, height, bit depth=8, colour type=2 (RGB), compression=0,
             filter=0, interlace=0)
    - IDAT (zlib-compressed filtered scanlines, filter type 0 = None)
    - IEND

    Filter type 0 (None) is applied to every row: prepend a 0x00 byte.
    The image data is then zlib-compressed (level 6 — good compression,
    reasonable speed).

    Parameters
    ----------
    rgb : numpy.ndarray
        Shape (H, W, 3), dtype uint8.

    Returns
    -------
    bytes  — complete PNG file content.
    """
    H, W, _ = rgb.shape

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    # IDAT: build raw scanlines with filter type 0 (None) prepended
    raw_rows = bytearray()
    for row in range(H):
        raw_rows.append(0)  # filter byte: None
        raw_rows.extend(rgb[row].tobytes())

    compressed = zlib.compress(bytes(raw_rows), level=6)
    idat = _png_chunk(b"IDAT", compressed)

    # IEND
    iend = _png_chunk(b"IEND", b"")

    return _PNG_SIGNATURE + ihdr + idat + iend


def export_heatmap_png(
    surface: NurbsSurface,
    path: str,
    kind: str = "gaussian",
    n_samples: int = 256,
    palette: str = "viridis",
    value_range: Union[str, tuple[float, float]] = "auto",
) -> None:
    """Export a NURBS curvature heatmap as a PNG file.

    Uses a pure-Python PNG encoder (no Pillow dependency).  The PNG
    uses 8-bit RGB colour (24 bpp), filter type 0, zlib compression
    level 6.

    Parameters
    ----------
    surface : NurbsSurface
    path : str
        Output file path (will be created/overwritten).
    kind : str
        ``'gaussian'`` | ``'mean'`` | ``'max_principal'``
    n_samples : int
        Grid resolution → image is n_samples × n_samples pixels.
        Clamped to [4, 512].
    palette : str
        ``'viridis'`` | ``'diverging_blue_red'``
    value_range : ``'auto'`` or (vmin, vmax)
    """
    rgb = render_curvature_heatmap(surface, kind=kind, n_samples=n_samples,
                                    palette=palette, value_range=value_range)
    png_bytes = _encode_png(rgb)
    Path(path).write_bytes(png_bytes)


def export_heatmap_svg(
    surface: NurbsSurface,
    path: str,
    kind: str = "gaussian",
    n_samples: int = 64,
    palette: str = "viridis",
    value_range: Union[str, tuple[float, float]] = "auto",
    cell_size: int = 4,
) -> None:
    """Export a NURBS curvature heatmap as an SVG file.

    Each UV sample point becomes a coloured rectangle of ``cell_size`` ×
    ``cell_size`` SVG user units.  The SVG viewBox is set to
    ``(n_samples * cell_size) × (n_samples * cell_size)``.

    Parameters
    ----------
    surface : NurbsSurface
    path : str
        Output file path.
    kind : str
        ``'gaussian'`` | ``'mean'`` | ``'max_principal'``
    n_samples : int
        Grid resolution.  Clamped to [4, 256].
    palette : str
        ``'viridis'`` | ``'diverging_blue_red'``
    value_range : ``'auto'`` or (vmin, vmax)
    cell_size : int
        Pixel size of each cell in SVG units (default 4).
    """
    n = int(np.clip(n_samples, 4, 256))
    cs = max(1, int(cell_size))
    rgb = render_curvature_heatmap(surface, kind=kind, n_samples=n,
                                    palette=palette, value_range=value_range)
    H, W, _ = rgb.shape
    svg_w = W * cs
    svg_h = H * cs

    lines: list[str] = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{svg_w}" height="{svg_h}"'
        f' viewBox="0 0 {svg_w} {svg_h}">',
        f'  <title>NURBS {kind} curvature heatmap ({palette})</title>',
        f'  <g id="heatmap">',
    ]

    for i in range(H):
        for j in range(W):
            r, g, b = int(rgb[i, j, 0]), int(rgb[i, j, 1]), int(rgb[i, j, 2])
            x = j * cs
            y = i * cs
            colour = f"#{r:02x}{g:02x}{b:02x}"
            lines.append(
                f'    <rect x="{x}" y="{y}"'
                f' width="{cs}" height="{cs}"'
                f' fill="{colour}"/>'
            )

    lines += [
        "  </g>",
        "</svg>",
    ]

    Path(path).write_text("\n".join(lines), encoding="utf-8")


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

    def _build_surface_for_heatmap(a: dict):
        """Build NurbsSurface from tool args. Returns (surface, err_str)."""
        degree_u = a.get("degree_u")
        degree_v = a.get("degree_v")
        raw_cp = a.get("control_points", [])
        num_u = a.get("num_u")
        num_v = a.get("num_v")

        if any(x is None for x in [degree_u, degree_v, num_u, num_v]) or not raw_cp:
            return None, "degree_u, degree_v, control_points, num_u, num_v are required"

        try:
            degree_u = int(degree_u)
            degree_v = int(degree_v)
            num_u = int(num_u)
            num_v = int(num_v)
        except (TypeError, ValueError) as exc:
            return None, f"degree/num must be integers: {exc}"

        if degree_u < 1 or degree_v < 1:
            return None, "degree_u and degree_v must be >= 1"
        if num_u < 2 or num_v < 2:
            return None, "num_u and num_v must be >= 2"
        if len(raw_cp) != num_u * num_v:
            return None, f"control_points length {len(raw_cp)} != num_u*num_v={num_u * num_v}"

        try:
            cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = np.array([p.tolist()[:dim] for p in cp_flat], dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n: int, deg: int) -> np.ndarray:
            inner = max(0, n - deg - 1)
            return np.concatenate([
                np.zeros(deg + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(deg + 1),
            ])

        try:
            surface = NurbsSurface(
                degree_u=degree_u, degree_v=degree_v,
                control_points=cp,
                knots_u=_make_knots(num_u, degree_u),
                knots_v=_make_knots(num_v, degree_v),
            )
        except Exception as exc:
            return None, f"failed to build NurbsSurface: {exc}"

        return surface, ""

    # -------------------------------------------------------------------------
    # nurbs_export_curvature_png
    # -------------------------------------------------------------------------

    _export_png_spec = ToolSpec(
        name="nurbs_export_curvature_png",
        description=(
            "Export a NURBS surface curvature heatmap as a PNG file.  "
            "Samples Gaussian / mean / max-principal curvature on an n_samples×n_samples "
            "UV grid, maps values to RGB via 'viridis' or 'diverging_blue_red' palette, "
            "and writes a pure-PNG (no Pillow) file to the given path.\n\n"
            "kind choices: 'gaussian' (K = eg-f²/EG-F²), 'mean' (H), 'max_principal' (κ₁).\n"
            "Returns: {ok, path, width, height, kind, palette, vmin, vmax}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer", "description": "Surface degree in U."},
                "degree_v": {"type": "integer", "description": "Surface degree in V."},
                "control_points": {
                    "type": "array",
                    "description": "Flattened num_u*num_v control points [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {"type": "integer"},
                "num_v": {"type": "integer"},
                "path": {
                    "type": "string",
                    "description": "Output PNG file path (will be created/overwritten).",
                },
                "kind": {
                    "type": "string",
                    "enum": ["gaussian", "mean", "max_principal"],
                    "description": "Curvature type to visualise (default 'gaussian').",
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Grid resolution; image will be n_samples×n_samples (default 256, clamped to [4,512]).",
                },
                "palette": {
                    "type": "string",
                    "enum": ["viridis", "diverging_blue_red"],
                    "description": "Colour palette (default 'viridis').",
                },
                "vmin": {"type": "number", "description": "Manual range minimum (omit for auto)."},
                "vmax": {"type": "number", "description": "Manual range maximum (omit for auto)."},
            },
            "required": ["degree_u", "degree_v", "control_points", "num_u", "num_v", "path"],
        },
    )

    @register(_export_png_spec)
    async def run_nurbs_export_curvature_png(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surface, err = _build_surface_for_heatmap(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        out_path = a.get("path")
        if not out_path:
            return err_payload("path is required", "BAD_ARGS")

        kind = str(a.get("kind", "gaussian"))
        n_samples = int(a.get("n_samples", 256))
        palette = str(a.get("palette", "viridis"))

        vmin_raw = a.get("vmin")
        vmax_raw = a.get("vmax")
        if vmin_raw is not None and vmax_raw is not None:
            value_range: Union[str, tuple[float, float]] = (float(vmin_raw), float(vmax_raw))
        else:
            value_range = "auto"

        try:
            rgb = render_curvature_heatmap(surface, kind=kind, n_samples=n_samples,
                                            palette=palette, value_range=value_range)
        except (ValueError, RuntimeError) as exc:
            return err_payload(str(exc), "OP_FAILED")

        try:
            export_heatmap_png(surface, path=out_path, kind=kind, n_samples=n_samples,
                                palette=palette, value_range=value_range)
        except Exception as exc:
            return err_payload(f"PNG write failed: {exc}", "IO_ERROR")

        H, W, _ = rgb.shape
        # Reconstruct actual vmin/vmax used
        field_map = {"gaussian": "gaussian", "mean": "mean", "max_principal": "principal_k1"}
        r2 = _curvature_heatmap(surface, nu=n_samples, nv=n_samples)
        field = r2[field_map.get(kind, "gaussian")]
        finite = field[np.isfinite(field)]
        actual_vmin = float(finite.min()) if finite.size > 0 else 0.0
        actual_vmax = float(finite.max()) if finite.size > 0 else 0.0

        return ok_payload({
            "path": out_path,
            "width": W,
            "height": H,
            "kind": kind,
            "palette": palette,
            "vmin": actual_vmin,
            "vmax": actual_vmax,
        })

    # -------------------------------------------------------------------------
    # nurbs_export_curvature_svg
    # -------------------------------------------------------------------------

    _export_svg_spec = ToolSpec(
        name="nurbs_export_curvature_svg",
        description=(
            "Export a NURBS surface curvature heatmap as an SVG file.  "
            "Each UV sample becomes a coloured <rect> element; the palette and "
            "curvature type are the same as nurbs_export_curvature_png.\n\n"
            "SVG is suitable for embedding in reports or documentation.  "
            "Use n_samples ≤ 64 for reasonable file sizes.\n\n"
            "Returns: {ok, path, width, height, kind, palette, n_rects}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer"},
                "degree_v": {"type": "integer"},
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {"type": "integer"},
                "num_v": {"type": "integer"},
                "path": {
                    "type": "string",
                    "description": "Output SVG file path.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["gaussian", "mean", "max_principal"],
                    "description": "Curvature type (default 'gaussian').",
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Grid resolution (default 64, clamped to [4, 256]).",
                },
                "palette": {
                    "type": "string",
                    "enum": ["viridis", "diverging_blue_red"],
                    "description": "Colour palette (default 'viridis').",
                },
                "cell_size": {
                    "type": "integer",
                    "description": "SVG rect size in user units (default 4).",
                },
                "vmin": {"type": "number"},
                "vmax": {"type": "number"},
            },
            "required": ["degree_u", "degree_v", "control_points", "num_u", "num_v", "path"],
        },
    )

    @register(_export_svg_spec)
    async def run_nurbs_export_curvature_svg(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surface, err = _build_surface_for_heatmap(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        out_path = a.get("path")
        if not out_path:
            return err_payload("path is required", "BAD_ARGS")

        kind = str(a.get("kind", "gaussian"))
        n_samples = int(a.get("n_samples", 64))
        palette = str(a.get("palette", "viridis"))
        cell_size = int(a.get("cell_size", 4))

        vmin_raw = a.get("vmin")
        vmax_raw = a.get("vmax")
        if vmin_raw is not None and vmax_raw is not None:
            value_range: Union[str, tuple[float, float]] = (float(vmin_raw), float(vmax_raw))
        else:
            value_range = "auto"

        try:
            export_heatmap_svg(surface, path=out_path, kind=kind, n_samples=n_samples,
                                palette=palette, value_range=value_range, cell_size=cell_size)
        except (ValueError, RuntimeError) as exc:
            return err_payload(str(exc), "OP_FAILED")
        except Exception as exc:
            return err_payload(f"SVG write failed: {exc}", "IO_ERROR")

        n = int(np.clip(n_samples, 4, 256))
        svg_w = n * cell_size
        svg_h = n * cell_size

        return ok_payload({
            "path": out_path,
            "width": svg_w,
            "height": svg_h,
            "kind": kind,
            "palette": palette,
            "n_rects": n * n,
        })
