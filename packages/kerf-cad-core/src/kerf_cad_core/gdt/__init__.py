"""
kerf_cad_core.gdt — GD&T (Geometric Dimensioning and Tolerancing) framework.

ASME Y14.5 / ISO 1101 datum + tolerance data model, validation, and callout
report tools.  Pure-Python; no OCC dependency.

Submodules:
  datums                    — Datum, DatumReferenceFrame dataclasses
  tolerances                — GeometricTolerance + ToleranceSymbol enum
  modifiers                 — ToleranceModifier enum (MMC, LMC, RFS, PROJECTED, TANGENT)
  report                    — gdt_callout_report() formatted-text builder
  tools                     — LLM tool wrappers registered with the tool registry
  composite_tolerance_check — Composite frame validator (ASME Y14.5-2018 §10.5.2 / §11.6)
  datum_shift_check         — Datum shift (bonus tolerance) for MMC/LMC datum features
                              (ASME Y14.5-2018 §4.5 + §7.3.5)
  feature_of_size_dof       — Feature of Size DOF enumerator (ASME Y14.5-2018 §4.7 + §7.3)
  runout_check              — Circular / total runout compliance check
                              (ASME Y14.5-2018 §13 / ISO 1101 §18)
"""
from __future__ import annotations

from kerf_cad_core.gdt.datums import Datum, DatumReferenceFrame
from kerf_cad_core.gdt.tolerances import GeometricTolerance, ToleranceSymbol
from kerf_cad_core.gdt.modifiers import ToleranceModifier
from kerf_cad_core.gdt.composite_tolerance_check import (
    CompositeTolSegment,
    CompositeFrameSpec,
    CompositeFrameValidationReport,
    validate_composite_frame,
)
from kerf_cad_core.gdt.datum_shift_check import (
    DatumFeatureSpec,
    DatumShiftReport,
    compute_datum_shift,
)
from kerf_cad_core.gdt.feature_of_size_dof import (
    FOSSpec,
    FOSDoFReport,
    compute_fos_dof,
)
from kerf_cad_core.gdt.runout_check import (
    InspectionPoint,
    RunoutCheckSpec,
    RunoutCheckReport,
    check_runout,
)

__all__ = [
    "Datum",
    "DatumReferenceFrame",
    "GeometricTolerance",
    "ToleranceSymbol",
    "ToleranceModifier",
    "CompositeTolSegment",
    "CompositeFrameSpec",
    "CompositeFrameValidationReport",
    "validate_composite_frame",
    "DatumFeatureSpec",
    "DatumShiftReport",
    "compute_datum_shift",
    "FOSSpec",
    "FOSDoFReport",
    "compute_fos_dof",
    "InspectionPoint",
    "RunoutCheckSpec",
    "RunoutCheckReport",
    "check_runout",
]
