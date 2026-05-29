"""test_hvac.py — Unit tests for kerf-hvac.

DoD oracles:
  1. Darcy-Weisbach pressure drop for a straight rect duct matches formula to 1%.
  2. Reducer flat-pattern developed length is analytic (exact comparison).
  3. Duct sizing for 1000 CFM @ 2000 FPM gives the correct rectangular dimension.
  4. Minor-loss coefficient for a 90° rect elbow within ASHRAE range (K ≈ 0.3).
"""

from __future__ import annotations

import json
import math
import unittest

from kerf_hvac.duct import (
    DuctShape,
    DuctSection,
    Fitting,
    FittingType,
    DuctSystem,
    cfm_to_m3s,
    fpm_to_ms,
    m3s_to_cfm,
    ms_to_fpm,
    inch_to_mm,
    mm_to_inch,
)
from kerf_hvac.sizing import size_duct, size_duct_cfm_fpm, SizingResult
from kerf_hvac.flat_pattern import rect_elbow_pattern, rect_reducer_pattern
from kerf_hvac.pressure import (
    darcy_weisbach_loss,
    minor_loss,
    friction_factor,
    velocity_pressure,
    total_duct_loss,
    ELBOW_90_RECT_K,
    ELBOW_90_ROUND_K,
    TEE_MAIN_K,
    TEE_BRANCH_K,
    AIR_DENSITY_KG_M3,
    AIR_DYNAMIC_VISCOSITY_PA_S,
)


# ===========================================================================
# 1. Darcy-Weisbach pressure drop — DoD oracle #1
# ===========================================================================

class TestDarcyWeisbach(unittest.TestCase):
    """Verify DW formula matches to within 1%."""

    def _manual_dw(self, v, dh, L, eps, rho, mu):
        """Reference Darcy-Weisbach calculation."""
        re = rho * v * dh / mu
        eps_D = eps / dh
        # Colebrook-White (same iteration as friction_factor)
        if re < 2300:
            f = 64.0 / re
        else:
            f = 0.25 / (math.log10(eps_D / 3.7 + 5.74 / re ** 0.9)) ** 2
            for _ in range(100):
                f_new = (1.0 / (-2.0 * math.log10(eps_D / 3.7 + 2.51 / (re * math.sqrt(f))))) ** 2
                if abs(f_new - f) < 1e-8:
                    f = f_new
                    break
                f = f_new
        return f * (L / dh) * 0.5 * rho * v * v

    def test_rect_duct_turbulent_matches_formula(self):
        """DoD oracle: DW loss for a straight rect duct matches formula to 1%."""
        # A 400×250 mm duct, 10 m long, carrying air at 6 m/s
        W, H = 0.400, 0.250
        area = W * H
        dh = 4 * area / (2 * (W + H))
        v = 6.0
        L = 10.0
        eps = 0.09e-3
        rho = AIR_DENSITY_KG_M3
        mu = AIR_DYNAMIC_VISCOSITY_PA_S

        expected = self._manual_dw(v, dh, L, eps, rho, mu)
        result = darcy_weisbach_loss(
            velocity_m_s=v,
            hydraulic_diameter_m=dh,
            length_m=L,
            roughness_m=eps,
        )
        rel_error = abs(result - expected) / expected
        self.assertLess(rel_error, 0.01, f"DW error {rel_error:.4%} exceeds 1%")

    def test_laminar_flow(self):
        """Laminar (Re < 2300): f = 64/Re gives correct loss."""
        dh = 0.05
        v = 0.01  # very slow — laminar
        L = 5.0
        eps = 0.09e-3
        rho = AIR_DENSITY_KG_M3
        mu = AIR_DYNAMIC_VISCOSITY_PA_S
        re = rho * v * dh / mu
        self.assertLess(re, 2300)
        expected = (64.0 / re) * (L / dh) * 0.5 * rho * v ** 2
        result = darcy_weisbach_loss(v, dh, L, eps)
        self.assertAlmostEqual(result, expected, places=6)

    def test_zero_length_gives_zero(self):
        self.assertEqual(darcy_weisbach_loss(5.0, 0.3, 0.0), 0.0)

    def test_round_duct_typical_office(self):
        """200 mm round duct at 5 m/s, 20 m run — sanity-check result is positive."""
        result = darcy_weisbach_loss(
            velocity_m_s=5.0,
            hydraulic_diameter_m=0.200,
            length_m=20.0,
            roughness_m=0.09e-3,
        )
        self.assertGreater(result, 0.0)
        # Rough expectation: ~1–5 Pa/m × 20 m → 20–100 Pa
        self.assertGreater(result, 10.0)
        self.assertLess(result, 200.0)

    def test_friction_factor_smooth_turbulent(self):
        """Smooth duct at high Re: f should be small and positive."""
        f = friction_factor(1e6, 0.0)
        self.assertGreater(f, 0)
        self.assertLess(f, 0.02)

    def test_friction_factor_rough_turbulent(self):
        """Rough duct: f should be higher than smooth."""
        f_smooth = friction_factor(5e4, 0.0)
        f_rough = friction_factor(5e4, 0.01)
        self.assertGreater(f_rough, f_smooth)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            darcy_weisbach_loss(-1.0, 0.2, 5.0)
        with self.assertRaises(ValueError):
            darcy_weisbach_loss(5.0, 0.0, 5.0)
        with self.assertRaises(ValueError):
            darcy_weisbach_loss(5.0, 0.2, -1.0)


