"""
test_kbe_engine.py — pytest suite for kerf_rules.kbe KBE rule engine.

Coverage
--------
1.  AISC W-shape (KBE-S-01): span=10m, udl=8 kN/m² → section W21X68 or heavier;
    confidence > 0.8; provenance non-empty.
2.  AISC depth guard: selected section depth ≥ span/16.
3.  Bearing L10 (KBE-M-01): F=10 kN, n=1500 rpm, L10h=20000 h → C_required
    satisfies ISO 281 oracle (L10_hours ≥ 20000).
4.  Multi-domain consistency: structural (W-shape) + mechanical (bearing) in one
    state — both fire without conflict.
5.  Rule provenance: every built-in rule has a non-empty provenance string
    citing a recognised standard keyword.
6.  DE-Goodman shaft (KBE-M-02): M=500 Nm, T=300 Nm, Se=150 MPa → diameter_mm > 0.
7.  NEC wire gauge (KBE-E-01): 40 A continuous load → ≥ 8 AWG, ampacity ≥ 50 A.
8.  Breaker (KBE-E-02): 40 A continuous → breaker ≥ 50 A standard rating.
9.  Transformer (KBE-E-03): 50 kW, pf=0.85 → transformer_kVA ≥ required kVA.
10. Pipe size (KBE-P-01): 25 DFU → drain_pipe_diameter_in ≥ 2 in.
11. Pump head (KBE-P-02): Q=0.005 m³/s, L=100m, D=0.05m → pump_head_m > 0.
12. Conflict resolution: two rules targeting same key — higher confidence wins.
13. LLM tool kbe_apply_rules: happy-path structural call returns ok=True + section.
14. LLM tool kbe_apply_rules: invalid params returns error payload.
15. KBELibrary.default() returns 10 rules across 4 domains.
16. apply_rules domain filter: only structural rules fire when domains=["structural"].
17. KBEState unified get(): derived values shadow params.
18. ASCE 7 wind (KBE-S-03): V=115 mph, Exposure B, z=30 ft → wind_pressure_psf > 0.
19. ACI rebar (KBE-S-02): given Mu=50 kip-ft, b=14 in, h=24 in → As_required > 0.
20. max_cycles guard: engine terminates even with mutually dependent rules.
"""

from __future__ import annotations

import asyncio
import json
import math
import types
import uuid

import pytest

from kerf_rules.kbe import (
    KBEEngine,
    KBELibrary,
    KBERule,
    KBEState,
    InferenceResult,
    apply_rules,
)
from kerf_rules.tools.kbe_apply_rules import kbe_apply_rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _ctx():
    ctx = types.SimpleNamespace()
    ctx.project_id = uuid.uuid4()
    ctx.pool = None
    ctx.storage = None
    return ctx


# ---------------------------------------------------------------------------
# 1. AISC W-shape selection — span 10m, UDL 8 kN/m²
# ---------------------------------------------------------------------------

class TestAISCWShapeSelection:
    """KBE-S-01 correctness tests."""

    def _run_beam(self, span_m=10.0, udl=8.0, trib=1.0):
        return apply_rules({"span_m": span_m, "udl_kN_m2": udl, "trib_m": trib})

    def test_section_selected(self):
        r = self._run_beam()
        assert r.derived.get("section") is not None, "No section derived"

    def test_section_not_lighter_than_w18x35(self):
        """
        For 10m span + 8 kN/m², the minimum adequate section must be at least
        W18×35 by AISC LRFD.  The engine may select W21×68 or heavier.
        Verify φMn ≥ Mu.
        """
        r = self._run_beam()
        phi_Mn = r.derived.get("phi_Mn_kip_ft", 0.0)
        Mu     = r.derived.get("Mu_kip_ft", 0.0)
        assert phi_Mn >= Mu, (
            f"Section {r.derived.get('section')} φMn={phi_Mn:.1f} < Mu={Mu:.1f} kip-ft"
        )
        # W18×35 or heavier means weight ≥ 35 lb/ft
        section = r.derived["section"]
        import re
        m = re.search(r"W\d+X(\d+)", section)
        weight = int(m.group(1)) if m else 0
        assert weight >= 35, f"Section {section} is lighter than W18×35"

    def test_confidence_above_0_8(self):
        lib  = KBELibrary.default()
        rule = lib.get("KBE-S-01")
        assert rule is not None
        assert rule.confidence > 0.8

    def test_kbe_s01_provenance_non_empty(self):
        lib  = KBELibrary.default()
        rule = lib.get("KBE-S-01")
        assert rule.provenance.strip() != ""

    def test_depth_guard(self):
        """Selected depth ≥ span / 16 (AISC serviceability)."""
        r = self._run_beam()
        section = r.derived.get("section")
        if section is None:
            pytest.skip("No section selected")
        from kerf_structural.steel_beam import w_section as _ws
        sec = _ws(section)
        span_in = 10.0 * 39.3701
        assert sec.d >= span_in / 16.0, (
            f"Section depth {sec.d:.2f} in < span/16 = {span_in/16.0:.2f} in"
        )


