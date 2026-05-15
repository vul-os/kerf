"""
kerf_cad_core.family.model
===========================

Pure-Python data model and logic for the parametric family system.

Concepts
--------
FamilyParam
    A single named parameter: type, default, optional range, optional formula.
    Formulae are safe arithmetic expressions referencing other param names.

FamilyDef
    A named family containing an ordered dict of FamilyParam objects, a type
    catalog (dict[str, FamilyType]), and a build-recipe template (plain dict).

FamilyType
    A pre-defined parameter-value set — e.g. {"width": 900, "height": 2100}.
    Values override defaults; formulae are still evaluated after substitution.

FamilyInstance
    A concrete instance: references a FamilyType and carries per-instance
    override values.  Resolved to a concrete recipe dict on demand.

Safety
------
Formula evaluation uses ``ast`` with a whitelist of allowed node types and
operators — no ``eval`` of arbitrary code.  Supported: numeric literals,
param name references, +  -  *  /  **  (unary -)  (  ).

All builder functions return ``{ok: bool, errors: list[str]}`` — they never
raise on bad input.

Author: imranparuk
"""
from __future__ import annotations

import ast
import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

_PARAM_TYPES = frozenset(["number", "string", "bool"])

# AST node types that are permitted inside a formula expression.
# ast.Load appears on every ast.Name and ast.Call in read position — it is a
# context marker, not an operation, so it is always safe to allow.
# ast.Call is allowed but restricted at eval-time to whitelisted function names.
_SAFE_NODES = frozenset([
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,       # context node — read position; always benign
    ast.Call,       # only allowed when callee is a whitelisted name (checked separately)
    # Operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.FloorDiv, ast.Mod,
    ast.UAdd, ast.USub,
])

