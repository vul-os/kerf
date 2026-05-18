"""Tests for the atopile → Circuit JSON compiler (T-195)."""
from __future__ import annotations

import pathlib
from typing import List

import pytest

from kerf_electronics.atopile.compile import compile_ato
from kerf_electronics.kicad_io import circuit_json_to_kicad_pcb

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "atopile"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _by_type(cj: List[dict], *types: str) -> List[dict]:
    type_set = set(types)
    return [r for r in cj if isinstance(r, dict) and r.get("type") in type_set]


# ===========================================================================
# T-195-1  voltage_divider.ato → 2 source_component + 3 source_net
# ===========================================================================


def test_voltage_divider_source_components():
    cj = compile_ato(load("voltage_divider.ato"))
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2, f"Expected 2 source_component, got {len(comps)}: {comps}"


def test_voltage_divider_component_refs():
    cj = compile_ato(load("voltage_divider.ato"))
    comps = _by_type(cj, "source_component")
    names = {c["name"] for c in comps}
    assert names == {"R1", "R2"}, f"Expected {{R1, R2}}, got {names}"


def test_voltage_divider_source_nets():
    cj = compile_ato(load("voltage_divider.ato"))
    nets = _by_type(cj, "source_net")
    assert len(nets) == 3, f"Expected 3 source_net, got {len(nets)}: {[n['name'] for n in nets]}"


def test_voltage_divider_net_names():
    cj = compile_ato(load("voltage_divider.ato"))
    nets = _by_type(cj, "source_net")
    net_names = {n["name"] for n in nets}
    assert "vin" in net_names, f"Missing 'vin' in {net_names}"
    assert "vout" in net_names, f"Missing 'vout' in {net_names}"
    assert "gnd" in net_names, f"Missing 'gnd' in {net_names}"


def test_voltage_divider_pcb_components():
    cj = compile_ato(load("voltage_divider.ato"))
    pcb_comps = _by_type(cj, "pcb_component")
    assert len(pcb_comps) == 2, f"Expected 2 pcb_component, got {len(pcb_comps)}"


def test_voltage_divider_component_values():
    cj = compile_ato(load("voltage_divider.ato"))
    comps = _by_type(cj, "source_component")
    values = {c["name"]: c["value"] for c in comps}
    # r1.value = 10kohm, r2.value = 1kohm
    assert values.get("R1") == "10kohm", f"R1 value: {values.get('R1')}"
    assert values.get("R2") == "1kohm", f"R2 value: {values.get('R2')}"


def test_voltage_divider_resistor_footprints():
    cj = compile_ato(load("voltage_divider.ato"))
    comps = _by_type(cj, "source_component")
    for c in comps:
        assert c["footprint"] == "Device:R", f"Wrong footprint: {c['footprint']}"


def test_voltage_divider_source_traces_connect_to_nets():
    cj = compile_ato(load("voltage_divider.ato"))
    traces = _by_type(cj, "source_trace")
    nets = _by_type(cj, "source_net")
    net_ids = {n["source_net_id"] for n in nets}

    # Every source_trace must reference at least one known net
    for t in traces:
        for nid in t.get("connected_source_net_ids", []):
            assert nid in net_ids, f"trace {t['source_trace_id']} refs unknown net {nid}"


def test_voltage_divider_all_pins_assigned_to_nets():
    """Each pin in r1.p1~vin, r1.p2~vout, r2.p1~vout, r2.p2~gnd must appear in a trace."""
    cj = compile_ato(load("voltage_divider.ato"))
    traces = _by_type(cj, "source_trace")
    all_port_ids = {pid for t in traces for pid in t.get("connected_source_port_ids", [])}
    # We expect port IDs for r1.p1, r1.p2, r2.p1, r2.p2
    expected = {"sp_r1_p1", "sp_r1_p2", "sp_r2_p1", "sp_r2_p2"}
    assert expected <= all_port_ids, (
        f"Missing port IDs. Expected subset {expected}, got {all_port_ids}"
    )


# ===========================================================================
# T-195-2  led_driver.ato → 1 Resistor + 1 LED + 2 source_net
# ===========================================================================


def test_led_driver_source_components():
    cj = compile_ato(load("led_driver.ato"))
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2, f"Expected 2 source_component, got {len(comps)}"


def test_led_driver_one_resistor_one_led():
    cj = compile_ato(load("led_driver.ato"))
    comps = _by_type(cj, "source_component")
    footprints = {c["footprint"] for c in comps}
    assert "Device:R" in footprints, f"No resistor footprint in {footprints}"
    assert "Device:LED" in footprints, f"No LED footprint in {footprints}"


