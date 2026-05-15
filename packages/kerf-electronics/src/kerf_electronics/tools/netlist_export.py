"""netlist_export.py — multi-format netlist export + extended ERC report.

Exports a CircuitJSON schematic netlist in three standard formats:
  - KiCad netlist (S-expression, KiCad 5/6 .net format)
  - OrCAD/PADS netlist (ascii .net format used by many legacy place-and-route tools)
  - Generic CSV (net → refdes.pin list, one row per net)

Net/component data is derived purely from the CircuitJSON source_* element model
(source_component, source_port, source_trace, source_net) — the same model used
by the existing ERC engine.

Extended ERC report wraps the existing `_run_erc` engine (imported, NOT copied)
and adds additional checks:
  - single_node_net   : a net that connects only one port (floating signal)
  - power_pin_no_driver : power-in pins on a net that has no corresponding
                          power-out / supply pin (subset of missing_power, but
                          pinpointing the specific missing sourcing pin)
  - conflicting_output  : replaces the inline output_to_output with a structured
                          per-net listing of all conflicting drivers

Two @register tools:
  export_netlist  — choose format, returns text (or base64 for binary-safe transfer)
  erc_report      — extended ERC, structured report with summary statistics
"""

from __future__ import annotations

import importlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# Import the existing ERC engine without modifying erc.py
# ---------------------------------------------------------------------------

_erc_mod = importlib.import_module("kerf_electronics.tools.erc")
_run_erc = _erc_mod._run_erc
_ports = _erc_mod._ports
_traces = _erc_mod._traces
_components = _erc_mod._components
_nets = _erc_mod._nets
_touched_port_ids = _erc_mod._touched_port_ids
_build_net_uf = _erc_mod._build_net_uf


# ---------------------------------------------------------------------------
# Net extraction — derives the net graph from the source_* model
# ---------------------------------------------------------------------------

def _extract_net_graph(circuit: list) -> dict:
    """Build a connectivity graph from CircuitJSON source_* elements.

    Returns:
        {
          "nets":       { root_id: net_name },
          "net_ports":  { root_id: [(refdes, pin_name), ...] },
          "components": { comp_id: {name, value, footprint} },
          "ports":      [ {source_port_id, source_component_id, name, pin_type} ]
        }

    The root_id for each net is the union-find canonical ID from tracing
    connected_source_port_ids and connected_source_net_ids across all traces.
    This is identical to the union-find used by the ERC engine.
    """
    port_list = _ports(circuit)
    trace_list = _traces(circuit)
    component_list = _components(circuit)
    net_list = _nets(circuit)

    uf = _build_net_uf(trace_list)

    # Index components
    comp_by_id: dict[str, dict] = {}
    for c in component_list:
        cid = c.get("source_component_id") or c.get("id")
        if cid:
            comp_by_id[cid] = c

    # Index ports
    port_by_id: dict[str, dict] = {}
    for p in port_list:
        pid = p.get("source_port_id") or p.get("id")
        if pid:
            port_by_id[pid] = p

    # Map net elements to their canonical root
    net_name_by_root: dict[str, str] = {}
    for n in net_list:
        nid = n.get("source_net_id") or n.get("id")
        if not nid:
            continue
        label = n.get("name") or n.get("net_name") or nid
        root = uf.find(nid)
        if root not in net_name_by_root:
            net_name_by_root[root] = label

    # For ports, use the port_id itself as the seed; each trace's port IDs
    # are already merged by _build_net_uf.
    net_ports: dict[str, list] = defaultdict(list)
    for p in port_list:
        pid = p.get("source_port_id") or p.get("id")
        if not pid:
            continue
        root = uf.find(pid)
        cid = p.get("source_component_id", "")
        comp = comp_by_id.get(cid, {})
        refdes = comp.get("name") or comp.get("refdes") or cid
        pin_name = p.get("name") or pid
        net_ports[root].append({
            "refdes": refdes,
            "pin": pin_name,
            "source_component_id": cid,
            "source_port_id": pid,
            "pin_type": p.get("pin_type", "passive"),
        })
        # If this root has no net name yet, derive one from the port
        if root not in net_name_by_root:
            # Check if any net element has this root via union membership
            pass  # will be filled from net_list or left as root id

    # Fill net names for roots that appear only as port-merged roots
    for root in list(net_ports.keys()):
        if root not in net_name_by_root:
            net_name_by_root[root] = root  # use the root port id as net name

    # Build component summary
    components: dict[str, dict] = {}
    for cid, c in comp_by_id.items():
        components[cid] = {
            "name": c.get("name") or c.get("refdes") or cid,
            "value": c.get("value", ""),
            "footprint": c.get("footprint", ""),
            "source_component_id": cid,
        }

    return {
        "nets": net_name_by_root,
        "net_ports": dict(net_ports),
        "components": components,
        "ports": port_list,
    }


