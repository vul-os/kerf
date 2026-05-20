"""
kerf_systems.parser.mo_parser
==============================

Modelica-flavoured .system model parser.

Handles a strict subset of Modelica-like syntax for `.system` files:

    model <Name>
      // comment
      parameter Real <var> = <value>;
      Real <var>(start = <value>);
      ...
    equation
      der(<var>) = <expr>;
      <lhs_expr> = <rhs_expr>;
      connect(<comp>.<port>, <comp>.<port>);   // future — ignored for now
    end <Name>;

Design notes
------------
- Parser is intentionally minimal: regex + line-by-line.
- Supports multi-parameter expressions (RHS may reference earlier parameters).
- ``build_dae_problem`` converts the AST into a callable F(t, x, dx) suitable
  for ``kerf_systems.solver.dae.solve_system``.
- Does NOT implement: arrays, for-equations, if-equations, Modelica packages,
  connectors, flow variables. These are out of scope for v1.

Higher-index notes
------------------
The parser produces an index-1 DAE by relying on the model author to manually
differentiate algebraic constraints.  For higher-index systems (e.g. ideal
rigid kinematic constraints) the user must apply dummy-derivative substitution
externally or use a Pantelides pre-processing step (not implemented here).
scipy.integrate.solve_ivp with method='BDF' can handle moderate stiffness
(index ≤ 1 after manual reduction).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------

@dataclass
class VarDecl:
    """One variable or parameter declaration."""
    name: str
    is_parameter: bool = False
    start: float = 0.0
    value: float | None = None   # set for parameters


@dataclass
class Equation:
    """One equation in the equation section."""
    lhs: str
    rhs: str
    is_der: bool = False
    der_var: str = ""


@dataclass
class ParsedModel:
    """Complete parsed model AST."""
    name: str
    vars: list[VarDecl] = field(default_factory=list)
    equations: list[Equation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_MODEL    = re.compile(r'^\s*model\s+(\w+)', re.IGNORECASE)
_RE_END      = re.compile(r'^\s*end\s+\w+\s*;', re.IGNORECASE)
_RE_PARAM    = re.compile(
    r'^\s*parameter\s+Real\s+(\w+)\s*=\s*([^;]+?)\s*;', re.IGNORECASE)
_RE_VAR      = re.compile(
    r'^\s*Real\s+(\w+)(?:\s*\(\s*start\s*=\s*([^)]+?)\s*\))?\s*;',
    re.IGNORECASE)
_RE_DER_EQ   = re.compile(
    r'^\s*der\s*\(\s*(\w+)\s*\)\s*=\s*(.+?)\s*;', re.IGNORECASE)
_RE_EQ       = re.compile(r'^\s*([^=]+?)\s*=\s*([^=;]+?)\s*;')
_RE_EQUATION = re.compile(r'^\s*equation\b', re.IGNORECASE)
_RE_CONNECT  = re.compile(r'^\s*connect\s*\(', re.IGNORECASE)
_RE_COMMENT  = re.compile(r'//.*$')


def _strip(line: str) -> str:
    """Strip inline comments and surrounding whitespace."""
    return _RE_COMMENT.sub("", line).strip()


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

_SAFE_NAMES: dict[str, Any] = {
    "exp": math.exp, "log": math.log, "sqrt": math.sqrt,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2,
    "abs": abs, "pi": math.pi, "e": math.e,
}


def _eval_expr(expr: str, env: dict[str, float]) -> float:
    """
    Evaluate a simple numeric expression in a restricted namespace.

    Supports Python-style operators; Modelica ``^`` is translated to ``**``.
    """
    expr = expr.replace("^", "**")
    ns = {**_SAFE_NAMES, **env}
    try:
        return float(eval(expr, {"__builtins__": {}}, ns))  # noqa: S307
    except Exception as exc:
        raise ValueError(f"Cannot evaluate {expr!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# Public: parse_model
# ---------------------------------------------------------------------------

def parse_model(source: str) -> ParsedModel:
    """
    Parse a Modelica-flavoured .system model source string.

    Parameters
    ----------
    source : str
        Model source text.

    Returns
    -------
    ParsedModel

    Raises
    ------
    ValueError
        If no ``model <Name>`` declaration is found.
    """
    lines = source.splitlines()
    model_name: str | None = None
    vars_: list[VarDecl] = []
    equations_: list[Equation] = []
    in_equation_section = False

    for raw_line in lines:
        line = _strip(raw_line)
        if not line:
            continue

        if model_name is None:
            m = _RE_MODEL.match(line)
            if m:
                model_name = m.group(1)
            continue

        if _RE_END.match(line):
            break

        if _RE_EQUATION.match(line):
            in_equation_section = True
            continue

        if not in_equation_section:
            # Variable / parameter declarations
            mp = _RE_PARAM.match(line)
            if mp:
                name = mp.group(1)
                val_str = mp.group(2).strip()
                # Evaluate value with previously seen parameters
                param_env = {v.name: v.value for v in vars_ if v.is_parameter}
                val = _eval_expr(val_str, param_env)
                vars_.append(VarDecl(name=name, is_parameter=True, value=val, start=val))
                continue
            mv = _RE_VAR.match(line)
            if mv:
                start_str = mv.group(2)
                if start_str:
                    param_env = {v.name: v.value for v in vars_ if v.is_parameter}
                    start_val = _eval_expr(start_str.strip(), param_env)
                else:
                    start_val = 0.0
                vars_.append(VarDecl(name=mv.group(1), start=start_val))
                continue
        else:
            # Equation section
            if _RE_CONNECT.match(line):
                # connect() statements are recorded but not yet processed
                continue
            md = _RE_DER_EQ.match(line)
            if md:
                equations_.append(Equation(
                    lhs=f"der({md.group(1)})",
                    rhs=md.group(2).strip(),
                    is_der=True,
                    der_var=md.group(1),
                ))
                continue
            meq = _RE_EQ.match(line)
            if meq:
                equations_.append(Equation(
                    lhs=meq.group(1).strip(),
                    rhs=meq.group(2).strip(),
                ))
                continue

    if model_name is None:
        raise ValueError("No 'model <Name>' declaration found in source.")

    return ParsedModel(name=model_name, vars=vars_, equations=equations_)


# ---------------------------------------------------------------------------
# Public: build_dae_problem
# ---------------------------------------------------------------------------

def build_dae_problem(model: ParsedModel):
    """
    Convert a ``ParsedModel`` into a DAE residual function.

    Returns
    -------
    F : callable(t, x, dx) -> list[float]
        DAE residual vector.  F(t, x, dx) == 0 at every consistent state.
    x0 : list[float]
        Initial values from ``start`` attributes.
    dx0 : list[float]
        Initial derivatives (zeros).
    var_names : list[str]
        Names of the state/algebraic variables (parameters excluded).
    params : dict[str, float]
        Parameter name → value.

    Notes on index reduction
    ------------------------
    The function returns an index-1 DAE suitable for BDF solvers.
    Higher-index constraints (e.g. ideal rigid contact) must be manually
    differentiated before calling ``parse_model``.  For typical thermal /
    electrical / hydraulic / control networks the equations are naturally
    index 1 or semi-explicit ODE form.
    """
    params: dict[str, float] = {
        v.name: float(v.value)  # type: ignore[arg-type]
        for v in model.vars
        if v.is_parameter
    }
    state_vars = [v for v in model.vars if not v.is_parameter]
    var_names = [v.name for v in state_vars]
    x0 = [v.start for v in state_vars]
    dx0 = [0.0] * len(state_vars)

    equations = model.equations

    def F(t: float, x: list[float], dx: list[float]) -> list[float]:
        env: dict[str, float] = {"t": t, **params}
        for name, val in zip(var_names, x):
            env[name] = val
        # der(x) references
        for name, dval in zip(var_names, dx):
            env[f"der_{name}"] = dval

        residuals = []
        for eq in equations:
            if eq.is_der:
                idx = var_names.index(eq.der_var)
                rhs_val = _eval_expr(eq.rhs, env)
                residuals.append(dx[idx] - rhs_val)
            else:
                lhs_val = _eval_expr(eq.lhs, env)
                rhs_val = _eval_expr(eq.rhs, env)
                residuals.append(lhs_val - rhs_val)

        return residuals

    return F, x0, dx0, var_names, params
