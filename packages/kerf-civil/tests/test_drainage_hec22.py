"""
Tests for kerf_civil.drainage — FHWA HEC-22 rational method.

Validation oracles
------------------
1. Rational method (direct): C=0.9, i=5 in/hr, A=2 acres → Q = 9 cfs
   (0.9 × 5 × 2 = 9.0, dimensionally exact)

2. Runoff coefficient lookup:
   - 'asphalt'    → 0.90  (HEC-22 Table 3-1: 0.85–0.95, mid = 0.90)
   - 'lawn_sandy' → 0.125 (HEC-22 Table 3-1: 0.05–0.20, mid = 0.125)

3. Kirpich Tc (L=1000 ft, S=0.02):
   Tc = 0.0078 × 1000^0.77 / 0.02^0.385
      = 0.0078 × 204.174 / 0.4475
      ≈ 7.181 min
   The test verifies the formula result within 1 % of the analytical value.
   Note: the task prompt cited "~14 minutes" as the oracle; the Kirpich
   formula (0.0078 × L^0.77 / S^0.385) analytically yields 7.18 min for
   these inputs.  The test is written against the correct formula value.

4. Composite watershed (HEC-22 §3.3 weighted-C):
   Sub-area 1: C=0.9, A=6 acres  (60 % of total 10 acres)
   Sub-area 2: C=0.2, A=4 acres  (40 % of total 10 acres)
   C_w = (0.9×6 + 0.2×4) / 10 = (5.4 + 0.8) / 10 = 0.62

References
----------
FHWA (2009) HEC-22, 3rd Edition, Urban Drainage Design Manual.
Kirpich, Z.P. (1940). Civil Engineering, 10(6), 362.
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_civil.drainage import (
    rational_method,
    runoff_coefficient_lookup,
    time_of_concentration,
    compute_design_flow,
)


# ---------------------------------------------------------------------------
# 1.  Rational Method — Q = C · i · A
# ---------------------------------------------------------------------------

class TestRationalMethodHEC22:
    """FHWA HEC-22 §3.1: Q = C · i · A [cfs]."""

    def test_asphalt_parking_lot_oracle(self):
        """HEC-22 §3.1 canonical: C=0.9, i=5 in/hr, A=2 acres → Q=9 cfs."""
        Q = rational_method(0.9, 5.0, 2.0)
        assert Q == pytest.approx(9.0, rel=1e-9), (
            f"Expected Q=9.0 cfs, got {Q}"
        )

    def test_zero_area_gives_zero_flow(self):
        assert rational_method(0.5, 5.0, 0.0) == 0.0

    def test_zero_intensity_gives_zero_flow(self):
        assert rational_method(0.9, 0.0, 2.0) == 0.0

    def test_full_impervious(self):
        """C=1.0 (fully impervious): Q = i × A."""
        Q = rational_method(1.0, 10.0, 5.0)
        assert Q == pytest.approx(50.0, rel=1e-9)

    def test_linearity_in_C(self):
        """Q scales linearly with C."""
        Q1 = rational_method(0.4, 3.0, 1.0)
        Q2 = rational_method(0.8, 3.0, 1.0)
        assert Q2 == pytest.approx(2.0 * Q1, rel=1e-9)

    def test_linearity_in_area(self):
        """Q scales linearly with area."""
        Q1 = rational_method(0.5, 4.0, 1.0)
        Q2 = rational_method(0.5, 4.0, 3.0)
        assert Q2 == pytest.approx(3.0 * Q1, rel=1e-9)

    def test_invalid_C_high(self):
        with pytest.raises(ValueError, match="runoff_coefficient_C"):
            rational_method(1.01, 5.0, 2.0)

    def test_invalid_C_negative(self):
        with pytest.raises(ValueError, match="runoff_coefficient_C"):
            rational_method(-0.1, 5.0, 2.0)

    def test_invalid_intensity_negative(self):
        with pytest.raises(ValueError, match="rainfall_intensity_i"):
            rational_method(0.5, -1.0, 2.0)

    def test_invalid_area_negative(self):
        with pytest.raises(ValueError, match="area_A_acres"):
            rational_method(0.5, 5.0, -0.1)


# ---------------------------------------------------------------------------
# 2.  Runoff coefficient lookup — HEC-22 Table 3-1
# ---------------------------------------------------------------------------

class TestRunoffCoefficientLookup:
    """HEC-22 Table 3-1 mid-range C values."""

    def test_asphalt_midrange(self):
        """asphalt: 0.85–0.95 → mid = 0.90."""
        C = runoff_coefficient_lookup("asphalt")
        assert C == pytest.approx(0.90, rel=1e-9), (
            f"asphalt C expected 0.90, got {C}"
        )

    def test_concrete_midrange(self):
        """concrete: 0.85–0.95 → mid = 0.90."""
        C = runoff_coefficient_lookup("concrete")
        assert C == pytest.approx(0.90, rel=1e-9)

    def test_lawn_sandy_midrange(self):
        """lawn_sandy: 0.05–0.20 → mid = 0.125."""
        C = runoff_coefficient_lookup("lawn_sandy")
        assert C == pytest.approx(0.125, rel=1e-9), (
            f"lawn_sandy C expected 0.125, got {C}"
        )

    def test_lawn_clay_midrange(self):
        """lawn_clay: 0.13–0.35 → mid = 0.24."""
        C = runoff_coefficient_lookup("lawn_clay")
        assert C == pytest.approx(0.24, rel=1e-9)

    def test_roofs_midrange(self):
        """roofs: 0.75–0.95 → mid = 0.85."""
        C = runoff_coefficient_lookup("roofs")
        assert C == pytest.approx(0.85, rel=1e-9)

    def test_gravel_drives_midrange(self):
        """gravel_drives: 0.30–0.50 → mid = 0.40."""
        C = runoff_coefficient_lookup("gravel_drives")
        assert C == pytest.approx(0.40, rel=1e-9)

    def test_forest_flat_midrange(self):
        """forest_flat: 0.05–0.30 → mid = 0.175."""
        C = runoff_coefficient_lookup("forest_flat")
        assert C == pytest.approx(0.175, rel=1e-9)

    def test_all_values_in_range(self):
        """All lookup values should be in [0, 1]."""
        surfaces = [
            "asphalt", "concrete", "roofs", "gravel_drives",
            "lawn_sandy", "lawn_clay", "forest_flat",
        ]
        for s in surfaces:
            C = runoff_coefficient_lookup(s)
            assert 0.0 <= C <= 1.0, f"{s}: C={C} out of [0,1]"

    def test_impervious_surfaces_higher_than_pervious(self):
        """Impervious covers should have higher C than pervious."""
        C_asphalt = runoff_coefficient_lookup("asphalt")
        C_lawn = runoff_coefficient_lookup("lawn_sandy")
        assert C_asphalt > C_lawn

    def test_unknown_surface_raises(self):
        with pytest.raises(ValueError, match="not in HEC-22"):
            runoff_coefficient_lookup("unknown_surface")

    def test_whitespace_strip(self):
        """Leading/trailing whitespace should be stripped."""
        C = runoff_coefficient_lookup("  asphalt  ")
        assert C == pytest.approx(0.90, rel=1e-9)


# ---------------------------------------------------------------------------
# 3.  Time of Concentration — Kirpich formula (HEC-22 §3.5)
# ---------------------------------------------------------------------------

class TestTimeOfConcentration:
    """Kirpich (1940) Tc = 0.0078 · L^0.77 / S^0.385 [minutes]."""

    def test_kirpich_analytical_oracle(self):
        """
        L=1000 ft, S=0.02:
        Tc = 0.0078 × 1000^0.77 / 0.02^0.385 ≈ 7.181 min.

        The formula is tested against its own analytical value (±1%).
        Note: an approximate '~14 min' reference exists in some project
        docs; the exact Kirpich formula yields 7.18 min for these inputs.
        """
        Tc = time_of_concentration(1000.0, 0.02, surface_kind="asphalt")
        expected = 0.0078 * (1000.0 ** 0.77) / (0.02 ** 0.385)
        assert Tc == pytest.approx(expected, rel=0.01), (
            f"Tc={Tc:.4f} expected≈{expected:.4f} min"
        )

    def test_tc_within_reasonable_range(self):
        """L=1000ft, S=0.02 → Tc should be in (5, 30) min."""
        Tc = time_of_concentration(1000.0, 0.02)
        assert 5.0 < Tc < 30.0, f"Tc={Tc:.2f} out of expected (5,30) range"

    def test_steeper_slope_shorter_tc(self):
        """Steeper slope → shorter travel time → smaller Tc."""
        Tc_flat = time_of_concentration(1000.0, 0.005)
        Tc_steep = time_of_concentration(1000.0, 0.05)
        assert Tc_steep < Tc_flat

    def test_longer_path_longer_tc(self):
        """Longer flow path → greater Tc."""
        Tc_short = time_of_concentration(500.0, 0.02)
        Tc_long = time_of_concentration(2000.0, 0.02)
        assert Tc_long > Tc_short

    def test_surface_kind_does_not_change_tc(self):
        """Kirpich formula is geometry-based; surface_kind is informational."""
        Tc_asphalt = time_of_concentration(800.0, 0.01, "asphalt")
        Tc_lawn = time_of_concentration(800.0, 0.01, "lawn_sandy")
        assert Tc_asphalt == pytest.approx(Tc_lawn, rel=1e-9)

    def test_zero_length_raises(self):
        with pytest.raises(ValueError, match="length_ft"):
            time_of_concentration(0.0, 0.02)

    def test_negative_length_raises(self):
        with pytest.raises(ValueError, match="length_ft"):
            time_of_concentration(-100.0, 0.02)

    def test_zero_slope_raises(self):
        with pytest.raises(ValueError, match="slope"):
            time_of_concentration(1000.0, 0.0)

    def test_negative_slope_raises(self):
        with pytest.raises(ValueError, match="slope"):
            time_of_concentration(1000.0, -0.01)


# ---------------------------------------------------------------------------
# 4.  Composite watershed — HEC-22 §3.3 weighted-C method
# ---------------------------------------------------------------------------

class TestCompositeDesignFlow:
    """HEC-22 §3.3: C_w = Σ(C_j · A_j) / Σ(A_j)."""

    def test_weighted_c_oracle(self):
        """
        60 % asphalt (C=0.9), 40 % forest (C=0.2):
        C_w = (0.9×6 + 0.2×4) / 10 = 6.2/10 = 0.62
        """
        watershed = [
            {"C": 0.9, "area_acres": 6.0},
            {"C": 0.2, "area_acres": 4.0},
        ]
        result = compute_design_flow(watershed, return_period_years=10)
        assert result["ok"] is True
        assert result["weighted_C"] == pytest.approx(0.62, rel=1e-6), (
            f"weighted_C={result['weighted_C']}, expected≈0.62"
        )

    def test_weighted_c_total_area(self):
        """Total area should equal sum of sub-areas."""
        watershed = [
            {"C": 0.9, "area_acres": 6.0},
            {"C": 0.2, "area_acres": 4.0},
        ]
        result = compute_design_flow(watershed)
        assert result["total_area_acres"] == pytest.approx(10.0, rel=1e-9)

    def test_composite_flow_with_intensity(self):
        """Supplying i should compute Q_cfs = C_w · i · A."""
        watershed = [
            {"C": 0.9, "area_acres": 6.0},
            {"C": 0.2, "area_acres": 4.0},
        ]
        result = compute_design_flow(watershed, rainfall_intensity_i=5.0)
        assert result["ok"] is True
        assert result["Q_cfs"] == pytest.approx(0.62 * 5.0 * 10.0, rel=1e-5)

    def test_composite_no_intensity_q_is_none(self):
        """Without intensity, Q should be None."""
        watershed = [{"C": 0.5, "area_acres": 2.0}]
        result = compute_design_flow(watershed)
        assert result["Q_cfs"] is None
        assert result["Q_m3s"] is None
        assert any("rainfall_intensity_i" in w for w in result["warnings"])

    def test_surface_kind_lookup_in_composite(self):
        """Sub-areas can use surface_kind instead of explicit C."""
        watershed = [
            {"surface_kind": "asphalt", "area_acres": 3.0},   # C=0.90
            {"surface_kind": "lawn_sandy", "area_acres": 7.0},  # C=0.125
        ]
        result = compute_design_flow(watershed)
        assert result["ok"] is True
        expected_C_w = (0.90 * 3.0 + 0.125 * 7.0) / 10.0
        assert result["weighted_C"] == pytest.approx(expected_C_w, rel=1e-5)

    def test_single_subarea_equals_its_c(self):
        """One sub-area: C_w must equal that sub-area's C."""
        watershed = [{"C": 0.75, "area_acres": 5.0}]
        result = compute_design_flow(watershed)
        assert result["weighted_C"] == pytest.approx(0.75, rel=1e-9)

    def test_empty_watershed_returns_error(self):
        result = compute_design_flow([])
        assert result["ok"] is False

    def test_missing_area_returns_error(self):
        result = compute_design_flow([{"C": 0.5}])
        assert result["ok"] is False
        assert "area_acres" in result["reason"]

    def test_missing_c_and_surface_kind_returns_error(self):
        result = compute_design_flow([{"area_acres": 2.0}])
        assert result["ok"] is False

    def test_negative_area_returns_error(self):
        result = compute_design_flow([{"C": 0.5, "area_acres": -1.0}])
        assert result["ok"] is False

    def test_return_period_echoed(self):
        watershed = [{"C": 0.5, "area_acres": 1.0}]
        result = compute_design_flow(watershed, return_period_years=25)
        assert result["return_period_years"] == 25

    def test_weighted_c_impervious_dominant(self):
        """Mostly impervious watershed: C_w closer to upper bound."""
        watershed = [
            {"C": 0.9, "area_acres": 9.0},
            {"C": 0.1, "area_acres": 1.0},
        ]
        result = compute_design_flow(watershed)
        assert result["weighted_C"] == pytest.approx(0.82, rel=1e-6)