def test_led_driver_source_nets():
    """led_driver has signals vcc, gnd, ctrl — at least 2 wired nets."""
    cj = compile_ato(load("led_driver.ato"))
    nets = _by_type(cj, "source_net")
    # vcc and gnd are connected; ctrl is declared but not connected to pins
    net_names = {n["name"] for n in nets}
    assert "vcc" in net_names, f"Missing vcc in {net_names}"
    assert "gnd" in net_names, f"Missing gnd in {net_names}"


def test_led_driver_net_count():
    """voltage: vcc, gnd, ctrl + possibly auto-net for r1.p2~led1.anode."""
    cj = compile_ato(load("led_driver.ato"))
    nets = _by_type(cj, "source_net")
    # Minimum: vcc + gnd = 2 declared signal nets used in connections
    # ctrl is declared but not connected to any pin so still appears as a net
    assert len(nets) >= 2, f"Expected at least 2 nets, got {len(nets)}"


def test_led_driver_r1_value():
    cj = compile_ato(load("led_driver.ato"))
    comps = _by_type(cj, "source_component")
    r_comps = [c for c in comps if c["footprint"] == "Device:R"]
    assert r_comps, "No resistor found"
    assert r_comps[0]["value"] == "330ohm", f"R1 value: {r_comps[0]['value']}"


def test_led_driver_led_color_attr():
    cj = compile_ato(load("led_driver.ato"))
    comps = _by_type(cj, "source_component")
    led_comps = [c for c in comps if c["footprint"] == "Device:LED"]
    assert led_comps, "No LED found"
    attrs = led_comps[0].get("attrs", {})
    assert attrs.get("color") == "red", f"LED color attr: {attrs}"


def test_led_driver_pcb_components():
    cj = compile_ato(load("led_driver.ato"))
    pcb_comps = _by_type(cj, "pcb_component")
    assert len(pcb_comps) == 2, f"Expected 2 pcb_component, got {len(pcb_comps)}"


# ===========================================================================
# T-195-3  rc_filter.ato → 1 Resistor + 1 Capacitor
# ===========================================================================


def test_rc_filter_source_components():
    cj = compile_ato(load("rc_filter.ato"))
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2, f"Expected 2 source_component, got {len(comps)}"


def test_rc_filter_one_r_one_c():
    cj = compile_ato(load("rc_filter.ato"))
    comps = _by_type(cj, "source_component")
    footprints = {c["footprint"] for c in comps}
    assert "Device:R" in footprints, f"No resistor footprint in {footprints}"
    assert "Device:C" in footprints, f"No capacitor footprint in {footprints}"


def test_rc_filter_source_nets():
    cj = compile_ato(load("rc_filter.ato"))
    nets = _by_type(cj, "source_net")
    net_names = {n["name"] for n in nets}
    assert "vin" in net_names, f"Missing vin in {net_names}"
    assert "vout" in net_names, f"Missing vout in {net_names}"
    assert "gnd" in net_names, f"Missing gnd in {net_names}"


def test_rc_filter_r1_value():
    cj = compile_ato(load("rc_filter.ato"))
    comps = _by_type(cj, "source_component")
    r_comps = [c for c in comps if c["footprint"] == "Device:R"]
    assert r_comps[0]["value"] == "1kohm"


def test_rc_filter_c1_value():
    cj = compile_ato(load("rc_filter.ato"))
    comps = _by_type(cj, "source_component")
    c_comps = [c for c in comps if c["footprint"] == "Device:C"]
    assert c_comps[0]["value"] == "100nF"


def test_rc_filter_pcb_components():
    cj = compile_ato(load("rc_filter.ato"))
    pcb_comps = _by_type(cj, "pcb_component")
    assert len(pcb_comps) == 2, f"Expected 2 pcb_component, got {len(pcb_comps)}"


# ===========================================================================
# T-195-4  Round-trip via kicad_io: compile → KiCad PCB → parseable text
# ===========================================================================


def test_voltage_divider_round_trip_kicad():
    cj = compile_ato(load("voltage_divider.ato"))
    kicad_text = circuit_json_to_kicad_pcb(cj)
    assert isinstance(kicad_text, str), "kicad_text must be a string"
    assert "kicad_pcb" in kicad_text, "Output is not a KiCad PCB file"
    # Check it has net declarations
    assert "net" in kicad_text, "Missing net declarations"
    # Check it has footprint blocks
    assert "footprint" in kicad_text, "Missing footprint blocks"