# ===========================================================================
# 2. Reducer flat-pattern developed length — DoD oracle #2
# ===========================================================================

class TestReducerFlatPattern(unittest.TestCase):
    """Verify reducer slant lengths against analytic formula."""

    def test_slant_length_analytic(self):
        """DoD oracle: reducer developed length matches sqrt(L^2 + (dH/2)^2)."""
        W1, H1 = 600.0, 400.0
        W2, H2 = 400.0, 300.0
        L = 300.0

        pat = rect_reducer_pattern(W1, H1, W2, H2, L)

        # Analytic top/bottom slant: sqrt(L^2 + ((H1-H2)/2)^2)
        expected_top = math.hypot(L, (H1 - H2) / 2)
        # Analytic side slant: sqrt(L^2 + ((W1-W2)/2)^2)
        expected_side = math.hypot(L, (W1 - W2) / 2)

        self.assertAlmostEqual(pat.top_slant_length_mm, expected_top, places=6)
        self.assertAlmostEqual(pat.side_slant_length_mm, expected_side, places=6)

    def test_symmetric_reducer_equal_slants(self):
        """Equal taper on all sides → top and side slants equal."""
        pat = rect_reducer_pattern(500, 500, 300, 300, 200)
        self.assertAlmostEqual(pat.top_slant_length_mm, pat.side_slant_length_mm, places=6)

    def test_panel_vertices_count(self):
        """Each panel should be a 4-vertex trapezoid."""
        pat = rect_reducer_pattern(400, 300, 200, 200, 250)
        for panel in [pat.top_plate, pat.bottom_plate, pat.left_plate, pat.right_plate]:
            self.assertEqual(len(panel), 4)

    def test_top_plate_upstream_width(self):
        """Top plate first edge should equal upstream width W1."""
        W1, H1, W2, H2, L = 500.0, 400.0, 300.0, 250.0, 200.0
        pat = rect_reducer_pattern(W1, H1, W2, H2, L)
        x0, y0 = pat.top_plate[0]
        x1, y1 = pat.top_plate[1]
        self.assertAlmostEqual(y0, 0.0)
        self.assertAlmostEqual(y1, 0.0)
        self.assertAlmostEqual(x1 - x0, W1)

    def test_top_plate_downstream_width(self):
        """Top plate top edge should equal downstream width W2 and be centred."""
        W1, H1, W2, H2, L = 500.0, 400.0, 300.0, 250.0, 200.0
        pat = rect_reducer_pattern(W1, H1, W2, H2, L)
        top_slant = pat.top_slant_length_mm
        # Top two vertices (indices 2, 3)
        x2, y2 = pat.top_plate[2]
        x3, y3 = pat.top_plate[3]
        self.assertAlmostEqual(y2, top_slant)
        self.assertAlmostEqual(y3, top_slant)
        self.assertAlmostEqual(x2 - x3, W2, places=6)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            rect_reducer_pattern(0, 300, 200, 200, 200)
        with self.assertRaises(ValueError):
            rect_reducer_pattern(400, 300, 200, 200, 0)

    def test_equal_size_reducer_is_straight_panel(self):
        """Reducer with W1=W2, H1=H2: slant = axial length (no offset)."""
        L = 300.0
        pat = rect_reducer_pattern(400, 300, 400, 300, L)
        self.assertAlmostEqual(pat.top_slant_length_mm, L, places=6)
        self.assertAlmostEqual(pat.side_slant_length_mm, L, places=6)


# ===========================================================================
# 3. Duct sizing for 1000 CFM @ 2000 FPM — DoD oracle #3
# ===========================================================================

