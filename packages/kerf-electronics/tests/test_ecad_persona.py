"""
T-97  E2E ECAD persona — hermetic pytest.

Scope: import KiCad fixture → DRC → Gerber export → BOM → fab zip.

Success criteria (from testing-breakdown.md §T-97):
  - DRC report produced; violations list present
  - Gerber zip downloads (base64 decodable; zip well-formed)
  - BOM table renders (rows present; columns correct)
  - Cost roll-up against mocked distributor prices

All tests are hermetic: no network, no filesystem side-effects, no DB.
≥ 10 user-visible assertions.

Author: imranparuk
"""

from __future__ import annotations

import base64
import csv
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import pytest

# ─── imports from the electronics plugin ─────────────────────────────────────

from kerf_electronics.kicad_io import (
    circuit_json_to_kicad_pcb,
    kicad_pcb_to_circuit_json,
)
from kerf_electronics.tools.pcb_drc import _run_drc_on_circuit, _DEFAULT_RULES
from kerf_electronics.fab.gerber import export_gerber
from kerf_electronics.fab.excellon import export_excellon, _collect_hits
from kerf_electronics.fab.pnp import export_pnp
from kerf_electronics.fab.fab_bom import (
    _extract_bom_rows,
    export_fab_bom,
    _pick_cheapest_distributor,
)
from kerf_electronics.fab.ipc2581 import export_ipc2581
from kerf_electronics.tools.bom_cost import _compute_cost_rollup, _select_price
from kerf_electronics._compat import Registry as _ElecRegistry


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _call_tool_sync(tool_name: str, args: dict) -> dict:
    """Call a tool registered in the electronics _compat Registry synchronously."""
    import asyncio
    tool = next(
        (t for t in _ElecRegistry if t.spec.name == tool_name),
        None,
    )
    assert tool is not None, f"Tool {tool_name!r} not found in electronics Registry"
    raw = asyncio.new_event_loop().run_until_complete(
        tool.run(None, json.dumps(args).encode())
    )
    return json.loads(raw)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

# Minimal KiCad PCB board in s-expression format that can be imported
_KICAD_PCB_FIXTURE = """\
(kicad_pcb
  version 20211014
  generator kerf_ecad_persona_test
  (general (thickness 1.6))
  (paper A4)
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user)
  )
  (setup
    (rules
      (min_clearance "0.0")
      (min_track_width "0.0")
      (min_via_annular_width "0.0")
      (min_via_diameter "0.0")
      (min_hole_to_hole "0.0")
      (allow_microvias 0)
      (allow_blind_buried_vias 0)
      (aux_axis_origin 0)
    )
    (grid_origin "0 0")
  )
  (net 0 "")
  (net 1 "VCC")
  (net 2 "GND")
  (net 3 "SIG")
  (footprint "R_0402"
    (layer "F.Cu")
    (tstamp "fp_u1")
    (at 10.0000 15.0000)
    (fp_text reference "U1" (at 0 -1.0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value "MCU" (at 0 1.0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
  )
  (footprint "R_0402"
    (layer "F.Cu")
    (tstamp "fp_r1")
    (at 30.0000 15.0000)
    (fp_text reference "R1" (at 0 -1.0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value "10k" (at 0 1.0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
  )
  (footprint "C_0402"
    (layer "B.Cu")
    (tstamp "fp_c1")
    (at 50.0000 15.0000)
    (fp_text reference "C1" (at 0 -1.0) (layer "B.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value "100n" (at 0 1.0) (layer "B.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
  )
  (segment
    (start 9.0000 15.0000)
    (end 11.0000 15.0000)
    (width 0.2500)
    (layer "F.Cu")
    (net 1)
  )
  (segment
    (start 29.0000 15.0000)
    (end 31.0000 15.0000)
    (width 0.2500)
    (layer "F.Cu")
    (net 2)
  )
)
"""

