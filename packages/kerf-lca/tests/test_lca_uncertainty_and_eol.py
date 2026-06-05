"""
test_lca_uncertainty_and_eol.py

Tests for:
  - kerf_lca.uncertainty (impact_uncertainty_bounds, monte_carlo_uncertainty)
  - kerf_lca.tools.lca_uncertainty (LLM tool dispatch)
  - kerf_lca.eol_circularity (Module D, MCI)
  - kerf_lca.tools.eol_circularity (LLM tool dispatch)
  - kerf_lca.plugin (registration of all 10 tools)

Oracle values are derived from:
  ISO 14044:2006 section 4.5 (uncertainty analysis)
  EN 15978:2011 section 11.4 (Module D)
  Ellen MacArthur Foundation MCI methodology (2015)
  Ecoinvent pedigree matrix GSD2 defaults (Weidema et al., 2013)
"""

from __future__ import annotations

import asyncio
import json
import math
import types
import uuid

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def _ctx():
    ctx = types.SimpleNamespace()
    ctx.project_id = uuid.uuid4()
    ctx.pool = None
    ctx.storage = None
    return ctx


# ---------------------------------------------------------------------------
# 1. uncertainty.impact_uncertainty_bounds
# ---------------------------------------------------------------------------

class TestImpactUncertaintyBounds:
    def test_gwp100_ci_width(self):
        """GSD2=1.05 for gwp100 → very tight CI."""
        from kerf_lca.uncertainty import impact_uncertainty_bounds
        res = impact_uncertainty_bounds(100.0, "gwp100")
        assert res["ci_low"] < 100.0 < res["ci_high"]
        # GSD2=1.05 → sigma_ln=0.5*ln(1.05)≈0.0244 → 90%CI is tight
        # expect ci_high < 1.20 * mean
        assert res["ci_high"] < 120.0

    def test_htp_wide_ci(self):
        """GSD2=2.00 for htp → wider CI."""
        from kerf_lca.uncertainty import impact_uncertainty_bounds
        res = impact_uncertainty_bounds(1.0, "htp")
        # HTP GSD2=2.0 → sigma_ln=0.5*ln(2.0)≈0.347 → P5=exp(-1.645*0.347)≈0.564
        assert res["ci_low"] < 0.8 * res["mean"]
        assert res["ci_high"] > 1.2 * res["mean"]

    def test_zero_impact_no_error(self):
        from kerf_lca.uncertainty import impact_uncertainty_bounds
        res = impact_uncertainty_bounds(0.0, "gwp100")
        assert res["mean"] == 0.0
        assert res["ci_low"] == 0.0
        assert res["ci_high"] == 0.0

    def test_gsd2_returned(self):
        from kerf_lca.uncertainty import impact_uncertainty_bounds
        res = impact_uncertainty_bounds(50.0, "ap")
        assert "gsd2" in res
        assert math.isclose(res["gsd2"], 1.20, rel_tol=1e-6)

    def test_unknown_category_uses_fallback(self):
        from kerf_lca.uncertainty import impact_uncertainty_bounds, _GSD2_FALLBACK
        res = impact_uncertainty_bounds(10.0, "unknown_cat")
        # Should not raise; uses fallback GSD2
        assert res["ci_low"] < 10.0 < res["ci_high"]

    @pytest.mark.parametrize("category", ["gwp100", "ap", "ep", "htp", "water", "pm25"])
    def test_all_standard_categories(self, category):
        from kerf_lca.uncertainty import impact_uncertainty_bounds
        res = impact_uncertainty_bounds(1.0, category)
        assert res["ci_low"] <= res["mean"] <= res["ci_high"]


# ---------------------------------------------------------------------------
# 2. uncertainty.monte_carlo_uncertainty
# ---------------------------------------------------------------------------

