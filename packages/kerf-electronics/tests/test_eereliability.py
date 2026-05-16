"""
Hermetic tests for the electronics reliability prediction module.

Covers ≥ 30 tests vs MIL-217F / Coffin-Manson / chi-square hand-calculations.

All tests are self-contained: no network, no filesystem, no external deps.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types
import warnings

# ── Stub kerf_chat.tools.registry so tools.py can be loaded without the server ─
try:
    import kerf_chat as _kc_pkg  # noqa: F401
    import kerf_chat.tools as _kc_tools  # noqa: F401
    import kerf_chat.tools.registry as _kc_real  # noqa: F401
except Exception:
    _kc_real = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type(
    "ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)}
)
_reg_stub.err_payload = lambda msg, code: json.dumps(
    {"ok": False, "error": msg, "code": code}
)
_reg_stub.ok_payload = lambda v: json.dumps({"ok": True, **v})
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kerf_chat_stub = types.ModuleType("kerf_chat")
_kerf_chat_tools_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kerf_chat_stub)
sys.modules.setdefault("kerf_chat.tools", _kerf_chat_tools_stub)
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ is on path ─────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.eereliability.predict import (
    arrhenius_acceleration_factor,
    bathtub_hazard_rate,
    board_fit_and_mtbf,
    coffin_manson_nf,
    derating_check,
    duty_cycle_adjusted_fit,
    mil217f_part_stress,
    mil217f_parts_count,
    mtbf_confidence_bound,
    peck_humidity_acceleration,
    redundancy_mtbf,
    voltage_acceleration,
    _K_B,
    _PI_E,
    _LAMBDA_G,
)

# ── Load tool module via importlib so stub is active ──────────────────────────
_tool_spec_path = os.path.join(
    _SRC, "kerf_electronics", "eereliability", "tools.py"
)
_tool_spec_obj = importlib.util.spec_from_file_location(
    "kerf_electronics.eereliability.tools", _tool_spec_path
)
_tool_mod = importlib.util.module_from_spec(_tool_spec_obj)
_tool_spec_obj.loader.exec_module(_tool_mod)

parts_count_tool = _tool_mod.eerel_mil217f_parts_count
part_stress_tool = _tool_mod.eerel_mil217f_part_stress
board_fit_tool = _tool_mod.eerel_board_fit_mtbf
arrhenius_tool = _tool_mod.eerel_arrhenius_af
coffin_manson_tool = _tool_mod.eerel_coffin_manson
peck_tool = _tool_mod.eerel_peck_humidity
volt_acc_tool = _tool_mod.eerel_voltage_acceleration
derating_tool = _tool_mod.eerel_derating_check
bathtub_tool = _tool_mod.eerel_bathtub
redundancy_tool = _tool_mod.eerel_redundancy_mtbf
conf_tool = _tool_mod.eerel_mtbf_confidence
duty_tool = _tool_mod.eerel_duty_cycle_fit


async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. mil217f_parts_count
# ═══════════════════════════════════════════════════════════════════════════════

class TestPartsCount:
    def test_single_resistor_gf_commercial(self):
        """
        Hand-calc: λ = N · λg · πQ · πE
          = 1 × 0.0023 × 8.0 × 2.0 = 0.0368 FIT
        """
        res = mil217f_parts_count(
            [{"type": "resistor", "count": 1}],
            environment="GF",
            quality="commercial",
        )
        assert res["ok"] is True
        assert math.isclose(res["fit_total"], 0.0023 * 8.0 * 2.0, rel_tol=1e-9)
        assert res["mtbf_hours"] == pytest.approx(1e9 / res["fit_total"])

    def test_count_scales_linearly(self):
        """Doubling count doubles FIT."""
        r1 = mil217f_parts_count([{"type": "capacitor", "count": 1}])
        r10 = mil217f_parts_count([{"type": "capacitor", "count": 10}])
        assert math.isclose(r10["fit_total"], 10 * r1["fit_total"], rel_tol=1e-9)

    def test_pi_e_scales_fit(self):
        """GB (πE=1) vs GF (πE=2) should give 2× ratio."""
        r_gb = mil217f_parts_count([{"type": "ic_digital"}], environment="GB")
        r_gf = mil217f_parts_count([{"type": "ic_digital"}], environment="GF")
        assert math.isclose(r_gf["fit_total"] / r_gb["fit_total"], 2.0, rel_tol=1e-9)

    def test_quality_s_lower_than_commercial(self):
        r_s = mil217f_parts_count([{"type": "resistor"}], quality="S")
        r_c = mil217f_parts_count([{"type": "resistor"}], quality="commercial")
        assert r_s["fit_total"] < r_c["fit_total"]

    def test_empty_parts_error(self):
        res = mil217f_parts_count([])
        assert res["ok"] is False

    def test_unknown_part_type_error(self):
        res = mil217f_parts_count([{"type": "flux_capacitor"}])
        assert res["ok"] is False
        assert "flux_capacitor" in res["reason"]

    def test_unknown_environment_error(self):
        res = mil217f_parts_count([{"type": "resistor"}], environment="ZZ")
        assert res["ok"] is False

    def test_unknown_quality_error(self):
        res = mil217f_parts_count([{"type": "resistor"}], quality="military_grade")
        assert res["ok"] is False

    def test_multi_part_sum(self):
        """Total FIT is sum of individual contributions."""
        r_res = mil217f_parts_count([{"type": "resistor", "count": 2}])
        r_cap = mil217f_parts_count([{"type": "capacitor", "count": 3}])
        r_both = mil217f_parts_count(
            [{"type": "resistor", "count": 2}, {"type": "capacitor", "count": 3}]
        )
        assert math.isclose(
            r_both["fit_total"], r_res["fit_total"] + r_cap["fit_total"], rel_tol=1e-9
        )

    def test_per_part_quality_override(self):
        """Per-part quality overrides board default."""
        r_default = mil217f_parts_count(
            [{"type": "transistor_bjt"}], quality="commercial"
        )
        r_override = mil217f_parts_count(
            [{"type": "transistor_bjt", "quality": "S"}], quality="commercial"
        )
        assert r_override["fit_total"] < r_default["fit_total"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. mil217f_part_stress
# ═══════════════════════════════════════════════════════════════════════════════

class TestPartStress:
    def test_reference_temperature_gives_pi_t_1(self):
        """At tref=40°C, πT should equal 1.0."""
        res = mil217f_part_stress("resistor", tj_c=40.0)
        assert res["ok"] is True
        assert math.isclose(res["pi_t"], 1.0, rel_tol=1e-6)

    def test_higher_temp_increases_pi_t(self):
        r40 = mil217f_part_stress("ic_digital", tj_c=40.0)
        r85 = mil217f_part_stress("ic_digital", tj_c=85.0)
        assert r85["pi_t"] > r40["pi_t"]

    def test_pi_t_arrhenius_hand_calc(self):
        """
        Ea(capacitor) = 0.35 eV, tref = 40°C, tj = 85°C.
        πT = exp(0.35 / 8.617e-5 × (1/313.15 − 1/358.15))
        """
        ea = 0.35
        k = _K_B
        tref = 313.15
        tj = 358.15
        expected = math.exp(ea / k * (1.0 / tref - 1.0 / tj))
        res = mil217f_part_stress("capacitor", tj_c=85.0)
        assert res["ok"] is True
        assert math.isclose(res["pi_t"], expected, rel_tol=1e-6)

    def test_stress_factor_exponent_capacitor(self):
        """Capacitor: πS = (max(vs, ps))^3."""
        res = mil217f_part_stress("capacitor", tj_c=40.0,
                                  voltage_stress=0.4, power_stress=0.3)
        assert math.isclose(res["pi_s"], 0.4 ** 3, rel_tol=1e-9)

    def test_stress_factor_exponent_resistor(self):
        """Resistor: πS = (max(vs, ps))^2."""
        res = mil217f_part_stress("resistor", tj_c=40.0,
                                  voltage_stress=0.5, power_stress=0.5)
        assert math.isclose(res["pi_s"], 0.5 ** 2, rel_tol=1e-9)

    def test_invalid_part_type(self):
        res = mil217f_part_stress("unobtainium", tj_c=50.0)
        assert res["ok"] is False

    def test_invalid_environment(self):
        res = mil217f_part_stress("resistor", tj_c=50.0, environment="XX")
        assert res["ok"] is False

    def test_derating_warning_issued(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = mil217f_part_stress(
                "capacitor", tj_c=40.0, voltage_stress=0.9, power_stress=0.1
            )
        assert res["ok"] is True
        assert len(res["warnings"]) > 0
        assert any("voltage" in str(x.message).lower() for x in w)

    def test_pi_a_multiplier(self):
        r1 = mil217f_part_stress("diode_signal", tj_c=40.0, pi_a=1.0)
        r2 = mil217f_part_stress("diode_signal", tj_c=40.0, pi_a=2.0)
        assert math.isclose(r2["fit"] / r1["fit"], 2.0, rel_tol=1e-9)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. board_fit_and_mtbf
# ═══════════════════════════════════════════════════════════════════════════════

class TestBoardFit:
    def test_single_part_consistent_with_part_stress(self):
        """board_fit_and_mtbf with one part should match mil217f_part_stress."""
        bres = board_fit_and_mtbf(
            [{"type": "resistor", "count": 1, "tj_c": 50.0}]
        )
        pres = mil217f_part_stress("resistor", tj_c=50.0)
        assert bres["ok"] is True
        assert math.isclose(bres["fit_total"], pres["fit"], rel_tol=1e-9)

    def test_count_multiplied_correctly(self):
        b1 = board_fit_and_mtbf([{"type": "ic_digital", "count": 1}])
        b5 = board_fit_and_mtbf([{"type": "ic_digital", "count": 5}])
        assert math.isclose(b5["fit_total"], 5 * b1["fit_total"], rel_tol=1e-9)

    def test_telcordia_note_present(self):
        res = board_fit_and_mtbf([{"type": "resistor"}])
        assert "telcordia_note" in res

    def test_empty_parts_error(self):
        res = board_fit_and_mtbf([])
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. arrhenius_acceleration_factor
# ═══════════════════════════════════════════════════════════════════════════════

class TestArrhenius:
    def test_hand_calc_0_7ev(self):
        """
        Ea = 0.7 eV, T_use = 25°C (298.15 K), T_test = 125°C (398.15 K)
        AF = exp(0.7/8.617e-5 × (1/298.15 − 1/398.15))
        """
        ea = 0.7
        t_use_k = 298.15
        t_test_k = 398.15
        expected = math.exp(ea / _K_B * (1.0 / t_use_k - 1.0 / t_test_k))
        res = arrhenius_acceleration_factor(t_use_c=25.0, t_test_c=125.0, ea_ev=0.7)
        assert res["ok"] is True
        assert math.isclose(res["acceleration_factor"], expected, rel_tol=1e-6)

    def test_same_temp_gives_af_1(self):
        res = arrhenius_acceleration_factor(t_use_c=85.0, t_test_c=85.0, ea_ev=0.7)
        assert res["ok"] is True
        assert math.isclose(res["acceleration_factor"], 1.0, rel_tol=1e-6)

    def test_higher_ea_gives_higher_af(self):
        r_low = arrhenius_acceleration_factor(25.0, 125.0, ea_ev=0.4)
        r_high = arrhenius_acceleration_factor(25.0, 125.0, ea_ev=1.0)
        assert r_high["acceleration_factor"] > r_low["acceleration_factor"]

    def test_zero_ea_error(self):
        res = arrhenius_acceleration_factor(25.0, 125.0, ea_ev=0.0)
        assert res["ok"] is False

    def test_warning_when_test_colder_than_use(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = arrhenius_acceleration_factor(t_use_c=100.0, t_test_c=50.0)
        assert res["ok"] is True
        assert any("acceleration factor" in str(x.message).lower() for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. coffin_manson_nf
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoffinManson:
    def test_hand_calc(self):
        """
        Nf = C_f / (ΔT)^m = 0.005 / (25)^2 = 8e-6 cycles
        lifetime = 8e-6 / (1 × 365.25) years
        """
        nf_expected = 0.005 / (25.0 ** 2)
        res = coffin_manson_nf(delta_t_c=25.0, c_f=0.005, m=2.0, f_cyc_per_day=1.0)
        assert res["ok"] is True
        assert math.isclose(res["nf_cycles"], nf_expected, rel_tol=1e-9)
        assert math.isclose(
            res["lifetime_years"], nf_expected / 365.25, rel_tol=1e-6
        )

    def test_larger_delta_t_fewer_cycles(self):
        r_small = coffin_manson_nf(10.0)
        r_large = coffin_manson_nf(50.0)
        assert r_large["nf_cycles"] < r_small["nf_cycles"]

    def test_larger_m_steeper_sensitivity(self):
        r_m2 = coffin_manson_nf(20.0, m=2.0)
        r_m3 = coffin_manson_nf(20.0, m=3.0)
        # Higher m → fewer cycles (stronger ΔT sensitivity)
        assert r_m3["nf_cycles"] < r_m2["nf_cycles"]

    def test_higher_cycling_frequency_shorter_lifetime(self):
        r1 = coffin_manson_nf(10.0, f_cyc_per_day=1.0)
        r5 = coffin_manson_nf(10.0, f_cyc_per_day=5.0)
        assert math.isclose(r5["lifetime_years"], r1["lifetime_years"] / 5.0, rel_tol=1e-9)

    def test_zero_delta_t_error(self):
        res = coffin_manson_nf(delta_t_c=0.0)
        assert res["ok"] is False

    def test_negative_delta_t_error(self):
        res = coffin_manson_nf(delta_t_c=-5.0)
        assert res["ok"] is False

    def test_warning_short_lifetime(self):
        """A huge ΔT will produce < 1 yr lifetime and trigger a warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = coffin_manson_nf(delta_t_c=200.0, c_f=0.005, m=2.0, f_cyc_per_day=10.0)
        assert res["ok"] is True
        assert any("lifetime" in str(x.message).lower() for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. peck_humidity_acceleration
# ═══════════════════════════════════════════════════════════════════════════════

class TestPeck:
    def test_hand_calc(self):
        """
        AF = (85/60)^2.7 × exp(0.9/k × (1/T_use − 1/T_test))
        T_use = 25°C = 298.15 K, T_test = 85°C = 358.15 K
        """
        rh_factor = (85.0 / 60.0) ** 2.7
        t_factor = math.exp(0.9 / _K_B * (1.0 / 298.15 - 1.0 / 358.15))
        expected = rh_factor * t_factor
        res = peck_humidity_acceleration(
            rh_use=60.0, rh_test=85.0, t_use_c=25.0, t_test_c=85.0,
            ea_ev=0.9, n_rh=2.7
        )
        assert res["ok"] is True
        assert math.isclose(res["acceleration_factor"], expected, rel_tol=1e-6)
        assert math.isclose(res["humidity_factor"], rh_factor, rel_tol=1e-9)
        assert math.isclose(res["thermal_factor"], t_factor, rel_tol=1e-6)

    def test_invalid_rh_zero(self):
        res = peck_humidity_acceleration(0.0, 85.0, 25.0, 85.0)
        assert res["ok"] is False

    def test_invalid_rh_over_100(self):
        res = peck_humidity_acceleration(50.0, 110.0, 25.0, 85.0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7. voltage_acceleration
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoltageAcceleration:
    def test_hand_calc(self):
        """AF = (20/10)^2.5 = 2^2.5 = 5.656..."""
        expected = 2.0 ** 2.5
        res = voltage_acceleration(v_use=10.0, v_test=20.0, beta=2.5)
        assert res["ok"] is True
        assert math.isclose(res["acceleration_factor"], expected, rel_tol=1e-9)

    def test_same_voltage_af_1(self):
        res = voltage_acceleration(v_use=12.0, v_test=12.0, beta=3.0)
        assert math.isclose(res["acceleration_factor"], 1.0, rel_tol=1e-9)

    def test_beta_scales_af(self):
        r2 = voltage_acceleration(10.0, 20.0, beta=2.0)
        r4 = voltage_acceleration(10.0, 20.0, beta=4.0)
        assert r4["acceleration_factor"] > r2["acceleration_factor"]

    def test_zero_v_use_error(self):
        res = voltage_acceleration(v_use=0.0, v_test=10.0)
        assert res["ok"] is False

    def test_warning_overstress(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = voltage_acceleration(v_use=5.0, v_test=15.0)  # ratio = 3×
        assert res["ok"] is True
        assert any("over-stress" in str(x.message).lower() for x in w)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. derating_check
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeratingCheck:
    def test_compliant_capacitor(self):
        """Capacitor at 40% voltage, 60% temp → compliant."""
        res = derating_check("capacitor", voltage_ratio=0.40, temperature_ratio=0.60)
        assert res["ok"] is True
        assert res["compliant"] is True
        assert res["violations"] == []

    def test_violation_capacitor_voltage(self):
        """Capacitor at 90% voltage → violation (limit 0.50)."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = derating_check("capacitor", voltage_ratio=0.90)
        assert res["ok"] is True
        assert res["compliant"] is False
        assert any(v["param"] == "voltage" for v in res["violations"])
        assert any("voltage" in str(x.message).lower() for x in w)

    def test_none_ratios_skipped(self):
        """Unspecified ratios are not checked."""
        res = derating_check("transistor_bjt")
        assert res["ok"] is True
        assert res["compliant"] is True

    def test_unknown_part_type_error(self):
        res = derating_check("alien_device")
        assert res["ok"] is False

    def test_multiple_violations(self):
        """Transistor over both voltage and power limits."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            res = derating_check(
                "transistor_bjt", voltage_ratio=0.9, power_ratio=0.8
            )
        assert res["ok"] is True
        params = [v["param"] for v in res["violations"]]
        assert "voltage" in params
        assert "power" in params


# ═══════════════════════════════════════════════════════════════════════════════
# 9. bathtub_hazard_rate
# ═══════════════════════════════════════════════════════════════════════════════

class TestBathtub:
    def test_phase_detection_infant(self):
        res = bathtub_hazard_rate(t_hours=10.0)
        assert res["ok"] is True
        assert res["phase"] == "infant_mortality"

    def test_phase_detection_random(self):
        res = bathtub_hazard_rate(t_hours=1000.0)
        assert res["phase"] == "random"

    def test_phase_detection_wearout(self):
        res = bathtub_hazard_rate(t_hours=100000.0)
        assert res["phase"] == "wearout"

    def test_t_zero(self):
        res = bathtub_hazard_rate(t_hours=0.0)
        assert res["ok"] is True
        assert res["lambda_fit"] > 0

    def test_negative_t_error(self):
        res = bathtub_hazard_rate(t_hours=-1.0)
        assert res["ok"] is False

    def test_lambda_fit_positive(self):
        for t in [1.0, 100.0, 1000.0, 50000.0, 200000.0]:
            res = bathtub_hazard_rate(t_hours=t)
            assert res["lambda_fit"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. redundancy_mtbf
# ═══════════════════════════════════════════════════════════════════════════════

class TestRedundancy:
    def test_active_2_of_2_hand_calc(self):
        """
        Active 2-of-2: MTBF_sys = MTBF_unit × (1 + 1/2) = 1.5 × MTBF_unit
        """
        fit = 100.0
        mtbf_unit = 1e9 / fit
        expected = mtbf_unit * (1.0 + 0.5)
        res = redundancy_mtbf(fit_per_unit=fit, n_active=2, redundancy_type="active")
        assert res["ok"] is True
        assert math.isclose(res["mtbf_system_hours"], expected, rel_tol=1e-9)
        assert math.isclose(res["mtbf_unit_hours"], mtbf_unit, rel_tol=1e-9)

    def test_active_1_unit_equals_unit_mtbf(self):
        """Single active unit: MTBF_sys = MTBF_unit."""
        fit = 50.0
        res = redundancy_mtbf(fit_per_unit=fit, n_active=1, redundancy_type="active")
        assert math.isclose(res["mtbf_system_hours"], res["mtbf_unit_hours"], rel_tol=1e-9)

    def test_standby_hand_calc(self):
        """
        Standby 2 units, Rs=0.99:
        MTBF_sys = MTBF_unit × 2 × 0.99
        """
        fit = 100.0
        mtbf_unit = 1e9 / fit
        expected = mtbf_unit * 2 * 0.99
        res = redundancy_mtbf(
            fit_per_unit=fit, n_active=2, redundancy_type="standby",
            switch_reliability=0.99
        )
        assert res["ok"] is True
        assert math.isclose(res["mtbf_system_hours"], expected, rel_tol=1e-9)

    def test_invalid_fit_zero(self):
        res = redundancy_mtbf(fit_per_unit=0.0)
        assert res["ok"] is False

    def test_invalid_redundancy_type(self):
        res = redundancy_mtbf(fit_per_unit=100.0, redundancy_type="warm")
        assert res["ok"] is False

    def test_active_more_units_higher_mtbf(self):
        r2 = redundancy_mtbf(100.0, n_active=2)
        r4 = redundancy_mtbf(100.0, n_active=4)
        assert r4["mtbf_system_hours"] > r2["mtbf_system_hours"]


# ═══════════════════════════════════════════════════════════════════════════════
# 11. mtbf_confidence_bound
# ═══════════════════════════════════════════════════════════════════════════════

class TestMtbfConfidence:
    def test_lower_bound_zero_failures(self):
        """
        Lower bound, 0 failures, CL=0.90:
        df = 2×0+2 = 2; MTBF_lower = 2T / χ²(2, 0.10)
        χ²(2, 0.90) ≈ 4.605 (exact: −2 ln(0.10))
        MTBF_lower = 2 × 1000 / 4.605 ≈ 434.3 h
        """
        res = mtbf_confidence_bound(
            total_hours=1000.0, n_failures=0, confidence=0.90, bound="lower"
        )
        assert res["ok"] is True
        # χ²(2, 0.90) exact = -2×ln(0.10) = 4.6052
        chi2_exact = -2.0 * math.log(0.10)
        expected = 2.0 * 1000.0 / chi2_exact
        assert math.isclose(res["mtbf_bound_hours"], expected, rel_tol=0.01)

    def test_lower_bound_with_failures_lower_than_no_failures(self):
        """More failures → lower MTBF bound."""
        r0 = mtbf_confidence_bound(1000.0, n_failures=0)
        r3 = mtbf_confidence_bound(1000.0, n_failures=3)
        assert r3["mtbf_bound_hours"] < r0["mtbf_bound_hours"]

    def test_higher_confidence_gives_lower_lower_bound(self):
        r90 = mtbf_confidence_bound(1000.0, 1, confidence=0.90)
        r99 = mtbf_confidence_bound(1000.0, 1, confidence=0.99)
        assert r99["mtbf_bound_hours"] < r90["mtbf_bound_hours"]

    def test_upper_bound_zero_failures_error(self):
        res = mtbf_confidence_bound(1000.0, n_failures=0, bound="upper")
        assert res["ok"] is False

    def test_upper_bound_above_lower_bound(self):
        lower = mtbf_confidence_bound(5000.0, n_failures=2, bound="lower")
        upper = mtbf_confidence_bound(5000.0, n_failures=2, bound="upper")
        assert upper["mtbf_bound_hours"] > lower["mtbf_bound_hours"]

    def test_more_test_hours_higher_bound(self):
        r1k = mtbf_confidence_bound(1000.0, 0)
        r10k = mtbf_confidence_bound(10000.0, 0)
        assert r10k["mtbf_bound_hours"] > r1k["mtbf_bound_hours"]

    def test_invalid_total_hours(self):
        res = mtbf_confidence_bound(total_hours=0.0, n_failures=0)
        assert res["ok"] is False

    def test_confidence_out_of_range(self):
        res = mtbf_confidence_bound(1000.0, 0, confidence=1.1)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 12. duty_cycle_adjusted_fit
# ═══════════════════════════════════════════════════════════════════════════════

class TestDutyCycle:
    def test_50_percent_duty(self):
        """50% duty: adjusted FIT = 0.5 × rated FIT."""
        res = duty_cycle_adjusted_fit(fit_rated=200.0, duty_cycle=0.5)
        assert res["ok"] is True
        assert math.isclose(res["fit_adjusted"], 100.0, rel_tol=1e-9)
        assert math.isclose(res["mtbf_calendar_hours"], 1e9 / 100.0, rel_tol=1e-9)

    def test_full_duty_no_change(self):
        res = duty_cycle_adjusted_fit(fit_rated=500.0, duty_cycle=1.0)
        assert math.isclose(res["fit_adjusted"], 500.0, rel_tol=1e-9)

    def test_mtbf_years_consistent(self):
        res = duty_cycle_adjusted_fit(100.0, 0.25, calendar_hours_per_year=8760.0)
        assert math.isclose(
            res["mtbf_calendar_years"],
            res["mtbf_calendar_hours"] / 8760.0,
            rel_tol=1e-9,
        )

    def test_power_on_hours(self):
        res = duty_cycle_adjusted_fit(100.0, 0.25, calendar_hours_per_year=8760.0)
        assert math.isclose(res["power_on_hours_per_year"], 0.25 * 8760.0, rel_tol=1e-9)

    def test_zero_fit_error(self):
        res = duty_cycle_adjusted_fit(fit_rated=0.0, duty_cycle=0.5)
        assert res["ok"] is False

    def test_zero_duty_error(self):
        res = duty_cycle_adjusted_fit(fit_rated=100.0, duty_cycle=0.0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 13. LLM tool handlers (stub registry)
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolHandlers:
    @pytest.mark.asyncio
    async def test_parts_count_tool_ok(self):
        res = await call(
            parts_count_tool,
            parts=[{"type": "resistor", "count": 5}],
            environment="GF",
            quality="commercial",
        )
        assert res["ok"] is True
        assert "fit_total" in res

    @pytest.mark.asyncio
    async def test_part_stress_tool_ok(self):
        res = await call(part_stress_tool, part_type="capacitor", tj_c=60.0)
        assert res["ok"] is True
        assert "fit" in res

    @pytest.mark.asyncio
    async def test_board_fit_tool_ok(self):
        res = await call(
            board_fit_tool,
            parts=[{"type": "ic_digital", "count": 2, "tj_c": 70.0}],
        )
        assert res["ok"] is True
        assert "mtbf_hours" in res

    @pytest.mark.asyncio
    async def test_arrhenius_tool_ok(self):
        res = await call(arrhenius_tool, t_use_c=25.0, t_test_c=125.0, ea_ev=0.7)
        assert res["ok"] is True
        assert "acceleration_factor" in res

    @pytest.mark.asyncio
    async def test_coffin_manson_tool_ok(self):
        res = await call(coffin_manson_tool, delta_t_c=30.0)
        assert res["ok"] is True
        assert "nf_cycles" in res

    @pytest.mark.asyncio
    async def test_peck_tool_ok(self):
        res = await call(peck_tool, rh_use=60.0, rh_test=85.0,
                         t_use_c=25.0, t_test_c=85.0)
        assert res["ok"] is True
        assert "acceleration_factor" in res

    @pytest.mark.asyncio
    async def test_volt_acc_tool_ok(self):
        res = await call(volt_acc_tool, v_use=12.0, v_test=20.0, beta=2.5)
        assert res["ok"] is True
        assert "acceleration_factor" in res

    @pytest.mark.asyncio
    async def test_derating_tool_ok(self):
        res = await call(derating_tool, part_type="capacitor", voltage_ratio=0.4)
        assert res["ok"] is True
        assert "compliant" in res

    @pytest.mark.asyncio
    async def test_bathtub_tool_ok(self):
        res = await call(bathtub_tool, t_hours=1000.0)
        assert res["ok"] is True
        assert "lambda_fit" in res

    @pytest.mark.asyncio
    async def test_redundancy_tool_ok(self):
        res = await call(redundancy_tool, fit_per_unit=100.0, n_active=2)
        assert res["ok"] is True
        assert "mtbf_system_hours" in res

    @pytest.mark.asyncio
    async def test_conf_tool_ok(self):
        res = await call(conf_tool, total_hours=5000.0, n_failures=1)
        assert res["ok"] is True
        assert "mtbf_bound_hours" in res

    @pytest.mark.asyncio
    async def test_duty_tool_ok(self):
        res = await call(duty_tool, fit_rated=100.0, duty_cycle=0.5)
        assert res["ok"] is True
        assert "fit_adjusted" in res

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        result = await parts_count_tool(None, b"not valid json {{{")
        parsed = json.loads(result)
        # Real registry err_payload has no "ok" key; stub includes it
        assert parsed.get("ok") is False or "error" in parsed

    @pytest.mark.asyncio
    async def test_bad_part_type_returns_error(self):
        res = await call(
            parts_count_tool,
            parts=[{"type": "unobtainium"}],
            environment="GF",
        )
        # Real registry err_payload has no "ok" key; stub includes it
        assert res.get("ok") is False or "error" in res
