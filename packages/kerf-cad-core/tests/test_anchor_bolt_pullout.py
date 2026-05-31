"""
Tests for kerf_cad_core.arch.anchor_bolt_pullout — ACI 318-19 §17.6 headed anchor bolt
tensile pullout capacity check.

All tests are hermetic (no OCC, no DB, no network).
Dimensions in mm, stresses in MPa, forces in kN.

Oracle derivations
------------------

PRIMARY ORACLE (T01–T06):
  16mm bolt, hef=200mm, edge=300mm (= 1.5·hef, no edge effect), spacing=200mm,
  fc=25MPa, fy=420MPa, A_brg=400mm², bolt_count=1, cracked_concrete=True.

  Steel (§17.6.1):
    A_se = 0.85 · π·16²/4 = 170.9026 mm²
    N_sa = 170.9026 · 420 = 71 779 N = 71.779 kN
    φ·N_sa = 0.75 · 71.779 = 53.834 kN

  Concrete breakout (§17.6.2):
    k_c_SI = 2.40  (cracked cast-in, SI equivalent of ACI imperial k_c=24)
    N_b = 2.40 · 1.0 · √25 · 200^1.5 = 2.40 · 5 · 2828.43 = 33 941 N = 33.941 kN
    A_Nco = 9 · 200² = 360 000 mm²
    edge = 300mm = 1.5·hef → A_Nc = (300+300)·(2·300) = 360 000 = A_Nco → ratio = 1.0
    ψ_ed = 1.0  (edge ≥ 1.5·hef)
    ψ_c = 1.0  (cracked)
    N_cb = 1.0 · 1.0 · 1.0 · 33 941 = 33 941 N
    φ·N_cb = 0.65 · 33.941 = 22.062 kN

  Concrete pullout (§17.6.3):
    N_p = 8 · 400 · 25 = 80 000 N = 80 kN
    ψ_c,P = 1.0 (cracked)
    φ·N_pn = 0.65 · 80 = 52.000 kN

  Governing: min(53.834, 22.062, 52.000) = 22.062 kN → concrete_breakout

  N=15 kN: DCR = 15/22.062 = 0.680 → ADEQUATE
  N=50 kN: DCR = 50/22.062 = 2.267 → FAILS

EDGE REDUCTION ORACLE (T07):
  16mm bolt, hef=200mm, edge=150mm (< 1.5·hef=300mm), A_brg=400mm², cracked.
    ψ_ed = 0.7 + 0.3·(150/300) = 0.85
    A_Nc: near_extent = min(150, 300) = 150; far = 300
          A_Nc = (150+300)·(2·300) = 450·600 = 270 000 mm²
          ratio = 270 000 / 360 000 = 0.75
    N_cb = 0.75 · 0.85 · 1.0 · 33 941 = 21 637 N
    φ·N_cb = 0.65 · 21.637 = 14.064 kN

GROUP ORACLE (T09):
  Two 16mm bolts, hef=200mm, edge=300mm, spacing=200mm, A_brg=400mm², cracked.
    A_Nc: width = (2−1)·200 + 2·300 = 800; length = 300+300 = 600
          A_Nc = 800·600 = 480 000 mm²; cap = 2·360 000 = 720 000 → A_Nc = 480 000
    N_cbg = (480 000/360 000) · 1.0 · 1.0 · 33 941 = 1.3333·33 941 = 45 255 N
    φ·N_cbg = 0.65 · 45.255 = 29.416 kN

UNCRACKED ORACLE (T10):
  16mm bolt, hef=200mm, edge=300mm, A_brg=400mm², cracked_concrete=False.
    k_c_SI = 3.40 (uncracked); ψ_c = 1.25
    N_b = 3.40 · 5 · 2828.43 = 48 083 N
    N_cb = 1.0 · 1.0 · 1.25 · 48 083 = 60 104 N
    φ·N_cb = 0.65 · 60.104 = 39.068 kN

Coverage list
-------------
  T01  N_b formula: k_c=2.40 (SI), √f'c, hef^1.5 → 33.941 kN
  T02  phi_Nsa: A_se = 0.85·π·d²/4, N_sa = A_se·fy, φ·N_sa = 0.75·N_sa
  T03  phi_Nph: N_p = 8·A_brg·f'c, φ·N_pn = φ_c·N_pn
  T04  phi_Ncb: no edge effect (edge=300mm = 1.5·hef) → ratio=1, ψ_ed=1 → 22.062 kN
  T05  Governing mode = concrete_breakout (min of all three)
  T06  Adequate at N=15 kN; fails at N=50 kN
  T07  Edge-effect: edge=150mm → ψ_ed=0.85; A_Nc/A_Nco=0.75 → phi_Ncb=14.064 kN
  T08  ψ_ed boundary: edge exactly = 1.5·hef → ψ_ed=1.0, no area clipping
  T09  Two-bolt group: A_Nc from (n−1)·s + 2·1.5·hef breadth
  T10  Uncracked concrete: k_c=3.40, ψ_c=1.25 → higher phi_Ncb than cracked
  T11  phi_concrete=0.70 (Condition A) instead of default 0.65
  T12  Zero demand → DCR=0, adequate=True
  T13  Re-export from arch/__init__.py works
  T14  honest_caveat mentions ACI 318-19 and scope limitations
  T15  ValueError: bolt_diameter_mm <= 0
  T16  ValueError: embedment_depth_hef_mm <= 0
  T17  ValueError: edge_distance_min_mm < 0
  T18  ValueError: bolt_count < 1
  T19  ValueError: anchor_spacing_min_mm <= 0 when bolt_count > 1
  T20  ValueError: fc_MPa <= 0
  T21  ValueError: fy_steel_MPa <= 0
  T22  ValueError: head_bearing_area_mm2 <= 0
  T23  ValueError: N_factored_kN < 0
  T24  Large group (4 bolts): A_Nc, phi_Ncb, and phi_Nsa scale with n
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.anchor_bolt_pullout import (
    AnchorBoltSpec,
    AnchorPulloutReport,
    check_anchor_pullout,
)


# ---------------------------------------------------------------------------
# Tolerance helper
# ---------------------------------------------------------------------------

def approx(val: float, rel: float = 1e-3) -> float:
    """pytest.approx wrapper for numeric checks."""
    return pytest.approx(val, rel=rel)


# ---------------------------------------------------------------------------
# Primary oracle spec: edge=300mm (= 1.5·hef, no edge effect)
# 16mm bolt, hef=200mm, fc=25MPa, fy=420MPa, A_brg=400mm²
# ---------------------------------------------------------------------------
_SPEC_PRI = AnchorBoltSpec(
    bolt_diameter_mm=16,
    embedment_depth_hef_mm=200,
    edge_distance_min_mm=300,   # = 1.5·hef: no edge reduction
    anchor_spacing_min_mm=200,
    fc_MPa=25,
    fy_steel_MPa=420,
    head_bearing_area_mm2=400,
    bolt_count=1,
    cracked_concrete=True,
)


class TestT01_N_b_Formula:
    """T01 — N_b = k_c · λ · √f'c · hef^1.5 with k_c_SI = 2.40."""

    def test_nb_exact_value(self):
        """N_b = 2.40 · √25 · 200^1.5 = 33 941 N = 33.941 kN."""
        r = check_anchor_pullout(_SPEC_PRI, N_factored_kN=0)
        assert r.N_b_kN == approx(33.9411, rel=1e-3)

    def test_nb_scales_with_sqrt_fc(self):
        """Doubling f'c multiplies N_b by √2."""
        r1 = check_anchor_pullout(
            AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400), 0
        )
        r2 = check_anchor_pullout(
            AnchorBoltSpec(16, 200, 300, 200, 50, 420, 400), 0
        )
        assert r2.N_b_kN == approx(r1.N_b_kN * math.sqrt(2), rel=1e-3)

    def test_nb_scales_with_hef_power_1_5(self):
        """Doubling hef multiplies N_b by 2^1.5 = 2.828."""
        r1 = check_anchor_pullout(
            AnchorBoltSpec(16, 200, 600, 200, 25, 420, 400), 0
        )
        r2 = check_anchor_pullout(
            AnchorBoltSpec(16, 400, 1200, 200, 25, 420, 400), 0
        )
        assert r2.N_b_kN == approx(r1.N_b_kN * 2**1.5, rel=1e-3)