class TestMonteCarlo:
    def _model(self, **kwargs):
        return sum(kwargs.values())

    def test_single_param_mean_close_to_input(self):
        from kerf_lca.uncertainty import monte_carlo_uncertainty
        res = monte_carlo_uncertainty(
            self._model,
            {"factor": {"mean": 10.0, "gsd2": 1.05}},
            n_samples=10_000,
            seed=42,
        )
        # Mean of lognormal(mean=10, GSD2=1.05) should be ≈10
        assert math.isclose(res["mean"], 10.0, rel_tol=0.05)

    def test_ci_bounds_ordered(self):
        from kerf_lca.uncertainty import monte_carlo_uncertainty
        res = monte_carlo_uncertainty(
            self._model,
            {"a": {"mean": 5.0, "gsd2": 1.2}, "b": {"mean": 3.0, "gsd2": 1.3}},
            n_samples=5_000, seed=42,
        )
        assert res["ci_low"] < res["mean"] < res["ci_high"]

    def test_deterministic_with_gsd1(self):
        """GSD2=1.0 means no uncertainty — all samples equal mean."""
        from kerf_lca.uncertainty import monte_carlo_uncertainty
        res = monte_carlo_uncertainty(
            self._model,
            {"x": {"mean": 7.0, "gsd2": 1.0}},
            n_samples=100, seed=42,
        )
        # With GSD2<=1.0, all samples = mean → std = 0
        assert math.isclose(res["std"], 0.0, abs_tol=1e-9)

    def test_reproducible_seed(self):
        from kerf_lca.uncertainty import monte_carlo_uncertainty
        res1 = monte_carlo_uncertainty(
            self._model, {"x": {"mean": 10.0, "gsd2": 1.2}},
            n_samples=1000, seed=99,
        )
        res2 = monte_carlo_uncertainty(
            self._model, {"x": {"mean": 10.0, "gsd2": 1.2}},
            n_samples=1000, seed=99,
        )
        assert math.isclose(res1["mean"], res2["mean"], rel_tol=1e-12)

    def test_n_samples_returned(self):
        from kerf_lca.uncertainty import monte_carlo_uncertainty
        res = monte_carlo_uncertainty(
            self._model, {"x": {"mean": 1.0, "gsd2": 1.1}},
            n_samples=500, seed=42,
        )
        assert res["n_samples"] == 500


# ---------------------------------------------------------------------------
# 3. LLM tool: lca_impact_uncertainty_bounds
# ---------------------------------------------------------------------------

class TestLCAImpactUncertaintyTool:
    def _get(self):
        try:
            from kerf_lca.tools.lca_uncertainty import (
                lca_impact_uncertainty_bounds_spec,
                run_lca_impact_uncertainty_bounds,
            )
            return lca_impact_uncertainty_bounds_spec, run_lca_impact_uncertainty_bounds
        except ImportError:
            pytest.skip("kerf_chat unavailable")

    def test_spec_name(self):
        spec, _ = self._get()
        assert spec.name == "lca_impact_uncertainty_bounds"

    def test_missing_impact_value(self):
        _, handler = self._get()
        result = run(handler(_ctx(), json.dumps({"category": "gwp100"}).encode()))
        d = json.loads(result)
        assert d.get("ok") is not True

    def test_missing_category(self):
        _, handler = self._get()
        result = run(handler(_ctx(), json.dumps({"impact_value": 10.0}).encode()))
        d = json.loads(result)
        assert d.get("ok") is not True

    def test_valid_call(self):
        _, handler = self._get()
        payload = json.dumps({"impact_value": 50.0, "category": "gwp100"}).encode()
        result = run(handler(_ctx(), payload))
        d = json.loads(result)
        assert d.get("ok") is not False, f"unexpected error: {d}"
        inner = d.get("result", d)
        assert "mean" in inner
        assert "ci_low" in inner
        assert "ci_high" in inner
        assert inner["mean"] == 50.0

    def test_bad_json(self):
        _, handler = self._get()
        result = run(handler(_ctx(), b"not-json"))
        d = json.loads(result)
        assert d.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 4. LLM tool: lca_monte_carlo_uncertainty
# ---------------------------------------------------------------------------

class TestLCAMonteCarloTool:
    def _get(self):
        try:
            from kerf_lca.tools.lca_uncertainty import (
                lca_monte_carlo_uncertainty_spec,
                run_lca_monte_carlo_uncertainty,
            )
            return lca_monte_carlo_uncertainty_spec, run_lca_monte_carlo_uncertainty
        except ImportError:
            pytest.skip("kerf_chat unavailable")

    def test_spec_name(self):
        spec, _ = self._get()
        assert spec.name == "lca_monte_carlo_uncertainty"

    def test_missing_parameters(self):
        _, handler = self._get()
        result = run(handler(_ctx(), b"{}"))
        d = json.loads(result)
        assert d.get("ok") is not True

    def test_valid_call(self):
        _, handler = self._get()
        payload = json.dumps({
            "parameters": [
                {"name": "steel_gwp", "mean": 18.0, "gsd2": 1.05},
                {"name": "transport", "mean": 2.5, "gsd2": 1.20},
            ],
            "n_samples": 1000,
        }).encode()
        result = run(handler(_ctx(), payload))
        d = json.loads(result)
        assert d.get("ok") is not False, f"unexpected: {d}"
        inner = d.get("result", d)
        assert "mean" in inner
        assert math.isclose(inner["mean"], 20.5, rel_tol=0.1)  # 18+2.5≈20.5


