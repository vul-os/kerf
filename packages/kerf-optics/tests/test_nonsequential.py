"""
Tests for kerf_optics.nonsequential — non-sequential ray tracing,
Fresnel ghost analysis, and stray-light simulation.

Validation
----------
1. Plano-convex lens spot: on-axis bundle converges to focal point; peak/mean > 5.
2. Ghost rays: same setup produces ≥1 ghost-ray pixel (Fresnel ~4% per interface).
3. SphericalSurface intersection: known geometry.
4. PlaneSurface intersection.
5. TIR: total internal reflection at a glass-air interface beyond critical angle.
6. RectAperture: rays inside pass, rays outside are absorbed.
7. Fresnel reflectance near normal incidence ≈ ((n-1)/(n+1))^2.
8. Ray direction is normalised.
9. trace_ray_ns returns empty list for zero-depth (terminal behaviour).
10. Detector irradiance accumulates correctly.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_optics.nonsequential import (
    Ray,
    SphericalSurface,
    PlaneSurface,
    RectAperture,
    Detector,
    Source,
    TraceResult,
    trace_ray_ns,
    trace_bundle,
    _fresnel_reflectance,
    _refract,
    _reflect,
    _unit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def plano_convex_setup(n_glass: float = 1.5, f_target: float = 0.1,
                        pixels: int = 128, n_rays: int = 2000, depth: int = 5):
    """
    Build a thin plano-convex lens (flat back, curved front) with a point
    source on-axis at z = -1.0 m and a detector at the paraxial focal plane.

    Lensmaker's equation for plano-convex (R2 = ∞):
        1/f = (n-1) / R1   →   R1 = (n-1)*f

    Surfaces (ordered by z position):
        z = 0.0   : front spherical surface (air → glass), radius R1, centre at (0,0,R1)
        z = 0.005 : rear plane surface (glass → air)
        z = f     : detector
    """
    R1 = (n_glass - 1.0) * f_target           # paraxial radius for target f
    thickness = 0.005                          # lens thickness (thin)

    surfaces = [
        SphericalSurface(
            radius=R1,
            center=np.array([0.0, 0.0, R1]),   # sphere centred at (0, 0, R1)
            n1=1.0,
            n2=n_glass,
        ),
        PlaneSurface(
            normal=np.array([0.0, 0.0, 1.0]),
            point=np.array([0.0, 0.0, thickness]),
            n1=n_glass,
            n2=1.0,
        ),
        Detector(
            plane_z=f_target,
            width=0.02,
            height=0.02,
            pixels_x=pixels,
            pixels_y=pixels,
        ),
    ]

    source = Source(
        position=np.array([0.0, 0.0, -1.0]),
        direction=np.array([0.0, 0.0, 1.0]),
        half_angle_deg=2.0,
        radius=0.0,
        wavelength_nm=550.0,
    )

    return source, surfaces


# ===========================================================================
# Primitive correctness
# ===========================================================================

class TestRay:
    def test_direction_normalised(self):
        ray = Ray([0, 0, 0], [3, 4, 0])
        assert abs(np.linalg.norm(ray.direction) - 1.0) < 1e-12

    def test_zero_direction_raises(self):
        with pytest.raises((ValueError, ZeroDivisionError)):
            Ray([0, 0, 0], [0, 0, 0])

    def test_point_at(self):
        ray = Ray([1.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        pt = ray.point_at(3.0)
        np.testing.assert_allclose(pt, [1.0, 0.0, 3.0])


class TestSphericalSurface:
    def test_intersect_along_axis(self):
        """Ray along +z hits a sphere centred at (0,0,2) with radius 1."""
        surf = SphericalSurface(radius=1.0, center=[0.0, 0.0, 2.0])
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        t = surf.intersect(ray)
        assert t is not None
        assert t == pytest.approx(1.0, abs=1e-10)   # front surface at z=1

    def test_no_intersection_behind_ray(self):
        """Sphere is entirely behind the ray origin."""
        surf = SphericalSurface(radius=1.0, center=[0.0, 0.0, -5.0])
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        t = surf.intersect(ray)
        assert t is None

    def test_miss(self):
        """Ray misses the sphere entirely."""
        surf = SphericalSurface(radius=0.5, center=[0.0, 0.0, 2.0])
        ray = Ray([0.0, 2.0, 0.0], [0.0, 0.0, 1.0])  # offset 2 m laterally
        t = surf.intersect(ray)
        assert t is None


class TestPlaneSurface:
    def test_perpendicular_hit(self):
        """Ray along z hits a plane at z=3."""
        surf = PlaneSurface(normal=[0, 0, 1], point=[0, 0, 3.0])
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        t = surf.intersect(ray)
        assert t == pytest.approx(3.0, abs=1e-12)

    def test_parallel_ray_no_hit(self):
        surf = PlaneSurface(normal=[0, 0, 1], point=[0, 0, 1.0])
        ray = Ray([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert surf.intersect(ray) is None

    def test_behind_ray(self):
        surf = PlaneSurface(normal=[0, 0, 1], point=[0, 0, -1.0])
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        assert surf.intersect(ray) is None


class TestRectAperture:
    def _aperture(self):
        return RectAperture(
            corner1=[-0.005, -0.005, 1.0],
            corner2=[ 0.005,  0.005, 1.0],
        )

    def test_ray_inside_passes(self):
        ap = self._aperture()
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        t = ap.intersect(ray)
        assert t is not None
        children = ap.interact(ray, t, depth=3, epsilon=1e-9)
        assert len(children) == 1
        assert children[0].intensity == pytest.approx(1.0)

    def test_ray_outside_absorbed(self):
        ap = self._aperture()
        ray = Ray([0.5, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        t = ap.intersect(ray)
        assert t is not None
        children = ap.interact(ray, t, depth=3, epsilon=1e-9)
        assert len(children) == 0


# ===========================================================================
# Fresnel physics
# ===========================================================================

class TestFresnelReflectance:
    def test_normal_incidence_glass_air(self):
        """R at normal incidence = ((n-1)/(n+1))^2 ≈ 0.04 for n=1.5."""
        n = 1.5
        R = _fresnel_reflectance(1.0, n, cos_i=1.0)
        expected = ((n - 1) / (n + 1)) ** 2
        assert R == pytest.approx(expected, rel=1e-6)

    def test_tir(self):
        """Beyond critical angle → R = 1.0."""
        n1, n2 = 1.5, 1.0
        theta_c = math.asin(n2 / n1)
        cos_beyond = math.cos(theta_c + 0.1)
        R = _fresnel_reflectance(n1, n2, cos_i=cos_beyond)
        assert R == pytest.approx(1.0, abs=1e-10)

    def test_r_between_0_and_1(self):
        for cos_i in [0.1, 0.3, 0.5, 0.8, 1.0]:
            R = _fresnel_reflectance(1.0, 1.5, cos_i)
            assert 0.0 <= R <= 1.0


class TestRefractReflect:
    def test_refract_normal_incidence(self):
        """At normal incidence refraction doesn't change direction."""
        d = np.array([0.0, 0.0, 1.0])
        n_hat = np.array([0.0, 0.0, -1.0])  # against incident ray
        refracted = _refract(d, n_hat, 1.0, 1.5)
        assert refracted is not None
        np.testing.assert_allclose(refracted, [0.0, 0.0, 1.0], atol=1e-12)

    def test_reflect_normal_incidence(self):
        """Reflection at normal incidence reverses direction."""
        d = np.array([0.0, 0.0, 1.0])
        n_hat = np.array([0.0, 0.0, -1.0])
        r = _reflect(d, n_hat)
        np.testing.assert_allclose(r, [0.0, 0.0, -1.0], atol=1e-12)

    def test_tir_returns_none(self):
        """Refraction returns None beyond critical angle."""
        n1, n2 = 1.5, 1.0
        theta_c = math.asin(n2 / n1)
        theta_i = theta_c + 0.2
        d = np.array([math.sin(theta_i), 0.0, math.cos(theta_i)])
        n_hat = np.array([0.0, 0.0, -1.0])
        result = _refract(d, n_hat, n1, n2)
        assert result is None