# Build a rich CircuitJSON board for DRC + fab export tests
def _make_ecad_circuit() -> list[dict]:
    """A well-formed CircuitJSON simulating a KiCad import output.

    3 components (U1 MCU, R1 resistor, C1 capacitor), 2 vias, 3 pads,
    board outline 100×80 mm.
    """
    return [
        # board outline
        {"type": "pcb_board", "width": 100.0, "height": 80.0,
         "center_x": 50.0, "center_y": 40.0},

        # source components (for BOM)
        {"type": "source_component", "source_component_id": "sc_u1",
         "name": "U1", "value": "STM32F103", "footprint": "LQFP-48",
         "mpn": "STM32F103C8T6", "manufacturer": "STMicroelectronics",
         "description": "ARM Cortex-M3 MCU 64KB Flash",
         "distributors": [
             {"name": "DigiKey", "part_number": "497-6063-ND", "unit_price_usd": 2.50},
             {"name": "Mouser",  "part_number": "511-STM32F103C8T6", "unit_price_usd": 2.75},
         ]},
        {"type": "source_component", "source_component_id": "sc_r1",
         "name": "R1", "value": "10k", "footprint": "R_0402",
         "mpn": "RC0402FR-0710KL", "manufacturer": "Yageo",
         "description": "10k Resistor 0402",
         "distributors": [
             {"name": "DigiKey", "part_number": "311-10KLRCT-ND", "unit_price_usd": 0.10},
         ]},
        {"type": "source_component", "source_component_id": "sc_c1",
         "name": "C1", "value": "100n", "footprint": "C_0402",
         "mpn": "GRM155R61A104KA01D", "manufacturer": "Murata",
         "description": "100nF Capacitor 0402",
         "distributors": [
             {"name": "DigiKey", "part_number": "490-1318-1-ND", "unit_price_usd": 0.05},
         ]},
        {"type": "source_component", "source_component_id": "sc_r2",
         "name": "R2", "value": "10k", "footprint": "R_0402",
         "mpn": "RC0402FR-0710KL", "manufacturer": "Yageo",
         "description": "10k Resistor 0402",
         "distributors": [
             {"name": "DigiKey", "part_number": "311-10KLRCT-ND", "unit_price_usd": 0.10},
         ]},

        # pcb components (placed)
        {"type": "pcb_component", "pcb_component_id": "pcb_u1",
         "source_component_id": "sc_u1", "x": 10.0, "y": 15.0,
         "rotation": 0.0, "layer": "top_copper"},
        {"type": "pcb_component", "pcb_component_id": "pcb_r1",
         "source_component_id": "sc_r1", "x": 30.0, "y": 15.0,
         "rotation": 0.0, "layer": "top_copper"},
        {"type": "pcb_component", "pcb_component_id": "pcb_c1",
         "source_component_id": "sc_c1", "x": 50.0, "y": 15.0,
         "rotation": 0.0, "layer": "bottom_copper"},
        {"type": "pcb_component", "pcb_component_id": "pcb_r2",
         "source_component_id": "sc_r2", "x": 70.0, "y": 15.0,
         "rotation": 0.0, "layer": "top_copper"},

        # pads (well within 100×80 board, separated > 0.3 mm)
        {"type": "pcb_smtpad", "pcb_smtpad_id": "pad_u1_1",
         "source_component_id": "sc_u1", "x": 9.0, "y": 15.0,
         "width": 1.2, "height": 0.8, "shape": "rect",
         "layer": "top_copper", "net_id": "net_vcc"},
        {"type": "pcb_smtpad", "pcb_smtpad_id": "pad_r1_1",
         "source_component_id": "sc_r1", "x": 29.0, "y": 15.0,
         "width": 1.2, "height": 0.8, "shape": "rect",
         "layer": "top_copper", "net_id": "net_gnd"},
        {"type": "pcb_smtpad", "pcb_smtpad_id": "pad_c1_1",
         "source_component_id": "sc_c1", "x": 49.0, "y": 15.0,
         "width": 1.2, "height": 0.8, "shape": "rect",
         "layer": "bottom_copper", "net_id": "net_gnd"},

        # vias (well-spaced)
        {"type": "pcb_via", "pcb_via_id": "via_0",
         "x": 20.0, "y": 40.0, "outer_diameter": 0.6, "hole_diameter": 0.3},
        {"type": "pcb_via", "pcb_via_id": "via_1",
         "x": 40.0, "y": 40.0, "outer_diameter": 0.6, "hole_diameter": 0.3},

        # traces (connect pads → no dangling)
        {"type": "pcb_trace", "pcb_trace_id": "trace_u1_r1",
         "route_thickness_mm": 0.25,
         "route": [{"x": 9.0, "y": 15.0}, {"x": 29.0, "y": 15.0}]},
    ]