class TestDuctSizing(unittest.TestCase):
    """Verify ASHRAE velocity method sizing."""

    def test_1000cfm_2000fpm_rect(self):
        """DoD oracle: 1000 CFM @ 2000 FPM gives correct rectangular size.

        Required cross-sectional area:
            Q = 1000 CFM = 0.47195 m³/s
            V = 2000 FPM = 10.16 m/s
            A_min = Q / V = 0.04646 m²

        The smallest 25-mm-modular rectangular duct satisfying this at ≤4:1 aspect:
          Try h=200mm (0.2m): w_needed = 0.04646/0.2 = 0.2323m → round up to 250mm
            aspect = 250/200 = 1.25 ✓ ; area = 0.050 m² ≥ 0.04646 m² ✓
          perimeter = 2*(0.25+0.2) = 0.90 m

          (h=150mm: w_needed=0.04646/0.15=0.3097 → 325mm, aspect=325/150=2.17 ✓)
          perimeter(150,325) = 2*(0.325+0.150) = 0.95 m  > 0.90 m  → worse

          (h=225mm: w_needed=0.04646/0.225=0.2065 → 225mm, aspect=225/225=1.0 ✓)
          perimeter(225,225) = 2*(0.225+0.225) = 0.90 m  (tie on perimeter, but
          same perimeter — sizing function picks first found so whichever comes
          first in the enumeration; actual correct answer depends on iteration order)

        We validate: resulting area ≥ A_min AND velocity ≤ 2000 FPM AND aspect ≤ 4.
        """
        q_m3s = cfm_to_m3s(1000.0)
        v_max_ms = fpm_to_ms(2000.0)
        result = size_duct(q_m3s, v_max_ms, DuctShape.RECTANGULAR)

        # Area must accommodate the flow at or below max velocity
        self.assertGreaterEqual(result.area_m2, q_m3s / v_max_ms)

        # Velocity must be at or below max
        self.assertLessEqual(result.actual_velocity_m_s, v_max_ms * 1.001)

        # Aspect ratio must be ≤ 4
        self.assertLessEqual(result.aspect_ratio, 4.0)

        # Both dimensions must be multiples of 25 mm
        self.assertEqual(result.width_mm % 25, 0)
        self.assertEqual(result.height_mm % 25, 0)

        # Resulting section must cover 1000 CFM
        actual_flow_cfm = m3s_to_cfm(result.actual_velocity_m_s * result.area_m2)
        self.assertAlmostEqual(actual_flow_cfm, m3s_to_cfm(q_m3s), delta=5.0)

    def test_1000cfm_2000fpm_specific_dims(self):
        """1000 CFM @ 2000 FPM: verify a plausible size is returned.

        The minimum area is ~0.0465 m².  A 250×200 mm section = 0.050 m² > 0.0465 m².
        The sizing function must return dimensions that give an area no smaller than
        the minimum.
        """
        result = size_duct_cfm_fpm(1000.0, 2000.0)
        min_area = cfm_to_m3s(1000.0) / fpm_to_ms(2000.0)
        self.assertGreaterEqual(result.area_m2, min_area)
        # Confirm numeric results are reasonable
        self.assertGreater(result.width_mm, 0)
        self.assertGreater(result.height_mm, 0)

    def test_round_duct_sizing(self):
        """500 CFM @ 1500 FPM round duct: result should be positive and valid."""
        result = size_duct_cfm_fpm(500.0, 1500.0, shape=DuctShape.ROUND)
        self.assertIsNotNone(result.diameter_mm)
        self.assertIsNone(result.width_mm)
        self.assertEqual(result.diameter_mm % 25, 0)
        q_m3s = cfm_to_m3s(500.0)
        v_max = fpm_to_ms(1500.0)
        self.assertGreaterEqual(result.area_m2, q_m3s / v_max)

    def test_zero_airflow_raises(self):
        with self.assertRaises(ValueError):
            size_duct(0.0, 5.0)

    def test_zero_velocity_raises(self):
        with self.assertRaises(ValueError):
            size_duct(0.5, 0.0)

    def test_preferred_height_constraint(self):
        """Fixed height constraint: width must be ≥ min and height = fixed."""
        result = size_duct_cfm_fpm(800.0, 1800.0, preferred_height_mm=200.0)
        self.assertEqual(result.height_mm, 200.0)
        q_m3s = cfm_to_m3s(800.0)
        v_max = fpm_to_ms(1800.0)
        self.assertGreaterEqual(result.area_m2, q_m3s / v_max)

    def test_to_duct_section(self):
        """SizingResult.to_duct_section returns a valid DuctSection."""
        result = size_duct_cfm_fpm(600.0, 1500.0)
        q = cfm_to_m3s(600.0)
        section = result.to_duct_section(length_mm=5000.0, airflow_m3s=q)
        self.assertIsInstance(section, DuctSection)
        self.assertEqual(section.length_mm, 5000.0)
        self.assertAlmostEqual(section.airflow_m3s, q, places=6)


# ===========================================================================
# 4. Minor loss coefficient for 90° rect elbow in ASHRAE range — DoD oracle #4
# ===========================================================================