# ---------------------------------------------------------------------------
# KiCad S-expression netlist (KiCad .net format, version 1)
# ---------------------------------------------------------------------------

def _kicad_escape(s: str) -> str:
    """Quote a string for S-expression if it contains spaces or special chars."""
    if not s:
        return '""'
    needs_quote = any(c in s for c in ' "()\\')
    if needs_quote:
        escaped = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _export_kicad(circuit: list, stem: str = "board") -> str:
    """Export a KiCad S-expression netlist (.net format, version 1).

    Structure follows KiCad's export_netlist.cpp output:
      (export (version "1")
        (design (source <stem>) (date <ts>) (tool "Kerf Electronics"))
        (components
          (comp (ref <refdes>) (value <value>) (footprint <fp>)))
        (nets
          (net (code <n>) (name <name>)
            (node (ref <refdes>) (pin <pin>)))))
    """
    graph = _extract_net_graph(circuit)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = []
    lines.append(f'(export (version "1")')
    lines.append(f'  (design')
    lines.append(f'    (source {_kicad_escape(stem)})')
    lines.append(f'    (date {_kicad_escape(ts)})')
    lines.append(f'    (tool "Kerf Electronics"))')

    # Components section
    lines.append('  (components')
    for cid, comp in sorted(graph["components"].items(), key=lambda x: x[1]["name"]):
        ref = _kicad_escape(comp["name"])
        val = _kicad_escape(comp["value"] or "?")
        fp = _kicad_escape(comp["footprint"] or "")
        lines.append(f'    (comp (ref {ref}) (value {val}) (footprint {fp}))')
    lines.append('  )')  # /components

    # Nets section — sorted by net name for determinism
    lines.append('  (nets')
    net_items = sorted(graph["nets"].items(), key=lambda x: x[1])
    for code, (root, net_name) in enumerate(net_items, start=1):
        name_str = _kicad_escape(net_name)
        lines.append(f'    (net (code "{code}") (name {name_str})')
        for entry in sorted(
            graph["net_ports"].get(root, []),
            key=lambda e: (e["refdes"], e["pin"])
        ):
            ref_str = _kicad_escape(entry["refdes"])
            pin_str = _kicad_escape(entry["pin"])
            lines.append(f'      (node (ref {ref_str}) (pin {pin_str}))')
        lines.append('    )')  # /net
    lines.append('  )')  # /nets
    lines.append(')')    # /export

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# OrCAD/PADS netlist (ascii NET format)
# ---------------------------------------------------------------------------

def _export_orcad_pads(circuit: list, stem: str = "board") -> str:
    """Export an OrCAD/PADS-style ASCII netlist.

    Format:
      !<stem> <timestamp>
      *PART*
      <REFDES> <footprint>
      ...
      *NET*
      *SIGNAL* <net_name>
      <REFDES>.<pin> [<REFDES>.<pin> ...]
      ...
      *END*

    This is the "PADS Layout ASCII netlist" subset accepted by PADS, CADSTAR,
    and many legacy place-and-route tools.
    """
    graph = _extract_net_graph(circuit)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = []
    lines.append(f"!{stem} {ts}")
    lines.append("*PART*")
    for cid, comp in sorted(graph["components"].items(), key=lambda x: x[1]["name"]):
        refdes = comp["name"]
        footprint = comp["footprint"] or "UNKNOWN"
        lines.append(f"{refdes} {footprint}")

    lines.append("*NET*")
    net_items = sorted(graph["nets"].items(), key=lambda x: x[1])
    for root, net_name in net_items:
        ports = graph["net_ports"].get(root, [])
        if not ports:
            continue
        lines.append(f"*SIGNAL* {net_name}")
        node_strs = [
            f"{e['refdes']}.{e['pin']}"
            for e in sorted(ports, key=lambda e: (e["refdes"], e["pin"]))
        ]
        # PADS format wraps at 8 nodes per continuation line
        chunk_size = 8
        for i in range(0, len(node_strs), chunk_size):
            lines.append(" ".join(node_strs[i:i + chunk_size]))

    lines.append("*END*")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Generic CSV netlist
