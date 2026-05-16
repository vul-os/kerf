"""
Tests for kerf_cad_core.jewelry.hollowing

Pure-Python: no OCC, no database, no project context required.

Covers (≥ 30 tests):
  - Weight conservation:  (V_solid − V_cavity) × ρ ≈ target_weight
  - hollow_for_weight: required cavity, feasibility, shape recommendation
  - Min-wall feasibility check (infeasible when target too low / wall too thick)
  - lattice_infill: mass scales with relative_density, modulus Gibson-Ashby
  - lattice_infill: all three topologies (gyroid, cubic, octet_truss)
  - lattice_infill: relative_density mass scaling (linear in ρ_rel)
  - lattice_infill: Gibson-Ashby modulus scaling (E ∝ ρ^n)
  - boolean_cleanup_holes: hole count monotonic in cavity volume
  - boolean_cleanup_holes: minimum hole count enforced
  - weight_reduction_report: structural-integrity flag > 60% bbox
  - weight_reduction_report: cast_time_change_pct tracks weight_saved_pct
  - alloy lookup covers gold / silver / platinum / palladium / base metals
  - warning fires when min_wall < 0.5 mm
  - bad inputs return ok=False (never raise)
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.jewelry.hollowing import (
    _GA_PARAMS,
    _HOLE_DIA_MAX_MM,
    _HOLE_DIA_MIN_MM,
    _STRUCTURAL_WARN_RATIO,
    boolean_cleanup_holes,
    hollow_for_weight,
    lattice_infill,
    weight_reduction_report,
)
from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3, MM3_PER_CM3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weight(volume_mm3: float, alloy: str) -> float:
    """Return grams for a solid of given volume and alloy."""
    rho = METAL_DENSITY_G_CM3[alloy]
    return rho * (volume_mm3 / MM3_PER_CM3)


# ---------------------------------------------------------------------------
# hollow_for_weight
# ---------------------------------------------------------------------------

class TestHollowForWeight:

    def test_weight_conservation_18k(self):
        """(V_solid − V_cavity) × ρ should equal target_weight within 0.1%."""
        vol = 2000.0   # mm³
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        target_g = solid_g * 0.60   # aim for 60% of original weight
        r = hollow_for_weight(vol, target_g, alloy)
        assert r["ok"] is True
        v_cav = r["required_cavity_mm3"]
        v_remain = vol - v_cav
        actual_g = rho * (v_remain / MM3_PER_CM3)
        assert abs(actual_g - target_g) / target_g < 1e-6

    def test_weight_conservation_sterling(self):
        """Conservation test with sterling_925."""
        vol = 500.0
        alloy = "sterling_925"
        rho = METAL_DENSITY_G_CM3[alloy]
        target_g = rho * (vol / MM3_PER_CM3) * 0.50
        r = hollow_for_weight(vol, target_g, alloy)
        assert r["ok"] is True
        v_cav = r["required_cavity_mm3"]
        restored_g = rho * ((vol - v_cav) / MM3_PER_CM3)
        assert abs(restored_g - target_g) < 1e-6 * target_g + 1e-9

    def test_weight_conservation_platinum(self):
        """Conservation holds for platinum_950."""
        vol = 3000.0
        alloy = "platinum_950"
        rho = METAL_DENSITY_G_CM3[alloy]
        target_g = rho * (vol / MM3_PER_CM3) * 0.40
        r = hollow_for_weight(vol, target_g, alloy)
        assert r["ok"] is True
        v_remain = vol - r["required_cavity_mm3"]
        assert abs(rho * (v_remain / MM3_PER_CM3) - target_g) < 1e-9 * max(target_g, 1.0)

    def test_solid_weight_reported(self):
        """solid_weight_g must equal ρ × V_solid."""
        vol = 1000.0
        alloy = "14k_white"
        rho = METAL_DENSITY_G_CM3[alloy]
        expected = rho * (vol / MM3_PER_CM3)
        r = hollow_for_weight(vol, expected * 0.70, alloy)
        assert r["ok"] is True
        assert abs(r["solid_weight_g"] - expected) < 1e-9

    def test_feasible_when_target_achievable(self):
        """Large volume, modest target → feasible."""
        vol = 5000.0
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        r = hollow_for_weight(vol, solid_g * 0.80, alloy, min_wall_mm=1.0)
        assert r["ok"] is True
        assert r["feasible"] is True

    def test_infeasible_when_wall_too_thick(self):
        """Tiny piece + very thick wall → infeasible."""
        vol = 50.0    # very small piece (5 mm diameter sphere ≈ 65 mm³)
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        # want only 5% of weight remaining — cavity would exceed max
        r = hollow_for_weight(vol, solid_g * 0.05, alloy, min_wall_mm=3.0)
        assert r["ok"] is True
        assert r["feasible"] is False

    def test_cavity_shape_ellipsoid(self):
        """< 30% hollowing → ellipsoid."""
        vol = 10000.0
        alloy = "14k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        r = hollow_for_weight(vol, solid_g * 0.85, alloy)   # 15% removal
        assert r["ok"] is True
        assert r["cavity_shape"] == "ellipsoid"

    def test_cavity_shape_prism(self):
        """30–60% hollowing → prism."""
        vol = 10000.0
        alloy = "14k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        r = hollow_for_weight(vol, solid_g * 0.55, alloy)   # 45% removal
        assert r["ok"] is True
        assert r["cavity_shape"] == "prism"

    def test_cavity_shape_lattice(self):
        """≥ 60% hollowing → lattice_infill."""
        vol = 10000.0
        alloy = "14k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        r = hollow_for_weight(vol, solid_g * 0.30, alloy)   # 70% removal
        assert r["ok"] is True
        assert r["cavity_shape"] == "lattice_infill"

    def test_weight_saved_pct(self):
        """weight_saved_pct ≈ 1 − target/solid ratio."""
        vol = 2000.0
        alloy = "18k_rose"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        target_g = solid_g * 0.70
        r = hollow_for_weight(vol, target_g, alloy)
        assert r["ok"] is True
        expected_pct = (solid_g - target_g) / solid_g * 100.0
        assert abs(r["weight_saved_pct"] - expected_pct) < 1e-3

    def test_warning_on_thin_wall(self):
        """Warning fires when min_wall < 0.5 mm."""
        vol = 2000.0
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        r = hollow_for_weight(vol, solid_g * 0.60, alloy, min_wall_mm=0.3)
        assert r["ok"] is True
        assert any("0.5 mm" in w for w in r["warnings"])

    def test_alloy_lookup_titanium(self):
        """titanium alloy resolves correctly."""
        vol = 1000.0
        alloy = "titanium"
        rho = METAL_DENSITY_G_CM3[alloy]
        target_g = rho * (vol / MM3_PER_CM3) * 0.70
        r = hollow_for_weight(vol, target_g, alloy)
        assert r["ok"] is True
        assert r["density_g_cm3"] == rho

    def test_alloy_lookup_bronze(self):
        """bronze alloy resolves correctly."""
        vol = 800.0
        alloy = "bronze"
        rho = METAL_DENSITY_G_CM3[alloy]
        target_g = rho * (vol / MM3_PER_CM3) * 0.60
        r = hollow_for_weight(vol, target_g, alloy)
        assert r["ok"] is True

    def test_explicit_density_override(self):
        """density_g_cm3 override bypasses alloy lookup."""
        vol = 1000.0
        rho = 15.0
        target_g = rho * (vol / MM3_PER_CM3) * 0.65
        r = hollow_for_weight(vol, target_g, "ignored_alloy", density_g_cm3=rho)
        assert r["ok"] is True
        assert r["density_g_cm3"] == 15.0
        assert r["alloy"] == "custom"

    def test_target_equal_or_greater_than_solid_is_error(self):
        """target_weight_g >= solid_weight_g → ok=False."""
        vol = 1000.0
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        r = hollow_for_weight(vol, solid_g, alloy)
        assert r["ok"] is False

    def test_negative_volume_is_error(self):
        """Negative solid_volume_mm3 → ok=False."""
        r = hollow_for_weight(-100.0, 5.0, "18k_yellow")
        assert r["ok"] is False

    def test_unknown_alloy_is_error(self):
        """Unknown alloy key → ok=False."""
        r = hollow_for_weight(1000.0, 3.0, "unobtainium_99k")
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# lattice_infill
# ---------------------------------------------------------------------------

class TestLatticeInfill:

    def test_gyroid_mass_scales_linearly_with_density(self):
        """mass ∝ relative_density for fixed volume (ρ_eff = ρ_rel × ρ_solid)."""
        vol = 1000.0
        alloy = "18k_yellow"
        r1 = lattice_infill(vol, 0.20, cell="gyroid", alloy=alloy)
        r2 = lattice_infill(vol, 0.40, cell="gyroid", alloy=alloy)
        assert r1["ok"] is True
        assert r2["ok"] is True
        # mass ratio should equal density ratio (0.40/0.20 = 2.0)
        assert abs(r2["mass_g"] / r1["mass_g"] - 2.0) < 1e-6

    def test_cubic_modulus_linear_in_density(self):
        """For cubic (n=1): E_eff ∝ ρ_rel."""
        vol = 500.0
        alloy = "sterling_925"
        r1 = lattice_infill(vol, 0.30, cell="cubic", alloy=alloy)
        r2 = lattice_infill(vol, 0.60, cell="cubic", alloy=alloy)
        assert r1["ok"] and r2["ok"]
        # n=1 → ratio should equal 0.60/0.30 = 2.0
        ratio = r2["effective_modulus_gpa"] / r1["effective_modulus_gpa"]
        assert abs(ratio - 2.0) < 1e-9

    def test_gyroid_modulus_quadratic_in_density(self):
        """For gyroid (n=2): E_eff ∝ ρ_rel²."""
        vol = 500.0
        alloy = "sterling_925"
        r1 = lattice_infill(vol, 0.20, cell="gyroid", alloy=alloy)
        r2 = lattice_infill(vol, 0.40, cell="gyroid", alloy=alloy)
        assert r1["ok"] and r2["ok"]
        # n=2 → ratio should equal (0.40/0.20)^2 = 4.0
        ratio = r2["effective_modulus_gpa"] / r1["effective_modulus_gpa"]
        assert abs(ratio - 4.0) < 1e-9

    def test_octet_truss_exponent(self):
        """For octet_truss (n=1.5): E_eff ∝ ρ^1.5."""
        vol = 500.0
        alloy = "14k_yellow"
        r1 = lattice_infill(vol, 0.20, cell="octet_truss", alloy=alloy)
        r2 = lattice_infill(vol, 0.40, cell="octet_truss", alloy=alloy)
        assert r1["ok"] and r2["ok"]
        # n=1.5 → ratio = (0.40/0.20)^1.5 = 2^1.5 ≈ 2.8284
        expected = (0.40 / 0.20) ** 1.5
        ratio = r2["effective_modulus_gpa"] / r1["effective_modulus_gpa"]
        # rounding in round() introduces ~1e-7 error; use relative tolerance
        assert abs(ratio - expected) < 1e-5

    def test_ga_params_returned(self):
        """C1 and n_exponent match _GA_PARAMS table."""
        for cell_key, (C1, n) in _GA_PARAMS.items():
            r = lattice_infill(1000.0, 0.30, cell=cell_key, alloy="18k_yellow")
            assert r["ok"] is True, cell_key
            assert r["C1"] == C1, cell_key
            assert r["n_exponent"] == n, cell_key

    def test_relative_stiffness_formula(self):
        """relative_stiffness = E_eff / E_solid (= C1 × ρ_rel^n)."""
        vol = 800.0
        rho_rel = 0.35
        alloy = "platinum_950"
        r = lattice_infill(vol, rho_rel, cell="gyroid", alloy=alloy)
        assert r["ok"] is True
        C1, n = _GA_PARAMS["gyroid"]
        expected_rs = C1 * (rho_rel ** n)
        assert abs(r["relative_stiffness"] - expected_rs) < 1e-9

    def test_mass_equals_rho_eff_times_volume(self):
        """mass_g = ρ_eff × V (with correct unit conversion)."""
        vol = 2000.0
        rho_rel = 0.25
        alloy = "18k_yellow"
        rho_solid = METAL_DENSITY_G_CM3[alloy]
        r = lattice_infill(vol, rho_rel, cell="cubic", alloy=alloy)
        assert r["ok"] is True
        rho_eff = rho_rel * rho_solid
        expected_g = rho_eff * (vol / MM3_PER_CM3)
        assert abs(r["mass_g"] - expected_g) < 1e-9

    def test_low_density_warning(self):
        """relative_density < 0.15 fires a warning."""
        r = lattice_infill(500.0, 0.10, cell="gyroid", alloy="18k_yellow")
        assert r["ok"] is True
        assert any("0.15" in w for w in r["warnings"])

    def test_explicit_modulus_override(self):
        """solid_modulus_gpa override is honoured."""
        r = lattice_infill(500.0, 0.30, cell="cubic",
                           alloy="18k_yellow", solid_modulus_gpa=90.0)
        assert r["ok"] is True
        assert r["solid_modulus_gpa"] == 90.0
        C1, n = _GA_PARAMS["cubic"]
        expected = C1 * (0.30 ** n) * 90.0
        assert abs(r["effective_modulus_gpa"] - expected) < 1e-9

    def test_unknown_cell_is_error(self):
        """Unknown cell topology → ok=False."""
        r = lattice_infill(500.0, 0.30, cell="diamond", alloy="18k_yellow")
        assert r["ok"] is False

    def test_density_out_of_range_is_error(self):
        """relative_density = 0 or >= 1 → ok=False."""
        r_zero = lattice_infill(500.0, 0.0, cell="gyroid", alloy="18k_yellow")
        r_one  = lattice_infill(500.0, 1.0, cell="gyroid", alloy="18k_yellow")
        assert r_zero["ok"] is False
        assert r_one["ok"] is False

    def test_no_alloy_no_density_is_error(self):
        """Neither alloy nor density_g_cm3 → ok=False."""
        r = lattice_infill(500.0, 0.30)
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# boolean_cleanup_holes
# ---------------------------------------------------------------------------

class TestBooleanCleanupHoles:

    def test_minimum_two_holes_always(self):
        """Even a tiny cavity gets at least 2 holes."""
        r = boolean_cleanup_holes(100.0, 5000.0)
        assert r["ok"] is True
        assert r["hole_count"] >= 2

    def test_hole_count_monotonic_in_cavity_volume(self):
        """Larger cavity → hole_count non-decreasing."""
        vols = [1000.0, 5000.0, 10000.0, 25000.0, 50000.0]
        counts = []
        for v in vols:
            r = boolean_cleanup_holes(v, v * 3)
            assert r["ok"] is True
            counts.append(r["hole_count"])
        for i in range(len(counts) - 1):
            assert counts[i] <= counts[i + 1], f"not monotonic at index {i}: {counts}"

    def test_hole_count_rule(self):
        """hole_count = max(2, ceil(cavity_volume / 5000))."""
        for v_cav in (500.0, 5000.0, 10001.0, 25000.0):
            r = boolean_cleanup_holes(v_cav, v_cav * 2)
            expected = max(2, math.ceil(v_cav / 5000.0))
            assert r["hole_count"] == expected, f"v={v_cav}: expected {expected} got {r['hole_count']}"

    def test_hole_diameter_clamped_min(self):
        """Very small cavity → diameter at minimum."""
        r = boolean_cleanup_holes(1.0, 1000.0)
        assert r["ok"] is True
        assert r["hole_diameter_mm"] == _HOLE_DIA_MIN_MM

    def test_hole_diameter_clamped_max(self):
        """Very large cavity → diameter at maximum."""
        # raw = 0.5 × V^(1/3) / 5; want this > 3.0:  V > (3.0×5/0.5)^3 = 27_000_000
        r = boolean_cleanup_holes(50_000_000.0, 200_000_000.0)
        assert r["ok"] is True
        assert r["hole_diameter_mm"] == _HOLE_DIA_MAX_MM

    def test_total_drain_area(self):
        """total_drain_area_mm2 = hole_count × (π/4) × d²."""
        r = boolean_cleanup_holes(3000.0, 10000.0)
        assert r["ok"] is True
        expected = r["hole_count"] * math.pi * (r["hole_diameter_mm"] / 2.0) ** 2
        assert abs(r["total_drain_area_mm2"] - expected) < 1e-3

    def test_cavity_larger_than_piece_is_error(self):
        """cavity_volume >= piece_volume → ok=False."""
        r = boolean_cleanup_holes(1000.0, 800.0)
        assert r["ok"] is False

    def test_negative_cavity_is_error(self):
        """cavity_volume ≤ 0 → ok=False."""
        r = boolean_cleanup_holes(-100.0, 5000.0)
        assert r["ok"] is False

    def test_placement_is_hidden_face_auto(self):
        """placement field is always 'hidden_face_auto'."""
        r = boolean_cleanup_holes(5000.0, 20000.0)
        assert r["ok"] is True
        assert r["placement"] == "hidden_face_auto"


# ---------------------------------------------------------------------------
# weight_reduction_report
# ---------------------------------------------------------------------------

class TestWeightReductionReport:

    def test_weight_conservation(self):
        """hollow_weight_g == (V_solid − V_cav) × ρ."""
        vol = 3000.0
        cav = 1000.0
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        r = weight_reduction_report(vol, cav, alloy)
        assert r["ok"] is True
        expected_hollow_g = rho * ((vol - cav) / MM3_PER_CM3)
        assert abs(r["hollow_weight_g"] - expected_hollow_g) < 1e-9

    def test_weight_saved_pct_accuracy(self):
        """weight_saved_pct = (solid − hollow) / solid × 100."""
        vol = 2000.0
        cav = 800.0
        alloy = "sterling_925"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        hollow_g = rho * ((vol - cav) / MM3_PER_CM3)
        r = weight_reduction_report(vol, cav, alloy)
        assert r["ok"] is True
        expected_pct = (solid_g - hollow_g) / solid_g * 100.0
        assert abs(r["weight_saved_pct"] - expected_pct) < 1e-6

    def test_structural_integrity_ok_below_threshold(self):
        """cavity / bbox = 0.50 → structural_integrity_ok is True."""
        vol = 2000.0
        cav = 500.0
        bbox = cav / 0.50   # cavity is exactly 50% of bbox
        r = weight_reduction_report(vol, cav, "18k_yellow", bbox_volume_mm3=bbox)
        assert r["ok"] is True
        assert r["structural_integrity_ok"] is True

    def test_structural_integrity_flag_above_threshold(self):
        """cavity / bbox > 0.60 → structural_integrity_ok is False, warning fires."""
        vol = 5000.0
        cav = 1000.0
        bbox = cav / 0.70   # cavity is 70% of bbox → above 60% threshold
        r = weight_reduction_report(vol, cav, "18k_yellow", bbox_volume_mm3=bbox)
        assert r["ok"] is True
        assert r["structural_integrity_ok"] is False
        assert len(r["warnings"]) > 0

    def test_structural_integrity_at_threshold_is_ok(self):
        """cavity / bbox exactly 0.60 → structural_integrity_ok is True."""
        vol = 5000.0
        cav = 600.0
        bbox = cav / _STRUCTURAL_WARN_RATIO   # exactly at threshold
        r = weight_reduction_report(vol, cav, "14k_white", bbox_volume_mm3=bbox)
        assert r["ok"] is True
        assert r["structural_integrity_ok"] is True

    def test_cast_time_change_matches_weight_saved(self):
        """cast_time_change_pct ≈ −weight_saved_pct."""
        vol = 3000.0
        cav = 900.0
        r = weight_reduction_report(vol, cav, "platinum_950")
        assert r["ok"] is True
        assert abs(r["cast_time_change_pct"] + r["weight_saved_pct"]) < 1e-6

    def test_no_bbox_returns_none_ratio(self):
        """Without bbox_volume_mm3 the cavity_bbox_ratio is None."""
        r = weight_reduction_report(2000.0, 800.0, "18k_rose")
        assert r["ok"] is True
        assert r["cavity_bbox_ratio"] is None

    def test_cavity_equals_solid_is_error(self):
        """cavity_volume == solid_volume → ok=False."""
        r = weight_reduction_report(1000.0, 1000.0, "18k_yellow")
        assert r["ok"] is False

    def test_negative_cavity_is_error(self):
        """Negative cavity_volume_mm3 → ok=False."""
        r = weight_reduction_report(1000.0, -100.0, "18k_yellow")
        assert r["ok"] is False

    def test_unknown_alloy_is_error(self):
        """Unknown alloy key → ok=False."""
        r = weight_reduction_report(1000.0, 400.0, "vibranium_999")
        assert r["ok"] is False

    def test_explicit_density_override(self):
        """density_g_cm3 override is honoured for alloy='anything'."""
        rho = 12.0
        vol = 1000.0
        cav = 400.0
        r = weight_reduction_report(vol, cav, "anything", density_g_cm3=rho)
        assert r["ok"] is True
        assert r["density_g_cm3"] == rho
        expected_hollow_g = rho * ((vol - cav) / MM3_PER_CM3)
        assert abs(r["hollow_weight_g"] - expected_hollow_g) < 1e-9


# ---------------------------------------------------------------------------
# Cross-function integration
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_hollow_then_report_consistent(self):
        """hollow_for_weight required_cavity feeds weight_reduction_report correctly."""
        vol = 4000.0
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        target_g = solid_g * 0.65

        h = hollow_for_weight(vol, target_g, alloy)
        assert h["ok"] is True
        v_cav = h["required_cavity_mm3"]

        rep = weight_reduction_report(vol, v_cav, alloy)
        assert rep["ok"] is True
        # The hollow_weight_g in the report should equal target_weight_g from hollow
        assert abs(rep["hollow_weight_g"] - target_g) < 1e-3

    def test_lattice_mass_less_than_solid_mass(self):
        """Lattice mass < solid mass for any relative_density < 1."""
        vol = 2000.0
        alloy = "14k_yellow"
        rho_solid = METAL_DENSITY_G_CM3[alloy]
        solid_mass_g = rho_solid * (vol / MM3_PER_CM3)
        for rho_rel in (0.15, 0.30, 0.50, 0.80):
            r = lattice_infill(vol, rho_rel, cell="cubic", alloy=alloy)
            assert r["ok"] is True
            assert r["mass_g"] < solid_mass_g, f"ρ_rel={rho_rel}"

    def test_hollow_and_holes_chain(self):
        """boolean_cleanup_holes accepts required_cavity from hollow_for_weight."""
        vol = 8000.0
        alloy = "14k_rose"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        h = hollow_for_weight(vol, solid_g * 0.55, alloy)
        assert h["ok"] is True
        holes = boolean_cleanup_holes(h["required_cavity_mm3"], vol)
        assert holes["ok"] is True
        assert holes["hole_count"] >= 2