_ECAD_CIRCUIT = _make_ecad_circuit()


# ─── Step 1: KiCad import ─────────────────────────────────────────────────────

class TestKiCadImport:
    """T-97 Step 1: import KiCad PCB fixture → CircuitJSON."""

    def test_kicad_pcb_roundtrip_returns_list(self):
        cj = kicad_pcb_to_circuit_json(_KICAD_PCB_FIXTURE)
        assert isinstance(cj, list), "kicad_pcb_to_circuit_json must return a list"

    def test_kicad_import_non_empty(self):
        cj = kicad_pcb_to_circuit_json(_KICAD_PCB_FIXTURE)
        assert len(cj) > 0, "Imported circuit must have at least one element"

    def test_kicad_import_recovers_nets(self):
        cj = kicad_pcb_to_circuit_json(_KICAD_PCB_FIXTURE)
        nets = [e for e in cj if e.get("type") == "source_net"]
        net_names = {n["name"] for n in nets}
        assert "VCC" in net_names, f"VCC net not recovered; got: {net_names}"
        assert "GND" in net_names, f"GND net not recovered; got: {net_names}"

    def test_kicad_import_recovers_footprints(self):
        cj = kicad_pcb_to_circuit_json(_KICAD_PCB_FIXTURE)
        comps = [e for e in cj if e.get("type") == "source_component"]
        refs = {c["name"] for c in comps}
        assert "U1" in refs, f"U1 not recovered; got: {refs}"
        assert "R1" in refs, f"R1 not recovered; got: {refs}"

    def test_kicad_import_recovers_pcb_components(self):
        cj = kicad_pcb_to_circuit_json(_KICAD_PCB_FIXTURE)
        pcb_comps = [e for e in cj if e.get("type") == "pcb_component"]
        assert len(pcb_comps) >= 3, (
            f"Expected ≥3 pcb_components (U1, R1, C1); got {len(pcb_comps)}"
        )

    def test_kicad_import_recovers_traces(self):
        cj = kicad_pcb_to_circuit_json(_KICAD_PCB_FIXTURE)
        traces = [e for e in cj if e.get("type") == "pcb_trace"]
        assert len(traces) >= 1, "At least one pcb_trace must be recovered from KiCad PCB"

    def test_kicad_export_roundtrip_balances_parens(self):
        pcb_text = circuit_json_to_kicad_pcb(_ECAD_CIRCUIT)
        assert pcb_text.count("(") == pcb_text.count(")"), (
            "kicad_pcb output has unbalanced parentheses"
        )

    def test_kicad_export_contains_footprints(self):
        pcb_text = circuit_json_to_kicad_pcb(_ECAD_CIRCUIT)
        assert "(footprint" in pcb_text, "kicad_pcb output must contain footprint entries"
        assert "U1" in pcb_text
        assert "R1" in pcb_text

    def test_empty_kicad_pcb_safe(self):
        cj = kicad_pcb_to_circuit_json("")
        assert isinstance(cj, list)

    def test_malformed_kicad_pcb_safe(self):
        cj = kicad_pcb_to_circuit_json("(kicad_pcb (net 1 ")
        assert isinstance(cj, list)


# ─── Step 2: DRC ──────────────────────────────────────────────────────────────

