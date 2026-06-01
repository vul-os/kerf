"""
Tests for CalculiX thermal analysis: generate_thermal_input + _parse_dat_thermal.

Test inventory
--------------
1. test_thermal_heading                   — deck starts with *HEADING + "Kerf thermal analysis"
2. test_thermal_steady_state_directive    — *HEAT TRANSFER, STEADY STATE present
3. test_thermal_transient_directive       — *HEAT TRANSFER with dt and t_end for transient
4. test_thermal_elements_dc_type          — DC3D4 thermal elements used, not C3D4
5. test_thermal_material_conductivity     — *CONDUCTIVITY block present
6. test_thermal_material_density          — *DENSITY block present
7. test_thermal_transient_specific_heat   — *SPECIFIC HEAT only in transient deck
8. test_thermal_steady_no_specific_heat   — *SPECIFIC HEAT absent from steady-state deck
9. test_thermal_initial_conditions        — *INITIAL CONDITIONS, TYPE=TEMPERATURE block
10. test_thermal_prescribed_temperature   — *BOUNDARY with DOF 11 for temperature BC
11. test_thermal_convection_film_block    — *FILM block present for convection BC
12. test_thermal_film_coefficient_value   — film coefficient and sink temp written correctly
13. test_thermal_heat_flux_cflux_block    — *CFLUX block present for heat-flux BC
14. test_thermal_output_nt                — *NODE FILE block requests NT output
15. test_thermal_output_hfl               — *EL FILE block requests HFL output
16. test_thermal_end_step                 — *END STEP closes the deck
17. test_thermal_cube_steady_state_bc     — cube with hot/cold faces (100°C / 0°C)
18. test_thermal_parse_dat_empty          — _parse_dat_thermal handles missing file gracefully
19. test_thermal_parse_dat_temperatures   — synthetic .dat temperature block parsed correctly
20. test_thermal_parse_dat_heat_flux      — synthetic .dat HFL block parsed correctly
21. test_thermal_run_pending_no_ccx       — run_static_analysis returns pending when ccx absent
22. test_thermal_node_nset_all            — *NODE, NSET=Nall present
23. test_thermal_solid_section            — *SOLID SECTION with correct material name
24. test_no_regression_linear_static      — structural static deck unaffected
25. test_no_regression_modal              — modal deck unaffected
"""

import math
import tempfile
from pathlib import Path

import pytest

from kerf_fem.calculix_utils import generate_thermal_input, _parse_dat_thermal


# ---------------------------------------------------------------------------
# Minimal mesh fixtures
# ---------------------------------------------------------------------------

def _cube_tet_mesh():
    """
    Simple 4-node tet (one element) representing a single thermal element.
    Nodes at origin + unit axis offsets.
    """
    nodes = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    elements = [(1, "tetra", [1, 2, 3, 4])]
    return {"nodes": nodes, "elements": elements}


def _cube_hex_mesh():
    """
    A single 8-node hexahedral element (unit cube).
    Node numbering follows CalculiX DC3D8 convention.
    """
    nodes = [
        [0.0, 0.0, 0.0],  # 1
        [1.0, 0.0, 0.0],  # 2
        [1.0, 1.0, 0.0],  # 3
        [0.0, 1.0, 0.0],  # 4
        [0.0, 0.0, 1.0],  # 5
        [1.0, 0.0, 1.0],  # 6
        [1.0, 1.0, 1.0],  # 7
        [0.0, 1.0, 1.0],  # 8
    ]
    elements = [(1, "hexahedron", [1, 2, 3, 4, 5, 6, 7, 8])]
    return {"nodes": nodes, "elements": elements}


def _steel_thermal():
    """Steel-like thermal material properties."""
    return {
        "name": "STEEL",
        "conductivity": 50.0,    # W/(m·K)
        "density": 7850.0,       # kg/m³
        "specific_heat": 500.0,  # J/(kg·K)
    }


# ---------------------------------------------------------------------------
# 1. Heading
# ---------------------------------------------------------------------------

def test_thermal_heading():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    assert "*HEADING" in inp
    assert "Kerf thermal analysis" in inp


# ---------------------------------------------------------------------------
# 2. Steady-state directive
# ---------------------------------------------------------------------------

def test_thermal_steady_state_directive():
    inp = generate_thermal_input(
        _cube_tet_mesh(), _steel_thermal(), [],
        analysis_type="steady-state",
    )
    assert "*HEAT TRANSFER, STEADY STATE" in inp


