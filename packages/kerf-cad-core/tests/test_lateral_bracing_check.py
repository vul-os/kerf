"""
Tests for kerf_cad_core.arch.lateral_bracing_check — AISC 360-22 §F2 LTB.

All tests are hermetic (no OCC, no DB, no network).
All dimensions in mm and MPa; moments in kN·m.

Reference section: W14x90 (AISC Manual 15e, Table 1-1, imperial)
  d  = 14.0 in, tf = 0.710 in → ho = d − tf = 13.29 in = 337.57 mm
  Sx = 143 in³  → 2 343 350 mm³
  Zx = 157 in³  → 2 572 769 mm³
  ry =  3.70 in → 93.98 mm
  J  =  4.06 in⁴ → 1 689 900 mm⁴
  Iy = 362 in⁴, Cw = 16 000 in⁶ → rts ≈ 4.102 in = 104.20 mm (AISC F2-7)
  Fy = 345 MPa (A992), E = 200 000 MPa

Hand-computed benchmarks (Python-verified):
  Lp  = 1.76 × 93.98 × √(200 000/345) = 3 982.5 mm ≈ 3.98 m
  Lr  = 12 962 mm ≈ 12.96 m
  Mp  = 345 × 2 572 769 / 1e6 = 887.6 kN·m
  Mr  = 0.7 × 345 × 2 343 350 / 1e6 = 565.9 kN·m

Coverage:
  1.  Lp ≈ 3 982 mm (±1 %)
  2.  Lr ≈ 12 962 mm (±3 %)
  3.  Mp ≈ 887.6 kN·m (±0.1 %)
  4.  Mr = 0.7·Fy·Sx ≈ 565.9 kN·m (±0.1 %)
  5.  Lb = 2 000 mm < Lp → mode = "yielding"; Mn = Mp
  6.  Lb = 8 000 mm (Lp < Lb < Lr) → mode = "inelastic_LTB"; Mn < Mp
  7.  Lb = 15 000 mm > Lr → mode = "elastic_LTB"; Mn < Mr
  8.  Inelastic LTB Mn formula: manually computed ramp value matches
  9.  Elastic LTB Mn formula: Fcr × Sx manually computed
  10. Cb = 1.14 amplifies inelastic LTB but is capped at Mp
  11. Cb = 2.0 in inelastic zone → Mn capped at Mp (never exceeds plastic)
  12. Cb = 1.5 in elastic zone → Mn amplified but capped at Mp
  13. Lb_to_Lp_ratio correct for yielding case
  14. ValueError: S_x_mm3 <= 0
  15. ValueError: Z_x_mm3 <= 0
  16. ValueError: r_y_mm <= 0
  17. ValueError: J_mm4 <= 0
  18. ValueError: h_o_mm <= 0
  19. ValueError: L_b_mm <= 0
  20. ValueError: Cb < 1.0
  21. LLM tool (async): valid W14x90 Lb=2m → ok, yielding
  22. LLM tool (async): valid W14x90 Lb=8m → ok, inelastic_LTB
  23. LLM tool (async): valid W14x90 Lb=15m → ok, elastic_LTB
  24. LLM tool (async): missing required field → err BAD_ARGS
  25. LLM tool (async): negative L_b_mm → err BAD_ARGS
  26. Re-export from arch/__init__.py
  27. phi_Mn = 0.90 * Mn for all three zones
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.arch.lateral_bracing_check import (
    WSectionSpec,
    LateralBracingReport,
    check_lateral_bracing,
)
from kerf_cad_core.arch.lateral_bracing_check_tools import (
    run_arch_check_lateral_bracing,
)


# ---------------------------------------------------------------------------
# W14x90 reference section properties (AISC Manual 15e Table 1-1, SI)
# ---------------------------------------------------------------------------

_IN_TO_MM = 25.4
_IN3_TO_MM3 = _IN_TO_MM ** 3
_IN4_TO_MM4 = _IN_TO_MM ** 4

# Imperial values (Table 1-1)
_Sx_in3 = 143.0
_Zx_in3 = 157.0
_ry_in = 3.70
_J_in4 = 4.06
_d_in = 14.0
_tf_in = 0.710
_Iy_in4 = 362.0
_Cw_in6 = 16_000.0

# Convert
_Sx = _Sx_in3 * _IN3_TO_MM3        # mm³
_Zx = _Zx_in3 * _IN3_TO_MM3        # mm³
_ry = _ry_in * _IN_TO_MM             # mm
_J  = _J_in4  * _IN4_TO_MM4         # mm⁴
_ho = (_d_in - _tf_in) * _IN_TO_MM  # mm  (distance between flange centroids ≈ d - tf)

# rts = √(√(Iy·Cw) / Sx)  AISC Eq. F2-7
_rts = math.sqrt(
    math.sqrt(_Iy_in4 * _Cw_in6) / _Sx_in3
) * _IN_TO_MM  # mm

_Fy = 345.0    # MPa (A992)
_E  = 200_000.0  # MPa


def _w14x90(ry_ts_mm: float | None = _rts) -> WSectionSpec:
    return WSectionSpec(
        section_label="W14x90",
        S_x_mm3=_Sx,
        Z_x_mm3=_Zx,
        r_y_mm=_ry,
        J_mm4=_J,
        h_o_mm=_ho,
        Fy_MPa=_Fy,
        E_MPa=_E,
        ry_TS_mm=ry_ts_mm,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _tool(args_dict: dict) -> dict:
    raw = _run(run_arch_check_lateral_bracing(None, json.dumps(args_dict).encode()))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Helper: expected hand-computed Lp / Lr
# ---------------------------------------------------------------------------

def _expected_Lp() -> float:
    return 1.76 * _ry * math.sqrt(_E / _Fy)


def _expected_Lr() -> float:
    c = 1.0
    JcSxho = _J * c / (_Sx * _ho)
    inner = math.sqrt(JcSxho**2 + 6.76 * (0.7 * _Fy / _E) ** 2)
    return 1.95 * _rts * (_E / (0.7 * _Fy)) * math.sqrt(JcSxho + inner)


# ===========================================================================
# Test class 1: Limiting lengths and moments
# ===========================================================================

class TestLimitingLengths:
    """Tests 1–4: Lp, Lr, Mp, Mr."""

    def test_01_lp_approx_4m(self):
        """Test 1: Lp ≈ 3 982 mm (within 1% of formula)."""
        spec = _w14x90()
        report = check_lateral_bracing(spec, L_b_mm=1_000.0)
        expected = _expected_Lp()
        assert abs(report.L_p_mm - expected) / expected < 0.001

    def test_02_lr_approx_13m(self):
        """Test 2: Lr ≈ 12 962 mm (within 3% — AISC Table 3-2 is ≈ 13 m)."""
        spec = _w14x90()
        report = check_lateral_bracing(spec, L_b_mm=1_000.0)
        expected = _expected_Lr()
        assert abs(report.L_r_mm - expected) / expected < 0.001, (
            f"Lr = {report.L_r_mm:.0f} mm, expected ≈ {expected:.0f} mm"
        )
        # Also check it is between 12 000 and 14 000 mm (AISC Manual Table 3-2)
        assert 12_000 < report.L_r_mm < 14_000

    def test_03_mp_kNm(self):
        """Test 3: Mp = Fy·Zx ≈ 887.6 kN·m (within 0.1 %)."""
        spec = _w14x90()
        report = check_lateral_bracing(spec, L_b_mm=1_000.0)
        expected_Mp = _Fy * _Zx / 1.0e6
        assert abs(report.Mp_kNm - expected_Mp) / expected_Mp < 0.001

    def test_04_mr_kNm(self):
        """Test 4: Mr = 0.7·Fy·Sx ≈ 565.9 kN·m (within 0.1 %)."""
        spec = _w14x90()
        report = check_lateral_bracing(spec, L_b_mm=1_000.0)
        expected_Mr = 0.7 * _Fy * _Sx / 1.0e6
        assert abs(report.Mr_kNm - expected_Mr) / expected_Mr < 0.001


# ===========================================================================
# Test class 2: Governing modes
# ===========================================================================

class TestGoverningModes:
    """Tests 5–7: mode detection for Lb < Lp, Lp < Lb < Lr, Lb > Lr."""

    def test_05_lb_2m_yielding(self):
        """Test 5: Lb = 2 000 mm < Lp ≈ 3 983 mm → yielding; Mn = Mp."""
        spec = _w14x90()
        report = check_lateral_bracing(spec, L_b_mm=2_000.0)
        assert report.governing_mode == "yielding"
        assert abs(report.Mn_kNm - report.Mp_kNm) < 0.001

    def test_06_lb_8m_inelastic_ltb(self):
        """Test 6: Lb = 8 000 mm (between Lp and Lr) → inelastic_LTB; Mn < Mp."""
        spec = _w14x90()
        Lp = _expected_Lp()
        Lr = _expected_Lr()
        assert Lp < 8_000.0 < Lr, "Pre-condition: Lb must be in inelastic zone"
        report = check_lateral_bracing(spec, L_b_mm=8_000.0)
        assert report.governing_mode == "inelastic_LTB"
        assert report.Mn_kNm < report.Mp_kNm

    def test_07_lb_15m_elastic_ltb(self):
        """Test 7: Lb = 15 000 mm > Lr ≈ 12 962 mm → elastic_LTB; Mn < Mr."""
        spec = _w14x90()
        Lr = _expected_Lr()
        assert 15_000.0 > Lr, "Pre-condition: Lb must be in elastic zone"
        report = check_lateral_bracing(spec, L_b_mm=15_000.0)
        assert report.governing_mode == "elastic_LTB"
        assert report.Mn_kNm < report.Mr_kNm


# ===========================================================================
# Test class 3: Formula fidelity
# ===========================================================================

class TestFormulas:
    """Tests 8–9: numeric checks against hand-computed Mn values."""

    def test_08_inelastic_ltb_formula(self):
        """Test 8: Mn for Lb = 8 000 mm matches AISC F2-2 hand computation (within 0.01 %)."""
        spec = _w14x90()
        Lp = _expected_Lp()
        Lr = _expected_Lr()
        Mp = _Fy * _Zx / 1.0e6
        Mr = 0.7 * _Fy * _Sx / 1.0e6
        Lb = 8_000.0
        Cb = 1.0
        ramp = (Lb - Lp) / (Lr - Lp)
        expected_Mn = min(Cb * (Mp - (Mp - Mr) * ramp), Mp)

        report = check_lateral_bracing(spec, L_b_mm=Lb, Cb=Cb)
        assert abs(report.Mn_kNm - expected_Mn) / expected_Mn < 0.0001

    def test_09_elastic_ltb_formula(self):
        """Test 9: Mn for Lb = 15 000 mm matches AISC F2-3/F2-4 hand computation (within 0.01 %)."""
        spec = _w14x90()
        Sx = _Sx
        J = _J
        ho = _ho
        rts = _rts
        E = _E
        Fy = _Fy
        Lb = 15_000.0
        c = 1.0
        Cb = 1.0
        LbOrts = Lb / rts
        Fcr = (
            Cb * math.pi**2 * E / LbOrts**2
            * math.sqrt(1.0 + 0.078 * J * c / (Sx * ho) * LbOrts**2)
        )
        Mp = Fy * _Zx / 1.0e6
        expected_Mn = min(Fcr * Sx / 1.0e6, Mp)

        report = check_lateral_bracing(spec, L_b_mm=Lb, Cb=Cb)
        assert abs(report.Mn_kNm - expected_Mn) / expected_Mn < 0.0001


# ===========================================================================
# Test class 4: Cb behaviour
# ===========================================================================

class TestCbAmplification:
    """Tests 10–12: Cb amplification and Mp cap."""

    def test_10_cb_amplifies_inelastic_ltb(self):
        """Test 10: Cb = 1.14 increases Mn in inelastic zone."""
        spec = _w14x90()
        Lb = 8_000.0
        r1 = check_lateral_bracing(spec, L_b_mm=Lb, Cb=1.0)
        r2 = check_lateral_bracing(spec, L_b_mm=Lb, Cb=1.14)
        assert r2.Mn_kNm > r1.Mn_kNm
        assert r2.governing_mode == "inelastic_LTB"

    def test_11_cb_capped_at_mp_inelastic(self):
        """Test 11: Cb = 2.0 in inelastic zone → Mn capped at Mp."""
        spec = _w14x90()
        Lb = 4_500.0  # just above Lp; Cb=2.0 would otherwise exceed Mp
        report = check_lateral_bracing(spec, L_b_mm=Lb, Cb=2.0)
        assert report.Mn_kNm <= report.Mp_kNm + 1e-9
        assert abs(report.Mn_kNm - report.Mp_kNm) < 1e-6  # should be capped

    def test_12_cb_amplifies_elastic_ltb(self):
        """Test 12: Cb = 1.5 in elastic zone → Mn amplified compared to Cb=1.0."""
        spec = _w14x90()
        Lb = 15_000.0
        r1 = check_lateral_bracing(spec, L_b_mm=Lb, Cb=1.0)
        r2 = check_lateral_bracing(spec, L_b_mm=Lb, Cb=1.5)
        assert r2.Mn_kNm > r1.Mn_kNm
        # Both must still be ≤ Mp
        assert r2.Mn_kNm <= r2.Mp_kNm + 1e-9


# ===========================================================================
# Test class 5: Derived fields
# ===========================================================================

class TestDerivedFields:
    """Tests 13, 27: Lb_to_Lp_ratio and phi_Mn."""

    def test_13_lb_to_lp_ratio(self):
        """Test 13: Lb_to_Lp_ratio = Lb / Lp for yielding case."""
        spec = _w14x90()
        Lb = 2_000.0
        report = check_lateral_bracing(spec, L_b_mm=Lb)
        Lp = _expected_Lp()
        expected_ratio = Lb / Lp
        assert abs(report.Lb_to_Lp_ratio - expected_ratio) / expected_ratio < 0.001

    def test_27_phi_mn_equals_090_mn(self):
        """Test 27: phi_Mn = 0.90 * Mn for all three zones."""
        spec = _w14x90()
        for Lb in [2_000.0, 8_000.0, 15_000.0]:
            report = check_lateral_bracing(spec, L_b_mm=Lb)
            assert abs(report.phi_Mn_kNm - 0.90 * report.Mn_kNm) < 0.0001, (
                f"phi_Mn mismatch at Lb={Lb}: {report.phi_Mn_kNm} vs {0.90 * report.Mn_kNm}"
            )


# ===========================================================================
# Test class 6: ValueError guards
# ===========================================================================

class TestValueErrors:
    """Tests 14–20: Input validation errors."""

    def _base_args(self):
        return dict(
            section_label="W14x90",
            S_x_mm3=_Sx,
            Z_x_mm3=_Zx,
            r_y_mm=_ry,
            J_mm4=_J,
            h_o_mm=_ho,
            Fy_MPa=_Fy,
            E_MPa=_E,
            ry_TS_mm=_rts,
        )

    def test_14_zero_sx(self):
        """Test 14: S_x_mm3 = 0 → ValueError."""
        kw = self._base_args()
        kw["S_x_mm3"] = 0.0
        with pytest.raises(ValueError, match="S_x_mm3"):
            check_lateral_bracing(WSectionSpec(**kw), L_b_mm=1_000.0)

    def test_15_zero_zx(self):
        """Test 15: Z_x_mm3 = 0 → ValueError."""
        kw = self._base_args()
        kw["Z_x_mm3"] = 0.0
        with pytest.raises(ValueError, match="Z_x_mm3"):
            check_lateral_bracing(WSectionSpec(**kw), L_b_mm=1_000.0)

    def test_16_zero_ry(self):
        """Test 16: r_y_mm = 0 → ValueError."""
        kw = self._base_args()
        kw["r_y_mm"] = 0.0
        with pytest.raises(ValueError, match="r_y_mm"):
            check_lateral_bracing(WSectionSpec(**kw), L_b_mm=1_000.0)

    def test_17_zero_J(self):
        """Test 17: J_mm4 = 0 → ValueError."""
        kw = self._base_args()
        kw["J_mm4"] = 0.0
        with pytest.raises(ValueError, match="J_mm4"):
            check_lateral_bracing(WSectionSpec(**kw), L_b_mm=1_000.0)

    def test_18_zero_ho(self):
        """Test 18: h_o_mm = 0 → ValueError."""
        kw = self._base_args()
        kw["h_o_mm"] = 0.0
        with pytest.raises(ValueError, match="h_o_mm"):
            check_lateral_bracing(WSectionSpec(**kw), L_b_mm=1_000.0)

    def test_19_zero_lb(self):
        """Test 19: L_b_mm = 0 → ValueError."""
        with pytest.raises(ValueError, match="L_b_mm"):
            check_lateral_bracing(_w14x90(), L_b_mm=0.0)

    def test_20_cb_below_one(self):
        """Test 20: Cb = 0.8 < 1.0 → ValueError."""
        with pytest.raises(ValueError, match="Cb"):
            check_lateral_bracing(_w14x90(), L_b_mm=5_000.0, Cb=0.8)


# ===========================================================================
# Test class 7: LLM tool
# ===========================================================================

class TestLLMTool:
    """Tests 21–25: tool handler ok/err payloads."""

    def _base_payload(self, L_b_mm: float) -> dict:
        return {
            "section_label": "W14x90",
            "S_x_mm3": _Sx,
            "Z_x_mm3": _Zx,
            "r_y_mm": _ry,
            "J_mm4": _J,
            "h_o_mm": _ho,
            "L_b_mm": L_b_mm,
            "Fy_MPa": _Fy,
            "E_MPa": _E,
            "ry_TS_mm": _rts,
        }

    def test_21_tool_lb_2m_yielding(self):
        """Test 21: LLM tool Lb=2m → no error, yielding mode."""
        result = _tool(self._base_payload(2_000.0))
        assert "error" not in result, f"Unexpected error: {result}"
        assert result["governing_mode"] == "yielding"
        assert result["Mn_kNm"] > 0

    def test_22_tool_lb_8m_inelastic(self):
        """Test 22: LLM tool Lb=8m → no error, inelastic_LTB mode."""
        result = _tool(self._base_payload(8_000.0))
        assert "error" not in result, f"Unexpected error: {result}"
        assert result["governing_mode"] == "inelastic_LTB"

    def test_23_tool_lb_15m_elastic(self):
        """Test 23: LLM tool Lb=15m → no error, elastic_LTB mode."""
        result = _tool(self._base_payload(15_000.0))
        assert "error" not in result, f"Unexpected error: {result}"
        assert result["governing_mode"] == "elastic_LTB"

    def test_24_tool_missing_field(self):
        """Test 24: Missing required field (L_b_mm) → err BAD_ARGS."""
        payload = self._base_payload(5_000.0)
        del payload["L_b_mm"]
        result = _tool(payload)
        assert "error" in result, f"Expected error response, got: {result}"
        assert result.get("code") == "BAD_ARGS"

    def test_25_tool_negative_lb(self):
        """Test 25: Negative L_b_mm → err BAD_ARGS."""
        payload = self._base_payload(-1_000.0)
        result = _tool(payload)
        assert "error" in result, f"Expected error response, got: {result}"
        assert result.get("code") == "BAD_ARGS"


# ===========================================================================
# Test class 8: Re-export
# ===========================================================================

class TestReexport:
    """Test 26: Public API re-exported from kerf_cad_core.arch."""

    def test_26_reexport_from_arch_init(self):
        """Test 26: WSectionSpec, LateralBracingReport, check_lateral_bracing in arch/__init__.py."""
        from kerf_cad_core.arch import (
            WSectionSpec as WS,
            LateralBracingReport as LBR,
            check_lateral_bracing as clb,
        )
        assert WS is WSectionSpec
        assert LBR is LateralBracingReport
        assert clb is check_lateral_bracing
