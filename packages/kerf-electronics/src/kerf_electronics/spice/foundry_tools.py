"""foundry_tools.py — LLM tool wrappers for SPICE foundry-parity features.

Exposes four tools to the kerf LLM agent:
  electronics_bsim4_iv         — Compute BSIM4 I-V curve points
  electronics_bsim4_corner     — Run PVT / Monte-Carlo corner sweep
  electronics_generate_netlist — Schematic graph → SPICE netlist (3 dialects)
  electronics_parse_netlist    — Parse SPICE netlist → schematic JSON

HONEST DISCLAIMER
-----------------
All computations use the BSIM4.8 first-order reference model (UC Berkeley,
2013) and Pelgrom (1989) statistical matching.  Results are NOT equivalent to
foundry-PDK sign-off accuracy.  Use for design exploration only.
"""

from __future__ import annotations

import json
import math
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.spice.bsim4_model import (
    Bsim4Geometry,
    Bsim4Parameters,
    cgs_bsim4,
    gm_bsim4,
    id_bsim4,
    vth_bsim4,
)
from kerf_electronics.spice.corner_analysis import (
    DEFAULT_CORNERS,
    PvtSweepSpec,
    corner_summary,
    run_pvt_corner_sweep,
)
from kerf_electronics.spice.netlist_codegen import (
    SchematicDevice,
    SchematicGraph,
    SchematicNode,
    generate_netlist,
    parse_netlist,
)


# ---------------------------------------------------------------------------
# Tool 1: electronics_bsim4_iv
# ---------------------------------------------------------------------------

_bsim4_iv_spec = ToolSpec(
    name="electronics_bsim4_iv",
    description=(
        "Compute BSIM4.8 MOSFET drain current Id, transconductance gm, and "
        "gate-source capacitance Cgs at specified bias conditions. "
        "Returns Id (A), gm (S), Cgs (F), Vth (V). "
        "HONEST NOTE: BSIM4.8 first-order model (UC Berkeley, 2013); "
        "not foundry-PDK accurate; for design exploration only."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vgs": {"type": "number", "description": "Gate-source voltage (V)"},
            "vds": {"type": "number", "description": "Drain-source voltage (V)"},
            "vbs": {"type": "number", "description": "Body-source voltage (V), default 0"},
            "T_celsius": {"type": "number", "description": "Temperature (°C), default 27"},
            "W_um": {"type": "number", "description": "Channel width (μm), default 1.0"},
            "L_nm": {"type": "number", "description": "Channel length (nm), default 100"},
            "nf": {"type": "integer", "description": "Number of gate fingers, default 1"},
            "model_params": {
                "type": "object",
                "description": "Optional BSIM4 parameter overrides (vth0, u0, tox, etc.)",
            },
        },
        "required": ["vgs", "vds"],
    },
)


@register(_bsim4_iv_spec)
async def electronics_bsim4_iv(_ctx: Any, args: bytes) -> str:
    """BSIM4 I-V point computation LLM tool."""
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    vgs   = float(a.get("vgs", 0.0))
    vds   = float(a.get("vds", 0.0))
    vbs   = float(a.get("vbs", 0.0))
    T_c   = float(a.get("T_celsius", 27.0))
    W_um  = float(a.get("W_um", 1.0))
    L_nm  = float(a.get("L_nm", 100.0))
    nf    = int(a.get("nf", 1))

    T_K  = T_c + 273.15
    W    = W_um * 1e-6
    L    = L_nm * 1e-9

    # Build params with optional overrides
    params = Bsim4Parameters()
    overrides = a.get("model_params", {}) or {}
    for k, v in overrides.items():
        if hasattr(params, k):
            try:
                setattr(params, k, float(v))
            except (TypeError, ValueError):
                pass

    geom = Bsim4Geometry(W=W, L=L, nf=nf)

    try:
        Id   = id_bsim4(vgs, vds, vbs, T_K, params, geom)
        gm   = gm_bsim4(vgs, vds, vbs, T_K, params, geom)
        Cgs  = cgs_bsim4(vgs, vds, params, geom)
        Vth  = vth_bsim4(vbs, T_K, params, geom)
    except Exception as e:
        return err_payload(f"BSIM4 computation error: {e}", "ERROR")

    region = "off"
    if vgs > Vth:
        if vds < vgs - Vth:
            region = "triode"
        else:
            region = "saturation"

    return ok_payload({
        "Id_A":     Id,
        "Id_uA":    Id * 1e6,
        "gm_mS":    gm * 1e3,
        "Cgs_fF":   Cgs * 1e15,
        "Vth_V":    Vth,
        "region":   region,
        "bias": {"vgs": vgs, "vds": vds, "vbs": vbs, "T_celsius": T_c},
        "geometry": {"W_um": W_um, "L_nm": L_nm, "nf": nf},
        "honest_disclaimer": (
            "BSIM4.8 first-order model (UC Berkeley 2013). "
            "Not foundry-PDK accurate. For design exploration only."
        ),
    })


