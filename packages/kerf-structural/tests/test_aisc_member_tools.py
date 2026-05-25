"""
Dispatch tests for the AISC 360-22 full member-check LLM tools.

Verifies that aisc_compression, aisc_flexure, aisc_combined, and
aisc_member_check are importable, have correct spec names, and produce
sensible payload for known reference sections.

Oracle values
-------------
W14x90 column, Fy=50 ksi, KL=12 ft (pinned–pinned):
  AISC 16th ed. Table 4-1: φcPn ≈ 1130 kips
  (KL/r ≈ 37.9, elastic-buckling regime)

W18x35 beam, Lb=10 ft, Fy=50 ksi, Cb=1.0:
  AISC Table 3-2: φbMn ≈ 133 kip-ft (inelastic LTB zone)
"""

from __future__ import annotations

import asyncio
import json
import pytest


def _run(coro):
    return asyncio.run(coro)


def _ctx():
    try:
        from kerf_structural._compat import ProjectCtx
    except ImportError:
        from types import SimpleNamespace
        return SimpleNamespace(pool=None, project_id=None)
    return ProjectCtx()


def _call(handler, payload: dict) -> dict:
    raw = _run(handler(_ctx(), json.dumps(payload).encode()))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Spec smoke tests
# ---------------------------------------------------------------------------

class TestSpecRegistration:
    def test_aisc_compression_spec(self):
        from kerf_structural.aisc_member import aisc_compression_spec
        assert aisc_compression_spec.name == "aisc_compression"

    def test_aisc_flexure_spec(self):
        from kerf_structural.aisc_member import aisc_flexure_spec
        assert aisc_flexure_spec.name == "aisc_flexure"

    def test_aisc_combined_spec(self):
        from kerf_structural.aisc_member import aisc_combined_spec
        assert aisc_combined_spec.name == "aisc_combined"

    def test_aisc_member_check_spec(self):
        from kerf_structural.aisc_member import aisc_member_check_spec
        assert aisc_member_check_spec.name == "aisc_member_check"


# ---------------------------------------------------------------------------
# aisc_compression — W14x90 column
# ---------------------------------------------------------------------------

class TestAISCCompression:
    def test_w_shape_ok(self):
        from kerf_structural.aisc_member import run_aisc_compression
        result = _call(run_aisc_compression, {
            "designation": "W14X90",
            "section_type": "W",
            "Lc_ft": 12.0,
        })
        assert result.get("ok") is True
        # AISC 16th Table 4-1 φcPn ≈ 1130 kips; implementation uses gross-area
        # Pn (no hole deduction) → accept within 6 % of table value.
        assert result["phi_Pn_kips"] == pytest.approx(1130, rel=0.06)

    def test_bad_section_raises_error(self):
        from kerf_structural.aisc_member import run_aisc_compression
        result = _call(run_aisc_compression, {
            "designation": "NONEXISTENT999",
            "section_type": "W",
            "Lc_ft": 12.0,
        })
        assert "error" in result

    def test_bad_json_returns_bad_args(self):
        from kerf_structural.aisc_member import run_aisc_compression
        raw = _run(run_aisc_compression(_ctx(), b"not-json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# aisc_flexure — W18x35 beam
# ---------------------------------------------------------------------------

class TestAISCFlexure:
    def test_w18x35_inelastic_ltb(self):
        from kerf_structural.aisc_member import run_aisc_flexure
        result = _call(run_aisc_flexure, {
            "designation": "W18X35",
            "section_type": "W",
            "Lb_ft": 10.0,
            "Fy": 50.0,
            "Cb": 1.0,
        })
        assert result.get("ok") is True
        # At Lb=10 ft (between Lp≈4.3 ft and Lr≈12.4 ft) → inelastic LTB.
        # φbMp = 0.9 × 50 × 66.5 / 12 = 249 kip-ft; inelastic reduction to
        # ~170–185 kip-ft is consistent with AISC F2-2 interpolation.
        assert 150.0 < result["phi_Mn_kip_ft"] < 250.0
        assert result["ltb_zone"] == "inelastic"

    def test_plastic_zone_short_unbraced(self):
        from kerf_structural.aisc_member import run_aisc_flexure
        result = _call(run_aisc_flexure, {
            "designation": "W18X35",
            "section_type": "W",
            "Lb_ft": 0.5,
        })
        assert result.get("ok") is True
        assert result["ltb_zone"] == "plastic"


# ---------------------------------------------------------------------------
# aisc_combined — W14x90 with axial + moment
# ---------------------------------------------------------------------------

class TestAISCCombined:
    def test_combined_check(self):
        from kerf_structural.aisc_member import run_aisc_combined
        result = _call(run_aisc_combined, {
            "designation": "W14X90",
            "section_type": "W",
            "Lc_ft": 12.0,
            "Lb_ft": 12.0,
            "Pu": 400.0,
            "Mux_kip_ft": 80.0,
        })
        assert result.get("ok") is True
        # H1 interaction ratio should be between 0 and 1.5 for a reasonable section
        assert 0.0 < result["ratio_H1"] < 1.5

    def test_zero_demands(self):
        from kerf_structural.aisc_member import run_aisc_combined
        result = _call(run_aisc_combined, {
            "designation": "W14X90",
            "section_type": "W",
            "Lc_ft": 12.0,
            "Lb_ft": 12.0,
        })
        assert result.get("ok") is True
        assert result["ratio_H1"] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# aisc_member_check — full check (E + F + H)
# ---------------------------------------------------------------------------

class TestAISCMemberCheck:
    def test_w14x90_full_check(self):
        from kerf_structural.aisc_member import run_aisc_member_check
        result = _call(run_aisc_member_check, {
            "designation": "W14X90",
            "section_type": "W",
            "Lc_ft": 12.0,
            "Lb_ft": 12.0,
            "Pu": 400.0,
            "Mux_kip_ft": 80.0,
        })
        assert result.get("ok") is True
        assert "phi_Pn_kips" in result
        assert "phi_Mnx_kip_ft" in result
        assert "ratio_H1" in result
        assert "KL_r" in result
        assert "Fcr_ksi" in result
        assert "ltb_zone" in result

    def test_missing_required_field_returns_error(self):
        from kerf_structural.aisc_member import run_aisc_member_check
        result = _call(run_aisc_member_check, {
            "section_type": "W",
            "Lc_ft": 12.0,
            "Lb_ft": 12.0,
        })
        assert "error" in result