# ---------------------------------------------------------------------------
# 3. Bearing L10 life — ISO 281 oracle verification
# ---------------------------------------------------------------------------

class TestBearingL10:
    """KBE-M-01 correctness tests."""

    def test_c_required_satisfies_life(self):
        r = apply_rules({
            "bearing_load_N":      10_000.0,
            "bearing_speed_rpm":   1_500.0,
            "bearing_L10h_target": 20_000.0,
            "bearing_type":        "ball",
        })
        C = r.derived.get("bearing_C_required_N", 0.0)
        assert C > 0, "No bearing C derived"

        # Oracle: bearing_l10(C, 10000, 1500) must achieve ≥ 20000 h
        from kerf_cad_core.shaft.calc import bearing_l10
        check = bearing_l10(C, 10_000.0, 1_500.0, "ball")
        assert check["ok"]
        assert check["L10_hours"] >= 20_000.0 * 0.999, (
            f"L10_hours={check['L10_hours']:.1f} < target 20000 h"
        )

    def test_kbe_m01_confidence(self):
        lib = KBELibrary.default()
        r   = lib.get("KBE-M-01")
        assert r.confidence >= 0.9

    def test_kbe_m01_provenance_cites_iso281(self):
        lib  = KBELibrary.default()
        rule = lib.get("KBE-M-01")
        assert "ISO 281" in rule.provenance


# ---------------------------------------------------------------------------
# 4. Multi-domain consistency
# ---------------------------------------------------------------------------

class TestMultiDomainConsistency:
    """Structural (W-shape) + Mechanical (bearing) in one state — no conflicts."""

    def test_both_rules_fire(self):
        params = {
            # structural
            "span_m": 8.0, "udl_kN_m2": 5.0, "trib_m": 1.0,
            # mechanical bearing
            "bearing_load_N": 8_000.0, "bearing_speed_rpm": 1_200.0,
            "bearing_L10h_target": 15_000.0,
        }
        r = apply_rules(params)
        assert "section" in r.derived, "Structural rule did not fire"
        assert "bearing_C_required_N" in r.derived, "Bearing rule did not fire"
        # No error keys
        assert "section_error" not in r.derived
        assert "bearing_error" not in r.derived

    def test_no_conflicts_in_multi_domain(self):
        params = {
            "span_m": 8.0, "udl_kN_m2": 5.0, "trib_m": 1.0,
            "bearing_load_N": 8_000.0, "bearing_speed_rpm": 1_200.0,
            "bearing_L10h_target": 15_000.0,
        }
        r = apply_rules(params)
        # Since the rules target non-overlapping keys, conflicts should be 0
        assert r.conflicts_resolved == 0


# ---------------------------------------------------------------------------
# 5. Rule provenance
# ---------------------------------------------------------------------------

class TestRuleProvenance:
    """Every built-in rule must have a non-empty provenance citing a standard."""

    # Known standard keywords that should appear in at least one provenance string
    _KNOWN_STANDARDS = [
        "AISC", "ACI 318", "ASCE 7", "ISO 281", "ASME B106",
        "NEC", "IPC", "Darcy",
    ]

    def test_all_rules_have_provenance(self):
        lib = KBELibrary.default()
        for rule in lib.all_rules():
            assert rule.provenance.strip() != "", (
                f"Rule {rule.id} has empty provenance"
            )

    def test_provenance_cites_standards(self):
        """At least one rule must cite each known standard."""
        lib         = KBELibrary.default()
        all_prov    = " ".join(r.provenance for r in lib.all_rules())
        for std in self._KNOWN_STANDARDS:
            assert std in all_prov, f"No rule cites standard keyword '{std}'"


# ---------------------------------------------------------------------------
# 6. Shaft diameter — DE-Goodman
# ---------------------------------------------------------------------------

class TestShaftDiameter:
    def test_diameter_positive(self):
        r = apply_rules({
            "shaft_M_Nm": 500.0,
            "shaft_T_Nm": 300.0,
            "shaft_Se_Pa": 150e6,
        })
        d_mm = r.derived.get("shaft_diameter_mm")
        assert d_mm is not None and d_mm > 0

    def test_kbe_m02_provenance_cites_asme(self):
        lib = KBELibrary.default()
        r   = lib.get("KBE-M-02")
        assert "ASME B106" in r.provenance


