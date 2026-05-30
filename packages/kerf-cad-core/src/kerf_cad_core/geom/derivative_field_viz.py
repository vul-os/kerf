"""
derivative_field_viz.py
=======================
NURBS surface 1st-partial-derivative vector-field visualisation (GK-P).

Renders the partial-derivative field (∂S/∂u, ∂S/∂v) on a NURBS surface as an
arrow-plot in both PNG and SVG formats.

Provides
--------
render_derivative_field_png(srf, samples=12) -> bytes
    Pure-Python PNG (IHDR + IDAT + IEND, no Pillow) of the arrow plot on a
    white background.  ∂S/∂u arrows in red, ∂S/∂v arrows in blue.

render_derivative_field_svg(srf, samples=12) -> str
    SVG string containing one ``<line>`` element per arrow, coloured red (∂u)
    or blue (∂v).

Both functions project the 3-D derivative vectors into the 2-D (u, v) parameter
domain for display: the arrow origin is the (u, v) grid point, and the arrow tip
is offset by the *projected* derivative scaled so the longest arrow spans at most
one grid-cell width.

Numerical caveats
-----------------
* Arrow magnitude uses the 3-D Euclidean norm of the derivative vector, which
  conflates parameter-space scaling with geometric curvature.  On surfaces with
  very non-uniform parameterisation some arrows may appear unnaturally short or
  long relative to others even though the underlying geometry is smooth — this is
  expected behaviour, not a bug.

* Arrow direction is computed in (u, v) space by projecting ∂S/∂u onto the
  (1, 0) axis and ∂S/∂v onto (0, 1) after normalising.  For non-orthogonal
  parameterisations this introduces a small shear; the arrow length still encodes
  the true 3-D partial-derivative magnitude.

PNG 1.2 spec: https://www.w3.org/TR/PNG/
"""

from __future__ import annotations

import struct
import zlib
from typing import Union

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivative

# ---------------------------------------------------------------------------
# Shared arrow-field computation
# ---------------------------------------------------------------------------

def _compute_arrow_field(srf: NurbsSurface, samples: int):
    """Return (u_grid, v_grid, dSu, dSv, scale) for the sample grid.

    dSu[i, j] and dSv[i, j] are the 3-D first partial derivatives at the (i, j)
    grid point.  scale is the global pixels-per-unit factor so the longest arrow
    fits within one cell.
    """
    n = max(2, int(samples))

    # Knot-domain boundaries
    u0 = float(srf.knots_u[srf.degree_u])
    u1 = float(srf.knots_u[-srf.degree_u - 1])
    v0 = float(srf.knots_v[srf.degree_v])
    v1 = float(srf.knots_v[-srf.degree_v - 1])

    # Avoid evaluating exactly at the boundary (degenerate poles on spheres etc.)
    eps_u = (u1 - u0) * 0.5 / n
    eps_v = (v1 - v0) * 0.5 / n
    u_vals = np.linspace(u0 + eps_u, u1 - eps_u, n)
    v_vals = np.linspace(v0 + eps_v, v1 - eps_v, n)

    dSu = np.zeros((n, n, 3))
    dSv = np.zeros((n, n, 3))

    for i, u in enumerate(u_vals):
        for j, v in enumerate(v_vals):
            dSu[i, j] = surface_derivative(srf, u, v, ku=1, kv=0)
            dSv[i, j] = surface_derivative(srf, u, v, ku=0, kv=1)

    return u_vals, v_vals, dSu, dSv


def _arrow_scale(dSu: np.ndarray, dSv: np.ndarray, cell_size_px: float) -> float:
    """Compute scale (pixels per unit of derivative magnitude).

    The longest arrow spans at most ``cell_size_px`` pixels.
    """
    mags_u = np.linalg.norm(dSu, axis=-1).ravel()
    mags_v = np.linalg.norm(dSv, axis=-1).ravel()
    max_mag = float(np.max(np.concatenate([mags_u, mags_v])))
    if max_mag < 1e-300:
        return 1.0
    return cell_size_px / max_mag


# ---------------------------------------------------------------------------
# PNG encoder (replicates curvature_heatmap pattern — no Pillow)
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return length + chunk_type + data + struct.pack(">I", crc)