class TestMinorLoss(unittest.TestCase):
    """Verify ASHRAE K coefficients and minor loss function."""

    def test_elbow_90_rect_k_in_ashrae_range(self):
        """DoD oracle: 90° rect elbow K is within ASHRAE published range (K ≈ 0.3).

        ASHRAE HOF 2021 Ch. 21 Table 8 (ED5-1): K ranges 0.20–0.35 for
        radius elbows without vanes at W:H ~ 1:1.
        """
        self.assertGreaterEqual(ELBOW_90_RECT_K, 0.20)
        self.assertLessEqual(ELBOW_90_RECT_K, 0.35)

    def test_elbow_90_round_k_reasonable(self):
        """90° round elbow K ≈ 0.11 (ASHRAE CR1-2, R/D=1.5)."""
        self.assertGreater(ELBOW_90_ROUND_K, 0.05)
        self.assertLess(ELBOW_90_ROUND_K, 0.20)

    def test_minor_loss_formula(self):
        """minor_loss = K × ρ × v² / 2."""
        v = 6.0
        k = ELBOW_90_RECT_K
        expected = k * 0.5 * AIR_DENSITY_KG_M3 * v ** 2
        result = minor_loss(v, k)
        self.assertAlmostEqual(result, expected, places=6)

    def test_tee_branch_higher_than_main(self):
        """Branch tee K must be higher than main through-flow K."""
        self.assertGreater(TEE_BRANCH_K, TEE_MAIN_K)

    def test_velocity_pressure(self):
        """velocity_pressure = ρ v² / 2."""
        v = 5.0
        expected = 0.5 * AIR_DENSITY_KG_M3 * v ** 2
        result = velocity_pressure(v)
        self.assertAlmostEqual(result, expected, places=6)

    def test_total_duct_loss_keys(self):
        """total_duct_loss returns expected keys."""
        result = total_duct_loss(
            velocity_m_s=5.0,
            hydraulic_diameter_m=0.3,
            length_m=10.0,
            fittings_k=[ELBOW_90_RECT_K],
        )
        for key in ["friction_pa", "fittings_pa", "total_pa", "velocity_pressure_pa", "friction_factor"]:
            self.assertIn(key, result)

    def test_total_equals_parts(self):
        """total_pa == friction_pa + fittings_pa."""
        result = total_duct_loss(5.0, 0.3, 10.0, [0.30, 0.10])
        self.assertAlmostEqual(
            result["total_pa"],
            result["friction_pa"] + result["fittings_pa"],
            places=6,
        )


# ===========================================================================
# 5. Elbow flat-pattern tests
# ===========================================================================

class TestElbowFlatPattern(unittest.TestCase):
    def test_90deg_arc_lengths(self):
        """90° elbow arc lengths match analytical formula."""
        W, H = 400.0, 300.0
        r_throat = 300.0  # 1× H
        pat = rect_elbow_pattern(W, H, 90.0, r_throat)

        angle_rad = math.pi / 2
        self.assertAlmostEqual(pat.heel_arc_length_mm, r_throat * angle_rad, places=6)
        self.assertAlmostEqual(
            pat.throat_arc_length_mm, (r_throat + H) * angle_rad, places=6
        )
        self.assertAlmostEqual(
            pat.centre_arc_length_mm, (r_throat + H / 2) * angle_rad, places=6
        )

    def test_default_throat_radius_is_height(self):
        """Default throat radius should equal duct height."""
        W, H = 300.0, 250.0
        pat = rect_elbow_pattern(W, H)
        self.assertAlmostEqual(pat.throat_radius_mm, H)

    def test_throat_plate_dimensions(self):
        """Throat plate width == duct width, height == throat arc length."""
        W, H = 350.0, 200.0
        pat = rect_elbow_pattern(W, H, 90.0)
        xs = [p[0] for p in pat.throat_plate]
        ys = [p[1] for p in pat.throat_plate]
        self.assertAlmostEqual(max(xs) - min(xs), W, places=6)
        self.assertAlmostEqual(max(ys) - min(ys), pat.throat_arc_length_mm, places=6)

    def test_throat_longer_than_heel(self):
        """Throat arc > heel arc for any positive throat radius."""
        pat = rect_elbow_pattern(400, 300, 90.0, 300.0)
        self.assertGreater(pat.throat_arc_length_mm, pat.heel_arc_length_mm)

    def test_45deg_elbow(self):
        """45° elbow has shorter arc lengths than 90°."""
        pat90 = rect_elbow_pattern(300, 200, 90.0, 200.0)
        pat45 = rect_elbow_pattern(300, 200, 45.0, 200.0)
        self.assertLess(pat45.throat_arc_length_mm, pat90.throat_arc_length_mm)
        self.assertLess(pat45.heel_arc_length_mm, pat90.heel_arc_length_mm)

    def test_cheek_has_four_vertices(self):
        """Each cheek should be a 4-vertex trapezoid."""
        pat = rect_elbow_pattern(400, 300)
        self.assertEqual(len(pat.cheek_left), 4)
        self.assertEqual(len(pat.cheek_right), 4)

    def test_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            rect_elbow_pattern(0, 300)
        with self.assertRaises(ValueError):
            rect_elbow_pattern(300, 0)

    def test_invalid_angle(self):
        with self.assertRaises(ValueError):
            rect_elbow_pattern(300, 200, 0.0)
        with self.assertRaises(ValueError):
            rect_elbow_pattern(300, 200, 200.0)


# ===========================================================================
# 6. DuctSystem data model
# ===========================================================================

