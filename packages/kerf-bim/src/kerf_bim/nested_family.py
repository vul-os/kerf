"""
kerf_bim.nested_family
=======================

Parametric Family Editor with nested sub-families and type catalogue.

Extends :mod:`kerf_bim.family_editor` (the simple FamilyDef/FamilyParameter
model) with two additional concepts:

1. **Nested sub-family** (``NestedFamily``) — a child family placed within a
   parent family, driven by the parent's parameters.  Equivalent to Revit's
   "nested family" feature where, e.g., a curtain-wall family contains a
   panel family and a frame profile family as nested components.

2. **Type catalogue** (``TypeCatalogueEntry`` / ``TypeCatalogue``) — a table
   of named type variants, each specifying a set of parameter overrides.
   Equivalent to Revit's type catalogue (.txt) and ArchiCAD's Object Subtypes.

References
----------
Revit Family Guide (2024) — Nested and Shared Families.
Revit Type Catalogue format documentation.
IFC4 ADD2 TC1 — IfcTypeObject, IfcTypeProduct for type-level BIM objects.

Public API
----------
  NestedFamily(sub_family_id, placement_params, count)
      A sub-family nested inside a parent, driven by parent parameters.

  NestedFamilyDef(parent, nested_families)
      A FamilyDef augmented with nested sub-family references.

  TypeCatalogueEntry(type_id, name, param_overrides)
      One row in the type catalogue.

  TypeCatalogue(family_name, entries)
      Ordered collection of type entries for a family.

  instantiate_nested(family_def, parameter_values, type_id) -> dict
      Evaluate the parent + all nested sub-families.

  validate_nested(family_def) -> list[str]
      Validate parent family + nested references.

  build_type_catalogue(family_def, entries) -> TypeCatalogue
      Construct a validated type catalogue from raw rows.

  render_catalogue_table(catalogue) -> list[dict]
      Produce a list-of-dicts table suitable for JSON / React table rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from kerf_bim.family_editor import (
    FamilyDef,
    FamilyEditorError,
    FamilyParameter,
    instantiate_family,
    validate_family,
)


# ---------------------------------------------------------------------------
# Nested family
# ---------------------------------------------------------------------------

@dataclass
class NestedFamily:
    """A sub-family nested inside a parent family.

    Parameters
    ----------
    sub_family_id : str
        Identifier of the child family definition (name or registry key).
    placement_params : dict[str, Any]
        Parameter expressions (as strings or literal values) that drive the
        child family from the parent's resolved parameter namespace.
        E.g. ``{"width": "panel_width", "height": "height"}`` means the child's
        width comes from the parent's ``panel_width`` formula result.
    count : int | str
        Number of instances of this sub-family, or a parameter expression
        that evaluates to an integer (e.g. ``"bay_count"``).
    label : str
        Human-readable label for the nested component in the UI.
    ifc_type : str
        IFC entity suggestion for the sub-component (e.g. 'IfcDoor').
    """

    sub_family_id: str
    placement_params: Dict[str, Any] = field(default_factory=dict)
    count: Any = 1
    label: str = ""
    ifc_type: str = ""

    def __post_init__(self):
        if not self.sub_family_id:
            raise FamilyEditorError("NestedFamily.sub_family_id must be non-empty")


@dataclass
class NestedFamilyDef:
    """A :class:`~kerf_bim.family_editor.FamilyDef` augmented with nested
    sub-family references and a type catalogue.

    Parameters
    ----------
    parent : FamilyDef
        The host family definition.
    nested_families : list[NestedFamily]
        Ordered list of sub-family placements.
    """

    parent: FamilyDef
    nested_families: List[NestedFamily] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Type catalogue
# ---------------------------------------------------------------------------

@dataclass
class TypeCatalogueEntry:
    """One row in a family type catalogue.

    Equivalent to one line in a Revit type catalogue .txt file.

    Parameters
    ----------
    type_id : str
        Unique type identifier (e.g. ``"W600x200"``).
    name : str
        Human-readable type name (e.g. ``"600×200 mm – Single"`).
    param_overrides : dict[str, Any]
        Parameter values that override the family defaults for this type.
    description : str
        Optional free-text description.
    """

    type_id: str
    name: str
    param_overrides: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self):
        if not self.type_id:
            raise FamilyEditorError("TypeCatalogueEntry.type_id must be non-empty")
        if not self.name:
            raise FamilyEditorError("TypeCatalogueEntry.name must be non-empty")


@dataclass
class TypeCatalogue:
    """Ordered collection of type entries for a family.

    Parameters
    ----------
    family_name : str
        The parent family name this catalogue belongs to.
    entries : list[TypeCatalogueEntry]
        Ordered type entries.
    """

    family_name: str
    entries: List[TypeCatalogueEntry] = field(default_factory=list)

    def get(self, type_id: str) -> Optional[TypeCatalogueEntry]:
        """Look up an entry by type_id."""
        for e in self.entries:
            if e.type_id == type_id:
                return e
        return None


# ---------------------------------------------------------------------------
# Build type catalogue
# ---------------------------------------------------------------------------

def build_type_catalogue(
    family_def: FamilyDef,
    rows: List[Dict[str, Any]],
) -> TypeCatalogue:
    """Construct a validated :class:`TypeCatalogue` from raw row dicts.

    Each row must have ``type_id`` and ``name`` keys; all other keys are
    treated as parameter override values and validated against the family's
    declared parameters.

    Parameters
    ----------
    family_def : FamilyDef
        The family whose parameters the types override.
    rows : list[dict]
        Raw row dicts.

    Returns
    -------
    :class:`TypeCatalogue`

    Raises
    ------
    FamilyEditorError
        If a row is missing required keys or overrides an undeclared parameter.
    """
    param_names = {p.name for p in family_def.parameters}
    param_map: Dict[str, FamilyParameter] = {p.name: p for p in family_def.parameters}

    entries: List[TypeCatalogueEntry] = []
    seen_ids: set = set()

    for i, row in enumerate(rows):
        type_id = str(row.get("type_id", ""))
        name = str(row.get("name", ""))
        if not type_id:
            raise FamilyEditorError(f"rows[{i}]: 'type_id' is required")
        if not name:
            raise FamilyEditorError(f"rows[{i}]: 'name' is required")
        if type_id in seen_ids:
            raise FamilyEditorError(
                f"rows[{i}]: duplicate type_id '{type_id}'"
            )
        seen_ids.add(type_id)

        overrides: Dict[str, Any] = {}
        for key, val in row.items():
            if key in ("type_id", "name", "description"):
                continue
            if key not in param_names:
                raise FamilyEditorError(
                    f"rows[{i}] type '{type_id}': unknown parameter '{key}' "
                    f"(declared: {sorted(param_names)})"
                )
            # Type-check value
            p = param_map[key]
            if p.type == "number" and not isinstance(val, (int, float)):
                raise FamilyEditorError(
                    f"rows[{i}] type '{type_id}': parameter '{key}' expects a number, got {val!r}"
                )
            if p.type == "boolean" and not isinstance(val, bool):
                raise FamilyEditorError(
                    f"rows[{i}] type '{type_id}': parameter '{key}' expects a boolean, got {val!r}"
                )
            if p.type == "choice" and val not in (p.choices or []):
                raise FamilyEditorError(
                    f"rows[{i}] type '{type_id}': parameter '{key}' value {val!r} "
                    f"not in choices {p.choices!r}"
                )
            overrides[key] = val

        entries.append(TypeCatalogueEntry(
            type_id=type_id,
            name=name,
            param_overrides=overrides,
            description=str(row.get("description", "")),
        ))

    return TypeCatalogue(family_name=family_def.name, entries=entries)


# ---------------------------------------------------------------------------
# Instantiate nested family
# ---------------------------------------------------------------------------

def _resolve_count(count_expr: Any, ns: Dict[str, Any]) -> int:
    """Resolve count: literal int or a name reference in the namespace."""
    if isinstance(count_expr, int):
        return count_expr
    if isinstance(count_expr, float):
        return int(count_expr)
    if isinstance(count_expr, str):
        v = ns.get(count_expr, 1)
        try:
            return max(1, int(v))
        except (TypeError, ValueError):
            return 1
    return 1


def instantiate_nested(
    family_def: NestedFamilyDef,
    parameter_values: Optional[Dict[str, Any]] = None,
    type_id: Optional[str] = None,
    catalogue: Optional[TypeCatalogue] = None,
) -> Dict[str, Any]:
    """Evaluate the parent family and all nested sub-families.

    Parameters
    ----------
    family_def : NestedFamilyDef
    parameter_values : dict | None
        Override values for the parent parameters.
    type_id : str | None
        If given and ``catalogue`` is provided, type-override values are
        merged before the user's ``parameter_values``.
    catalogue : TypeCatalogue | None
        Type catalogue to look up ``type_id`` from.

    Returns
    -------
    dict with keys:
      ``family``         — parent family name
      ``category``       — parent category
      ``resolved_params``— final resolved parameter + formula values
      ``nested``         — list of nested sub-family result dicts
    """
    pv = dict(parameter_values or {})

    # Apply type catalogue overrides first (user overrides win)
    if type_id and catalogue:
        entry = catalogue.get(type_id)
        if entry:
            merged = dict(entry.param_overrides)
            merged.update(pv)
            pv = merged

    # Instantiate parent
    parent_result = instantiate_family(family_def.parent, pv)
    if isinstance(parent_result, dict):
        resolved = parent_result.get("resolved_params", pv)
    else:
        resolved = pv

    # Instantiate nested sub-families
    nested_results = []
    for nf in family_def.nested_families:
        # Resolve placement_params against parent resolved namespace
        child_params: Dict[str, Any] = {}
        for k, expr in nf.placement_params.items():
            if isinstance(expr, str) and expr in resolved:
                child_params[k] = resolved[expr]
            else:
                child_params[k] = expr

        count = _resolve_count(nf.count, resolved)

        nested_results.append({
            "sub_family_id": nf.sub_family_id,
            "label": nf.label or nf.sub_family_id,
            "count": count,
            "placement_params": child_params,
            "ifc_type": nf.ifc_type,
        })

    return {
        "family": family_def.parent.name,
        "category": family_def.parent.category,
        "type_id": type_id,
        "resolved_params": resolved,
        "nested": nested_results,
        "nested_count": len(nested_results),
    }


# ---------------------------------------------------------------------------
# Validate nested family
# ---------------------------------------------------------------------------

def validate_nested(family_def: NestedFamilyDef) -> List[str]:
    """Validate the parent family and nested structure.

    Checks:
    - Parent family errors (via :func:`~kerf_bim.family_editor.validate_family`).
    - Each nested family has a non-empty sub_family_id.
    - placement_params that reference parent formula/parameter names by string
      actually resolve (warns on unknown references).
    """
    errors = validate_family(family_def.parent)
    parent_names = {p.name for p in family_def.parent.parameters}
    parent_names |= {f.name for f in family_def.parent.formulas}

    for i, nf in enumerate(family_def.nested_families):
        if not nf.sub_family_id:
            errors.append(f"nested[{i}]: sub_family_id is required")
        for k, expr in nf.placement_params.items():
            if isinstance(expr, str) and expr not in parent_names:
                # Warn (not error) — the string might be a literal value or
                # come from a runtime context
                errors.append(
                    f"nested[{i}] '{nf.sub_family_id}': placement_params['{k}'] "
                    f"references unknown name '{expr}' in parent family "
                    f"(known: {sorted(parent_names)})"
                )

    return errors


# ---------------------------------------------------------------------------
# Catalogue table rendering
# ---------------------------------------------------------------------------

def render_catalogue_table(catalogue: TypeCatalogue) -> List[Dict[str, Any]]:
    """Produce a list-of-dicts table from the catalogue for UI rendering.

    Each row: ``{"type_id": ..., "name": ..., "description": ..., **overrides}``
    """
    rows = []
    for e in catalogue.entries:
        row: Dict[str, Any] = {
            "type_id": e.type_id,
            "name": e.name,
            "description": e.description,
        }
        row.update(e.param_overrides)
        rows.append(row)
    return rows


__all__ = [
    "NestedFamily",
    "NestedFamilyDef",
    "TypeCatalogueEntry",
    "TypeCatalogue",
    "build_type_catalogue",
    "instantiate_nested",
    "validate_nested",
    "render_catalogue_table",
]