def _encode_png(rgb: np.ndarray) -> bytes:
    """Encode an (H, W, 3) uint8 RGB array as PNG bytes (IHDR+IDAT+IEND)."""
    H, W, _ = rgb.shape
    ihdr_data = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    raw_rows = bytearray()
    for row in range(H):
        raw_rows.append(0)  # filter type None
        raw_rows.extend(rgb[row].tobytes())

    compressed = zlib.compress(bytes(raw_rows), level=6)
    idat = _png_chunk(b"IDAT", compressed)
    iend = _png_chunk(b"IEND", b"")
    return _PNG_SIGNATURE + ihdr + idat + iend


def _draw_line_rgb(
    canvas: np.ndarray,
    x0: float, y0: float, x1: float, y1: float,
    colour: tuple,
    thickness: int = 1,
) -> None:
    """Draw a line on an (H, W, 3) uint8 canvas using Bresenham's algorithm."""
    H, W, _ = canvas.shape
    ix0, iy0 = int(round(x0)), int(round(y0))
    ix1, iy1 = int(round(x1)), int(round(y1))
    dx = abs(ix1 - ix0)
    dy = abs(iy1 - iy0)
    sx = 1 if ix0 < ix1 else -1
    sy = 1 if iy0 < iy1 else -1
    err = dx - dy

    while True:
        for ty in range(-thickness // 2, thickness // 2 + 1):
            for tx in range(-thickness // 2, thickness // 2 + 1):
                px = ix0 + tx
                py = iy0 + ty
                if 0 <= px < W and 0 <= py < H:
                    canvas[py, px] = colour

        if ix0 == ix1 and iy0 == iy1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            ix0 += sx
        if e2 < dx:
            err += dx
            iy0 += sy


def _draw_arrowhead(
    canvas: np.ndarray,
    tip_x: float, tip_y: float,
    dx: float, dy: float,
    colour: tuple,
    size: int = 4,
) -> None:
    """Draw a small arrowhead at (tip_x, tip_y) pointing in direction (dx, dy)."""
    length = (dx ** 2 + dy ** 2) ** 0.5
    if length < 1e-9:
        return
    ux, uy = dx / length, dy / length
    # Two flanking points
    px = tip_x - size * ux + size * 0.4 * (-uy)
    py = tip_y - size * uy + size * 0.4 * ux
    qx = tip_x - size * ux - size * 0.4 * (-uy)
    qy = tip_y - size * uy - size * 0.4 * ux
    _draw_line_rgb(canvas, tip_x, tip_y, px, py, colour)
    _draw_line_rgb(canvas, tip_x, tip_y, qx, qy, colour)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_derivative_field_png(srf: NurbsSurface, samples: int = 12) -> bytes:
    """Render the ∂S/∂u and ∂S/∂v vector field as a PNG image.

    Parameters
    ----------
    srf : NurbsSurface
        Surface to analyse.
    samples : int
        Number of sample points along each parameter axis (default 12).
        The output image is ``(samples * cell_px) × (samples * cell_px)`` pixels.

    Returns
    -------
    bytes
        Complete PNG file content (pure-Python encoder, no Pillow).
        ∂S/∂u arrows are red (255, 0, 0); ∂S/∂v arrows are blue (0, 0, 255).
    """
    n = max(2, int(samples))
    cell_px = 48  # pixels per grid cell

    W = n * cell_px
    H = n * cell_px

    # White background
    canvas = np.full((H, W, 3), 255, dtype=np.uint8)

    u_vals, v_vals, dSu, dSv = _compute_arrow_field(srf, n)
    scale = _arrow_scale(dSu, dSv, cell_px * 0.85)

    # Grid cell spacing in pixels
    cell_u = W / n
    cell_v = H / n

    RED = (220, 30, 30)
    BLUE = (20, 60, 210)
    GREY = (180, 180, 180)

    # Draw faint grid
    for i in range(n + 1):
        x = int(i * cell_u)
        _draw_line_rgb(canvas, x, 0, x, H - 1, GREY)
    for j in range(n + 1):
        y = int(j * cell_v)
        _draw_line_rgb(canvas, 0, y, W - 1, y, GREY)

    for i in range(n):
        for j in range(n):
            # Pixel origin of this cell (u left→right, v top→bottom)
            ox = (i + 0.5) * cell_u
            oy = (j + 0.5) * cell_v

            # ∂S/∂u arrow — project magnitude onto u-axis direction in image space
            du_vec = dSu[i, j]
            du_mag = float(np.linalg.norm(du_vec))
            du_px = du_mag * scale
            # Arrow points right (+u direction)
            x1_u = ox + du_px
            y1_u = oy
            _draw_line_rgb(canvas, ox, oy, x1_u, y1_u, RED, thickness=2)
            _draw_arrowhead(canvas, x1_u, y1_u, du_px, 0.0, RED, size=5)

            # ∂S/∂v arrow — project magnitude onto v-axis direction in image space
            dv_vec = dSv[i, j]
            dv_mag = float(np.linalg.norm(dSv[i, j]))
            dv_px = dv_mag * scale
            # Arrow points down (+v direction)
            x1_v = ox
            y1_v = oy + dv_px
            _draw_line_rgb(canvas, ox, oy, x1_v, y1_v, BLUE, thickness=2)
            _draw_arrowhead(canvas, x1_v, y1_v, 0.0, dv_px, BLUE, size=5)

    return _encode_png(canvas)


def render_derivative_field_svg(srf: NurbsSurface, samples: int = 12) -> str:
    """Render the ∂S/∂u and ∂S/∂v vector field as an SVG string.

    Each arrow is a ``<line>`` element (shaft) plus two flanking ``<line>``
    elements forming the arrowhead.  The SVG viewBox is in pixel units with
    one cell = 48 SVG user units.

    Parameters
    ----------
    srf : NurbsSurface
    samples : int
        Grid resolution (default 12).

    Returns
    -------
    str
        Complete UTF-8 SVG document string.
        ∂S/∂u lines are ``stroke="#dc1e1e"``; ∂S/∂v lines are ``stroke="#143cd2"``.
    """
    n = max(2, int(samples))
    cell_px = 48
    W = n * cell_px
    H = n * cell_px

    u_vals, v_vals, dSu, dSv = _compute_arrow_field(srf, n)
    scale = _arrow_scale(dSu, dSv, cell_px * 0.85)

    cell_u = W / n
    cell_v = H / n

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{W}" height="{H}"'
        f' viewBox="0 0 {W} {H}">',
        f'  <title>NURBS 1st partial-derivative field ({n}×{n} samples)</title>',
        f'  <desc>Red = dS/du, Blue = dS/dv. Arrow length encodes 3-D magnitude.</desc>',
        # White background
        f'  <rect width="{W}" height="{H}" fill="white"/>',
        # Grid
        '  <g id="grid" stroke="#cccccc" stroke-width="0.5">',
    ]

    for i in range(n + 1):
        x = round(i * cell_u, 2)
        lines.append(f'    <line x1="{x}" y1="0" x2="{x}" y2="{H}"/>')
    for j in range(n + 1):
        y = round(j * cell_v, 2)
        lines.append(f'    <line x1="0" y1="{y}" x2="{W}" y2="{y}"/>')
    lines.append("  </g>")

    # du arrows (red)
    lines.append('  <g id="du_arrows" stroke="#dc1e1e" stroke-width="1.5" fill="none">')
    for i in range(n):
        for j in range(n):
            ox = round((i + 0.5) * cell_u, 2)
            oy = round((j + 0.5) * cell_v, 2)
            du_mag = float(np.linalg.norm(dSu[i, j]))
            du_px = round(du_mag * scale, 2)
            x1 = round(ox + du_px, 2)
            y1 = oy
            # shaft
            lines.append(f'    <line x1="{ox}" y1="{oy}" x2="{x1}" y2="{y1}"/>')
            # arrowhead
            if du_px > 1e-3:
                head = 4
                lines.append(
                    f'    <line x1="{x1}" y1="{y1}"'
                    f' x2="{round(x1 - head, 2)}" y2="{round(y1 - head * 0.4, 2)}"/>'
                )
                lines.append(
                    f'    <line x1="{x1}" y1="{y1}"'
                    f' x2="{round(x1 - head, 2)}" y2="{round(y1 + head * 0.4, 2)}"/>'
                )
    lines.append("  </g>")

    # dv arrows (blue)
    lines.append('  <g id="dv_arrows" stroke="#143cd2" stroke-width="1.5" fill="none">')
    for i in range(n):
        for j in range(n):
            ox = round((i + 0.5) * cell_u, 2)
            oy = round((j + 0.5) * cell_v, 2)
            dv_mag = float(np.linalg.norm(dSv[i, j]))
            dv_px = round(dv_mag * scale, 2)
            x1 = ox
            y1 = round(oy + dv_px, 2)
            lines.append(f'    <line x1="{ox}" y1="{oy}" x2="{x1}" y2="{y1}"/>')
            if dv_px > 1e-3:
                head = 4
                lines.append(
                    f'    <line x1="{x1}" y1="{y1}"'
                    f' x2="{round(x1 - head * 0.4, 2)}" y2="{round(y1 - head, 2)}"/>'
                )
                lines.append(
                    f'    <line x1="{x1}" y1="{y1}"'
                    f' x2="{round(x1 + head * 0.4, 2)}" y2="{round(y1 - head, 2)}"/>'
                )
    lines.append("  </g>")
    lines.append("</svg>")

    return "\n".join(lines)


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

    def _build_surface(a: dict):
        """Build NurbsSurface from tool args. Returns (surface, err_str)."""
        import numpy as _np
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
            cp_flat = [_np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = _np.array([p.tolist()[:dim] for p in cp_flat], dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n: int, deg: int) -> _np.ndarray:
            inner = max(0, n - deg - 1)
            return _np.concatenate([
                _np.zeros(deg + 1),
                _np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else _np.array([]),
                _np.ones(deg + 1),
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
    # nurbs_derivative_field_png
    # -------------------------------------------------------------------------

    _png_spec = ToolSpec(
        name="nurbs_derivative_field_png",
        description=(
            "Render the 1st partial-derivative vector field (∂S/∂u, ∂S/∂v) of a NURBS surface "
            "as a PNG arrow-plot.  Red arrows = ∂S/∂u, blue arrows = ∂S/∂v.  Arrow length is "
            "proportional to the 3-D derivative magnitude, scaled so the longest arrow fits one "
            "grid cell.  Output is a pure-Python PNG file (no Pillow).\n\n"
            "Returns: {ok, path, width, height, samples}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer", "description": "Surface degree in U (>= 1)."},
                "degree_v": {"type": "integer", "description": "Surface degree in V (>= 1)."},
                "control_points": {
                    "type": "array",
                    "description": "Flattened num_u*num_v control points [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {"type": "integer", "description": "Control-point count in U."},
                "num_v": {"type": "integer", "description": "Control-point count in V."},
                "path": {
                    "type": "string",
                    "description": "Output PNG file path (will be created/overwritten).",
                },
                "samples": {
                    "type": "integer",
                    "description": "Grid resolution — image is (samples*48)×(samples*48) px (default 12).",
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "num_u", "num_v", "path"],
        },
    )

    @register(_png_spec)
    async def run_nurbs_derivative_field_png(ctx: "ProjectCtx", args: bytes) -> str:
        from pathlib import Path as _Path
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surface, err = _build_surface(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        out_path = a.get("path")
        if not out_path:
            return err_payload("path is required", "BAD_ARGS")

        samples = int(a.get("samples", 12))

        try:
            png_bytes = render_derivative_field_png(surface, samples=samples)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        try:
            _Path(out_path).write_bytes(png_bytes)
        except Exception as exc:
            return err_payload(f"PNG write failed: {exc}", "IO_ERROR")

        n = max(2, samples)
        cell_px = 48
        side = n * cell_px
        return ok_payload({
            "path": out_path,
            "width": side,
            "height": side,
            "samples": n,
        })

    # -------------------------------------------------------------------------
    # nurbs_derivative_field_svg
    # -------------------------------------------------------------------------

    _svg_spec = ToolSpec(
        name="nurbs_derivative_field_svg",
        description=(
            "Render the 1st partial-derivative vector field (∂S/∂u, ∂S/∂v) of a NURBS surface "
            "as an SVG arrow-plot.  Each arrow is a ``<line>`` element; red = ∂S/∂u, "
            "blue = ∂S/∂v.  Suitable for embedding in reports or documentation.\n\n"
            "Returns: {ok, path, width, height, samples, n_lines}. Never raises."
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
                "samples": {
                    "type": "integer",
                    "description": "Grid resolution (default 12).",
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "num_u", "num_v", "path"],
        },
    )

    @register(_svg_spec)
    async def run_nurbs_derivative_field_svg(ctx: "ProjectCtx", args: bytes) -> str:
        from pathlib import Path as _Path
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surface, err = _build_surface(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        out_path = a.get("path")
        if not out_path:
            return err_payload("path is required", "BAD_ARGS")

        samples = int(a.get("samples", 12))

        try:
            svg_str = render_derivative_field_svg(surface, samples=samples)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        try:
            _Path(out_path).write_text(svg_str, encoding="utf-8")
        except Exception as exc:
            return err_payload(f"SVG write failed: {exc}", "IO_ERROR")

        n = max(2, samples)
        cell_px = 48
        side = n * cell_px
        # 3 lines per arrow (shaft + 2 arrowhead), 2 arrows per cell
        n_lines = n * n * 2 * 3
        return ok_payload({
            "path": out_path,
            "width": side,
            "height": side,
            "samples": n,
            "n_lines": n_lines,
        })