# ---------------------------------------------------------------------------

def _export_csv(circuit: list, stem: str = "board") -> str:
    """Export a generic CSV netlist: one row per (net, refdes, pin).

    Columns: net_name, refdes, pin, pin_type

    This is easy to import into spreadsheets, BOM tools, or custom scripts.
    The net_name column is the canonical net label derived from source_net
    elements or the union-find root id when no label is available.
    """
    import csv
    import io

    graph = _extract_net_graph(circuit)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["net_name", "refdes", "pin", "pin_type"])

    net_items = sorted(graph["nets"].items(), key=lambda x: x[1])
    for root, net_name in net_items:
        ports = sorted(
            graph["net_ports"].get(root, []),
            key=lambda e: (e["refdes"], e["pin"])
        )
        for entry in ports:
            writer.writerow([net_name, entry["refdes"], entry["pin"], entry["pin_type"]])

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Extended ERC checks (not in erc.py)
# ---------------------------------------------------------------------------

def _check_single_node_net(port_list, trace_list) -> list:
    """Flag nets that have exactly one port connected (isolated stubs).

    Unlike the existing floating_net warning (which fires when a *trace* has
    only one port), this check operates at the net level via union-find: if
    an entire merged net touches only a single port, it is a single-node net.

    Severity: warning (same rationale as floating_net).
    """
    warnings = []
    uf = _build_net_uf(trace_list)

    root_ports: dict[str, set] = defaultdict(set)
    for t in trace_list:
        ids = t.get("connected_source_port_ids") or t.get("port_ids") or []
        if not ids:
            continue
        root = uf.find(ids[0])
        for pid in ids:
            root_ports[root].add(pid)

    port_by_id = {(p.get("source_port_id") or p.get("id")): p for p in port_list}

    for root, port_set in root_ports.items():
        if len(port_set) == 1:
            only_id = next(iter(port_set))
            p = port_by_id.get(only_id)
            warnings.append({
                "kind": "single_node_net",
                "severity": "warning",
                "message": (
                    f'Net (root "{root}") has exactly one connected port '
                    f'"{p.get("name", only_id) if p else only_id}" — single-node net, '
                    f'signal never reaches a second pin'
                ),
                "port_id": only_id,
                "net_root": root,
            })
    return warnings


def _check_power_pin_no_driver(port_list, trace_list) -> list:
    """Flag power-in pins whose net has no power-out/supply driving pin.

    This is more specific than the existing missing_power check: it targets
    cases where a power-in pin (pin_type="power_in") is connected to a net
    that has no power-out pin — meaning the supply rail is present in the
    schematic but no driver component (e.g. regulator, PWR_FLAG) sources it.

    Severity: error.
    """
    errors = []
    uf = _build_net_uf(trace_list)

    port_by_id = {(p.get("source_port_id") or p.get("id")): p for p in port_list}

    # For each merged net root: collect power_in pins and power_out/supply pins
    root_power_in: dict[str, list] = defaultdict(list)
    root_power_out: dict[str, list] = defaultdict(list)

    for pid, p in port_by_id.items():
        pt = p.get("pin_type", "")
        hints = p.get("port_hints") or []

        is_power_in = pt == "power_in" or "power_in" in hints
        is_power_out = (
            pt in ("power", "power_out", "supply") or
            "power" in hints or "supply" in hints or "power_out" in hints
        )

        root = uf.find(pid)
        if is_power_in:
            root_power_in[root].append(p)
        if is_power_out:
            root_power_out[root].append(p)

    for root, pins in root_power_in.items():
        if root not in root_power_out:
            for p in pins:
                pid = p.get("source_port_id") or p.get("id")
                errors.append({
                    "kind": "power_pin_no_driver",
                    "severity": "error",
                    "message": (
                        f'Power-in pin "{p.get("name", pid)}" on component '
                        f'"{p.get("source_component_id", "?")}" is on a net with '
                        f'no power-out/supply driver (net root "{root}")'
                    ),
                    "port_id": pid,
                    "component_id": p.get("source_component_id"),
                    "net_root": root,
                })
    return errors


