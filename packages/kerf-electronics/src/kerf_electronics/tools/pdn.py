"""
Power Distribution Network (PDN) analysis tools.

Provides three LLM-callable tools:

  pdn_ir_drop           — DC IR-drop analysis on a resistive power-net mesh
  pdn_target_impedance  — Target impedance + first-order decap count estimate
  pdn_report            — Combined IR-drop + target-impedance report

CircuitJSON extensions used (read only, never mutated by these read-only tools):
  board.pdn_nodes    — list of PDNNode-compatible dicts (optional)
  board.pdn_segments — list of PDNSegment-compatible dicts (optional)

All tools also accept an *explicit* simplified input model directly in the
tool arguments, which takes precedence over board-embedded data.  This allows
LLM callers to supply a minimal network description without a full CircuitJSON
board.

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.pdn.analyzer import (
    PDNNode,
    PDNSegment,
    decap_count_estimate,
    sheet_resistance_ohms_per_sq,
    solve_ir_drop,
    target_impedance,
)


# ── Internal CircuitJSON helpers ──────────────────────────────────────────────

def _get_board(circuit_json) -> dict | None:
    elements = circuit_json if isinstance(circuit_json, list) else [circuit_json]
    for e in elements:
        if isinstance(e, dict) and e.get("type") == "pcb_board":
            return e
    return None


def _parse_nodes(raw: list) -> list[PDNNode]:
    nodes = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        nodes.append(PDNNode(
            node_id=str(item.get("node_id", "")),
            i_draw_a=float(item.get("i_draw_a", 0.0)),
            is_source=bool(item.get("is_source", False)),
            voltage_v=item.get("voltage_v"),
        ))
    return nodes


def _parse_segments(raw: list) -> list[PDNSegment]:
    segs = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        segs.append(PDNSegment(
            node_a=str(item.get("node_a", "")),
            node_b=str(item.get("node_b", "")),
            resistance_ohms=item.get("resistance_ohms"),
            length_mm=item.get("length_mm"),
            width_mm=item.get("width_mm"),
            sheet_resistance_ohms_per_sq=item.get("sheet_resistance_ohms_per_sq"),
        ))
    return segs


def _sink_to_dict(s) -> dict:
    return {
        "node_id": s.node_id,
        "voltage_v": s.voltage_v,
        "ir_drop_v": s.ir_drop_v,
        "current_a": s.current_a,
        "pass_fail": s.pass_fail,
        "budget_v": s.budget_v,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. pdn_ir_drop
# ═══════════════════════════════════════════════════════════════════════════════

pdn_ir_drop_spec = ToolSpec(
    name="pdn_ir_drop",
    description=(
        "DC IR-drop analysis for a power distribution network. "
        "Builds a resistive node-edge graph from *nodes* (one source + one or more "
        "sinks with current draws) and *segments* (resistive conductors), then solves "
        "node voltages via a conductance matrix (Kirchhoff's current law). "
        "Returns per-sink voltage, IR drop, and pass/fail against an optional budget. "
        "\n\n"
        "Input model (supply directly in args or embed in circuit_json):\n"
        "  nodes    — list of {node_id, i_draw_a, is_source, voltage_v}\n"
        "  segments — list of {node_a, node_b} with one of:\n"
        "             • resistance_ohms (direct)\n"
        "             • length_mm + width_mm + sheet_resistance_ohms_per_sq\n"
        "             • length_mm + width_mm + copper_weight_oz (sheet R computed)\n"
        "\n"
        "Copper sheet resistance helpers:\n"
        "  1 oz copper ≈ 0.539 mΩ/sq, 2 oz ≈ 0.270 mΩ/sq\n"
        "\n"
        "Returns {ok, source_node_id, source_voltage_v, all_node_voltages, sinks, "
        "worst_ir_drop_v, worst_node_id, all_pass, total_current_a}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "oneOf": [{"type": "object"}, {"type": "array"}],
                "description": (
                    "Optional CircuitJSON board or element list. If supplied the tool "
                    "reads board.pdn_nodes and board.pdn_segments as fallback data when "
                    "'nodes'/'segments' are not provided directly."
                ),
            },
            "nodes": {
                "type": "array",
                "description": (
                    "PDN node list. Each item: {node_id, i_draw_a?, is_source?, voltage_v?}. "
                    "Exactly one node must have is_source=true and voltage_v set."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string"},
                        "i_draw_a": {"type": "number"},
                        "is_source": {"type": "boolean"},
                        "voltage_v": {"type": "number"},
                    },
                    "required": ["node_id"],
                },
            },
            "segments": {
                "type": "array",
                "description": (
                    "PDN segment list. Each item: {node_a, node_b} + resistance spec. "
                    "Specify resistance_ohms, or (length_mm + width_mm + "
                    "sheet_resistance_ohms_per_sq), or (length_mm + width_mm + copper_weight_oz)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "node_a": {"type": "string"},
                        "node_b": {"type": "string"},
                        "resistance_ohms": {"type": "number"},
                        "length_mm": {"type": "number"},
                        "width_mm": {"type": "number"},
                        "sheet_resistance_ohms_per_sq": {"type": "number"},
                        "copper_weight_oz": {"type": "number"},
                    },
                    "required": ["node_a", "node_b"],
                },
            },
            "ir_drop_budget_v": {
                "type": "number",
                "description": (
                    "Per-sink IR-drop tolerance in volts. Sinks with IR drop exceeding "
                    "this value are marked FAIL. Omit to skip pass/fail evaluation."
                ),
            },
        },
    },
)


@register(pdn_ir_drop_spec, write=False)
async def pdn_ir_drop(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    raw_nodes = a.get("nodes")
    raw_segments = a.get("segments")
    budget = a.get("ir_drop_budget_v")

    # Fall back to circuit_json board data if not provided inline
    if raw_nodes is None or raw_segments is None:
        cj = a.get("circuit_json")
        if cj is not None:
            board = _get_board(cj)
            if board is not None:
                if raw_nodes is None:
                    raw_nodes = board.get("pdn_nodes")
                if raw_segments is None:
                    raw_segments = board.get("pdn_segments")

    if not isinstance(raw_nodes, list) or len(raw_nodes) == 0:
        return err_payload(
            "nodes is required — provide a list of PDN nodes with is_source/i_draw_a",
            "BAD_ARGS",
        )
    if not isinstance(raw_segments, list) or len(raw_segments) == 0:
        return err_payload(
            "segments is required — provide a list of resistive segments",
            "BAD_ARGS",
        )

    # Expand copper_weight_oz to sheet_resistance_ohms_per_sq if needed
    expanded_segments = []
    for seg in raw_segments:
        seg = dict(seg)
        if seg.get("sheet_resistance_ohms_per_sq") is None and seg.get("copper_weight_oz") is not None:
            try:
                seg["sheet_resistance_ohms_per_sq"] = sheet_resistance_ohms_per_sq(
                    float(seg["copper_weight_oz"])
                )
            except (ValueError, TypeError) as e:
                return err_payload(f"invalid copper_weight_oz: {e}", "BAD_ARGS")
        expanded_segments.append(seg)

    nodes = _parse_nodes(raw_nodes)
    segments = _parse_segments(expanded_segments)

    if not isinstance(budget, (int, float)):
        budget = None

    result = solve_ir_drop(nodes, segments, ir_drop_budget_v=budget)

    if result.error:
        return err_payload(result.error, "ANALYSIS_ERROR")

    return ok_payload({
        "source_node_id": result.source_node_id,
        "source_voltage_v": result.source_voltage_v,
        "all_node_voltages": result.all_node_voltages,
        "sinks": [_sink_to_dict(s) for s in result.sinks],
        "worst_ir_drop_v": result.worst_ir_drop_v,
        "worst_node_id": result.worst_node_id,
        "all_pass": result.all_pass,
        "total_current_a": result.total_current_a,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 2. pdn_target_impedance
# ═══════════════════════════════════════════════════════════════════════════════

pdn_target_impedance_spec = ToolSpec(
    name="pdn_target_impedance",
    description=(
        "Calculate the PDN target impedance (Zt) and estimate the number of "
        "decoupling capacitors required to meet it at a given frequency.\n\n"
        "Formula:  Zt = (Vdd × ripple_fraction) / I_transient\n\n"
        "Decap count model: each cap is a series LC (|Xc − Xl|); N caps in parallel "
        "divide the impedance by N.  ESR is ignored (conservative estimate).\n\n"
        "Returns {ok, target_impedance_ohms, decap} where decap contains count, "
        "z_single_ohms, srf_hz, regime ('capacitive'|'inductive'|'resonant')}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vdd_v": {
                "type": "number",
                "description": "Nominal supply voltage in volts (e.g. 3.3, 1.8, 1.0).",
            },
            "ripple_fraction": {
                "type": "number",
                "description": (
                    "Allowed supply ripple as a fraction of Vdd (e.g. 0.05 for 5%, "
                    "0.02 for 2%). Must be in (0, 1]."
                ),
            },
            "i_transient_a": {
                "type": "number",
                "description": "Peak transient current draw in amperes.",
            },
            "cap_value_f": {
                "type": "number",
                "description": "Decoupling capacitor value in farads (e.g. 100e-9 for 100 nF).",
            },
            "cap_esl_h": {
                "type": "number",
                "description": "Effective series inductance (ESL) of one cap in henries (e.g. 1e-9 = 1 nH).",
            },
            "frequency_hz": {
                "type": "number",
                "description": "Analysis frequency in Hz (e.g. 100e6 = 100 MHz).",
            },
        },
        "required": ["vdd_v", "ripple_fraction", "i_transient_a", "cap_value_f", "cap_esl_h", "frequency_hz"],
    },
)


@register(pdn_target_impedance_spec, write=False)
async def pdn_target_impedance_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    vdd = a.get("vdd_v")
    ripple = a.get("ripple_fraction")
    i_trans = a.get("i_transient_a")
    cap_val = a.get("cap_value_f")
    cap_esl = a.get("cap_esl_h")
    freq = a.get("frequency_hz")

    for name, val in [
        ("vdd_v", vdd), ("ripple_fraction", ripple), ("i_transient_a", i_trans),
        ("cap_value_f", cap_val), ("cap_esl_h", cap_esl), ("frequency_hz", freq),
    ]:
        if not isinstance(val, (int, float)):
            return err_payload(f"{name} must be a number", "BAD_ARGS")

    try:
        zt = target_impedance(float(vdd), float(ripple), float(i_trans))
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    try:
        decap = decap_count_estimate(zt, float(cap_val), float(cap_esl), float(freq))
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    return ok_payload({
        "vdd_v": vdd,
        "ripple_fraction": ripple,
        "i_transient_a": i_trans,
        "target_impedance_ohms": round(zt, 6),
        "decap": decap,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 3. pdn_report
# ═══════════════════════════════════════════════════════════════════════════════

pdn_report_spec = ToolSpec(
    name="pdn_report",
    description=(
        "Combined PDN report: DC IR-drop analysis + target-impedance + decap estimate "
        "in one call.  Useful as a single-shot power integrity summary.\n\n"
        "Supply the IR-drop network (nodes + segments) *and* the target-impedance "
        "parameters in the same call.  Either section may be omitted; the report will "
        "skip the missing section gracefully.\n\n"
        "Returns {ok, ir_drop?, target_impedance?} where each sub-report mirrors the "
        "dedicated tool's output."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "oneOf": [{"type": "object"}, {"type": "array"}],
                "description": "Optional CircuitJSON board (board.pdn_nodes + board.pdn_segments used as fallback).",
            },
            "nodes": {
                "type": "array",
                "description": "PDN node list (see pdn_ir_drop).",
                "items": {"type": "object"},
            },
            "segments": {
                "type": "array",
                "description": "PDN segment list (see pdn_ir_drop).",
                "items": {"type": "object"},
            },
            "ir_drop_budget_v": {
                "type": "number",
                "description": "IR-drop pass/fail tolerance in volts.",
            },
            "vdd_v": {"type": "number", "description": "Nominal supply voltage (V)."},
            "ripple_fraction": {"type": "number", "description": "Allowed ripple fraction."},
            "i_transient_a": {"type": "number", "description": "Peak transient current (A)."},
            "cap_value_f": {"type": "number", "description": "Decap value (F)."},
            "cap_esl_h": {"type": "number", "description": "Decap ESL (H)."},
            "frequency_hz": {"type": "number", "description": "Analysis frequency (Hz)."},
        },
    },
)


@register(pdn_report_spec, write=False)
async def pdn_report(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    report: dict = {}

    # ── IR-drop section ───────────────────────────────────────────────────
    raw_nodes = a.get("nodes")
    raw_segments = a.get("segments")
    budget = a.get("ir_drop_budget_v")

    cj = a.get("circuit_json")
    if cj is not None:
        board = _get_board(cj)
        if board is not None:
            if raw_nodes is None:
                raw_nodes = board.get("pdn_nodes")
            if raw_segments is None:
                raw_segments = board.get("pdn_segments")

    has_ir = isinstance(raw_nodes, list) and len(raw_nodes) > 0 and \
             isinstance(raw_segments, list) and len(raw_segments) > 0

    if has_ir:
        expanded_segments = []
        for seg in raw_segments:
            seg = dict(seg)
            if seg.get("sheet_resistance_ohms_per_sq") is None and seg.get("copper_weight_oz") is not None:
                try:
                    seg["sheet_resistance_ohms_per_sq"] = sheet_resistance_ohms_per_sq(
                        float(seg["copper_weight_oz"])
                    )
                except (ValueError, TypeError):
                    pass
            expanded_segments.append(seg)

        nodes = _parse_nodes(raw_nodes)
        segments = _parse_segments(expanded_segments)
        ir_result = solve_ir_drop(
            nodes, segments,
            ir_drop_budget_v=budget if isinstance(budget, (int, float)) else None,
        )
        if ir_result.error:
            report["ir_drop"] = {"error": ir_result.error}
        else:
            report["ir_drop"] = {
                "source_node_id": ir_result.source_node_id,
                "source_voltage_v": ir_result.source_voltage_v,
                "all_node_voltages": ir_result.all_node_voltages,
                "sinks": [_sink_to_dict(s) for s in ir_result.sinks],
                "worst_ir_drop_v": ir_result.worst_ir_drop_v,
                "worst_node_id": ir_result.worst_node_id,
                "all_pass": ir_result.all_pass,
                "total_current_a": ir_result.total_current_a,
            }

    # ── Target impedance section ──────────────────────────────────────────
    vdd = a.get("vdd_v")
    ripple = a.get("ripple_fraction")
    i_trans = a.get("i_transient_a")
    cap_val = a.get("cap_value_f")
    cap_esl = a.get("cap_esl_h")
    freq = a.get("frequency_hz")

    has_zt = all(isinstance(v, (int, float)) for v in [vdd, ripple, i_trans, cap_val, cap_esl, freq])

    if has_zt:
        try:
            zt = target_impedance(float(vdd), float(ripple), float(i_trans))
            decap = decap_count_estimate(zt, float(cap_val), float(cap_esl), float(freq))
            report["target_impedance"] = {
                "vdd_v": vdd,
                "ripple_fraction": ripple,
                "i_transient_a": i_trans,
                "target_impedance_ohms": round(zt, 6),
                "decap": decap,
            }
        except ValueError as e:
            report["target_impedance"] = {"error": str(e)}

    if not report:
        return err_payload(
            "No data to analyse. Supply nodes+segments for IR-drop and/or "
            "vdd_v+ripple_fraction+i_transient_a+cap_value_f+cap_esl_h+frequency_hz "
            "for target impedance.",
            "BAD_ARGS",
        )

    return ok_payload(report)


# ── TOOLS registry (consumed by plugin._register_tools) ──────────────────────

TOOLS = [
    ("pdn_ir_drop", pdn_ir_drop_spec, pdn_ir_drop),
    ("pdn_target_impedance", pdn_target_impedance_spec, pdn_target_impedance_tool),
    ("pdn_report", pdn_report_spec, pdn_report),
]