class TestDRC:
    """T-97 Step 2: run DRC on the ECAD circuit."""

    def test_drc_returns_dict(self):
        result = _run_drc_on_circuit(_ECAD_CIRCUIT)
        assert isinstance(result, dict), "DRC must return a dict"

    def test_drc_has_errors_and_warnings_keys(self):
        result = _run_drc_on_circuit(_ECAD_CIRCUIT)
        assert "errors" in result
        assert "warnings" in result

    def test_drc_errors_is_list(self):
        result = _run_drc_on_circuit(_ECAD_CIRCUIT)
        assert isinstance(result["errors"], list)

    def test_drc_warnings_is_list(self):
        result = _run_drc_on_circuit(_ECAD_CIRCUIT)
        assert isinstance(result["warnings"], list)

    def test_drc_well_spaced_vias_no_via_clearance_error(self):
        """Vias separated by 20 mm must not produce via_clearance errors."""
        result = _run_drc_on_circuit(_ECAD_CIRCUIT)
        via_errs = [e for e in result["errors"] if e["kind"] == "via_clearance"]
        assert len(via_errs) == 0, (
            f"Unexpected via_clearance errors: {via_errs}"
        )

    def test_drc_trace_width_ok_for_025mm(self):
        """0.25 mm trace is above the 0.15 mm default minimum."""
        result = _run_drc_on_circuit(_ECAD_CIRCUIT)
        trace_errs = [e for e in result["errors"] if e["kind"] == "trace_too_narrow"]
        assert len(trace_errs) == 0, (
            f"Unexpected trace_too_narrow errors: {trace_errs}"
        )

    def test_drc_custom_rule_tightens_min_trace(self):
        """Set min_trace_width_mm=0.30: the 0.25 mm trace should now fail."""
        circuit = [
            {"type": "pcb_board", "width": 100, "height": 80,
             "drc_rules": {"min_trace_width_mm": 0.30}},
            {"type": "pcb_trace", "pcb_trace_id": "t1",
             "route_thickness_mm": 0.25,
             "route": [{"x": 5, "y": 5}, {"x": 20, "y": 5}]},
        ]
        result = _run_drc_on_circuit(circuit)
        assert any(e["kind"] == "trace_too_narrow" for e in result["errors"]), (
            "Expected trace_too_narrow error with tightened min_trace_width_mm=0.30"
        )

    def test_drc_net_short_detected(self):
        """Two pads on different nets bridged by a trace → net_short error."""
        circuit = [
            {"type": "pcb_board", "width": 50, "height": 50},
            {"type": "pcb_smtpad", "pcb_smtpad_id": "p1",
             "x": 0, "y": 0, "net_id": "VCC"},
            {"type": "pcb_smtpad", "pcb_smtpad_id": "p2",
             "x": 10, "y": 0, "net_id": "GND"},
            {"type": "pcb_trace", "pcb_trace_id": "t1",
             "route_thickness_mm": 0.2,
             "route": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]},
        ]
        result = _run_drc_on_circuit(circuit)
        assert any(e["kind"] == "net_short" for e in result["errors"]), (
            "Expected net_short error for VCC-GND bridge"
        )

    def test_drc_empty_circuit_zero_violations(self):
        result = _run_drc_on_circuit([])
        assert result["errors"] == []
        assert result["warnings"] == []

    def test_drc_tool_registered_in_electronics_registry(self):
        """run_pcb_drc tool must be discoverable in the electronics Registry."""
        import kerf_electronics.tools.pcb_drc  # noqa: F401 — ensures @register fires
        names = [t.spec.name for t in _ElecRegistry]
        assert "run_pcb_drc" in names, f"run_pcb_drc not in registry: {names}"

    def test_drc_tool_json_roundtrip(self):
        """Call run_pcb_drc via the tool interface; verify summary keys."""
        import kerf_electronics.tools.pcb_drc  # noqa: F401
        resp = _call_tool_sync("run_pcb_drc", {"circuit_json": _ECAD_CIRCUIT})
        assert "errors" in resp
        assert "warnings" in resp
        assert "summary" in resp
        assert isinstance(resp["summary"]["error_count"], int)
        assert isinstance(resp["summary"]["warning_count"], int)


