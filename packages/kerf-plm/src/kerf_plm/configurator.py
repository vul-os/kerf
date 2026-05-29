"""
kerf_plm.configurator — rule-based product configurator (PLM-A).

This module implements a variant-configuration engine suitable for:
  - 150% BOM management (superset BOM filtered down to an exact BOM)
  - Option-driven part inclusion / exclusion
  - Parameter overrides per selection
  - Effectivity-date filtering for as-of BOM snapshots

Design follows Configurator OWL / feature-model conventions:
  - A *selection* is a {feature: value} dict (e.g. {"engine": "V8", "colour": "red"}).
  - A *Rule* binds a guard predicate to a list of *Actions*.
  - Actions are evaluated in a fixed-point loop until the parts-set + params stabilise.
  - Conflicting hard constraints (two rules forcing include AND exclude on the same
    part_id in the same pass) raise ConfigConflict immediately.

References:
  - Soininen et al. (1998) "Configurator Knowledge Representation and Reasoning"
  - Junker (2006) "Preference-based Configuration" — priority ordering
  - CIMdata PLM glossary — "150% BOM", "effectivity"
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, auto
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Enumerations and data types
# ---------------------------------------------------------------------------

class ActionKind(Enum):
    INCLUDE_PART = auto()
    EXCLUDE_PART = auto()
    SET_PARAM = auto()
    RAISE_CONSTRAINT = auto()


@dataclass(frozen=True)
class Action:
    """A single effect applied when a rule fires.

    Attributes:
        kind:     The type of effect.
        part_id:  Target part identifier (for INCLUDE_PART / EXCLUDE_PART).
        param:    Parameter name (for SET_PARAM).
        value:    Parameter value (for SET_PARAM) or constraint message
                  (for RAISE_CONSTRAINT).
    """
    kind: ActionKind
    part_id: str | None = None
    param: str | None = None
    value: Any = None


def include_part(part_id: str) -> Action:
    """Convenience constructor — include a part by ID."""
    return Action(kind=ActionKind.INCLUDE_PART, part_id=part_id)


def exclude_part(part_id: str) -> Action:
    """Convenience constructor — exclude a part by ID."""
    return Action(kind=ActionKind.EXCLUDE_PART, part_id=part_id)


def set_param(param: str, value: Any) -> Action:
    """Convenience constructor — set a configuration parameter."""
    return Action(kind=ActionKind.SET_PARAM, param=param, value=value)


def raise_constraint_violation(message: str) -> Action:
    """Convenience constructor — fire a hard constraint violation."""
    return Action(kind=ActionKind.RAISE_CONSTRAINT, value=message)


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    """A configurator rule: guard predicate → list of actions.

    Attributes:
        condition:  Callable[[dict], bool] — receives the current selection
                    and returns True when the rule should fire.
        effect:     List of Actions to apply when the rule fires.
        priority:   Lower number = higher priority (evaluated first).
                    Rules with equal priority are evaluated in insertion order.
        name:       Optional human-readable label (used in error messages).
    """
    condition: Callable[[dict], bool]
    effect: list[Action]
    priority: int = 100
    name: str = ""

    def fires(self, selection: dict) -> bool:
        """Return True if this rule's condition is satisfied."""
        try:
            return bool(self.condition(selection))
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Part
# ---------------------------------------------------------------------------

@dataclass
class Part:
    """A part record in the 150% BOM.

    Attributes:
        part_id:        Unique identifier (e.g. "ENG-V8-001").
        description:    Human-readable description.
        quantity:       Default quantity (may be overridden by SET_PARAM).
        effective_from: Date from which this part is effective (inclusive).
                        None means "always effective from the beginning".
        effective_to:   Date until which this part is effective (exclusive).
                        None means "effective indefinitely".
        metadata:       Arbitrary extra fields (e.g. cost, weight, supplier).
    """
    part_id: str
    description: str = ""
    quantity: float = 1.0
    effective_from: date | None = None
    effective_to: date | None = None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConstraintViolation(ValueError):
    """Raised when a RAISE_CONSTRAINT action fires during configuration."""
    def __init__(self, message: str, rule_name: str = ""):
        self.rule_name = rule_name
        super().__init__(f"Constraint violation [{rule_name}]: {message}" if rule_name else message)


class ConfigConflict(ValueError):
    """Raised when two rules produce contradictory hard effects on the same part.

    Example: rule A says include_part("P-001") and rule B says
    exclude_part("P-001") and both fire in the same fixed-point pass.
    """
    def __init__(self, part_id: str, include_rules: list[str], exclude_rules: list[str]):
        self.part_id = part_id
        self.include_rules = include_rules
        self.exclude_rules = exclude_rules
        super().__init__(
            f"Configurator conflict on part '{part_id}': "
            f"included by [{', '.join(include_rules) or '(unnamed)'}] "
            f"but excluded by [{', '.join(exclude_rules) or '(unnamed)'}]"
        )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ConfigResult:
    """Output of a successful configuration run.

    Attributes:
        parts:   List of part_ids included in this configuration.
        params:  Dict of parameter overrides set by SET_PARAM rules.
        errors:  Non-fatal messages accumulated during evaluation.
        iterations: Number of fixed-point iterations needed to converge.
    """
    parts: list[str]
    params: dict[str, Any]
    errors: list[str]
    iterations: int = 0


# ---------------------------------------------------------------------------
# Configurator
# ---------------------------------------------------------------------------

