"""
Tests for kerf-1dsim FMI 2.0 export.

Oracle tests
------------
1. Simple harmonic oscillator: export .fmu + check file exists; unzip and
   verify modelDescription.xml structural compliance (FMI 2.0 XSD subset).
2. Inputs/outputs registration: 2 inputs + 3 outputs → 5 ScalarVariables with
   correct causality attributes.
3. Round-trip export→validate: validate_fmu returns valid=True for any just-
   exported model.
4. fmu_kind cs vs me: both produce valid .fmu; CoSimulation vs ModelExchange
   element differs; underlying structure is identical otherwise.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_fmu_path(suffix: str = "") -> str:
    """Return a fresh temp-directory path for an .fmu file."""
    td = tempfile.mkdtemp()
    return os.path.join(td, f"test_model{suffix}.fmu")


def _make_oscillator_model():
    """
    Simple harmonic oscillator (1 state): q = displacement.

    Equations:
      dq/dt = v
      m * dv/dt + k * q = 0

    Mapped as:
      parameter  q (fixed, initial=1)
      local/continuous  q (state, start=1.0)
      local/continuous  v (state, start=0.0)
      output  q
    """
    from kerf_1dsim.fmi_export import SimModel, FMIVariable

    variables = [
        FMIVariable(name="m",  causality="parameter", variability="fixed",
                    initial="exact", start=1.0, value_ref=0, description="mass [kg]"),
        FMIVariable(name="k",  causality="parameter", variability="fixed",
                    initial="exact", start=1.0, value_ref=1, description="spring stiffness [N/m]"),
        FMIVariable(name="q",  causality="output", variability="continuous",
                    initial="exact", start=1.0, value_ref=2, description="displacement [m]",
                    unit="m"),
        FMIVariable(name="v",  causality="local", variability="continuous",
                    initial="exact", start=0.0, value_ref=3, description="velocity [m/s]",
                    unit="m/s"),
    ]

    return SimModel(
        name="HarmonicOscillator",
        description="Simple undamped harmonic oscillator",
        variables=variables,
        state_variables=["q", "v"],
        parameters={"m": 1.0, "k": 1.0},
        author="kerf-test",
        version="0.1",
    )


def _make_io_model():
    """
    2 inputs + 3 outputs model (pure signal-flow, no dynamics).
    """
    from kerf_1dsim.fmi_export import SimModel, FMIVariable

    variables = [
        FMIVariable(name="u1", causality="input",  variability="continuous",
                    start=0.0, value_ref=0),
        FMIVariable(name="u2", causality="input",  variability="continuous",
                    start=0.0, value_ref=1),
        FMIVariable(name="y1", causality="output", variability="continuous",
                    initial="calculated", start=0.0, value_ref=2),
        FMIVariable(name="y2", causality="output", variability="continuous",
                    initial="calculated", start=0.0, value_ref=3),
        FMIVariable(name="y3", causality="output", variability="continuous",
                    initial="calculated", start=0.0, value_ref=4),
    ]
    return SimModel(
        name="IOModel",
        description="2 inputs 3 outputs",
        variables=variables,
        state_variables=[],
    )


# ---------------------------------------------------------------------------
# Oracle 1: Simple harmonic oscillator export
# ---------------------------------------------------------------------------

class TestHarmonicOscillatorExport:
    """
    Export a 1-state SimModel to FMU; verify .fmu file exists;
    unzip and check modelDescription.xml validates against FMI 2.0 XSD subset.
    """

    def test_fmu_file_created(self):
        """Exporting a model creates a .fmu file at the specified path."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_oscillator")
        result = export_fmu(model, path)
        assert result == path
        assert os.path.isfile(path), f"FMU not created at {path}"
        assert os.path.getsize(path) > 0

    def test_fmu_is_valid_zip(self):
        """The .fmu archive is a valid ZIP file."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_osc_zip")
        export_fmu(model, path)
        assert zipfile.is_zipfile(path), "FMU is not a valid ZIP"

    def test_fmu_contains_model_description(self):
        """modelDescription.xml is present inside the FMU archive."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_osc_xml")
        export_fmu(model, path)
        with zipfile.ZipFile(path) as zf:
            assert "modelDescription.xml" in zf.namelist(), \
                "modelDescription.xml missing from FMU"

    def test_model_description_xml_valid_root(self):
        """modelDescription.xml has correct root element and fmiVersion."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_osc_root")
        export_fmu(model, path)
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("modelDescription.xml")
        root = ET.fromstring(xml_bytes)
        assert root.tag == "fmiModelDescription", \
            f"Root tag should be fmiModelDescription, got {root.tag}"
        assert root.get("fmiVersion") == "2.0"
        assert root.get("modelName") == "HarmonicOscillator"
        assert root.get("guid")  # non-empty

    def test_model_description_has_cosimulation(self):
        """Default fmu_kind='cs' → <CoSimulation> element with modelIdentifier."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_osc_cs")
        export_fmu(model, path, fmu_kind="cs")
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("modelDescription.xml")
        root = ET.fromstring(xml_bytes)
        cs = root.find("CoSimulation")
        assert cs is not None, "<CoSimulation> element not found"
        assert cs.get("modelIdentifier"), "CoSimulation missing modelIdentifier"

    def test_model_description_has_model_variables(self):
        """<ModelVariables> present with ScalarVariable entries."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_osc_mv")
        export_fmu(model, path)
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("modelDescription.xml")
        root = ET.fromstring(xml_bytes)
        mv = root.find("ModelVariables")
        assert mv is not None
        svars = mv.findall("ScalarVariable")
        assert len(svars) == len(model.variables), \
            f"Expected {len(model.variables)} ScalarVariables, got {len(svars)}"

    def test_model_description_has_model_structure(self):
        """<ModelStructure> present with <Outputs> and <Derivatives>."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_osc_ms")
        export_fmu(model, path)
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("modelDescription.xml")
        root = ET.fromstring(xml_bytes)
        ms = root.find("ModelStructure")
        assert ms is not None, "<ModelStructure> not found"
        assert ms.find("Outputs") is not None, "<Outputs> not found"
        assert ms.find("Derivatives") is not None, "<Derivatives> not found"

    def test_fmu_contains_c_source(self):
        """sources/model.c is present inside the FMU archive."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_osc_c")
        export_fmu(model, path)
        with zipfile.ZipFile(path) as zf:
            assert "sources/model.c" in zf.namelist(), \
                "sources/model.c missing from FMU"


# ---------------------------------------------------------------------------
# Oracle 2: Inputs/outputs registration
# ---------------------------------------------------------------------------

class TestIORegistration:
    """
    A model with 2 inputs + 3 outputs → modelDescription.xml lists 5
    ScalarVariables; correct causality attributes set.
    """

    def _get_scalar_variables(self) -> list[ET.Element]:
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_io_model()
        path = _tmp_fmu_path("_io")
        export_fmu(model, path)
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("modelDescription.xml")
        root = ET.fromstring(xml_bytes)
        mv = root.find("ModelVariables")
        assert mv is not None
        return mv.findall("ScalarVariable")

    def test_five_scalar_variables(self):
        """Exactly 5 ScalarVariables (2 inputs + 3 outputs)."""
        svars = self._get_scalar_variables()
        assert len(svars) == 5, f"Expected 5 ScalarVariables, got {len(svars)}"

    def test_two_inputs(self):
        """Exactly 2 variables with causality='input'."""
        svars = self._get_scalar_variables()
        inputs = [sv for sv in svars if sv.get("causality") == "input"]
        assert len(inputs) == 2, f"Expected 2 inputs, got {len(inputs)}"

    def test_three_outputs(self):
        """Exactly 3 variables with causality='output'."""
        svars = self._get_scalar_variables()
        outputs = [sv for sv in svars if sv.get("causality") == "output"]
        assert len(outputs) == 3, f"Expected 3 outputs, got {len(outputs)}"

    def test_input_names(self):
        """Input variable names are 'u1' and 'u2'."""
        svars = self._get_scalar_variables()
        input_names = {sv.get("name") for sv in svars if sv.get("causality") == "input"}
        assert input_names == {"u1", "u2"}, f"Input names: {input_names}"

    def test_output_names(self):
        """Output variable names are 'y1', 'y2', 'y3'."""
        svars = self._get_scalar_variables()
        output_names = {sv.get("name") for sv in svars if sv.get("causality") == "output"}
        assert output_names == {"y1", "y2", "y3"}, f"Output names: {output_names}"

    def test_value_references_unique(self):
        """All valueReference attributes are unique integers."""
        svars = self._get_scalar_variables()
        vrs = [int(sv.get("valueReference")) for sv in svars]
        assert len(set(vrs)) == len(vrs), f"Duplicate valueReferences: {vrs}"

    def test_causality_attributes_valid(self):
        """All causality values are from the FMI 2.0 enum set."""
        valid = {"parameter", "calculatedParameter", "input", "output",
                 "local", "independent"}
        svars = self._get_scalar_variables()
        for sv in svars:
            c = sv.get("causality", "")
            assert c in valid, f"Invalid causality '{c}' for '{sv.get('name')}'"

    def test_outputs_in_model_structure(self):
        """<Outputs> in <ModelStructure> lists the 3 output variables."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_io_model()
        path = _tmp_fmu_path("_io_ms")
        export_fmu(model, path)
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("modelDescription.xml")
        root = ET.fromstring(xml_bytes)
        outputs_el = root.find(".//ModelStructure/Outputs")
        assert outputs_el is not None
        unknowns = outputs_el.findall("Unknown")
        assert len(unknowns) == 3, f"Expected 3 output unknowns, got {len(unknowns)}"


