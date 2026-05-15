"""
kerf_cad_core.gdt — GD&T (Geometric Dimensioning and Tolerancing) framework.

ASME Y14.5 / ISO 1101 datum + tolerance data model, validation, and callout
report tools.  Pure-Python; no OCC dependency.

Submodules:
  datums       — Datum, DatumReferenceFrame dataclasses
  tolerances   — GeometricTolerance + ToleranceSymbol enum
  modifiers    — ToleranceModifier enum (MMC, LMC, RFS, PROJECTED, TANGENT)
  report       — gdt_callout_report() formatted-text builder
  tools        — LLM tool wrappers registered with the tool registry
"""
from __future__ import annotations

from kerf_cad_core.gdt.datums import Datum, DatumReferenceFrame
from kerf_cad_core.gdt.tolerances import GeometricTolerance, ToleranceSymbol
from kerf_cad_core.gdt.modifiers import ToleranceModifier

__all__ = [
    "Datum",
    "DatumReferenceFrame",
    "GeometricTolerance",
    "ToleranceSymbol",
    "ToleranceModifier",
]