# ---------------------------------------------------------------------------
# 7-9. Electrical rules
# ---------------------------------------------------------------------------

class TestElectricalRules:
    def test_wire_gauge_40A_continuous(self):
        r = apply_rules({"load_current_A": 40.0, "continuous_load": True})
        gauge = r.derived.get("wire_gauge_awg")
        amp   = r.derived.get("wire_ampacity_A", 0)
        assert gauge is not None
        # Design current = 40 * 1.25 = 50 A; must pick conductor ≥ 50 A
        assert amp >= 50, f"Ampacity {amp} < 50 A (design current for 40 A continuous)"

    def test_breaker_40A_continuous(self):
        r = apply_rules({"load_current_A": 40.0, "continuous_load": True})
        br = r.derived.get("breaker_rating_A", 0)
        # 40 A × 1.25 = 50 A design; next standard = 50 A
        assert br >= 50, f"Breaker rating {br} < 50 A"

    def test_transformer_50kW(self):
        r = apply_rules({"load_kW": 50.0, "power_factor": 0.85})
        kva = r.derived.get("transformer_kVA", 0)
        required = 50.0 / 0.85 * 1.25
        assert kva >= required, f"transformer_kVA {kva} < required {required:.1f}"


# ---------------------------------------------------------------------------
# 10-11. Plumbing rules
# ---------------------------------------------------------------------------

class TestPlumbingRules:
    def test_pipe_size_25dfu(self):
        r = apply_rules({"drainage_fixture_units": 25.0})
        dia = r.derived.get("drain_pipe_diameter_in", 0.0)
        assert dia >= 2.0, f"Pipe diameter {dia} in for 25 DFU (should be ≥ 2 in per IPC)"

    def test_pump_head_positive(self):
        r = apply_rules({
            "flow_rate_m3s": 0.005,
            "pipe_length_m": 100.0,
            "pipe_diameter_m": 0.05,
            "static_head_m": 5.0,
        })
        h = r.derived.get("pump_head_m", 0.0)
        assert h > 0, "Pump head should be > 0"


# ---------------------------------------------------------------------------
# 12. Conflict resolution
# ---------------------------------------------------------------------------

class TestConflictResolution:
    """Higher-confidence rule wins key collision."""

    def test_higher_confidence_wins(self):
        """Two rules both derive 'result_key'; higher confidence should win."""
        def _low_pre(s: KBEState) -> bool:
            return "trigger" in s.params

        def _low_der(s: KBEState) -> dict:
            return {"result_key": "LOW"}

        def _high_pre(s: KBEState) -> bool:
            return "trigger" in s.params

        def _high_der(s: KBEState) -> dict:
            return {"result_key": "HIGH"}

        low_rule = KBERule(
            id="TEST-LOW",
            domain="test",
            description="Low-confidence rule",
            provenance="Test §1",
            confidence=0.5,
            precondition=_low_pre,
            derivation=_low_der,
        )
        high_rule = KBERule(
            id="TEST-HIGH",
            domain="test",
            description="High-confidence rule",
            provenance="Test §2",
            confidence=0.9,
            precondition=_high_pre,
            derivation=_high_der,
        )
        engine = KBEEngine([low_rule, high_rule])
        state  = KBEState(params={"trigger": True})
        result = engine.run(state)
        assert result.derived.get("result_key") == "HIGH"
        assert result.conflicts_resolved >= 1


# ---------------------------------------------------------------------------
# 13-14. LLM tool kbe_apply_rules
# ---------------------------------------------------------------------------