# ---------------------------------------------------------------------------
# Oracle 3: Round-trip export → validate
# ---------------------------------------------------------------------------

class TestRoundTripValidation:
    """validate_fmu returns valid=True for any model just exported by export_fmu."""

    @pytest.mark.parametrize("model_factory,label", [
        (_make_oscillator_model, "oscillator"),
        (_make_io_model, "io_model"),
    ])
    def test_validate_exported_fmu(self, model_factory, label):
        from kerf_1dsim.fmi_export import export_fmu, validate_fmu
        model = model_factory()
        path = _tmp_fmu_path(f"_{label}_roundtrip")
        export_fmu(model, path, fmu_kind="cs")
        result = validate_fmu(path)
        assert result.valid, (
            f"validate_fmu returned invalid for '{label}' FMU.\n"
            f"Errors:\n" + "\n".join(f"  {e}" for e in result.errors)
        )

    def test_validate_modelica_exported_fmu(self):
        """Export a model built from a Modelica ParsedModel → validate passes."""
        from kerf_1dsim.parser import parse_model
        from kerf_1dsim.fmi_export import model_from_parsed, export_fmu, validate_fmu

        source = """
        model RCExport
          parameter Real R = 1000.0;
          parameter Real C = 1e-6;
          parameter Real V0 = 1.0;
          Real v_C(start = 0.0);
          Real i(start = 0.001);
        equation
          der(v_C) = i / C;
          v_C + R * i = V0;
        end RCExport;
        """
        parsed = parse_model(source)
        model = model_from_parsed(parsed)
        path = _tmp_fmu_path("_rc_modelica")
        export_fmu(model, path)
        result = validate_fmu(path)
        assert result.valid, (
            "validate_fmu returned invalid for Modelica-parsed RC model.\n"
            "Errors:\n" + "\n".join(f"  {e}" for e in result.errors)
        )

    def test_validate_nonexistent_fmu(self):
        """validate_fmu returns valid=False for a non-existent file."""
        from kerf_1dsim.fmi_export import validate_fmu
        result = validate_fmu("/tmp/does_not_exist_xyzabc.fmu")
        assert not result.valid
        assert len(result.errors) >= 1

    def test_validate_empty_zip(self):
        """validate_fmu returns valid=False for a ZIP lacking modelDescription.xml."""
        from kerf_1dsim.fmi_export import validate_fmu
        path = _tmp_fmu_path("_empty")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("dummy.txt", "hello")
        result = validate_fmu(path)
        assert not result.valid
        assert any("modelDescription.xml" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Oracle 4: fmu_kind cs vs me
# ---------------------------------------------------------------------------

class TestFmuKind:
    """
    Both cs and me produce valid .fmu files.
    They differ only in the CoSimulation vs ModelExchange capability element.
    """

    def test_cs_fmu_valid(self):
        from kerf_1dsim.fmi_export import export_fmu, validate_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_cs")
        export_fmu(model, path, fmu_kind="cs")
        result = validate_fmu(path)
        assert result.valid, \
            "CS FMU validation failed:\n" + "\n".join(result.errors)

    def test_me_fmu_valid(self):
        from kerf_1dsim.fmi_export import export_fmu, validate_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_me")
        export_fmu(model, path, fmu_kind="me")
        result = validate_fmu(path)
        assert result.valid, \
            "ME FMU validation failed:\n" + "\n".join(result.errors)

    def test_cs_has_cosimulation_element(self):
        """cs FMU has <CoSimulation> not <ModelExchange>."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_cs_elem")
        export_fmu(model, path, fmu_kind="cs")
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("modelDescription.xml"))
        assert root.find("CoSimulation") is not None
        assert root.find("ModelExchange") is None

    def test_me_has_modelexchange_element(self):
        """me FMU has <ModelExchange> not <CoSimulation>."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path = _tmp_fmu_path("_me_elem")
        export_fmu(model, path, fmu_kind="me")
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("modelDescription.xml"))
        assert root.find("ModelExchange") is not None
        assert root.find("CoSimulation") is None

    def test_same_variables_cs_and_me(self):
        """cs and me FMUs have the same ScalarVariable list (same model)."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        path_cs = _tmp_fmu_path("_cs_vars")
        path_me = _tmp_fmu_path("_me_vars")
        export_fmu(model, path_cs, fmu_kind="cs")
        export_fmu(model, path_me, fmu_kind="me")

        def _var_names(path):
            with zipfile.ZipFile(path) as zf:
                root = ET.fromstring(zf.read("modelDescription.xml"))
            mv = root.find("ModelVariables")
            return {sv.get("name") for sv in mv.findall("ScalarVariable")}

        assert _var_names(path_cs) == _var_names(path_me)

    def test_invalid_fmu_kind_raises(self):
        """export_fmu raises ValueError for an unknown fmu_kind."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        with pytest.raises(ValueError, match="fmu_kind must be"):
            export_fmu(model, "/tmp/bad.fmu", fmu_kind="xx")

    def test_invalid_fmi_version_raises(self):
        """export_fmu raises ValueError for fmi_version != '2.0'."""
        from kerf_1dsim.fmi_export import export_fmu
        model = _make_oscillator_model()
        with pytest.raises(ValueError, match="Only FMI 2.0"):
            export_fmu(model, "/tmp/bad.fmu", fmi_version="3.0")