def _check_conflicting_outputs(port_list, trace_list) -> list:
    """Return a per-net structured listing of all conflicting output drivers.

    The existing output_to_output check in erc.py fires once per trace pair.
    This check groups all output pins by their merged net root and reports a
    single structured entry per net, listing every conflicting driver.

    Severity: error.
    """
    errors = []
    uf = _build_net_uf(trace_list)

    port_by_id = {(p.get("source_port_id") or p.get("id")): p for p in port_list}

    def is_output(p) -> bool:
        if p is None:
            return False
        pt = p.get("pin_type", "")
        hints = p.get("port_hints") or []
        if pt != "output" and "output" not in hints:
            return False
        ef = p.get("electrical_function", "")
        if ef in ("open_collector", "open_drain"):
            return False
        return True

    root_outputs: dict[str, list] = defaultdict(list)
    touched = _touched_port_ids(trace_list)

    for pid, p in port_by_id.items():
        if pid not in touched:
            continue
        if is_output(p):
            root = uf.find(pid)
            root_outputs[root].append(p)

    for root, outputs in root_outputs.items():
        if len(outputs) >= 2:
            driver_list = [
                {
                    "refdes": p.get("source_component_id", "?"),
                    "pin": p.get("name", p.get("source_port_id", "?")),
                    "port_id": p.get("source_port_id") or p.get("id"),
                }
                for p in outputs
            ]
            errors.append({
                "kind": "conflicting_outputs",
                "severity": "error",
                "message": (
                    f'Net (root "{root}") has {len(outputs)} output drivers '
                    f'tied together: '
                    + ", ".join(f'{d["refdes"]}.{d["pin"]}' for d in driver_list)
                ),
                "net_root": root,
                "drivers": driver_list,
            })
    return errors


# ---------------------------------------------------------------------------
# Extended ERC report engine
# ---------------------------------------------------------------------------

def _run_erc_extended(circuit: list) -> dict:
    """Run the full ERC (via imported _run_erc) plus three additional checks.

    Returns:
      {
        "errors":   [...],   # from _run_erc + power_pin_no_driver + conflicting_outputs
        "warnings": [...],   # from _run_erc + single_node_net
        "summary": {
          "total_errors":   int,
          "total_warnings": int,
          "checks_run":     [str],
        }
      }
    """
    base = _run_erc(circuit)

    port_list = _ports(circuit)
    trace_list = _traces(circuit)

    extra_errors = (
        _check_power_pin_no_driver(port_list, trace_list) +
        _check_conflicting_outputs(port_list, trace_list)
    )
    extra_warnings = _check_single_node_net(port_list, trace_list)

    all_errors = base["errors"] + extra_errors
    all_warnings = base["warnings"] + extra_warnings

    checks_run = [
        # base checks (from erc.py)
        "unconnected_pin",
        "duplicate_refdes",
        "conflicting_net_label",
        "output_to_output",
        "missing_power",
        "pin_direction_mismatch",
        "floating_net",
        "bidirectional_promiscuity",
        # extended checks (this module)
        "single_node_net",
        "power_pin_no_driver",
        "conflicting_outputs",
    ]

    return {
        "errors": all_errors,
        "warnings": all_warnings,
        "summary": {
            "total_errors": len(all_errors),
            "total_warnings": len(all_warnings),
            "checks_run": checks_run,
        },
    }