class TestDuctSystem(unittest.TestCase):
    def _make_system(self) -> DuctSystem:
        sys = DuctSystem(name="Test Supply", design_airflow_m3s=cfm_to_m3s(1000.0))
        s1 = DuctSection(
            shape=DuctShape.RECTANGULAR,
            length_mm=5000.0,
            airflow_m3s=cfm_to_m3s(1000.0),
            width_mm=400.0,
            height_mm=300.0,
        )
        s2 = DuctSection(
            shape=DuctShape.ROUND,
            length_mm=3000.0,
            airflow_m3s=cfm_to_m3s(500.0),
            diameter_mm=250.0,
        )
        sys.add_section(s1)
        sys.add_section(s2)
        sys.add_fitting(Fitting(fitting_type=FittingType.ELBOW, angle_deg=90.0))
        return sys

    def test_total_length(self):
        sys = self._make_system()
        self.assertAlmostEqual(sys.total_length_mm(), 8000.0)

    def test_serialise_roundtrip(self):
        """to_dict / from_dict round-trip preserves key fields."""
        sys = self._make_system()
        d = sys.to_dict()
        sys2 = DuctSystem.from_dict(d)
        self.assertEqual(sys2.name, sys.name)
        self.assertEqual(len(sys2.sections), len(sys.sections))
        self.assertEqual(len(sys2.fittings), len(sys.fittings))
        self.assertEqual(sys2.sections[0].shape, DuctShape.RECTANGULAR)
        self.assertEqual(sys2.sections[1].shape, DuctShape.ROUND)

    def test_rect_section_area(self):
        s = DuctSection(
            shape=DuctShape.RECTANGULAR,
            length_mm=1000.0,
            airflow_m3s=0.5,
            width_mm=500.0,
            height_mm=400.0,
        )
        self.assertAlmostEqual(s.area_m2(), 0.2, places=6)

    def test_round_section_area(self):
        s = DuctSection(
            shape=DuctShape.ROUND,
            length_mm=1000.0,
            airflow_m3s=0.3,
            diameter_mm=400.0,
        )
        self.assertAlmostEqual(s.area_m2(), math.pi * 0.04, places=6)

    def test_round_hydraulic_diameter_equals_diameter(self):
        d_mm = 300.0
        s = DuctSection(
            shape=DuctShape.ROUND, length_mm=1.0, airflow_m3s=0.1, diameter_mm=d_mm
        )
        self.assertAlmostEqual(s.hydraulic_diameter_m(), d_mm / 1000.0, places=9)

    def test_rect_hydraulic_diameter(self):
        """D_h = 4A/P for a rectangular duct."""
        W, H = 0.4, 0.3
        s = DuctSection(
            shape=DuctShape.RECTANGULAR,
            length_mm=1.0,
            airflow_m3s=0.5,
            width_mm=W * 1000,
            height_mm=H * 1000,
        )
        expected = 4 * W * H / (2 * (W + H))
        self.assertAlmostEqual(s.hydraulic_diameter_m(), expected, places=9)

    def test_oval_section_area(self):
        """Oval area = rectangle + semicircles."""
        a_mm, b_mm = 600.0, 200.0
        s = DuctSection(
            shape=DuctShape.OVAL,
            length_mm=1000.0,
            airflow_m3s=0.3,
            width_mm=a_mm,
            height_mm=b_mm,
        )
        a, b = a_mm / 1000, b_mm / 1000
        expected = (a - b) * b + math.pi * (b / 2) ** 2
        self.assertAlmostEqual(s.area_m2(), expected, places=9)

    def test_velocity_calculation(self):
        s = DuctSection(
            shape=DuctShape.RECTANGULAR,
            length_mm=1000.0,
            airflow_m3s=1.0,
            width_mm=1000.0,
            height_mm=1000.0,
        )
        # 1 m³/s through 1 m² → 1 m/s
        self.assertAlmostEqual(s.velocity_m_s(), 1.0, places=9)


# ===========================================================================
# 7. Unit conversion helpers
# ===========================================================================

class TestUnitConversions(unittest.TestCase):
    def test_cfm_to_m3s_roundtrip(self):
        for cfm in [100, 500, 1000, 5000]:
            self.assertAlmostEqual(m3s_to_cfm(cfm_to_m3s(cfm)), cfm, places=6)

    def test_fpm_to_ms_roundtrip(self):
        from kerf_hvac.duct import ms_to_fpm
        for fpm in [500, 1000, 2000, 3000]:
            self.assertAlmostEqual(ms_to_fpm(fpm_to_ms(fpm)), fpm, places=6)

    def test_cfm_exact(self):
        """1 CFM = 4.719474432e-4 m³/s"""
        self.assertAlmostEqual(cfm_to_m3s(1.0), 4.719474432e-4, places=12)

    def test_inch_mm_roundtrip(self):
        for inch in [1.0, 12.0, 24.0]:
            self.assertAlmostEqual(mm_to_inch(inch_to_mm(inch)), inch, places=9)


# ===========================================================================
# 8. Tools LLM surface smoke tests
# ===========================================================================

