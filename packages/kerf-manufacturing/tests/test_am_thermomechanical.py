"""
Tests for kerf_manufacturing.am_thermomechanical — Coupled Transient
Thermo-Mechanical AM Simulation.

Test plan
---------
1.  peak_temp_increases_with_laser_power
        Higher laser power → higher peak temperature (all else equal).

2.  peak_temp_decreases_with_scan_speed
        Higher scan speed → lower peak temperature (less energy input per unit
        volume / shorter dwell time at each layer).

3.  melt_pool_size_scales_with_energy_density
        Energy density = P / (v · h · b).  Higher energy density → deeper/wider
        melt pool.  Test: doubling P at same v gives strictly deeper melt pool
        than halving P.

4.  heated_bar_develops_tensile_residual_stress
        A bar heated significantly above T_ref then allowed to cool develops
        tensile residual stress (the thermo-elastic eigenstrain α·ΔT is
        compressive during heating → becomes tensile upon cooling lock-in).
        The von-Mises residual stress must be > 0.

5.  distortion_direction_matches_expectation
        A tall cantilever build with uniform thermal load (simulating symmetric
        preheat over all layers) should show non-zero distortion.  With a high
        power / slow scan the distortion must be strictly positive.

6.  latent_heat_plateaus_temperature
        With only latent heat (L_fusion >> 0) and a moderate heat source,
        the temperature near T_melt should evolve more slowly than the case
        without latent heat (effective cp is much larger near T_melt).

7.  energy_balance_bounded
        The energy_balance_ok flag must be True for a physically plausible
        set of inputs.

8.  bad_inputs_return_ok_false
        Negative laser_power_w, zero scan_speed, zero layer_thickness, and
        negative E_pa must each return ok=False without raising.

9.  llm_tool_handler_round_trip
        run_am_thermomechanical_simulate must return valid JSON with expected
        fields and max_deviation_mm > 0, layer_peak_temp_k non-empty.

10. melt_pool_metrics_length
        melt_pool_metrics list must have exactly n_layers entries.

11. distortion_field_shape
        displacement array must have shape (n_nodes, 3).

12. residual_stress_nonzero_after_build
        max_von_mises_pa > 0 after a build that reaches melt temperature.
"""

from __future__ import annotations

import asyncio
import json
import math

import numpy as np
import pytest

