"""
kerf_1dsim.fmi_export
=====================

FMI 2.0 model export for kerf-1dsim.

Generates Functional Mock-up Unit (.fmu) archives from SimModel descriptors.
An FMU is a ZIP archive containing:

  - ``modelDescription.xml``  — scalar variable list, model structure,
                                 CoSimulation or ModelExchange element
  - ``sources/model.c``        — C source wrapper (textual, not compiled;
                                  the FMU is a "source-code FMU")

This implementation targets the FMI 2.0 specification (fmi-standard.org).

DISCLAIMER: FMI 2.0 export subset — NOT FMI Cross-Check certified.
The generated .fmu passes the structural compliance checks implemented here
(valid XML, required attributes, correct causality/variability mapping) but
has not been submitted to or validated against the official FMI Cross-Check
test suite. Interoperability with specific tools (Dymola, OpenModelica,
MATLAB/Simulink) is expected for source-code FMUs but is not guaranteed
without a compiled binary.

Public API
----------
    export_fmu(model, path, fmi_version='2.0', fmu_kind='cs') -> str
    generate_model_description_xml(model) -> str
    validate_fmu(fmu_path) -> ValidationResult

SimModel — lightweight descriptor used by fmi_export
-----------------------------------------------------
    SimModel is a dataclass whose fields map onto the modelDescription.xml
    elements required by FMI 2.0 §2.2.

    Fields
    ------
    name : str
        Model name (used as modelIdentifier and modelName).
    guid : str
        GUID string, e.g. ``"{8c4e810f-3df3-4a00-8276-176fa3c9f003}"``.
    description : str
        Free-text description embedded in modelDescription.xml.
    variables : list[FMIVariable]
        All scalar variables (inputs, outputs, state vars, parameters).
    state_variables : list[str]
        Names of continuous state variables (subset of variables).
    parameters : dict[str, float]
        Parameter name → default value.
    author : str
        Optional author string.
    version : str
        Model version string.

FMIVariable
-----------
    name        : str
    causality   : 'input'|'output'|'local'|'parameter'|'calculatedParameter'
    variability : 'continuous'|'discrete'|'fixed'|'tunable'|'constant'
    initial     : 'exact'|'approx'|'calculated'|None
    start       : float|None   — start / default value
    value_ref   : int          — valueReference (0-based index)
    description : str
    unit        : str|None

References
----------
  FMI 2.0.4 specification: https://fmi-standard.org/docs/2.0.4/
  §2.2   modelDescription.xml schema
  §3     Model Exchange interface
  §4     Co-Simulation interface
"""

from __future__ import annotations

import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

_FMICausality = Literal["input", "output", "local", "parameter", "calculatedParameter"]
_FMIVariability = Literal["continuous", "discrete", "fixed", "tunable", "constant"]
_FMIInitial = Literal["exact", "approx", "calculated"]


@dataclass
class FMIVariable:
    """One scalar variable as described in FMI 2.0 §2.2.7."""
    name: str
    causality: _FMICausality = "local"
    variability: _FMIVariability = "continuous"
    initial: _FMIInitial | None = None
    start: float | None = None
    value_ref: int = 0
    description: str = ""
    unit: str | None = None


@dataclass
class SimModel:
    """
    Lightweight descriptor of a simulation model for FMI export.

    This is intentionally minimal — it carries just what is needed to build
    a compliant modelDescription.xml.  It does NOT require a solver or
    equations callable; those live in ``kerf_1dsim.solver``.
    """
    name: str
    guid: str = ""
    description: str = ""
    variables: list[FMIVariable] = field(default_factory=list)
    state_variables: list[str] = field(default_factory=list)
    parameters: dict[str, float] = field(default_factory=dict)
    author: str = "kerf-1dsim"
    version: str = "0.1"

    def __post_init__(self):
        # Auto-assign a deterministic GUID if none given
        if not self.guid:
            raw = f"{self.name}-{self.version}-{self.author}"
            h = hashlib.md5(raw.encode()).hexdigest()  # noqa: S324
            self.guid = (
                f"{{{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}}}"
            )


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of validate_fmu()."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "VALID" if self.valid else "INVALID"
        lines = [f"FMU validation: {status}"]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# modelDescription.xml builder  (FMI 2.0 §2.2)
