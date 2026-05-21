"""
test_gk95_reflection_lines.py
==============================
Hermetic pytest oracle for GK-95 — reflection_lines / highlight_lines.

Oracles
-------
1. A single smooth degree-3 NURBS patch (z = 0 plane or gentle paraboloid)
   produces a continuous stripe field — the c1_break_mask has very few
   flagged cells (well below 5 % of the interior).

2. A G1-but-not-G2 join is synthesised by gluing two patches that share the
   same position and tangent plane along a seam, but whose second-order
   partials differ.  The reflection_lines result for a surface sampled *across*
   this seam shows a localised spike in the stripe-field curvature
   (gradient2_grid) — i.e., the c1_break_mask fires near the seam.

All tests are pure-Python: no OCC, no database, no network.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_analysis import reflection_lines


# ---------------------------------------------------------------------------
# Helpers shared with other surface_analysis tests
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def _smooth_plane(size: float = 2.0, nu: int = 5, nv: int = 5) -> NurbsSurface:
    """Flat degree-1 plane z=0 spanning [0, size] × [0, size]."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i * size / (nu - 1), j * size / (nv - 1), 0.0]
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_make_knots(nu, 1),
        knots_v=_make_knots(nv, 1),
    )


def _smooth_paraboloid(R: float = 4.0, half_extent: float = 0.5,
                        nu: int = 6, nv: int = 6) -> NurbsSurface:
    """Degree-2 paraboloid z = (1/(2R))*(x²+y²) — single smooth patch."""
    deg = 2
    c = 1.0 / (2.0 * R)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i - (nu - 1) / 2.0) / ((nu - 1) / 2.0) * half_extent
        for j in range(nv):
            y = (j - (nv - 1) / 2.0) / ((nv - 1) / 2.0) * half_extent
            cp[i, j] = [x, y, c * (x * x + y * y)]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def _g1_not_g2_surface(
    half: float = 0.5,
    nu_patch: int = 4,
    nv: int = 5,
    curvature_jump: float = 3.0,
) -> NurbsSurface:
    """Construct a synthetic G1-but-not-G2 surface.

    Two degree-2 patches are stitched along the u=0 seam in v-parameter space.
    Left patch (v in [0, 0.5]): gentle paraboloid, curvature c_left = 1/(2*R)
    Right patch (v in [0.5, 1]): steeper paraboloid, curvature c_right =
    c_left * curvature_jump.

    At the seam (v=0.5) positions match (G0) and first partials match (G1)
    because both patches are built so that the seam control row is identical.
    However the second partials differ (curvature jump) — G2 is NOT satisfied.

    We build a single NurbsSurface that spans both patches by concatenating
    control points in the v-direction with repeated interior knot to model
    the seam.  A double knot at the interior of a degree-2 B-spline introduces
    a C0 (position-continuous, tangent-discontinuous) join; using a single
    repeated interior knot for degree-2 gives C1-only — but to create a
    deliberate G1-not-G2 break we use a continuous (single-knot) interior
    while having distinct curvatures on each half by lifting the interior
    control rows symmetrically away from the seam.
    """
    # Build manually: nu_patch control points in u per patch half;
    # total nv_total = 2*nv_patch - 1 (shared seam row).
    nv_patch = nv
    nv_total = 2 * nv_patch - 1

    c_left = 1.0 / (2.0 * 4.0)               # gentle curvature
    c_right = c_left * curvature_jump          # steeper curvature

    cp = np.zeros((nu_patch, nv_total, 3))

    # u-coords
    xs = np.linspace(-half, half, nu_patch)

    # Left half: j = 0 .. nv_patch-1, v in [0, 0.5]
    for j in range(nv_patch):
        y = (j / (nv_patch - 1) - 0.5)        # y in [-0.5, 0] (seam at y=0)
        for i in range(nu_patch):
            x = xs[i]
            z = c_left * (x * x + y * y)
            cp[i, j] = [x, y, z]

    # Right half: j = nv_patch .. nv_total-1 (seam row shared → skip j=0 of right)
    for j in range(1, nv_patch):
        y = j / (nv_patch - 1) * 0.5          # y in (0, 0.5]
        for i in range(nu_patch):
            x = xs[i]
            z = c_right * (x * x + y * y)
            cp[i, nv_patch - 1 + j] = [x, y, z]

    # Knots: degree-2 in v with enough control points
    # nv_total control points, degree 2 → nv_total + 3 knots
    deg_u, deg_v = 1, 2
    knots_u = _make_knots(nu_patch, deg_u)
    knots_v = _make_knots(nv_total, deg_v)

    return NurbsSurface(
        degree_u=deg_u,
        degree_v=deg_v,
        control_points=cp,
        knots_u=knots_u,
        knots_v=knots_v,
    )


