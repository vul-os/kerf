"""
kerf_bim.family.evaluator
==========================

Safe arithmetic-expression evaluator for parametric family formulae.

Design goals
------------
* No ``eval`` of arbitrary code. Parse the formula with ``ast``,
  walk every node and reject anything outside a strict whitelist.
* Support the basic operators a parametric-family author needs:
  ``+ - * / // % **`` and unary ``+ -``.
* Expose a small set of math functions: sin/cos/tan, asin/acos/atan,
  sqrt, abs, floor/ceil/round, min/max, log/exp, plus ``pi`` and ``e``.
* Provide a topological-sort resolver that evaluates dependent
  formulae in dependency order, and reports cycles cleanly.

Public surface (re-exported via ``kerf_bim.family``):
    FormulaError, CycleError
    evaluate_formula(formula, bindings) -> float
    topo_sort(deps) -> list[str]
    resolve_parameters(params, overrides) -> dict[str, Any]

The evaluator is intentionally side-effect free; it does not touch
the wider Kerf runtime, the DB, or any plugin state. This makes it
trivial to reuse from downstream BIM modules (walls, doors, stairs,
structural grid, ...) without dragging async or transactional
machinery in.
"""
from __future__ import annotations

import ast
import math
from typing import Any, Iterable, Mapping

__all__ = [
    "FormulaError",
    "CycleError",
    "SAFE_NAMES",
    "evaluate_formula",
    "extract_referenced_names",
    "topo_sort",
    "resolve_parameters",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FormulaError(ValueError):
    """Raised when a formula is syntactically invalid, contains unsafe
    constructs, references unknown names, or fails to evaluate."""


class CycleError(FormulaError):
    """Raised when a set of formula parameters forms a dependency cycle."""


# ---------------------------------------------------------------------------
# Whitelist of AST nodes & callable names
# ---------------------------------------------------------------------------

# Every node type permitted inside a formula. ``ast.Load`` is a context
# marker (read-position) — always benign.
_SAFE_NODES: frozenset[type] = frozenset([
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.IfExp,           # ternary: a if cond else b
    ast.Compare,         # comparisons inside IfExp
    ast.BoolOp,          # and/or for IfExp guards
    # Binary operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
    ast.FloorDiv, ast.Mod,
    # Unary operators
    ast.UAdd, ast.USub, ast.Not,
    # Comparison operators
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    # Boolean operators
    ast.And, ast.Or,
])

# Functions and constants that formulae may reference. Anything else is
# rejected at parse-time.
SAFE_NAMES: dict[str, Any] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sqrt": math.sqrt,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "min": min,
    "max": max,
    "log": math.log,
    "exp": math.exp,
    "radians": math.radians,
    "degrees": math.degrees,
}


# ---------------------------------------------------------------------------
# AST safety check
# ---------------------------------------------------------------------------

def _check_ast_safe(tree: ast.AST) -> None:
    """Walk *tree* and raise :class:`FormulaError` on any disallowed
    construct.

    Rules
    -----
    * Node type must appear in ``_SAFE_NODES``.
    * ``ast.Call`` callees must be a plain :class:`ast.Name` and the
      name must be in :data:`SAFE_NAMES`.
    * No keyword arguments, ``*args``, or ``**kwargs`` on calls.
    """
    for node in ast.walk(tree):
        if type(node) not in _SAFE_NODES:
            raise FormulaError(
                f"unsafe construct in formula: {type(node).__name__}"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaError(
                    "function calls must use a plain name "
                    "(attribute access is forbidden)"
                )
            if node.func.id not in SAFE_NAMES:
                raise FormulaError(
                    f"call to '{node.func.id}' is not whitelisted"
                )
            if node.keywords:
                raise FormulaError(
                    "keyword arguments are not allowed in formula calls"
                )


# ---------------------------------------------------------------------------
# Public evaluator
# ---------------------------------------------------------------------------

def evaluate_formula(formula: str, bindings: Mapping[str, Any]) -> Any:
    """Evaluate *formula* against *bindings* and return the result.

    Parameters
    ----------
    formula : str
        Arithmetic expression. May reference any name in *bindings*
        or in :data:`SAFE_NAMES`.
    bindings : Mapping[str, Any]
        Concrete values for parameter names referenced in the formula.

    Raises
    ------
    FormulaError
        If the formula is malformed, references an unknown name, uses
        an unsafe construct, or raises at evaluation time.
    """
    if not isinstance(formula, str):
        raise FormulaError("formula must be a string")
    text = formula.strip()
    if not text:
        raise FormulaError("formula is empty")

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"formula syntax error: {exc.msg}") from None

    _check_ast_safe(tree)

    # Every Name must resolve either to a bound parameter or to a
    # whitelisted callable / constant.
    namespace: dict[str, Any] = dict(SAFE_NAMES)
    namespace.update(bindings)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in namespace:
            raise FormulaError(f"unknown name in formula: '{node.id}'")

    code = compile(tree, filename="<family-formula>", mode="eval")
    try:
        return eval(code, {"__builtins__": {}}, namespace)  # noqa: S307 (sandboxed)
    except FormulaError:
        raise
    except Exception as exc:  # ZeroDivisionError, OverflowError, ...
        raise FormulaError(f"formula evaluation error: {exc}") from None


