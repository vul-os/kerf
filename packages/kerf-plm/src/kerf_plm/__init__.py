"""
kerf-plm — PLM configurator + effectivity BOM + ECR/ECO change management.

Public API:
    from kerf_plm.configurator import (
        Rule, Action, Part, Configurator, ConfigResult, ConfigConflict,
        effectivity_bom,
    )
    from kerf_plm.change_management import (
        ECR, ECO, ChangeBoard, AuditEntry,
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
from kerf_plm.change_management import (
    ECR,
    ECO,
    ChangeBoard,
    AuditEntry,
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
    "ECR",
    "ECO",
    "ChangeBoard",
    "AuditEntry",
]