# ---------------------------------------------------------------------------

def generate_model_description_xml(
    model: SimModel,
    fmu_kind: Literal["cs", "me"] = "cs",
) -> str:
    """
    Build a conformant modelDescription.xml string for FMI 2.0.

    Parameters
    ----------
    model : SimModel
    fmu_kind : 'cs' | 'me'
        'cs' — CoSimulation element; 'me' — ModelExchange element.

    Returns
    -------
    str
        UTF-8 XML text (with XML declaration).

    Notes
    -----
    Variable ordering follows the FMI 2.0 convention:
        - parameters   (causality="parameter", variability="fixed"|"tunable")
        - inputs       (causality="input")
        - outputs      (causality="output")
        - state vars   (causality="local", variability="continuous")
        - local/other  (remainder)
    """
    root = ET.Element("fmiModelDescription")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("fmiVersion", "2.0")
    root.set("modelName", model.name)
    root.set("guid", model.guid)
    root.set("description", model.description)
    root.set("author", model.author)
    root.set("version", model.version)
    root.set("generationTool", "kerf-1dsim")
    root.set("generationDateAndTime", "2026-01-01T00:00:00Z")
    root.set("variableNamingConvention", "flat")
    root.set(
        "numberOfEventIndicators",
        str(len(model.state_variables)),
    )

    # ---- CoSimulation or ModelExchange capability element ----
    if fmu_kind == "cs":
        cap = ET.SubElement(root, "CoSimulation")
        cap.set("modelIdentifier", _safe_identifier(model.name))
        cap.set("canHandleVariableCommunicationStepSize", "true")
        cap.set("canInterpolateInputs", "false")
        cap.set("maxOutputDerivativeOrder", "0")
        cap.set("canRunAsynchronuously", "false")
        cap.set("canBeInstantiatedOnlyOncePerProcess", "false")
        cap.set("canNotUseMemoryManagementFunctions", "false")
        cap.set("canGetAndSetFMUstate", "false")
        cap.set("canSerializeFMUstate", "false")
        cap.set("providesDirectionalDerivative", "false")
    else:
        cap = ET.SubElement(root, "ModelExchange")
        cap.set("modelIdentifier", _safe_identifier(model.name))
        cap.set("canGetAndSetFMUstate", "false")
        cap.set("canSerializeFMUstate", "false")
        cap.set("providesDirectionalDerivative", "false")

    # ---- LogCategories ----
    log_cats = ET.SubElement(root, "LogCategories")
    for cat_name in ("logStatusWarning", "logStatusError", "logStatusFatal",
                     "logStatusPending", "logAll"):
        c = ET.SubElement(log_cats, "Category")
        c.set("name", cat_name)

    # ---- ModelVariables (FMI 2.0 §2.2.7) ----
    mvars = ET.SubElement(root, "ModelVariables")

    # Sort: parameters first, then inputs, outputs, states, locals
    priority_order = {
        "parameter": 0,
        "calculatedParameter": 1,
        "input": 2,
        "output": 3,
        "local": 4,
    }
    sorted_vars = sorted(
        model.variables,
        key=lambda v: (priority_order.get(v.causality, 5), v.name),
    )

    for var in sorted_vars:
        sv = ET.SubElement(mvars, "ScalarVariable")
        sv.set("name", var.name)
        sv.set("valueReference", str(var.value_ref))
        if var.description:
            sv.set("description", var.description)
        sv.set("causality", var.causality)
        sv.set("variability", var.variability)

        # Resolve 'initial' per FMI 2.0 Table 13 defaults if not set
        initial = var.initial or _default_initial(var.causality, var.variability)
        if initial is not None:
            sv.set("initial", initial)

        # Real child element (FMI 2.0 only supports Real/Integer/Boolean/String;
        # we emit Real for all numeric variables)
        real_el = ET.SubElement(sv, "Real")
        if var.unit:
            real_el.set("unit", var.unit)
        if var.start is not None:
            real_el.set("start", _fmt_float(var.start))

    # ---- ModelStructure (FMI 2.0 §2.2.8) ----
    #
    # Required sub-elements: Outputs, Derivatives, InitialUnknowns
    # Outputs lists indices (1-based) into ModelVariables.
    # Derivatives lists indices of ContinuousState derivative declarations.

    ms = ET.SubElement(root, "ModelStructure")

    # Build index map (1-based) for sorted_vars
    var_index = {v.name: i + 1 for i, v in enumerate(sorted_vars)}

    # Outputs
    outputs_el = ET.SubElement(ms, "Outputs")
    for i, v in enumerate(sorted_vars):
        if v.causality == "output":
            uk = ET.SubElement(outputs_el, "Unknown")
            uk.set("index", str(i + 1))
            uk.set("dependencies", "")

    # Derivatives — one entry per continuous state variable (derivative = index+1
    # in a correctly built model that also has a der(x) local variable).
    derivs_el = ET.SubElement(ms, "Derivatives")
    for state_name in model.state_variables:
        der_name = f"der({state_name})"
        if der_name in var_index:
            uk = ET.SubElement(derivs_el, "Unknown")
            uk.set("index", str(var_index[der_name]))
            uk.set("dependencies", "")
        elif state_name in var_index:
            # Fallback: reference the state variable itself
            uk = ET.SubElement(derivs_el, "Unknown")
            uk.set("index", str(var_index[state_name]))
            uk.set("dependencies", "")

    # InitialUnknowns
    iu_el = ET.SubElement(ms, "InitialUnknowns")
    for i, v in enumerate(sorted_vars):
        if v.initial in ("approx", "calculated"):
            uk = ET.SubElement(iu_el, "Unknown")
            uk.set("index", str(i + 1))
            uk.set("dependencies", "")

    return _to_xml_string(root)


