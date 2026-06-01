"""
Tests for the openEMS XML bridge in kerf_electronics.routes_rf.

Covers:
  - XML file is created and parses cleanly
  - Root tag is <openEMS>
  - FDTD element carries NumberOfTimesteps and endCriteria
  - BoundaryCond PML on all 6 faces
  - Gaussian Excitation block present with f0 / fc
  - Materials block contains substrate and copper entries
  - Primitives: substrate_slab, ground_plane, trace boxes present
  - Port probes (Voltage + Current) present for each port
  - DumpBox present for each port
  - Frequency range round-trips correctly (f_min / f_max)
  - Mesh resolution scales with shortest wavelength
  - High-frequency route uses finer mesh than low-frequency route
  - Custom substrate eps_r shifts mesh resolution
  - num_primitives matches actual Primitive child count (Box + Probe + DumpBox)
  - num_ports equals len(rf_route.ports)
  - honest_caveat is non-empty and mentions openEMS
  - Export result xml_path matches requested output path
  - RectilinearGrid has XLines / YLines / ZLines
  - XLines includes 0.0 and trace_length_mm mesh anchor points
  - ZLines covers ground plane through substrate
  - XML is re-parseable after export (round-trip validity)
  - Non-default port names appear in Probe names
  - sigma_conductor flows into copper Material/Property Kappa
  - mesh_resolution_mm capped at trace_thickness_mm / 2
"""

import os
import sys
import tempfile
import math
import xml.etree.ElementTree as ET
import pytest

