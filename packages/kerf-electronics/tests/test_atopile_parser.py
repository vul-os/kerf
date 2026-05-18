"""Tests for the atopile `.ato` parser (T-194)."""
from __future__ import annotations

import pathlib
from typing import List

import pytest

from kerf_electronics.atopile import parse
from kerf_electronics.atopile.ast import (
    Assignment,
    ComponentBlock,
    ComponentInstance,
    Connection,
    DottedName,
    ImportStatement,
    ModuleBlock,
    Module,
    PinDecl,
    QuantityLiteral,
    SignalDecl,
    StringLiteral,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "atopile"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# Helper: collect nodes of a specific type from a block body (recursively)
# ---------------------------------------------------------------------------


def _collect(nodes, *types):
    """Collect all nodes of one of *types* from a list, non-recursively."""
    return [n for n in nodes if isinstance(n, tuple(types))]


def _collect_from_module(module: Module, *types):
    """Collect nodes of *types* from every block body in *module*."""
    found = []
    for block in module.blocks:
        if hasattr(block, "body"):
            found.extend(_collect(block.body, *types))
    return found


# ===========================================================================
# T-194-1  All four fixtures parse without errors and produce a non-empty AST
# ===========================================================================


@pytest.mark.parametrize(
    "filename",
    ["resistor.ato", "voltage_divider.ato", "rc_filter.ato", "led_driver.ato"],
)
def test_fixtures_parse_non_empty(filename: str):
    source = load(filename)
    root = parse(source)
    assert isinstance(root, Module)
    # Must have at least one import or one block
    assert root.imports or root.blocks, f"{filename} produced an empty AST"


# ===========================================================================
# T-194-2  voltage_divider.ato: 2 component_instance nodes + 4 connection nodes
# ===========================================================================


def test_voltage_divider_instances_and_connections():
    root = parse(load("voltage_divider.ato"))

    instances = _collect_from_module(root, ComponentInstance)
    connections = _collect_from_module(root, Connection)

    assert len(instances) == 2, f"Expected 2 component instances, got {len(instances)}"
    assert len(connections) == 4, f"Expected 4 connections, got {len(connections)}"

    # Verify instance names
    names = {i.instance_name for i in instances}
    assert names == {"r1", "r2"}

    # Verify type names
    types = {i.type_name for i in instances}
    assert types == {"Resistor"}


def test_voltage_divider_instance_types():
    root = parse(load("voltage_divider.ato"))
    instances = _collect_from_module(root, ComponentInstance)
    for inst in instances:
        assert inst.type_name == "Resistor"


def test_voltage_divider_connection_targets():
    root = parse(load("voltage_divider.ato"))
    connections = _collect_from_module(root, Connection)
    # Collect all left/right names
    left_names = {c.left.name for c in connections}
    right_names = {c.right.name for c in connections}
    assert "r1.p1" in left_names
    assert "r1.p2" in left_names
    assert "r2.p1" in left_names
    assert "r2.p2" in left_names
    assert "vin" in right_names
    assert "vout" in right_names
    assert "gnd" in right_names


# ===========================================================================
# T-194-3  rc_filter.ato: 1 Resistor + 1 Capacitor instance
# ===========================================================================


def test_rc_filter_one_r_one_c():
    root = parse(load("rc_filter.ato"))
    instances = _collect_from_module(root, ComponentInstance)

    type_counts: dict[str, int] = {}
    for inst in instances:
        type_counts[inst.type_name] = type_counts.get(inst.type_name, 0) + 1

    assert type_counts.get("Resistor", 0) == 1, (
        f"Expected 1 Resistor, got {type_counts.get('Resistor', 0)}"
    )
    assert type_counts.get("Capacitor", 0) == 1, (
        f"Expected 1 Capacitor, got {type_counts.get('Capacitor', 0)}"
    )


def test_rc_filter_imports():
    root = parse(load("rc_filter.ato"))
    assert len(root.imports) == 2
    paths = {imp.path for imp in root.imports}
    assert "generics/resistors.ato" in paths
    assert "generics/capacitors.ato" in paths


# ===========================================================================
# T-194-4  AST nodes carry correct line numbers
# ===========================================================================


def test_import_line_numbers():
    root = parse(load("voltage_divider.ato"))
    # ``import Resistor from ...`` is the very first line
    assert len(root.imports) == 1
    imp = root.imports[0]
    assert imp.loc.line == 1, f"Import should be on line 1, got {imp.loc.line}"


def test_module_block_line_number():
    root = parse(load("voltage_divider.ato"))
    assert len(root.blocks) == 1
    block = root.blocks[0]
    # ``module VoltageDivider:`` is line 3 (after import + blank line)
    assert block.loc.line == 3, f"Module block should be on line 3, got {block.loc.line}"


def test_signal_decl_line_numbers():
    root = parse(load("voltage_divider.ato"))
    block = root.blocks[0]
    signals = _collect(block.body, SignalDecl)
    assert len(signals) == 3
    # First signal (vin) is on line 4
    assert signals[0].loc.line == 4, (
        f"First signal should be on line 4, got {signals[0].loc.line}"
    )
    assert signals[0].name == "vin"


def test_component_instance_line_numbers():
    root = parse(load("voltage_divider.ato"))
    block = root.blocks[0]
    instances = _collect(block.body, ComponentInstance)
    # r1 = new Resistor  is line 7 (signals on 4,5,6)
    assert instances[0].loc.line == 7, (
        f"r1 instance should be on line 7, got {instances[0].loc.line}"
    )
    # r2 = new Resistor  is line 9
    assert instances[1].loc.line == 9, (
        f"r2 instance should be on line 9, got {instances[1].loc.line}"
    )


def test_connection_line_numbers():
    root = parse(load("voltage_divider.ato"))
    block = root.blocks[0]
    connections = _collect(block.body, Connection)
    # First connection (r1.p1 ~ vin) is line 11
    assert connections[0].loc.line == 11, (
        f"First connection should be on line 11, got {connections[0].loc.line}"
    )


# ===========================================================================
# T-194-5  Quantity literals are parsed correctly
# ===========================================================================


def test_quantity_units_voltage_divider():
    root = parse(load("voltage_divider.ato"))
    block = root.blocks[0]
    assignments = _collect(block.body, Assignment)

    qty_map: dict[str, QuantityLiteral] = {}
    for a in assignments:
        if isinstance(a.value, QuantityLiteral):
            qty_map[a.target.name] = a.value

    assert "r1.value" in qty_map
    assert "r2.value" in qty_map

    r1_val = qty_map["r1.value"]
    assert r1_val.raw == "10kohm"
    assert r1_val.value == pytest.approx(10_000.0)

    r2_val = qty_map["r2.value"]
    assert r2_val.raw == "1kohm"
    assert r2_val.value == pytest.approx(1_000.0)


def test_quantity_units_rc_filter():
    root = parse(load("rc_filter.ato"))
    block = root.blocks[0]
    assignments = _collect(block.body, Assignment)

    qty_map: dict[str, QuantityLiteral] = {}
    for a in assignments:
        if isinstance(a.value, QuantityLiteral):
            qty_map[a.target.name] = a.value

    assert "c1.value" in qty_map
    c1_val = qty_map["c1.value"]
    assert c1_val.raw == "100nF"
    assert c1_val.value == pytest.approx(100e-9)


# ===========================================================================
# T-194-6  led_driver.ato: string literal assignment parses correctly
# ===========================================================================


def test_led_driver_string_assignment():
    root = parse(load("led_driver.ato"))
    block = root.blocks[0]
    assignments = _collect(block.body, Assignment)

    str_assignments = [a for a in assignments if isinstance(a.value, StringLiteral)]
    assert len(str_assignments) == 1
    assert str_assignments[0].value.value == "red"
    assert str_assignments[0].target.name == "led1.color"


def test_led_driver_connection_count():
    root = parse(load("led_driver.ato"))
    connections = _collect_from_module(root, Connection)
    assert len(connections) == 3


# ===========================================================================
# T-194-7  resistor.ato: component block with pin declarations
# ===========================================================================


def test_resistor_component_block():
    root = parse(load("resistor.ato"))
    component_blocks = [b for b in root.blocks if isinstance(b, ComponentBlock)]
    assert len(component_blocks) == 1
    block = component_blocks[0]
    assert block.name == "Resistor"

    pins = _collect(block.body, PinDecl)
    assert len(pins) == 2
    pin_names = {p.name for p in pins}
    assert pin_names == {"p1", "p2"}


# ===========================================================================
# T-194-8  DottedName parts are correct
# ===========================================================================


def test_dotted_name_parts():
    root = parse(load("voltage_divider.ato"))
    block = root.blocks[0]
    connections = _collect(block.body, Connection)
    # r1.p1 ~ vin
    first = connections[0]
    assert first.left.parts == ["r1", "p1"]
    assert first.right.parts == ["vin"]
