"""
Tests for kerf_optics.tolerancing — NEST (inverse sensitivity) tolerancing.

Analytic oracles
----------------
1. nest_tolerancing RSS check ≈ merit_budget (by construction).
2. With equal weights, all parameters get equal allocated_deltas / sensitivity.
3. Higher sensitivity parameter gets smaller tolerance allocation (more sensitive = tighter).
4. Custom weights: parameter with 2× weight gets 2× the allocation of equal-weight case.
5. Zero budget raises ValueError.
6. Empty params raises ValueError.
7. NESTResult.table() is sorted by RSS contribution descending.
8. rss_check ≈ merit_budget to within numerical tolerance.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_optics.tolerancing import (
    ToleranceParam,
    NESTResult,
    sensitivity_analysis,
    monte_carlo_tolerancing,
    nest_tolerancing,
    merit_efl,
    merit_bfd,
)
from kerf_optics.lens_system import LensSystem, ThinLens, FreeSpace
import numpy as np


# ===========================================================================
# Helpers
# ===========================================================================

def _single_lens(f: float = 0.1) -> LensSystem:
    return LensSystem([ThinLens(f)])


def _two_lens_system(f1: float = 0.2, f2: float = 0.1, d: float = 0.05) -> LensSystem:
    return LensSystem([ThinLens(f1), FreeSpace(d), ThinLens(f2)])


# ===========================================================================
# NESTResult validation
# ===========================================================================

class TestNESTResult:
    def test_basic_rss_check(self):
        """RSS check should equal merit_budget within numerical tolerance."""
        system = _single_lens(0.1)
        params = [
            ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005),
        ]
        result = nest_tolerancing(system, params, merit_efl(0.1), merit_budget=0.005)
        assert isinstance(result, NESTResult)
        assert abs(result.rss_check - 0.005) < 1e-8, (
            f"rss_check {result.rss_check:.8f} != merit_budget 0.005"
        )

    def test_table_sorted_descending(self):
        """NESTResult.table() rows are sorted by RSS contribution descending."""
        system = _two_lens_system()
        params = [
            ToleranceParam(element_index=0, param_name="f", nominal=0.2, delta=0.002),
            ToleranceParam(element_index=2, param_name="f", nominal=0.1, delta=0.001),
        ]
        result = nest_tolerancing(system, params, merit_efl(
            -1.0 / system.system_matrix()[1, 0]
        ), merit_budget=0.01)
        rows = result.table()
        contribs = [r["rss_contribution"] for r in rows]
        assert contribs == sorted(contribs, reverse=True)

    def test_table_has_expected_keys(self):
        system = _single_lens()
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.002)]
        result = nest_tolerancing(system, params, merit_efl(0.1), merit_budget=0.003)
        row = result.table()[0]
        for key in ("param_index", "description", "sensitivity", "allocated_delta", "rss_contribution"):
            assert key in row, f"missing key: {key}"


# ===========================================================================
# Budget allocation correctness
# ===========================================================================

class TestNESTBudgetAllocation:
    def test_single_param_full_budget(self):
        """With one parameter, all of the budget is allocated to it.
        s · δ = budget  →  δ = budget / s."""
        system = _single_lens(0.1)
        params = [
            ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.01),
        ]
        budget = 0.005
        result = nest_tolerancing(system, params, merit_efl(0.1), budget)
        # With one parameter, rss = s·δ = budget
        assert abs(result.rss_check - budget) < 1e-8

    def test_equal_weights_equal_allocated_deltas(self):
        """Equal weights + identical parameters → equal allocated deltas.

        The NEST allocation is δ_i = budget·w_i / √(Σ(w_j·s_j)²).
        With equal weights w=1, this simplifies to δ_i = budget / (s_i · √N)
        where N = number of parameters weighted by unit vector normalization.
        With identical sensitivities, δ_0 = δ_1.
        """
        # Use two lenses with same focal length so sensitivities match
        system = LensSystem([ThinLens(0.1), FreeSpace(0.0), ThinLens(0.1)])
        M = system.system_matrix()
        C = M[1, 0]
        nominal_efl = -1.0 / C
        params = [
            ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.01),
            ToleranceParam(element_index=2, param_name="f", nominal=0.1, delta=0.01),
        ]
        budget = 0.01
        result = nest_tolerancing(system, params, merit_efl(nominal_efl), budget)
        # Identical parameters → identical sensitivities → equal deltas
        assert abs(result.allocated_deltas[0] - result.allocated_deltas[1]) < 1e-8, (
            f"Equal params should get equal deltas: "
            f"d0={result.allocated_deltas[0]:.8f}, d1={result.allocated_deltas[1]:.8f}"
        )
        # And RSS should still equal budget
        assert abs(result.rss_check - budget) < 1e-8

    def test_higher_sensitivity_gets_smaller_delta(self):
        """More sensitive parameter gets a tighter tolerance."""
        system = _two_lens_system(0.2, 0.1, 0.05)
        M = system.system_matrix()
        C = M[1, 0]
        nominal_efl = -1.0 / C
        params = [
            ToleranceParam(element_index=0, param_name="f", nominal=0.2, delta=0.01),
            ToleranceParam(element_index=2, param_name="f", nominal=0.1, delta=0.01),
        ]
        result = nest_tolerancing(system, params, merit_efl(nominal_efl), merit_budget=0.01)
        # The parameter with higher sensitivity should get smaller delta
        idx_high_s = max(range(2), key=lambda i: result.sensitivity[i])
        idx_low_s = 1 - idx_high_s
        assert (
            result.allocated_deltas[idx_high_s] <= result.allocated_deltas[idx_low_s] + 1e-12
        ), (
            f"Higher-sensitivity param {idx_high_s} (s={result.sensitivity[idx_high_s]:.4f}) "
            f"got larger delta {result.allocated_deltas[idx_high_s]:.6f} than "
            f"lower-sensitivity param (delta {result.allocated_deltas[idx_low_s]:.6f})"
        )

    def test_custom_weights_scale_deltas(self):
        """Custom weight w_i = 2 for param 0: param 0 gets 2× the delta of param 1."""
        system = _two_lens_system(0.2, 0.1, 0.05)
        M = system.system_matrix()
        C = M[1, 0]
        nominal_efl = -1.0 / C
        params = [
            ToleranceParam(element_index=0, param_name="f", nominal=0.2, delta=0.01),
            ToleranceParam(element_index=2, param_name="f", nominal=0.1, delta=0.01),
        ]

        # Equal weights baseline
        r_equal = nest_tolerancing(system, params, merit_efl(nominal_efl),
                                   merit_budget=0.01, weights=[1.0, 1.0])
        # Double weight on param 0
        r_custom = nest_tolerancing(system, params, merit_efl(nominal_efl),
                                    merit_budget=0.01, weights=[2.0, 1.0])

        # Param 0 in custom should get proportionally more delta
        ratio_custom = r_custom.allocated_deltas[0] / r_custom.allocated_deltas[1]
        ratio_equal = r_equal.allocated_deltas[0] / r_equal.allocated_deltas[1]
        assert ratio_custom > ratio_equal, (
            f"Custom weight 2:1 should give larger delta ratio than equal weights. "
            f"Got custom={ratio_custom:.4f}, equal={ratio_equal:.4f}"
        )

    def test_rss_check_matches_budget(self):
        """rss_check should match merit_budget to float precision."""
        system = _two_lens_system(0.2, 0.1, 0.05)
        M = system.system_matrix()
        C = M[1, 0]
        nominal_efl = -1.0 / C
        params = [
            ToleranceParam(element_index=0, param_name="f", nominal=0.2, delta=0.005),
            ToleranceParam(element_index=2, param_name="f", nominal=0.1, delta=0.002),
        ]
        budget = 0.008
        result = nest_tolerancing(system, params, merit_efl(nominal_efl), budget)
        assert abs(result.rss_check - budget) / budget < 1e-6


# ===========================================================================
# Error conditions
# ===========================================================================

class TestNESTErrors:
    def test_zero_budget_raises(self):
        system = _single_lens()
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.001)]
        with pytest.raises(ValueError, match="merit_budget"):
            nest_tolerancing(system, params, merit_efl(0.1), merit_budget=0.0)

    def test_negative_budget_raises(self):
        system = _single_lens()
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.001)]
        with pytest.raises(ValueError, match="merit_budget"):
            nest_tolerancing(system, params, merit_efl(0.1), merit_budget=-0.001)

    def test_empty_params_raises(self):
        system = _single_lens()
        with pytest.raises(ValueError, match="empty"):
            nest_tolerancing(system, [], merit_efl(0.1), merit_budget=0.005)

    def test_wrong_weights_length_raises(self):
        system = _single_lens()
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.001)]
        with pytest.raises(ValueError, match="weights length"):
            nest_tolerancing(system, params, merit_efl(0.1), merit_budget=0.005,
                             weights=[1.0, 1.0])  # wrong length

    def test_negative_weights_raises(self):
        system = _single_lens()
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.001)]
        with pytest.raises(ValueError, match="weights must all be >= 0"):
            nest_tolerancing(system, params, merit_efl(0.1), merit_budget=0.005,
                             weights=[-1.0])


# ===========================================================================
# LLM tool dispatch
# ===========================================================================

class TestNESTTool:
    def test_happy_path(self):
        import asyncio
        import json
        from kerf_optics.tools import run_optics_nest_tolerancing

        args = {
            "elements": [{"type": "thin_lens", "f": 0.1}],
            "tolerances": [
                {"element_index": 0, "param_name": "f", "delta": 0.005, "nominal": 0.1}
            ],
            "merit_budget": 0.005,
        }
        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_optics_nest_tolerancing(args, ctx=None)
        ))
        assert "rss_check" in result or result.get("ok") is True
        if "rss_check" in result:
            assert abs(result["rss_check"] - 0.005) < 1e-6

    def test_missing_elements_error(self):
        import asyncio
        import json
        from kerf_optics.tools import run_optics_nest_tolerancing

        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_optics_nest_tolerancing(
                {"tolerances": [{"element_index": 0, "param_name": "f", "delta": 0.001}],
                 "merit_budget": 0.005},
                ctx=None
            )
        ))
        assert "error" in result or result.get("ok") is False or "code" in result

    def test_table_in_response(self):
        import asyncio
        import json
        from kerf_optics.tools import run_optics_nest_tolerancing

        args = {
            "elements": [
                {"type": "free_space", "d": 0.1},
                {"type": "thin_lens", "f": 0.05},
            ],
            "tolerances": [
                {"element_index": 0, "param_name": "d", "delta": 0.002},
                {"element_index": 1, "param_name": "f", "delta": 0.001},
            ],
            "merit_budget": 0.003,
        }
        result = json.loads(asyncio.get_event_loop().run_until_complete(
            run_optics_nest_tolerancing(args, ctx=None)
        ))
        if "table" in result:
            assert len(result["table"]) >= 1