# ---------------------------------------------------------------------------
# C source wrapper generator
# ---------------------------------------------------------------------------

_C_TEMPLATE = """\
/*
 * FMI 2.0 source-code wrapper — generated by kerf-1dsim
 * Model: {model_name}
 * GUID : {guid}
 * Kind : {fmu_kind}
 *
 * DISCLAIMER: FMI 2.0 export subset — NOT FMI Cross-Check certified.
 *
 * This file provides the FMI 2.0 API stubs so that a compliant FMI importer
 * can compile a platform binary.  The actual numerical integration uses the
 * kerf-1dsim Python DAE solver via Python/C API or ctypes; a full C
 * integration kernel is left to the downstream build chain.
 */

#define MODEL_IDENTIFIER  {model_identifier}
#define FMI_VERSION       "2.0"
#define MODEL_GUID        "{guid}"
#define N_STATES          {n_states}
#define N_INPUTS          {n_inputs}
#define N_OUTPUTS         {n_outputs}

#include <stddef.h>
#include <string.h>

/* fmi2TypesPlatform.h (inline) */
typedef double       fmi2Real;
typedef int          fmi2Integer;
typedef int          fmi2Boolean;
typedef char*        fmi2String;
typedef void*        fmi2Component;
typedef unsigned int fmi2ValueReference;
typedef void*        fmi2ComponentEnvironment;
typedef void*        fmi2FMUstate;
typedef void*        fmi2Byte;

#define fmi2True  1
#define fmi2False 0

typedef enum {{
    fmi2OK = 0,
    fmi2Warning,
    fmi2Discard,
    fmi2Error,
    fmi2Fatal,
    fmi2Pending
}} fmi2Status;

/* Minimal stub implementations — replace with a proper C solver or
   Python embedding for production use. */

fmi2Component fmi2Instantiate(
    fmi2String instanceName, int fmuType, fmi2String fmuGUID,
    fmi2String fmuResourceLocation, const void* functions,
    fmi2Boolean visible, fmi2Boolean loggingOn)
{{
    (void)instanceName; (void)fmuType; (void)fmuGUID;
    (void)fmuResourceLocation; (void)functions;
    (void)visible; (void)loggingOn;
    return (fmi2Component)1;  /* non-null placeholder */
}}

fmi2Status fmi2SetupExperiment(
    fmi2Component c, fmi2Boolean toleranceDefined, fmi2Real tolerance,
    fmi2Real startTime, fmi2Boolean stopTimeDefined, fmi2Real stopTime)
{{
    (void)c; (void)toleranceDefined; (void)tolerance;
    (void)startTime; (void)stopTimeDefined; (void)stopTime;
    return fmi2OK;
}}

fmi2Status fmi2EnterInitializationMode(fmi2Component c) {{ (void)c; return fmi2OK; }}
fmi2Status fmi2ExitInitializationMode(fmi2Component c)  {{ (void)c; return fmi2OK; }}
fmi2Status fmi2Terminate(fmi2Component c)               {{ (void)c; return fmi2OK; }}
void       fmi2FreeInstance(fmi2Component c)            {{ (void)c; }}

fmi2Status fmi2GetReal(
    fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2Real val[])
{{
    (void)c;
    for (size_t i = 0; i < nvr; ++i) val[i] = 0.0;
    return fmi2OK;
}}

fmi2Status fmi2SetReal(
    fmi2Component c, const fmi2ValueReference vr[], size_t nvr,
    const fmi2Real val[])
{{
    (void)c; (void)vr; (void)nvr; (void)val;
    return fmi2OK;
}}

/* Co-Simulation step (no-op stub) */
fmi2Status fmi2DoStep(
    fmi2Component c, fmi2Real currentCommunicationPoint,
    fmi2Real communicationStepSize, fmi2Boolean noSetFMUStatePriorToCurrentPoint)
{{
    (void)c; (void)currentCommunicationPoint;
    (void)communicationStepSize; (void)noSetFMUStatePriorToCurrentPoint;
    return fmi2OK;
}}

/* ModelExchange: continuous-time step (no-op stub) */
fmi2Status fmi2SetTime(fmi2Component c, fmi2Real time)
{{
    (void)c; (void)time;
    return fmi2OK;
}}

fmi2Status fmi2GetDerivatives(
    fmi2Component c, fmi2Real derivatives[], size_t nx)
{{
    (void)c;
    for (size_t i = 0; i < nx; ++i) derivatives[i] = 0.0;
    return fmi2OK;
}}

fmi2Status fmi2GetContinuousStates(
    fmi2Component c, fmi2Real x[], size_t nx)
{{
    (void)c;
    for (size_t i = 0; i < nx; ++i) x[i] = 0.0;
    return fmi2OK;
}}

fmi2Status fmi2SetContinuousStates(
    fmi2Component c, const fmi2Real x[], size_t nx)
{{
    (void)c; (void)x; (void)nx;
    return fmi2OK;
}}

fmi2Status fmi2CompletedIntegratorStep(
    fmi2Component c, fmi2Boolean noSetFMUStatePriorToCurrentPoint,
    fmi2Boolean* enterEventMode, fmi2Boolean* terminateSimulation)
{{
    (void)c; (void)noSetFMUStatePriorToCurrentPoint;
    if (enterEventMode)      *enterEventMode      = fmi2False;
    if (terminateSimulation) *terminateSimulation = fmi2False;
    return fmi2OK;
}}

const char* fmi2GetTypesPlatform(void)  {{ return "default"; }}
const char* fmi2GetVersion(void)        {{ return "2.0"; }}
"""