# ─── Step 3: Gerber export ────────────────────────────────────────────────────

class TestGerberExport:
    """T-97 Step 3: Gerber export for the ECAD circuit."""

    def setup_method(self):
        self.files = export_gerber(_ECAD_CIRCUIT, stem="ecad_test")

    def test_gerber_returns_dict(self):
        assert isinstance(self.files, dict)

    def test_gerber_top_copper_present(self):
        assert "ecad_test.GTL" in self.files, (
            f"Missing top-copper Gerber; keys: {sorted(self.files)}"
        )

    def test_gerber_bottom_copper_present(self):
        assert "ecad_test.GBL" in self.files, (
            f"Missing bottom-copper Gerber; keys: {sorted(self.files)}"
        )

    def test_gerber_edge_cuts_present(self):
        assert "ecad_test.GKO" in self.files, (
            f"Missing edge-cuts Gerber; keys: {sorted(self.files)}"
        )

    def test_gerber_rs274x_header(self):
        for fname, content in self.files.items():
            assert "%FSLAX46Y46*%" in content, (
                f"{fname}: missing RS-274X format statement"
            )
            assert "%MOMM*%" in content, f"{fname}: missing metric mode statement"

    def test_gerber_ends_with_m02(self):
        for fname, content in self.files.items():
            assert "M02*" in content, f"{fname}: missing M02 end-of-file"

    def test_gerber_as_zip_is_valid(self):
        """Gerber files can be bundled into a valid zip and re-read."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fname, content in self.files.items():
                zf.writestr(fname, content.encode("utf-8"))
        buf.seek(0)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
        assert "ecad_test.GTL" in names
        assert "ecad_test.GBL" in names
        assert "ecad_test.GKO" in names

    def test_gerber_zip_base64_decodable(self):
        """Base64-encoded zip round-trips to valid bytes."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for fname, content in self.files.items():
                zf.writestr(fname, content)
        zip_b64 = base64.b64encode(buf.getvalue()).decode()
        decoded = base64.b64decode(zip_b64)
        buf2 = io.BytesIO(decoded)
        with zipfile.ZipFile(buf2, "r") as zf:
            assert len(zf.namelist()) > 0


# ─── Step 4: BOM table ────────────────────────────────────────────────────────

class TestBOMTable:
    """T-97 Step 4: BOM generation from the ECAD circuit."""

    def setup_method(self):
        self.rows = _extract_bom_rows(_ECAD_CIRCUIT)
        self.bom_files = export_fab_bom(_ECAD_CIRCUIT, stem="ecad_test")
        self.csv_text = self.bom_files["ecad_test-bom.csv"]

    def test_bom_rows_non_empty(self):
        assert len(self.rows) > 0, "BOM must have at least one row"

    def test_bom_csv_file_present(self):
        assert "ecad_test-bom.csv" in self.bom_files

    def test_bom_csv_has_header(self):
        lines = self.csv_text.strip().splitlines()
        assert len(lines) >= 2, "BOM CSV must have header + at least one row"
        header = lines[0]
        for col in ("Item", "Qty", "Refdes", "Value", "Footprint", "MPN"):
            assert col in header, f"BOM CSV missing column '{col}'"

    def test_bom_csv_qty_column_numeric(self):
        reader = csv.DictReader(io.StringIO(self.csv_text))
        for row in reader:
            assert row["Qty"].isdigit(), f"BOM Qty not numeric: {row['Qty']!r}"

    def test_bom_csv_has_u1(self):
        assert "U1" in self.csv_text, "U1 (MCU) must appear in BOM CSV"

    def test_bom_csv_has_r1(self):
        assert "R1" in self.csv_text, "R1 must appear in BOM CSV"

    def test_bom_csv_has_c1(self):
        assert "C1" in self.csv_text, "C1 must appear in BOM CSV"

    def test_bom_csv_resistors_grouped_together(self):
        """R1 and R2 share same (value, footprint) → same BOM row, qty=2."""
        rows = _extract_bom_rows(_ECAD_CIRCUIT)
        resistor_rows = [r for r in rows if "10k" in r["value"] and "R_0402" in r["footprint"]]
        assert len(resistor_rows) == 1, (
            f"R1+R2 should be grouped into one BOM row; got {len(resistor_rows)}"
        )
        assert resistor_rows[0]["qty"] == 2

    def test_bom_distributor_picked(self):
        """Components with distributors should have distributor filled in."""
        rows = _extract_bom_rows(_ECAD_CIRCUIT)
        # U1 has DigiKey and Mouser — DigiKey is cheaper
        u1_rows = [r for r in rows if "STM32" in r["mpn"]]
        assert len(u1_rows) == 1
        assert u1_rows[0]["distributor"] == "DigiKey", (
            "DigiKey should be selected as cheapest distributor for U1"
        )

    def test_bom_mpn_present_for_u1(self):
        rows = _extract_bom_rows(_ECAD_CIRCUIT)
        u1_row = next((r for r in rows if "STM32" in r["mpn"]), None)
        assert u1_row is not None, "U1 row with STM32 MPN not found in BOM"


