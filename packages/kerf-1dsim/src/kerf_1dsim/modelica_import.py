"""
kerf_1dsim.modelica_import
==========================

Modelica .mo file import — subset parser and kerf-1dsim bridge.

IMPORTANT CAVEAT
----------------
This implements a *Modelica subset*, NOT certified Modelica compliance.
The parser covers the constructs most common in introductory / textbook models:
  - model … end …  blocks
  - parameter Real x = 1.0;
  - Real y;  /  Real y(start=0.0);
  - equation   …   sections
  - der(x) = rhs;
  - connect(a.port, b.port);
  - algebraic equations: lhs = rhs;
  - package … end …  blocks (one level deep; inner models collected)
  - Line comments  //  and block comments  /* … */

Constructs deliberately NOT supported (would require a full Modelica compiler):
  - Inheritance / extends
  - Redeclaration, replaceable
  - Flow / stream connectors (topology equations)
  - Conditional components
  - Arrays & records beyond trivial scalars
  - Algorithm sections

Public API
----------
  parse_modelica_file(file_path) -> ModelicaModel
  parse_modelica_source(source)  -> ModelicaModel
  modelica_to_kerf_components(modelica_model) -> list[Component]
  load_modelica_library(library_path) -> dict[str, ModelicaModel]
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any


# ===========================================================================
# Data model
# ===========================================================================

@dataclass
class ModelicaParameter:
    """A ``parameter Real`` declaration."""
    name: str
    value: float
    unit: str = ""
    description: str = ""


@dataclass
class ModelicaVariable:
    """A state / algebraic variable declaration."""
    name: str
    start: float = 0.0
    unit: str = ""
    description: str = ""


@dataclass
class ModelicaComponent:
    """An instance declaration inside a model (e.g. ``Resistor R1(R=100);``)."""
    type_name: str    # e.g. "Resistor", "Modelica.Electrical.Analog.Basic.Resistor"
    instance_name: str   # e.g. "R1"
    modifications: dict[str, float] = field(default_factory=dict)


@dataclass
class ModelicaEquation:
    """One equation in the equation section."""
    lhs: str
    rhs: str
    is_der: bool = False
    der_var: str = ""
    is_connect: bool = False
    connect_a: str = ""
    connect_b: str = ""


@dataclass
class ModelicaModel:
    """
    Parsed representation of one Modelica model block.

    Subset support — see module docstring for caveats.
    """
    name: str
    package: str = ""                                     # enclosing package name, if any
    parameters: list[ModelicaParameter] = field(default_factory=list)
    variables: list[ModelicaVariable] = field(default_factory=list)
    components: list[ModelicaComponent] = field(default_factory=list)
    equations: list[ModelicaEquation] = field(default_factory=list)

    # Convenience: resolved connect pairs  (instance_a.port, instance_b.port)
    connections: list[tuple[str, str]] = field(default_factory=list)

    def parameter_dict(self) -> dict[str, float]:
        return {p.name: p.value for p in self.parameters}

    def variable_names(self) -> list[str]:
        return [v.name for v in self.variables]


# ===========================================================================
# Tokeniser / pre-processor
# ===========================================================================

def _strip_comments(source: str) -> str:
    """Remove // line comments and /* block */ comments."""
    # Block comments first (non-greedy)
    source = re.sub(r'/\*.*?\*/', ' ', source, flags=re.DOTALL)
    # Line comments
    source = re.sub(r'//[^\n]*', '', source)
    return source


# Individual regex patterns
_RE_PACKAGE_START = re.compile(r'^\s*package\s+(\w+)', re.IGNORECASE)
_RE_PACKAGE_END   = re.compile(r'^\s*end\s+(\w+)\s*;', re.IGNORECASE)
_RE_MODEL_START   = re.compile(r'^\s*model\s+(\w+)', re.IGNORECASE)
_RE_EQUATION_SEC  = re.compile(r'^\s*equation\b', re.IGNORECASE)