# ---------------------------------------------------------------------------
# 3. Transient directive
# ---------------------------------------------------------------------------

def test_thermal_transient_directive():
    inp = generate_thermal_input(
        _cube_tet_mesh(), _steel_thermal(), [],
        analysis_type="transient",
        dt=0.1,
        t_end=10.0,
    )
    assert "*HEAT TRANSFER" in inp
    # The transient line must contain both dt and t_end values
    transient_line = next(
        line for line in inp.splitlines()
        if line.startswith("*HEAT TRANSFER") and "STEADY STATE" not in line
    )
    assert "0.1" in transient_line
    assert "10" in transient_line


# ---------------------------------------------------------------------------
# 4. Thermal element type (DC prefix)
# ---------------------------------------------------------------------------

def test_thermal_elements_dc_type():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    # Thermal tet must be DC3D4, not structural C3D4
    assert "DC3D4" in inp
    assert "C3D4" not in inp or inp.count("C3D4") == inp.count("DC3D4")


def test_thermal_elements_dc3d8_for_hex():
    inp = generate_thermal_input(_cube_hex_mesh(), _steel_thermal(), [])
    assert "DC3D8" in inp


# ---------------------------------------------------------------------------
# 5. Material: conductivity
# ---------------------------------------------------------------------------

def test_thermal_material_conductivity():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    assert "*CONDUCTIVITY" in inp
    lines = inp.splitlines()
    cond_idx = next(i for i, l in enumerate(lines) if l.strip() == "*CONDUCTIVITY")
    # The line after *CONDUCTIVITY must be the conductivity value
    val_line = lines[cond_idx + 1]
    assert math.isclose(float(val_line.strip()), 50.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 6. Material: density
# ---------------------------------------------------------------------------

def test_thermal_material_density():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    assert "*DENSITY" in inp
    lines = inp.splitlines()
    dens_idx = next(i for i, l in enumerate(lines) if l.strip() == "*DENSITY")
    val_line = lines[dens_idx + 1]
    assert math.isclose(float(val_line.strip()), 7850.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 7. Transient-only: specific heat
# ---------------------------------------------------------------------------

def test_thermal_transient_specific_heat():
    inp = generate_thermal_input(
        _cube_tet_mesh(), _steel_thermal(), [],
        analysis_type="transient",
    )
    assert "*SPECIFIC HEAT" in inp
    lines = inp.splitlines()
    sh_idx = next(i for i, l in enumerate(lines) if "*SPECIFIC HEAT" in l)
    val_line = lines[sh_idx + 1]
    assert math.isclose(float(val_line.strip()), 500.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 8. Steady-state: no specific heat
# ---------------------------------------------------------------------------

def test_thermal_steady_no_specific_heat():
    inp = generate_thermal_input(
        _cube_tet_mesh(), _steel_thermal(), [],
        analysis_type="steady-state",
    )
    assert "*SPECIFIC HEAT" not in inp


# ---------------------------------------------------------------------------
# 9. Initial conditions block
# ---------------------------------------------------------------------------

def test_thermal_initial_conditions():
    inp = generate_thermal_input(
        _cube_tet_mesh(), _steel_thermal(), [],
        initial_temp=25.0,
    )
    assert "*INITIAL CONDITIONS, TYPE=TEMPERATURE" in inp
    assert "25" in inp  # initial temperature appears somewhere in the deck


# ---------------------------------------------------------------------------
# 10. Prescribed temperature BC → *BOUNDARY with DOF 11
# ---------------------------------------------------------------------------

def test_thermal_prescribed_temperature():
    bcs = [{"type": "temperature", "node_ids": [1, 2], "value": 100.0}]
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), bcs)
    assert "*BOUNDARY" in inp
    # DOF 11 is the thermal DOF in CalculiX
    lines = inp.splitlines()
    boundary_lines = [l for l in lines if ",11,11," in l]
    assert len(boundary_lines) >= 1, "Expected a *BOUNDARY line with DOF 11,11"
    assert "100" in boundary_lines[0]


# ---------------------------------------------------------------------------
# 11. Convection BC → *FILM block
# ---------------------------------------------------------------------------

def test_thermal_convection_film_block():
    bcs = [{"type": "film", "node_ids": [3], "film_coeff": 25.0, "sink_temp": 20.0}]
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), bcs)
    assert "*FILM" in inp


