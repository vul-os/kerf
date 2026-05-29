"""kerf-rules — Knowledge-based engineering code-compliance rule engine for Kerf.

Provides a declarative DSL for engineering standards (AISC, Eurocode 2, ASME B18,
ACI, ISO, etc.) and an evaluation engine that produces structured violation reports
citing rule IDs and standard clauses.

Also provides the KBE (Knowledge-Based Engineering) parametric-design engine:
  KBERule, KBEEngine, KBELibrary, KBEState, InferenceResult, apply_rules.
"""

from kerf_rules.dsl import Rule, RulePack, load_rule_file, load_rule_pack
from kerf_rules.engine import RulesEngine, Violation, evaluate
from kerf_rules.kbe import (
    KBERule,
    KBEEngine,
    KBELibrary,
    KBEState,
    InferenceResult,
    apply_rules,
)

__all__ = [
    # Compliance engine
    "Rule",
    "RulePack",
    "load_rule_file",
    "load_rule_pack",
    "RulesEngine",
    "Violation",
    "evaluate",
    # KBE parametric-design engine
    "KBERule",
    "KBEEngine",
    "KBELibrary",
    "KBEState",
    "InferenceResult",
    "apply_rules",
]
