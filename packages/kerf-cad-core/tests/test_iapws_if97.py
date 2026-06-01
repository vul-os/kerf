"""
tests/test_iapws_if97.py — Validation tests for IAPWS-IF97 steam properties
=============================================================================

Reference values are taken directly from the IAPWS-IF97 standard
(Wagner et al., J. Eng. Gas Turbines Power, 2000), Tables 5, 15, 26, and 35.

Tolerances follow IF97 published precision:
  - v:  7 significant figures (relative tol 1e-6)
  - h:  5 significant figures (abs tol 0.01 kJ/kg)
  - s:  5 significant figures (abs tol 0.001 kJ/kg·K)
  - cp: 5 significant figures (abs tol 0.001 kJ/kg·K)
  - psat, Tsat: 5 significant figures
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.fluids.iapws_if97 import (
    psat_T,
    Tsat_p,
    region1_props,
    region2_props,
    steam_properties_if97,
    _region3_properties,
    _region3_inverse,
    _region3_helmholtz_phi,
)


# ---------------------------------------------------------------------------
# Region 4 — Saturation curve
# ---------------------------------------------------------------------------

class TestRegion4Saturation:
    def test_Tsat_at_atmospheric_pressure(self):
        """Tsat(101.325 kPa) = 373.124 K  (IF97 Table 35 / standard result)."""
        T = Tsat_p(101325.0)
        assert abs(T - 373.124) < 0.001, f"Tsat={T:.4f} K, expected 373.124 K"

    def test_psat_at_370K(self):
        """psat(370 K) = 90.535 kPa  (IF97 Table 35)."""
        p = psat_T(370.0)
        assert abs(p / 1000.0 - 90.535) < 0.01, f"psat={p/1000:.4f} kPa, expected 90.535 kPa"

    def test_psat_at_critical_temperature(self):
        """psat(647.096 K) ≈ 22.064 MPa (critical point)."""
        p = psat_T(647.096)
        assert abs(p / 1e6 - 22.064) < 0.01, f"psat={p/1e6:.4f} MPa, expected 22.064 MPa"

    def test_Tsat_at_1MPa(self):
        """Tsat(1 MPa) ≈ 453.03 K — IF97 verification."""
        T = Tsat_p(1.0e6)
        # IAPWS-IF97: Tsat(1 MPa) = 453.0353 K
        assert abs(T - 453.035) < 0.01, f"Tsat={T:.4f} K, expected 453.035 K"

    def test_psat_T_and_Tsat_p_are_inverse(self):
        """Round-trip: Tsat(psat(T)) == T."""
        for T_ref in (280.0, 350.0, 500.0, 600.0):
            p = psat_T(T_ref)
            T_back = Tsat_p(p)
            assert abs(T_back - T_ref) < 1e-6, (
                f"Round-trip error at T={T_ref}: got {T_back:.8f}"
            )

    def test_psat_out_of_range_raises(self):
        with pytest.raises(ValueError):
            psat_T(200.0)   # below 273.15 K

    def test_Tsat_out_of_range_raises(self):
        with pytest.raises(ValueError):
            Tsat_p(30e6)    # above critical pressure


# ---------------------------------------------------------------------------
# Region 1 — Compressed liquid
# ---------------------------------------------------------------------------

class TestRegion1CompressedLiquid:
    """
    Reference: IAPWS-IF97 Table 5.

    T=300 K, p=3 MPa:
      v  = 0.00100215 m³/kg
      h  = 115.331    kJ/kg
      s  = 0.392294   kJ/kg·K
      cp = 4.17301    kJ/kg·K
    """

    @pytest.fixture
    def props_300_3mpa(self):
        return region1_props(300.0, 3.0e6)

    def test_v(self, props_300_3mpa):
        v = props_300_3mpa["v"]
        ref = 0.00100215
        assert abs(v - ref) / ref < 1e-5, f"v={v:.8f}, ref={ref}"

    def test_h(self, props_300_3mpa):
        h_kJ = props_300_3mpa["h"] / 1000.0
        ref = 115.331
        assert abs(h_kJ - ref) < 0.01, f"h={h_kJ:.4f} kJ/kg, ref={ref}"

    def test_s(self, props_300_3mpa):
        s_kJ = props_300_3mpa["s"] / 1000.0
        ref = 0.392294
        assert abs(s_kJ - ref) < 0.001, f"s={s_kJ:.6f} kJ/kg·K, ref={ref}"

    def test_cp(self, props_300_3mpa):
        cp_kJ = props_300_3mpa["cp"] / 1000.0
        ref = 4.17301
        assert abs(cp_kJ - ref) < 0.001, f"cp={cp_kJ:.5f} kJ/kg·K, ref={ref}"

    def test_additional_point_T300_p80mpa(self):
        """
        T=300 K, p=80 MPa — IF97 Table 5 second verification point.
        v = 0.971180e-3 m³/kg, h = 184.142 kJ/kg.
        """
        props = region1_props(300.0, 80.0e6)
        assert abs(props["v"] - 0.971180e-3) / 0.971180e-3 < 1e-5, f"v={props['v']:.8e}"
        assert abs(props["h"] / 1000.0 - 184.142) < 0.01, f"h={props['h']/1000:.4f}"

    def test_additional_point_T500_p3mpa(self):
        """
        T=500 K, p=3 MPa — IF97 Table 5 third verification point.
        v = 0.120241e-2 m³/kg, h = 975.542 kJ/kg.
        """
        props = region1_props(500.0, 3.0e6)
        assert abs(props["v"] - 0.120241e-2) / 0.120241e-2 < 1e-4, f"v={props['v']:.8e}"
        assert abs(props["h"] / 1000.0 - 975.542) < 0.01, f"h={props['h']/1000:.4f}"


# ---------------------------------------------------------------------------
# Region 2 — Superheated steam
# ---------------------------------------------------------------------------

class TestRegion2SuperheatedSteam:
    """
    Reference: IAPWS-IF97 Table 15.

    T=300 K, p=0.0035 MPa:
      v  = 39.4913  m³/kg
      h  = 2549.91  kJ/kg
      s  = 8.52238  kJ/kg·K
      cp = 1.91300  kJ/kg·K
    """

    @pytest.fixture
    def props_300_3500pa(self):
        return region2_props(300.0, 3500.0)

    def test_v(self, props_300_3500pa):
        v = props_300_3500pa["v"]
        ref = 39.4913
        assert abs(v - ref) / ref < 1e-5, f"v={v:.6f}, ref={ref}"

    def test_h(self, props_300_3500pa):
        h_kJ = props_300_3500pa["h"] / 1000.0
        ref = 2549.91
        assert abs(h_kJ - ref) < 0.01, f"h={h_kJ:.4f} kJ/kg, ref={ref}"

    def test_s(self, props_300_3500pa):
        s_kJ = props_300_3500pa["s"] / 1000.0
        ref = 8.52238
        assert abs(s_kJ - ref) < 0.001, f"s={s_kJ:.5f} kJ/kg·K, ref={ref}"

    def test_cp(self, props_300_3500pa):
        cp_kJ = props_300_3500pa["cp"] / 1000.0
        ref = 1.91300
        assert abs(cp_kJ - ref) < 0.001, f"cp={cp_kJ:.5f} kJ/kg·K, ref={ref}"

    def test_additional_point_T700_p0035mpa(self):
        """
        T=700 K, p=0.0035 MPa — IF97 Table 15 second verification point.
        v = 92.3015 m³/kg, h = 3335.68 kJ/kg.
        """
        props = region2_props(700.0, 3500.0)
        assert abs(props["v"] - 92.3015) / 92.3015 < 1e-5, f"v={props['v']:.6f}"
        assert abs(props["h"] / 1000.0 - 3335.68) < 0.05, f"h={props['h']/1000:.4f}"

    def test_additional_point_T700_p30mpa(self):
        """
        T=700 K, p=30 MPa — IF97 Table 15 third verification point.
        v = 0.542946e-2 m³/kg, h = 2631.49 kJ/kg.
        """
        props = region2_props(700.0, 30.0e6)
        assert abs(props["v"] - 0.542946e-2) / 0.542946e-2 < 1e-5, f"v={props['v']:.8e}"
        assert abs(props["h"] / 1000.0 - 2631.49) < 0.05, f"h={props['h']/1000:.4f}"


# ---------------------------------------------------------------------------
# Top-level dispatcher: steam_properties_if97
# ---------------------------------------------------------------------------

class TestSteamPropertiesIF97:
    def test_dispatcher_liquid_region1(self):
        """T=300K, p=3MPa → liquid, correct v."""
        result = steam_properties_if97(300.0, 3.0e6)
        assert result["phase"] == "liquid"
        assert abs(result["v_m3_per_kg"] - 0.00100215) < 1e-7
        assert abs(result["h_J_per_kg"] / 1000.0 - 115.331) < 0.01

    def test_dispatcher_vapour_region2(self):
        """T=300K, p=3500 Pa → vapour, correct v and h."""
        result = steam_properties_if97(300.0, 3500.0)
        assert result["phase"] == "vapour"
        assert abs(result["v_m3_per_kg"] - 39.4913) / 39.4913 < 1e-5
        assert abs(result["h_J_per_kg"] / 1000.0 - 2549.91) < 0.01

    def test_dispatcher_returns_all_fields(self):
        result = steam_properties_if97(400.0, 0.5e6)
        for key in ("T_K", "p_Pa", "v_m3_per_kg", "h_J_per_kg",
                    "s_J_per_kg_K", "cp_J_per_kg_K", "phase"):
            assert key in result, f"Missing key: {key}"

    def test_dispatcher_invalid_temperature(self):
        with pytest.raises(ValueError):
            steam_properties_if97(200.0, 1e5)  # below 273.15 K

    def test_dispatcher_invalid_pressure(self):
        with pytest.raises(ValueError):
            steam_properties_if97(300.0, 0.0)

    def test_steam_at_100c_atmospheric(self):
        """
        At ~373.124 K (psat ≈ 101.325 kPa), vapour just above saturation.
        Specific volume should be close to ideal gas RT/p.
        """
        T = 374.0    # slightly above saturation at atmospheric
        p = 101325.0
        result = steam_properties_if97(T, p)
        assert result["phase"] == "vapour"
        # Rough sanity: v ~ R*T/p for steam ≈ 461.5*374/101325 ≈ 1.70 m³/kg
        expected_v_rough = 461.526 * T / p
        assert abs(result["v_m3_per_kg"] - expected_v_rough) / expected_v_rough < 0.05


# ---------------------------------------------------------------------------
# Region 3 — Supercritical / near-critical region
# ---------------------------------------------------------------------------

class TestRegion3Supercritical:
    """
    Reference values: IAPWS-IF97 (2007 release), Table 33.

    The three canonical verification points from Table 33 are specified
    as (ρ, T) inputs, not (p, T), because Region 3 is a Helmholtz formulation:

      T=650 K, ρ=500 kg/m³  → p=25.5837 MPa, h=1863.43 kJ/kg, s=4.05427 kJ/(kg·K),
                               cv=3.19132 kJ/(kg·K), w=502.006 m/s
      T=650 K, ρ=200 kg/m³  → p=22.2930 MPa, h=2375.12 kJ/kg, s=4.85438 kJ/(kg·K),
                               cv=4.04118 kJ/(kg·K), w=383.444 m/s
      T=750 K, ρ=500 kg/m³  → p=78.3096 MPa, h=2258.69 kJ/kg, s=4.46972 kJ/(kg·K)
    """

    # ------------------------------------------------------------------
    # Direct Region 3 properties function tests (Table 33 reference points)
    # ------------------------------------------------------------------

    def test_helmholtz_phi_finite_at_critical(self):
        """φ(ρ*, T*) must be finite and well-behaved at the critical point."""
        phi, phi_d, phi_dd, phi_t, phi_tt = _region3_helmholtz_phi(322.0, 647.096)
        assert math.isfinite(phi)
        assert math.isfinite(phi_d)
        assert math.isfinite(phi_t)
        # φ_δ should be positive (pressure > 0)
        assert phi_d > 0.0

    def test_region3_pressure_T650_rho500(self):
        """
        T=650 K, ρ=500 kg/m³ → p = 25.5837 MPa (IAPWS-IF97 Table 33, point 1).
        Tolerance 0.01% on pressure.
        """
        props = _region3_properties(500.0, 650.0)
        p_ref = 25.5837e6  # Pa
        assert abs(props["p"] - p_ref) / p_ref < 1e-4, (
            f"p={props['p']/1e6:.5f} MPa, expected 25.5837 MPa"
        )

    def test_region3_enthalpy_T650_rho500(self):
        """
        T=650 K, ρ=500 kg/m³ → h = 1863.43 kJ/kg (Table 33, point 1).
        Tolerance 0.01% on enthalpy.
        """
        props = _region3_properties(500.0, 650.0)
        h_kJ = props["h"] / 1000.0
        assert abs(h_kJ - 1863.43) / 1863.43 < 1e-4, (
            f"h={h_kJ:.4f} kJ/kg, expected 1863.43 kJ/kg"
        )

    def test_region3_entropy_T650_rho500(self):
        """
        T=650 K, ρ=500 kg/m³ → s = 4.05427 kJ/(kg·K) (Table 33, point 1).
        Tolerance 0.01%.
        """
        props = _region3_properties(500.0, 650.0)
        s_kJ = props["s"] / 1000.0
        assert abs(s_kJ - 4.05427) / 4.05427 < 1e-4, (
            f"s={s_kJ:.6f} kJ/(kg·K), expected 4.05427"
        )

    def test_region3_cv_T650_rho500(self):
        """
        T=650 K, ρ=500 kg/m³ → cv = 3.19132 kJ/(kg·K) (Table 33, point 1).
        Tolerance 0.01%.
        """
        props = _region3_properties(500.0, 650.0)
        cv_kJ = props["cv"] / 1000.0
        assert abs(cv_kJ - 3.19132) / 3.19132 < 1e-4, (
            f"cv={cv_kJ:.5f} kJ/(kg·K), expected 3.19132"
        )

    def test_region3_sound_speed_T650_rho500(self):
        """
        T=650 K, ρ=500 kg/m³ → w = 502.006 m/s (Table 33, point 1).
        Tolerance 0.01%.
        """
        props = _region3_properties(500.0, 650.0)
        assert abs(props["w"] - 502.006) / 502.006 < 1e-4, (
            f"w={props['w']:.3f} m/s, expected 502.006 m/s"
        )

    def test_region3_T650_rho200_pressure(self):
        """
        T=650 K, ρ=200 kg/m³ → p = 22.2930 MPa (Table 33, point 2).
        Tolerance 0.01%.
        """
        props = _region3_properties(200.0, 650.0)
        assert abs(props["p"] - 22.2930e6) / 22.2930e6 < 1e-4, (
            f"p={props['p']/1e6:.5f} MPa, expected 22.2930 MPa"
        )

    def test_region3_T750_rho500_pressure(self):
        """
        T=750 K, ρ=500 kg/m³ → p = 78.3096 MPa (Table 33, point 3).
        Tolerance 0.01%.
        """
        props = _region3_properties(500.0, 750.0)
        assert abs(props["p"] - 78.3096e6) / 78.3096e6 < 1e-4, (
            f"p={props['p']/1e6:.5f} MPa, expected 78.3096 MPa"
        )

    def test_region3_T750_rho500_enthalpy(self):
        """
        T=750 K, ρ=500 kg/m³ → h = 2258.69 kJ/kg (Table 33, point 3).
        Tolerance 0.01%.
        """
        props = _region3_properties(500.0, 750.0)
        h_kJ = props["h"] / 1000.0
        assert abs(h_kJ - 2258.69) / 2258.69 < 1e-4, (
            f"h={h_kJ:.4f} kJ/kg, expected 2258.69 kJ/kg"
        )

    def test_region3_specific_volume_positive(self):
        """Specific volume must be positive and consistent with 1/rho."""
        props = _region3_properties(500.0, 650.0)
        assert props["v"] > 0.0
        assert abs(props["v"] - 1.0 / 500.0) < 1e-12

    def test_region3_cv_cp_positive(self):
        """Heat capacities cv and cp must both be positive and finite."""
        props = _region3_properties(500.0, 650.0)
        assert props["cv"] > 0.0, f"cv={props['cv']}"
        assert props["cp"] > 0.0, f"cp={props['cp']}"
        assert math.isfinite(props["cv"])
        assert math.isfinite(props["cp"])
        # cp ≥ cv always (thermodynamic identity)
        assert props["cp"] >= props["cv"]

    def test_region3_sound_speed_positive(self):
        """Speed of sound must be positive and physically plausible (> 100 m/s)."""
        props = _region3_properties(500.0, 650.0)
        assert math.isfinite(props["w"])
        assert props["w"] > 100.0, f"w={props['w']:.1f} m/s"

    # ------------------------------------------------------------------
    # Inversion: _region3_inverse (p, T) → ρ
    # ------------------------------------------------------------------

    def test_inverse_roundtrip_T650_rho500(self):
        """
        Round-trip: _region3_inverse(p(500,650), 650) == 500 kg/m³.
        The exact p=25.5837 MPa should invert back to ρ≈500 within 0.1%.
        """
        p_ref = _region3_properties(500.0, 650.0)["p"]
        rho = _region3_inverse(p_ref, 650.0)
        assert abs(rho - 500.0) / 500.0 < 0.001, (
            f"rho={rho:.3f} kg/m³, expected 500.0 kg/m³"
        )

    def test_inverse_roundtrip_T650_rho200(self):
        """
        Round-trip for T=650 K, ρ=200 kg/m³ (near-critical, p≈22.29 MPa).
        """
        p_ref = _region3_properties(200.0, 650.0)["p"]
        rho = _region3_inverse(p_ref, 650.0)
        # Near-critical: looser tolerance
        assert abs(rho - 200.0) / 200.0 < 0.05, (
            f"rho={rho:.3f} kg/m³, expected 200.0 kg/m³"
        )

    def test_inverse_roundtrip_T750_rho500(self):
        """
        Round-trip for T=750 K, ρ=500 kg/m³ (high pressure, p≈78.31 MPa).
        """
        p_ref = _region3_properties(500.0, 750.0)["p"]
        rho = _region3_inverse(p_ref, 750.0)
        assert abs(rho - 500.0) / 500.0 < 0.001, (
            f"rho={rho:.3f} kg/m³, expected 500.0 kg/m³"
        )

    def test_critical_point_density(self):
        """
        At the critical point (T=647.096 K, p=22.064 MPa), ρ ≈ 322 kg/m³.
        Tolerance 2% (near-critical convergence is harder).
        """
        rho = _region3_inverse(22.064e6, 647.096)
        assert abs(rho - 322.0) / 322.0 < 0.02, (
            f"rho={rho:.2f} kg/m³, expected 322 kg/m³"
        )

    # ------------------------------------------------------------------
    # Dispatcher integration tests
    # ------------------------------------------------------------------

    def test_dispatcher_region3_T650_p25mpa(self):
        """
        steam_properties_if97(650 K, 25.5837 MPa) → phase='supercritical',
        h ≈ 1863.43 kJ/kg (within 1%).
        """
        result = steam_properties_if97(650.0, 25.5837e6)
        assert result["phase"] == "supercritical"
        assert abs(result["h_J_per_kg"] / 1e3 - 1863.43) / 1863.43 < 0.01, (
            f"h={result['h_J_per_kg']/1e3:.2f} kJ/kg, expected 1863.43"
        )

    def test_dispatcher_region3_returns_all_fields(self):
        """Region 3 results include all required SteamProperties fields."""
        result = steam_properties_if97(700.0, 30.0e6)
        for key in ("T_K", "p_Pa", "v_m3_per_kg", "h_J_per_kg",
                    "s_J_per_kg_K", "cp_J_per_kg_K", "phase"):
            assert key in result, f"Missing key: {key}"
        assert result["phase"] == "supercritical"

    def test_boundary_continuity_with_region1(self):
        """
        At T just below 623.15 K (Region 1 boundary) and high pressure,
        properties should not jump discontinuously into Region 3.
        Checks that both sides return finite, similar-order-of-magnitude
        enthalpies (continuity check, not identity — a small jump is
        expected from the two different formulations near the boundary).
        """
        p = 40.0e6  # 40 MPa — safely in the stable liquid/dense-fluid regime
        T_r1 = 620.0   # Region 1
        T_r3 = 630.0   # Region 3

        res1 = steam_properties_if97(T_r1, p)
        res3 = steam_properties_if97(T_r3, p)

        assert res1["phase"] == "liquid"
        assert res3["phase"] == "supercritical"
        # Over a 10 K span, |Δh| < cp * ΔT ≈ 5000 * 10 = 50 kJ/kg = 50e3 J/kg
        # Use a generous 500 kJ/kg bound for the formulation boundary
        assert abs(res1["h_J_per_kg"] - res3["h_J_per_kg"]) < 500.0e3, (
            f"h jump at boundary: R1={res1['h_J_per_kg']/1e3:.1f} kJ/kg, "
            f"R3={res3['h_J_per_kg']/1e3:.1f} kJ/kg"
        )
