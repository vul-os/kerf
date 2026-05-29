"""
kerf-plm — PLM configurator + effectivity BOM.

Public API:
    from kerf_plm.configurator import (
        Rule, Action, Part, Configurator, ConfigResult, ConfigConflict,
        effectivity_bom,
    )
"""

from kerf_plm.configurator import (
    Rule,
    Action,
    ActionKind,
    Part,
    Configurator,
    ConfigResult,
    ConfigConflict,
    ConstraintViolation,
    effectivity_bom,
)

__all__ = [
    "Rule",
    "Action",
    "ActionKind",
    "Part",
    "Configurator",
    "ConfigResult",
    "ConfigConflict",
    "ConstraintViolation",
    "effectivity_bom",
]