class Configurator:
    """Rule-based product configurator.

    Usage::

        rules = [
            Rule(
                condition=lambda s: s.get("engine") == "V8",
                effect=[include_part("ENG-V8-001"), set_param("hp", 450)],
                priority=10,
                name="V8 engine rule",
            ),
            Rule(
                condition=lambda s: s["engine"] == "V8" and s["transmission"] == "manual",
                effect=[raise_constraint_violation("V8 not available with manual gearbox")],
                priority=1,
                name="V8/manual forbidden",
            ),
        ]
        options = {
            "colour": ["red", "blue", "black"],
            "engine": ["V6", "V8"],
            "transmission": ["auto", "manual"],
        }
        cfg = Configurator(rules=rules, options=options)
        result = cfg.configure({"colour": "red", "engine": "V8", "transmission": "auto"})

    Args:
        rules:   List of Rule objects that define the configuration logic.
        options: Dict mapping each feature key to its allowed values.
                 Used for input validation — selections with unknown values
                 are rejected.
    """

    def __init__(self, rules: list[Rule], options: dict[str, list[str]]) -> None:
        self._rules = sorted(rules, key=lambda r: r.priority)
        self._options = options

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def configure(self, selection: dict) -> ConfigResult:
        """Evaluate the rule set for *selection* and return a ConfigResult.

        Algorithm
        ---------
        1. Validate that all keys in *selection* are known option features and
           that their values are in the declared option space.
        2. Sort rules by priority (ascending = higher priority first).
        3. Run a fixed-point loop:
           a. Collect all rules whose condition fires.
           b. Detect RAISE_CONSTRAINT actions first (hard stops).
           c. Compute include/exclude sets; detect conflicts.
           d. Apply SET_PARAM actions.
           e. Check whether the parts-set or params changed vs previous pass.
              If stable → done.  If not → repeat up to len(rules)+1 times.
        4. Return ConfigResult with final parts list, params, and any
           non-fatal error strings.

        Raises:
            ValueError:         If *selection* contains unknown features/values.
            ConstraintViolation: If any RAISE_CONSTRAINT action fires.
            ConfigConflict:     If two rules produce contradictory include/exclude
                                on the same part in the same pass.
        """
        self._validate_selection(selection)

        parts: set[str] = set()
        params: dict[str, Any] = {}
        errors: list[str] = []
        max_iters = len(self._rules) + 1

        for iteration in range(1, max_iters + 1):
            prev_parts = frozenset(parts)
            prev_params = copy.copy(params)

            # Collect firing rules
            firing = [r for r in self._rules if r.fires(selection)]

            # Step 1: evaluate RAISE_CONSTRAINT actions first (hard stop)
            for rule in firing:
                for action in rule.effect:
                    if action.kind == ActionKind.RAISE_CONSTRAINT:
                        raise ConstraintViolation(
                            str(action.value), rule_name=rule.name
                        )

            # Step 2: collect include/exclude intents, detect conflicts
            include_map: dict[str, list[str]] = {}   # part_id → [rule names]
            exclude_map: dict[str, list[str]] = {}

            for rule in firing:
                for action in rule.effect:
                    if action.kind == ActionKind.INCLUDE_PART and action.part_id:
                        include_map.setdefault(action.part_id, []).append(rule.name or "(unnamed)")
                    elif action.kind == ActionKind.EXCLUDE_PART and action.part_id:
                        exclude_map.setdefault(action.part_id, []).append(rule.name or "(unnamed)")

            # Conflict detection: same part in both sets
            conflicts = set(include_map.keys()) & set(exclude_map.keys())
            if conflicts:
                pid = sorted(conflicts)[0]
                raise ConfigConflict(
                    part_id=pid,
                    include_rules=include_map[pid],
                    exclude_rules=exclude_map[pid],
                )

            # Apply includes and excludes
            for pid in include_map:
                parts.add(pid)
            for pid in exclude_map:
                parts.discard(pid)

            # Step 3: SET_PARAM actions
            for rule in firing:
                for action in rule.effect:
                    if action.kind == ActionKind.SET_PARAM and action.param is not None:
                        params[action.param] = action.value

            # Fixed-point check
            if frozenset(parts) == prev_parts and params == prev_params:
                return ConfigResult(
                    parts=sorted(parts),
                    params=params,
                    errors=errors,
                    iterations=iteration,
                )

        # Reached max iterations without convergence — return best effort
        errors.append(
            f"Fixed-point did not converge in {max_iters} iterations; "
            "result may be incomplete."
        )
        return ConfigResult(
            parts=sorted(parts),
            params=params,
            errors=errors,
            iterations=max_iters,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_selection(self, selection: dict) -> None:
        for key, val in selection.items():
            if key not in self._options:
                raise ValueError(
                    f"Unknown feature '{key}'. Known features: {list(self._options.keys())}"
                )
            allowed = self._options[key]
            if val not in allowed:
                raise ValueError(
                    f"Value '{val}' not in allowed values for '{key}': {allowed}"
                )


# ---------------------------------------------------------------------------
# 150% / effectivity BOM helper
# ---------------------------------------------------------------------------

def effectivity_bom(parts: list[Part], effective_date: date) -> list[Part]:
    """Filter a 150% BOM to the parts effective on *effective_date*.

    A part is included if:
      - Its ``effective_from`` is None or <= effective_date, AND
      - Its ``effective_to`` is None or > effective_date.

    The ">" on effective_to follows the standard PLM half-open interval
    convention: [effective_from, effective_to).

    Args:
        parts:          Full 150% BOM (all possible parts).
        effective_date: The as-of date for which to compute the exact BOM.

    Returns:
        List of Part objects that are effective on *effective_date*.
    """
    result = []
    for part in parts:
        from_ok = part.effective_from is None or part.effective_from <= effective_date
        to_ok = part.effective_to is None or part.effective_to > effective_date
        if from_ok and to_ok:
            result.append(part)
    return result