# ---------------------------------------------------------------------------
# LLM tool: export_netlist
# ---------------------------------------------------------------------------

export_netlist_spec = ToolSpec(
    name="export_netlist",
    description=(
        "Export a CircuitJSON schematic netlist in a standard EDA format. "
        "Derives net topology purely from source_component / source_port / "
        "source_trace / source_net elements — same model as run_erc. "
        "Supported formats: "
        "'kicad' — KiCad S-expression (.net, KiCad 5/6 compatible); "
        "'orcad_pads' — OrCAD/PADS ASCII netlist (.net, compatible with PADS Layout, "
        "CADSTAR, and legacy place-and-route tools); "
        "'csv' — generic CSV (net_name, refdes, pin, pin_type). "
        "Returns the netlist text and metadata. "
        "Run erc_report first to catch wiring errors before exporting."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": "Flat array of CircuitJSON source_* elements.",
            },
            "format": {
                "type": "string",
                "enum": ["kicad", "orcad_pads", "csv"],
                "description": (
                    "Output format: 'kicad' (S-expression), 'orcad_pads' (ASCII), "
                    "or 'csv' (spreadsheet-friendly)."
                ),
            },
            "stem": {
                "type": "string",
                "description": "Board/job name used in file header (default: 'board').",
            },
        },
        "required": ["circuit_json", "format"],
    },
)

_FORMAT_EXT = {"kicad": ".net", "orcad_pads": ".net", "csv": ".csv"}
_FORMAT_FN = {
    "kicad": _export_kicad,
    "orcad_pads": _export_orcad_pads,
    "csv": _export_csv,
}


@register(export_netlist_spec, write=False)
async def run_export_netlist(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit = a.get("circuit_json")
    if not isinstance(circuit, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    fmt = a.get("format", "").strip().lower()
    if fmt not in _FORMAT_FN:
        return err_payload(
            f"format must be one of: {', '.join(_FORMAT_FN)}", "BAD_ARGS"
        )

    stem = (a.get("stem") or "board").strip() or "board"

    try:
        text = _FORMAT_FN[fmt](circuit, stem=stem)
    except Exception as e:
        return err_payload(f"netlist export failed: {e}", "EXPORT_ERROR")

    import base64
    content_b64 = base64.b64encode(text.encode("utf-8", errors="replace")).decode()
    filename = f"{stem}{_FORMAT_EXT[fmt]}"
    line_count = text.count("\n")

    return ok_payload({
        "filename": filename,
        "format": fmt,
        "content_b64": content_b64,
        "line_count": line_count,
        "preview": "\n".join(text.splitlines()[:25]),
        "message": (
            f"Netlist exported as {fmt} → {filename} ({line_count} lines). "
            "Decode content_b64 (UTF-8) to obtain the file."
        ),
    })


# ---------------------------------------------------------------------------
# LLM tool: erc_report
# ---------------------------------------------------------------------------

erc_report_spec = ToolSpec(
    name="erc_report",
    description=(
        "Run an extended Electrical Rules Check over a CircuitJSON schematic. "
        "Wraps the core run_erc checks (unconnected_pin, duplicate_refdes, "
        "conflicting_net_label, output_to_output, missing_power, "
        "pin_direction_mismatch, floating_net, bidirectional_promiscuity) and adds: "
        "single_node_net (net touches exactly one port — signal can never reach a "
        "receiver), power_pin_no_driver (power-in pin on a net with no power-out "
        "driver — supply rail sourcing is missing), conflicting_outputs (all "
        "output-driver pins on a shared net listed together). "
        "Returns errors, warnings, and a summary with total counts and checks_run list. "
        "Use this instead of run_erc when you need the structured per-net driver "
        "listing or the power-sourcing diagnostics."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": "Flat array of CircuitJSON source_* elements.",
            },
        },
        "required": ["circuit_json"],
    },
)


@register(erc_report_spec, write=False)
async def run_erc_report(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit = a.get("circuit_json")
    if not isinstance(circuit, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    try:
        result = _run_erc_extended(circuit)
    except Exception as e:
        return err_payload(f"ERC failed: {e}", "ERC_ERROR")

    return ok_payload(result)