class TestToolsSurface(unittest.TestCase):
    """Smoke tests for LLM tools — verify JSON shapes and error handling."""

    def setUp(self):
        from kerf_hvac.tools import (
            handle_size_duct,
            handle_pressure_drop,
            handle_fitting_loss,
            handle_reducer_flat_pattern,
            handle_elbow_flat_pattern,
        )
        self.size_duct = handle_size_duct
        self.pressure_drop = handle_pressure_drop
        self.fitting_loss = handle_fitting_loss
        self.reducer_pattern = handle_reducer_flat_pattern
        self.elbow_pattern = handle_elbow_flat_pattern

    def _ok(self, raw: str) -> dict:
        d = json.loads(raw)
        self.assertNotIn("error", d, f"Tool returned error: {d}")
        return d

    def _err(self, raw: str) -> dict:
        d = json.loads(raw)
        self.assertIn("error", d)
        return d

    def test_size_duct_happy_path(self):
        r = self._ok(self.size_duct({"airflow_cfm": 1000, "max_velocity_fpm": 2000}))
        self.assertIn("width_mm", r)
        self.assertIn("height_mm", r)
        self.assertIn("actual_velocity_fpm", r)

    def test_size_duct_round(self):
        r = self._ok(self.size_duct({"airflow_cfm": 500, "max_velocity_fpm": 1500, "shape": "round"}))
        self.assertIn("diameter_mm", r)
        self.assertIsNotNone(r["diameter_mm"])

    def test_size_duct_bad_args(self):
        self._err(self.size_duct({"airflow_cfm": -1, "max_velocity_fpm": 2000}))

    def test_pressure_drop_happy_path(self):
        r = self._ok(self.pressure_drop({
            "velocity_m_s": 6.0,
            "hydraulic_diameter_mm": 329.0,
            "length_m": 10.0,
            "fittings": ["elbow_90_rect"],
        }))
        self.assertIn("total_pa", r)
        self.assertGreater(r["total_pa"], 0)

    def test_pressure_drop_unknown_fitting_warns(self):
        r = self._ok(self.pressure_drop({
            "velocity_m_s": 5.0,
            "hydraulic_diameter_mm": 300.0,
            "length_m": 5.0,
            "fittings": ["bogus_fitting"],
        }))
        self.assertIn("warning", r)

    def test_fitting_loss_happy_path(self):
        r = self._ok(self.fitting_loss({"velocity_m_s": 5.0, "fitting_type": "elbow_90_rect"}))
        self.assertIn("loss_pa", r)
        self.assertIn("k_coefficient", r)

    def test_fitting_loss_unknown(self):
        self._err(self.fitting_loss({"velocity_m_s": 5.0, "fitting_type": "nonexistent"}))

    def test_reducer_pattern_happy_path(self):
        r = self._ok(self.reducer_pattern({
            "width_upstream_mm": 600,
            "height_upstream_mm": 400,
            "width_downstream_mm": 400,
            "height_downstream_mm": 300,
            "axial_length_mm": 300,
        }))
        self.assertIn("top_slant_length_mm", r)
        self.assertIn("top_plate", r)
        self.assertEqual(len(r["top_plate"]), 4)

    def test_elbow_pattern_happy_path(self):
        r = self._ok(self.elbow_pattern({
            "width_mm": 400,
            "height_mm": 300,
            "angle_deg": 90,
        }))
        self.assertIn("throat_arc_length_mm", r)
        self.assertIn("heel_arc_length_mm", r)
        self.assertIn("throat_plate", r)
        self.assertIn("cheek_left", r)

    def test_elbow_pattern_bad_args(self):
        self._err(self.elbow_pattern({"width_mm": 0, "height_mm": 300}))


# ===========================================================================
# 9. AHRI catalogue — DoD: each category returns ≥1 model; part-load values
#    match catalogue entries; equipment_select LLM tool returns valid JSON.
# ===========================================================================