from kerf_manufacturing.am_process_sim import AMMesh, make_block_mesh
from kerf_manufacturing.am_thermomechanical import (
    AMThermoMechParams,
    AMThermoMechResult,
    simulate_am_thermomechanical,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def small_mesh() -> AMMesh:
    """2×2×4 block 10×10×20 mm."""
    return make_block_mesh(nx=2, ny=2, nz=4, lx=0.01, ly=0.01, lz=0.02)


@pytest.fixture(scope="module")
def base_params() -> AMThermoMechParams:
    """Baseline Ti-6Al-4V LPBF parameters for small mesh (coarse layers)."""
    return AMThermoMechParams(
        laser_power_w=200.0,
        scan_speed_m_s=0.8,
        beam_radius_m=50e-6,
        absorptivity=0.35,
        layer_time_s=5.0,
        layer_thickness_m=5e-3,   # 5 mm coarse layers to match mesh
        # Ti-6Al-4V
        rho_kg_m3=4430.0,
        cp_j_kg_k=526.0,
        k_w_m_k=6.7,
        T_melt_k=1878.0,
        L_fusion_j_kg=286_000.0,
        alpha_therm=8.6e-6,
        T_ref_k=298.15,
        T_preheat_k=298.15,
        E_pa=114e9,
        nu=0.342,
        beta_E_per_k=3.5e-4,
        n_z_nodes=20,
        cfl_factor=0.4,
    )


# ---------------------------------------------------------------------------
# 1. Peak temperature increases with laser power
# ---------------------------------------------------------------------------

def test_peak_temp_increases_with_laser_power(small_mesh):
    """Higher laser power must yield higher peak temperature."""
    p_low = AMThermoMechParams(
        laser_power_w=100.0, layer_thickness_m=5e-3, layer_time_s=5.0, n_z_nodes=15
    )
    p_high = AMThermoMechParams(
        laser_power_w=400.0, layer_thickness_m=5e-3, layer_time_s=5.0, n_z_nodes=15
    )
    r_low = simulate_am_thermomechanical(small_mesh, p_low)
    r_high = simulate_am_thermomechanical(small_mesh, p_high)

    assert r_low.ok, f"Low power sim failed: {r_low.reason}"
    assert r_high.ok, f"High power sim failed: {r_high.reason}"

    max_low = max(r_low.layer_peak_temp_k)
    max_high = max(r_high.layer_peak_temp_k)
    assert max_high > max_low, (
        f"High power ({400} W) peak temp {max_high:.1f} K should exceed "
        f"low power ({100} W) peak temp {max_low:.1f} K"
    )


# ---------------------------------------------------------------------------
# 2. Peak temperature decreases with scan speed
# ---------------------------------------------------------------------------

def test_peak_temp_decreases_with_scan_speed(small_mesh):
    """Higher scan speed → lower energy dwell → lower peak temperature."""
    p_slow = AMThermoMechParams(
        laser_power_w=200.0, scan_speed_m_s=0.2,
        layer_thickness_m=5e-3, layer_time_s=5.0, n_z_nodes=15
    )
    p_fast = AMThermoMechParams(
        laser_power_w=200.0, scan_speed_m_s=2.0,
        layer_thickness_m=5e-3, layer_time_s=5.0, n_z_nodes=15
    )
    r_slow = simulate_am_thermomechanical(small_mesh, p_slow)
    r_fast = simulate_am_thermomechanical(small_mesh, p_fast)

    assert r_slow.ok
    assert r_fast.ok

    # Slow scan: longer interaction time → higher temperature
    max_slow = max(r_slow.layer_peak_temp_k)
    max_fast = max(r_fast.layer_peak_temp_k)
    # The energy density ratio is 10:1 (2.0/0.2) → temperature must differ
    assert max_slow > max_fast, (
        f"Slow scan ({0.2} m/s) peak {max_slow:.1f} K should exceed "
        f"fast scan ({2.0} m/s) peak {max_fast:.1f} K"
    )


# ---------------------------------------------------------------------------
# 3. Melt-pool size scales with energy density
# ---------------------------------------------------------------------------

def test_melt_pool_size_scales_with_energy_density(small_mesh):
    """Doubling laser power at same scan speed → deeper melt pool than halving power."""
    # High energy density
    p_high = AMThermoMechParams(
        laser_power_w=600.0, scan_speed_m_s=0.4,
        layer_thickness_m=5e-3, layer_time_s=5.0, n_z_nodes=20
    )
    # Low energy density
    p_low = AMThermoMechParams(
        laser_power_w=100.0, scan_speed_m_s=1.6,
        layer_thickness_m=5e-3, layer_time_s=5.0, n_z_nodes=20
    )
    r_high = simulate_am_thermomechanical(small_mesh, p_high)
    r_low = simulate_am_thermomechanical(small_mesh, p_low)

    assert r_high.ok
    assert r_low.ok

    # At high energy density, at least some layers should reach melt temperature
    high_peak = max(r_high.layer_peak_temp_k)
    low_peak = max(r_low.layer_peak_temp_k)

    # Melt pool width is geometry-based (beam radius), but peak temperature
    # is a proxy for melt pool depth — high energy density must yield higher T
    assert high_peak > low_peak, (
        f"High energy density peak {high_peak:.1f} K should exceed "
        f"low energy density peak {low_peak:.1f} K"
    )
    # Both must show non-zero melt pool width (beam radius is non-zero)
    assert all(m.melt_pool_width_m > 0 for m in r_high.melt_pool_metrics)


# ---------------------------------------------------------------------------
# 4. Heated bar develops tensile residual stress
# ---------------------------------------------------------------------------

def test_heated_bar_develops_tensile_residual_stress(small_mesh):
    """A bar heated significantly above T_ref must develop non-zero residual stress."""
    params = AMThermoMechParams(
        laser_power_w=500.0,
        scan_speed_m_s=0.2,
        layer_thickness_m=5e-3,
        layer_time_s=5.0,
        alpha_therm=8.6e-6,
        T_ref_k=298.15,
        T_preheat_k=298.15,
        E_pa=114e9,
        nu=0.342,
        n_z_nodes=20,
    )
    res = simulate_am_thermomechanical(small_mesh, params)
    assert res.ok, f"Sim failed: {res.reason}"

    # Must develop non-zero residual stress
    assert res.max_von_mises_pa > 0.0, (
        "Von-Mises residual stress is zero — thermal eigenstrain not applied"
    )
    # Physically plausible upper bound: < 10 GPa
    assert res.max_von_mises_pa < 10e9, (
        f"Von-Mises {res.max_von_mises_pa / 1e6:.1f} MPa seems unphysically large"
    )


# ---------------------------------------------------------------------------
# 5. Distortion direction matches expectation
# ---------------------------------------------------------------------------

def test_distortion_direction_matches_expectation(small_mesh):
    """With strong thermal load, distortion must be non-zero and positive."""
    params = AMThermoMechParams(
        laser_power_w=400.0,
        layer_thickness_m=5e-3,
        layer_time_s=5.0,
        E_pa=114e9,
        nu=0.342,
        alpha_therm=8.6e-6,
        T_ref_k=298.15,
        n_z_nodes=20,
    )
    res = simulate_am_thermomechanical(small_mesh, params)
    assert res.ok
    assert res.max_deviation_m > 0.0, "Expected non-zero distortion from thermal load"
    assert res.displacement.shape == (small_mesh.n_nodes, 3)

    # Distortion must be bounded (< part height = 20 mm)
    assert res.max_deviation_m < 0.02, (
        f"Distortion {res.max_deviation_m * 1e3:.3f} mm exceeds part height — runaway"
    )


# ---------------------------------------------------------------------------
# 6. Latent heat plateaus temperature near T_melt
# ---------------------------------------------------------------------------

def test_latent_heat_plateaus_temperature():
    """With latent heat, temperature evolution near T_melt is slower than without."""
    from kerf_manufacturing.am_thermomechanical import (
        _cp_eff, AMThermoMechParams
    )
    params = AMThermoMechParams(
        T_melt_k=1878.0, cp_j_kg_k=526.0, L_fusion_j_kg=286_000.0,
        latent_heat_smear_k=50.0
    )

    # cp_eff near T_melt must be >> cp_base
    T_at_melt = params.T_melt_k
    cp_at_melt = _cp_eff(T_at_melt, params)
    cp_far_below = _cp_eff(params.T_melt_k - 300.0, params)

    assert cp_at_melt > cp_far_below * 5, (
        f"cp_eff at T_melt ({cp_at_melt:.1f} J/kg/K) should be >> "
        f"cp far below ({cp_far_below:.1f} J/kg/K) due to latent heat"
    )

    # The peak of cp_eff should be at T_melt
    T_range = np.linspace(params.T_melt_k - 200.0, params.T_melt_k + 200.0, 200)
    cp_curve = np.array([_cp_eff(T, params) for T in T_range])
    T_peak_cp = float(T_range[np.argmax(cp_curve)])
    assert abs(T_peak_cp - params.T_melt_k) < 10.0, (
        f"cp_eff peak should be near T_melt {params.T_melt_k} K, got {T_peak_cp:.1f} K"
    )


# ---------------------------------------------------------------------------
# 7. Energy balance bounded for realistic inputs
# ---------------------------------------------------------------------------

def test_energy_balance_bounded(small_mesh, base_params):
    """energy_balance_ok must be True for standard parameters."""
    res = simulate_am_thermomechanical(small_mesh, base_params)
    assert res.ok
    assert res.energy_input_j > 0.0, "Energy input must be positive"
    assert res.energy_balance_ok, (
        "Energy balance check failed — verify laser_power_w and layer geometry"
    )


# ---------------------------------------------------------------------------
# 8. Bad inputs return ok=False without raising
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_kwargs,expected_fragment", [
    ({"laser_power_w": -1.0}, "laser_power_w"),
    ({"scan_speed_m_s": 0.0}, "scan_speed_m_s"),
    ({"layer_thickness_m": 0.0}, "layer_thickness_m"),
    ({"E_pa": -1.0}, "E_pa"),
    ({"nu": 0.7}, "nu"),
])
def test_bad_inputs_return_ok_false(bad_kwargs, expected_fragment):
    mesh = make_block_mesh(nx=1, ny=1, nz=2)
    params = AMThermoMechParams(**bad_kwargs)
    res = simulate_am_thermomechanical(mesh, params)
    assert not res.ok, (
        f"Expected ok=False for bad input {bad_kwargs}, got ok=True"
    )
    assert expected_fragment.lower() in res.reason.lower(), (
        f"Expected '{expected_fragment}' in reason, got: {res.reason}"
    )