# Whitelist of safe names usable in formulae (math functions).
_SAFE_NAMES: dict[str, Any] = {
    "pi": math.pi,
    "e": math.e,
    "sqrt": math.sqrt,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FamilyParam:
    """A single named parameter in a family definition.

    Attributes
    ----------
    name : str
        Unique identifier within the family.
    param_type : str
        One of "number", "string", "bool".
    default : Any
        Default value.  For "number" params, must be numeric.
        For "string", must be str.  For "bool", must be bool.
    min_value : float | None
        Minimum allowed value (for "number" params only).
    max_value : float | None
        Maximum allowed value (for "number" params only).
    formula : str | None
        Arithmetic expression referencing other param names.  When set the
        param value is computed at resolve-time; any explicit value supplied
        for this param is ignored.
    description : str
        Human-readable description.
    """
    name: str
    param_type: str = "number"
    default: Any = 0.0
    min_value: float | None = None
    max_value: float | None = None
    formula: str | None = None
    description: str = ""


@dataclass
class FamilyType:
    """A pre-defined parameter-value set within a family.

    Attributes
    ----------
    name : str
        Unique identifier within the family (e.g. "Door 900x2100").
    values : dict[str, Any]
        Overrides for specific params.  Params not listed here fall back to
        their defaults (or computed formulas).
    description : str
        Human-readable description.
    """
    name: str
    values: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class FamilyInstance:
    """A concrete instance of a family type with optional overrides.

    Attributes
    ----------
    name : str
        Instance identifier (e.g. "Entry Door").
    family_name : str
        The family this instance belongs to.
    type_name : str
        The FamilyType this instance is based on.
    overrides : dict[str, Any]
        Per-instance value overrides applied on top of the type's values.
    """
    name: str
    family_name: str
    type_name: str
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class FamilyDef:
    """A complete parametric family definition.

    Attributes
    ----------
    name : str
        Family name (e.g. "Door").
    params : dict[str, FamilyParam]
        Ordered mapping of parameter name → FamilyParam.
    types : dict[str, FamilyType]
        Named type catalog.
    recipe_template : dict[str, Any]
        Build-recipe template.  String values may contain ``{param_name}``
        placeholders that are substituted during instantiation.
    description : str
        Human-readable description.
    """
    name: str
    params: dict[str, FamilyParam] = field(default_factory=dict)
    types: dict[str, FamilyType] = field(default_factory=dict)
    recipe_template: dict[str, Any] = field(default_factory=dict)
    description: str = ""


# ---------------------------------------------------------------------------
# In-memory registry (module-level, keyed by family name)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, FamilyDef] = {}


def _registry() -> dict[str, FamilyDef]:
    """Return the module-level family registry (test-friendly)."""
    return _REGISTRY


def _clear_registry() -> None:
    """Reset the registry — used by tests."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Safe formula evaluation
# ---------------------------------------------------------------------------

def _check_ast_safe(node: ast.AST) -> list[str]:
    """Return a list of safety-violation messages for *node*.

    Rules
    -----
    * Only node types in ``_SAFE_NODES`` are allowed.
    * ``ast.Call`` is allowed only when the callee is a ``ast.Name`` whose id
      appears in ``_SAFE_NAMES`` (i.e. a whitelisted math function).
    * No keyword arguments or ``*args`` / ``**kwargs`` on calls.
    """
    errors: list[str] = []
    for n in ast.walk(node):
        if type(n) not in _SAFE_NODES:
            errors.append(f"unsafe node type: {type(n).__name__}")
            continue
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name):
                errors.append("call target must be a plain name (no attribute access)")
            elif n.func.id not in _SAFE_NAMES:
                errors.append(f"call to '{n.func.id}' is not whitelisted")
            if n.keywords or n.starargs if hasattr(n, "starargs") else n.keywords:
                errors.append("keyword/star arguments not allowed in formula calls")
    return errors


def _eval_formula(formula: str, bindings: dict[str, float]) -> tuple[float | None, str | None]:
    """Evaluate *formula* safely given numeric *bindings*.

    Returns (result, None) on success or (None, error_message) on failure.
    Raises nothing.
    """
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        return None, f"formula syntax error: {exc}"

    safety_errors = _check_ast_safe(tree)
    if safety_errors:
        return None, f"formula not safe: {'; '.join(safety_errors)}"

    # Build evaluation namespace: safe math names + param bindings.
    namespace: dict[str, Any] = dict(_SAFE_NAMES)
    namespace.update(bindings)

    # Ensure all Name nodes refer to something in namespace.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in namespace:
                return None, f"unknown name in formula: '{node.id}'"

    try:
        result = eval(compile(tree, filename="<formula>", mode="eval"), {"__builtins__": {}}, namespace)  # noqa: S307
    except Exception as exc:
        return None, f"formula evaluation error: {exc}"

    if not isinstance(result, (int, float)):
        return None, f"formula must evaluate to a number, got {type(result).__name__}"
    return float(result), None


# ---------------------------------------------------------------------------
# Param validation helpers
# ---------------------------------------------------------------------------

def _validate_param_def(p: FamilyParam) -> list[str]:
    """Return validation errors for a FamilyParam definition."""
    errors: list[str] = []
    if not p.name or not isinstance(p.name, str):
        errors.append("param name must be a non-empty string")
    if p.param_type not in _PARAM_TYPES:
        errors.append(f"param '{p.name}': invalid type '{p.param_type}'; must be one of {sorted(_PARAM_TYPES)}")
    if p.param_type == "number":
        if not isinstance(p.default, (int, float)):
            errors.append(f"param '{p.name}': default must be numeric for type 'number'")
        if p.min_value is not None and p.max_value is not None:
            if p.min_value > p.max_value:
                errors.append(f"param '{p.name}': min_value > max_value")
    if p.param_type == "bool" and not isinstance(p.default, bool):
        errors.append(f"param '{p.name}': default must be bool for type 'bool'")
    if p.param_type == "string" and not isinstance(p.default, str):
        errors.append(f"param '{p.name}': default must be str for type 'string'")
    if p.formula is not None:
        # Smoke-check formula syntax.
        try:
            tree = ast.parse(p.formula.strip(), mode="eval")
            safety_errors = _check_ast_safe(tree)
            if safety_errors:
                errors.append(f"param '{p.name}' formula not safe: {'; '.join(safety_errors)}")
        except SyntaxError as exc:
            errors.append(f"param '{p.name}' formula syntax error: {exc}")
    return errors


def _detect_cycle(params: dict[str, FamilyParam]) -> list[str]:
    """Return param names that form a dependency cycle, or [] if none."""
    # Build adjacency list: param → set of params it references in its formula.
    deps: dict[str, set[str]] = {}
    for name, p in params.items():
        if p.formula is None:
            deps[name] = set()
            continue
        try:
            tree = ast.parse(p.formula.strip(), mode="eval")
        except SyntaxError:
            deps[name] = set()
            continue
        referenced = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id in params
        }
        deps[name] = referenced

    # Tarjan-style DFS cycle detection.
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in params}
    cycle_nodes: list[str] = []

    def dfs(node: str) -> bool:
        """Return True if a cycle is found."""
        color[node] = GRAY
        for nb in deps.get(node, set()):
            if color.get(nb, BLACK) == GRAY:
                if nb not in cycle_nodes:
                    cycle_nodes.append(nb)
                if node not in cycle_nodes:
                    cycle_nodes.append(node)
                return True
            if color.get(nb, BLACK) == WHITE:
                if dfs(nb):
                    return True
        color[node] = BLACK
        return False

    for n in list(params):
        if color[n] == WHITE:
            dfs(n)

    return cycle_nodes


def _resolve_params(
    params: dict[str, FamilyParam],
    overrides: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve all param values given *overrides*.

    Returns (resolved_dict, []) on success or (None, errors) on failure.
    Formula params are computed in dependency order; cycles are reported as
    errors.
    """
    errors: list[str] = []

    # Check for cycles.
    cycle = _detect_cycle(params)
    if cycle:
        errors.append(f"formula cycle detected involving params: {sorted(cycle)}")
        return None, errors

    # Topological sort (Kahn's algorithm).
    # Build edge set: param → its formula deps (only params in this family).
    adj: dict[str, set[str]] = {}
    in_deg: dict[str, int] = {}
    for name, p in params.items():
        in_deg[name] = 0
        adj[name] = set()

    for name, p in params.items():
        if p.formula is None:
            continue
        try:
            tree = ast.parse(p.formula.strip(), mode="eval")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in params:
                adj[node.id].add(name)  # dep → dependent
                in_deg[name] = in_deg.get(name, 0) + 1

    queue = [n for n, d in in_deg.items() if d == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in adj.get(n, set()):
            in_deg[m] -= 1
            if in_deg[m] == 0:
                queue.append(m)

    if len(order) != len(params):
        # Remaining nodes are in a cycle (should have been caught above).
        errors.append("could not resolve param order; possible formula cycle")
        return None, errors

    resolved: dict[str, Any] = {}

    for name in order:
        p = params[name]
        if p.formula is not None:
            # Build numeric bindings from already-resolved params.
            bindings: dict[str, float] = {
                k: float(v)
                for k, v in resolved.items()
                if isinstance(v, (int, float))
            }
            val, err = _eval_formula(p.formula, bindings)
            if err:
                errors.append(f"param '{name}': {err}")
                return None, errors
            resolved[name] = val
        else:
            # Use override → type value → default.
            if name in overrides:
                resolved[name] = overrides[name]
            else:
                resolved[name] = copy.deepcopy(p.default)

    return resolved, []


def _validate_ranges(
    params: dict[str, FamilyParam],
    resolved: dict[str, Any],
) -> list[str]:
    """Check that all resolved number params satisfy their min/max."""
    errors: list[str] = []
    for name, p in params.items():
        if p.param_type != "number":
            continue
        val = resolved.get(name)
        if val is None:
            continue
        if not isinstance(val, (int, float)):
            errors.append(f"param '{name}': expected a number, got {type(val).__name__}")
            continue
        if p.min_value is not None and val < p.min_value:
            errors.append(
                f"param '{name}': value {val} is below minimum {p.min_value}"
            )
        if p.max_value is not None and val > p.max_value:
            errors.append(
                f"param '{name}': value {val} is above maximum {p.max_value}"
            )
    return errors


def _substitute_template(template: Any, resolved: dict[str, Any]) -> Any:
    """Recursively substitute ``{param_name}`` placeholders in *template*."""
    if isinstance(template, str):
        def replacer(m: re.Match) -> str:
            key = m.group(1)
            return str(resolved.get(key, m.group(0)))
        return re.sub(r"\{(\w+)\}", replacer, template)
    if isinstance(template, dict):
        return {k: _substitute_template(v, resolved) for k, v in template.items()}
    if isinstance(template, list):
        return [_substitute_template(v, resolved) for v in template]
    return template


# ---------------------------------------------------------------------------
# Public builder functions
# ---------------------------------------------------------------------------

def family_define(
    name: str,
    params: list[dict],
    recipe_template: dict | None = None,
    description: str = "",
    *,
    _registry_: dict | None = None,
) -> dict:
    """Define a new parametric family and register it in the in-memory store.

    Parameters
    ----------
    name : str
        Family name.  Must be non-empty and unique in the registry.
    params : list[dict]
        Each dict: {name, param_type?, default?, min_value?, max_value?,
                    formula?, description?}
    recipe_template : dict | None
        Build-recipe template.  String values may contain ``{param_name}``
        placeholders.
    description : str
        Human-readable description.

    Returns
    -------
    dict
        ``{ok: True, family_name: str}`` on success.
        ``{ok: False, errors: list[str]}`` on failure.
    """
    reg = _registry_ if _registry_ is not None else _REGISTRY
    errors: list[str] = []

    if not name or not isinstance(name, str):
        errors.append("family name must be a non-empty string")
        return {"ok": False, "errors": errors}

    if name in reg:
        errors.append(f"family '{name}' already exists")
        return {"ok": False, "errors": errors}

    if not isinstance(params, list):
        errors.append("'params' must be a list")
        return {"ok": False, "errors": errors}

    param_objs: dict[str, FamilyParam] = {}
    seen_names: set[str] = set()
    for raw in params:
        if not isinstance(raw, dict):
            errors.append(f"each param must be a dict, got {type(raw).__name__}")
            continue
        pname = raw.get("name", "")
        if pname in seen_names:
            errors.append(f"duplicate param name: '{pname}'")
            continue
        seen_names.add(pname)
        p = FamilyParam(
            name=pname,
            param_type=raw.get("param_type", "number"),
            default=raw.get("default", 0.0),
            min_value=raw.get("min_value"),
            max_value=raw.get("max_value"),
            formula=raw.get("formula"),
            description=raw.get("description", ""),
        )
        p_errors = _validate_param_def(p)
        errors.extend(p_errors)
        if not p_errors:
            param_objs[pname] = p

    if errors:
        return {"ok": False, "errors": errors}

    # Check for formula cycles in the set of params.
    cycle = _detect_cycle(param_objs)
    if cycle:
        return {
            "ok": False,
            "errors": [f"formula cycle detected involving params: {sorted(cycle)}"],
        }

    family = FamilyDef(
        name=name,
        params=param_objs,
        types={},
        recipe_template=copy.deepcopy(recipe_template or {}),
        description=description,
    )
    reg[name] = family
    return {"ok": True, "family_name": name}


def family_add_type(
    family_name: str,
    type_name: str,
    values: dict,
    description: str = "",
    *,
    _registry_: dict | None = None,
) -> dict:
    """Add a named type (parameter-value set) to an existing family.

    Parameters
    ----------
    family_name : str
        Name of the target family.
    type_name : str
        Unique name for this type (e.g. "Door 900x2100").
    values : dict
        Param overrides for this type.  Only params defined in the family are
        accepted; unknown keys produce an error.
    description : str
        Human-readable description.

    Returns
    -------
    dict
        ``{ok: True, family_name: str, type_name: str}`` on success.
        ``{ok: False, errors: list[str]}`` on failure.
    """
    reg = _registry_ if _registry_ is not None else _REGISTRY
    errors: list[str] = []

    family = reg.get(family_name)
    if family is None:
        errors.append(f"family '{family_name}' not found")
        return {"ok": False, "errors": errors}

    if not type_name or not isinstance(type_name, str):
        errors.append("type_name must be a non-empty string")
        return {"ok": False, "errors": errors}

    if type_name in family.types:
        errors.append(f"type '{type_name}' already exists in family '{family_name}'")
        return {"ok": False, "errors": errors}

    if not isinstance(values, dict):
        errors.append("'values' must be a dict")
        return {"ok": False, "errors": errors}

    # Check for unknown param names.
    for k in values:
        if k not in family.params:
            errors.append(f"unknown param '{k}' in type values for family '{family_name}'")

    if errors:
        return {"ok": False, "errors": errors}

    # Validate ranges against the merged param set.
    merged = {**{n: p.default for n, p in family.params.items()}, **values}
    range_errors = _validate_ranges(family.params, merged)
    if range_errors:
        return {"ok": False, "errors": range_errors}

    family.types[type_name] = FamilyType(
        name=type_name,
        values=copy.deepcopy(values),
        description=description,
    )
    return {"ok": True, "family_name": family_name, "type_name": type_name}


def family_instantiate(
    family_name: str,
    type_name: str,
    instance_name: str = "",
    overrides: dict | None = None,
    *,
    _registry_: dict | None = None,
) -> dict:
    """Instantiate a family type and resolve its parametric recipe.

    Merges type values → instance overrides → formula evaluation → range check
    → template substitution.

    Parameters
    ----------
    family_name : str
        Name of the target family.
    type_name : str
        Name of the type to instantiate.
    instance_name : str
        Optional human-readable identifier for this instance.
    overrides : dict | None
        Per-instance param overrides applied on top of the type's values.

    Returns
    -------
    dict
        ``{ok: True, instance: FamilyInstance.__dict__, resolved_params: dict,
            recipe: dict}`` on success.
        ``{ok: False, errors: list[str]}`` on failure.
    """
    reg = _registry_ if _registry_ is not None else _REGISTRY
    errors: list[str] = []

    family = reg.get(family_name)
    if family is None:
        errors.append(f"family '{family_name}' not found")
        return {"ok": False, "errors": errors}

    ftype = family.types.get(type_name)
    if ftype is None:
        errors.append(f"type '{type_name}' not found in family '{family_name}'")
        return {"ok": False, "errors": errors}

    if overrides is not None and not isinstance(overrides, dict):
        errors.append("'overrides' must be a dict or null")
        return {"ok": False, "errors": errors}

    # Check for unknown override keys.
    for k in (overrides or {}):
        if k not in family.params:
            errors.append(f"unknown param '{k}' in overrides for family '{family_name}'")
    if errors:
        return {"ok": False, "errors": errors}

    # Merge: type values → instance overrides.
    merged_overrides = {**ftype.values, **(overrides or {})}

    resolved, resolve_errors = _resolve_params(family.params, merged_overrides)
    if resolve_errors:
        return {"ok": False, "errors": resolve_errors}

    range_errors = _validate_ranges(family.params, resolved)
    if range_errors:
        return {"ok": False, "errors": range_errors}

    recipe = _substitute_template(family.recipe_template, resolved)

    instance = FamilyInstance(
        name=instance_name or f"{family_name}:{type_name}",
        family_name=family_name,
        type_name=type_name,
        overrides=overrides or {},
    )

    return {
        "ok": True,
        "instance": {
            "name": instance.name,
            "family_name": instance.family_name,
            "type_name": instance.type_name,
            "overrides": instance.overrides,
        },
        "resolved_params": resolved,
        "recipe": recipe,
    }


def family_validate(
    family_name: str,
    values: dict,
    *,
    _registry_: dict | None = None,
) -> dict:
    """Validate a set of param values against a family's constraints.

    Evaluates formulas, checks ranges, and returns a detailed error list.
    Does not modify the registry.

    Parameters
    ----------
    family_name : str
        Name of the target family.
    values : dict
        Param values to validate (non-formula params only; formula params are
        computed).

    Returns
    -------
    dict
        ``{ok: True, resolved_params: dict}`` when all values are valid.
        ``{ok: False, errors: list[str]}`` with full details otherwise.
    """
    reg = _registry_ if _registry_ is not None else _REGISTRY
    errors: list[str] = []

    family = reg.get(family_name)
    if family is None:
        errors.append(f"family '{family_name}' not found")
        return {"ok": False, "errors": errors}

    if not isinstance(values, dict):
        errors.append("'values' must be a dict")
        return {"ok": False, "errors": errors}

    for k in values:
        if k not in family.params:
            errors.append(f"unknown param '{k}' in family '{family_name}'")
    if errors:
        return {"ok": False, "errors": errors}

    resolved, resolve_errors = _resolve_params(family.params, values)
    if resolve_errors:
        return {"ok": False, "errors": resolve_errors}

    range_errors = _validate_ranges(family.params, resolved)
    if range_errors:
        return {"ok": False, "errors": range_errors}

    return {"ok": True, "resolved_params": resolved}
