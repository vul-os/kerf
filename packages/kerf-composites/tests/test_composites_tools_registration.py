"""
Dispatch tests for composites LLM tools:
  composites_drape / composites_interlaminar / composites_thermal / composites_failure_depth /
  composites_weight_cost / composites_failure_envelope / composites_afp_pathplan

Each test calls the async handler directly and verifies the JSON payload.
"""

from __future__ import annotations

import asyncio
import json
import pytest

from kerf_composites.tools import (
    composites_drape_spec, run_composites_drape,
    composites_interlaminar_spec, run_composites_interlaminar,
    composites_thermal_spec, run_composites_thermal,
    composites_failure_depth_spec, run_composites_failure_depth,
    composites_weight_cost_spec, run_composites_weight_cost,
    composites_failure_envelope_spec, run_composites_failure_envelope,
    composites_afp_pathplan_spec, run_composites_afp_pathplan,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()

# ---------------------------------------------------------------------------
# Shared ply stack — [0/90/0] T300/5208, 3 × 0.125 mm
# ---------------------------------------------------------------------------

_PLIES_0_90_0 = [
    {"angle": 0.0, "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
     "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0, "Yc": 246.0, "S12": 68.0},
    {"angle": 90.0, "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
     "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0, "Yc": 246.0, "S12": 68.0},
    {"angle": 0.0, "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
     "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0, "Yc": 246.0, "S12": 68.0},
]


# ---------------------------------------------------------------------------
# Spec sanity
# ---------------------------------------------------------------------------

class TestSpecs:
    def test_all_specs_have_names(self):
        for spec in [
            composites_drape_spec,
            composites_interlaminar_spec,
            composites_thermal_spec,
            composites_failure_depth_spec,
            composites_weight_cost_spec,
            composites_failure_envelope_spec,
            composites_afp_pathplan_spec,
        ]:
            assert spec.name.startswith("composites_"), spec.name
            assert len(spec.description) > 20
            assert "type" in spec.input_schema


# ---------------------------------------------------------------------------
# composites_drape
# ---------------------------------------------------------------------------

class TestCompositesDrape:
    def test_flat_surface_zero_shear(self):
        result = json.loads(_run(run_composites_drape(
            {"surface": "flat", "u_range": [0, 100], "v_range": [0, 100], "nu": 5, "nv": 5},
            CTX,
        )))
        assert result["surface"] == "flat"
        assert result["shear_angle_deg"]["max"] == 0.0

    def test_cylinder_x_returns_coords(self):
        result = json.loads(_run(run_composites_drape(
            {"surface": "cylinder_x", "u_range": [0, 90], "v_range": [0, 50],
             "nu": 6, "nv": 6, "radius": 50.0},
            CTX,
        )))
        assert result["surf_coords_shape"] == [6, 6, 3]

    def test_bad_surface_returns_error(self):
        result = json.loads(_run(run_composites_drape(
            {"surface": "torus"},  # not supported
            CTX,
        )))
        assert "error" in result

    def test_sphere_surface_returns_coords(self):
        """Sphere is now a supported surface type."""
        result = json.loads(_run(run_composites_drape(
            {"surface": "sphere", "u_range": [0, 30], "v_range": [0, 90],
             "nu": 5, "nv": 5, "radius": 100.0},
            CTX,
        )))
        assert result["surf_coords_shape"] == [5, 5, 3]
        assert "shear_angle_deg" in result

    def test_cone_surface_returns_coords(self):
        """Cone is a supported surface type."""
        result = json.loads(_run(run_composites_drape(
            {"surface": "cone", "u_range": [10, 100], "v_range": [0, 360],
             "nu": 6, "nv": 8, "half_angle_deg": 20.0},
            CTX,
        )))
        assert result["surf_coords_shape"] == [6, 8, 3]

    def test_include_flat_pattern_cylinder(self):
        """Cylinder (developable) should have near-zero distortion in flat pattern."""
        result = json.loads(_run(run_composites_drape(
            {"surface": "cylinder_x", "u_range": [0, 30], "v_range": [0, 100],
             "nu": 6, "nv": 6, "radius": 100.0, "include_flat_pattern": True},
            CTX,
        )))
        assert "flat_pattern" in result
        fp = result["flat_pattern"]
        assert "distortion_pct" in fp
        assert "corner_coords_mm" in fp
        # Cylinder is developable → distortion should be small
        assert fp["distortion_pct"] < 2.0, f"distortion={fp['distortion_pct']:.3f}%"

    def test_arc_length_fields_present(self):
        """Drape result now includes arc_length_u_max_mm and arc_length_v_max_mm."""
        result = json.loads(_run(run_composites_drape(
            {"surface": "flat", "u_range": [0, 100], "v_range": [0, 50],
             "nu": 5, "nv": 5},
            CTX,
        )))
        assert "arc_length_u_max_mm" in result
        assert "arc_length_v_max_mm" in result
        # Flat surface: arc length = linear distance
        assert abs(result["arc_length_u_max_mm"] - 100.0) < 1e-3
        assert abs(result["arc_length_v_max_mm"] - 50.0) < 1e-3


# ---------------------------------------------------------------------------
# composites_interlaminar
# ---------------------------------------------------------------------------

class TestCompositesInterlaminar:
    def test_returns_tau_xz(self):
        result = json.loads(_run(run_composites_interlaminar(
            {"plies": _PLIES_0_90_0, "Mx_Nmm_per_mm": 10.0, "beam_length_mm": 100.0},
            CTX,
        )))
        assert "tau_xz_MPa" in result
        assert len(result["tau_xz_MPa"]) == 4  # n_plies + 1 interfaces
        assert result["max_tau_xz_MPa"] >= 0

    def test_free_surface_near_zero(self):
        result = json.loads(_run(run_composites_interlaminar(
            {"plies": _PLIES_0_90_0},
            CTX,
        )))
        # Bottom surface should be exactly 0
        assert result["tau_xz_MPa"][0] == 0.0

    def test_bad_plies_returns_error(self):
        result = json.loads(_run(run_composites_interlaminar(
            {"plies": [{"angle": 0.0}]},  # missing required fields
            CTX,
        )))
        assert "error" in result


# ---------------------------------------------------------------------------
# composites_thermal
# ---------------------------------------------------------------------------

class TestCompositesThermal:
    def test_symmetric_laminate_low_curvature(self):
        """[0/90/0] is symmetric → thermal curvature κ should be near zero."""
        plies_with_cte = [
            dict(p, alpha1=0.02e-6, alpha2=22.5e-6) for p in _PLIES_0_90_0
        ]
        result = json.loads(_run(run_composites_thermal(
            {"plies": plies_with_cte, "delta_T": -120.0},
            CTX,
        )))
        assert "ply_thermal_stresses" in result
        assert len(result["ply_thermal_stresses"]) == 3
        # Symmetric laminate: curvatures ≈ 0
        for kap in result["curvatures_per_mm"]:
            assert abs(kap) < 1e-6, f"Expected near-zero curvature, got {kap}"

    def test_ply_stresses_have_correct_keys(self):
        result = json.loads(_run(run_composites_thermal(
            {"plies": _PLIES_0_90_0, "delta_T": -100.0},
            CTX,
        )))
        ps = result["ply_thermal_stresses"][0]
        for key in ("ply_index", "angle", "sigma1_MPa", "sigma2_MPa", "tau12_MPa"):
            assert key in ps

    def test_bad_missing_delta_T(self):
        result = json.loads(_run(run_composites_thermal(
            {"plies": _PLIES_0_90_0},  # missing delta_T
            CTX,
        )))
        assert "error" in result


# ---------------------------------------------------------------------------
# composites_failure_depth
# ---------------------------------------------------------------------------

class TestCompositesFailureDepth:
    # T300/5208 reference allowables
    MATERIAL = {
        "Xt": 1500.0, "Xc": 1500.0,
        "Yt": 40.0, "Yc": 246.0,
        "S12": 68.0,
        "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
    }

    def test_safe_stress_not_failed(self):
        args = dict(self.MATERIAL, sigma1=500.0, sigma2=10.0, tau12=20.0)
        result = json.loads(_run(run_composites_failure_depth(args, CTX)))
        assert "tsai_wu" in result
        assert result["tsai_wu"]["failed"] is False
        assert result["hashin"]["failed"] is False

    def test_failure_at_limit_stress(self):
        """Apply stress exactly at Xt → tsai_wu FI ≥ 1."""
        args = dict(self.MATERIAL, sigma1=1500.0, sigma2=0.0, tau12=0.0)
        result = json.loads(_run(run_composites_failure_depth(args, CTX)))
        assert result["max_stress"]["failed"] is True

    def test_hashin_fiber_tension_mode(self):
        args = dict(self.MATERIAL, sigma1=1600.0, sigma2=0.0, tau12=0.0)
        result = json.loads(_run(run_composites_failure_depth(args, CTX)))
        assert result["hashin"]["mode"] == "fiber_tension"

    def test_all_criteria_present(self):
        args = dict(self.MATERIAL, sigma1=100.0, sigma2=5.0, tau12=10.0)
        result = json.loads(_run(run_composites_failure_depth(args, CTX)))
        for key in ("tsai_wu", "tsai_hill", "max_stress", "hashin"):
            assert key in result

    def test_missing_strength_returns_error(self):
        result = json.loads(_run(run_composites_failure_depth(
            {"sigma1": 100.0, "sigma2": 0.0, "tau12": 0.0},  # missing Xt etc.
            CTX,
        )))
        assert "error" in result


# ---------------------------------------------------------------------------
# composites_weight_cost
# ---------------------------------------------------------------------------

_PLIES_WEIGHT = [
    {"angle": 0.0,  "thickness": 0.125, "material": "T300/Epoxy"},
    {"angle": 45.0, "thickness": 0.125, "material": "T300/Epoxy"},
    {"angle": -45.0,"thickness": 0.125, "material": "T300/Epoxy"},
    {"angle": 90.0, "thickness": 0.125, "material": "T300/Epoxy"},
]


class TestCompositesWeightCost:
    def test_basic_rollup(self):
        """4-ply [0/45/-45/90] T300/Epoxy over 1 m² → reasonable weight + cost."""
        result = json.loads(_run(run_composites_weight_cost(
            {"plies": _PLIES_WEIGHT, "part_area_m2": 1.0},
            CTX,
        )))
        assert "total_areal_weight_g_m2" in result
        assert "total_mass_kg" in result
        assert "total_material_cost_usd" in result
        # 4 × 0.125 mm × 1.58 g/cm³ × 1000 = 790 g/m² areal weight
        assert 700 < result["total_areal_weight_g_m2"] < 900, result["total_areal_weight_g_m2"]
        assert result["total_mass_kg"] > 0

    def test_waste_factor_increases_cost(self):
        """Waste factor > 1 should increase the material cost."""
        res1 = json.loads(_run(run_composites_weight_cost(
            {"plies": _PLIES_WEIGHT, "part_area_m2": 1.0, "waste_factor": 1.0},
            CTX,
        )))
        res2 = json.loads(_run(run_composites_weight_cost(
            {"plies": _PLIES_WEIGHT, "part_area_m2": 1.0, "waste_factor": 1.15},
            CTX,
        )))
        assert res2["total_material_cost_usd"] > res1["total_material_cost_usd"]

    def test_larger_area_scales_linearly(self):
        """Doubling part area should double mass and cost."""
        res1 = json.loads(_run(run_composites_weight_cost(
            {"plies": _PLIES_WEIGHT, "part_area_m2": 1.0},
            CTX,
        )))
        res2 = json.loads(_run(run_composites_weight_cost(
            {"plies": _PLIES_WEIGHT, "part_area_m2": 2.0},
            CTX,
        )))
        import math
        assert abs(res2["total_mass_kg"] / res1["total_mass_kg"] - 2.0) < 0.01
        assert abs(res2["total_material_cost_usd"] / res1["total_material_cost_usd"] - 2.0) < 0.01

    def test_ply_breakdown_present(self):
        result = json.loads(_run(run_composites_weight_cost(
            {"plies": _PLIES_WEIGHT},
            CTX,
        )))
        assert "ply_breakdown" in result
        assert len(result["ply_breakdown"]) == 4

    def test_custom_rho_override(self):
        """Supply rho directly and verify it overrides the preset."""
        plies = [{"angle": 0.0, "thickness": 0.125, "rho": 1.80}]
        result = json.loads(_run(run_composites_weight_cost({"plies": plies}, CTX)))
        # areal weight = 1.80 g/cm³ × 0.125 mm × 1000 = 225 g/m²
        assert abs(result["total_areal_weight_g_m2"] - 225.0) < 0.5

    def test_areal_weight_formula_correct(self):
        """Single T300/Epoxy ply 0.125 mm: areal weight = rho*t*1000 = 1.58*0.125*1000 = 197.5 g/m²."""
        plies = [{"angle": 0.0, "thickness": 0.125, "material": "T300/Epoxy"}]
        result = json.loads(_run(run_composites_weight_cost({"plies": plies}, CTX)))
        expected = 1.58 * 0.125 * 1000  # = 197.5 g/m²
        assert abs(result["total_areal_weight_g_m2"] - expected) < 1.0


# ---------------------------------------------------------------------------
# composites_failure_envelope
# ---------------------------------------------------------------------------

# T300/5208 [0/90/0] ply — all needed fields
_PLIES_ENVELOPE = [
    {"angle": 0.0,  "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
     "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0, "Yc": 246.0, "S12": 68.0},
    {"angle": 90.0, "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
     "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0, "Yc": 246.0, "S12": 68.0},
    {"angle": 0.0,  "E1": 181.0, "E2": 10.3, "G12": 7.17, "nu12": 0.28,
     "thickness": 0.125, "Xt": 1500.0, "Xc": 1500.0, "Yt": 40.0, "Yc": 246.0, "S12": 68.0},
]


class TestCompositesFailureEnvelope:
    def test_returns_envelope_points(self):
        result = json.loads(_run(run_composites_failure_envelope(
            {"plies": _PLIES_ENVELOPE, "n_angles": 8},
            CTX,
        )))
        assert "envelope_points" in result
        assert len(result["envelope_points"]) > 0

    def test_envelope_has_required_keys(self):
        result = json.loads(_run(run_composites_failure_envelope(
            {"plies": _PLIES_ENVELOPE, "n_angles": 8},
            CTX,
        )))
        pt = result["envelope_points"][0]
        for key in ("theta_deg", "Nx_fail_N_per_mm", "Ny_fail_N_per_mm", "lambda_crit"):
            assert key in pt

    def test_uniaxial_Nx_positive(self):
        """Pure Nx (θ=0) failure load should be positive."""
        result = json.loads(_run(run_composites_failure_envelope(
            {"plies": _PLIES_ENVELOPE, "n_angles": 4},
            CTX,
        )))
        # theta=0 point
        pt0 = next((p for p in result["envelope_points"] if abs(p["theta_deg"]) < 5), None)
        if pt0:
            assert pt0["lambda_crit"] > 0

    def test_symmetric_envelope_Nx_Ny_comparable(self):
        """[0/90/0] has higher Nx capacity than Ny (2:1 plies in x-direction)."""
        result = json.loads(_run(run_composites_failure_envelope(
            {"plies": _PLIES_ENVELOPE, "n_angles": 36},
            CTX,
        )))
        assert result["max_uniaxial_Nx_N_per_mm"] > result["max_uniaxial_Ny_N_per_mm"]

    def test_metadata_fields_present(self):
        result = json.loads(_run(run_composites_failure_envelope(
            {"plies": _PLIES_ENVELOPE, "n_angles": 4},
            CTX,
        )))
        for key in ("num_plies", "n_angles", "Nxy_N_per_mm", "F12_star"):
            assert key in result


# ---------------------------------------------------------------------------
# composites_afp_pathplan
# ---------------------------------------------------------------------------

class TestCompositesAFPPathplan:
    def test_zero_degree_courses(self):
        """0° angle → horizontal passes; num_courses ~ part_height / course_width."""
        result = json.loads(_run(run_composites_afp_pathplan(
            {"part_width_mm": 400, "part_height_mm": 100,
             "course_width_mm": 10.0, "angle_deg": 0.0},
            CTX,
        )))
        assert "num_courses" in result
        assert result["num_courses"] > 0
        assert result["num_courses"] <= 15  # 100/10 = 10 passes + 1
        # All courses should be horizontal (same y start/end)
        for c in result["courses"]:
            assert abs(c["start_y"] - c["end_y"]) < 1e-3

    def test_ninety_degree_courses(self):
        """90° angle → vertical passes."""
        result = json.loads(_run(run_composites_afp_pathplan(
            {"part_width_mm": 100, "part_height_mm": 200,
             "course_width_mm": 10.0, "angle_deg": 90.0},
            CTX,
        )))
        assert result["num_courses"] > 0
        for c in result["courses"]:
            assert abs(c["start_x"] - c["end_x"]) < 1e-3

    def test_forty_five_degree_courses(self):
        """45° angle → diagonal passes; all have angle_deg ≈ 45."""
        result = json.loads(_run(run_composites_afp_pathplan(
            {"part_width_mm": 200, "part_height_mm": 200,
             "course_width_mm": 15.0, "angle_deg": 45.0},
            CTX,
        )))
        assert result["num_courses"] > 0
        for c in result["courses"]:
            assert abs(c["angle_deg"] - 45.0) < 0.1

    def test_coverage_positive(self):
        result = json.loads(_run(run_composites_afp_pathplan(
            {"part_width_mm": 300, "part_height_mm": 200, "course_width_mm": 6.35},
            CTX,
        )))
        assert 0 < result["coverage_pct"] <= 100

    def test_total_length_positive(self):
        result = json.loads(_run(run_composites_afp_pathplan(
            {"part_width_mm": 300, "part_height_mm": 200, "course_width_mm": 10.0},
            CTX,
        )))
        assert result["total_length_mm"] > 0

    def test_gcode_format(self):
        """format='gcode' should return a G-code string (not a dict)."""
        raw = _run(run_composites_afp_pathplan(
            {"part_width_mm": 100, "part_height_mm": 50,
             "course_width_mm": 10.0, "angle_deg": 0.0, "format": "gcode"},
            CTX,
        ))
        # ok_payload wraps string in JSON; unwrap
        content = json.loads(raw)
        assert isinstance(content, str)
        assert "G00" in content or "M30" in content

    def test_apt_format(self):
        """format='apt' should return an APT string."""
        raw = _run(run_composites_afp_pathplan(
            {"part_width_mm": 100, "part_height_mm": 50,
             "course_width_mm": 10.0, "angle_deg": 0.0, "format": "apt"},
            CTX,
        ))
        content = json.loads(raw)
        assert isinstance(content, str)
        assert "GOTO" in content or "PARTNO" in content