# ─── Step 5: Cost rollup against mocked distributor prices ───────────────────

class TestBOMCostRollup:
    """T-97 Step 5: cost roll-up using BOM data with mocked distributor prices."""

    # Mocked BOM lines derived from the ECAD circuit fixture
    _ECAD_BOM_LINES = [
        {
            "refdes": "U1", "qty": 1,
            "mpn": "STM32F103C8T6", "manufacturer": "STMicroelectronics",
            "unit_price": None,
            "price_breaks": [
                {"min_qty": 1,   "unit_price": 2.50},
                {"min_qty": 10,  "unit_price": 2.20},
                {"min_qty": 100, "unit_price": 1.80},
            ],
        },
        {
            "refdes": "R1,R2", "qty": 2,
            "mpn": "RC0402FR-0710KL", "manufacturer": "Yageo",
            "unit_price": 0.10,
        },
        {
            "refdes": "C1", "qty": 1,
            "mpn": "GRM155R61A104KA01D", "manufacturer": "Murata",
            "unit_price": 0.05,
        },
    ]

    def test_cost_rollup_produces_total(self):
        result = _compute_cost_rollup(
            self._ECAD_BOM_LINES,
            board_qty=1, assembly_qty=1, nre_usd=0.0, dnp_list=[],
        )
        assert result["total_usd"] > 0, "Total cost must be positive"

    def test_cost_rollup_per_board_at_qty1(self):
        """At qty=1: U1=2.50, R1+R2=2×0.10=0.20, C1=0.05 → 2.75."""
        result = _compute_cost_rollup(
            self._ECAD_BOM_LINES,
            board_qty=1, assembly_qty=1, nre_usd=0.0, dnp_list=[],
        )
        assert abs(result["subtotal_parts_usd"] - 2.75) < 0.01, (
            f"Expected subtotal ~2.75, got {result['subtotal_parts_usd']}"
        )

    def test_cost_rollup_price_break_at_qty100(self):
        """At qty=100: U1 price-break at ≥100 → $1.80 each."""
        result = _compute_cost_rollup(
            self._ECAD_BOM_LINES,
            board_qty=100, assembly_qty=100, nre_usd=0.0, dnp_list=[],
        )
        # U1 × 100 boards × 1 per board = 100 units → tier $1.80
        # Find U1 line result
        u1_line = next((l for l in result["line_items"] if l["refdes"] == "U1"), None)
        assert u1_line is not None
        assert abs(u1_line["unit_price_usd"] - 1.80) < 0.01, (
            f"Expected U1 price $1.80 at qty=100, got {u1_line['unit_price_usd']}"
        )

    def test_cost_rollup_nre_amortised(self):
        """NRE of $50 is added to total; per_board = (parts + NRE) / assembly_qty.

        At assembly_qty=10:
          U1: 10 units → price-break tier ≥10 = $2.20 → $22.00
          R1,R2: qty=2 per board × 10 = 20 units × $0.10 = $2.00
          C1: qty=1 per board × 10 = 10 units × $0.05 = $0.50
          Parts subtotal = $24.50  NRE = $50.00  Total = $74.50
        """
        result = _compute_cost_rollup(
            self._ECAD_BOM_LINES,
            board_qty=10, assembly_qty=10, nre_usd=50.0, dnp_list=[],
        )
        expected_total = 74.50
        assert abs(result["total_usd"] - expected_total) < 0.05, (
            f"Expected total ~{expected_total:.2f}, got {result['total_usd']}"
        )
        assert result["nre_usd"] == 50.0

    def test_cost_rollup_dnp_excluded(self):
        """C1 marked DNP is excluded from cost."""
        bom = [
            {"refdes": "R1", "qty": 1, "unit_price": 0.10},
            {"refdes": "C1", "qty": 1, "unit_price": 0.05, "dnp": True},
        ]
        result = _compute_cost_rollup(bom, board_qty=1, assembly_qty=1,
                                      nre_usd=0.0, dnp_list=[])
        assert abs(result["subtotal_parts_usd"] - 0.10) < 0.001
        assert "C1" in result["dnp_lines"]

    def test_cost_rollup_missing_price_line_reported(self):
        """A BOM line with no price is reported in missing_price_lines."""
        bom = [
            {"refdes": "U2", "qty": 1},  # no price
            {"refdes": "R3", "qty": 1, "unit_price": 0.10},
        ]
        result = _compute_cost_rollup(bom, board_qty=1, assembly_qty=1,
                                      nre_usd=0.0, dnp_list=[])
        assert "U2" in result["missing_price_lines"]

    def test_price_break_select_tier1_below_threshold(self):
        breaks = [
            {"min_qty": 1,    "unit_price": 2.50},
            {"min_qty": 10,   "unit_price": 2.20},
            {"min_qty": 100,  "unit_price": 1.80},
        ]
        assert abs(_select_price(None, breaks, 5) - 2.50) < 0.001
        assert abs(_select_price(None, breaks, 10) - 2.20) < 0.001
        assert abs(_select_price(None, breaks, 100) - 1.80) < 0.001