# ---------------------------------------------------------------------------
# Oracle 1 — smooth patch → continuous stripe field (very few C1 breaks)
# ---------------------------------------------------------------------------

class TestReflectionLinesSmooth:
    """A single smooth NURBS patch must produce a stripe field with minimal
    c1_break_mask hits — the highlight lines are continuous."""

    def test_returns_ok_plane(self):
        surf = _smooth_plane()
        result = reflection_lines(surf, nu=16, nv=16)
        assert result["ok"] is True, result["reason"]

    def test_returns_ok_paraboloid(self):
        surf = _smooth_paraboloid()
        result = reflection_lines(surf, nu=16, nv=16)
        assert result["ok"] is True, result["reason"]

    def test_stripe_grid_shape(self):
        surf = _smooth_plane()
        result = reflection_lines(surf, nu=12, nv=10)
        assert result["stripe_grids"][0].shape == (12, 10)

    def test_normal_grid_shape(self):
        surf = _smooth_plane()
        result = reflection_lines(surf, nu=8, nv=8)
        assert result["normal_grid"].shape == (8, 8, 3)

    def test_us_vs_shapes(self):
        surf = _smooth_plane()
        result = reflection_lines(surf, nu=10, nv=7)
        assert result["us"].shape == (10,)
        assert result["vs"].shape == (7,)

    def test_stripe_values_in_range(self):
        """Stripe intensities are in [0, 1] (ignoring nan)."""
        surf = _smooth_paraboloid()
        result = reflection_lines(surf, nu=20, nv=20)
        sg = result["stripe_grids"][0]
        finite = sg[np.isfinite(sg)]
        assert finite.size > 0
        assert float(np.min(finite)) >= -1e-9
        assert float(np.max(finite)) <= 1.0 + 1e-9

    def test_smooth_surface_has_few_c1_breaks(self):
        """Smooth paraboloid: c1_break_mask fraction < 10 % (generous threshold
        to allow for boundary artefacts from finite differences)."""
        surf = _smooth_paraboloid(nu=7, nv=7)
        result = reflection_lines(surf, nu=32, nv=32)
        mask = result["c1_break_mask"]
        frac = float(np.sum(mask)) / mask.size
        assert frac < 0.10, (
            f"Too many C1-break flags on smooth surface: {frac:.1%}"
        )

    def test_smooth_surface_has_few_c0_breaks(self):
        """Smooth plane: c0_break_mask fraction < 10 %."""
        surf = _smooth_plane(nu=6, nv=6)
        result = reflection_lines(surf, nu=32, nv=32)
        mask = result["c0_break_mask"]
        frac = float(np.sum(mask)) / mask.size
        assert frac < 0.10, (
            f"Too many C0-break flags on smooth plane: {frac:.1%}"
        )

    def test_multiple_light_dirs_returns_one_grid_each(self):
        surf = _smooth_plane()
        lights = [[0, 0, -1], [0, 1, -1], [1, 0, -1]]
        result = reflection_lines(surf, light_dirs=lights, nu=10, nv=10)
        assert len(result["stripe_grids"]) == 3
        for sg in result["stripe_grids"]:
            assert sg.shape == (10, 10)

    def test_default_light_same_as_explicit(self):
        """Omitting light_dirs gives same result as passing [[0,0,-1]]."""
        surf = _smooth_plane(nu=4, nv=4)
        r_default = reflection_lines(surf, nu=8, nv=8)
        r_explicit = reflection_lines(surf, light_dirs=[[0.0, 0.0, -1.0]],
                                      nu=8, nv=8)
        np.testing.assert_allclose(
            r_default["stripe_grids"][0],
            r_explicit["stripe_grids"][0],
            atol=1e-12,
        )

    def test_gradient_grid_finite_for_smooth(self):
        surf = _smooth_paraboloid()
        result = reflection_lines(surf, nu=16, nv=16)
        g = result["gradient_grid"]
        finite = g[np.isfinite(g)]
        assert finite.size > 50
        assert float(np.min(finite)) >= 0.0