def _generate_c_source(model: SimModel, fmu_kind: str) -> str:
    n_states = len(model.state_variables)
    n_inputs = sum(1 for v in model.variables if v.causality == "input")
    n_outputs = sum(1 for v in model.variables if v.causality == "output")
    return _C_TEMPLATE.format(
        model_name=model.name,
        guid=model.guid,
        fmu_kind=fmu_kind,
        model_identifier=_safe_identifier(model.name),
        n_states=n_states,
        n_inputs=n_inputs,
        n_outputs=n_outputs,
    )


# ---------------------------------------------------------------------------
# export_fmu
# ---------------------------------------------------------------------------

def export_fmu(
    model: SimModel,
    path: str,
    fmi_version: str = "2.0",
    fmu_kind: Literal["cs", "me"] = "cs",
) -> str:
    """
    Export a SimModel as an FMI 2.0 .fmu archive.

    The generated .fmu contains:
    - ``modelDescription.xml``   — FMI 2.0 compliant XML
    - ``sources/model.c``         — C source stubs (source-code FMU)
    - ``sources/README_fmi.txt``  — brief note on compilation

    Parameters
    ----------
    model : SimModel
        Model descriptor to export.
    path : str
        Destination path for the .fmu file (must end in ``.fmu``).
    fmi_version : str
        Must be ``'2.0'``.  Other versions are not supported.
    fmu_kind : 'cs' | 'me'
        ``'cs'`` — CoSimulation; ``'me'`` — ModelExchange.

    Returns
    -------
    str
        Absolute path to the written .fmu file (same as ``path``).

    Raises
    ------
    ValueError
        If ``fmi_version`` is not '2.0', or ``fmu_kind`` is not 'cs'/'me'.
    """
    if fmi_version != "2.0":
        raise ValueError(
            f"Only FMI 2.0 is supported; got fmi_version={fmi_version!r}"
        )
    if fmu_kind not in ("cs", "me"):
        raise ValueError(f"fmu_kind must be 'cs' or 'me'; got {fmu_kind!r}")

    xml_text = generate_model_description_xml(model, fmu_kind=fmu_kind)
    c_source = _generate_c_source(model, fmu_kind)
    readme = _make_readme(model, fmu_kind)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modelDescription.xml", xml_text.encode("utf-8"))
        zf.writestr("sources/model.c", c_source.encode("utf-8"))
        zf.writestr("sources/README_fmi.txt", readme.encode("utf-8"))

    return path


