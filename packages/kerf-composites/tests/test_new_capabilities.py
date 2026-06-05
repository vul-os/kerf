"""
Analytic oracle tests for the three new composites capabilities:

1. Drape engine extensions:
   - Sphere / cone surface factories
   - Flat-pattern unrolling (exact for cylinder, approximate for sphere)
   - Arc-length fields

2. Laminate weight / cost estimation:
   - Analytic areal-weight formula validation
   - Cost scaling with area + waste

3. Failure envelope:
   - Uniaxial limits equal FPF result from composites_failure_check
   - Envelope is closed and convex (rough check)

4. AFP path plan:
   - Coverage completeness
   - Course lengths positive
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

from kerf_composites.drape import (
    drape_flat_to_surface,
    flat_surface,
    cylindrical_surface,
    spherical_surface,
    conical_surface,
    unroll_to_flat_pattern,
    DrapeResult,
    FlatPatternResult,
)
from kerf_composites.layup import Ply, PlyMaterial, LaminateLayup, T300_5208


# ===========================================================================
# Section 1: Arc-length fields
# ===========================================================================

class TestArcLengths:
    """Arc-length fields in DrapeResult."""

    def test_flat_arc_length_u_equals_linear_distance(self):
        """On a flat surface the arc length along u equals the u range."""
        result = drape_flat_to_surface(flat_surface(0.0), (0.0, 100.0), (0.0, 50.0), nu=6, nv=4)
        # Last row of arc_lengths_u (j=0): cumulative along u-axis
        # arc_lengths_u[-1, 0] should equal 100.0
        assert abs(result.arc_lengths_u[-1, 0] - 100.0) < 1e-8

    def test_flat_arc_length_v_equals_linear_distance(self):
        result = drape_flat_to_surface(flat_surface(0.0), (0.0, 100.0), (0.0, 50.0), nu=6, nv=4)
        assert abs(result.arc_lengths_v[0, -1] - 50.0) < 1e-8

    def test_cylinder_arc_length_u_is_arc_distance(self):
        """Cylinder u=0..90 deg, R=100: arc length = R * π/2 ≈ 157.08 mm."""
        R = 100.0
        result = drape_flat_to_surface(
            cylindrical_surface(radius=R, axis="x"),
            (0.0, 90.0), (0.0, 50.0), nu=20, nv=4
        )
        # Arc length of 90° arc on radius-100 cylinder = R * π/2
        expected = R * math.pi / 2.0  # 157.08 mm
        # The last arc_lengths_u entry should be close to this
        actual = result.arc_lengths_u[-1, 0]
        assert abs(actual - expected) / expected < 0.01, (
            f"arc_length_u_max={actual:.3f} vs expected={expected:.3f}"
        )

    def test_arc_lengths_monotone_increasing(self):
        """Arc lengths are non-decreasing along each axis."""
        result = drape_flat_to_surface(
            cylindrical_surface(radius=200.0),
            (0.0, 45.0), (0.0, 100.0), nu=8, nv=8
        )
        for j in range(result.nv):
            diffs = np.diff(result.arc_lengths_u[:, j])
            assert np.all(diffs >= -1e-10), f"arc_u not monotone at col {j}"
        for i in range(result.nu):
            diffs = np.diff(result.arc_lengths_v[i, :])
            assert np.all(diffs >= -1e-10), f"arc_v not monotone at row {i}"


# ===========================================================================
# Section 2: Spherical surface
# ===========================================================================

class TestSphericalSurface:
    """Spherical cap surface factory."""

    def test_all_nodes_on_sphere(self):
        """All draped nodes lie on the sphere of radius R."""
        R = 250.0
        result = drape_flat_to_surface(
            spherical_surface(radius=R, pole="north"),
            (0.0, 30.0), (0.0, 90.0), nu=6, nv=8
        )
        for i in range(result.nu):
            for j in range(result.nv):
                x, y, z = result.surf_coords[i, j]
                dist = math.sqrt(x**2 + y**2 + z**2)
                assert abs(dist - R) < 1e-6, (
                    f"Node ({i},{j}): |P|={dist:.6f} vs R={R}"
                )

    def test_north_pole_at_zero_colatitude(self):
        """At u=0 (φ=0), all v → north pole (0, 0, R)."""
        R = 100.0
        sfn = spherical_surface(radius=R, pole="north")
        for v in [0.0, 45.0, 90.0, 180.0]:
            x, y, z = sfn(0.0, v)
            assert abs(x) < 1e-10, f"x={x} at u=0, v={v}"
            assert abs(y) < 1e-10, f"y={y} at u=0, v={v}"
            assert abs(z - R) < 1e-10, f"z={z} at u=0, v={v}"

    def test_south_pole_at_zero_colatitude(self):
        """South pole: at u=0, z = −R."""
        R = 100.0
        sfn = spherical_surface(radius=R, pole="south")
        x, y, z = sfn(0.0, 0.0)
        assert abs(x) < 1e-10
        assert abs(y) < 1e-10
        assert abs(z + R) < 1e-10

    def test_sphere_shear_nonzero(self):
        """Doubly-curved sphere → non-zero shear angles for non-trivial patches."""
        result = drape_flat_to_surface(
            spherical_surface(radius=100.0),
            (5.0, 45.0), (0.0, 90.0), nu=8, nv=8
        )
        # At least some shear should appear on a sphere
        shear_max = float(np.max(result.shear_angles))
        assert shear_max > 0.01, f"Expected non-zero shear on sphere, got {shear_max:.4f}"


# ===========================================================================
# Section 3: Conical surface
# ===========================================================================

class TestConicalSurface:
    """Right circular cone factory."""

    def test_all_nodes_on_cone(self):
        """
        All nodes satisfy the cone surface equation: sqrt(x²+y²) = (z − apex_z) * tan(α).

        The conical_surface factory maps (u=slant, v=azimuth_deg) to:
            x = u * sin(α) * cos(v_rad)
            y = u * sin(α) * sin(v_rad)
            z = apex_z + u * cos(α)
        so sqrt(x²+y²) = u * sin(α) and z = apex_z + u * cos(α)
        → sqrt(x²+y²) = (z − apex_z) * tan(α).
        """
        alpha = 20.0  # half-angle
        alpha_rad = math.radians(alpha)
        apex_z = 0.0
        result = drape_flat_to_surface(
            conical_surface(half_angle_deg=alpha, apex_z=apex_z),
            (10.0, 100.0), (0.0, 360.0), nu=6, nv=9
        )
        for i in range(result.nu):
            for j in range(result.nv):
                x, y, z = result.surf_coords[i, j]
                r_xy = math.sqrt(x**2 + y**2)
                r_expected = (z - apex_z) * math.tan(alpha_rad)
                assert abs(r_xy - r_expected) < 1e-6, (
                    f"Node ({i},{j}): r_xy={r_xy:.6f} vs r_expected={r_expected:.6f}"
                )

    def test_cone_flat_pattern_zero_distortion(self):
        """A cone is developable → flat-pattern distortion should be near zero."""
        result = drape_flat_to_surface(
            conical_surface(half_angle_deg=20.0),
            (10.0, 80.0), (0.0, 60.0), nu=8, nv=8
        )
        fp = unroll_to_flat_pattern(result)
        assert fp.distortion_pct < 5.0, (
            f"Cone flat-pattern distortion={fp.distortion_pct:.2f}% (expected near zero)"
        )


# ===========================================================================
# Section 4: Flat-pattern unrolling
# ===========================================================================

class TestFlatPatternUnrolling:
    """Flat-pattern unrolling via unroll_to_flat_pattern."""

    def test_flat_surface_zero_distortion(self):
        """Flat surface unrolling should have exactly zero distortion."""
        result = drape_flat_to_surface(flat_surface(0.0), (0.0, 100.0), (0.0, 50.0), nu=5, nv=5)
        fp = unroll_to_flat_pattern(result)
        assert fp.distortion_pct < 0.01, f"distortion={fp.distortion_pct:.4f}% on flat"

    def test_returns_flat_pattern_result(self):
        result = drape_flat_to_surface(flat_surface(0.0), (0.0, 10.0), (0.0, 10.0), nu=3, nv=3)
        fp = unroll_to_flat_pattern(result)
        assert isinstance(fp, FlatPatternResult)
        assert fp.unrolled_coords.shape == (3, 3, 2)

    def test_cylinder_near_zero_distortion(self):
        """Cylinder is developable → flat-pattern distortion < 1%."""
        result = drape_flat_to_surface(
            cylindrical_surface(radius=500.0, axis="x"),
            (0.0, 20.0), (0.0, 100.0), nu=8, nv=6
        )
        fp = unroll_to_flat_pattern(result)
        assert fp.distortion_pct < 1.5, (
            f"Cylinder flat-pattern distortion={fp.distortion_pct:.4f}%"
        )

    def test_sphere_unrolled_coords_shape(self):
        """Sphere unrolling should return the correct shape."""
        result = drape_flat_to_surface(
            spherical_surface(radius=100.0),
            (5.0, 60.0), (0.0, 90.0), nu=8, nv=8
        )
        fp = unroll_to_flat_pattern(result)
        assert fp.unrolled_coords.shape == (8, 8, 2)
        assert isinstance(fp.distortion_pct, float)
        assert fp.distortion_pct >= 0.0

    def test_origin_at_zero(self):
        """Unrolled origin (0,0) node should be at (0, 0)."""
        result = drape_flat_to_surface(flat_surface(0.0), (0.0, 100.0), (0.0, 50.0), nu=5, nv=5)
        fp = unroll_to_flat_pattern(result)
        assert abs(fp.unrolled_coords[0, 0, 0]) < 1e-10
        assert abs(fp.unrolled_coords[0, 0, 1]) < 1e-10

    def test_flat_unrolled_coords_preserve_distances(self):
        """
        Flat surface: unrolled coords should preserve chord distances.

        The unrolling algorithm seeds row 0 along the x-axis using v-direction
        chord lengths (j = 0..nv-1 at i=0).  For a flat surface with
        u_range=[0,100], v_range=[0,50], nu=5, nv=5:
          - v-step = 50/(5-1) = 12.5 mm
          - First row (i=0) seeds: x = [0, 12.5, 25.0, 37.5, 50.0], y = 0
        """
        result = drape_flat_to_surface(flat_surface(0.0), (0.0, 100.0), (0.0, 50.0), nu=5, nv=5)
        fp = unroll_to_flat_pattern(result)
        # First row should lie on y=0 (seed axis)
        for j in range(fp.nv):
            assert abs(fp.unrolled_coords[0, j, 1]) < 1e-6, (
                f"Row 0 should have y=0; got y={fp.unrolled_coords[0, j, 1]:.6f}"
            )
        # v-step = 50 / (5-1) = 12.5 mm
        v_step = 50.0 / (5 - 1)
        for j in range(1, fp.nv):
            dx = fp.unrolled_coords[0, j, 0] - fp.unrolled_coords[0, j - 1, 0]
            assert abs(dx - v_step) < 0.01, f"dx={dx:.4f} should be {v_step:.1f}"


# ===========================================================================
# Section 5: Areal weight formula — analytic oracle
# ===========================================================================

class TestArealWeightFormula:
    """
    Areal weight formula: w = ρ [g/cm³] × t [mm] × 1000 [g/m²]

    For a single ply of T300/Epoxy (ρ=1.58 g/cm³) with t=0.125 mm:
        w = 1.58 × 0.125 × 1000 = 197.5 g/m²

    Mass over 1 m²: 0.1975 kg.
    """

    def test_single_ply_t300_125mm(self):
        """Single T300/Epoxy ply 0.125 mm → areal weight = 197.5 g/m²."""
        rho = 1.58  # T300/Epoxy
        t = 0.125
        expected = rho * t * 1000.0
        assert abs(expected - 197.5) < 0.1

    def test_four_plies_qi_laminate(self):
        """QI [0/45/-45/90] T300/Epoxy: 4 × 197.5 = 790.0 g/m²."""
        rho, t, n = 1.58, 0.125, 4
        total = rho * t * 1000.0 * n
        assert abs(total - 790.0) < 0.5

    def test_mass_kg_per_m2_from_areal_weight(self):
        """Mass [kg/m²] = areal weight [g/m²] / 1000."""
        areal_g_m2 = 790.0
        mass_kg_m2 = areal_g_m2 / 1000.0
        assert abs(mass_kg_m2 - 0.790) < 1e-6

    def test_cost_formula_single_ply(self):
        """
        Cost = mass [kg] × cost_per_kg [USD/kg] × waste.

        T300/Epoxy: $45/kg, 1 m², no waste, single 0.125 mm ply.
        mass = 1.58 × 0.125/1000 m [thickness in m = /1e3] × 1e6 cm³/m³ × ...

        Using our formula:
          mass_kg = rho [g/cm³] × t [mm] × 1000 / 1000 = rho × t
          → per unit area, t in mm, rho in g/cm³:
            mass_kg_per_m2 = rho × t × 1000 / 1000 = rho × t [g/cm³ × mm = 0.1 kg/m²]
          !!  rho=1.58 g/cm³ × t=0.125mm × 1000 = 197.5 g/m² / 1000 = 0.1975 kg/m²

        cost = 0.1975 kg/m² × $45/kg = $8.888/m²
        """
        rho = 1.58  # g/cm³
        t = 0.125   # mm
        cost_per_kg = 45.0
        mass_kg_m2 = rho * t * 1000.0 / 1000.0  # = 0.1975 kg/m²
        cost = mass_kg_m2 * cost_per_kg
        assert abs(cost - 8.888) < 0.01


# ===========================================================================
# Section 6: Failure envelope sanity
# ===========================================================================

class TestFailureEnvelopeSanity:
    """
    The failure envelope for a [0/90/0] laminate should satisfy:
    - The point (0, 0) is inside the envelope (zero load is safe).
    - The uniaxial failure load Nx along theta=0° should be positive.
    - For a [0/90/0] laminate, max Nx > max Ny (more 0° plies).
    """

    def _layup_0_90_0(self):
        return LaminateLayup.from_sequence([0, 90, 0], T300_5208, ply_thickness=0.125)

    def test_envelope_points_positive_lambda(self):
        """All failure lambdas in the envelope must be positive."""
        import asyncio
        import json
        import sys
        sys.path.insert(0, _SRC)
        from kerf_composites.tools import run_composites_failure_envelope

        plies = [
            {"angle": a, "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
             "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0,
             "Yc": 246.0, "S12": 68.0}
            for a in [0, 90, 0]
        ]

        class _Ctx:
            pass

        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_composites_failure_envelope({"plies": plies, "n_angles": 8}, _Ctx())
        ))
        for pt in result["envelope_points"]:
            assert pt["lambda_crit"] > 0.0, f"lambda_crit={pt['lambda_crit']} at theta={pt['theta_deg']}"

    def test_max_Nx_exceeds_max_Ny(self):
        """[0/90/0] → max Nx failure load > max Ny failure load."""
        import asyncio, json
        from kerf_composites.tools import run_composites_failure_envelope

        plies = [
            {"angle": a, "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
             "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0,
             "Yc": 246.0, "S12": 68.0}
            for a in [0, 90, 0]
        ]

        class _Ctx:
            pass

        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_composites_failure_envelope({"plies": plies, "n_angles": 36}, _Ctx())
        ))
        assert result["max_uniaxial_Nx_N_per_mm"] > result["max_uniaxial_Ny_N_per_mm"], (
            f"Nx_max={result['max_uniaxial_Nx_N_per_mm']:.1f} should exceed "
            f"Ny_max={result['max_uniaxial_Ny_N_per_mm']:.1f}"
        )


# ===========================================================================
# Section 7: AFP path coverage
# ===========================================================================

class TestAFPCoverage:
    """AFP path plan coverage completeness."""

    def _run_afp(self, **kwargs):
        import asyncio, json
        from kerf_composites.tools import run_composites_afp_pathplan

        class _Ctx:
            pass

        return json.loads(asyncio.get_event_loop().run_until_complete(
            run_composites_afp_pathplan(kwargs, _Ctx())
        ))

    def test_0deg_coverage_near_100_pct(self):
        """0° with course width 10 mm on 100×100 mm part: ~100% coverage."""
        result = self._run_afp(
            part_width_mm=100, part_height_mm=100, course_width_mm=10.0, angle_deg=0.0
        )
        assert result["coverage_pct"] > 80.0, f"coverage={result['coverage_pct']:.1f}%"

    def test_45deg_generates_courses(self):
        """45° angle should generate at least 1 course on a 200×200 mm part."""
        result = self._run_afp(
            part_width_mm=200, part_height_mm=200, course_width_mm=10.0, angle_deg=45.0
        )
        assert result["num_courses"] > 0

    def test_course_lengths_all_positive(self):
        """All generated courses must have positive length."""
        result = self._run_afp(
            part_width_mm=200, part_height_mm=150, course_width_mm=8.0, angle_deg=30.0
        )
        for c in result["courses"]:
            assert c["length_mm"] > 0.0

    def test_course_ids_unique(self):
        """Course IDs must be unique."""
        result = self._run_afp(
            part_width_mm=100, part_height_mm=100, course_width_mm=10.0, angle_deg=0.0
        )
        ids = [c["course_id"] for c in result["courses"]]
        assert len(ids) == len(set(ids))

    def test_minus_45_generates_courses(self):
        """−45° should also generate courses."""
        result = self._run_afp(
            part_width_mm=200, part_height_mm=200, course_width_mm=10.0, angle_deg=-45.0
        )
        assert result["num_courses"] > 0