# ---------------------------------------------------------------------------
# 5.  LLM tool handlers
# ---------------------------------------------------------------------------

class TestLLMToolDrainageRationalMethod:
    """civil_drainage_rational_method tool smoke tests."""

    def _run(self, params: dict) -> dict:
        from kerf_civil.tools_hydraulics import run_civil_drainage_rational_method
        from kerf_civil._compat import ProjectCtx
        return json.loads(asyncio.run(run_civil_drainage_rational_method(params, ProjectCtx())))

    def test_basic_oracle_via_tool(self):
        """C=0.9, i=5 in/hr, A=2 acres → Q=9 cfs via tool."""
        data = self._run({"C": 0.9, "i_in_per_hr": 5.0, "area_acres": 2.0})
        assert data["ok"] is True
        assert data["Q_cfs"] == pytest.approx(9.0, rel=1e-5)

    def test_surface_kind_lookup_via_tool(self):
        """surface_kind='asphalt' should auto-lookup C=0.90."""
        data = self._run({"surface_kind": "asphalt", "i_in_per_hr": 5.0, "area_acres": 2.0})
        assert data["ok"] is True
        assert data["weighted_C"] == pytest.approx(0.90, rel=1e-5)

    def test_composite_watershed_via_tool(self):
        """Composite: C_w=0.62 for 60% C=0.9 + 40% C=0.2."""
        watershed = [
            {"C": 0.9, "area_acres": 6.0},
            {"C": 0.2, "area_acres": 4.0},
        ]
        data = self._run({"watershed": watershed, "i_in_per_hr": 5.0})
        assert data["ok"] is True
        assert data["weighted_C"] == pytest.approx(0.62, rel=1e-5)

    def test_missing_c_and_surface_returns_error(self):
        data = self._run({"i_in_per_hr": 5.0, "area_acres": 2.0})
        assert data.get("ok") is not True or "error" in data


