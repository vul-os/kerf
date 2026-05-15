"""
kerf_cad_core.family — Parametric family definition system.

A *family* is a named, reusable parametric component definition — analogous to
a Revit family or a FreeCAD parametric spreadsheet.  It consists of:

  * Named parameters — each with a type (number | string | bool), default
    value, optional min/max range, and an optional formula that computes the
    value from other parameters.
  * A type catalog — pre-defined parameter-value sets (e.g. "Door 900×2100",
    "Door 800×2100").
  * Instances — concrete overrides of a type's values.
  * A build-recipe template — a descriptor (plain dict) that references param
    names via ``{param_name}`` placeholders; resolved to a concrete recipe dict
    when a type/instance is instantiated.

Submodules
----------
  model   — FamilyDef, FamilyParam, FamilyType, FamilyInstance data model +
            pure logic (formula eval, resolution, validation)
  tools   — LLM tool wrappers registered with the Kerf tool registry

Author: imranparuk
"""
from __future__ import annotations

from kerf_cad_core.family.model import (
    FamilyDef,
    FamilyParam,
    FamilyType,
    FamilyInstance,
    family_define,
    family_add_type,
    family_instantiate,
    family_validate,
)

__all__ = [
    "FamilyDef",
    "FamilyParam",
    "FamilyType",
    "FamilyInstance",
    "family_define",
    "family_add_type",
    "family_instantiate",
    "family_validate",
]