class TestT02_PhiNsa:
    """T02 — Steel strength: A_se = 0.85·π·d²/4, φ·N_sa = 0.75·A_se·fy."""

    def test_ase_formula(self):
        """A_se = 0.85 · π · 16² / 4 = 170.90 mm²."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        expected_ase = 0.85 * math.pi * 16**2 / 4
        assert r.A_se_mm2 == approx(expected_ase, rel=1e-4)

    def test_phi_nsa_value(self):
        """φ·N_sa = 0.75 · (170.90 · 420 / 1000) = 53.834 kN."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        expected = 0.75 * (0.85 * math.pi * 16**2 / 4) * 420 / 1000
        assert r.phi_Nsa_kN == approx(expected, rel=1e-4)

    def test_phi_nsa_scales_with_fy(self):
        """Doubling fy doubles phi_Nsa."""
        r1 = check_anchor_pullout(
            AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400), 0
        )
        r2 = check_anchor_pullout(
            AnchorBoltSpec(16, 200, 300, 200, 25, 840, 400), 0
        )
        assert r2.phi_Nsa_kN == approx(2 * r1.phi_Nsa_kN, rel=1e-4)


class TestT03_PhiNph:
    """T03 — Concrete pullout: N_p = 8·A_brg·f'c, φ·N_pn = 0.65·N_p."""

    def test_phi_nph_value(self):
        """φ·N_pn = 0.65 · 8 · 400 · 25 / 1000 = 52.000 kN."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        expected = 0.65 * 8 * 400 * 25 / 1000
        assert r.phi_Nph_kN == approx(expected, rel=1e-4)

    def test_phi_nph_scales_linearly_with_a_brg(self):
        """Doubling A_brg doubles phi_Nph."""
        r1 = check_anchor_pullout(
            AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400), 0
        )
        r2 = check_anchor_pullout(
            AnchorBoltSpec(16, 200, 300, 200, 25, 420, 800), 0
        )
        assert r2.phi_Nph_kN == approx(2 * r1.phi_Nph_kN, rel=1e-4)


class TestT04_PhiNcb_NoEdge:
    """T04 — Concrete breakout with no edge effect (edge = 1.5·hef)."""

    def test_phi_ncb_no_edge_effect(self):
        """φ·N_cb = 0.65 · 1.0 · 1.0 · 1.0 · 33.941 = 22.062 kN."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        assert r.phi_Ncb_kN == approx(22.062, rel=1e-3)

    def test_a_nco_formula(self):
        """A_Nco = 9 · hef² = 9 · 200² = 360 000 mm²."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        assert r.A_Nco_mm2 == approx(360_000, rel=1e-4)

    def test_a_nc_equals_a_nco_when_no_edge_effect(self):
        """A_Nc = A_Nco when edge ≥ 1.5·hef (single bolt)."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        assert r.A_Nc_mm2 == approx(r.A_Nco_mm2, rel=1e-4)

    def test_psi_ed_equals_one_when_edge_gte_1_5_hef(self):
        """ψ_ed = 1.0 when c_a,min ≥ 1.5·hef."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        assert r.psi_ed == approx(1.0)

    def test_psi_c_equals_one_for_cracked(self):
        """ψ_c,N = 1.0 for cracked concrete (default)."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        assert r.psi_c == approx(1.0)