# ---------------------------------------------------------------------------
# Tool 2: electronics_bsim4_corner
# ---------------------------------------------------------------------------

_bsim4_corner_spec = ToolSpec(
    name="electronics_bsim4_corner",
    description=(
        "Run a PVT / Monte-Carlo corner sweep on a BSIM4 MOSFET. "
        "Sweeps all 5 standard process corners (TT/SS/FF/SF/FS), "
        "voltages ±10%, and temperatures −40/27/125°C with Pelgrom "
        "mismatch Monte-Carlo. Returns worst-case Id variation, yield "
        "estimate, and per-corner statistics. "
        "HONEST NOTE: not foundry-PDK accurate; for design exploration only."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vgs": {"type": "number", "description": "Nominal Vgs (V)"},
            "vds": {"type": "number", "description": "Nominal Vds (V)"},
            "vbs": {"type": "number", "description": "Body-source voltage (V), default 0"},
            "W_um": {"type": "number", "description": "Channel width (μm), default 1.0"},
            "L_nm": {"type": "number", "description": "Channel length (nm), default 100"},
            "monte_carlo_iterations": {
                "type": "integer",
                "description": "MC iterations per (corner, V, T) point, default 100",
            },
            "spec_min_id_uA": {
                "type": "number",
                "description": "Minimum Id spec for yield estimation (μA); omit for no spec",
            },
            "rng_seed": {"type": "integer", "description": "RNG seed for reproducibility"},
        },
        "required": ["vgs", "vds"],
    },
)


@register(_bsim4_corner_spec)
async def electronics_bsim4_corner(_ctx: Any, args: bytes) -> str:
    """PVT / Monte-Carlo corner sweep LLM tool."""
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    vgs    = float(a.get("vgs", 1.0))
    vds    = float(a.get("vds", 1.0))
    vbs    = float(a.get("vbs", 0.0))
    W_um   = float(a.get("W_um", 1.0))
    L_nm   = float(a.get("L_nm", 100.0))
    mc_n   = int(a.get("monte_carlo_iterations", 100))
    seed   = int(a.get("rng_seed", 0))

    spec_min_id = None
    if "spec_min_id_uA" in a:
        spec_min_id = float(a["spec_min_id_uA"]) * 1e-6

    params = Bsim4Parameters()
    geom   = Bsim4Geometry(W=W_um * 1e-6, L=L_nm * 1e-9)
    spec   = PvtSweepSpec(monte_carlo_iterations=mc_n)

    try:
        report  = run_pvt_corner_sweep(params, geom, vgs, vds, vbs, spec, spec_min_id, seed)
        summary = corner_summary(report)
    except Exception as e:
        return err_payload(f"corner sweep error: {e}", "ERROR")

    return ok_payload(summary)


# ---------------------------------------------------------------------------
# Tool 3: electronics_generate_netlist
# ---------------------------------------------------------------------------