def _make_readme(model: SimModel, fmu_kind: str) -> str:
    kind_full = "CoSimulation" if fmu_kind == "cs" else "ModelExchange"
    return (
        f"FMI 2.0 source-code FMU — {kind_full}\n"
        f"Model       : {model.name}\n"
        f"GUID        : {model.guid}\n"
        f"States      : {len(model.state_variables)}\n"
        f"Variables   : {len(model.variables)}\n"
        "\n"
        "DISCLAIMER: FMI 2.0 export subset — NOT FMI Cross-Check certified.\n"
        "\n"
        "To build a binary FMU:\n"
        "  gcc -shared -fPIC -o binaries/<platform>/model.so sources/model.c\n"
        "\n"
        "Generated by kerf-1dsim (https://kerf.ai)\n"
    )


# ---------------------------------------------------------------------------
# validate_fmu
# ---------------------------------------------------------------------------

# Minimal required attributes on <fmiModelDescription> per FMI 2.0 §2.2.1
_REQUIRED_ROOT_ATTRS = {
    "fmiVersion", "modelName", "guid",
}

# Valid causality / variability / initial values per FMI 2.0 Table 13
_VALID_CAUSALITY = {
    "parameter", "calculatedParameter", "input", "output", "local", "independent",
}
_VALID_VARIABILITY = {
    "constant", "fixed", "tunable", "discrete", "continuous",
}
_VALID_INITIAL = {"exact", "approx", "calculated"}


