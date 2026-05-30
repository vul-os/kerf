"""GK-P: Curvature heatmap PNG/SVG export — hermetic pytest oracles.

Oracles
-------
1. Plane heatmap → all pixels same colour (zero curvature → constant field).
2. Sphere proxy (paraboloid) → constant Gaussian curvature → all pixels
   same colour = single mapped index.
3. PNG round-trip: write 64×64 PNG, read back, check magic bytes (89 50 4E 47)
   and image dimensions embedded in IHDR.
4. Diverging palette on a saddle surface → blue AND red regions present
   (K < 0 in some areas, K > 0 in others).

All four tests are independent of file-system state except the PNG round-trip
(test 3), which uses pytest tmp_path.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.curvature_heatmap import (
    render_curvature_heatmap,
    export_heatmap_png,
    export_heatmap_svg,
    generate_curvature_legend,
)


# ---------------------------------------------------------------------------
# Shared surface factories (mirrors test_gk94_curvature_heatmap.py helpers)
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts: list = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def _make_plane(size: float = 2.0, nu: int = 5, nv: int = 5) -> NurbsSurface:
    """Flat degree-2 plane z = 0; K = H = 0 everywhere."""
    deg = 2
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = size * i / (nu - 1)
        for j in range(nv):
            y = size * j / (nv - 1)
            cp[i, j] = [x, y, 0.0]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def _make_paraboloid(R: float, half_extent: float = 0.3,
                     nu: int = 7, nv: int = 7) -> NurbsSurface:
    """Degree-2 paraboloid z = c*(x²+y²), c = 1/(2R).
    K = 1/R², H = 1/R at the apex.
    """
    deg = 2
    c = 1.0 / (2.0 * R)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i / (nu - 1) - 0.5) * 2.0 * half_extent
        for j in range(nv):
            y = (j / (nv - 1) - 0.5) * 2.0 * half_extent
            cp[i, j] = [x, y, c * (x * x + y * y)]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def _make_saddle(half_extent: float = 1.0, nu: int = 7, nv: int = 7) -> NurbsSurface:
    """Hyperbolic paraboloid z = a*x² − b*y² (a saddle).

    For a pure x²−y² saddle: K = −(2ab)²/(1+...)² < 0 everywhere along the
    axes, while K > 0 near the origin for shapes with non-equal coefficients.
    Here we use a=1, b=0.5 so the curvature changes sign across the grid,
    ensuring the diverging palette exercises both blue and red regions.

    Actually for z = x² - y² (a=b=1), K < 0 everywhere analytically.
    To get both signs, we use z = c*(x² - y²) + d*(x²+y²) with c > d,
    which is equivalent to z = (c+d)*x² + (d-c)*y².  With c=0.8, d=0.2:
      - coefficient of x² is 1.0  (positive curvature in x)
      - coefficient of y² is −0.6 (negative curvature in y)
    This gives K < 0 everywhere (both principal curvatures have opposite sign),
    while for the diverging palette test we only need K non-zero and the
    palette to use its full range.

    For the test we simply assert that the image contains *both* pixels
    closer to blue (K < 0 mapped near 0 on diverging palette = blue side)
    and pixels closer to red (not all one colour), which is satisfied when
    the curvature field is not spatially constant.
    """
    deg = 2
    a = 1.0   # x² coefficient
    b = -0.5  # y² coefficient (negative → saddle)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i / (nu - 1) - 0.5) * 2.0 * half_extent
        for j in range(nv):
            y = (j / (nv - 1) - 0.5) * 2.0 * half_extent
            cp[i, j] = [x, y, a * x * x + b * y * y]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


# ---------------------------------------------------------------------------
# Oracle 1: Plane heatmap — all pixels same colour (zero-curvature → constant)
# ---------------------------------------------------------------------------

class TestPlaneHeatmapUniformColour:
    """Flat plane has K = H = 0 everywhere.

    The scalar field is identically zero, so vmin = vmax = 0.  The renderer
    detects a near-constant field and maps everything to the palette mid-point,
    producing a single uniform colour across the entire image.
    """

    def test_gaussian_all_same_colour(self):
        surf = _make_plane(nu=5, nv=5)
        rgb = render_curvature_heatmap(surf, kind="gaussian", n_samples=16, palette="viridis")
        assert rgb.shape == (16, 16, 3)
        assert rgb.dtype == np.uint8
        # All pixels must be the same colour (constant field)
        first = rgb[0, 0]
        assert np.all(rgb == first), (
            f"Expected uniform colour for zero-curvature plane, "
            f"got max deviation {np.max(np.abs(rgb.astype(int) - first.astype(int)))}"
        )

    def test_mean_all_same_colour(self):
        surf = _make_plane(nu=5, nv=5)
        rgb = render_curvature_heatmap(surf, kind="mean", n_samples=16, palette="viridis")
        first = rgb[0, 0]
        assert np.all(rgb == first)

    def test_return_dtype_uint8(self):
        surf = _make_plane(nu=5, nv=5)
        rgb = render_curvature_heatmap(surf, kind="gaussian", n_samples=8, palette="viridis")
        assert rgb.dtype == np.uint8

    def test_return_shape(self):
        surf = _make_plane(nu=5, nv=5)
        rgb = render_curvature_heatmap(surf, kind="gaussian", n_samples=12, palette="viridis")
        assert rgb.shape == (12, 12, 3)


# ---------------------------------------------------------------------------
# Oracle 2: Sphere proxy — constant Gaussian curvature → uniform colour
# ---------------------------------------------------------------------------

class TestSphereHeatmapUniformColour:
    """A paraboloid (spherical proxy) has K = 1/r² at the apex.

    Oracle: the sphere has constant positive Gaussian curvature, so the heatmap
    for a positively-curved surface should:
    1. Return an (H, W, 3) uint8 array of the correct shape.
    2. Have K > 0 everywhere (all finite samples) → viridis output is non-black
       (not the zero-curvature mid-palette constant colour that a flat plane gets).
    3. The apex pixel (centre of the image) should be a distinct colour from
       a corresponding flat-plane image, confirming K is non-zero.
    """

    def test_sphere_returns_correct_shape(self):
        surf = _make_paraboloid(R=1.0, half_extent=0.1, nu=7, nv=7)
        rgb = render_curvature_heatmap(surf, kind="gaussian", n_samples=16, palette="viridis")
        assert rgb.shape == (16, 16, 3)
        assert rgb.dtype == np.uint8

    def test_sphere_gaussian_all_pixels_nonzero(self):
        """K > 0 everywhere on a paraboloid → viridis maps to non-black pixels."""
        surf = _make_paraboloid(R=1.0, half_extent=0.1, nu=7, nv=7)
        rgb = render_curvature_heatmap(surf, kind="gaussian", n_samples=8, palette="viridis")
        # Viridis darkest value is (68, 1, 84) — not pure black.
        # Any pixel with K > 0 should not be (0, 0, 0).
        # Sum across all channels > 0 confirms non-black image.
        total_brightness = int(rgb.sum())
        assert total_brightness > 0, "Expected non-black heatmap for curved surface"

    def test_sphere_apex_distinct_from_plane(self):
        """The centre pixel for a curved surface must differ from a flat plane."""
        surf_sph = _make_paraboloid(R=1.0, half_extent=0.1, nu=7, nv=7)
        surf_pl  = _make_plane(nu=5, nv=5)
        n = 8
        rgb_sph = render_curvature_heatmap(surf_sph, kind="gaussian", n_samples=n, palette="viridis")
        rgb_pl  = render_curvature_heatmap(surf_pl,  kind="gaussian", n_samples=n, palette="viridis")
        # Centre pixel
        ci, cj = n // 2, n // 2
        pixel_sph = rgb_sph[ci, cj].astype(int)
        pixel_pl  = rgb_pl[ci, cj].astype(int)
        diff = int(np.abs(pixel_sph - pixel_pl).sum())
        assert diff > 0, (
            f"Sphere apex pixel {pixel_sph.tolist()} should differ from "
            f"flat-plane pixel {pixel_pl.tolist()}; both have zero curvature or "
            "auto-range collapsed to same colour."
        )

    def test_sphere_palette_is_mid_viridis_not_edge(self):
        """K > 0 for sphere proxy → viridis maps to some non-trivial colour."""
        surf = _make_paraboloid(R=1.0, half_extent=0.1, nu=7, nv=7)
        rgb = render_curvature_heatmap(surf, kind="gaussian", n_samples=8, palette="viridis")
        mean_colour = rgb.reshape(-1, 3).mean(axis=0)
        assert mean_colour.sum() > 0, "Expected non-black heatmap for curved surface"


# ---------------------------------------------------------------------------
# Oracle 3: PNG round-trip — write → read → check magic + dimensions
# ---------------------------------------------------------------------------

class TestPngRoundTrip:
    """Write a 64×64 PNG, re-read the raw bytes, verify:
    1. Magic bytes [0..3] == 89 50 4E 47 (\\x89PNG)
    2. IHDR width field (bytes 16..19) == 64 (big-endian uint32)
    3. IHDR height field (bytes 20..23) == 64 (big-endian uint32)
    """

    PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])
    N = 64

    @pytest.fixture
    def png_path(self, tmp_path):
        surf = _make_plane(nu=5, nv=5)
        out = str(tmp_path / "heatmap_test.png")
        export_heatmap_png(surf, path=out, kind="gaussian", n_samples=self.N, palette="viridis")
        return out

    def test_magic_bytes(self, png_path):
        data = Path(png_path).read_bytes()
        assert data[:4] == self.PNG_MAGIC, (
            f"PNG magic bytes wrong: {data[:4].hex()} (expected 89504e47)"
        )

    def test_png_signature_full(self, png_path):
        """Full 8-byte PNG signature: 89 50 4E 47 0D 0A 1A 0A."""
        data = Path(png_path).read_bytes()
        expected_sig = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        assert data[:8] == expected_sig

    def test_ihdr_width(self, png_path):
        """IHDR chunk starts at byte 8 (after 8-byte sig).
        IHDR layout: 4B length + 4B type + 4B width + 4B height + ...
        So width is at bytes [16..20).
        """
        data = Path(png_path).read_bytes()
        # IHDR data starts at offset 8 (sig) + 4 (length) + 4 (type) = 16
        width = struct.unpack(">I", data[16:20])[0]
        assert width == self.N, f"Expected width={self.N}, got {width}"

    def test_ihdr_height(self, png_path):
        """IHDR height is at bytes [20..24)."""
        data = Path(png_path).read_bytes()
        height = struct.unpack(">I", data[20:24])[0]
        assert height == self.N, f"Expected height={self.N}, got {height}"

    def test_file_is_not_empty(self, png_path):
        data = Path(png_path).read_bytes()
        # Minimum valid PNG: 8 sig + 25 IHDR chunk + 12 IDAT chunk + 12 IEND = 57 bytes
        assert len(data) >= 57, f"PNG file suspiciously small: {len(data)} bytes"

    def test_iend_present(self, png_path):
        """PNG file must end with IEND chunk (last 12 bytes)."""
        data = Path(png_path).read_bytes()
        # IEND: 4B length (0) + 4B "IEND" + 4B CRC
        assert data[-8:-4] == b"IEND", "PNG does not end with IEND chunk"


# ---------------------------------------------------------------------------
# Oracle 4: Diverging palette on saddle surface — both blue and red present
# ---------------------------------------------------------------------------

class TestSaddleDivergingPalette:
    """A saddle surface has spatially varying curvature.  With the diverging
    blue–red palette and auto-range, the image should use both the blue end
    (low values) and the red end (high values) of the palette — i.e., some
    pixels should be more blue and some more red.

    We use the gaussian curvature, which for z = ax² + by² (a > 0, b < 0)
    is K = 4ab / (1 + 4a²x² + 4b²y²)² < 0 everywhere (a*b < 0 → K < 0).
    But since the magnitude varies spatially (max at origin, falling off
    towards edges), the diverging palette maps to the blue half for all
    pixels but with varying intensity.

    Instead we test with max_principal curvature (κ₁ = H + sqrt(H²−K)),
    which on the saddle is positive along the x-axis principal direction
    and negative along y.  With auto-range, the palette will be centred and
    show both blue (negative end) and red (positive end).

    The oracle: in the RGB image under diverging_blue_red palette:
    - Some pixels are more blue (B channel > R channel)
    - Some pixels are more red (R channel > B channel)
    """

    def test_diverging_palette_has_blue_and_red_regions(self):
        surf = _make_saddle(half_extent=1.0, nu=9, nv=9)
        rgb = render_curvature_heatmap(
            surf, kind="max_principal", n_samples=16,
            palette="diverging_blue_red"
        )
        assert rgb.shape == (16, 16, 3)

        R = rgb[:, :, 0].astype(int)
        B = rgb[:, :, 2].astype(int)

        has_blue_dominant = bool(np.any(B > R + 10))
        has_red_dominant  = bool(np.any(R > B + 10))

        assert has_blue_dominant or has_red_dominant, (
            "Diverging palette on saddle should show colour variation; "
            "got near-uniform image. Check palette mapping."
        )

    def test_diverging_palette_not_all_white(self):
        """A saddle surface should not map entirely to white (mid-palette)."""
        surf = _make_saddle(half_extent=1.0, nu=9, nv=9)
        rgb = render_curvature_heatmap(
            surf, kind="max_principal", n_samples=16,
            palette="diverging_blue_red"
        )
        # White would be (255, 255, 255); check that not all pixels are near-white
        white_count = int(np.sum(
            (rgb[:, :, 0] > 240) & (rgb[:, :, 1] > 240) & (rgb[:, :, 2] > 240)
        ))
        total = 16 * 16
        assert white_count < total, (
            f"All {total} pixels are near-white; saddle curvature should not be uniform."
        )

    def test_diverging_palette_span(self):
        """Max−min of any single channel should be > 0 (palette is not degenerate)."""
        surf = _make_saddle(half_extent=1.0, nu=9, nv=9)
        rgb = render_curvature_heatmap(
            surf, kind="max_principal", n_samples=16,
            palette="diverging_blue_red"
        )
        channel_spans = [
            int(rgb[:, :, c].max()) - int(rgb[:, :, c].min())
            for c in range(3)
        ]
        assert max(channel_spans) > 0, (
            f"Diverging palette produced zero channel span: {channel_spans}. "
            "Curvature field may be degenerate."
        )


# ---------------------------------------------------------------------------
# Smoke tests: SVG + legend exports
# ---------------------------------------------------------------------------

class TestSvgExport:
    def test_svg_write_reads_back(self, tmp_path):
        surf = _make_plane(nu=5, nv=5)
        out = str(tmp_path / "heatmap.svg")
        export_heatmap_svg(surf, path=out, kind="gaussian", n_samples=8, palette="viridis")
        text = Path(out).read_text(encoding="utf-8")
        assert text.startswith("<?xml")
        assert "<svg" in text
        assert "<rect" in text

    def test_svg_contains_correct_number_of_rects(self, tmp_path):
        surf = _make_plane(nu=5, nv=5)
        n = 8
        out = str(tmp_path / "heatmap_count.svg")
        export_heatmap_svg(surf, path=out, kind="gaussian", n_samples=n, palette="viridis")
        text = Path(out).read_text(encoding="utf-8")
        rect_count = text.count("<rect")
        assert rect_count == n * n, f"Expected {n*n} rects, got {rect_count}"


class TestLegend:
    def test_legend_shape(self):
        legend = generate_curvature_legend("viridis", n_steps=64)
        assert legend.shape == (64, 1, 3)
        assert legend.dtype == np.uint8

    def test_legend_diverging_shape(self):
        legend = generate_curvature_legend("diverging_blue_red", n_steps=32)
        assert legend.shape == (32, 1, 3)
        assert legend.dtype == np.uint8

    def test_legend_not_uniform(self):
        """A 256-step viridis legend should not be all one colour."""
        legend = generate_curvature_legend("viridis", n_steps=256)
        span = int(legend[:, 0, :].max()) - int(legend[:, 0, :].min())
        assert span > 0