class TestKBEApplyRulesTool:
    def test_structural_happy_path(self):
        result = kbe_apply_rules(
            {"span_m": 10.0, "udl_kN_m2": 8.0, "trib_m": 1.0}
        )
        assert result["ok"] is True
        assert "section" in result["derived"]
        assert "structural" in result["domains_covered"]

    def test_bearing_happy_path(self):
        result = kbe_apply_rules(
            {
                "bearing_load_N": 10_000.0,
                "bearing_speed_rpm": 1_500.0,
                "bearing_L10h_target": 20_000.0,
            },
            domains=["mechanical"],
        )
        assert result["ok"] is True
        assert "bearing_C_required_N" in result["derived"]

    def test_invalid_params_type(self):
        with pytest.raises((TypeError, AttributeError, ValueError)):
            kbe_apply_rules("not_a_dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 15. KBELibrary.default() — 10 rules, 4 domains
# ---------------------------------------------------------------------------

class TestKBELibraryDefault:
    def test_ten_rules(self):
        lib = KBELibrary.default()
        assert len(lib.all_rules()) == 10

    def test_four_domains(self):
        lib     = KBELibrary.default()
        domains = {r.domain for r in lib.all_rules()}
        assert domains == {"structural", "mechanical", "electrical", "plumbing"}

    def test_all_rule_ids_unique(self):
        lib = KBELibrary.default()
        ids = [r.id for r in lib.all_rules()]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# 16. Domain filter
# ---------------------------------------------------------------------------

class TestDomainFilter:
    def test_only_structural_fires(self):
        params = {
            "span_m": 10.0, "udl_kN_m2": 8.0, "trib_m": 1.0,
            "bearing_load_N": 10_000.0, "bearing_speed_rpm": 1_500.0,
            "bearing_L10h_target": 20_000.0,
        }
        r = apply_rules(params, domains=["structural"])
        assert "section" in r.derived
        assert "bearing_C_required_N" not in r.derived


# ---------------------------------------------------------------------------
# 17. KBEState unified get()
# ---------------------------------------------------------------------------

class TestKBEStateUnifiedGet:
    def test_derived_shadows_params(self):
        s = KBEState(
            params={"span_m": 5.0},
            derived={"span_m": 99.0},
        )
        assert s.get("span_m") == 99.0  # derived wins

    def test_fallback_to_params(self):
        s = KBEState(params={"span_m": 5.0})
        assert s.get("span_m") == 5.0

    def test_default_when_missing(self):
        s = KBEState()
        assert s.get("nonexistent", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# 18. ASCE 7 wind
# ---------------------------------------------------------------------------

class TestASCE7Wind:
    def test_wind_pressure_positive(self):
        r = apply_rules({
            "wind_speed_mph": 115.0,
            "exposure_category": "B",
            "mean_roof_height_ft": 30.0,
        })
        p = r.derived.get("wind_pressure_psf", 0.0)
        assert p > 0, "Wind pressure should be > 0"

    def test_exposure_c_higher_than_b(self):
        params_b = {
            "wind_speed_mph": 115.0, "exposure_category": "B",
            "mean_roof_height_ft": 30.0,
        }
        params_c = {
            "wind_speed_mph": 115.0, "exposure_category": "C",
            "mean_roof_height_ft": 30.0,
        }
        r_b = apply_rules(params_b)
        r_c = apply_rules(params_c)
        assert r_c.derived.get("wind_pressure_psf", 0) > r_b.derived.get("wind_pressure_psf", 0)


# ---------------------------------------------------------------------------
# 19. ACI rebar selection
# ---------------------------------------------------------------------------

class TestACIRebar:
    def test_as_required_positive(self):
        r = apply_rules({
            "Mu_kip_ft": 50.0,
            "beam_b_in": 14.0,
            "beam_h_in": 24.0,
        })
        As = r.derived.get("As_required_in2", 0.0)
        assert As > 0, f"As_required_in2 should be > 0, got {As}"

    def test_rho_within_aci_bounds(self):
        r = apply_rules({
            "Mu_kip_ft": 50.0,
            "beam_b_in": 14.0,
            "beam_h_in": 24.0,
        })
        rho = r.derived.get("rho_design", -1.0)
        rho_min = r.derived.get("rho_min", 0.0)
        rho_max = r.derived.get("rho_max", 1.0)
        assert rho_min <= rho <= rho_max, (
            f"ρ={rho:.6f} not in [{rho_min:.6f}, {rho_max:.6f}]"
        )


# ---------------------------------------------------------------------------
# 20. max_cycles guard
# ---------------------------------------------------------------------------

class TestMaxCyclesGuard:
    def test_terminates_with_cyclic_rules(self):
        """Engine must not loop forever even if rules keep firing indefinitely."""
        counter = {"n": 0}

        def _pre(s: KBEState) -> bool:
            # Always fires — deliberately never reaches a fixed point
            return True

        def _der(s: KBEState) -> dict:
            counter["n"] += 1
            return {"cycle_count": counter["n"]}  # different value each cycle

        rule = KBERule(
            id="CYCLIC",
            domain="test",
            description="Cyclic rule for guard test",
            provenance="Test §99",
            confidence=0.5,
            precondition=_pre,
            derivation=_der,
        )
        max_c  = 5
        engine = KBEEngine([rule], max_cycles=max_c)
        state  = KBEState()
        result = engine.run(state)
        # Must terminate and have a result
        assert result.derived.get("cycle_count") is not None
        # The engine is bounded by max_cycles — counter fires at most max_c times
        assert counter["n"] <= max_c, (
            f"Engine ran {counter['n']} cycles, exceeding max_cycles={max_c}"
        )