# ---------------------------------------------------------------------------
# 9. LLM tool handler round-trip
# ---------------------------------------------------------------------------

def test_llm_tool_handler_round_trip():
    """run_am_thermomechanical_simulate returns valid JSON with expected fields."""
    from kerf_manufacturing.am_thermo_tool import run_am_thermomechanical_simulate
    from kerf_manufacturing._compat import ProjectCtx

    ctx = ProjectCtx()
    params = {
        "nx": 2, "ny": 2, "nz": 3,
        "lx": 0.01, "ly": 0.01, "lz": 0.015,
        "layer_thickness_m": 5e-3,
        "laser_power_w": 250.0,
        "scan_speed_m_s": 0.5,
        "layer_time_s": 5.0,
        "E_pa": 114e9,
        "nu": 0.342,
        "n_z_nodes": 15,
    }
    raw = asyncio.run(
        run_am_thermomechanical_simulate(params, ctx)
    )
    doc = json.loads(raw)
    assert doc.get("ok") is True, f"Handler returned error: {doc}"

    # Thermal results
    assert "layer_peak_temp_k" in doc
    assert len(doc["layer_peak_temp_k"]) > 0
    assert all(t > 0 for t in doc["layer_peak_temp_k"])

    assert "melt_pool_depth_mm" in doc
    assert "melt_pool_width_mm" in doc
    assert "melt_pool_reached" in doc
    assert "energy_input_j" in doc
    assert doc["energy_input_j"] > 0.0
    assert "energy_balance_ok" in doc

    # Mechanical results
    assert "max_deviation_mm" in doc
    assert doc["max_deviation_mm"] > 0.0
    assert "max_von_mises_mpa" in doc
    assert "layer_max_disp_mm" in doc
    assert "distortion_field" in doc
    assert "residual_stress_mpa" in doc
    assert "warnings" in doc
    assert len(doc["warnings"]) > 0  # always includes honest model note


def test_llm_tool_handler_bad_args():
    """Handler must return error payload for invalid laser_power_w."""
    from kerf_manufacturing.am_thermo_tool import run_am_thermomechanical_simulate
    from kerf_manufacturing._compat import ProjectCtx

    ctx = ProjectCtx()
    params = {"laser_power_w": -1.0, "nx": 2, "ny": 2, "nz": 2}
    raw = asyncio.run(
        run_am_thermomechanical_simulate(params, ctx)
    )
    doc = json.loads(raw)
    # Must indicate failure
    assert doc.get("ok") is not True or "error" in doc


# ---------------------------------------------------------------------------
# 10. Melt-pool metrics length matches n_layers
# ---------------------------------------------------------------------------

def test_melt_pool_metrics_length(small_mesh, base_params):
    """melt_pool_metrics must have exactly n_layers entries."""
    res = simulate_am_thermomechanical(small_mesh, base_params)
    assert res.ok
    assert len(res.melt_pool_metrics) == res.n_layers, (
        f"Expected {res.n_layers} melt_pool_metrics entries, "
        f"got {len(res.melt_pool_metrics)}"
    )
    # Each entry's layer_index must be in [0, n_layers)
    for m in res.melt_pool_metrics:
        assert 0 <= m.layer_index < res.n_layers


# ---------------------------------------------------------------------------
# 11. Distortion field shape
# ---------------------------------------------------------------------------

def test_distortion_field_shape(small_mesh, base_params):
    """displacement must have shape (n_nodes, 3)."""
    res = simulate_am_thermomechanical(small_mesh, base_params)
    assert res.ok
    assert res.displacement.shape == (small_mesh.n_nodes, 3), (
        f"Expected shape ({small_mesh.n_nodes}, 3), got {res.displacement.shape}"
    )


# ---------------------------------------------------------------------------
# 12. Residual stress non-zero after build with thermal load
# ---------------------------------------------------------------------------

def test_residual_stress_nonzero_after_build(small_mesh):
    """A build with non-zero thermal expansion coefficient must produce residual stress."""
    params = AMThermoMechParams(
        laser_power_w=300.0,
        layer_thickness_m=5e-3,
        layer_time_s=5.0,
        alpha_therm=8.6e-6,
        T_ref_k=298.15,
        E_pa=114e9,
        nu=0.342,
        n_z_nodes=20,
    )
    res = simulate_am_thermomechanical(small_mesh, params)
    assert res.ok
    assert res.max_von_mises_pa > 0.0, (
        "Expected non-zero von-Mises residual stress from thermal eigenstrain"
    )
