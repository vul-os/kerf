"""Tests for compile_with_distributor (T-197 wiring into T-195 compile flow).

Verifies that after calling compile_with_distributor:
  - source_component records are enriched with distributor part metadata
    (distributor_part_number, distributor_url, manufacturer, lcsc_part)
  - Unresolved components carry warnings: ["unresolved"]
  - Non source_component records are passed through unchanged
  - voltage_divider: both resistors resolve to LCSC mock parts
  - rc_filter: resistor + capacitor both resolve
  - unmatched value: warning present, Circuit JSON otherwise valid

All tests are hermetic (no network calls).
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

import pytest

from kerf_electronics.atopile.compile_with_dist import compile_with_distributor
from kerf_electronics.atopile.library import MockCatalogue

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "atopile"
MIXED_FIXTURE = FIXTURES / "jlcpcb_mixed.json"
RESISTORS_FIXTURE = FIXTURES / "jlcpcb_resistors.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _by_type(cj: List[dict], *types: str) -> List[dict]:
    type_set = set(types)
    return [r for r in cj if isinstance(r, dict) and r.get("type") in type_set]


def _mock_cat(fixture: pathlib.Path = MIXED_FIXTURE) -> MockCatalogue:
    return MockCatalogue(fixture)


# ---------------------------------------------------------------------------
# T-197-wire-1  voltage_divider — both resistors resolved
# ---------------------------------------------------------------------------


def test_voltage_divider_compiles_successfully():
    """compile_with_distributor returns a non-empty list for voltage_divider."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    assert isinstance(cj, list)
    assert len(cj) > 0


def test_voltage_divider_two_source_components():
    """voltage_divider emits exactly 2 source_component records."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2, f"Expected 2 source_component, got {len(comps)}"


def test_voltage_divider_resistors_have_lcsc_part():
    """Both resistor source_component records carry an lcsc_part field."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    for comp in comps:
        assert "lcsc_part" in comp, (
            f"Expected 'lcsc_part' on component {comp.get('name')!r}: {comp}"
        )
        assert comp["lcsc_part"], (
            f"'lcsc_part' is empty on component {comp.get('name')!r}"
        )


def test_voltage_divider_resistors_have_distributor_part_number():
    """Both resistors carry a distributor_part_number."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    for comp in comps:
        assert "distributor_part_number" in comp, (
            f"Missing distributor_part_number on {comp.get('name')!r}"
        )


def test_voltage_divider_r1_resolves_10k():
    """R1 (10kohm) resolves to the LCSC 10k resistor (C25076)."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    r1 = next((c for c in comps if c.get("name") == "R1"), None)
    assert r1 is not None, "R1 component not found"
    assert r1.get("lcsc_part") == "C25076", (
        f"R1 should resolve to C25076 (10k), got {r1.get('lcsc_part')!r}"
    )


def test_voltage_divider_r2_resolves_1k():
    """R2 (1kohm) resolves to the LCSC 1k resistor (C26022)."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    r2 = next((c for c in comps if c.get("name") == "R2"), None)
    assert r2 is not None, "R2 component not found"
    assert r2.get("lcsc_part") == "C26022", (
        f"R2 should resolve to C26022 (1k), got {r2.get('lcsc_part')!r}"
    )


def test_voltage_divider_no_unresolved_warnings():
    """Neither resistor should have an unresolved warning."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    for comp in comps:
        warnings = comp.get("warnings", [])
        assert "unresolved" not in warnings, (
            f"Component {comp.get('name')!r} unexpectedly has 'unresolved' warning"
        )


def test_voltage_divider_manufacturer_present():
    """Resolved components carry a non-empty manufacturer field."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    for comp in comps:
        assert "manufacturer" in comp, (
            f"Missing 'manufacturer' on {comp.get('name')!r}"
        )


def test_voltage_divider_nets_untouched():
    """source_net records are passed through without modification."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    nets = _by_type(cj, "source_net")
    assert len(nets) == 3
    net_names = {n["name"] for n in nets}
    assert net_names == {"vin", "vout", "gnd"}


# ---------------------------------------------------------------------------
# T-197-wire-2  rc_filter — resistor + capacitor both resolve
# ---------------------------------------------------------------------------


def test_rc_filter_compiles():
    """rc_filter.ato compiles without error."""
    cj = compile_with_distributor(
        load("rc_filter.ato"),
        catalogue=_mock_cat(),
    )
    assert isinstance(cj, list)
    assert len(cj) > 0