_RE_PARAM = re.compile(
    r'^\s*parameter\s+Real\s+(\w+)'
    r'(?:\s*\([^)]*\))?'           # optional modifier list (unit, etc.) — ignored
    r'\s*=\s*([\d.eE+\-]+)\s*;',
    re.IGNORECASE,
)
_RE_VAR = re.compile(
    r'^\s*Real\s+(\w+)'
    r'(?:\s*\(\s*start\s*=\s*([\d.eE+\-]+)[^)]*\))?\s*;',
    re.IGNORECASE,
)
# Component instance:  TypeName instanceName(param=val, ...);
_RE_COMPONENT = re.compile(
    r'^\s*([A-Z]\w*(?:\.\w+)*)\s+(\w+)'
    r'(?:\s*\(([^)]*)\))?\s*;',
)
_RE_DER_EQ = re.compile(
    r'^\s*der\s*\(\s*(\w+)\s*\)\s*=\s*(.+?)\s*;',
    re.IGNORECASE,
)
_RE_CONNECT = re.compile(
    r'^\s*connect\s*\(\s*([\w.]+)\s*,\s*([\w.]+)\s*\)\s*;',
    re.IGNORECASE,
)
_RE_PLAIN_EQ = re.compile(r'^\s*(.+?)\s*=\s*(.+?)\s*;')