# ---------------------------------------------------------------------------
# generate_model_description_xml unit tests
# ---------------------------------------------------------------------------

class TestGenerateModelDescriptionXml:
    """Unit tests for the XML generation function."""

    def test_returns_string(self):
        from kerf_1dsim.fmi_export import generate_model_description_xml
        xml = generate_model_description_xml(_make_oscillator_model())
        assert isinstance(xml, str)
        assert len(xml) > 0

    def test_xml_parseable(self):
        from kerf_1dsim.fmi_export import generate_model_description_xml
        xml = generate_model_description_xml(_make_oscillator_model())
        root = ET.fromstring(xml)
        assert root is not None

    def test_xml_declaration_present(self):
        from kerf_1dsim.fmi_export import generate_model_description_xml
        xml = generate_model_description_xml(_make_oscillator_model())
        assert xml.startswith("<?xml")

    def test_correct_scalar_variable_count(self):
        from kerf_1dsim.fmi_export import generate_model_description_xml
        model = _make_io_model()
        root = ET.fromstring(generate_model_description_xml(model))
        mv = root.find("ModelVariables")
        assert mv is not None
        assert len(mv.findall("ScalarVariable")) == 5

    def test_unit_attribute_present(self):
        from kerf_1dsim.fmi_export import generate_model_description_xml
        model = _make_oscillator_model()
        root = ET.fromstring(generate_model_description_xml(model))
        # 'q' has unit="m" — check the Real child has unit="m"
        mv = root.find("ModelVariables")
        q_sv = next(
            sv for sv in mv.findall("ScalarVariable") if sv.get("name") == "q"
        )
        real_el = q_sv.find("Real")
        assert real_el is not None
        assert real_el.get("unit") == "m"

    def test_start_value_on_parameter(self):
        from kerf_1dsim.fmi_export import generate_model_description_xml
        model = _make_oscillator_model()
        root = ET.fromstring(generate_model_description_xml(model))
        mv = root.find("ModelVariables")
        m_sv = next(
            sv for sv in mv.findall("ScalarVariable") if sv.get("name") == "m"
        )
        real_el = m_sv.find("Real")
        assert real_el is not None
        assert real_el.get("start") == "1"  # 1.0 → "1"


