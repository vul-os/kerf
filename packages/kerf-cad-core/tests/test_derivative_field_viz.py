"""
test_derivative_field_viz.py
============================
Hermetic analytic-oracle tests for derivative_field_viz.py.

Test groups
-----------
1. flat_plane_arrows_parallel  — All ∂S/∂u arrows have identical magnitude and
   all ∂S/∂v arrows have identical magnitude (uniform parameterisation, flat surface).
2. sphere_arrows_tangent       — ∂S/∂u and ∂S/∂v vectors are both orthogonal to the
   surface normal at every sampled point (i.e. tangent to the surface).
3. png_magic_bytes             — Returned bytes start with the PNG signature.
4. svg_structure               — SVG output contains <line> elements in two groups.
5. arrow_scaling               — Longest arrow fits within one cell (scale invariant).
6. samples_param               — Different sample counts produce different image sizes.

All tests are pure-Python: no OCC, no database, no network.
"""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_normal
from kerf_cad_core.geom.derivative_field_viz import (
    render_derivative_field_png,
    render_derivative_field_svg,
    _compute_arrow_field,
    _arrow_scale,
)


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def make_flat_plane(size: float = 1.0, nu: int = 4, nv: int = 4) -> NurbsSurface:
    """Flat z=0 plane over [0,size]×[0,size], degree 2."""
    deg = 2
    nu = max(nu, deg + 1)
    nv = max(nv, deg + 1)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i * size / (nu - 1), j * size / (nv - 1), 0.0]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_bilinear_plane(size: float = 1.0) -> NurbsSurface:
    """Degree-1 bilinear patch (exact derivatives = constant vectors)."""
    cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, size, 0.0]],
        [[size, 0.0, 0.0], [size, size, 0.0]],
    ])
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=knots.copy(),
        knots_v=knots.copy(),
    )


def make_sphere_approx(radius: float = 1.0, n: int = 5) -> NurbsSurface:
    """Approximate sphere as a degree-2 tensor-product surface (z-pole patch).

    Parameterised over [0,1]×[0,1] mapping (u→θ, v→φ).  Not the exact NURBS
    circle construction — uses a sampled grid sufficient to test tangency.
    """
    deg = 2
    n = max(n, deg + 1)
    cp = np.zeros((n, n, 3))
    for i in range(n):
        theta = math.pi * i / (n - 1)  # 0..π
        for j in range(n):
            phi = 2 * math.pi * j / (n - 1)  # 0..2π
            cp[i, j] = [
                radius * math.sin(theta) * math.cos(phi),
                radius * math.sin(theta) * math.sin(phi),
                radius * math.cos(theta),
            ]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(n, deg),
        knots_v=_make_knots(n, deg),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFlatPlaneParallel:
    """On a flat uniformly-parameterised plane, all ∂S/∂u arrows are parallel
    (same direction and same magnitude) and all ∂S/∂v arrows are parallel."""

    def test_du_magnitudes_uniform(self):
        srf = make_bilinear_plane(size=2.0)
        _, _, dSu, dSv = _compute_arrow_field(srf, samples=6)
        mags_u = np.linalg.norm(dSu, axis=-1)  # (6, 6)
        # All magnitudes should be equal to machine precision
        assert float(np.std(mags_u)) < 1e-10, (
            f"∂S/∂u magnitudes on flat plane should be constant, std={np.std(mags_u)}"
        )

    def test_dv_magnitudes_uniform(self):
        srf = make_bilinear_plane(size=2.0)
        _, _, dSu, dSv = _compute_arrow_field(srf, samples=6)
        mags_v = np.linalg.norm(dSv, axis=-1)
        assert float(np.std(mags_v)) < 1e-10, (
            f"∂S/∂v magnitudes on flat plane should be constant, std={np.std(mags_v)}"
        )

    def test_du_direction_uniform(self):
        srf = make_bilinear_plane(size=2.0)
        _, _, dSu, _ = _compute_arrow_field(srf, samples=6)
        # Normalise
        norms = np.linalg.norm(dSu, axis=-1, keepdims=True) + 1e-300
        dirs = dSu / norms
        # All should be equal to the first
        ref = dirs[0, 0]
        for i in range(dirs.shape[0]):
            for j in range(dirs.shape[1]):
                err = float(np.linalg.norm(dirs[i, j] - ref))
                assert err < 1e-10, f"∂S/∂u direction not uniform at [{i},{j}]: err={err}"

    def test_dv_direction_uniform(self):
        srf = make_bilinear_plane(size=2.0)
        _, _, _, dSv = _compute_arrow_field(srf, samples=6)
        norms = np.linalg.norm(dSv, axis=-1, keepdims=True) + 1e-300
        dirs = dSv / norms
        ref = dirs[0, 0]
        for i in range(dirs.shape[0]):
            for j in range(dirs.shape[1]):
                err = float(np.linalg.norm(dirs[i, j] - ref))
                assert err < 1e-10, f"∂S/∂v direction not uniform at [{i},{j}]: err={err}"