# ─── Step 6: Complete fab zip ─────────────────────────────────────────────────

class TestFabZip:
    """T-97 Step 6: fab zip generation — DRC + Gerbers + Excellon + BOM + IPC-2581."""

    def _build_fab_zip(self) -> tuple[bytes, dict[str, str]]:
        """Build the complete fab package in memory; return (zip_bytes, files)."""
        gerber_files = export_gerber(_ECAD_CIRCUIT, stem="ecad_test")
        drill_files = export_excellon(_ECAD_CIRCUIT, stem="ecad_test")
        pnp_files = export_pnp(_ECAD_CIRCUIT, stem="ecad_test")
        bom_files = export_fab_bom(_ECAD_CIRCUIT, stem="ecad_test")
        ipc_files = export_ipc2581(_ECAD_CIRCUIT, stem="ecad_test")

        all_files: dict[str, str] = {}
        all_files.update(gerber_files)
        all_files.update(drill_files)
        all_files.update(pnp_files)
        all_files.update(bom_files)
        all_files.update(ipc_files)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fname, content in sorted(all_files.items()):
                zf.writestr(fname, content.encode("utf-8"))

        return buf.getvalue(), all_files

    def test_fab_zip_non_empty(self):
        zip_bytes, _ = self._build_fab_zip()
        assert len(zip_bytes) > 0

    def test_fab_zip_is_valid_zip(self):
        zip_bytes, _ = self._build_fab_zip()
        buf = io.BytesIO(zip_bytes)
        assert zipfile.is_zipfile(buf), "fab zip bytes are not a valid zip archive"

    def test_fab_zip_contains_gerbers(self):
        zip_bytes, _ = self._build_fab_zip()
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
        assert any(n.endswith(".GTL") for n in names), "No top-copper Gerber in fab zip"
        assert any(n.endswith(".GBL") for n in names), "No bottom-copper Gerber in fab zip"
        assert any(n.endswith(".GKO") for n in names), "No edge-cuts Gerber in fab zip"

    def test_fab_zip_contains_drill(self):
        zip_bytes, _ = self._build_fab_zip()
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
        assert any(n.endswith(".DRL") for n in names), "No drill file in fab zip"

    def test_fab_zip_contains_bom(self):
        zip_bytes, _ = self._build_fab_zip()
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
        assert any("bom" in n.lower() for n in names), "No BOM file in fab zip"

    def test_fab_zip_contains_ipc2581(self):
        zip_bytes, _ = self._build_fab_zip()
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
        assert any(n.endswith(".xml") for n in names), "No IPC-2581 XML in fab zip"

    def test_fab_zip_ipc2581_well_formed(self):
        zip_bytes, _ = self._build_fab_zip()
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            xml_name = next(n for n in zf.namelist() if n.endswith(".xml"))
            xml_text = zf.read(xml_name).decode("utf-8")
        root = ET.fromstring(xml_text)
        local_tag = root.tag.split("}")[-1]
        assert local_tag == "IPC-2581", f"Root element is {local_tag!r}, expected 'IPC-2581'"

    def test_fab_zip_bom_csv_readable(self):
        zip_bytes, _ = self._build_fab_zip()
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            bom_name = next(n for n in zf.namelist() if "bom" in n.lower())
            bom_text = zf.read(bom_name).decode("utf-8")
        reader = csv.DictReader(io.StringIO(bom_text))
        rows = list(reader)
        assert len(rows) >= 1, "BOM CSV in fab zip must have at least one data row"

    def test_fab_zip_base64_round_trips(self):
        zip_bytes, _ = self._build_fab_zip()
        b64 = base64.b64encode(zip_bytes).decode()
        decoded = base64.b64decode(b64)
        assert decoded == zip_bytes, "Base64 round-trip corrupted the fab zip"

    def test_drill_hits_coincide_with_vias(self):
        """Via positions in the circuit must have matching drill hits."""
        hits = _collect_hits(_ECAD_CIRCUIT)
        hit_coords = {(round(h.x, 3), round(h.y, 3)) for h in hits}

        vias = [e for e in _ECAD_CIRCUIT if e.get("type") == "pcb_via"]
        assert len(vias) == 2, f"Expected 2 vias in ECAD circuit, got {len(vias)}"
        for via in vias:
            vx, vy = round(float(via["x"]), 3), round(float(via["y"]), 3)
            assert (vx, vy) in hit_coords, (
                f"Via at ({vx},{vy}) has no matching drill hit. Hits: {sorted(hit_coords)}"
            )


# ─── Step 7: Pnp CSV ──────────────────────────────────────────────────────────

class TestPnpCSV:
    """Pick-and-place CSV is part of the fab bundle."""

    def test_pnp_returns_top_csv(self):
        files = export_pnp(_ECAD_CIRCUIT, stem="ecad_test")
        assert "ecad_test-top-pnp.csv" in files, (
            f"Missing top PnP CSV; keys: {sorted(files)}"
        )

    def test_pnp_top_csv_has_header(self):
        files = export_pnp(_ECAD_CIRCUIT, stem="ecad_test")
        header = files["ecad_test-top-pnp.csv"].splitlines()[0]
        for col in ("Designator", "MidX(mm)", "Rotation(deg)"):
            assert col in header, f"PnP CSV missing column '{col}' — header: {header!r}"

    def test_pnp_top_csv_lists_top_components(self):
        files = export_pnp(_ECAD_CIRCUIT, stem="ecad_test")
        top_csv = files["ecad_test-top-pnp.csv"]
        lines = top_csv.strip().splitlines()
        # header + at least U1, R1, R2 (3 top-copper components)
        assert len(lines) >= 4, (
            f"Expected ≥4 lines (header + ≥3 components), got {len(lines)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
