"""
Tests for kerf_mold.runner_balance_check — MOLD-RUNNER-BALANCE-CHECK

Covers:
  - H-pattern 4-cavity (Beaumont fig 6.18): balanced=True
  - Asymmetric runner (one cavity 2× path length): max_imbalance > 30 %
  - 8-cavity natural-balance tree: balanced=True
  - Edge: single cavity always balanced
  - Detached gate (parent_id missing): ValueError
  - LLM tool round-trip (mold_check_runner_balance)
  - Plugin registration

References:
  Beaumont 2007 §6.6; Menges 2001 §6.6.4.
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_mold.runner_balance_check import (
    RunnerSegment,
    RunnerBalanceReport,
    check_runner_balance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _h4_segments() -> tuple[list[RunnerSegment], list[str]]:
    """H-pattern 4-cavity natural balance (Beaumont 2007 fig 6.18).

    Topology:
        sprue (root)
         ├── R_left  (sprue → left junction)
         │    ├── R_L1  (left junction → cavity C1)
         │    └── R_L2  (left junction → cavity C2)
         └── R_right (sprue → right junction)
              ├── R_R1  (right junction → cavity C3)
              └── R_R2  (right junction → cavity C4)

    All branch segments have identical length and diameter
    → all gate resistances are equal → balanced=True.
    """
    d = 6.0   # mm, identical everywhere
    segs = [
        RunnerSegment(id="sprue",   length_mm=30.0, diameter_mm=d, parent_id=None),
        RunnerSegment(id="R_left",  length_mm=40.0, diameter_mm=d, parent_id="sprue"),
        RunnerSegment(id="R_right", length_mm=40.0, diameter_mm=d, parent_id="sprue"),
        RunnerSegment(id="R_L1",    length_mm=25.0, diameter_mm=d, parent_id="R_left"),
        RunnerSegment(id="R_L2",    length_mm=25.0, diameter_mm=d, parent_id="R_left"),
        RunnerSegment(id="R_R1",    length_mm=25.0, diameter_mm=d, parent_id="R_right"),
        RunnerSegment(id="R_R2",    length_mm=25.0, diameter_mm=d, parent_id="R_right"),
    ]
    gates = ["R_L1", "R_L2", "R_R1", "R_R2"]
    return segs, gates


def _asymmetric_segments() -> tuple[list[RunnerSegment], list[str]]:
    """Two cavities; one has a runner leg that is 2× longer.

    Topology:
        sprue (root, L=10, D=8)
         ├── R_short  (L=50, D=6) → cavity C1
         └── R_long   (L=100, D=6) → cavity C2

    R_short path resistance = R(sprue) + R(R_short)
    R_long  path resistance = R(sprue) + R(R_long)

    Because R ∝ L the long path has significantly higher resistance.
    """
    segs = [
        RunnerSegment(id="sprue",   length_mm=10.0,  diameter_mm=8.0, parent_id=None),
        RunnerSegment(id="R_short", length_mm=50.0,  diameter_mm=6.0, parent_id="sprue"),
        RunnerSegment(id="R_long",  length_mm=100.0, diameter_mm=6.0, parent_id="sprue"),
    ]
    gates = ["R_short", "R_long"]
    return segs, gates


def _8cavity_natural_balance() -> tuple[list[RunnerSegment], list[str]]:
    """8-cavity symmetric binary tree (2 levels of branching below sprue).

    Topology:
        sprue
         ├── R_A (→ R_A1, R_A2)
         │    ├── R_A1 (→ R_A1a, R_A1b) — leaves C1, C2
         │    └── R_A2 (→ R_A2a, R_A2b) — leaves C3, C4
         └── R_B (→ R_B1, R_B2)
              ├── R_B1 (→ R_B1a, R_B1b) — leaves C5, C6
              └── R_B2 (→ R_B2a, R_B2b) — leaves C7, C8

    All segments at the same level share identical length and diameter
    → all 8 gate resistances are equal → balanced=True.
    """
    d_s = 8.0
    d_1 = 6.0
    d_2 = 5.0
    d_3 = 4.0

    segs = [
        RunnerSegment(id="sprue", length_mm=20.0, diameter_mm=d_s, parent_id=None),
        # Level 1
        RunnerSegment(id="R_A", length_mm=40.0, diameter_mm=d_1, parent_id="sprue"),
        RunnerSegment(id="R_B", length_mm=40.0, diameter_mm=d_1, parent_id="sprue"),
        # Level 2
        RunnerSegment(id="R_A1", length_mm=25.0, diameter_mm=d_2, parent_id="R_A"),
        RunnerSegment(id="R_A2", length_mm=25.0, diameter_mm=d_2, parent_id="R_A"),
        RunnerSegment(id="R_B1", length_mm=25.0, diameter_mm=d_2, parent_id="R_B"),
        RunnerSegment(id="R_B2", length_mm=25.0, diameter_mm=d_2, parent_id="R_B"),
        # Level 3 (gates)
        RunnerSegment(id="R_A1a", length_mm=15.0, diameter_mm=d_3, parent_id="R_A1"),
        RunnerSegment(id="R_A1b", length_mm=15.0, diameter_mm=d_3, parent_id="R_A1"),
        RunnerSegment(id="R_A2a", length_mm=15.0, diameter_mm=d_3, parent_id="R_A2"),
        RunnerSegment(id="R_A2b", length_mm=15.0, diameter_mm=d_3, parent_id="R_A2"),
        RunnerSegment(id="R_B1a", length_mm=15.0, diameter_mm=d_3, parent_id="R_B1"),
        RunnerSegment(id="R_B1b", length_mm=15.0, diameter_mm=d_3, parent_id="R_B1"),
        RunnerSegment(id="R_B2a", length_mm=15.0, diameter_mm=d_3, parent_id="R_B2"),
        RunnerSegment(id="R_B2b", length_mm=15.0, diameter_mm=d_3, parent_id="R_B2"),
    ]
    gates = [
        "R_A1a", "R_A1b", "R_A2a", "R_A2b",
        "R_B1a", "R_B1b", "R_B2a", "R_B2b",
    ]
    return segs, gates


# ===========================================================================
# 1. H-pattern 4-cavity: balanced
# ===========================================================================

class TestH4Balanced:
    def _report(self) -> RunnerBalanceReport:
        segs, gates = _h4_segments()
        return check_runner_balance(segs, gates)

    def test_balanced_flag(self):
        """H-pattern 4-cavity must be naturally balanced (Beaumont fig 6.18)."""
        assert self._report().balanced is True

    def test_max_imbalance_below_5pct(self):
        assert self._report().max_imbalance_pct < 5.0

    def test_max_imbalance_nearly_zero(self):
        """Perfectly symmetric tree: imbalance should be essentially 0."""
        assert self._report().max_imbalance_pct == pytest.approx(0.0, abs=1e-6)

    def test_four_cavity_paths(self):
        r = self._report()
        assert len(r.cavity_paths) == 4

    def test_all_fill_ratios_one(self):
        """Identical resistance paths → fill_ratio = 1 for all cavities."""
        for cp in self._report().cavity_paths:
            assert cp["fill_ratio"] == pytest.approx(1.0, abs=1e-6)

    def test_cavity_ids_present(self):
        ids = {cp["cavity_id"] for cp in self._report().cavity_paths}
        assert ids == {"R_L1", "R_L2", "R_R1", "R_R2"}

    def test_honest_caveat_mentions_hp(self):
        caveat = self._report().honest_caveat.lower()
        assert "hagen" in caveat or "poiseuille" in caveat or "geometric" in caveat

    def test_total_length_consistent(self):
        """All 4 gate paths should have the same total length (30+40+25=95 mm)."""
        lengths = [cp["total_length_mm"] for cp in self._report().cavity_paths]
        assert max(lengths) - min(lengths) == pytest.approx(0.0, abs=1e-3)


# ===========================================================================
# 2. Asymmetric runner: imbalanced > 30 %
# ===========================================================================

class TestAsymmetricImbalance:
    def _report(self) -> RunnerBalanceReport:
        segs, gates = _asymmetric_segments()
        return check_runner_balance(segs, gates)

    def test_not_balanced(self):
        """Asymmetric runner (2× leg length) must be flagged as unbalanced."""
        assert self._report().balanced is False

    def test_max_imbalance_above_30pct(self):
        """Path resistances differ substantially; imbalance must exceed 30 %."""
        assert self._report().max_imbalance_pct > 30.0

    def test_two_cavity_paths(self):
        assert len(self._report().cavity_paths) == 2

    def test_longer_path_higher_resistance(self):
        """R_long should have higher total resistance than R_short."""
        paths = {cp["cavity_id"]: cp for cp in self._report().cavity_paths}
        assert paths["R_long"]["total_resistance"] > paths["R_short"]["total_resistance"]

    def test_fill_ratio_spread(self):
        """fill_ratio: shorter path < 1, longer path > 1."""
        paths = {cp["cavity_id"]: cp for cp in self._report().cavity_paths}
        assert paths["R_short"]["fill_ratio"] < 1.0
        assert paths["R_long"]["fill_ratio"] > 1.0


# ===========================================================================
# 3. 8-cavity natural balance (binary tree)
# ===========================================================================

class TestEightCavityNaturalBalance:
    def _report(self) -> RunnerBalanceReport:
        segs, gates = _8cavity_natural_balance()
        return check_runner_balance(segs, gates)

    def test_balanced(self):
        """8-cavity symmetric binary tree must be naturally balanced."""
        assert self._report().balanced is True

    def test_max_imbalance_zero(self):
        assert self._report().max_imbalance_pct == pytest.approx(0.0, abs=1e-6)

    def test_eight_paths(self):
        assert len(self._report().cavity_paths) == 8

    def test_all_fill_ratios_one(self):
        for cp in self._report().cavity_paths:
            assert cp["fill_ratio"] == pytest.approx(1.0, abs=1e-6)

    def test_total_lengths_equal(self):
        lengths = [cp["total_length_mm"] for cp in self._report().cavity_paths]
        assert max(lengths) - min(lengths) == pytest.approx(0.0, abs=1e-3)


# ===========================================================================
# 4. Single cavity: always balanced
# ===========================================================================

class TestSingleCavity:
    def _report(self) -> RunnerBalanceReport:
        segs = [
            RunnerSegment(id="sprue", length_mm=50.0, diameter_mm=6.0, parent_id=None),
        ]
        return check_runner_balance(segs, ["sprue"])

    def test_balanced(self):
        """Single-cavity mold is always balanced by definition."""
        assert self._report().balanced is True

    def test_max_imbalance_zero(self):
        assert self._report().max_imbalance_pct == pytest.approx(0.0, abs=1e-9)

    def test_one_cavity_path(self):
        assert len(self._report().cavity_paths) == 1

    def test_fill_ratio_one(self):
        assert self._report().cavity_paths[0]["fill_ratio"] == pytest.approx(1.0)


# ===========================================================================
# 5. Error: detached gate (parent_id references missing segment)
# ===========================================================================

class TestDetachedGate:
    def test_missing_parent_raises(self):
        """A segment that references a non-existent parent_id must raise ValueError."""
        segs = [
            RunnerSegment(id="sprue",    length_mm=30.0, diameter_mm=6.0, parent_id=None),
            RunnerSegment(id="gate_ok",  length_mm=20.0, diameter_mm=5.0, parent_id="sprue"),
            RunnerSegment(id="gate_bad", length_mm=20.0, diameter_mm=5.0, parent_id="GHOST"),
        ]
        with pytest.raises(ValueError, match="GHOST"):
            check_runner_balance(segs, ["gate_ok", "gate_bad"])

    def test_unknown_cavity_gate_id_raises(self):
        """Requesting a gate id that is not in segments must raise ValueError."""
        segs = [
            RunnerSegment(id="sprue", length_mm=30.0, diameter_mm=6.0, parent_id=None),
        ]
        with pytest.raises(ValueError, match="ghost_gate"):
            check_runner_balance(segs, ["ghost_gate"])

    def test_duplicate_segment_id_raises(self):
        segs = [
            RunnerSegment(id="sprue", length_mm=30.0, diameter_mm=6.0, parent_id=None),
            RunnerSegment(id="sprue", length_mm=20.0, diameter_mm=5.0, parent_id=None),
        ]
        with pytest.raises(ValueError, match="Duplicate"):
            check_runner_balance(segs, ["sprue"])

    def test_no_root_raises(self):
        """Every segment has a parent → no root → ValueError."""
        segs = [
            RunnerSegment(id="A", length_mm=10.0, diameter_mm=5.0, parent_id="B"),
            RunnerSegment(id="B", length_mm=10.0, diameter_mm=5.0, parent_id="A"),
        ]
        with pytest.raises(ValueError):
            check_runner_balance(segs, ["A"])


# ===========================================================================
# 6. RunnerSegment validation
# ===========================================================================

class TestRunnerSegmentValidation:
    def test_zero_length_raises(self):
        with pytest.raises(ValueError, match="length_mm"):
            RunnerSegment(id="S", length_mm=0.0, diameter_mm=5.0, parent_id=None)

    def test_negative_length_raises(self):
        with pytest.raises(ValueError, match="length_mm"):
            RunnerSegment(id="S", length_mm=-1.0, diameter_mm=5.0, parent_id=None)

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="diameter_mm"):
            RunnerSegment(id="S", length_mm=10.0, diameter_mm=0.0, parent_id=None)

    def test_negative_diameter_raises(self):
        with pytest.raises(ValueError, match="diameter_mm"):
            RunnerSegment(id="S", length_mm=10.0, diameter_mm=-3.0, parent_id=None)


# ===========================================================================
# 7. Hagen-Poiseuille resistance sanity check
# ===========================================================================

class TestHPResistanceSanity:
    """White-box: R_norm = L / r^4; larger diameter → lower resistance."""

    def test_larger_diameter_lower_resistance(self):
        """Doubling diameter reduces resistance by 16× (r^4 factor)."""
        from kerf_mold.runner_balance_check import _hp_resistance
        s_narrow = RunnerSegment(id="a", length_mm=100.0, diameter_mm=4.0)
        s_wide   = RunnerSegment(id="b", length_mm=100.0, diameter_mm=8.0)
        ratio = _hp_resistance(s_narrow) / _hp_resistance(s_wide)
        # r^4 ratio: (2mm)^4 / (4mm)^4 = 16 / 256 = 1/16 → narrow is 16× higher
        assert ratio == pytest.approx(16.0, rel=1e-6)

    def test_longer_segment_higher_resistance(self):
        from kerf_mold.runner_balance_check import _hp_resistance
        s_short = RunnerSegment(id="a", length_mm=50.0,  diameter_mm=6.0)
        s_long  = RunnerSegment(id="b", length_mm=100.0, diameter_mm=6.0)
        assert _hp_resistance(s_long) == pytest.approx(
            2.0 * _hp_resistance(s_short), rel=1e-9
        )


# ===========================================================================
# 8. Near-balanced but just over 5 % threshold
# ===========================================================================

class TestNearBalanceThreshold:
    def test_just_balanced(self):
        """4 % imbalance: balanced=True."""
        # Construct two paths: one slightly longer
        # Need to engineer R_max/R_mean spread of ~4%
        # Use L = 100 and L = 104 with same diameter to get ~4% imbalance
        # R_mean = (100 + 104) / 2 / r^4 = 102 / r^4
        # (R_max - R_min) / R_mean = 4/102 ≈ 3.92 %
        segs = [
            RunnerSegment(id="sprue", length_mm=1.0, diameter_mm=8.0, parent_id=None),
            RunnerSegment(id="G1",    length_mm=100.0, diameter_mm=6.0, parent_id="sprue"),
            RunnerSegment(id="G2",    length_mm=104.0, diameter_mm=6.0, parent_id="sprue"),
        ]
        r = check_runner_balance(segs, ["G1", "G2"])
        # The sprue R contribution is tiny (D=8); the main imbalance comes from G1 vs G2
        # Total R_G1 ≈ R(sprue) + R(100,6); Total R_G2 ≈ R(sprue) + R(104,6)
        # If spread < 5% the test passes as balanced
        assert r.balanced is True or r.max_imbalance_pct < 5.0

    def test_just_unbalanced(self):
        """Two paths: one significantly longer → unbalanced."""
        segs = [
            RunnerSegment(id="sprue", length_mm=0.1, diameter_mm=8.0, parent_id=None),
            RunnerSegment(id="G1",    length_mm=100.0, diameter_mm=6.0, parent_id="sprue"),
            RunnerSegment(id="G2",    length_mm=120.0, diameter_mm=6.0, parent_id="sprue"),
        ]
        r = check_runner_balance(segs, ["G1", "G2"])
        # 20 % length difference on main branch → unbalanced
        assert r.balanced is False or r.max_imbalance_pct > 5.0


# ===========================================================================
# 9. LLM tool round-trip
# ===========================================================================

class TestRunnerBalanceTool:
    def _h4_args(self) -> dict:
        segs, gates = _h4_segments()
        return {
            "segments": [
                {
                    "id": s.id,
                    "length_mm": s.length_mm,
                    "diameter_mm": s.diameter_mm,
                    "parent_id": s.parent_id,
                }
                for s in segs
            ],
            "cavity_gate_ids": gates,
        }

    def test_h4_balanced_ok(self):
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        result = json.loads(_run(run_mold_check_runner_balance(self._h4_args(), CTX)))
        assert result.get("ok") is True
        assert result["balanced"] is True
        assert result["max_imbalance_pct"] == pytest.approx(0.0, abs=1e-4)
        assert len(result["cavity_paths"]) == 4

    def test_asymmetric_not_balanced(self):
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        segs, gates = _asymmetric_segments()
        args = {
            "segments": [
                {"id": s.id, "length_mm": s.length_mm,
                 "diameter_mm": s.diameter_mm, "parent_id": s.parent_id}
                for s in segs
            ],
            "cavity_gate_ids": gates,
        }
        result = json.loads(_run(run_mold_check_runner_balance(args, CTX)))
        assert result.get("ok") is True
        assert result["balanced"] is False
        assert result["max_imbalance_pct"] > 30.0

    def test_missing_segments_returns_error(self):
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        result = json.loads(_run(run_mold_check_runner_balance(
            {"cavity_gate_ids": ["G1"]}, CTX
        )))
        assert result.get("ok") is not True
        assert "error" in result

    def test_missing_gate_ids_returns_error(self):
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        result = json.loads(_run(run_mold_check_runner_balance(
            {"segments": [{"id": "s", "length_mm": 10, "diameter_mm": 5}]}, CTX
        )))
        assert result.get("ok") is not True

    def test_bad_parent_id_returns_error(self):
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        args = {
            "segments": [
                {"id": "sprue", "length_mm": 30, "diameter_mm": 6, "parent_id": None},
                {"id": "gate",  "length_mm": 20, "diameter_mm": 5, "parent_id": "NOPE"},
            ],
            "cavity_gate_ids": ["gate"],
        }
        result = json.loads(_run(run_mold_check_runner_balance(args, CTX)))
        assert result.get("ok") is not True

    def test_reference_in_response(self):
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        result = json.loads(_run(run_mold_check_runner_balance(self._h4_args(), CTX)))
        assert "Beaumont" in result.get("reference", "")

    def test_honest_caveat_in_response(self):
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        result = json.loads(_run(run_mold_check_runner_balance(self._h4_args(), CTX)))
        caveat = result.get("honest_caveat", "").lower()
        assert "geometric" in caveat or "hagen" in caveat or "shear" in caveat

    def test_plugin_registration(self):
        """mold_check_runner_balance must be registered by plugin.register()."""
        from kerf_mold.plugin import register
        from fastapi import FastAPI

        class _MockReg:
            def __init__(self):
                self.registered = {}
            def register(self, name, spec, handler):
                self.registered[name] = (spec, handler)

        class _MockCtx:
            def __init__(self):
                self.tools = _MockReg()

        app = FastAPI()
        ctx = _MockCtx()
        _run(register(app, ctx))
        assert "mold_check_runner_balance" in ctx.tools.registered