# ---------------------------------------------------------------------------
# model_from_parsed integration test
# ---------------------------------------------------------------------------

class TestModelFromParsed:
    """model_from_parsed correctly maps Modelica vars to SimModel vars."""

    def test_rc_model_from_parsed(self):
        from kerf_1dsim.parser import parse_model
        from kerf_1dsim.fmi_export import model_from_parsed

        source = """
        model RC
          parameter Real R = 1000.0;
          parameter Real C = 1e-6;
          parameter Real V0 = 1.0;
          Real v_C(start = 0.0);
          Real i(start = 0.001);
        equation
          der(v_C) = i / C;
          v_C + R * i = V0;
        end RC;
        """
        parsed = parse_model(source)
        model = model_from_parsed(parsed)
        assert model.name == "RC"

        var_names = {v.name for v in model.variables}
        assert "R" in var_names
        assert "C" in var_names
        assert "V0" in var_names
        assert "v_C" in var_names
        assert "i" in var_names

        param_vars = [v for v in model.variables if v.causality == "parameter"]
        assert len(param_vars) == 3  # R, C, V0

        state_vars = [v for v in model.variables if v.causality in ("local", "output")]
        assert len(state_vars) == 2  # v_C, i

    def test_state_variables_populated(self):
        from kerf_1dsim.parser import parse_model
        from kerf_1dsim.fmi_export import model_from_parsed

        source = """
        model MS
          parameter Real m = 1.0;
          parameter Real k = 1.0;
          Real q(start = 1.0);
          Real v(start = 0.0);
        equation
          der(q) = v;
          der(v) = -k * q / m;
        end MS;
        """
        parsed = parse_model(source)
        model = model_from_parsed(parsed)
        assert "q" in model.state_variables
        assert "v" in model.state_variables