# ===========================================================================
# Detector accumulation
# ===========================================================================

class TestDetector:
    def test_on_axis_ray_hits_centre_pixel(self):
        det = Detector(plane_z=1.0, width=0.02, height=0.02, pixels_x=10, pixels_y=10)
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        t = det.intersect(ray)
        assert t is not None
        det.interact(ray, t, depth=3, epsilon=1e-9)
        centre_px = det.irradiance[5, 5]   # centre pixel
        assert centre_px == pytest.approx(1.0)

    def test_offaxis_ray_misses_detector(self):
        det = Detector(plane_z=1.0, width=0.01, height=0.01, pixels_x=10, pixels_y=10)
        ray = Ray([1.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        t = det.intersect(ray)
        assert t is not None
        det.interact(ray, t, depth=3, epsilon=1e-9)
        # x=1.0 is outside width=0.01, so no intensity deposited
        assert det.irradiance.sum() == pytest.approx(0.0)

    def test_reset_clears_map(self):
        det = Detector(plane_z=1.0, width=0.02, height=0.02)
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=0.5)
        t = det.intersect(ray)
        det.interact(ray, t, depth=3, epsilon=1e-9)
        det.reset()
        assert det.irradiance.sum() == 0.0

    def test_ghost_map_incremented_for_2_reflections(self):
        det = Detector(plane_z=1.0, width=0.02, height=0.02, pixels_x=4, pixels_y=4)
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=0.3, n_reflections=2)
        t = det.intersect(ray)
        det.interact(ray, t, depth=3, epsilon=1e-9)
        assert det.ghost_map.sum() > 0.0
        assert det.irradiance.sum() > 0.0