# ---------------------------------------------------------------------------
# 5. eol_circularity: Module D credit
# ---------------------------------------------------------------------------

class TestModuleDCredit:
    def test_recycling_credit_steel(self):
        from kerf_lca.eol_circularity import compute_module_d_credit, EolScenario
        scenario = EolScenario(scenario_type="recycling", recovery_efficiency=0.90)
        result = compute_module_d_credit("steel", 10.0, scenario)
        # Should return a credit (negative or zero net burden)
        assert isinstance(result, dict)
        assert "module_d_credit_kg_co2" in result
        assert result["module_d_credit_kg_co2"] > 0  # credit is positive value

    def test_landfill_zero_credit(self):
        from kerf_lca.eol_circularity import compute_module_d_credit, EolScenario
        scenario = EolScenario(scenario_type="landfill")
        result = compute_module_d_credit("concrete", 100.0, scenario)
        assert isinstance(result, dict)
        # Landfill → zero or minimal module D credit
        assert result.get("module_d_credit_kg_co2", 0.0) == 0.0

    def test_reuse_credit(self):
        from kerf_lca.eol_circularity import compute_module_d_credit, EolScenario
        scenario = EolScenario(scenario_type="reuse", recovery_efficiency=0.95, displacement_factor=1.0)
        result = compute_module_d_credit("aluminium", 5.0, scenario)
        # Reuse with full displacement → credit > recycling credit
        assert result["module_d_credit_kg_co2"] > 0


# ---------------------------------------------------------------------------
# 6. eol_circularity: MCI
# ---------------------------------------------------------------------------

class TestCircularityIndex:
    def test_mci_range(self):
        from kerf_lca.eol_circularity import circularity_index
        mci = circularity_index("steel", {})
        assert 0.0 <= mci <= 1.0

    def test_higher_recycled_input_higher_mci(self):
        from kerf_lca.eol_circularity import circularity_index
        mci_low = circularity_index("aluminium", {"recycled_input_fraction": 0.0})
        mci_high = circularity_index("aluminium", {"recycled_input_fraction": 1.0})
        assert mci_high > mci_low

    def test_landfill_eol_lower_mci(self):
        from kerf_lca.eol_circularity import circularity_index
        mci_recycle = circularity_index("steel", {"eol_scenario": "recycling"})
        mci_landfill = circularity_index("steel", {"eol_scenario": "landfill"})
        assert mci_recycle > mci_landfill


# ---------------------------------------------------------------------------
# 7. LLM tool: lca_module_d_credit
# ---------------------------------------------------------------------------

class TestModuleDCreditTool:
    def _get(self):
        try:
            from kerf_lca.tools.eol_circularity import module_d_credit_spec, run_lca_module_d_credit
            return module_d_credit_spec, run_lca_module_d_credit
        except ImportError:
            pytest.skip("kerf_chat unavailable")

    def test_spec_name(self):
        spec, _ = self._get()
        assert spec.name == "lca_module_d_credit"

    def test_missing_material(self):
        _, handler = self._get()
        result = run(handler(_ctx(), json.dumps({
            "mass_kg": 10.0,
            "eol_scenario": {"scenario_type": "recycling"},
        }).encode()))
        d = json.loads(result)
        assert d.get("ok") is not True

    def test_valid_call(self):
        _, handler = self._get()
        result = run(handler(_ctx(), json.dumps({
            "material": "steel",
            "mass_kg": 10.0,
            "eol_scenario": {"scenario_type": "recycling", "recovery_efficiency": 0.9},
        }).encode()))
        d = json.loads(result)
        assert d.get("ok") is not False, f"unexpected: {d}"
        inner = d.get("result", d)
        assert "module_d_credit_kg_co2" in inner


# ---------------------------------------------------------------------------
# 8. LLM tool: lca_circularity_index
# ---------------------------------------------------------------------------