# ---------------------------------------------------------------------------
# 12. Film coefficient and sink temperature written correctly
# ---------------------------------------------------------------------------

def test_thermal_film_coefficient_value():
    film_coeff = 100.0
    sink_temp = 30.0
    bcs = [{"type": "film", "node_ids": [2], "film_coeff": film_coeff, "sink_temp": sink_temp}]
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), bcs)
    # Find the data line after *FILM
    lines = inp.splitlines()
    film_data_lines = []
    capture_next = False
    for line in lines:
        if line.strip() == "*FILM":
            capture_next = True
            continue
        if capture_next:
            film_data_lines.append(line)
            capture_next = False
    assert film_data_lines, "No data line found after *FILM"
    data = film_data_lines[0]
    assert str(int(film_coeff)) in data or f"{film_coeff:.6g}" in data
    assert str(int(sink_temp)) in data or f"{sink_temp:.6g}" in data


# ---------------------------------------------------------------------------
# 13. Heat flux BC → *CFLUX block
# ---------------------------------------------------------------------------

def test_thermal_heat_flux_cflux_block():
    bcs = [{"type": "heat_flux", "node_ids": [4], "value": 1000.0}]
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), bcs)
    assert "*CFLUX" in inp
    # DOF 11 for thermal flux
    lines = inp.splitlines()
    cflux_data = [l for l in lines if ",11," in l and not l.startswith("*BOUNDARY")]
    assert len(cflux_data) >= 1, "Expected *CFLUX data line with DOF 11"
    assert "1000" in cflux_data[0]


# ---------------------------------------------------------------------------
# 14. Output: NT (nodal temperature)
# ---------------------------------------------------------------------------

def test_thermal_output_nt():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    assert "*NODE FILE" in inp
    assert "NT" in inp
    lines = inp.splitlines()
    nf_idx = next(i for i, l in enumerate(lines) if l.startswith("*NODE FILE"))
    assert lines[nf_idx + 1].strip() == "NT"


# ---------------------------------------------------------------------------
# 15. Output: HFL (heat flux)
# ---------------------------------------------------------------------------

def test_thermal_output_hfl():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    assert "*EL FILE" in inp
    assert "HFL" in inp
    lines = inp.splitlines()
    ef_idx = next(i for i, l in enumerate(lines) if l.startswith("*EL FILE"))
    assert lines[ef_idx + 1].strip() == "HFL"


# ---------------------------------------------------------------------------
# 16. *END STEP
# ---------------------------------------------------------------------------

def test_thermal_end_step():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    assert "*END STEP" in inp
    assert inp.splitlines()[-1].strip() == "*END STEP"


# ---------------------------------------------------------------------------
# 17. Cube steady-state: hot face (100°C) + cold face (0°C)
# ---------------------------------------------------------------------------

def test_thermal_cube_steady_state_bc():
    """
    Simulate a unit cube with one face prescribed at 100°C and the opposite
    at 0°C — the canonical 1D conduction test case.

    The deck must contain both *BOUNDARY + DOF 11 lines (one per prescribed face).
    """
    bcs = [
        {"type": "temperature", "node_ids": [1, 4, 5, 8], "value": 100.0},
        {"type": "temperature", "node_ids": [2, 3, 6, 7], "value": 0.0},
    ]
    inp = generate_thermal_input(
        _cube_hex_mesh(), _steel_thermal(), bcs,
        analysis_type="steady-state",
    )
    assert "*HEAT TRANSFER, STEADY STATE" in inp
    assert "*BOUNDARY" in inp
    # Both temperature values must appear in the deck
    boundary_lines = [l for l in inp.splitlines() if ",11,11," in l]
    values = [float(l.split(",")[-1]) for l in boundary_lines]
    assert 100.0 in values
    assert 0.0 in values


# ---------------------------------------------------------------------------
# 18. _parse_dat_thermal: missing file
# ---------------------------------------------------------------------------

def test_thermal_parse_dat_empty():
    result = _parse_dat_thermal(Path("/tmp/__nonexistent_thermal__.dat"))
    assert "error" in result


# ---------------------------------------------------------------------------
# 19. _parse_dat_thermal: synthetic temperature block
# ---------------------------------------------------------------------------