# Ensure the package src is on path (mirrors conftest.py)
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_electronics.routes_rf import (
    OpenEMSRoute,
    OpenEMSExportResult,
    export_to_openems,
    _mesh_resolution,
    _c_in_medium,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_default_route(**kwargs) -> OpenEMSRoute:
    """Return a default microstrip route, optionally overriding fields."""
    return OpenEMSRoute(**kwargs)


def _export(route: OpenEMSRoute) -> tuple[str, ET.ElementTree, OpenEMSExportResult]:
    """Write XML to a temp file, return (path, parsed_tree, result)."""
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        result = export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        return xml_path, tree, result
    finally:
        pass  # caller cleans up via fixture or explicit unlink


@pytest.fixture
def default_export():
    """Fixture: exports default route, yields (xml_path, tree, result), cleans up."""
    route = _make_default_route()
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    result = export_to_openems(route, xml_path)
    tree = ET.parse(xml_path)
    yield xml_path, tree, result
    if os.path.exists(xml_path):
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 1. File creation and basic XML validity
# ---------------------------------------------------------------------------

def test_xml_file_exists(default_export):
    xml_path, _, _ = default_export
    assert os.path.isfile(xml_path), "XML file must be created at the requested path"


def test_xml_parses_without_error(default_export):
    xml_path, _, _ = default_export
    # Re-parse independently to confirm the file is self-consistent
    ET.parse(xml_path)


def test_root_tag_is_openems(default_export):
    _, tree, _ = default_export
    assert tree.getroot().tag == "openEMS"


# ---------------------------------------------------------------------------
# 2. FDTD element
# ---------------------------------------------------------------------------

def test_fdtd_element_present(default_export):
    _, tree, _ = default_export
    fdtd = tree.getroot().find("FDTD")
    assert fdtd is not None, "<FDTD> element must be present"


def test_fdtd_number_of_timesteps(default_export):
    route = _make_default_route()
    _, tree, result = default_export
    fdtd = tree.getroot().find("FDTD")
    assert fdtd is not None
    ts = int(fdtd.attrib["NumberOfTimesteps"])
    assert ts == route.num_timesteps


def test_fdtd_end_criteria(default_export):
    _, tree, _ = default_export
    fdtd = tree.getroot().find("FDTD")
    ec = float(fdtd.attrib["endCriteria"])
    assert ec == pytest.approx(1e-5, rel=1e-3)


# ---------------------------------------------------------------------------
# 3. BoundaryCond — PML on all 6 faces
# ---------------------------------------------------------------------------

def test_boundary_cond_pml_all_faces(default_export):
    _, tree, _ = default_export
    bc = tree.getroot().find("FDTD/BoundaryCond")
    assert bc is not None, "<BoundaryCond> must be present"
    for face in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"):
        val = bc.attrib.get(face, "")
        assert "PML" in val, f"Face {face!r} must be PML, got {val!r}"


# ---------------------------------------------------------------------------
# 4. Excitation block (Gaussian)
# ---------------------------------------------------------------------------

def test_excitation_type_0_gaussian(default_export):
    _, tree, _ = default_export
    exc = tree.getroot().find("FDTD/Excitation")
    assert exc is not None, "<Excitation> must be present"
    assert exc.attrib.get("Type") == "0", "Gaussian pulse is Type 0"


def test_excitation_f0_matches_route():
    route = _make_default_route(f_center_Hz=5.8e9, f_cutoff_Hz=8.0e9)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        exc = tree.getroot().find("FDTD/Excitation")
        f0 = float(exc.attrib["f0"])
        assert f0 == pytest.approx(5.8e9, rel=1e-6)
    finally:
        os.unlink(xml_path)


def test_excitation_fc_equals_cutoff_minus_center():
    route = _make_default_route(f_center_Hz=2.45e9, f_cutoff_Hz=5.0e9)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        exc = tree.getroot().find("FDTD/Excitation")
        fc = float(exc.attrib["fc"])
        expected_fc = 5.0e9 - 2.45e9
        assert fc == pytest.approx(expected_fc, rel=1e-6)
    finally:
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 5. Materials
# ---------------------------------------------------------------------------

def test_materials_block_present(default_export):
    _, tree, _ = default_export
    cs = tree.getroot().find("ContinuousStructure")
    assert cs is not None
    mats = cs.find("Materials")
    assert mats is not None, "<Materials> block must be present"


def test_substrate_material_present(default_export):
    _, tree, _ = default_export
    mats = tree.getroot().find("ContinuousStructure/Materials")
    names = [m.attrib.get("name", "") for m in mats.findall("Material")]
    assert "substrate" in names, "substrate material must be in <Materials>"


def test_copper_material_present(default_export):
    _, tree, _ = default_export
    mats = tree.getroot().find("ContinuousStructure/Materials")
    names = [m.attrib.get("name", "") for m in mats.findall("Material")]
    assert "copper" in names, "copper material must be in <Materials>"


def test_substrate_eps_r_matches_route():
    route = _make_default_route(eps_r=3.66)  # Rogers 4003C
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        mats = tree.getroot().find("ContinuousStructure/Materials")
        for mat in mats.findall("Material"):
            if mat.attrib.get("name") == "substrate":
                prop = mat.find("Property")
                assert prop is not None
                eps = float(prop.attrib["Epsilon"])
                assert eps == pytest.approx(3.66, rel=1e-4)
                return
        pytest.fail("substrate Material element not found")
    finally:
        os.unlink(xml_path)


def test_copper_kappa_matches_sigma():
    route = _make_default_route(sigma_conductor=5.8e7)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        mats = tree.getroot().find("ContinuousStructure/Materials")
        for mat in mats.findall("Material"):
            if mat.attrib.get("name") == "copper":
                prop = mat.find("Property")
                kappa = float(prop.attrib["Kappa"])
                assert kappa == pytest.approx(5.8e7, rel=1e-4)
                return
        pytest.fail("copper Material element not found")
    finally:
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 6. Primitives — geometry boxes
# ---------------------------------------------------------------------------

def test_substrate_slab_box_present(default_export):
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    names = [b.attrib.get("name", "") for b in prims.findall("Box")]
    assert "substrate_slab" in names


def test_ground_plane_box_present(default_export):
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    names = [b.attrib.get("name", "") for b in prims.findall("Box")]
    assert "ground_plane" in names


def test_trace_box_present(default_export):
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    names = [b.attrib.get("name", "") for b in prims.findall("Box")]
    assert "trace" in names


def test_trace_box_material_is_copper(default_export):
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    for b in prims.findall("Box"):
        if b.attrib.get("name") == "trace":
            assert b.attrib.get("Material") == "copper"
            return
    pytest.fail("trace box not found")


def test_substrate_slab_material_is_substrate(default_export):
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    for b in prims.findall("Box"):
        if b.attrib.get("name") == "substrate_slab":
            assert b.attrib.get("Material") == "substrate"
            return
    pytest.fail("substrate_slab box not found")


# ---------------------------------------------------------------------------
# 7. Ports — Probe and DumpBox elements
# ---------------------------------------------------------------------------

def test_port_voltage_probes_present(default_export):
    route = _make_default_route()
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    probe_names = [p.attrib.get("name", "") for p in prims.findall("Probe")]
    for port_name in route.ports:
        assert f"{port_name}_V" in probe_names, f"Voltage probe {port_name}_V missing"


def test_port_current_probes_present(default_export):
    route = _make_default_route()
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    probe_names = [p.attrib.get("name", "") for p in prims.findall("Probe")]
    for port_name in route.ports:
        assert f"{port_name}_I" in probe_names, f"Current probe {port_name}_I missing"


def test_port_dumpboxes_present(default_export):
    route = _make_default_route()
    _, tree, _ = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    dump_names = [d.attrib.get("name", "") for d in prims.findall("DumpBox")]
    for port_name in route.ports:
        assert f"{port_name}_dump" in dump_names, f"DumpBox {port_name}_dump missing"


def test_custom_port_names_in_probes():
    route = _make_default_route(ports=["InputPort", "OutputPort"])
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        prims = tree.getroot().find("ContinuousStructure/Primitives")
        probe_names = {p.attrib.get("name", "") for p in prims.findall("Probe")}
        assert "InputPort_V" in probe_names
        assert "OutputPort_V" in probe_names
        assert "InputPort_I" in probe_names
        assert "OutputPort_I" in probe_names
    finally:
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 8. Frequency range
# ---------------------------------------------------------------------------

def test_frequency_range_f_min_non_negative(default_export):
    _, _, result = default_export
    assert result.frequency_range_Hz[0] >= 0.0


def test_frequency_range_f_max_greater_than_f_min(default_export):
    _, _, result = default_export
    f_min, f_max = result.frequency_range_Hz
    assert f_max > f_min


def test_frequency_range_covers_center():
    route = _make_default_route(f_center_Hz=10e9, f_cutoff_Hz=15e9)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        result = export_to_openems(route, xml_path)
        f_min, f_max = result.frequency_range_Hz
        assert f_min <= 10e9 <= f_max
    finally:
        os.unlink(xml_path)


def test_frequency_range_emitted_in_fdtd_f_max():
    route = _make_default_route(f_center_Hz=2.45e9, f_cutoff_Hz=5.0e9)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        fdtd = tree.getroot().find("FDTD")
        f_max_attr = float(fdtd.attrib["f_max"])
        expected = route.f_center_Hz + (route.f_cutoff_Hz - route.f_center_Hz)
        assert f_max_attr == pytest.approx(expected, rel=1e-6)
    finally:
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 9. Mesh resolution
# ---------------------------------------------------------------------------

def test_mesh_resolution_positive(default_export):
    _, _, result = default_export
    assert result.mesh_resolution_mm > 0


def test_mesh_resolution_decreases_with_higher_frequency():
    """Higher f_cutoff → shorter wavelength → finer mesh."""
    route_low = _make_default_route(f_cutoff_Hz=1e9)
    route_high = _make_default_route(f_cutoff_Hz=20e9)
    res_low = _mesh_resolution(route_low.f_cutoff_Hz, route_low.eps_r,
                               route_low.num_mesh_cells_per_wavelength)
    res_high = _mesh_resolution(route_high.f_cutoff_Hz, route_high.eps_r,
                                route_high.num_mesh_cells_per_wavelength)
    assert res_high < res_low, "Higher frequency must produce finer mesh"


def test_mesh_resolution_scales_with_wavelength():
    """Doubling f_cutoff should roughly halve mesh resolution."""
    f1 = 5e9
    f2 = 10e9
    eps_r = 4.4
    cells = 15
    r1 = _mesh_resolution(f1, eps_r, cells)
    r2 = _mesh_resolution(f2, eps_r, cells)
    # ratio should be close to 2 (within 1%)
    assert abs(r1 / r2 - 2.0) < 0.01, f"Expected ~2× ratio, got {r1/r2:.4f}"


def test_mesh_resolution_depends_on_eps_r():
    """Higher eps_r → slower wave → shorter wavelength → finer mesh."""
    r_air = _mesh_resolution(5e9, 1.0, 15)
    r_fr4 = _mesh_resolution(5e9, 4.4, 15)
    assert r_fr4 < r_air, "FR-4 medium must give finer mesh than air"


def test_mesh_resolution_capped_at_trace_thickness():
    """mesh_resolution_mm <= trace_thickness_mm / 2 for thin-trace accuracy."""
    # Use very low frequency so natural mesh would be coarse
    route = _make_default_route(
        f_cutoff_Hz=0.5e9,
        trace_thickness_mm=0.035,
        num_mesh_cells_per_wavelength=3,
    )
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        result = export_to_openems(route, xml_path)
        assert result.mesh_resolution_mm <= max(route.trace_thickness_mm / 2.0, 0.005) + 1e-9
    finally:
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 10. RectilinearGrid
# ---------------------------------------------------------------------------

def test_rectilinear_grid_present(default_export):
    _, tree, _ = default_export
    cs = tree.getroot().find("ContinuousStructure")
    grid = cs.find("RectilinearGrid")
    assert grid is not None, "<RectilinearGrid> must be present"


def test_grid_xlines_present(default_export):
    _, tree, _ = default_export
    xl = tree.getroot().find("ContinuousStructure/RectilinearGrid/XLines")
    assert xl is not None and xl.text and len(xl.text.strip()) > 0


def test_grid_ylines_present(default_export):
    _, tree, _ = default_export
    yl = tree.getroot().find("ContinuousStructure/RectilinearGrid/YLines")
    assert yl is not None and yl.text and len(yl.text.strip()) > 0


def test_grid_zlines_present(default_export):
    _, tree, _ = default_export
    zl = tree.getroot().find("ContinuousStructure/RectilinearGrid/ZLines")
    assert zl is not None and zl.text and len(zl.text.strip()) > 0


def test_grid_xlines_span_trace_length():
    route = _make_default_route(trace_length_mm=30.0)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        xl_text = tree.getroot().find("ContinuousStructure/RectilinearGrid/XLines").text
        values = [float(v) for v in xl_text.split(",")]
        assert min(values) < 0.0, "XLines must extend below 0 (air buffer)"
        assert max(values) > 30.0, "XLines must extend past trace_length_mm"
    finally:
        os.unlink(xml_path)


def test_grid_zlines_include_substrate_surface():
    route = _make_default_route(substrate_thickness_mm=1.6)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        export_to_openems(route, xml_path)
        tree = ET.parse(xml_path)
        zl_text = tree.getroot().find("ContinuousStructure/RectilinearGrid/ZLines").text
        values = [float(v) for v in zl_text.split(",")]
        # Substrate top surface at z=1.6 should be in z-lines or bracketed
        assert any(abs(v - 1.6) < 0.1 for v in values), \
            "ZLines must include a point near substrate top surface (z=1.6)"
    finally:
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 11. Return value fields
# ---------------------------------------------------------------------------

def test_result_xml_path_matches_requested(default_export):
    xml_path, _, result = default_export
    assert result.xml_path == xml_path


def test_result_num_primitives_positive(default_export):
    _, _, result = default_export
    assert result.num_primitives > 0


def test_result_num_ports_equals_route_ports(default_export):
    route = _make_default_route()
    _, _, result = default_export
    assert result.num_ports == len(route.ports)


def test_result_honest_caveat_non_empty(default_export):
    _, _, result = default_export
    assert len(result.honest_caveat) > 20


def test_result_honest_caveat_mentions_openems(default_export):
    _, _, result = default_export
    assert "openEMS" in result.honest_caveat


def test_result_honest_caveat_warns_file_only(default_export):
    _, _, result = default_export
    caveat_upper = result.honest_caveat.upper()
    assert "FILE EXPORT ONLY" in caveat_upper or "NOT INVOKED" in caveat_upper or "NOT invoke" in result.honest_caveat


# ---------------------------------------------------------------------------
# 12. num_primitives count is consistent with XML
# ---------------------------------------------------------------------------

def test_num_primitives_matches_xml_count(default_export):
    _, tree, result = default_export
    prims = tree.getroot().find("ContinuousStructure/Primitives")
    xml_count = (
        len(prims.findall("Box"))
        + len(prims.findall("Probe"))
        + len(prims.findall("DumpBox"))
    )
    assert result.num_primitives == xml_count, (
        f"num_primitives={result.num_primitives} but XML has {xml_count} primitive elements"
    )


# ---------------------------------------------------------------------------
# 13. Round-trip XML validity after export
# ---------------------------------------------------------------------------

def test_xml_round_trip_parse(default_export):
    xml_path, _, _ = default_export
    # Parse twice — second parse from file confirms no mutation
    tree1 = ET.parse(xml_path)
    tree2 = ET.parse(xml_path)
    assert tree1.getroot().tag == tree2.getroot().tag


# ---------------------------------------------------------------------------
# 14. Three-port route
# ---------------------------------------------------------------------------

def test_three_port_route():
    route = _make_default_route(ports=["P1", "P2", "P3"])
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    try:
        result = export_to_openems(route, xml_path)
        assert result.num_ports == 3
        tree = ET.parse(xml_path)
        prims = tree.getroot().find("ContinuousStructure/Primitives")
        probe_names = {p.attrib.get("name", "") for p in prims.findall("Probe")}
        for pname in ("P1_V", "P1_I", "P2_V", "P2_I", "P3_V", "P3_I"):
            assert pname in probe_names, f"Probe {pname} missing for 3-port"
    finally:
        os.unlink(xml_path)


# ---------------------------------------------------------------------------
# 15. Helper: _c_in_medium
# ---------------------------------------------------------------------------

def test_c_in_medium_vacuum():
    c = _c_in_medium(1.0)
    assert c == pytest.approx(2.998e8, rel=1e-3)


def test_c_in_medium_fr4():
    c = _c_in_medium(4.4)
    expected = 2.998e8 / math.sqrt(4.4)
    assert c == pytest.approx(expected, rel=1e-6)