def test_led_driver_round_trip_kicad():
    cj = compile_ato(load("led_driver.ato"))
    kicad_text = circuit_json_to_kicad_pcb(cj)
    assert "kicad_pcb" in kicad_text
    assert "footprint" in kicad_text


def test_rc_filter_round_trip_kicad():
    cj = compile_ato(load("rc_filter.ato"))
    kicad_text = circuit_json_to_kicad_pcb(cj)
    assert "kicad_pcb" in kicad_text
    assert "footprint" in kicad_text


def test_voltage_divider_kicad_contains_nets():
    cj = compile_ato(load("voltage_divider.ato"))
    kicad_text = circuit_json_to_kicad_pcb(cj)
    # vin, vout, gnd should appear as net names
    assert '"vin"' in kicad_text or "vin" in kicad_text, "Missing vin net in KiCad output"
    assert '"vout"' in kicad_text or "vout" in kicad_text, "Missing vout net in KiCad output"
    assert '"gnd"' in kicad_text or "gnd" in kicad_text, "Missing gnd net in KiCad output"


def test_voltage_divider_kicad_parseable():
    """KiCad output must start with '(kicad_pcb' — a valid s-expression."""
    cj = compile_ato(load("voltage_divider.ato"))
    kicad_text = circuit_json_to_kicad_pcb(cj)
    stripped = kicad_text.strip()
    assert stripped.startswith("(kicad_pcb"), (
        f"KiCad output must start with '(kicad_pcb', got: {stripped[:80]!r}"
    )
    # Must end with matching parenthesis
    assert stripped.endswith(")"), "KiCad output must end with ')'"


# ===========================================================================
# T-195-5  Schema integrity checks
# ===========================================================================


def test_source_component_has_required_fields():
    cj = compile_ato(load("voltage_divider.ato"))
    comps = _by_type(cj, "source_component")
    for c in comps:
        assert "source_component_id" in c, f"Missing source_component_id in {c}"
        assert "name" in c, f"Missing name in {c}"
        assert "footprint" in c, f"Missing footprint in {c}"
        assert "type" in c, f"Missing type in {c}"


def test_source_net_has_required_fields():
    cj = compile_ato(load("voltage_divider.ato"))
    nets = _by_type(cj, "source_net")
    for n in nets:
        assert "source_net_id" in n, f"Missing source_net_id in {n}"
        assert "name" in n, f"Missing name in {n}"


def test_pcb_component_has_required_fields():
    cj = compile_ato(load("voltage_divider.ato"))
    pcb_comps = _by_type(cj, "pcb_component")
    for p in pcb_comps:
        assert "pcb_component_id" in p, f"Missing pcb_component_id in {p}"
        assert "source_component_id" in p, f"Missing source_component_id in {p}"
        assert "x" in p, f"Missing x in {p}"
        assert "y" in p, f"Missing y in {p}"
        assert "layer" in p, f"Missing layer in {p}"


def test_source_component_ids_are_unique():
    cj = compile_ato(load("voltage_divider.ato"))
    comps = _by_type(cj, "source_component")
    ids = [c["source_component_id"] for c in comps]
    assert len(ids) == len(set(ids)), f"Duplicate source_component_id: {ids}"


def test_source_net_ids_are_unique():
    cj = compile_ato(load("voltage_divider.ato"))
    nets = _by_type(cj, "source_net")
    ids = [n["source_net_id"] for n in nets]
    assert len(ids) == len(set(ids)), f"Duplicate source_net_id: {ids}"


def test_pcb_component_links_to_source_component():
    cj = compile_ato(load("voltage_divider.ato"))
    sc_ids = {c["source_component_id"] for c in _by_type(cj, "source_component")}
    for pc in _by_type(cj, "pcb_component"):
        assert pc["source_component_id"] in sc_ids, (
            f"pcb_component {pc['pcb_component_id']} references unknown "
            f"source_component_id {pc['source_component_id']}"
        )


# ===========================================================================
# T-195-6  Error handling
# ===========================================================================


def test_compile_empty_source_raises():
    with pytest.raises((ValueError, Exception)):
        compile_ato("")


def test_compile_no_module_raises():
    with pytest.raises(ValueError, match="No module block"):
        compile_ato("import Resistor from \"generics/resistors.ato\"\n")


def test_compile_nonexistent_top_module_raises():
    with pytest.raises(ValueError, match="not found"):
        compile_ato(load("voltage_divider.ato"), top_module="DoesNotExist")


def test_compile_explicit_top_module():
    cj = compile_ato(load("voltage_divider.ato"), top_module="VoltageDivider")
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2