# ---------------------------------------------------------------------------
# Dependency-graph helpers
# ---------------------------------------------------------------------------

def extract_referenced_names(formula: str) -> set[str]:
    """Return the set of identifier names referenced in *formula*,
    excluding whitelisted math callables / constants.

    This is the dependency set used for topological sorting. Returns
    an empty set on syntax errors (the actual error is surfaced later
    by :func:`evaluate_formula`).
    """
    try:
        tree = ast.parse((formula or "").strip(), mode="eval")
    except SyntaxError:
        return set()
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in SAFE_NAMES:
            refs.add(node.id)
    return refs


def topo_sort(deps: Mapping[str, Iterable[str]]) -> list[str]:
    """Topologically sort a dependency graph.

    Parameters
    ----------
    deps : Mapping[str, Iterable[str]]
        Adjacency map: each key depends on the names in its value.

    Returns
    -------
    list[str]
        Nodes in evaluation order (dependencies first).

    Raises
    ------
    CycleError
        If the graph contains a cycle. The error message lists the
        names participating in the cycle for easy debugging.
    """
    # Filter the dependency set to only nodes present in deps — external
    # references (e.g. shared parameters) don't constrain ordering here.
    pruned: dict[str, set[str]] = {
        name: {d for d in (dep_set or ()) if d in deps}
        for name, dep_set in deps.items()
    }

    in_deg: dict[str, int] = {n: 0 for n in pruned}
    rev: dict[str, list[str]] = {n: [] for n in pruned}
    for name, dep_set in pruned.items():
        for d in dep_set:
            rev[d].append(name)
            in_deg[name] += 1

    ready = [n for n, d in in_deg.items() if d == 0]
    ready.sort()  # deterministic order
    order: list[str] = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for nxt in rev.get(cur, ()):
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                ready.append(nxt)
        ready.sort()

    if len(order) != len(pruned):
        stuck = sorted(n for n, d in in_deg.items() if d > 0)
        raise CycleError(
            f"formula dependency cycle among parameters: {stuck}"
        )
    return order


# ---------------------------------------------------------------------------
# High-level parameter resolution
# ---------------------------------------------------------------------------

def resolve_parameters(
    params: Mapping[str, Any],
    overrides: Mapping[str, Any] | None = None,
    *,
    extra_bindings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a set of parameter definitions to concrete values.

    Parameters
    ----------
    params : Mapping[str, Parameter]
        Map of parameter name → :class:`kerf_bim.family.Parameter`.
        (Duck-typed: we only read ``.formula`` and ``.default``.)
    overrides : Mapping[str, Any] | None
        Caller-supplied values that take precedence over the
        parameter's default. Overrides for *formula* parameters are
        ignored — formulae always win.
    extra_bindings : Mapping[str, Any] | None
        Additional names made available to formula evaluation
        (e.g. shared parameters from the project scope). Not resolved
        themselves.

    Returns
    -------
    dict[str, Any]
        Fully-resolved name → value map.

    Raises
    ------
    CycleError
        If formula parameters form a dependency cycle.
    FormulaError
        If any formula is malformed or evaluation fails.
    """
    overrides = dict(overrides or {})
    extras = dict(extra_bindings or {})

    # Build dependency graph (only parameters with formulae produce edges).
    deps: dict[str, set[str]] = {}
    for name, p in params.items():
        if getattr(p, "formula", None):
            deps[name] = extract_referenced_names(p.formula)
        else:
            deps[name] = set()

    order = topo_sort(deps)

    resolved: dict[str, Any] = {}
    for name in order:
        p = params[name]
        formula = getattr(p, "formula", None)
        if formula:
            # Provide every already-resolved value plus extras to the
            # evaluator. Numeric coercion happens inside the formula.
            namespace = {**extras, **resolved}
            resolved[name] = evaluate_formula(formula, namespace)
        elif name in overrides:
            resolved[name] = overrides[name]
        else:
            resolved[name] = getattr(p, "default", None)
    return resolved