class TestT05_GoverningMode:
    """T05 — Governing mode = concrete_breakout (minimum of three)."""

    def test_governing_mode_is_concrete_breakout(self):
        """Primary oracle: phi_Ncb governs (smallest capacity)."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        assert r.governing_mode == "concrete_breakout"

    def test_phi_nn_equals_phi_ncb(self):
        """φ·N_n_governing = φ·N_cb when breakout governs."""
        r = check_anchor_pullout(_SPEC_PRI, 0)
        assert r.phi_Nn_governing_kN == approx(r.phi_Ncb_kN, rel=1e-4)

    def test_governing_mode_steel_when_small_bolt(self):
        """Steel governs when bolt diameter is tiny and embedment is large."""
        # Tiny diameter → small A_se → small phi_Nsa
        spec = AnchorBoltSpec(
            bolt_diameter_mm=6,
            embedment_depth_hef_mm=200,
            edge_distance_min_mm=300,
            anchor_spacing_min_mm=200,
            fc_MPa=25,
            fy_steel_MPa=250,
            head_bearing_area_mm2=400,
        )
        r = check_anchor_pullout(spec, 0)
        # phi_Nsa = 0.75 · (0.85·π·36/4) · 250 / 1000 = 7.54 kN
        assert r.governing_mode == "steel"
        assert r.phi_Nn_governing_kN == approx(r.phi_Nsa_kN, rel=1e-4)

    def test_governing_mode_pullout_when_small_head(self):
        """Pullout governs when A_brg is very small and breakout/steel are large."""
        # Large embedment → large N_b; large bolt → large N_sa; tiny head → pullout governs
        spec = AnchorBoltSpec(
            bolt_diameter_mm=30,
            embedment_depth_hef_mm=400,
            edge_distance_min_mm=600,
            anchor_spacing_min_mm=400,
            fc_MPa=25,
            fy_steel_MPa=250,
            head_bearing_area_mm2=50,   # tiny head → small N_p
        )
        r = check_anchor_pullout(spec, 0)
        assert r.governing_mode == "concrete_pullout"
        assert r.phi_Nn_governing_kN == approx(r.phi_Nph_kN, rel=1e-4)


class TestT06_AdequateAndFail:
    """T06 — Adequate at N=15 kN; fails at N=50 kN."""

    def test_adequate_at_15kN(self):
        """N=15 kN < φ·N_n=22.06 kN → adequate=True, DCR < 1."""
        r = check_anchor_pullout(_SPEC_PRI, 15.0)
        assert r.adequate is True
        assert r.dcr < 1.0
        assert r.dcr == approx(15.0 / 22.062, rel=1e-3)

    def test_fails_at_50kN(self):
        """N=50 kN > φ·N_n=22.06 kN → adequate=False, DCR > 1."""
        r = check_anchor_pullout(_SPEC_PRI, 50.0)
        assert r.adequate is False
        assert r.dcr > 1.0
        assert r.dcr == approx(50.0 / 22.062, rel=1e-3)

    def test_borderline_equal_to_capacity(self):
        """N = φ·N_n → DCR = 1.0, adequate=True (at limit)."""
        phi_Nn = check_anchor_pullout(_SPEC_PRI, 0).phi_Nn_governing_kN
        r = check_anchor_pullout(_SPEC_PRI, phi_Nn)
        assert r.dcr == approx(1.0, rel=1e-4)
        assert r.adequate is True


class TestT07_EdgeReduction:
    """T07 — Edge effect: edge < 1.5·hef reduces A_Nc and ψ_ed."""

    def test_psi_ed_for_edge_150mm(self):
        """ψ_ed = 0.7 + 0.3 · (150/300) = 0.85 for edge=150mm, hef=200mm."""
        spec = AnchorBoltSpec(16, 200, 150, 200, 25, 420, 400)
        r = check_anchor_pullout(spec, 0)
        assert r.psi_ed == approx(0.85, rel=1e-4)

    def test_a_nc_reduced_for_edge_150mm(self):
        """A_Nc = (150+300)·(2·300) = 270 000 mm² for edge=150mm, hef=200mm."""
        spec = AnchorBoltSpec(16, 200, 150, 200, 25, 420, 400)
        r = check_anchor_pullout(spec, 0)
        assert r.A_Nc_mm2 == approx(270_000, rel=1e-4)

    def test_phi_ncb_reduced_for_edge_150mm(self):
        """φ·N_cb = 0.65·0.75·0.85·33.941 = 14.064 kN for edge=150mm."""
        spec = AnchorBoltSpec(16, 200, 150, 200, 25, 420, 400)
        r = check_anchor_pullout(spec, 0)
        expected = 0.65 * (270_000 / 360_000) * 0.85 * 1.0 * 33.9411
        assert r.phi_Ncb_kN == approx(expected, rel=1e-3)

    def test_phi_ncb_less_with_edge_effect(self):
        """phi_Ncb with edge reduction < phi_Ncb without edge reduction."""
        spec_close = AnchorBoltSpec(16, 200, 150, 200, 25, 420, 400)
        spec_far = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400)
        r_close = check_anchor_pullout(spec_close, 0)
        r_far = check_anchor_pullout(spec_far, 0)
        assert r_close.phi_Ncb_kN < r_far.phi_Ncb_kN


class TestT08_EdgeBoundary:
    """T08 — ψ_ed boundary: edge exactly = 1.5·hef → ψ_ed = 1.0."""

    def test_psi_ed_exactly_1_at_boundary(self):
        """Edge = 1.5·hef exactly → ψ_ed = 1.0."""
        hef = 200
        spec = AnchorBoltSpec(16, hef, 1.5 * hef, 200, 25, 420, 400)
        r = check_anchor_pullout(spec, 0)
        assert r.psi_ed == approx(1.0)

    def test_psi_ed_less_than_1_just_below_boundary(self):
        """Edge = 1.5·hef − ε → ψ_ed < 1.0."""
        hef = 200
        spec = AnchorBoltSpec(16, hef, 1.5 * hef - 1, 200, 25, 420, 400)
        r = check_anchor_pullout(spec, 0)
        assert r.psi_ed < 1.0

    def test_psi_ed_greater_edge_still_1(self):
        """Edge > 1.5·hef → ψ_ed clamped at 1.0."""
        hef = 200
        spec = AnchorBoltSpec(16, hef, 1.5 * hef + 100, 200, 25, 420, 400)
        r = check_anchor_pullout(spec, 0)
        assert r.psi_ed == approx(1.0)


class TestT09_TwoBoltGroup:
    """T09 — Group of 2 bolts: A_Nc uses (n−1)·s + 2·1.5·hef for width."""

    def test_a_nc_two_bolt_group(self):
        """A_Nc = (1·200 + 2·300) · (300+300) = 800·600 = 480 000 mm²."""
        spec = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 2, True)
        r = check_anchor_pullout(spec, 0)
        assert r.A_Nc_mm2 == approx(480_000, rel=1e-4)

    def test_phi_ncb_two_bolt_group(self):
        """φ·N_cbg = 0.65 · (480 000/360 000) · 1.0 · 1.0 · 33.941 = 29.416 kN."""
        spec = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 2, True)
        r = check_anchor_pullout(spec, 0)
        expected = 0.65 * (480_000 / 360_000) * 33.9411
        assert r.phi_Ncb_kN == approx(expected, rel=1e-3)

    def test_phi_nsa_scales_with_bolt_count(self):
        """Group φ·N_sa = n × single φ·N_sa."""
        spec1 = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1)
        spec2 = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 2)
        r1 = check_anchor_pullout(spec1, 0)
        r2 = check_anchor_pullout(spec2, 0)
        assert r2.phi_Nsa_kN == approx(2 * r1.phi_Nsa_kN, rel=1e-4)


class TestT10_UncrackdConcrete:
    """T10 — Uncracked concrete: k_c=3.40, ψ_c=1.25 → higher capacity."""

    def test_psi_c_is_1_25_for_uncracked(self):
        """ψ_c,N = 1.25 when cracked_concrete=False."""
        spec = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1, False)
        r = check_anchor_pullout(spec, 0)
        assert r.psi_c == approx(1.25)

    def test_uncracked_nb_larger_than_cracked(self):
        """Uncracked N_b = (3.40/2.40)·cracked N_b."""
        spec_cr = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1, True)
        spec_uc = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1, False)
        r_cr = check_anchor_pullout(spec_cr, 0)
        r_uc = check_anchor_pullout(spec_uc, 0)
        assert r_uc.N_b_kN == approx(r_cr.N_b_kN * (3.40 / 2.40), rel=1e-3)

    def test_uncracked_phi_ncb_ratio(self):
        """Uncracked φ·N_cb = cracked φ·N_cb × (3.40/2.40) × 1.25 ≈ 1.7708."""
        spec_cr = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1, True)
        spec_uc = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1, False)
        r_cr = check_anchor_pullout(spec_cr, 0)
        r_uc = check_anchor_pullout(spec_uc, 0)
        ratio = r_uc.phi_Ncb_kN / r_cr.phi_Ncb_kN
        assert ratio == approx(3.40 / 2.40 * 1.25, rel=1e-3)


class TestT11_PhiConcreteConditionA:
    """T11 — phi_concrete=0.70 (Condition A, ACI Table 17.5.3)."""

    def test_phi_concrete_0_70(self):
        """Increasing phi_concrete from 0.65 to 0.70 scales phi_Ncb and phi_Nph."""
        r65 = check_anchor_pullout(_SPEC_PRI, 0, phi_concrete=0.65)
        r70 = check_anchor_pullout(_SPEC_PRI, 0, phi_concrete=0.70)
        assert r70.phi_Ncb_kN == approx(r65.phi_Ncb_kN * 0.70 / 0.65, rel=1e-4)
        assert r70.phi_Nph_kN == approx(r65.phi_Nph_kN * 0.70 / 0.65, rel=1e-4)


class TestT12_ZeroDemand:
    """T12 — Zero demand → DCR = 0, adequate = True."""

    def test_zero_demand(self):
        r = check_anchor_pullout(_SPEC_PRI, 0.0)
        assert r.dcr == approx(0.0)
        assert r.adequate is True


class TestT13_ReExport:
    """T13 — Re-export from arch/__init__.py works."""

    def test_import_from_arch_init(self):
        from kerf_cad_core.arch import (
            AnchorBoltSpec as ABS,
            AnchorPulloutReport as APR,
            check_anchor_pullout as cap,
        )
        spec = ABS(16, 200, 300, 200, 25, 420, 400)
        r = cap(spec, 10)
        assert isinstance(r, APR)
        assert r.phi_Nn_governing_kN > 0


class TestT14_HonestCaveat:
    """T14 — honest_caveat mentions ACI 318-19 and scope limitations."""

    def test_caveat_mentions_aci_318(self):
        r = check_anchor_pullout(_SPEC_PRI, 10)
        assert "ACI 318-19" in r.honest_caveat

    def test_caveat_mentions_tension_only_scope(self):
        r = check_anchor_pullout(_SPEC_PRI, 10)
        assert "TENSION ONLY" in r.honest_caveat or "tension-only" in r.honest_caveat.lower()

    def test_caveat_mentions_cracked_assumption(self):
        r = check_anchor_pullout(_SPEC_PRI, 10)
        assert "CRACKED" in r.honest_caveat or "cracked" in r.honest_caveat.lower()


class TestT15_ErrorBoltDiameter:
    """T15 — ValueError: bolt_diameter_mm <= 0."""

    def test_zero_diameter(self):
        with pytest.raises(ValueError, match="bolt_diameter_mm"):
            check_anchor_pullout(
                AnchorBoltSpec(0, 200, 300, 200, 25, 420, 400), 10
            )

    def test_negative_diameter(self):
        with pytest.raises(ValueError):
            check_anchor_pullout(
                AnchorBoltSpec(-5, 200, 300, 200, 25, 420, 400), 10
            )


class TestT16_ErrorEmbedment:
    """T16 — ValueError: embedment_depth_hef_mm <= 0."""

    def test_zero_embedment(self):
        with pytest.raises(ValueError, match="embedment_depth_hef_mm"):
            check_anchor_pullout(
                AnchorBoltSpec(16, 0, 300, 200, 25, 420, 400), 10
            )


class TestT17_ErrorEdgeDistance:
    """T17 — ValueError: edge_distance_min_mm < 0."""

    def test_negative_edge(self):
        with pytest.raises(ValueError, match="edge_distance_min_mm"):
            check_anchor_pullout(
                AnchorBoltSpec(16, 200, -1, 200, 25, 420, 400), 10
            )


class TestT18_ErrorBoltCount:
    """T18 — ValueError: bolt_count < 1."""

    def test_zero_bolt_count(self):
        with pytest.raises(ValueError, match="bolt_count"):
            check_anchor_pullout(
                AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 0), 10
            )


class TestT19_ErrorSpacingForGroup:
    """T19 — ValueError: anchor_spacing_min_mm <= 0 when bolt_count > 1."""

    def test_zero_spacing_with_group(self):
        with pytest.raises(ValueError, match="anchor_spacing_min_mm"):
            check_anchor_pullout(
                AnchorBoltSpec(16, 200, 300, 0, 25, 420, 400, 2), 10
            )


class TestT20_ErrorFc:
    """T20 — ValueError: fc_MPa <= 0."""

    def test_zero_fc(self):
        with pytest.raises(ValueError, match="fc_MPa"):
            check_anchor_pullout(
                AnchorBoltSpec(16, 200, 300, 200, 0, 420, 400), 10
            )


class TestT21_ErrorFy:
    """T21 — ValueError: fy_steel_MPa <= 0."""

    def test_zero_fy(self):
        with pytest.raises(ValueError, match="fy_steel_MPa"):
            check_anchor_pullout(
                AnchorBoltSpec(16, 200, 300, 200, 25, 0, 400), 10
            )


class TestT22_ErrorHeadArea:
    """T22 — ValueError: head_bearing_area_mm2 <= 0."""

    def test_zero_head_area(self):
        with pytest.raises(ValueError, match="head_bearing_area_mm2"):
            check_anchor_pullout(
                AnchorBoltSpec(16, 200, 300, 200, 25, 420, 0), 10
            )


class TestT23_ErrorNegativeLoad:
    """T23 — ValueError: N_factored_kN < 0."""

    def test_negative_factored_load(self):
        with pytest.raises(ValueError, match="N_factored_kN"):
            check_anchor_pullout(_SPEC_PRI, -5.0)


class TestT24_FourBoltGroup:
    """T24 — Group of 4 bolts: A_Nc, phi_Ncb, and phi_Nsa scale correctly."""

    def test_four_bolt_phi_nsa(self):
        """φ·N_sa for 4 bolts = 4 × φ·N_sa for 1 bolt."""
        spec1 = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1)
        spec4 = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 4)
        r1 = check_anchor_pullout(spec1, 0)
        r4 = check_anchor_pullout(spec4, 0)
        assert r4.phi_Nsa_kN == approx(4 * r1.phi_Nsa_kN, rel=1e-4)

    def test_four_bolt_a_nc_width(self):
        """A_Nc width for 4 bolts in line = (4−1)·200 + 2·300 = 1200 mm."""
        spec4 = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 4)
        r4 = check_anchor_pullout(spec4, 0)
        # A_Nc = 1200 (width) × 600 (length) = 720 000
        # Cap = 4 × 360 000 = 1 440 000 → A_Nc = 720 000
        assert r4.A_Nc_mm2 == approx(720_000, rel=1e-4)

    def test_four_bolt_phi_nph_scales_with_n(self):
        """φ·N_pn for 4 bolts = 4 × single φ·N_pn."""
        spec1 = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 1)
        spec4 = AnchorBoltSpec(16, 200, 300, 200, 25, 420, 400, 4)
        r1 = check_anchor_pullout(spec1, 0)
        r4 = check_anchor_pullout(spec4, 0)
        assert r4.phi_Nph_kN == approx(4 * r1.phi_Nph_kN, rel=1e-4)