# ===========================================================================
# trace_ray_ns unit tests
# ===========================================================================

class TestTraceRayNS:
    def test_ray_passes_through_to_detector(self):
        """A ray aimed at the detector should be absorbed (no leaves)."""
        det = Detector(plane_z=1.0, width=0.1, height=0.1)
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        leaves = trace_ray_ns(ray, [det], max_depth=4)
        assert leaves == []                        # absorbed by detector
        assert det.irradiance.sum() > 0.0

    def test_ray_escapes_empty_scene(self):
        """No surfaces → ray is a leaf immediately."""
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        leaves = trace_ray_ns(ray, [], max_depth=4)
        assert len(leaves) == 1

    def test_fresnel_spawns_two_children(self):
        """At a glass interface, two children (refracted + reflected) are spawned."""
        surf = PlaneSurface([0, 0, 1], [0, 0, 1.0], n1=1.0, n2=1.5)
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        # Use max_depth=1 so children cannot recurse further
        leaves = trace_ray_ns(ray, [surf], max_depth=1)
        assert len(leaves) == 2

    def test_intensity_conserved(self):
        """Total leaf intensity ≤ incident (no gain; Fresnel split conserves energy)."""
        surf = PlaneSurface([0, 0, 1], [0, 0, 1.0], n1=1.0, n2=1.5)
        ray = Ray([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        leaves = trace_ray_ns(ray, [surf], max_depth=3)
        total = sum(l.intensity for l in leaves)
        assert total <= 1.0 + 1e-12

    def test_aperture_blocks_ray(self):
        """Ray outside aperture window is absorbed."""
        ap = RectAperture([-0.005, -0.005, 0.5], [0.005, 0.005, 0.5])
        ray = Ray([1.0, 0.0, 0.0], [0.0, 0.0, 1.0], intensity=1.0)
        leaves = trace_ray_ns(ray, [ap], max_depth=4)
        assert leaves == []


# ===========================================================================
# Integration: plano-convex lens spot + ghost validation
# ===========================================================================

class TestNonseqBundle:
    """
    Validation tests per the task specification:
    1. Peak/mean irradiance ratio > 5 at the paraxial focal point.
    2. Ghost pixels (≥ 2 reflections) are non-zero but small.
    """

    @pytest.fixture(scope="class")
    def result(self):
        source, surfaces = plano_convex_setup(n_glass=1.5, f_target=0.1,
                                              pixels=128, n_rays=3000, depth=5)
        return trace_bundle(source, surfaces, n_rays=3000, max_depth=5, seed=7)

    def test_bundle_returns_trace_result(self, result):
        assert isinstance(result, TraceResult)

    def test_total_intensity_positive(self, result):
        assert result.total_intensity > 0.0

    def test_spot_peak_to_mean_ratio(self, result):
        """
        Peak pixel irradiance must be > 5× the mean of all off-peak pixels.

        This validates that the bundle converges to a focussed spot rather
        than spreading uniformly across the detector.
        """
        irr = result.detector.irradiance
        peak = irr.max()
        assert peak > 0.0, "no intensity on detector"
        off_peak = irr[irr < peak]
        if off_peak.size == 0:
            pytest.skip("only one pixel illuminated — trivially a spot")
        mean_off = off_peak.mean()
        ratio = peak / mean_off if mean_off > 1e-14 else float("inf")
        assert ratio > 5.0, (
            f"peak/mean ratio {ratio:.2f} < 5 — beam not focussed to a spot"
        )

    def test_ghost_rays_nonzero(self, result):
        """
        Fresnel reflectance at each glass-air interface is ~4%.
        A ray reflected from the rear surface and then reflected back from
        the front surface (double bounce) constitutes a ghost; intensity ≈ 0.04^2 = 0.16%.
        With 3000 rays we should see at least one ghost pixel.
        """
        assert result.ghost_flag, (
            "expected at least one ghost ray (≥ 2 reflections) to reach detector"
        )
        assert result.n_ghost_rays >= 1, (
            f"ghost pixel count {result.n_ghost_rays} should be ≥ 1"
        )

    def test_ghost_intensity_small_fraction(self, result):
        """Ghost intensity should be a small fraction of total (< 5%)."""
        if result.total_intensity < 1e-14:
            pytest.skip("no total intensity — cannot compute ratio")
        ratio = result.ghost_intensity / result.total_intensity
        assert ratio < 0.05, (
            f"ghost fraction {ratio:.4f} exceeds 5% — unexpectedly large"
        )

    def test_ghost_map_subset_of_irradiance(self, result):
        """Every pixel in the ghost map must also appear in the irradiance map."""
        ghost = result.detector.ghost_map
        irr = result.detector.irradiance
        # Wherever ghost > 0, irr must also be > 0
        mask = ghost > 0
        assert np.all(irr[mask] > 0), "ghost pixel with zero total irradiance"


# ===========================================================================
# LLM tool handler (async)
# ===========================================================================

class TestNSTraceTool:
    """Smoke-test the async LLM tool handler."""

    @pytest.mark.asyncio
    async def test_tool_returns_json_with_ghost_flag(self):
        import json
        from kerf_optics.nonsequential import run_optics_nonsequential_trace
        from kerf_optics._compat import ProjectCtx

        args = {
            "surfaces": [
                {
                    "type": "spherical",
                    "radius": 0.05,
                    "center": [0.0, 0.0, 0.05],
                    "n1": 1.0,
                    "n2": 1.5,
                },
                {
                    "type": "plane",
                    "normal": [0.0, 0.0, 1.0],
                    "point": [0.0, 0.0, 0.005],
                    "n1": 1.5,
                    "n2": 1.0,
                },
                {
                    "type": "detector",
                    "plane_z": 0.1,
                    "width": 0.02,
                    "height": 0.02,
                    "pixels_x": 32,
                    "pixels_y": 32,
                },
            ],
            "source": {
                "position": [0.0, 0.0, -1.0],
                "direction": [0.0, 0.0, 1.0],
                "half_angle_deg": 2.0,
            },
            "n_rays": 500,
            "max_depth": 4,
            "seed": 42,
        }
        ctx = ProjectCtx()
        raw = await run_optics_nonsequential_trace(args, ctx)
        payload = json.loads(raw)
        assert "ghost_flag" in payload
        assert "total_intensity_on_detector" in payload
        assert "irradiance_map" in payload
        assert payload["total_intensity_on_detector"] > 0.0

    @pytest.mark.asyncio
    async def test_tool_bad_surface_type_returns_error(self):
        import json
        from kerf_optics.nonsequential import run_optics_nonsequential_trace
        from kerf_optics._compat import ProjectCtx

        args = {
            "surfaces": [{"type": "banana"}],
            "source": {"position": [0, 0, -1], "direction": [0, 0, 1]},
        }
        ctx = ProjectCtx()
        raw = await run_optics_nonsequential_trace(args, ctx)
        payload = json.loads(raw)
        assert "error" in payload
        assert payload.get("code") == "NS_TRACE_ERROR"


# ===========================================================================
# Module import smoke test
# ===========================================================================

class TestNSImport:
    def test_import(self):
        import kerf_optics.nonsequential  # noqa: F401

    def test_pycompile(self):
        import py_compile
        path = os.path.join(_SRC, "kerf_optics", "nonsequential.py")
        py_compile.compile(path, doraise=True)
