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
    from kerf_plm.bom_cost_rollup import (
        BomNode, RollupReport, rollup_bom_cost,
    )
    from kerf_plm.component_whereused import (
        BomRelationship, WhereUsedEntry, WhereUsedReport,
        find_component_whereused,
    )
    from kerf_plm.maturity_check import (
        ComponentMaturity, MaturityReport, assess_bom_maturity,
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
from kerf_plm.bom_cost_rollup import (
    BomNode,
    RollupReport,
    rollup_bom_cost,
)
from kerf_plm.component_whereused import (
    BomRelationship,
    WhereUsedEntry,
    WhereUsedReport,
    find_component_whereused,
)
from kerf_plm.ecn_impact_analysis import (
    EcnInput,
    EcnImpactReport,
    analyze_ecn_impact,
)
from kerf_plm.maturity_check import (
    ComponentMaturity,
    MaturityReport,
    assess_bom_maturity,
)
from kerf_plm.change_log_export import (
    EcnLogEntry,
    ChangeLogExportResult,
    export_change_log,
)
from kerf_plm.part_obsolescence_check import (
    PartLifecycleStatus,
    PartLifecycleEntry,
    ObsolescenceReport,
    check_part_obsolescence,
)
from kerf_plm.variant_config import (
    VariantRule,
    VariantSelection,
    VariantResolvedBomEntry,
    VariantConfigReport,
    resolve_variant_bom,
)
from kerf_plm.bom_compare_diff import (
    BomLineItem,
    BomDiffEntry,
    BomDiffReport,
    compare_boms,
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
    "BomNode",
    "RollupReport",
    "rollup_bom_cost",
    "BomRelationship",
    "WhereUsedEntry",
    "WhereUsedReport",
    "find_component_whereused",
    "EcnInput",
    "EcnImpactReport",
    "analyze_ecn_impact",
    "ComponentMaturity",
    "MaturityReport",
    "assess_bom_maturity",
    "EcnLogEntry",
    "ChangeLogExportResult",
    "export_change_log",
    "PartLifecycleStatus",
    "PartLifecycleEntry",
    "ObsolescenceReport",
    "check_part_obsolescence",
    "VariantRule",
    "VariantSelection",
    "VariantResolvedBomEntry",
    "VariantConfigReport",
    "resolve_variant_bom",
    "BomLineItem",
    "BomDiffEntry",
    "BomDiffReport",
    "compare_boms",
]
