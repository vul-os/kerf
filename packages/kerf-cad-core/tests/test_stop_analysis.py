"""
Tests for kerf_cad_core.optics.stop_analysis — STOP multiphysics analysis.

Test plan
---------
 1. test_zero_displacement_zero_temperature_rise_gives_zero_wfe
        compute_stop_perturbation with zero displacement and T=reference → WFE = 0.
 2. test_zero_perturbation_strehl_equals_one
        With no perturbation, Strehl ratio = 1.0.
 3. test_uniform_temperature_rise_shifts_surfaces_outward
        Uniform +10 K rise: all surfaces shift axially by α·L·10 (outward = positive).
 4. test_thermal_expansion_positive_for_positive_delta_T
        thermal_expansion_displacement with T > 293.15 K → positive ΔL.
 5. test_thermal_expansion_negative_for_cold
        thermal_expansion_displacement with T < 293.15 K → negative ΔL.
 6. test_thermal_expansion_zero_at_reference
        T = 293.15 K → ΔL = 0 exactly.
 7. test_thermal_expansion_formula_exact
        ΔL = α·L₀·ΔT: check numeric value.
 8. test_strehl_in_unit_interval
        Strehl ratio is always in [0, 1].
 9. test_most_sensitive_surface_correct
        When one surface has dominant displacement, that surface is reported as most sensitive.
10. test_stop_report_type
        Return type is StopReport.
11. test_surface_perturbations_dict_has_all_surfaces
        surface_pose_perturbations has an entry for every surface.
12. test_perturbation_matrix_is_4x4
        Each perturbation matrix has shape (4, 4).
13. test_identity_perturbation_for_zero_state
        With zero displacement and reference temperature, each delta matrix = identity.
14. test_wfe_positive_for_nonzero_displacement
        Nonzero lateral displacement → WFE > 0.
15. test_wfe_pv_gt_rms
        Peak-to-valley WFE ≥ RMS WFE.
16. test_single_surface_wfe_correct_sign
        With a lateral shift, most_sensitive_surface is the only surface.
17. test_strehl_decreases_with_larger_displacement
        Larger displacement → lower Strehl ratio.
18. test_empty_surfaces_raises
        Empty surface list raises ValueError.
19. test_multi_surface_quadrature_sum
        Three surfaces with equal WFE: system WFE ≈ √3 × individual WFE.
20. test_rms_spot_radius_positive_for_perturbation
        Non-zero displacement → rms_spot_radius_um > 0.

All tests: pure-Python, no network, no DB, no OCC.

References
----------
Doyle, K.B., Genberg, V.L., Michels, G.J. (2002). Integrated optomechanical analysis.
    SPIE Press PM130.
Wang, T-Y. et al. (2006). Proc. SPIE 6288.
Mahajan, V.N. (1983). J. Opt. Soc. Am. 73:860–867.

Author: imranparuk
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.optics.stop_analysis import (
    OpticalSurface,
    StopReport,
    StopState,
    _T_REFERENCE_K,
    compute_stop_perturbation,
    thermal_expansion_displacement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_surface(surface_id: str, aperture_radius_mm: float = 25.0, material: str = "N-BK7"):
    return OpticalSurface(
        surface_id=surface_id,
        nominal_pose=np.eye(4, dtype=float),
        radius_of_curvature_mm=100.0,
        aperture_radius_mm=aperture_radius_mm,
        material=material,
    )


_CTE_BK7 = 7.1e-6   # /K (N-BK7 glass)
_CTE_AL = 23.6e-6   # /K (Al 6061)

_CTE = {"N-BK7": _CTE_BK7, "Al6061": _CTE_AL}
_E = {"N-BK7": 82.0, "Al6061": 69.0}

_ZERO_STATE = StopState(
    temperatures_at_node={},
    displacements_at_node={},
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_zero_displacement_zero_temperature_rise_gives_zero_wfe():
    """Zero displacement + reference temperature → WFE = 0."""
    surfaces = [_make_surface("S1")]
    report = compute_stop_perturbation(surfaces, _ZERO_STATE, _CTE, _E)
    assert report.wavefront_error_rms_nm == pytest.approx(0.0, abs=1e-12)


def test_zero_perturbation_strehl_equals_one():
    """With no perturbation, Strehl ratio = 1.0 exactly."""
    surfaces = [_make_surface("S1")]
    report = compute_stop_perturbation(surfaces, _ZERO_STATE, _CTE, _E)
    assert report.strehl_ratio == pytest.approx(1.0, abs=1e-12)


def test_uniform_temperature_rise_shifts_surfaces_outward():
    """Uniform +10 K rise: axial shift ≈ α·aperture·ΔT (positive, outward)."""
    surfaces = [_make_surface("S1", aperture_radius_mm=25.0, material="N-BK7")]
    state = StopState(
        temperatures_at_node={"S1": _T_REFERENCE_K + 10.0},
        displacements_at_node={},
    )
    report = compute_stop_perturbation(surfaces, state, _CTE, _E)
    dz = report.surface_pose_perturbations["S1"][2, 3]
    expected_dz = _CTE_BK7 * 25.0 * 10.0
    assert dz == pytest.approx(expected_dz, rel=1e-6)
    assert dz > 0.0, "Thermal expansion should be positive (outward)"


def test_thermal_expansion_positive_for_positive_delta_T():
    """thermal_expansion_displacement with T > reference → positive ΔL."""
    temps = {"S1": _T_REFERENCE_K + 50.0}
    delta_L = thermal_expansion_displacement("S1", temps, cte=_CTE_BK7, original_size_mm=100.0)
    assert delta_L > 0.0


def test_thermal_expansion_negative_for_cold():
    """thermal_expansion_displacement with T < reference → negative ΔL."""
    temps = {"S1": _T_REFERENCE_K - 30.0}
    delta_L = thermal_expansion_displacement("S1", temps, cte=_CTE_BK7, original_size_mm=100.0)
    assert delta_L < 0.0


def test_thermal_expansion_zero_at_reference():
    """T = reference temperature → ΔL = 0."""
    temps = {"S1": _T_REFERENCE_K}
    delta_L = thermal_expansion_displacement("S1", temps, cte=_CTE_BK7, original_size_mm=100.0)
    assert delta_L == pytest.approx(0.0, abs=1e-15)


def test_thermal_expansion_formula_exact():
    """ΔL = α · L₀ · ΔT exactly."""
    alpha = 23.6e-6  # Al 6061
    L0 = 50.0        # mm
    delta_T = 25.0   # K
    temps = {"Al_mount": _T_REFERENCE_K + delta_T}
    delta_L = thermal_expansion_displacement("Al_mount", temps, cte=alpha, original_size_mm=L0)
    expected = alpha * L0 * delta_T
    assert delta_L == pytest.approx(expected, rel=1e-12)


def test_strehl_in_unit_interval():
    """Strehl ratio is always in [0, 1]."""
    surfaces = [_make_surface("S1"), _make_surface("S2")]
    # Large displacement to drive WFE high
    state = StopState(
        temperatures_at_node={},
        displacements_at_node={
            "S1": np.array([2.0, 0.0, 5.0]),
            "S2": np.array([0.0, 1.5, 3.0]),
        },
    )
    report = compute_stop_perturbation(surfaces, state, _CTE, _E)
    assert 0.0 <= report.strehl_ratio <= 1.0


def test_most_sensitive_surface_correct():
    """When one surface has a dominant displacement, that surface is most sensitive."""
    surfaces = [
        _make_surface("S1", aperture_radius_mm=25.0),
        _make_surface("S2", aperture_radius_mm=25.0),
        _make_surface("S3", aperture_radius_mm=25.0),
    ]
    state = StopState(
        temperatures_at_node={},
        displacements_at_node={
            "S1": np.array([0.001, 0.0, 0.0]),
            "S2": np.array([10.0, 0.0, 0.0]),  # dominant
            "S3": np.array([0.001, 0.0, 0.0]),
        },
    )
    report = compute_stop_perturbation(surfaces, state, _CTE, _E)
    assert report.most_sensitive_surface == "S2", (
        f"Expected S2 as most sensitive, got {report.most_sensitive_surface}"
    )


def test_stop_report_type():
    """compute_stop_perturbation returns a StopReport."""
    surfaces = [_make_surface("S1")]
    report = compute_stop_perturbation(surfaces, _ZERO_STATE, _CTE, _E)
    assert isinstance(report, StopReport)


def test_surface_perturbations_dict_has_all_surfaces():
    """surface_pose_perturbations has an entry for every input surface."""
    surfaces = [_make_surface(f"S{i}") for i in range(4)]
    report = compute_stop_perturbation(surfaces, _ZERO_STATE, _CTE, _E)
    for surf in surfaces:
        assert surf.surface_id in report.surface_pose_perturbations


def test_perturbation_matrix_is_4x4():
    """Each perturbation matrix has shape (4, 4)."""
    surfaces = [_make_surface("S1")]
    report = compute_stop_perturbation(surfaces, _ZERO_STATE, _CTE, _E)
    delta = report.surface_pose_perturbations["S1"]
    assert delta.shape == (4, 4)


def test_identity_perturbation_for_zero_state():
    """With zero displacement and reference temperature, delta = identity."""
    surfaces = [_make_surface("S1")]
    report = compute_stop_perturbation(surfaces, _ZERO_STATE, _CTE, _E)
    np.testing.assert_allclose(
        report.surface_pose_perturbations["S1"],
        np.eye(4),
        atol=1e-12,
    )


def test_wfe_positive_for_nonzero_displacement():
    """Nonzero lateral displacement → WFE > 0."""
    surfaces = [_make_surface("S1")]
    state = StopState(
        temperatures_at_node={},
        displacements_at_node={"S1": np.array([0.1, 0.0, 0.0])},
    )
    report = compute_stop_perturbation(surfaces, state, _CTE, _E)
    assert report.wavefront_error_rms_nm > 0.0


def test_wfe_pv_gt_rms():
    """Peak-to-valley WFE ≥ RMS WFE for any non-trivial perturbation."""
    surfaces = [_make_surface("S1")]
    state = StopState(
        temperatures_at_node={},
        displacements_at_node={"S1": np.array([0.5, 0.3, 0.2])},
    )
    report = compute_stop_perturbation(surfaces, state, _CTE, _E)
    assert report.wavefront_error_pv_nm >= report.wavefront_error_rms_nm


def test_single_surface_wfe_correct_sign():
    """With a single surface displaced laterally, most_sensitive_surface is that surface."""
    surfaces = [_make_surface("L1_front")]
    state = StopState(
        temperatures_at_node={},
        displacements_at_node={"L1_front": np.array([0.2, 0.0, 0.0])},
    )
    report = compute_stop_perturbation(surfaces, state, _CTE, _E)
    assert report.most_sensitive_surface == "L1_front"


def test_strehl_decreases_with_larger_displacement():
    """Larger displacement → lower Strehl ratio."""
    surfaces = [_make_surface("S1")]

    state_small = StopState(
        temperatures_at_node={},
        displacements_at_node={"S1": np.array([0.05, 0.0, 0.0])},
    )
    state_large = StopState(
        temperatures_at_node={},
        displacements_at_node={"S1": np.array([2.0, 0.0, 0.0])},
    )

    report_small = compute_stop_perturbation(surfaces, state_small, _CTE, _E)
    report_large = compute_stop_perturbation(surfaces, state_large, _CTE, _E)
    assert report_large.strehl_ratio < report_small.strehl_ratio, (
        f"Larger displacement should yield lower Strehl: "
        f"small={report_small.strehl_ratio:.4f}, large={report_large.strehl_ratio:.4f}"
    )


def test_empty_surfaces_raises():
    """Empty surface list raises ValueError."""
    with pytest.raises(ValueError, match="must not be empty"):
        compute_stop_perturbation([], _ZERO_STATE, _CTE, _E)


def test_multi_surface_quadrature_sum():
    """Three surfaces with equal displacement: system WFE ≈ √3 × single WFE."""
    single_surf = [_make_surface("S1")]
    three_surfs = [_make_surface(f"S{i+1}") for i in range(3)]
    common_disp = np.array([0.1, 0.0, 0.0])

    state_single = StopState(
        temperatures_at_node={},
        displacements_at_node={"S1": common_disp},
    )
    state_triple = StopState(
        temperatures_at_node={},
        displacements_at_node={f"S{i+1}": common_disp for i in range(3)},
    )

    report_single = compute_stop_perturbation(single_surf, state_single, _CTE, _E)
    report_triple = compute_stop_perturbation(three_surfs, state_triple, _CTE, _E)

    expected = report_single.wavefront_error_rms_nm * math.sqrt(3.0)
    assert report_triple.wavefront_error_rms_nm == pytest.approx(expected, rel=1e-9)


def test_rms_spot_radius_positive_for_perturbation():
    """Non-zero displacement → rms_spot_radius_um > 0."""
    surfaces = [_make_surface("S1")]
    state = StopState(
        temperatures_at_node={},
        displacements_at_node={"S1": np.array([0.5, 0.0, 0.0])},
    )
    report = compute_stop_perturbation(surfaces, state, _CTE, _E)
    assert report.rms_spot_radius_um > 0.0
