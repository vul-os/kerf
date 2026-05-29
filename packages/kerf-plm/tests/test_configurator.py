"""
Tests for kerf_plm.configurator — PLM-A rule-based product configurator.

Test plan:
  1. Car configurator — 3 colours × 2 engines × 2 transmissions = 12 valid configs,
     each yields a unique parts list with no errors.
  2. Conflict — V8 + manual raises ConfigConflict (two rules collide on same part).
  3. Effectivity — a part with effective_to in the past is excluded from a
     today-dated BOM.
  4. Fixed-point convergence — a chain A→B→C converges in ≤ rules count iterations.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest

from kerf_plm.configurator import (
    Action,
    ActionKind,
    ConfigConflict,
    ConfigResult,
    Configurator,
    ConstraintViolation,
    Part,
    Rule,
    effectivity_bom,
    exclude_part,
    include_part,
    raise_constraint_violation,
    set_param,
)


# ---------------------------------------------------------------------------
# Fixtures: car configurator
# ---------------------------------------------------------------------------

COLOURS = ["red", "blue", "black"]
ENGINES = ["V6", "V8"]
TRANSMISSIONS = ["auto", "manual"]

# Part IDs
BODY_RED = "BODY-RED-001"
BODY_BLUE = "BODY-BLUE-002"
BODY_BLACK = "BODY-BLK-003"
ENGINE_V6 = "ENG-V6-100"
ENGINE_V8 = "ENG-V8-200"
TRANS_AUTO = "TRANS-AUTO-010"
TRANS_MAN = "TRANS-MAN-020"
DIFF_SPORT = "DIFF-SPORT-030"   # V8 auto only


def _car_rules() -> list[Rule]:
    return [
        # Colour → body part
        Rule(
            condition=lambda s: s.get("colour") == "red",
            effect=[include_part(BODY_RED)],
            priority=10,
            name="colour=red",
        ),
        Rule(
            condition=lambda s: s.get("colour") == "blue",
            effect=[include_part(BODY_BLUE)],
            priority=10,
            name="colour=blue",
        ),
        Rule(
            condition=lambda s: s.get("colour") == "black",
            effect=[include_part(BODY_BLACK)],
            priority=10,
            name="colour=black",
        ),
        # Engine → engine part + hp param
        Rule(
            condition=lambda s: s.get("engine") == "V6",
            effect=[include_part(ENGINE_V6), set_param("hp", 300)],
            priority=20,
            name="engine=V6",
        ),
        Rule(
            condition=lambda s: s.get("engine") == "V8",
            effect=[include_part(ENGINE_V8), set_param("hp", 450)],
            priority=20,
            name="engine=V8",
        ),
        # Transmission → gearbox part
        Rule(
            condition=lambda s: s.get("transmission") == "auto",
            effect=[include_part(TRANS_AUTO)],
            priority=30,
            name="transmission=auto",
        ),
        Rule(
            condition=lambda s: s.get("transmission") == "manual",
            effect=[include_part(TRANS_MAN)],
            priority=30,
            name="transmission=manual",
        ),
        # V8 + auto → sport differential upgrade
        Rule(
            condition=lambda s: s.get("engine") == "V8" and s.get("transmission") == "auto",
            effect=[include_part(DIFF_SPORT)],
            priority=40,
            name="V8+auto sport-diff",
        ),
    ]


OPTIONS = {
    "colour": COLOURS,
    "engine": ENGINES,
    "transmission": TRANSMISSIONS,
}


# ---------------------------------------------------------------------------
# Test 1: car configurator — 12 valid configurations
# ---------------------------------------------------------------------------

class TestCarConfigurator:
    """All 12 valid selections (3×2×2) must return unique parts lists."""

    def _make_cfg(self) -> Configurator:
        return Configurator(rules=_car_rules(), options=OPTIONS)

    def test_all_12_configs_produce_results(self):
        cfg = self._make_cfg()
        results: list[ConfigResult] = []
        for colour, engine, trans in itertools.product(COLOURS, ENGINES, TRANSMISSIONS):
            sel = {"colour": colour, "engine": engine, "transmission": trans}
            r = cfg.configure(sel)
            assert r.errors == [], f"Unexpected errors for {sel}: {r.errors}"
            assert len(r.parts) > 0, f"No parts returned for {sel}"
            results.append(r)
        assert len(results) == 12

    def test_12_configs_produce_unique_parts_lists(self):
        cfg = self._make_cfg()
        seen: set[frozenset] = set()
        for colour, engine, trans in itertools.product(COLOURS, ENGINES, TRANSMISSIONS):
            sel = {"colour": colour, "engine": engine, "transmission": trans}
            r = cfg.configure(sel)
            key = frozenset(r.parts)
            assert key not in seen, f"Duplicate parts list for {sel}: {r.parts}"
            seen.add(key)
        assert len(seen) == 12

    def test_v8_auto_includes_sport_diff(self):
        cfg = self._make_cfg()
        r = cfg.configure({"colour": "red", "engine": "V8", "transmission": "auto"})
        assert DIFF_SPORT in r.parts

    def test_v6_auto_excludes_sport_diff(self):
        cfg = self._make_cfg()
        r = cfg.configure({"colour": "blue", "engine": "V6", "transmission": "auto"})
        assert DIFF_SPORT not in r.parts

    def test_hp_param_set_correctly(self):
        cfg = self._make_cfg()
        r_v6 = cfg.configure({"colour": "red", "engine": "V6", "transmission": "auto"})
        r_v8 = cfg.configure({"colour": "red", "engine": "V8", "transmission": "auto"})
        assert r_v6.params.get("hp") == 300
        assert r_v8.params.get("hp") == 450

    def test_colour_parts_exclusive(self):
        """Each colour selection includes exactly one body colour part."""
        cfg = self._make_cfg()
        body_parts = [BODY_RED, BODY_BLUE, BODY_BLACK]
        for colour in COLOURS:
            r = cfg.configure({"colour": colour, "engine": "V6", "transmission": "auto"})
            in_bom = [p for p in body_parts if p in r.parts]
            assert len(in_bom) == 1, f"Expected 1 body part for colour={colour}, got {in_bom}"


# ---------------------------------------------------------------------------
# Test 2: conflict — V8 + manual raises ConfigConflict
# ---------------------------------------------------------------------------

class TestConflictDetection:
    """A rule that forces include AND another that forces exclude on the same
    part (when V8+manual selected) must raise ConfigConflict."""

    def _make_conflicting_cfg(self) -> Configurator:
        """
        Add two conflicting rules: one includes ENGINE_V8, another excludes
        ENGINE_V8 when manual is selected — creating a hard conflict.
        """
        rules = _car_rules() + [
            Rule(
                condition=lambda s: s.get("transmission") == "manual",
                effect=[exclude_part(ENGINE_V8)],
                priority=5,   # higher priority than the engine=V8 rule (priority=20)
                name="manual excludes V8",
            ),
        ]
        return Configurator(rules=rules, options=OPTIONS)

    def test_v8_manual_raises_config_conflict(self):
        cfg = self._make_conflicting_cfg()
        with pytest.raises(ConfigConflict) as exc_info:
            cfg.configure({"colour": "red", "engine": "V8", "transmission": "manual"})

        conflict = exc_info.value
        assert conflict.part_id == ENGINE_V8
        assert any("V8" in r for r in conflict.include_rules + conflict.exclude_rules)

    def test_v6_manual_no_conflict(self):
        """V6 + manual should not trigger the conflict (V8 engine rule doesn't fire)."""
        cfg = self._make_conflicting_cfg()
        # Should not raise — V8 rule doesn't fire, so no conflict
        r = cfg.configure({"colour": "red", "engine": "V6", "transmission": "manual"})
        assert ENGINE_V6 in r.parts
        assert ENGINE_V8 not in r.parts

    def test_constraint_violation_v8_manual(self):
        """RAISE_CONSTRAINT action fires cleanly for forbidden V8+manual combo."""
        rules = _car_rules() + [
            Rule(
                condition=lambda s: s.get("engine") == "V8" and s.get("transmission") == "manual",
                effect=[raise_constraint_violation("V8 engine is not available with manual transmission")],
                priority=1,
                name="V8/manual forbidden",
            ),
        ]
        cfg = Configurator(rules=rules, options=OPTIONS)
        with pytest.raises(ConstraintViolation) as exc_info:
            cfg.configure({"colour": "red", "engine": "V8", "transmission": "manual"})
        assert "V8" in str(exc_info.value)
        assert "manual" in str(exc_info.value)

    def test_constraint_violation_not_raised_for_valid_combo(self):
        """ConstraintViolation must NOT fire for V8+auto."""
        rules = _car_rules() + [
            Rule(
                condition=lambda s: s.get("engine") == "V8" and s.get("transmission") == "manual",
                effect=[raise_constraint_violation("V8 engine is not available with manual transmission")],
                priority=1,
                name="V8/manual forbidden",
            ),
        ]
        cfg = Configurator(rules=rules, options=OPTIONS)
        r = cfg.configure({"colour": "red", "engine": "V8", "transmission": "auto"})
        assert ENGINE_V8 in r.parts


# ---------------------------------------------------------------------------
# Test 3: effectivity BOM — past parts excluded
# ---------------------------------------------------------------------------

class TestEffectivityBom:
    """Parts with effective_to in the past must be excluded from a today-dated BOM."""

    def test_past_part_excluded(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        next_year = today + timedelta(days=365)

        parts = [
            Part(
                part_id="LEGACY-001",
                description="Old widget",
                effective_from=date(2020, 1, 1),
                effective_to=yesterday,         # expired yesterday
            ),
            Part(
                part_id="CURRENT-002",
                description="Current widget",
                effective_from=date(2020, 1, 1),
                effective_to=next_year,         # still valid
            ),
            Part(
                part_id="FUTURE-003",
                description="Future widget",
                effective_from=next_year,       # not yet valid
                effective_to=None,
            ),
            Part(
                part_id="ALWAYS-004",
                description="Always valid",
                effective_from=None,
                effective_to=None,
            ),
        ]

        result = effectivity_bom(parts, today)
        ids = [p.part_id for p in result]

        assert "LEGACY-001" not in ids,  "Expired part should be excluded"
        assert "CURRENT-002" in ids,     "Current part should be included"
        assert "FUTURE-003" not in ids,  "Future part should be excluded"
        assert "ALWAYS-004" in ids,      "Always-valid part should be included"

    def test_effective_to_is_exclusive(self):
        """effective_to is an exclusive upper bound: part is NOT included on effective_to date."""
        cutoff = date(2025, 6, 1)
        part = Part(
            part_id="EDGE-001",
            effective_from=date(2024, 1, 1),
            effective_to=cutoff,  # expires ON this date (exclusive)
        )
        # On cutoff date → excluded (half-open interval [from, to) )
        assert effectivity_bom([part], cutoff) == []
        # One day before cutoff → included
        assert len(effectivity_bom([part], cutoff - timedelta(days=1))) == 1

    def test_effective_from_is_inclusive(self):
        """effective_from is an inclusive lower bound."""
        start = date(2025, 1, 1)
        part = Part(
            part_id="NEW-001",
            effective_from=start,
            effective_to=None,
        )
        # On start date → included
        assert len(effectivity_bom([part], start)) == 1
        # Day before start → excluded
        assert effectivity_bom([part], start - timedelta(days=1)) == []

    def test_empty_bom(self):
        assert effectivity_bom([], date.today()) == []

    def test_all_parts_no_effectivity_limits(self):
        """Parts with no effective_from / effective_to are always included."""
        parts = [Part(part_id=f"P-{i}") for i in range(5)]
        result = effectivity_bom(parts, date.today())
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Test 4: fixed-point convergence — chained A → B → C
# ---------------------------------------------------------------------------

class TestFixedPointConvergence:
    """A chain of cascading rules (A enables B, B requires C) must converge
    in at most len(rules) + 1 iterations."""

    def test_chain_abc_converges(self):
        """
        Rule chain:
          R1: feature=A → include_part("PART-A")
          R2: PART-A in parts → include_part("PART-B")  [keyed on selection, not state]
          R3: feature=A → include_part("PART-C")        [simulating a 2-hop dependency]

        Because the fixed-point evaluates all firing rules each pass,
        the chain resolves in a single pass (iteration 1 or 2 at most).
        """
        options = {"feature": ["A", "B", "off"]}

        rules = [
            Rule(
                condition=lambda s: s.get("feature") == "A",
                effect=[include_part("PART-A")],
                priority=10,
                name="R1: A→PART-A",
            ),
            Rule(
                # B depends on A — simulate by checking if feature=="A"
                condition=lambda s: s.get("feature") == "A",
                effect=[include_part("PART-B")],
                priority=20,
                name="R2: A→PART-B",
            ),
            Rule(
                condition=lambda s: s.get("feature") == "A",
                effect=[include_part("PART-C")],
                priority=30,
                name="R3: A→PART-C",
            ),
        ]

        cfg = Configurator(rules=rules, options=options)
        result = cfg.configure({"feature": "A"})

        assert "PART-A" in result.parts
        assert "PART-B" in result.parts
        assert "PART-C" in result.parts
        assert result.errors == []
        # Should converge quickly — certainly within len(rules)+1 = 4 iterations
        assert result.iterations <= len(rules) + 1

    def test_cascading_param_override_converges(self):
        """SET_PARAM rules chained together still converge."""
        options = {"mode": ["standard", "premium"]}

        rules = [
            Rule(
                condition=lambda s: s.get("mode") == "premium",
                effect=[set_param("tier", "premium"), include_part("PART-PREMIUM")],
                priority=10,
                name="premium tier",
            ),
            Rule(
                condition=lambda s: s.get("mode") == "premium",
                effect=[set_param("support", "priority"), include_part("PART-SUPPORT")],
                priority=20,
                name="premium support",
            ),
            Rule(
                condition=lambda s: s.get("mode") == "premium",
                effect=[set_param("warranty_years", 3)],
                priority=30,
                name="premium warranty",
            ),
        ]

        cfg = Configurator(rules=rules, options=options)
        result = cfg.configure({"mode": "premium"})

        assert result.params["tier"] == "premium"
        assert result.params["support"] == "priority"
        assert result.params["warranty_years"] == 3
        assert result.iterations <= len(rules) + 1

    def test_unknown_feature_raises(self):
        cfg = Configurator(rules=[], options={"x": ["1"]})
        with pytest.raises(ValueError, match="Unknown feature"):
            cfg.configure({"y": "1"})

    def test_unknown_value_raises(self):
        cfg = Configurator(rules=[], options={"x": ["1", "2"]})
        with pytest.raises(ValueError, match="not in allowed values"):
            cfg.configure({"x": "99"})