class TestCircularityIndexTool:
    def _get(self):
        try:
            from kerf_lca.tools.eol_circularity import circularity_index_spec, run_lca_circularity_index
            return circularity_index_spec, run_lca_circularity_index
        except ImportError:
            pytest.skip("kerf_chat unavailable")

    def test_spec_name(self):
        spec, _ = self._get()
        assert spec.name == "lca_circularity_index"

    def test_valid_call(self):
        _, handler = self._get()
        result = run(handler(_ctx(), json.dumps({"material": "aluminium"}).encode()))
        d = json.loads(result)
        assert d.get("ok") is not False, f"unexpected: {d}"
        inner = d.get("result", d)
        assert "circularity_index" in inner
        assert 0.0 <= inner["circularity_index"] <= 1.0

    def test_missing_material(self):
        _, handler = self._get()
        result = run(handler(_ctx(), b"{}"))
        d = json.loads(result)
        assert d.get("ok") is not True


# ---------------------------------------------------------------------------
# 9. LLM tool: lca_full_lifecycle
# ---------------------------------------------------------------------------

class TestFullLifecycleTool:
    def _get(self):
        try:
            from kerf_lca.tools.eol_circularity import full_lifecycle_spec, run_lca_full_lifecycle
            return full_lifecycle_spec, run_lca_full_lifecycle
        except ImportError:
            pytest.skip("kerf_chat unavailable")

    def test_spec_name(self):
        spec, _ = self._get()
        assert spec.name == "lca_full_lifecycle"

    def test_valid_call(self):
        _, handler = self._get()
        result = run(handler(_ctx(), json.dumps({
            "material": "steel",
            "mass_kg": 5.0,
            "lifetime_years": 10.0,
            "eol_scenario": {"scenario_type": "recycling"},
        }).encode()))
        d = json.loads(result)
        assert d.get("ok") is not False, f"unexpected: {d}"
        inner = d.get("result", d)
        assert any(k for k in inner if "co2" in k.lower()), f"no co2 key in {list(inner.keys())}"

    def test_missing_required_field(self):
        _, handler = self._get()
        result = run(handler(_ctx(), json.dumps({
            "material": "steel",
            "mass_kg": 5.0,
            # missing lifetime_years and eol_scenario
        }).encode()))
        d = json.loads(result)
        assert d.get("ok") is not True


# ---------------------------------------------------------------------------
# 10. Plugin: all 10 LCA tools registered
# ---------------------------------------------------------------------------

class TestLCAPluginRegistration:
    """
    Verify that kerf_lca.plugin._tool_modules lists all 10 tools.
    We inspect the module-level list without actually loading the plugin
    (which requires the kerf runtime).
    """

    def test_ten_tool_entries(self):
        import ast
        import pathlib
        plugin_path = pathlib.Path(__file__).parent.parent / "src" / "kerf_lca" / "plugin.py"
        source = plugin_path.read_text()
        # Count lines that look like tool module tuples
        tree = ast.parse(source)
        # Look for _tool_modules = [...] assignment
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_tool_modules":
                        assert isinstance(node.value, ast.List)
                        n = len(node.value.elts)
                        assert n >= 10, f"Expected >= 10 tool entries, got {n}"
                        return
        pytest.fail("_tool_modules not found in plugin.py")

    def test_eol_circularity_in_plugin(self):
        import pathlib
        plugin_path = pathlib.Path(__file__).parent.parent / "src" / "kerf_lca" / "plugin.py"
        source = plugin_path.read_text()
        assert "eol_circularity" in source, "eol_circularity not registered in plugin.py"

    def test_lca_uncertainty_in_plugin(self):
        import pathlib
        plugin_path = pathlib.Path(__file__).parent.parent / "src" / "kerf_lca" / "plugin.py"
        source = plugin_path.read_text()
        assert "lca_uncertainty" in source, "lca_uncertainty not registered in plugin.py"

    def test_provides_uncertainty_in_plugin(self):
        import pathlib
        plugin_path = pathlib.Path(__file__).parent.parent / "src" / "kerf_lca" / "plugin.py"
        source = plugin_path.read_text()
        assert "lca.uncertainty" in source

    def test_provides_eol_circularity_in_plugin(self):
        import pathlib
        plugin_path = pathlib.Path(__file__).parent.parent / "src" / "kerf_lca" / "plugin.py"
        source = plugin_path.read_text()
        assert "lca.eol_circularity" in source