class TestSphereTangent:
    """On an approximate sphere, ∂S/∂u and ∂S/∂v must both be orthogonal to the
    surface normal (i.e. tangent to the surface)."""

    def test_du_tangent_to_surface(self):
        srf = make_sphere_approx(radius=1.0, n=5)
        u_vals, v_vals, dSu, dSv = _compute_arrow_field(srf, samples=5)
        for i, u in enumerate(u_vals):
            for j, v in enumerate(v_vals):
                n_hat = surface_normal(srf, u, v)
                du = dSu[i, j]
                du_norm = float(np.linalg.norm(du))
                if du_norm < 1e-9:
                    continue  # near-degenerate pole — skip
                dot = float(abs(np.dot(du / du_norm, n_hat)))
                assert dot < 0.05, (
                    f"∂S/∂u not tangent at u={u:.3f}, v={v:.3f}: |dot(du,n)|={dot:.4f}"
                )

    def test_dv_tangent_to_surface(self):
        srf = make_sphere_approx(radius=1.0, n=5)
        u_vals, v_vals, dSu, dSv = _compute_arrow_field(srf, samples=5)
        for i, u in enumerate(u_vals):
            for j, v in enumerate(v_vals):
                n_hat = surface_normal(srf, u, v)
                dv = dSv[i, j]
                dv_norm = float(np.linalg.norm(dv))
                if dv_norm < 1e-9:
                    continue
                dot = float(abs(np.dot(dv / dv_norm, n_hat)))
                assert dot < 0.05, (
                    f"∂S/∂v not tangent at u={u:.3f}, v={v:.3f}: |dot(dv,n)|={dot:.4f}"
                )


class TestPNGRoundTrip:
    """PNG output must start with the standard PNG magic bytes."""

    _PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

    def test_magic_bytes(self):
        srf = make_flat_plane()
        data = render_derivative_field_png(srf, samples=4)
        assert data[:8] == self._PNG_MAGIC, "PNG magic bytes mismatch"

    def test_ihdr_present(self):
        srf = make_flat_plane()
        data = render_derivative_field_png(srf, samples=4)
        # IHDR chunk starts at byte 8: 4-byte length + 4-byte type "IHDR"
        assert data[12:16] == b"IHDR", "IHDR chunk missing"

    def test_iend_present(self):
        srf = make_flat_plane()
        data = render_derivative_field_png(srf, samples=4)
        # IEND is always the last 12 bytes (0 length + "IEND" + CRC)
        assert data[-8:-4] == b"IEND", "IEND chunk missing"

    def test_image_dimensions_from_ihdr(self):
        n = 6
        srf = make_flat_plane()
        data = render_derivative_field_png(srf, samples=n)
        # IHDR data starts at byte 16; width and height are first two big-endian uint32s
        W = struct.unpack(">I", data[16:20])[0]
        H = struct.unpack(">I", data[20:24])[0]
        expected = n * 48
        assert W == expected, f"PNG width={W} expected {expected}"
        assert H == expected, f"PNG height={H} expected {expected}"


class TestSVGStructure:
    """SVG output must contain <line> elements grouped by arrow type."""

    def test_contains_du_group(self):
        srf = make_flat_plane()
        svg = render_derivative_field_svg(srf, samples=4)
        assert 'id="du_arrows"' in svg, "SVG missing du_arrows group"

    def test_contains_dv_group(self):
        srf = make_flat_plane()
        svg = render_derivative_field_svg(srf, samples=4)
        assert 'id="dv_arrows"' in svg, "SVG missing dv_arrows group"

    def test_has_line_elements(self):
        srf = make_flat_plane()
        svg = render_derivative_field_svg(srf, samples=4)
        assert "<line " in svg, "SVG has no <line> elements"

    def test_red_stroke_present(self):
        srf = make_flat_plane()
        svg = render_derivative_field_svg(srf, samples=4)
        assert "dc1e1e" in svg.lower(), "SVG missing red (#dc1e1e) stroke for ∂S/∂u"

    def test_blue_stroke_present(self):
        srf = make_flat_plane()
        svg = render_derivative_field_svg(srf, samples=4)
        assert "143cd2" in svg.lower(), "SVG missing blue (#143cd2) stroke for ∂S/∂v"

    def test_svg_opens_and_closes(self):
        srf = make_flat_plane()
        svg = render_derivative_field_svg(srf, samples=4)
        assert svg.strip().startswith("<?xml"), "SVG missing XML declaration"
        assert svg.strip().endswith("</svg>"), "SVG not properly closed"


class TestArrowScaling:
    """Arrow scaling: longest arrow length <= cell_size (scale invariant check)."""

    def test_scale_respects_cell_bound(self):
        srf = make_flat_plane(size=3.0)
        cell_px = 48.0 * 0.85  # same as internal default
        _, _, dSu, dSv = _compute_arrow_field(srf, samples=8)
        scale = _arrow_scale(dSu, dSv, cell_px)
        all_mags = np.concatenate([
            np.linalg.norm(dSu, axis=-1).ravel(),
            np.linalg.norm(dSv, axis=-1).ravel(),
        ])
        max_arrow_px = float(np.max(all_mags)) * scale
        assert max_arrow_px <= cell_px + 1e-9, (
            f"Longest arrow {max_arrow_px:.2f}px exceeds cell bound {cell_px:.2f}px"
        )


class TestSamplesParam:
    """Different sample counts produce differently-sized outputs."""

    def test_png_size_scales_with_samples(self):
        srf = make_flat_plane()
        data4 = render_derivative_field_png(srf, samples=4)
        data8 = render_derivative_field_png(srf, samples=8)
        assert len(data8) > len(data4), "8-sample PNG should be larger than 4-sample"

    def test_svg_line_count_scales_with_samples(self):
        srf = make_flat_plane()
        svg4 = render_derivative_field_svg(srf, samples=4)
        svg8 = render_derivative_field_svg(srf, samples=8)
        n4 = svg4.count("<line ")
        n8 = svg8.count("<line ")
        assert n8 > n4, f"8-sample SVG has fewer lines ({n8}) than 4-sample ({n4})"