def validate_fmu(fmu_path: str) -> ValidationResult:
    """
    Validate a .fmu archive for FMI 2.0 structural compliance.

    Checks performed
    ----------------
    1. File exists and is a valid ZIP archive.
    2. ``modelDescription.xml`` is present inside the ZIP.
    3. Root element is ``<fmiModelDescription>``.
    4. Required root attributes present: ``fmiVersion``, ``modelName``, ``guid``.
    5. ``fmiVersion`` == "2.0".
    6. Either a ``<CoSimulation>`` or ``<ModelExchange>`` child element exists.
    7. ``<ModelVariables>`` present.
    8. ``<ModelStructure>`` present with ``<Outputs>`` and ``<Derivatives>`` children.
    9. Each ``<ScalarVariable>`` has ``name``, ``valueReference``, ``causality``,
       ``variability``; all values are from the FMI 2.0 enum sets.

    Parameters
    ----------
    fmu_path : str

    Returns
    -------
    ValidationResult
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- 1. ZIP validity ---
    try:
        zf = zipfile.ZipFile(fmu_path, "r")
    except FileNotFoundError:
        return ValidationResult(valid=False, errors=[f"File not found: {fmu_path}"])
    except zipfile.BadZipFile:
        return ValidationResult(valid=False, errors=[f"Not a valid ZIP file: {fmu_path}"])

    with zf:
        names = zf.namelist()

        # --- 2. modelDescription.xml present ---
        if "modelDescription.xml" not in names:
            errors.append("modelDescription.xml not found in FMU archive")
            return ValidationResult(valid=False, errors=errors)

        try:
            xml_bytes = zf.read("modelDescription.xml")
        except Exception as exc:
            errors.append(f"Cannot read modelDescription.xml: {exc}")
            return ValidationResult(valid=False, errors=errors)

        # --- 3–8. XML structural checks ---
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            errors.append(f"modelDescription.xml XML parse error: {exc}")
            return ValidationResult(valid=False, errors=errors)

        if root.tag != "fmiModelDescription":
            errors.append(
                f"Root element must be 'fmiModelDescription', got '{root.tag}'"
            )

        # --- 4. Required root attributes ---
        for attr in _REQUIRED_ROOT_ATTRS:
            if attr not in root.attrib:
                errors.append(f"Missing required attribute on root: '{attr}'")

        # --- 5. fmiVersion == 2.0 ---
        fmi_ver = root.get("fmiVersion", "")
        if fmi_ver != "2.0":
            errors.append(f"fmiVersion must be '2.0', got '{fmi_ver}'")

        # --- 6. CoSimulation or ModelExchange ---
        has_cs = root.find("CoSimulation") is not None
        has_me = root.find("ModelExchange") is not None
        if not has_cs and not has_me:
            errors.append(
                "Neither <CoSimulation> nor <ModelExchange> found — "
                "exactly one must be present per FMI 2.0 §2.2"
            )
        if has_cs and has_me:
            warnings.append(
                "Both <CoSimulation> and <ModelExchange> found; "
                "FMI 2.0 allows this but most tools only consume one."
            )

        # modelIdentifier check
        for tag in ("CoSimulation", "ModelExchange"):
            cap = root.find(tag)
            if cap is not None and not cap.get("modelIdentifier", ""):
                errors.append(f"<{tag}> is missing required 'modelIdentifier' attribute")

        # --- 7. ModelVariables ---
        mv = root.find("ModelVariables")
        if mv is None:
            errors.append("<ModelVariables> element not found")
        else:
            # --- 9. ScalarVariable checks ---
            vr_seen: set[int] = set()
            for sv in mv.findall("ScalarVariable"):
                sv_name = sv.get("name", "")
                if not sv_name:
                    errors.append("A <ScalarVariable> is missing the 'name' attribute")

                vr_str = sv.get("valueReference")
                if vr_str is None:
                    errors.append(
                        f"ScalarVariable '{sv_name}' missing 'valueReference'"
                    )
                else:
                    try:
                        vr = int(vr_str)
                        if vr in vr_seen:
                            errors.append(
                                f"Duplicate valueReference {vr} (variable '{sv_name}')"
                            )
                        vr_seen.add(vr)
                    except ValueError:
                        errors.append(
                            f"ScalarVariable '{sv_name}' has non-integer "
                            f"valueReference '{vr_str}'"
                        )

                causality = sv.get("causality", "")
                if causality not in _VALID_CAUSALITY:
                    errors.append(
                        f"ScalarVariable '{sv_name}' has invalid causality "
                        f"'{causality}'"
                    )

                variability = sv.get("variability", "")
                if variability not in _VALID_VARIABILITY:
                    errors.append(
                        f"ScalarVariable '{sv_name}' has invalid variability "
                        f"'{variability}'"
                    )

                initial = sv.get("initial")
                if initial is not None and initial not in _VALID_INITIAL:
                    errors.append(
                        f"ScalarVariable '{sv_name}' has invalid initial "
                        f"'{initial}'"
                    )

        # --- 8. ModelStructure ---
        ms = root.find("ModelStructure")
        if ms is None:
            errors.append("<ModelStructure> element not found")
        else:
            if ms.find("Outputs") is None:
                errors.append("<ModelStructure> is missing <Outputs>")
            if ms.find("Derivatives") is None:
                errors.append("<ModelStructure> is missing <Derivatives>")

        # source file presence (warn only — not required for validity)
        has_sources = any(n.startswith("sources/") or n.startswith("binaries/")
                          for n in names)
        if not has_sources:
            warnings.append(
                "No sources/ or binaries/ directory found — "
                "FMU may not be executable without a compiled binary."
            )

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


# ---------------------------------------------------------------------------
# Convenience: build SimModel from a ParsedModel (kerf_1dsim.parser)
# ---------------------------------------------------------------------------

def model_from_parsed(parsed, name: str | None = None) -> SimModel:
    """
    Convert a ``kerf_1dsim.parser.ParsedModel`` to a ``SimModel`` for export.

    All non-parameter variables become ``local`` continuous variables unless
    they appear as the first equation's LHS (heuristic: treat as output).
    Parameter variables become FMI parameters.

    Parameters
    ----------
    parsed : ParsedModel
    name : str, optional
        Override the model name.  Defaults to ``parsed.name``.

    Returns
    -------
    SimModel
    """
    from kerf_1dsim.parser import ParsedModel  # local import to avoid circular

    assert isinstance(parsed, ParsedModel)
    model_name = name or parsed.name

    params: dict[str, float] = {}
    state_vars: list[str] = []
    fmi_vars: list[FMIVariable] = []
    vr = 0

    for v in parsed.vars:
        if v.is_parameter:
            params[v.name] = float(v.value or 0.0)
            fmi_vars.append(FMIVariable(
                name=v.name,
                causality="parameter",
                variability="fixed",
                initial="exact",
                start=float(v.value or 0.0),
                value_ref=vr,
            ))
        else:
            state_vars.append(v.name)
            fmi_vars.append(FMIVariable(
                name=v.name,
                causality="local",
                variability="continuous",
                initial="approx",
                start=float(v.start),
                value_ref=vr,
            ))
        vr += 1

    # Identify outputs: variables that appear as LHS of non-der equations
    output_candidates = set()
    for eq in parsed.equations:
        if not eq.is_der:
            # LHS may be a variable name
            lhs = eq.lhs.strip()
            if re.match(r"^\w+$", lhs):
                output_candidates.add(lhs)

    # Promote matched local vars to output
    for fv in fmi_vars:
        if fv.name in output_candidates and fv.causality == "local":
            fv.causality = "output"
            fv.initial = "calculated"

    return SimModel(
        name=model_name,
        description=f"Exported from Modelica model '{parsed.name}'",
        variables=fmi_vars,
        state_variables=state_vars,
        parameters=params,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_identifier(name: str) -> str:
    """Convert a model name to a valid C identifier."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return safe or "_model"