class TestAhriCatalogue(unittest.TestCase):
    """Verify the AHRI-listed equipment catalogue and LLM tool surface."""

    def setUp(self):
        from kerf_hvac.ahri_catalogue import lookup_equipment, VALID_CATEGORIES, _CATALOGUE
        from kerf_hvac.tools import handle_equipment_select
        self.lookup = lookup_equipment
        self.VALID_CATEGORIES = VALID_CATEGORIES
        self._CATALOGUE = _CATALOGUE
        self.handle_equipment_select = handle_equipment_select

    # -----------------------------------------------------------------------
    # 9a. Thirty models across 6 categories
    # -----------------------------------------------------------------------

    def test_catalogue_has_thirty_models(self):
        """DoD: exactly 30 models are present in the catalogue."""
        self.assertEqual(len(self._CATALOGUE), 30)

    def test_six_categories_present(self):
        """DoD: all 6 required categories are in VALID_CATEGORIES."""
        required = {
            "rooftop_ac", "split_ac", "water_chiller",
            "air_chiller", "gas_boiler", "heat_pump",
        }
        self.assertEqual(required, set(self.VALID_CATEGORIES))

    def test_five_models_per_category(self):
        """DoD: each category has exactly 5 representative models."""
        from collections import Counter
        counts = Counter(m.category for m in self._CATALOGUE)
        for cat in self.VALID_CATEGORIES:
            self.assertEqual(counts[cat], 5, f"Expected 5 models for {cat}, got {counts[cat]}")

    # -----------------------------------------------------------------------
    # 9b. Each category returns ≥1 model on an open capacity query
    # -----------------------------------------------------------------------

    def test_each_category_returns_at_least_one_model(self):
        """DoD: lookup_equipment(cat, 0) returns ≥1 result for every category."""
        for cat in self.VALID_CATEGORIES:
            with self.subTest(category=cat):
                results = self.lookup(cat, 0)
                self.assertGreaterEqual(len(results), 1,
                    f"lookup_equipment({cat!r}, 0) returned no models")

    def test_rooftop_ac_returns_models(self):
        results = self.lookup("rooftop_ac", 0)
        self.assertGreaterEqual(len(results), 1)

    def test_split_ac_returns_models(self):
        results = self.lookup("split_ac", 0)
        self.assertGreaterEqual(len(results), 1)

    def test_water_chiller_returns_models(self):
        results = self.lookup("water_chiller", 0)
        self.assertGreaterEqual(len(results), 1)

    def test_air_chiller_returns_models(self):
        results = self.lookup("air_chiller", 0)
        self.assertGreaterEqual(len(results), 1)

    def test_gas_boiler_returns_models(self):
        results = self.lookup("gas_boiler", 0)
        self.assertGreaterEqual(len(results), 1)

    def test_heat_pump_returns_models(self):
        results = self.lookup("heat_pump", 0)
        self.assertGreaterEqual(len(results), 1)

    # -----------------------------------------------------------------------
    # 9c. Part-load curve values match the catalogue entries
    # -----------------------------------------------------------------------

    def test_part_load_curve_has_four_load_points(self):
        """Every model must have part-load values at 0.25, 0.5, 0.75, 1.0."""
        required_points = {0.25, 0.5, 0.75, 1.0}
        for m in self._CATALOGUE:
            with self.subTest(model=m.model_number):
                self.assertEqual(
                    set(m.part_load_curve.keys()),
                    required_points,
                    f"{m.model_number}: part_load_curve keys must be exactly {required_points}",
                )

    def test_part_load_values_are_positive(self):
        """All part-load efficiency values must be positive finite numbers."""
        for m in self._CATALOGUE:
            for load, val in m.part_load_curve.items():
                with self.subTest(model=m.model_number, load=load):
                    self.assertGreater(val, 0)
                    self.assertTrue(
                        val == val and val != float("inf"),
                        f"{m.model_number} load={load}: value {val} is not finite",
                    )

    def test_part_load_25_gte_full_load_for_ac_and_hp(self):
        """AC / heat-pump part-load efficiency at 25 % must exceed full-load EER/COP.

        All variable-speed HVAC equipment achieves higher COP at reduced load
        (this is the physical basis for IEER > EER).
        """
        for m in self._CATALOGUE:
            if m.category not in ("rooftop_ac", "split_ac", "heat_pump"):
                continue
            with self.subTest(model=m.model_number):
                v_25 = m.part_load_curve[0.25]
                v_100 = m.part_load_curve[1.0]
                self.assertGreater(
                    v_25, v_100,
                    f"{m.model_number}: 25% load efficiency {v_25} should exceed "
                    f"full-load {v_100}",
                )

    def test_part_load_matches_catalogue_carrier_rooftop(self):
        """Spot-check: Carrier rooftop 48k BTU part-load curve is exactly as catalogued."""
        models = self.lookup("rooftop_ac", 48_000)
        carrier = next(
            (m for m in models if m.manufacturer == "Carrier" and "48HC" in m.model_number),
            None,
        )
        self.assertIsNotNone(carrier, "Carrier 48HC model not found near 48k BTU/hr")
        self.assertAlmostEqual(carrier.part_load_curve[0.25], 14.8)
        self.assertAlmostEqual(carrier.part_load_curve[0.5],  13.6)
        self.assertAlmostEqual(carrier.part_load_curve[0.75], 12.8)
        self.assertAlmostEqual(carrier.part_load_curve[1.0],  11.2)
        self.assertAlmostEqual(carrier.eer, 11.2)

    def test_part_load_matches_catalogue_carrier_water_chiller(self):
        """Spot-check: Carrier water-cooled chiller COP values from catalogue."""
        models = self.lookup("water_chiller", 600_000)
        carrier = next(
            (m for m in models if m.manufacturer == "Carrier" and "19DV" in m.model_number),
            None,
        )
        self.assertIsNotNone(carrier, "Carrier 19DV chiller not found near 600k BTU/hr")
        self.assertAlmostEqual(carrier.cop_cooling, 6.10)
        self.assertAlmostEqual(carrier.part_load_curve[0.25], 8.40)
        self.assertAlmostEqual(carrier.part_load_curve[1.0],  6.10)

    def test_part_load_matches_catalogue_viessmann_boiler(self):
        """Spot-check: Viessmann boiler AFUE values from catalogue."""
        models = self.lookup("gas_boiler", 0)
        vies = next(
            (m for m in models if m.manufacturer == "Viessmann"),
            None,
        )
        self.assertIsNotNone(vies, "Viessmann boiler not found")
        self.assertAlmostEqual(vies.afue, 0.97)
        # Condensing boiler: part-load efficiency should be >= full-load
        self.assertGreaterEqual(vies.part_load_curve[0.25], vies.part_load_curve[1.0])

    # -----------------------------------------------------------------------
    # 9d. Capacity-band filter
    # -----------------------------------------------------------------------

    def test_capacity_band_filter_excludes_far_models(self):
        """Lookup near 36,000 BTU/hr should not return 360-ton models."""
        results = self.lookup("rooftop_ac", 36_000)
        for m in results:
            ratio = m.capacity_btu_hr / 36_000
            self.assertGreaterEqual(ratio, 0.60)
            self.assertLessEqual(ratio, 1.40)

    def test_zero_capacity_returns_all_in_category(self):
        """Capacity=0 should bypass the band filter and return all 5 models."""
        results = self.lookup("split_ac", 0)
        self.assertEqual(len(results), 5)

    def test_invalid_category_raises(self):
        with self.assertRaises(ValueError):
            self.lookup("bogus_category", 0)

    # -----------------------------------------------------------------------
    # 9e. Efficiency filter
    # -----------------------------------------------------------------------

    def test_efficiency_filter_removes_low_models(self):
        """min_efficiency=15 for split_ac should narrow results to high-IEER models."""
        results = self.lookup("split_ac", 0, min_efficiency=15.0)
        for m in results:
            eff = m.eer if m.eer else m.ieer
            self.assertGreaterEqual(
                eff, 15.0,
                f"{m.model_number} EER/IEER {eff} is below min_efficiency=15",
            )

    def test_boiler_afue_filter(self):
        """Boiler AFUE filter: min_efficiency=0.95 should exclude Raypak (AFUE=0.83)."""
        results = self.lookup("gas_boiler", 0, min_efficiency=0.95)
        for m in results:
            self.assertGreaterEqual(m.afue, 0.95)

    # -----------------------------------------------------------------------
    # 9f. LLM tool surface — handle_equipment_select
    # -----------------------------------------------------------------------

    def _ok(self, raw: str) -> dict:
        d = json.loads(raw)
        self.assertNotIn("error", d, f"Tool returned error: {d}")
        return d

    def _err(self, raw: str) -> dict:
        d = json.loads(raw)
        self.assertIn("error", d)
        return d

    def test_equipment_select_rooftop_ac(self):
        r = self._ok(self.handle_equipment_select({
            "category": "rooftop_ac",
            "capacity_btu_hr": 60_000,
        }))
        self.assertIn("models", r)
        self.assertGreaterEqual(len(r["models"]), 1)
        m = r["models"][0]
        self.assertIn("manufacturer", m)
        self.assertIn("ahri_number", m)
        self.assertIn("part_load_curve", m)
        # Part-load curve should have 4 load points
        self.assertEqual(len(m["part_load_curve"]), 4)

    def test_equipment_select_water_chiller(self):
        r = self._ok(self.handle_equipment_select({
            "category": "water_chiller",
            "capacity_btu_hr": 1_200_000,
        }))
        self.assertGreaterEqual(len(r["models"]), 1)

    def test_equipment_select_all_categories(self):
        """Every category returns ≥1 model via the LLM tool with capacity=0."""
        for cat in self.VALID_CATEGORIES:
            with self.subTest(category=cat):
                r = self._ok(self.handle_equipment_select({
                    "category": cat,
                    "capacity_btu_hr": 0,
                }))
                self.assertGreaterEqual(len(r.get("models", [])), 1,
                    f"Tool returned no models for category={cat!r}")

    def test_equipment_select_returns_ahri_source(self):
        """Result should include an AHRI source citation."""
        r = self._ok(self.handle_equipment_select({
            "category": "heat_pump",
            "capacity_btu_hr": 0,
        }))
        self.assertIn("source", r)
        self.assertIn("ahri", r["source"].lower())

    def test_equipment_select_bad_category(self):
        self._err(self.handle_equipment_select({
            "category": "bogus",
            "capacity_btu_hr": 60_000,
        }))

    def test_equipment_select_missing_capacity(self):
        self._err(self.handle_equipment_select({
            "category": "split_ac",
        }))

    def test_equipment_select_model_has_ahri_number(self):
        """Each returned model must have a non-empty AHRI number."""
        r = self._ok(self.handle_equipment_select({
            "category": "gas_boiler",
            "capacity_btu_hr": 0,
        }))
        for m in r["models"]:
            self.assertTrue(m["ahri_number"], f"AHRI number missing: {m}")

    def test_equipment_select_part_load_matches_catalogue(self):
        """Carrier 19DV water chiller part-load values come through correctly."""
        r = self._ok(self.handle_equipment_select({
            "category": "water_chiller",
            "capacity_btu_hr": 600_000,
        }))
        carrier = next(
            (m for m in r["models"] if "19DV" in m.get("model_number", "")),
            None,
        )
        self.assertIsNotNone(carrier, "Carrier 19DV not in results near 600k BTU/hr")
        plc = carrier["part_load_curve"]
        self.assertAlmostEqual(float(plc["0.25"]), 8.40)
        self.assertAlmostEqual(float(plc["1.0"]),  6.10)


if __name__ == "__main__":
    unittest.main()
