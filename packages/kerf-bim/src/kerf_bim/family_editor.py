"""
kerf_bim.family_editor
=======================

Simplified parametric family model for the GDL-replacement Family Editor.

Three data classes form the model:

* :class:`FamilyParameter` — a typed, bounded parameter declaration
  (number / text / choice / boolean).
* :class:`FamilyFormula` — a derived value expressed as a Python
  arithmetic expression referencing parameter names.
* :class:`FamilyDef` — a complete family definition: category, parameters,
  formulas, and a Python geometry script.

Two runtime functions:

* :func:`instantiate_family` — evaluate formulas, execute geometry script,
  return a :class:`~kerf_cad_core.body.Body` (or a plain dict summary when
  the CAD kernel is unavailable).
* :func:`validate_family` — static analysis: formula syntax, parameter
  references, geometry script safety; returns a list of error strings.

LLM tools ``bim_instantiate_family``, ``bim_validate_family``,
``bim_list_families`` are registered via the standard gated-import pattern
so they are only wired when :mod:`kerf_chat` is present.

This module intentionally mirrors (but does not replace) the richer
:mod:`kerf_bim.family` package — it is the simplified, script-friendly
surface intended for Python SDK users authoring families from scratch.
"""
from __future__ import annotations

import ast
import math
import textwrap
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    # Data classes
    "FamilyParameter",
    "FamilyFormula",
    "FamilyDef",
    # Runtime
    "instantiate_family",
    "validate_family",
    # Errors
    "FamilyEditorError",
    "FamilyFormulaError",
]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FamilyEditorError(ValueError):
    """Base error for the family editor system."""


class FamilyFormulaError(FamilyEditorError):
    """Raised when a formula expression is invalid or unsafe."""


# ---------------------------------------------------------------------------
# Allowed names in formula / script expressions (safe math subset)
# ---------------------------------------------------------------------------