def _fmt_float(v: float) -> str:
    """Format a float for XML emission (avoid scientific notation for small ints)."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _default_initial(
    causality: str,
    variability: str,
) -> str | None:
    """
    Return the default 'initial' value per FMI 2.0 Table 13 if not explicitly set.

    Only non-trivial cases (output + continuous, local + continuous) get 'calculated'
    or 'approx'; parameters get 'exact'; inputs have no initial.
    """
    if causality == "parameter":
        return "exact"
    if causality == "calculatedParameter":
        return "calculated"
    if causality == "input":
        return None  # no initial attribute for inputs
    if causality in ("output", "local"):
        if variability == "continuous":
            return "calculated"
        if variability == "discrete":
            return "exact"
    return None


def _to_xml_string(element: ET.Element) -> str:
    """Serialize an ElementTree element to a pretty-printed UTF-8 XML string."""
    _indent_xml(element)
    buf = io.StringIO()
    tree = ET.ElementTree(element)
    tree.write(buf, encoding="unicode", xml_declaration=True)
    return buf.getvalue()


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """In-place recursive indentation (Python ≥ 3.9 has ET.indent; this works on 3.8+)."""
    pad = "\n" + "  " * level
    child_pad = "\n" + "  " * (level + 1)
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = child_pad
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            _indent_xml(child, level + 1)
        # last child's tail
        if not child.tail or not child.tail.strip():  # type: ignore[possibly-undefined]
            child.tail = pad  # type: ignore[possibly-undefined]
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad
