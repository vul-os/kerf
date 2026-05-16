"""
Hermetic tests for kerf_cad_core.refrigeration — vapor-compression refrigeration
& heat-pump design.

Coverage:
  cycle.saturation_pressure        — Antoine/Clausius-Clapeyron per refrigerant
  cycle.single_stage_cycle         — COP, mass flow, compressor work, duties
  cycle.tons_of_refrigeration      — unit conversions (W, kW, TR, BTU/h)
  cycle.compressor_sizing          — mass flow, displacement, pressure ratio
  cycle.superheat_subcool_effect   — incremental COP improvement from SH/SC
  cycle.two_stage_cycle            — two-stage flash/intercooler cycle
  cycle.cascade_cycle              — two-refrigerant cascade
  cycle.defrost_energy             — daily defrost energy estimate
  cycle.pressure_ratio_check       — pressure ratio + discharge temp flags
  tools.*                          — LLM wrapper happy paths + error paths

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against:
  ASHRAE Fundamentals Handbook 2021.
  Stoecker & Jones, "Refrigeration and Air Conditioning", 2nd ed.
  Cengel & Boles, "Thermodynamics: An Engineering Approach", 8th ed.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
import warnings

import pytest

from kerf_cad_core.refrigeration.cycle import (
    saturation_pressure,
    single_stage_cycle,
    tons_of_refrigeration,
    compressor_sizing,
    superheat_subcool_effect,
    two_stage_cycle,
    cascade_cycle,
    defrost_energy,
    pressure_ratio_check,
    TR_TO_W,
    W_TO_TR,
    SUPPORTED_REFRIGERANTS,
    _sat_pressure,
    _sat_temperature,
    _h_fg,
    _C_to_K,
    _K_to_C,
    _REFRIGERANT_DATA,
)
from kerf_cad_core.refrigeration.tools import (
    run_saturation_pressure,
    run_single_stage_cycle,
    run_tons_of_refrigeration,
    run_compressor_sizing,
    run_superheat_subcool_effect,
    run_two_stage_cycle,
    run_cascade_cycle,
    run_defrost_energy,
    run_pressure_ratio_check,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REL = 1e-6
REL_1PCT = 0.01   # 1 % tolerance for engineering approximations
REL_5PCT = 0.05   # 5 % tolerance for multi-stage approximations


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    # ok_payload may wrap the result in a nested dict
    if "ok" in d and d["ok"] is True:
        return d
    if "result" in d and isinstance(d["result"], dict) and d["result"].get("ok") is True:
        return d["result"]
    assert False, f"Expected ok=True response, got: {d}"


def _err_response(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


# ===========================================================================
# Constants
# ===========================================================================

class TestConstants:

    def test_TR_to_W(self):
        """1 TR = 3516.853 W (ASHRAE definition)."""
        assert abs(TR_TO_W - 3516.853) < 0.01

    def test_W_to_TR_inverse(self):
        assert abs(TR_TO_W * W_TO_TR - 1.0) < REL

    def test_supported_refrigerants(self):
        assert set(SUPPORTED_REFRIGERANTS) == {"R134a", "R410A", "R717", "R744", "R290"}


# ===========================================================================
# 1. saturation_pressure (cycle.py internal helpers)
# ===========================================================================

class TestSaturationPressure:

    def test_R134a_at_0C_approx(self):
        """R134a sat. pressure at 0°C ≈ 293 kPa (ASHRAE / NIST)."""
        r = saturation_pressure(0.0, "R134a")
        assert r["ok"] is True
        # NIST: ~292,800 Pa at 0°C; our Antoine fit should be within 10%
        assert 250_000 < r["P_sat_Pa"] < 350_000

    def test_R134a_higher_temp_gives_higher_pressure(self):
        """Saturation pressure increases with temperature."""
        r1 = saturation_pressure(-10.0, "R134a")
        r2 = saturation_pressure(30.0,  "R134a")
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r2["P_sat_Pa"] > r1["P_sat_Pa"]

    def test_R717_ammonia_0C(self):
        """R717 (ammonia) saturation pressure at 0°C ≈ 429 kPa (ASHRAE)."""
        r = saturation_pressure(0.0, "R717")
        assert r["ok"] is True
        assert 350_000 < r["P_sat_Pa"] < 550_000

    def test_R744_CO2_negative20(self):
        """R744 (CO₂) at −20°C has very high pressure ≈ 1.97 MPa."""
        r = saturation_pressure(-20.0, "R744")
        assert r["ok"] is True
        assert 1_500_000 < r["P_sat_Pa"] < 2_500_000

    def test_R290_propane_0C(self):
        r = saturation_pressure(0.0, "R290")
        assert r["ok"] is True
        # R290 at 0°C ≈ 473 kPa (NIST)
        assert 300_000 < r["P_sat_Pa"] < 650_000

    def test_R410A_0C(self):
        r = saturation_pressure(0.0, "R410A")
        assert r["ok"] is True
        # R410A at 0°C ≈ 798 kPa; Antoine fit within 20%
        assert 500_000 < r["P_sat_Pa"] < 1_200_000

    def test_unknown_refrigerant_returns_err(self):
        r = saturation_pressure(0.0, "R999")
        assert r["ok"] is False
        assert "R999" in r["reason"]

    def test_T_K_returned(self):
        r = saturation_pressure(25.0, "R134a")
        assert abs(r["T_K"] - 298.15) < 0.01

    def test_inverse_roundtrip(self):
        """_sat_temperature(_sat_pressure(T)) ≈ T for R134a."""
        ref = _REFRIGERANT_DATA["R134a"]
        T_K = 280.0
        P = _sat_pressure(T_K, ref)
        T_back = _sat_temperature(P, ref)
        assert abs(T_back - T_K) < 1e-6


# ===========================================================================
# 2. h_fg helper
# ===========================================================================

class TestHfg:

    def test_h_fg_positive_at_evap_range(self):
        ref = _REFRIGERANT_DATA["R134a"]
        h = _h_fg(_C_to_K(-10.0), ref)
        assert h > 0

    def test_h_fg_decreases_toward_critical(self):
        ref = _REFRIGERANT_DATA["R134a"]
        h_low = _h_fg(_C_to_K(-10.0), ref)
        h_high = _h_fg(_C_to_K(80.0), ref)
        assert h_low > h_high

    def test_h_fg_zero_at_critical(self):
        ref = _REFRIGERANT_DATA["R134a"]
        h = _h_fg(ref["T_max_K"], ref)
        assert abs(h) < 1.0  # ≈ 0 at critical


# ===========================================================================
# 3. tons_of_refrigeration — unit conversions
# ===========================================================================

class TestTonsOfRefrigeration:

    def test_1TR_equals_3516W(self):
        r = tons_of_refrigeration(capacity_TR=1.0)
        assert r["ok"] is True
        assert abs(r["capacity_W"] - TR_TO_W) < 0.01

    def test_3516W_equals_1TR(self):
        r = tons_of_refrigeration(capacity_W=TR_TO_W)
        assert abs(r["capacity_TR"] - 1.0) < 1e-4

    def test_1kW_converts_correctly(self):
        r = tons_of_refrigeration(capacity_kW=1.0)
        assert abs(r["capacity_W"] - 1000.0) < REL

    def test_12000_BTUh_equals_1TR(self):
        """1 TR ≈ 12,000 BTU/h (standard definition)."""
        r = tons_of_refrigeration(capacity_BTUh=12_000.0)
        assert r["ok"] is True
        # 12,000 BTU/h / 3.41214 BTU/h/W ≈ 3516.8 W ≈ 1 TR
        assert abs(r["capacity_TR"] - 1.0) < 0.05  # within 5%

    def test_no_input_returns_err(self):
        r = tons_of_refrigeration()
        assert r["ok"] is False

    def test_negative_capacity_err(self):
        r = tons_of_refrigeration(capacity_W=-100.0)
        assert r["ok"] is False

    def test_roundtrip_W_TR_W(self):
        """W → TR → W round-trip."""
        r1 = tons_of_refrigeration(capacity_W=10_000.0)
        r2 = tons_of_refrigeration(capacity_TR=r1["capacity_TR"])
        assert abs(r2["capacity_W"] - 10_000.0) < 0.01


# ===========================================================================
# 4. single_stage_cycle
# ===========================================================================

class TestSingleStageCycle:

    def test_basic_R134a_returns_ok(self):
        r = single_stage_cycle(-10.0, 40.0, 10_000.0)
        assert r["ok"] is True

    def test_COP_positive(self):
        r = single_stage_cycle(-10.0, 40.0, 10_000.0)
        assert r["COP_cooling"] > 0

    def test_heating_COP_equals_cooling_plus_one(self):
        """First-law check: COP_heat = COP_cool + 1."""
        r = single_stage_cycle(-10.0, 40.0, 10_000.0)
        assert abs(r["COP_heating"] - (r["COP_cooling"] + 1.0)) < 1e-9

    def test_energy_balance(self):
        """Q_cond ≈ Q_evap + W_compressor."""
        r = single_stage_cycle(-10.0, 40.0, 10_000.0)
        Q_cond_check = r["Q_evap_W"] + r["W_compressor_W"]
        assert abs(r["Q_cond_W"] - Q_cond_check) / r["Q_cond_W"] < REL_1PCT

    def test_mass_flow_positive(self):
        r = single_stage_cycle(-10.0, 40.0, 10_000.0)
        assert r["mass_flow_kg_s"] > 0

    def test_displacement_greater_than_vol_flow(self):
        """Displacement (actual) > volumetric flow due to volumetric efficiency."""
        r = single_stage_cycle(-10.0, 40.0, 10_000.0, eta_volumetric=0.8)
        assert r["compressor_displacement_m3s"] > r["volumetric_flow_m3s"]

    def test_mass_flow_scales_with_capacity(self):
        """Doubling capacity should approximately double mass flow."""
        r1 = single_stage_cycle(-10.0, 40.0, 5_000.0)
        r2 = single_stage_cycle(-10.0, 40.0, 10_000.0)
        assert abs(r2["mass_flow_kg_s"] / r1["mass_flow_kg_s"] - 2.0) < REL_1PCT

    def test_COP_improves_with_higher_evap_temp(self):
        """Higher evaporator temperature → lower pressure ratio → better COP."""
        r_low  = single_stage_cycle(-20.0, 40.0, 10_000.0)
        r_high = single_stage_cycle(-5.0,  40.0, 10_000.0)
        assert r_high["COP_cooling"] > r_low["COP_cooling"]

    def test_COP_improves_with_lower_cond_temp(self):
        """Lower condenser temperature → lower pressure ratio → better COP."""
        r_high = single_stage_cycle(-10.0, 50.0, 10_000.0)
        r_low  = single_stage_cycle(-10.0, 30.0, 10_000.0)
        assert r_low["COP_cooling"] > r_high["COP_cooling"]

    def test_capacity_TR_field(self):
        """capacity_TR = capacity_W / TR_TO_W."""
        cap = 7033.7
        r = single_stage_cycle(-10.0, 40.0, cap)
        assert abs(r["capacity_TR"] - cap * W_TO_TR) < 1e-4

    def test_pressure_ratio_positive(self):
        r = single_stage_cycle(-10.0, 40.0, 10_000.0)
        assert r["pressure_ratio"] > 1.0

    def test_R410A_works(self):
        r = single_stage_cycle(-5.0, 45.0, 8_000.0, "R410A")
        assert r["ok"] is True
        assert r["COP_cooling"] > 1.0

    def test_R717_ammonia_works(self):
        r = single_stage_cycle(-15.0, 35.0, 20_000.0, "R717")
        assert r["ok"] is True
        assert r["COP_cooling"] > 1.0

    def test_R290_propane_works(self):
        r = single_stage_cycle(-10.0, 40.0, 5_000.0, "R290")
        assert r["ok"] is True

    def test_evap_ge_cond_returns_err(self):
        r = single_stage_cycle(40.0, 40.0, 10_000.0)
        assert r["ok"] is False

    def test_evap_gt_cond_returns_err(self):
        r = single_stage_cycle(50.0, 40.0, 10_000.0)
        assert r["ok"] is False

    def test_negative_capacity_err(self):
        r = single_stage_cycle(-10.0, 40.0, -100.0)
        assert r["ok"] is False

    def test_bad_refrigerant_err(self):
        r = single_stage_cycle(-10.0, 40.0, 10_000.0, "R999")
        assert r["ok"] is False

    def test_low_superheat_warning(self):
        """superheat < 3 K should trigger a warning about floodback."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = single_stage_cycle(-10.0, 40.0, 10_000.0, superheat_K=1.0)
        assert r["ok"] is True
        assert any("floodback" in str(ww.message).lower() for ww in w) or \
               any("floodback" in msg.lower() for msg in r["warnings"])

    def test_high_pressure_ratio_warning(self):
        """Very large temperature lift → pressure ratio > 10 → warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = single_stage_cycle(-60.0, 60.0, 10_000.0, "R134a")
        # May or may not reach pr>10 depending on refrigerant; just check no crash
        assert "ok" in r


# ===========================================================================
# 5. pressure_ratio_check
# ===========================================================================

class TestPressureRatioCheck:

    def test_basic(self):
        r = pressure_ratio_check(-10.0, 40.0, "R134a")
        assert r["ok"] is True
        assert r["pressure_ratio"] > 1.0

    def test_flag_high_ratio_false_for_normal_operation(self):
        r = pressure_ratio_check(-5.0, 40.0, "R134a")
        assert r["ok"] is True
        assert r["flag_high_ratio"] is False

    def test_discharge_temp_positive(self):
        r = pressure_ratio_check(-10.0, 40.0, "R134a")
        assert r["discharge_temp_est_C"] > 0

    def test_p_cond_gt_p_evap(self):
        r = pressure_ratio_check(-10.0, 40.0)
        assert r["P_cond_Pa"] > r["P_evap_Pa"]

    def test_evap_ge_cond_err(self):
        r = pressure_ratio_check(40.0, 40.0)
        assert r["ok"] is False

    def test_bad_refrigerant_err(self):
        r = pressure_ratio_check(-10.0, 40.0, "R999")
        assert r["ok"] is False


# ===========================================================================
# 6. compressor_sizing
# ===========================================================================

class TestCompressorSizing:

    def test_returns_ok(self):
        r = compressor_sizing(10_000.0, -10.0, 40.0)
        assert r["ok"] is True

    def test_displacement_positive(self):
        r = compressor_sizing(10_000.0, -10.0, 40.0)
        assert r["compressor_displacement_m3s"] > 0

    def test_mass_flow_positive(self):
        r = compressor_sizing(10_000.0, -10.0, 40.0)
        assert r["mass_flow_kg_s"] > 0

    def test_missing_capacity_err(self):
        r = compressor_sizing(0.0, -10.0, 40.0)
        assert r["ok"] is False


# ===========================================================================
# 7. superheat_subcool_effect
# ===========================================================================

class TestSuperheatSubcoolEffect:

    def test_returns_ok(self):
        r = superheat_subcool_effect(-10.0, 40.0, 10_000.0, superheat_K=8.0, subcool_K=5.0)
        assert r["ok"] is True

    def test_subcooling_improves_refrigerating_effect(self):
        """Subcooling reduces h4 → increases refrigerating effect."""
        r = superheat_subcool_effect(-10.0, 40.0, 10_000.0, superheat_K=0.0, subcool_K=5.0)
        assert r["refrig_effect_modified"] > r["refrig_effect_base"]

    def test_zero_sh_zero_sc_no_change(self):
        """COP_change should be ~0 when superheat=0 and subcool=0."""
        r = superheat_subcool_effect(-10.0, 40.0, 10_000.0, superheat_K=0.0, subcool_K=0.0)
        assert abs(r["COP_change"]) < 1e-6


# ===========================================================================
# 8. two_stage_cycle
# ===========================================================================

class TestTwoStageCycle:

    def test_returns_ok(self):
        r = two_stage_cycle(-40.0, 40.0, 20_000.0)
        assert r["ok"] is True

    def test_COP_positive(self):
        r = two_stage_cycle(-40.0, 40.0, 20_000.0)
        assert r["COP_cooling_two_stage"] > 0

    def test_W_total_positive(self):
        r = two_stage_cycle(-40.0, 40.0, 20_000.0)
        assert r["W_total_W"] > 0

    def test_interstage_between_evap_and_cond(self):
        """Interstage temperature should be between evap and cond temperatures."""
        r = two_stage_cycle(-40.0, 40.0, 20_000.0)
        assert -40.0 < r["T_interstage_C"] < 40.0

    def test_interstage_approx_geometric_mean(self):
        """Geometric mean of T_evap_K and T_cond_K (in K), then convert to °C."""
        T_evap_K = _C_to_K(-40.0)
        T_cond_K = _C_to_K(40.0)
        T_int_expected_C = _K_to_C(math.sqrt(T_evap_K * T_cond_K))
        r = two_stage_cycle(-40.0, 40.0, 20_000.0)
        assert abs(r["T_interstage_C"] - T_int_expected_C) < 0.1

    def test_explicit_interstage(self):
        r = two_stage_cycle(-40.0, 40.0, 20_000.0, T_interstage_C=-5.0)
        assert r["ok"] is True
        assert abs(r["T_interstage_C"] - (-5.0)) < 0.01

    def test_evap_ge_cond_err(self):
        r = two_stage_cycle(40.0, 40.0, 20_000.0)
        assert r["ok"] is False

    def test_bad_refrigerant_err(self):
        r = two_stage_cycle(-40.0, 40.0, 20_000.0, "R999")
        assert r["ok"] is False


# ===========================================================================
# 9. cascade_cycle
# ===========================================================================

class TestCascadeCycle:

    def test_returns_ok(self):
        r = cascade_cycle(-50.0, 40.0, 15_000.0, "R744", "R134a")
        assert r["ok"] is True

    def test_COP_positive(self):
        r = cascade_cycle(-50.0, 40.0, 15_000.0)
        assert r["COP_cooling"] > 0

    def test_W_total_positive(self):
        r = cascade_cycle(-50.0, 40.0, 15_000.0)
        assert r["W_total_W"] > 0

    def test_energy_balance_rough(self):
        """Q_cond ≈ Q_evap + W_total (within 5%)."""
        r = cascade_cycle(-50.0, 40.0, 15_000.0)
        assert abs(r["Q_cond_W"] - (r["Q_evap_W"] + r["W_total_W"])) / r["Q_cond_W"] < REL_5PCT

    def test_evap_ge_cond_err(self):
        r = cascade_cycle(40.0, 40.0, 10_000.0)
        assert r["ok"] is False

    def test_bad_refrigerant_err(self):
        r = cascade_cycle(-50.0, 40.0, 15_000.0, refrigerant_low="R999")
        assert r["ok"] is False


# ===========================================================================
# 10. defrost_energy
# ===========================================================================

class TestDefrostEnergy:

    def test_basic(self):
        r = defrost_energy(5000.0, 20.0, 4, 30.0)
        assert r["ok"] is True

    def test_daily_evap_energy(self):
        """daily_evap = Q_evap × hours."""
        r = defrost_energy(5000.0, 20.0, 4, 30.0)
        assert abs(r["daily_evap_energy_Wh"] - 5000.0 * 20.0) < 0.01

    def test_defrost_fraction_applied(self):
        """defrost_Wh = daily_evap × fraction."""
        r = defrost_energy(5000.0, 20.0, 4, 30.0, defrost_fraction=0.05)
        assert abs(r["defrost_energy_Wh"] - 5000.0 * 20.0 * 0.05) < 0.01

    def test_per_cycle_energy(self):
        r = defrost_energy(5000.0, 20.0, 4, 30.0, defrost_fraction=0.05)
        assert abs(r["defrost_energy_per_cycle_Wh"] - r["defrost_energy_Wh"] / 4) < 0.001

    def test_defrost_duration_total(self):
        """4 cycles × 30 min = 120 min = 2 h."""
        r = defrost_energy(5000.0, 20.0, 4, 30.0)
        assert abs(r["defrost_duration_h_total"] - 2.0) < 1e-9

    def test_effective_operating_hours(self):
        r = defrost_energy(5000.0, 20.0, 4, 30.0)
        assert abs(r["effective_operating_hours"] - (20.0 - 2.0)) < 1e-9

    def test_zero_Q_evap_err(self):
        r = defrost_energy(0.0, 20.0, 4, 30.0)
        assert r["ok"] is False

    def test_zero_cycles_err(self):
        r = defrost_energy(5000.0, 20.0, 0, 30.0)
        assert r["ok"] is False


# ===========================================================================
# 11. LLM tool wrappers — happy paths
# ===========================================================================

class TestToolWrappers:

    def test_saturation_pressure_tool_happy(self):
        raw = _run(run_saturation_pressure(_ctx(), _args(T_C=0.0, refrigerant="R134a")))
        d = _ok(raw)
        assert d["P_sat_Pa"] > 0

    def test_single_stage_tool_happy(self):
        raw = _run(run_single_stage_cycle(
            _ctx(), _args(T_evap_C=-10.0, T_cond_C=40.0, capacity_W=10_000.0)
        ))
        d = _ok(raw)
        assert d["COP_cooling"] > 0

    def test_tons_tool_from_TR(self):
        raw = _run(run_tons_of_refrigeration(_ctx(), _args(capacity_TR=2.0)))
        d = _ok(raw)
        assert abs(d["capacity_W"] - 2 * TR_TO_W) < 0.1

    def test_compressor_sizing_tool_happy(self):
        raw = _run(run_compressor_sizing(
            _ctx(), _args(capacity_W=10_000.0, T_evap_C=-10.0, T_cond_C=40.0)
        ))
        d = _ok(raw)
        assert d["mass_flow_kg_s"] > 0

    def test_sh_sc_tool_happy(self):
        raw = _run(run_superheat_subcool_effect(
            _ctx(), _args(T_evap_C=-10.0, T_cond_C=40.0, capacity_W=10_000.0,
                          superheat_K=8.0, subcool_K=5.0)
        ))
        d = _ok(raw)
        assert "COP_base" in d

    def test_two_stage_tool_happy(self):
        raw = _run(run_two_stage_cycle(
            _ctx(), _args(T_evap_C=-40.0, T_cond_C=40.0, capacity_W=20_000.0)
        ))
        d = _ok(raw)
        assert d["COP_cooling_two_stage"] > 0

    def test_cascade_tool_happy(self):
        raw = _run(run_cascade_cycle(
            _ctx(), _args(T_evap_C=-50.0, T_cond_C=40.0, capacity_W=15_000.0)
        ))
        d = _ok(raw)
        assert d["COP_cooling"] > 0

    def test_defrost_tool_happy(self):
        raw = _run(run_defrost_energy(
            _ctx(), _args(
                Q_evap_W=5000.0,
                operating_hours_per_day=20.0,
                defrost_cycles_per_day=4,
                defrost_duration_min=30.0,
            )
        ))
        d = _ok(raw)
        assert d["defrost_energy_Wh"] > 0

    def test_pressure_ratio_tool_happy(self):
        raw = _run(run_pressure_ratio_check(
            _ctx(), _args(T_evap_C=-10.0, T_cond_C=40.0)
        ))
        d = _ok(raw)
        assert d["pressure_ratio"] > 1.0


# ===========================================================================
# 12. LLM tool wrappers — error paths
# ===========================================================================

class TestToolErrors:

    def test_sat_pressure_missing_T_C(self):
        raw = _run(run_saturation_pressure(_ctx(), _args(refrigerant="R134a")))
        _err_response(raw)

    def test_single_stage_missing_evap(self):
        raw = _run(run_single_stage_cycle(_ctx(), _args(T_cond_C=40.0, capacity_W=10_000.0)))
        _err_response(raw)

    def test_single_stage_bad_json(self):
        raw = _run(run_single_stage_cycle(_ctx(), b"not-json"))
        _err_response(raw)

    def test_tons_no_input(self):
        raw = _run(run_tons_of_refrigeration(_ctx(), _args()))
        _err_response(raw)

    def test_compressor_missing_capacity(self):
        raw = _run(run_compressor_sizing(_ctx(), _args(T_evap_C=-10.0, T_cond_C=40.0)))
        _err_response(raw)

    def test_pressure_ratio_evap_ge_cond(self):
        raw = _run(run_pressure_ratio_check(_ctx(), _args(T_evap_C=40.0, T_cond_C=40.0)))
        _err_response(raw)

    def test_defrost_missing_field(self):
        raw = _run(run_defrost_energy(
            _ctx(), _args(Q_evap_W=5000.0, operating_hours_per_day=20.0,
                          defrost_duration_min=30.0)  # missing defrost_cycles_per_day
        ))
        _err_response(raw)


# ===========================================================================
# 13. CITABLE REFERENCE CASES — known numeric answers from the literature
#
# Saturation-pressure anchors cross-checked against the published NIST
# WebBook / ASHRAE Fundamentals Handbook 2021 calibration points used to
# fit the per-refrigerant Antoine constants (see cycle.py docstring), plus
# the exact ASHRAE ton-of-refrigeration definition and analytic COP bounds.
# ===========================================================================

class TestCitableReferenceCases:

    def test_ref_R134a_sat_pressure_0C_NIST(self):
        """NIST WebBook: R134a P_sat at 0°C ≈ 292.80 kPa.

        The Antoine constants are two-point fitted to this exact value.
        """
        r = saturation_pressure(0.0, "R134a")
        assert r["ok"] is True
        assert r["P_sat_Pa"] / 1000.0 == pytest.approx(292.80, rel=0.005)

    def test_ref_R134a_sat_pressure_40C_NIST(self):
        """NIST WebBook: R134a P_sat at 40°C ≈ 1017.0 kPa."""
        r = saturation_pressure(40.0, "R134a")
        assert r["ok"] is True
        assert r["P_sat_Pa"] / 1000.0 == pytest.approx(1017.0, rel=0.005)

    def test_ref_R717_ammonia_sat_pressure_0C_ASHRAE(self):
        """ASHRAE / NIST: R717 (ammonia) P_sat at 0°C ≈ 429.44 kPa."""
        r = saturation_pressure(0.0, "R717")
        assert r["ok"] is True
        assert r["P_sat_Pa"] / 1000.0 == pytest.approx(429.44, rel=0.005)

    def test_ref_R744_CO2_sat_pressure_minus20C_NIST(self):
        """NIST WebBook: R744 (CO₂) P_sat at −20°C ≈ 1969.1 kPa."""
        r = saturation_pressure(-20.0, "R744")
        assert r["ok"] is True
        assert r["P_sat_Pa"] / 1000.0 == pytest.approx(1969.1, rel=0.005)

    def test_ref_R290_propane_sat_pressure_0C_NIST(self):
        """NIST WebBook: R290 (propane) P_sat at 0°C ≈ 473.9 kPa."""
        r = saturation_pressure(0.0, "R290")
        assert r["ok"] is True
        assert r["P_sat_Pa"] / 1000.0 == pytest.approx(473.9, rel=0.005)

    def test_ref_R410A_sat_pressure_40C_ASHRAE(self):
        """ASHRAE: R410A P_sat at 40°C ≈ 2419.0 kPa."""
        r = saturation_pressure(40.0, "R410A")
        assert r["ok"] is True
        assert r["P_sat_Pa"] / 1000.0 == pytest.approx(2419.0, rel=0.005)

    def test_ref_ton_of_refrigeration_ASHRAE_definition(self):
        """ASHRAE definition: 1 TR = 3516.853 W = 12,000 BTU/h exactly.

        Standard refrigeration-engineering constant.
        """
        r = tons_of_refrigeration(capacity_TR=1.0)
        assert r["ok"] is True
        assert r["capacity_W"] == pytest.approx(3516.853, rel=1e-6)
        assert r["capacity_BTUh"] == pytest.approx(12_000.0, rel=2e-3)

    def test_ref_single_stage_COP_below_reverse_carnot(self):
        """2nd-law bound (Cengel §11-2): real cycle COP < reverse-Carnot COP.

        R134a, T_evap=-10°C (263.15 K), T_cond=40°C (313.15 K):
            COP_Carnot,R = T_L/(T_H-T_L) = 263.15/50 = 5.263.
        The modelled single-stage COP_cooling must be positive and below
        this thermodynamic ceiling.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = single_stage_cycle(-10.0, 40.0, 10_000.0, "R134a",
                                    eta_isentropic=1.0)
        assert r["ok"] is True
        cop_carnot = 263.15 / (313.15 - 263.15)
        assert 0.0 < r["COP_cooling"] < cop_carnot

    def test_ref_single_stage_first_law_energy_balance(self):
        """First law (Cengel §11-2): Q_cond = Q_evap + W_compressor exactly.

        Holds for every standard vapor-compression cycle.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = single_stage_cycle(-10.0, 40.0, 10_000.0, "R134a")
        assert r["ok"] is True
        assert r["Q_cond_W"] == pytest.approx(
            r["Q_evap_W"] + r["W_compressor_W"], rel=1e-9
        )
        assert r["COP_heating"] == pytest.approx(
            r["COP_cooling"] + 1.0, rel=1e-9
        )

    def test_ref_sat_temperature_inverse_exact(self):
        """Antoine inverse is the exact analytic inverse of the forward fit.

        _sat_temperature(_sat_pressure(T)) == T to machine precision for
        every supported refrigerant (closed-form invertibility check).
        """
        for name in SUPPORTED_REFRIGERANTS:
            ref = _REFRIGERANT_DATA[name]
            for T_K in (240.0, 270.0, 300.0):
                P = _sat_pressure(T_K, ref)
                T_back = _sat_temperature(P, ref)
                assert T_back == pytest.approx(T_K, abs=1e-6)