_gen_netlist_spec = ToolSpec(
    name="electronics_generate_netlist",
    description=(
        "Generate a SPICE netlist from a schematic graph description. "
        "Supports Cadence Spectre, ngspice, and HSPICE dialects. "
        "Returns the netlist as a string. "
        "HONEST NOTE: Syntax-correct but requires foundry device model files "
        "for simulation accuracy. Not for tape-out sign-off."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Netlist title"},
            "dialect": {
                "type": "string",
                "enum": ["spectre", "ngspice", "hspice"],
                "description": "Simulator dialect, default 'ngspice'",
            },
            "devices": {
                "type": "array",
                "description": "List of device objects",
                "items": {
                    "type": "object",
                    "properties": {
                        "device_id": {"type": "string"},
                        "kind": {"type": "string"},
                        "pins": {"type": "array", "items": {"type": "string"}},
                        "parameters": {"type": "object"},
                        "model_name": {"type": "string"},
                    },
                    "required": ["device_id", "kind", "pins"],
                },
            },
            "nodes": {
                "type": "array",
                "description": "Optional list of named nodes",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "voltage": {"type": "string"},
                    },
                },
            },
        },
        "required": ["devices"],
    },
)


@register(_gen_netlist_spec)
async def electronics_generate_netlist(_ctx: Any, args: bytes) -> str:
    """Schematic → netlist LLM tool."""
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    dialect = a.get("dialect", "ngspice")
    title   = a.get("title", "kerf_netlist")

    raw_devices = a.get("devices", [])
    if not raw_devices:
        return err_payload("devices list is required and must not be empty", "BAD_ARGS")

    devices = []
    for d in raw_devices:
        dev_id = d.get("device_id", "")
        kind   = d.get("kind", "R")
        pins   = d.get("pins", [])
        params = d.get("parameters", {})
        model  = d.get("model_name")

        if not dev_id:
            return err_payload("each device must have a device_id", "BAD_ARGS")

        devices.append(SchematicDevice(
            device_id  = dev_id,
            kind       = kind,
            pins       = pins,
            parameters = params,
            model_name = model,
        ))

    raw_nodes = a.get("nodes", [])
    nodes = [SchematicNode(name=n["name"], voltage=n.get("voltage")) for n in raw_nodes]

    graph = SchematicGraph(nodes=nodes, devices=devices, title=title)

    try:
        netlist = generate_netlist(graph, dialect=dialect)
    except Exception as e:
        return err_payload(f"netlist generation error: {e}", "ERROR")

    return ok_payload({
        "netlist": netlist,
        "dialect": dialect,
        "device_count": len(devices),
        "honest_disclaimer": (
            "Syntax follows public documentation for the selected dialect. "
            "Requires foundry .MODEL / .SUBCKT files for accurate simulation. "
            "Not for tape-out sign-off."
        ),
    })


# ---------------------------------------------------------------------------
# Tool 4: electronics_parse_netlist
# ---------------------------------------------------------------------------

_parse_netlist_spec = ToolSpec(
    name="electronics_parse_netlist",
    description=(
        "Parse a SPICE netlist string into a structured schematic graph (JSON). "
        "Supports Cadence Spectre, ngspice, and HSPICE syntax. "
        "Useful for round-trip verification and netlist inspection."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "netlist": {"type": "string", "description": "SPICE netlist text"},
            "dialect": {
                "type": "string",
                "enum": ["spectre", "ngspice", "hspice"],
                "description": "Simulator dialect, default 'ngspice'",
            },
        },
        "required": ["netlist"],
    },
)


@register(_parse_netlist_spec)
async def electronics_parse_netlist(_ctx: Any, args: bytes) -> str:
    """Netlist parser LLM tool."""
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    text    = a.get("netlist", "")
    dialect = a.get("dialect", "ngspice")

    if not text.strip():
        return err_payload("netlist text is required", "BAD_ARGS")

    try:
        graph = parse_netlist(text, dialect=dialect)
    except Exception as e:
        return err_payload(f"parse error: {e}", "ERROR")

    devices_out = [
        {
            "device_id":  dev.device_id,
            "kind":       dev.kind,
            "pins":       dev.pins,
            "parameters": dev.parameters,
            "model_name": dev.model_name,
        }
        for dev in graph.devices
    ]
    nodes_out = [{"name": n.name, "voltage": n.voltage} for n in graph.nodes]

    return ok_payload({
        "title":        graph.title,
        "device_count": len(devices_out),
        "node_count":   len(nodes_out),
        "devices":      devices_out,
        "nodes":        nodes_out,
    })