def test_rc_filter_two_source_components():
    """rc_filter emits exactly 2 source_component records (R + C)."""
    cj = compile_with_distributor(
        load("rc_filter.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2, f"Expected 2 source_component, got {len(comps)}"


def test_rc_filter_resistor_resolves():
    """R1 (1kohm) in rc_filter resolves to an LCSC part."""
    cj = compile_with_distributor(
        load("rc_filter.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    resistors = [c for c in comps if "R" in c.get("name", "")]
    assert len(resistors) >= 1, "No resistor found in rc_filter output"
    for r in resistors:
        assert r.get("lcsc_part"), (
            f"Resistor {r.get('name')!r} did not resolve: {r}"
        )


def test_rc_filter_capacitor_resolves():
    """C1 (100nF) in rc_filter resolves to an LCSC part."""
    cj = compile_with_distributor(
        load("rc_filter.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    caps = [c for c in comps if "C" in c.get("name", "")]
    assert len(caps) >= 1, "No capacitor found in rc_filter output"
    for cap in caps:
        assert cap.get("lcsc_part"), (
            f"Capacitor {cap.get('name')!r} did not resolve: {cap}"
        )


def test_rc_filter_no_unresolved_warnings():
    """Both components in rc_filter should resolve without warnings."""
    cj = compile_with_distributor(
        load("rc_filter.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    for comp in comps:
        warnings = comp.get("warnings", [])
        assert "unresolved" not in warnings, (
            f"Component {comp.get('name')!r} has unexpected 'unresolved' warning"
        )


# ---------------------------------------------------------------------------
# T-197-wire-3  unmatched value → warning (no exception)
# ---------------------------------------------------------------------------

_UNMATCHED_ATO = """\
import Resistor from "generics/resistors.ato"

module UnmatchedResistor:
    signal vin
    signal gnd
    r1 = new Resistor
    r1.value = 999kohm
    r1.p1 ~ vin
    r1.p2 ~ gnd
"""


def test_unmatched_value_returns_circuit_json():
    """An unmatched component value does not raise; returns a valid Circuit JSON."""
    cj = compile_with_distributor(
        _UNMATCHED_ATO,
        catalogue=_mock_cat(),
    )
    assert isinstance(cj, list)
    comps = _by_type(cj, "source_component")
    assert len(comps) == 1


def test_unmatched_value_has_unresolved_warning():
    """An unmatched component has warnings=['unresolved']."""
    cj = compile_with_distributor(
        _UNMATCHED_ATO,
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    assert len(comps) == 1
    comp = comps[0]
    warnings = comp.get("warnings", [])
    assert "unresolved" in warnings, (
        f"Expected 'unresolved' in warnings, got: {warnings}"
    )


def test_unmatched_value_no_lcsc_part():
    """An unmatched component does NOT have an lcsc_part key."""
    cj = compile_with_distributor(
        _UNMATCHED_ATO,
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    comp = comps[0]
    assert "lcsc_part" not in comp, (
        f"Unmatched component should not have 'lcsc_part': {comp}"
    )


def test_unmatched_value_other_records_intact():
    """source_net and other records are present even when a component is unresolved."""
    cj = compile_with_distributor(
        _UNMATCHED_ATO,
        catalogue=_mock_cat(),
    )
    nets = _by_type(cj, "source_net")
    assert len(nets) >= 1, "source_net records missing"


# ---------------------------------------------------------------------------
# T-197-wire-4  dist_mode parameter
# ---------------------------------------------------------------------------


def test_dist_mode_mock_uses_mock_catalogue(monkeypatch):
    """dist_mode='mock' should not raise even when no live catalogue is present."""
    # We rely on the default fixture being on disk (which it is in the worktree)
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        dist_mode="mock",
    )
    assert isinstance(cj, list)
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2


def test_catalogue_kwarg_overrides_dist_mode():
    """Explicit catalogue= kwarg overrides dist_mode."""
    cat = _mock_cat(RESISTORS_FIXTURE)
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        dist_mode="live",   # would normally use live, but catalogue= takes precedence
        catalogue=cat,
    )
    comps = _by_type(cj, "source_component")
    # Both resistors should still resolve from the mock catalogue
    resolved = [c for c in comps if "lcsc_part" in c and c["lcsc_part"]]
    assert len(resolved) == 2


# ---------------------------------------------------------------------------
# T-197-wire-5  Circuit JSON schema preservation
# ---------------------------------------------------------------------------


def test_source_component_type_field_preserved():
    """Enriched source_component records still have type='source_component'."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    for comp in comps:
        assert comp["type"] == "source_component"


def test_pcb_records_pass_through_unchanged():
    """pcb_component and pcb_smtpad records are not modified."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    pcb_comps = _by_type(cj, "pcb_component")
    pads = _by_type(cj, "pcb_smtpad")
    assert len(pcb_comps) == 2
    assert len(pads) > 0
    for rec in pcb_comps + pads:
        assert "lcsc_part" not in rec


def test_source_traces_present():
    """source_trace records are emitted and not disturbed."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        catalogue=_mock_cat(),
    )
    traces = _by_type(cj, "source_trace")
    assert len(traces) > 0


def test_top_module_kwarg_respected():
    """top_module= kwarg is forwarded to compile_ato correctly."""
    cj = compile_with_distributor(
        load("voltage_divider.ato"),
        top_module="VoltageDivider",
        catalogue=_mock_cat(),
    )
    comps = _by_type(cj, "source_component")
    assert len(comps) == 2


def test_invalid_top_module_raises():
    """An unknown top_module raises ValueError (propagated from compile_ato)."""
    with pytest.raises(ValueError, match="NonExistent"):
        compile_with_distributor(
            load("voltage_divider.ato"),
            top_module="NonExistent",
            catalogue=_mock_cat(),
        )