def test_thermal_parse_dat_temperatures():
    synthetic = """
 T E M P E R A T U R E S
  1  2.500000E+01
  2  5.000000E+01
  3  7.500000E+01
  4  1.000000E+02

"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".dat", delete=False) as f:
        f.write(synthetic)
        fpath = Path(f.name)

    try:
        result = _parse_dat_thermal(fpath)
        temps = result["temperatures"]
        assert len(temps) == 4
        assert temps[0]["node"] == 1
        assert math.isclose(temps[0]["T"], 25.0, rel_tol=1e-6)
        assert math.isclose(temps[3]["T"], 100.0, rel_tol=1e-6)
    finally:
        fpath.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 20. _parse_dat_thermal: synthetic HFL block
# ---------------------------------------------------------------------------

def test_thermal_parse_dat_heat_flux():
    synthetic = """
 H E A T  F L U X
  1  1.000000E+03  0.000000E+00  0.000000E+00
  2  0.000000E+00  5.000000E+02  0.000000E+00

"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".dat", delete=False) as f:
        f.write(synthetic)
        fpath = Path(f.name)

    try:
        result = _parse_dat_thermal(fpath)
        hfluxes = result["heat_fluxes"]
        assert len(hfluxes) == 2
        assert hfluxes[0]["elem"] == 1
        assert math.isclose(hfluxes[0]["HFL"], 1000.0, rel_tol=1e-6)
        assert math.isclose(hfluxes[1]["HFL"], 500.0, rel_tol=1e-6)
    finally:
        fpath.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 21. run_static_analysis returns "pending" when ccx absent
# ---------------------------------------------------------------------------

def test_thermal_run_pending_no_ccx(monkeypatch):
    from kerf_fem import calculix_utils
    monkeypatch.setattr(calculix_utils, "_CALCULIX_AVAILABLE", False)
    result = calculix_utils.run_static_analysis(
        "dummy.msh",
        {"conductivity": 50.0},
        [],
        [],
        analysis_type="thermal",
    )
    assert result["status"] == "pending"
    assert "warnings" in result


# ---------------------------------------------------------------------------
# 22. Nodes block: NSET=Nall
# ---------------------------------------------------------------------------

def test_thermal_node_nset_all():
    inp = generate_thermal_input(_cube_tet_mesh(), _steel_thermal(), [])
    assert "NSET=Nall" in inp


# ---------------------------------------------------------------------------
# 23. Solid section with correct material name
# ---------------------------------------------------------------------------

def test_thermal_solid_section():
    mat = dict(_steel_thermal())
    mat["name"] = "COPPER"
    mat["conductivity"] = 400.0
    inp = generate_thermal_input(_cube_tet_mesh(), mat, [])
    assert "*MATERIAL, NAME=COPPER" in inp
    assert "*SOLID SECTION, ELSET=Eall, MATERIAL=COPPER" in inp


# ---------------------------------------------------------------------------
# 24. No regression: structural static deck unaffected
# ---------------------------------------------------------------------------

def test_no_regression_linear_static():
    from kerf_fem.calculix_utils import build_nonlinear_plastic_inp
    nodes = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    elements = [(1, "tetra", [1, 2, 3, 4])]
    mat = {"E": 200e9, "nu": 0.3, "rho": 7850.0, "sigma_y0": 250e6, "H": 0.0}
    inp = build_nonlinear_plastic_inp(nodes, elements, mat, [], [])
    assert "*HEADING" in inp
    assert "C3D4" in inp
    assert "NLGEOM" in inp
    assert "*HEAT TRANSFER" not in inp


# ---------------------------------------------------------------------------
# 25. No regression: modal deck unaffected
# ---------------------------------------------------------------------------

def test_no_regression_modal():
    """
    _msh_to_inp_modal is internal; access it via the public import path to
    check that the thermal additions don't break the modal path's module load.
    """
    from kerf_fem import calculix_utils
    # Simply importing the module (which includes the new thermal code) must not
    # raise any exceptions and the existing module-level attributes must be intact.
    assert hasattr(calculix_utils, "run_static_analysis")
    assert hasattr(calculix_utils, "generate_thermal_input")
    assert hasattr(calculix_utils, "_THERMAL_ELEM_MAP")
    assert calculix_utils._THERMAL_ELEM_MAP["tetra"] == "DC3D4"
    assert calculix_utils._THERMAL_ELEM_MAP["hexahedron"] == "DC3D8"