class TestLLMToolTimeOfConcentration:
    """civil_time_of_concentration tool smoke tests."""

    def _run(self, params: dict) -> dict:
        from kerf_civil.tools_hydraulics import run_civil_time_of_concentration
        from kerf_civil._compat import ProjectCtx
        return json.loads(asyncio.run(run_civil_time_of_concentration(params, ProjectCtx())))

    def test_kirpich_via_tool(self):
        """L=1000ft, S=0.02 → Tc ≈ 7.18 min via tool."""
        data = self._run({"length_ft": 1000.0, "slope": 0.02})
        assert data["ok"] is True
        expected = 0.0078 * (1000.0 ** 0.77) / (0.02 ** 0.385)
        assert data["Tc_min"] == pytest.approx(expected, rel=0.01)

    def test_tc_hr_consistent(self):
        """Tc_hr must equal Tc_min / 60 (allowing for independent rounding)."""
        data = self._run({"length_ft": 800.0, "slope": 0.015})
        assert data["ok"] is True
        # Tool rounds Tc_min to 4 dp and Tc_hr to 6 dp independently;
        # allow up to 0.001 min of discrepancy from rounding.
        assert data["Tc_hr"] == pytest.approx(data["Tc_min"] / 60.0, abs=1e-4)

    def test_formula_field_present(self):
        data = self._run({"length_ft": 500.0, "slope": 0.03})
        assert data.get("formula") == "kirpich_hec22"

    def test_zero_slope_returns_error(self):
        data = self._run({"length_ft": 1000.0, "slope": 0.0})
        assert data.get("ok") is not True or "error" in data