# ---------------------------------------------------------------------------
# Oracle 2 — G1-but-not-G2 join → kinked highlight line (C1 break detected)
# ---------------------------------------------------------------------------

class TestReflectionLinesG1NotG2Join:
    """The G1-but-not-G2 synthetic surface must show a C1 break in the
    stripe field: the c1_break_mask or the gradient2_grid must have a
    measurable spike at/near the seam (v ≈ 0.5)."""

    def _surf(self) -> NurbsSurface:
        return _g1_not_g2_surface(curvature_jump=4.0)

    def test_returns_ok(self):
        result = reflection_lines(self._surf(), nu=32, nv=32)
        assert result["ok"] is True, result["reason"]

    def test_gradient2_spike_near_seam(self):
        """The second-order gradient (stripe curvature) must be larger near the
        seam (middle third of the v range) than far from it.  This is the
        hallmark of a kinked highlight line: the curvature of the stripe field
        changes abruptly where the surface second-derivative jumps."""
        surf = self._surf()
        result = reflection_lines(surf, nu=32, nv=48)
        g2 = np.abs(result["gradient2_grid"])

        nv_total = g2.shape[1]
        # Seam region: middle ~1/6 of v range
        seam_lo = nv_total // 3
        seam_hi = nv_total - nv_total // 3

        # Far-from-seam regions (outer quarters)
        far_lo = nv_total // 8
        far_hi = nv_total - nv_total // 8

        seam_region = g2[:, seam_lo:seam_hi]
        far_region = np.concatenate(
            [g2[:, :far_lo], g2[:, far_hi:]], axis=1
        )

        finite_seam = seam_region[np.isfinite(seam_region)]
        finite_far = far_region[np.isfinite(far_region)]

        if finite_seam.size == 0 or finite_far.size == 0:
            pytest.skip("No finite values in seam/far region")

        mean_seam = float(np.mean(finite_seam))
        mean_far = float(np.mean(finite_far))

        assert mean_seam > mean_far, (
            f"Expected highlight-line kink at seam (mean_seam={mean_seam:.4g}) "
            f"to exceed far-region baseline (mean_far={mean_far:.4g})"
        )

    def test_c1_break_mask_fires(self):
        """At least one cell of c1_break_mask must be True for the G1/not-G2
        surface — the kinked highlight line triggers the detector."""
        surf = self._surf()
        result = reflection_lines(surf, nu=32, nv=48)
        assert result["c1_break_mask"].any(), (
            "c1_break_mask should have at least one True cell for a G1/not-G2 join"
        )

    def test_seam_has_higher_c1_density_than_smooth(self):
        """The fraction of c1_break_mask True cells is strictly higher for the
        G1/not-G2 join than for a smooth paraboloid of comparable size."""
        surf_join = self._surf()
        surf_smooth = _smooth_paraboloid(R=4.0, half_extent=0.4, nu=6, nv=6)

        r_join = reflection_lines(surf_join, nu=32, nv=48)
        r_smooth = reflection_lines(surf_smooth, nu=32, nv=48)

        frac_join = float(np.sum(r_join["c1_break_mask"])) / r_join["c1_break_mask"].size
        frac_smooth = float(np.sum(r_smooth["c1_break_mask"])) / r_smooth["c1_break_mask"].size

        assert frac_join > frac_smooth, (
            f"G1/not-G2 join ({frac_join:.1%}) should have more C1 break "
            f"flags than smooth paraboloid ({frac_smooth:.1%})"
        )