_SAFE_MATH: dict[str, Any] = {
    k: v
    for k, v in vars(math).items()
    if not k.startswith("_")
}
_SAFE_MATH.update({
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float,
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FamilyParameter:
    """A single typed parameter declaration.

    Attributes
    ----------
    name : str
        Unique identifier within the family. Must be a valid Python
        identifier so it can be referenced in formulas.
    type : str
        One of ``"number"``, ``"text"``, ``"choice"``, ``"boolean"``.
    default : Any
        Default value. Must match ``type``.
    min : float | None
        Minimum value (number only).
    max : float | None
        Maximum value (number only).
    choices : list | None
        Allowed values (choice only).
    units : str
        Display units hint, e.g. ``"mm"``, ``"deg"`` (informational only).
    description : str
        Human-readable description.
    """

    name: str
    type: str = "number"
    default: Any = 0.0
    min: float | None = None
    max: float | None = None
    choices: list | None = None
    units: str = ""
    description: str = ""

    VALID_TYPES: frozenset = frozenset({"number", "text", "choice", "boolean"})

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.isidentifier():
            raise FamilyEditorError(
                f"FamilyParameter.name must be a valid identifier, got {self.name!r}"
            )
        if self.type not in self.VALID_TYPES:
            raise FamilyEditorError(
                f"FamilyParameter '{self.name}': type must be one of "
                f"{sorted(self.VALID_TYPES)}, got {self.type!r}"
            )
        if self.type == "choice" and not self.choices:
            raise FamilyEditorError(
                f"FamilyParameter '{self.name}': choice parameters must have a "
                f"non-empty choices list"
            )
        if self.type == "choice" and self.default not in (self.choices or []):
            raise FamilyEditorError(
                f"FamilyParameter '{self.name}': default {self.default!r} is not "
                f"in choices {self.choices!r}"
            )
        if (
            self.type == "number"
            and self.min is not None
            and self.max is not None
            and self.min > self.max
        ):
            raise FamilyEditorError(
                f"FamilyParameter '{self.name}': min ({self.min}) > max ({self.max})"
            )


@dataclass
class FamilyFormula:
    """A derived value: ``name = expression``.

    The expression is a pure Python arithmetic expression that may reference
    parameter names (and other formula names in dependency order).

    Example::

        FamilyFormula(
            name="frame_width",
            expression="width - 2 * frame_thickness",
        )
    """

    name: str
    expression: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.isidentifier():
            raise FamilyEditorError(
                f"FamilyFormula.name must be a valid identifier, got {self.name!r}"
            )
        if not isinstance(self.expression, str) or not self.expression.strip():
            raise FamilyEditorError(
                f"FamilyFormula '{self.name}': expression must be a non-empty string"
            )
        # Syntax-check at declaration time.
        try:
            ast.parse(self.expression, mode="eval")
        except SyntaxError as exc:
            raise FamilyFormulaError(
                f"FamilyFormula '{self.name}': syntax error in expression "
                f"{self.expression!r}: {exc}"
            ) from exc


@dataclass
class FamilyDef:
    """A complete parametric family definition.

    Attributes
    ----------
    name : str
        Human-readable name, e.g. ``"Single Swing Door"``.
    category : str
        One of ``"door"``, ``"window"``, ``"furniture"``, ``"fixture"``,
        ``"column"``, ``"beam"``, ``"generic"``.
    parameters : list[FamilyParameter]
        Input parameters that drive the geometry.
    formulas : list[FamilyFormula]
        Derived values computed from parameters in declaration order.
    geometry_script : str
        Python code that builds a B-rep body.  The script is executed with
        all parameter + formula values pre-bound into its namespace; it must
        assign ``result`` to a :class:`~kerf_cad_core.body.Body` or a dict
        summary.
    description : str
        Optional human-readable description.
    """

    name: str
    category: str
    parameters: list[FamilyParameter] = field(default_factory=list)
    formulas: list[FamilyFormula] = field(default_factory=list)
    geometry_script: str = ""
    description: str = ""

    VALID_CATEGORIES: frozenset = frozenset({
        "door", "window", "furniture", "fixture",
        "column", "beam", "generic",
    })

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise FamilyEditorError("FamilyDef.name must be a non-empty string")
        if self.category not in self.VALID_CATEGORIES:
            raise FamilyEditorError(
                f"FamilyDef '{self.name}': category must be one of "
                f"{sorted(self.VALID_CATEGORIES)}, got {self.category!r}"
            )
        # Check for duplicate parameter names.
        seen: set[str] = set()
        for p in self.parameters:
            if p.name in seen:
                raise FamilyEditorError(
                    f"FamilyDef '{self.name}': duplicate parameter name '{p.name}'"
                )
            seen.add(p.name)

    # -- convenience -------------------------------------------------------

    def param_defaults(self) -> dict[str, Any]:
        """Return a ``name → default`` mapping."""
        return {p.name: p.default for p in self.parameters}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_UNSAFE_NODES = frozenset({
    ast.Import, ast.ImportFrom, ast.Delete, ast.Global, ast.Nonlocal,
    ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor,
    ast.AsyncWith,
})


def _check_ast_safety(
    source: str,
    label: str,
) -> list[str]:
    """Return a list of safety-violation messages for *source*."""
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        errors.append(f"{label}: syntax error: {exc}")
        return errors

    for node in ast.walk(tree):
        if type(node) in _UNSAFE_NODES:
            errors.append(
                f"{label}: unsafe construct '{type(node).__name__}' is not allowed"
            )
        # Disallow attribute access except on the 'math' module.
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id not in ("math",):
                errors.append(
                    f"{label}: attribute access on '{node.value.id}' is not allowed"
                )
        # Forbid exec/eval/compile/open/__import__.
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {
                "exec", "eval", "compile", "open", "__import__",
            }:
                errors.append(
                    f"{label}: call to '{func.id}' is not allowed"
                )
    return errors


def validate_family(family_def: FamilyDef) -> list[str]:
    """Validate *family_def* and return a (possibly empty) list of error strings.

    Checks performed:

    * Formula expression syntax.
    * Formula references resolve to declared parameters or earlier formulas.
    * Geometry script AST safety (no imports, no exec/eval, no attribute
      access on non-math names).

    Parameters
    ----------
    family_def : FamilyDef

    Returns
    -------
    list[str]
        Empty list means valid.  Each string is a human-readable error.
    """
    errors: list[str] = []

    # Collect all declared names.
    known_names: set[str] = {p.name for p in family_def.parameters}

    for formula in family_def.formulas:
        try:
            tree = ast.parse(formula.expression, mode="eval")
        except SyntaxError as exc:
            errors.append(f"formula '{formula.name}': syntax error: {exc}")
            known_names.add(formula.name)
            continue

        # Check that every Name node is known (excluding safe-math builtins).
        ref_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id not in _SAFE_MATH
        }
        for ref in ref_names:
            if ref not in known_names:
                errors.append(
                    f"formula '{formula.name}': references unknown name '{ref}' "
                    f"(known: {sorted(known_names)})"
                )

        known_names.add(formula.name)

    # Geometry script safety.
    if family_def.geometry_script.strip():
        errors.extend(
            _check_ast_safety(
                family_def.geometry_script,
                label="geometry_script",
            )
        )

    return errors


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


def _eval_formula(
    expression: str,
    bindings: dict[str, Any],
) -> Any:
    """Safely evaluate a formula expression against *bindings*."""
    ns = {**_SAFE_MATH, **bindings}
    try:
        return eval(  # noqa: S307
            compile(expression, "<formula>", "eval"),
            {"__builtins__": {}},
            ns,
        )
    except Exception as exc:
        raise FamilyFormulaError(
            f"error evaluating formula {expression!r}: {exc}"
        ) from exc


def _build_namespace(
    family_def: FamilyDef,
    parameter_values: dict[str, Any],
) -> dict[str, Any]:
    """Build the complete evaluation namespace (params + formulas)."""
    ns: dict[str, Any] = family_def.param_defaults()
    ns.update(parameter_values)

    for formula in family_def.formulas:
        ns[formula.name] = _eval_formula(formula.expression, ns)

    return ns


def instantiate_family(
    family_def: FamilyDef,
    parameter_values: dict[str, Any] | None = None,
) -> Any:
    """Evaluate formulas and run the geometry script.

    Parameters
    ----------
    family_def : FamilyDef
    parameter_values : dict | None
        Override values for any declared parameter. Defaults used for
        omitted parameters.

    Returns
    -------
    Any
        Whatever the geometry script assigns to ``result``.  When no
        geometry script is provided, returns a plain dict with
        ``resolved_params``.

    Raises
    ------
    FamilyFormulaError
        If a formula fails to evaluate.
    FamilyEditorError
        If the geometry script raises.
    """
    pv = dict(parameter_values or {})
    ns = _build_namespace(family_def, pv)

    if not family_def.geometry_script.strip():
        return {
            "family": family_def.name,
            "category": family_def.category,
            "resolved_params": ns,
        }

    exec_globals: dict[str, Any] = {
        "__builtins__": {
            "abs": abs, "round": round, "min": min, "max": max,
            "int": int, "float": float, "bool": bool, "str": str,
            "list": list, "dict": dict, "tuple": tuple,
            "range": range, "len": len, "sum": sum,
            "sorted": sorted, "zip": zip, "enumerate": enumerate,
            "print": print,
        },
        "math": math,
        **_SAFE_MATH,
    }
    exec_locals: dict[str, Any] = dict(ns)

    try:
        import kerf_cad_core  # noqa: F401
        exec_globals["kerf_cad_core"] = kerf_cad_core
    except ImportError:
        pass

    try:
        exec(  # noqa: S102
            compile(
                textwrap.dedent(family_def.geometry_script),
                f"<family:{family_def.name}>",
                "exec",
            ),
            exec_globals,
            exec_locals,
        )
    except Exception as exc:
        raise FamilyEditorError(
            f"geometry script for '{family_def.name}' raised: {exc}"
        ) from exc

    result = exec_locals.get("result")
    if result is None:
        return {
            "family": family_def.name,
            "category": family_def.category,
            "resolved_params": ns,
        }
    return result


# ---------------------------------------------------------------------------
# LLM tool registration (gated — only when kerf_chat is importable)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx

    # -- bim_validate_family -----------------------------------------------

    _bim_validate_spec = ToolSpec(
        name="bim_validate_family",
        description=(
            "Validate a FamilyDef definition (provided as a JSON dict) and return "
            "any errors. An empty errors list means the family is valid. "
            "Keys: name (str), category (str), parameters (list of {name, type, "
            "default, min?, max?, choices?, units?}), formulas (list of "
            "{name, expression}), geometry_script (str)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "family": {"type": "object"},
            },
            "required": ["family"],
        },
    )

    @register(_bim_validate_spec, write=False)
    async def _run_bim_validate_family(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw = a.get("family")
        if not isinstance(raw, dict):
            return err_payload("'family' must be a JSON object", "BAD_ARGS")

        try:
            fdef = _family_def_from_dict(raw)
        except FamilyEditorError as exc:
            return err_payload(str(exc), "VALIDATION_ERROR")

        errors = validate_family(fdef)
        return ok_payload({
            "family_name": fdef.name,
            "valid": len(errors) == 0,
            "errors": errors,
        })

    # -- bim_instantiate_family --------------------------------------------

    _bim_instantiate_spec = ToolSpec(
        name="bim_instantiate_family",
        description=(
            "Instantiate a FamilyDef with the given parameter overrides and "
            "return the resolved parameter values and geometry summary. "
            "Provide either a full 'family' dict or a 'family_name' to look up "
            "from the built-in starter library."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "family": {"type": "object"},
                "family_name": {"type": "string"},
                "parameter_values": {"type": "object"},
            },
        },
    )

    @register(_bim_instantiate_spec, write=False)
    async def _run_bim_instantiate_family(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        pv = a.get("parameter_values") or {}

        if "family" in a:
            try:
                fdef = _family_def_from_dict(a["family"])
            except FamilyEditorError as exc:
                return err_payload(str(exc), "VALIDATION_ERROR")
        elif "family_name" in a:
            fdef = _get_starter_family(a["family_name"])
            if fdef is None:
                return err_payload(
                    f"no starter family named {a['family_name']!r}", "NOT_FOUND"
                )
        else:
            return err_payload(
                "provide either 'family' (dict) or 'family_name' (string)", "BAD_ARGS"
            )

        try:
            result = instantiate_family(fdef, pv)
        except FamilyEditorError as exc:
            return err_payload(str(exc), "INSTANTIATION_ERROR")

        if isinstance(result, dict):
            return ok_payload(result)
        return ok_payload({
            "family": fdef.name,
            "category": fdef.category,
            "parameter_values": pv,
            "result_type": type(result).__name__,
        })

    # -- bim_list_families -------------------------------------------------

    _bim_list_spec = ToolSpec(
        name="bim_list_families",
        description=(
            "List all families in the built-in starter library. "
            "Returns a list of {name, category, parameter_count, description}. "
            "Optionally filter by category."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (optional).",
                },
            },
        },
    )

    @register(_bim_list_spec, write=False)
    async def _run_bim_list_families(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        category_filter = a.get("category")
        families = _list_starter_families()
        if category_filter:
            families = [f for f in families if f["category"] == category_filter]

        return ok_payload({"families": families, "count": len(families)})

except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helpers for LLM tools — starter family lookup
# ---------------------------------------------------------------------------


def _family_def_from_dict(raw: dict) -> "FamilyDef":
    """Construct a :class:`FamilyDef` from a plain dict."""
    params = [
        FamilyParameter(
            name=p["name"],
            type=p.get("type", "number"),
            default=p.get("default", 0.0),
            min=p.get("min"),
            max=p.get("max"),
            choices=p.get("choices"),
            units=p.get("units", ""),
            description=p.get("description", ""),
        )
        for p in raw.get("parameters", [])
    ]
    formulas = [
        FamilyFormula(name=f["name"], expression=f["expression"])
        for f in raw.get("formulas", [])
    ]
    return FamilyDef(
        name=raw.get("name", "Unnamed"),
        category=raw.get("category", "generic"),
        parameters=params,
        formulas=formulas,
        geometry_script=raw.get("geometry_script", ""),
        description=raw.get("description", ""),
    )


def _list_starter_families() -> list[dict]:
    """Return metadata for all starter families in :mod:`kerf_bim.families`."""
    import importlib
    import pkgutil

    import kerf_bim.families as _pkg

    results = []
    for info in pkgutil.iter_modules(_pkg.__path__):
        try:
            mod = importlib.import_module(f"kerf_bim.families.{info.name}")
            fdef: FamilyDef | None = getattr(mod, "family_def", None)
            if fdef is not None:
                results.append({
                    "name": fdef.name,
                    "category": fdef.category,
                    "parameter_count": len(fdef.parameters),
                    "description": fdef.description,
                    "module": info.name,
                })
        except Exception:
            pass
    return results


def _get_starter_family(name: str) -> "FamilyDef | None":
    """Return the starter :class:`FamilyDef` by *name*, or ``None``."""
    for meta in _list_starter_families():
        if meta["name"] == name:
            import importlib
            mod = importlib.import_module(f"kerf_bim.families.{meta['module']}")
            return getattr(mod, "family_def", None)
    return None