def _parse_modifications(mod_str: str) -> dict[str, float]:
    """Parse  param=val, param2=val2  into a dict."""
    result: dict[str, float] = {}
    if not mod_str:
        return result
    for part in mod_str.split(','):
        part = part.strip()
        m = re.match(r'(\w+)\s*=\s*([\d.eE+\-]+)', part)
        if m:
            try:
                result[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return result


# ===========================================================================
# Core parser
# ===========================================================================

def parse_modelica_source(source: str) -> ModelicaModel:
    """
    Parse Modelica subset from a source string.

    Returns the *first* model found at top level or inside a package block.
    Raises ValueError if no model declaration is found.
    """
    clean = _strip_comments(source)
    lines = clean.splitlines()

    # Two-pass approach: find outermost model block
    # We track nesting depth using begin/end keywords.
    models: list[ModelicaModel] = []
    _collect_models(lines, models, package_name="")

    if not models:
        raise ValueError("No 'model <Name>' declaration found in source.")

    # Return the first model found
    return models[0]


def _collect_models(
    lines: list[str],
    out: list[ModelicaModel],
    package_name: str,
    start: int = 0,
) -> int:
    """
    Scan lines from *start* and collect all model blocks.
    Returns the index of the line AFTER the closing 'end <pkg>;'.
    """
    i = start
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        # Skip blank lines
        if not line:
            i += 1
            continue

        # Package block
        mp = _RE_PACKAGE_START.match(line)
        if mp:
            pkg = mp.group(1)
            i = _collect_models(lines, out, package_name=pkg, start=i + 1)
            continue

        # Model block
        mm = _RE_MODEL_START.match(line)
        if mm:
            model_name = mm.group(1)
            model, i = _parse_model_block(lines, i + 1, model_name, package_name)
            out.append(model)
            continue

        # End of enclosing package
        me = _RE_PACKAGE_END.match(line)
        if me:
            return i + 1

        i += 1

    return i


def _parse_model_block(
    lines: list[str],
    start: int,
    model_name: str,
    package_name: str,
) -> tuple[ModelicaModel, int]:
    """
    Parse model body starting at *start* (the line after 'model Foo').
    Returns (ModelicaModel, next_line_index).
    """
    model = ModelicaModel(name=model_name, package=package_name)
    i = start
    n = len(lines)
    in_equation = False

    while i < n:
        line = lines[i].strip()
        i += 1

        if not line:
            continue

        # End of model block
        me = _RE_PACKAGE_END.match(line)
        if me:
            break

        # Switch to equation section
        if _RE_EQUATION_SEC.match(line):
            in_equation = True
            continue

        if not in_equation:
            # --- Variable/component declaration section ---

            # parameter Real
            mp = _RE_PARAM.match(line)
            if mp:
                model.parameters.append(ModelicaParameter(
                    name=mp.group(1),
                    value=float(mp.group(2)),
                ))
                continue

            # Real variable
            mv = _RE_VAR.match(line)
            if mv:
                start_val = float(mv.group(2)) if mv.group(2) else 0.0
                model.variables.append(ModelicaVariable(
                    name=mv.group(1),
                    start=start_val,
                ))
                continue

            # Component instance (type starts with uppercase)
            mc = _RE_COMPONENT.match(line)
            if mc:
                mods = _parse_modifications(mc.group(3) or "")
                model.components.append(ModelicaComponent(
                    type_name=mc.group(1),
                    instance_name=mc.group(2),
                    modifications=mods,
                ))
                continue

        else:
            # --- Equation section ---

            # connect(a, b)
            mconn = _RE_CONNECT.match(line)
            if mconn:
                a, b = mconn.group(1), mconn.group(2)
                eq = ModelicaEquation(
                    lhs="", rhs="",
                    is_connect=True,
                    connect_a=a,
                    connect_b=b,
                )
                model.equations.append(eq)
                model.connections.append((a, b))
                continue

            # der(x) = rhs
            md = _RE_DER_EQ.match(line)
            if md:
                model.equations.append(ModelicaEquation(
                    lhs=f"der({md.group(1)})",
                    rhs=md.group(2),
                    is_der=True,
                    der_var=md.group(1),
                ))
                continue

            # plain equation
            meq = _RE_PLAIN_EQ.match(line)
            if meq:
                model.equations.append(ModelicaEquation(
                    lhs=meq.group(1),
                    rhs=meq.group(2),
                ))
                continue

    return model, i


# ===========================================================================
# File-level entry points
# ===========================================================================

def parse_modelica_file(file_path: str) -> ModelicaModel:
    """
    Parse a Modelica .mo file and return the first model found.

    Parameters
    ----------
    file_path : str
        Absolute or relative path to the .mo file.

    Returns
    -------
    ModelicaModel

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If no model block is found.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Modelica file not found: {file_path!r}")
    with open(file_path, encoding="utf-8") as fh:
        source = fh.read()
    return parse_modelica_source(source)


def load_modelica_library(library_path: str) -> dict[str, ModelicaModel]:
    """
    Load a directory of .mo files as a library.

    Recursively scans *library_path* for ``*.mo`` files and parses each one.
    The returned dict maps model name → ModelicaModel.  When a package
    structure is detected (package.mo at the root) the dict key is the
    qualified name ``Package.ModelName``.

    Parameters
    ----------
    library_path : str
        Path to the library directory.

    Returns
    -------
    dict[str, ModelicaModel]
        {qualified_model_name: ModelicaModel}
    """
    if not os.path.isdir(library_path):
        raise NotADirectoryError(f"Library path is not a directory: {library_path!r}")

    library: dict[str, ModelicaModel] = {}

    for root, _dirs, files in os.walk(library_path):
        for fname in sorted(files):
            if not fname.endswith(".mo"):
                continue
            fpath = os.path.join(root, fname)
            try:
                model = parse_modelica_file(fpath)
            except (ValueError, UnicodeDecodeError):
                # Skip files that don't contain a parseable model
                continue
            # Build a qualified key: strip library_path prefix → relative path
            rel = os.path.relpath(fpath, library_path)
            parts = rel.replace(os.sep, "/").split("/")
            # Drop filename, use package hierarchy + model name
            # e.g.  Electrical/Analog/Basic/Resistor.mo → Electrical.Analog.Basic.Resistor
            key_parts = [p[:-3] if p.endswith(".mo") else p for p in parts]
            qualified = ".".join(key_parts)
            if model.package:
                key = f"{model.package}.{model.name}"
            else:
                key = model.name
            library[key] = model

    return library


# ===========================================================================
# Mapping Modelica component names → kerf-1dsim Component classes
# ===========================================================================

# Canonical Modelica Standard Library (MSL) paths and common short names
# mapped to (kerf_class_name, primary_param).
# primary_param: the MSL parameter name used to set the single numeric param.

_MODELICA_COMPONENT_MAP: dict[str, tuple[str, str]] = {
    # Electrical analog
    "Resistor": ("Resistor", "R"),
    "Modelica.Electrical.Analog.Basic.Resistor": ("Resistor", "R"),
    "Capacitor": ("Capacitor", "C"),
    "Modelica.Electrical.Analog.Basic.Capacitor": ("Capacitor", "C"),
    "Inductor": ("Inductor", "L"),
    "Modelica.Electrical.Analog.Basic.Inductor": ("Inductor", "L"),
    # Mechanical translational
    "Mass": ("MassSpring", "m"),
    "Modelica.Mechanics.Translational.Components.Mass": ("MassSpring", "m"),
    "Spring": ("MassSpring", "k"),
    "Modelica.Mechanics.Translational.Components.Spring": ("MassSpring", "k"),
    "Damper": ("Damper", "d"),
    "Modelica.Mechanics.Translational.Components.Damper": ("Damper", "d"),
    # Thermal
    "ThermalConductor": ("ThermalConductor", "G"),
    "Modelica.Thermal.HeatTransfer.Components.ThermalConductor": ("ThermalConductor", "G"),
    # Fluid (linearised)
    "Pipe": ("FluidResistor", "R"),
    "FluidResistor": ("FluidResistor", "R"),
}

# Default parameter values used when the .mo file provides no modification
_DEFAULT_PARAM: dict[str, float] = {
    "Resistor": 1.0,
    "Capacitor": 1e-6,
    "Inductor": 1e-3,
    "MassSpring": 1.0,
    "Damper": 1.0,
    "ThermalConductor": 1.0,
    "FluidResistor": 1e6,
}


def modelica_to_kerf_components(modelica_model: ModelicaModel) -> list[Any]:
    """
    Convert a ``ModelicaModel`` to a list of kerf-1dsim ``Component`` instances.

    Mapping strategy
    ----------------
    1.  For each ``ModelicaComponent`` in ``modelica_model.components``:
        - Look up the type name in ``_MODELICA_COMPONENT_MAP``.
        - Extract the primary parameter value from ``modifications``,
          falling back to the default.
        - Instantiate the corresponding kerf-1dsim class.
    2.  If the model contains no ``components`` (e.g. it was written with
        explicit equations instead of component instances), we attempt a
        heuristic mapping from the ``parameters`` list using parameter
        names (R, C, L, m, k, b, G, Rf).

    Returns
    -------
    list[Component]
        Native kerf-1dsim component instances.  Components whose type
        cannot be mapped are silently skipped (only a best-effort subset).
    """
    from kerf_1dsim.components import (
        Resistor, Capacitor, Inductor,
        MassSpring, Damper,
        ThermalConductor, FluidResistor,
    )

    _BUILDERS = {
        "Resistor":         lambda p: Resistor(R=p),
        "Capacitor":        lambda p: Capacitor(C=p),
        "Inductor":         lambda p: Inductor(L=p),
        "MassSpring":       lambda p: MassSpring(m=p, k=1.0),
        "Damper":           lambda p: Damper(b=p),
        "ThermalConductor": lambda p: ThermalConductor(G=p),
        "FluidResistor":    lambda p: FluidResistor(Rf=p),
    }

    result = []

    if modelica_model.components:
        for comp in modelica_model.components:
            mapping = _MODELICA_COMPONENT_MAP.get(comp.type_name)
            if mapping is None:
                # Try stripping trailing qualified parts
                short = comp.type_name.split(".")[-1]
                mapping = _MODELICA_COMPONENT_MAP.get(short)
            if mapping is None:
                continue  # unknown type — skip

            kerf_class, primary_key = mapping
            # Look up param value in modifications dict
            param_val = comp.modifications.get(primary_key)
            if param_val is None:
                # Fall back to common param name variants
                for k in comp.modifications:
                    if k.lower() in (primary_key.lower(), "value"):
                        param_val = comp.modifications[k]
                        break
            if param_val is None:
                param_val = _DEFAULT_PARAM.get(kerf_class, 1.0)

            builder = _BUILDERS.get(kerf_class)
            if builder is not None:
                try:
                    result.append(builder(param_val))
                except ValueError:
                    pass

    else:
        # Heuristic: look for recognisable parameter names
        params = modelica_model.parameter_dict()
        if "R" in params:
            try:
                result.append(Resistor(R=params["R"]))
            except ValueError:
                pass
        if "C" in params:
            try:
                result.append(Capacitor(C=params["C"]))
            except ValueError:
                pass
        if "L" in params:
            try:
                result.append(Inductor(L=params["L"]))
            except ValueError:
                pass
        if "m" in params and "k" in params:
            try:
                result.append(MassSpring(m=params["m"], k=params["k"]))
            except ValueError:
                pass
        if "b" in params:
            try:
                result.append(Damper(b=params["b"]))
            except ValueError:
                pass
        if "G" in params:
            try:
                result.append(ThermalConductor(G=params["G"]))
            except ValueError:
                pass
        if "Rf" in params:
            try:
                result.append(FluidResistor(Rf=params["Rf"]))
            except ValueError:
                pass

    return result
