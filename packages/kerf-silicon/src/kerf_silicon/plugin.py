"""
kerf-silicon plugin registration.

Wires the silicon / VLSI design LLM tools into a Kerf plugin app.

Capabilities
------------
  silicon.analog_cell     — instantiate_analog_cell: analog cell instantiation + LVS + char
  silicon.drc             — silicon_drc_check: design rule check against PDK rules
  silicon.formal_equiv    — silicon_formal_equiv: BDD-based combinational equivalence check
  silicon.openlane        — silicon_run_openlane: RTL→GDS-II via OpenLane (external binary)
  silicon.ibis            — silicon_import_ibis: IBIS 7.1 model import + eye-diagram estimation
                            silicon_eye_diagram:  compute eye-diagram metrics at a pin

IBIS 7.1 compliance note
-------------------------
  The IBIS tools implement the core I/O buffer model sections (Component, Pin,
  Model, Pulldown/Pullup IV tables, GND/POWER clamp, Ramp, Voltage Range).
  They are NOT IBIS-certified.  Full spec: https://ibis.org/ver7.1/ibis_specs_7_1.pdf
"""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _openlane_available() -> bool:
    """Return True if the OpenLane CLI is on PATH."""
    return (
        shutil.which("openlane") is not None
        or shutil.which("flow.tcl") is not None
    )


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    # No HTTP routes for silicon — pure LLM tool surface.

    provides: list[str] = []
    _register_tools(ctx, provides)

    if _openlane_available():
        if "silicon.openlane" not in provides:
            provides.append("silicon.openlane")
        logger.info("kerf-silicon: OpenLane found — silicon.openlane available")
    else:
        logger.info(
            "kerf-silicon: OpenLane CLI not found — "
            "silicon_run_openlane tool registered but will return an error when called. "
            "Install OpenLane to enable RTL→GDS-II flow."
        )

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "silicon",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="silicon",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all silicon LLM tools into ctx.tools."""

    # ── 1. instantiate_analog_cell ──────────────────────────────────────────
    try:
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _TS
        except ImportError:
            from kerf_silicon._compat import ToolSpec as _TS  # type: ignore

        _analog_spec = _TS(
            name="instantiate_analog_cell",
            description=(
                "Instantiate a parameterised analog cell from the sky130 library. "
                "Supported families: 'opamp_2stage' (GBW-parameterised Miller OTA), "
                "'comparator_strongarm' (clocked strong-arm latch), "
                "'bandgap_brokaw' (Brokaw bandgap reference). "
                "Returns layout descriptor, LVS-clean flag, and characterisation summary "
                "(GBW/Vref/offset oracle with ±20 % / ±5 % checks). "
                "Params for opamp_2stage: gbw_hz, idd_ua, pdk. "
                "Params for comparator_strongarm: offset_mv, pdk. "
                "Params for bandgap_brokaw: iref_ua, pdk."
            ),
            input_schema={
                "type": "object",
                "required": ["family"],
                "properties": {
                    "family": {
                        "type": "string",
                        "description": (
                            "Cell family: 'opamp_2stage', 'comparator_strongarm', "
                            "or 'bandgap_brokaw'."
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": (
                            "Optional sizing parameters dict. "
                            "opamp_2stage: {gbw_hz, idd_ua, pdk}. "
                            "comparator_strongarm: {offset_mv, pdk}. "
                            "bandgap_brokaw: {iref_ua, pdk}."
                        ),
                        "default": {},
                    },
                },
            },
        )

        from kerf_silicon.tools.instantiate_analog_cell import instantiate_analog_cell as _iac

        async def _instantiate_analog_cell_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"ok": False, "error": f"invalid args: {e}", "code": "BAD_ARGS"})
            family = a.get("family", "").strip()
            if not family:
                return _json.dumps({"ok": False, "error": "'family' is required", "code": "BAD_ARGS"})
            params = a.get("params") or {}
            result = _iac(family, params)
            return _json.dumps(result)

        ctx.tools.register("instantiate_analog_cell", _analog_spec, _instantiate_analog_cell_tool)
        provides.append("silicon.analog_cell")
    except Exception as exc:
        logger.warning("kerf-silicon: failed to load instantiate_analog_cell tool: %s", exc)

    # ── 2. silicon_drc_check ────────────────────────────────────────────────
    try:
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _TS2
        except ImportError:
            from kerf_silicon._compat import ToolSpec as _TS2  # type: ignore

        _drc_spec = _TS2(
            name="silicon_drc_check",
            description=(
                "Run a Design Rule Check (DRC) on a layout against PDK rules. "
                "Layout is a list of shape dicts: {layer: str, coords: [[x,y], ...]}. "
                "Rules are a list of rule dicts with keys: type (width|spacing|enclosure|density|overlap), "
                "layer, min_um (float), etc. "
                "Returns {violations: [{rule_name, layer, location, description}], passed_rules: int}. "
                "Use pdk='sky130' to load standard sky130 design rules automatically."
            ),
            input_schema={
                "type": "object",
                "required": ["layout"],
                "properties": {
                    "layout": {
                        "type": "array",
                        "description": "List of shape dicts: [{layer: str, coords: [[x,y],...]}]",
                        "items": {"type": "object"},
                    },
                    "rules": {
                        "type": "array",
                        "description": (
                            "List of rule dicts. If omitted and pdk='sky130', sky130 rules are used."
                        ),
                        "items": {"type": "object"},
                        "default": [],
                    },
                    "pdk": {
                        "type": "string",
                        "description": "PDK name for automatic rule loading ('sky130'). Default: 'sky130'.",
                        "default": "sky130",
                    },
                },
            },
        )

        async def _silicon_drc_check_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"error": f"invalid args: {e}", "code": "BAD_ARGS"})

            layout = a.get("layout")
            if not isinstance(layout, list):
                return _json.dumps({"error": "'layout' must be an array", "code": "BAD_ARGS"})

            rules = a.get("rules") or []
            pdk = a.get("pdk", "sky130")

            # If no rules provided, load PDK rules
            if not rules and pdk == "sky130":
                try:
                    from kerf_silicon.drc.rules import SKY130_RULES
                    rules = SKY130_RULES
                except Exception as exc:
                    return _json.dumps({
                        "error": f"Failed to load sky130 rules: {exc}",
                        "code": "PDK_ERROR",
                    })

            try:
                from kerf_silicon.drc.engine import check
                report = check(layout, rules)
                return _json.dumps(report.to_dict())
            except Exception as exc:
                return _json.dumps({"error": str(exc), "code": "DRC_ERROR"})

        ctx.tools.register("silicon_drc_check", _drc_spec, _silicon_drc_check_tool)
        provides.append("silicon.drc")
    except Exception as exc:
        logger.warning("kerf-silicon: failed to load silicon_drc_check tool: %s", exc)

    # ── 3. silicon_formal_equiv ─────────────────────────────────────────────
    try:
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _TS3
        except ImportError:
            from kerf_silicon._compat import ToolSpec as _TS3  # type: ignore

        _equiv_spec = _TS3(
            name="silicon_formal_equiv",
            description=(
                "BDD-based combinational equivalence check between two gate-level netlists. "
                "Both netlists must have the same primary inputs and outputs. "
                "Netlist format: {inputs: [str], outputs: [str], gates: [{type, inputs: {port: net}, "
                "output: net}]}. "
                "Returns {equivalent: bool, per_output: {out: bool}, counterexample: {out: {in: val}} | null}."
            ),
            input_schema={
                "type": "object",
                "required": ["netlist_a", "netlist_b"],
                "properties": {
                    "netlist_a": {
                        "type": "object",
                        "description": "First gate-level netlist (reference).",
                    },
                    "netlist_b": {
                        "type": "object",
                        "description": "Second gate-level netlist (implementation).",
                    },
                },
            },
        )

        async def _silicon_formal_equiv_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"error": f"invalid args: {e}", "code": "BAD_ARGS"})

            netlist_a = a.get("netlist_a")
            netlist_b = a.get("netlist_b")
            if not isinstance(netlist_a, dict) or not isinstance(netlist_b, dict):
                return _json.dumps({
                    "error": "'netlist_a' and 'netlist_b' must be objects",
                    "code": "BAD_ARGS",
                })

            try:
                from kerf_silicon.formal.equiv import check_equiv
                result = check_equiv(netlist_a, netlist_b)
                return _json.dumps(result)
            except ValueError as exc:
                return _json.dumps({"error": str(exc), "code": "INPUT_MISMATCH"})
            except Exception as exc:
                return _json.dumps({"error": str(exc), "code": "EQUIV_ERROR"})

        ctx.tools.register("silicon_formal_equiv", _equiv_spec, _silicon_formal_equiv_tool)
        provides.append("silicon.formal_equiv")
    except Exception as exc:
        logger.warning("kerf-silicon: failed to load silicon_formal_equiv tool: %s", exc)

    # ── 4. silicon_run_openlane ─────────────────────────────────────────────
    try:
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _TS4
        except ImportError:
            from kerf_silicon._compat import ToolSpec as _TS4  # type: ignore

        _ol_spec = _TS4(
            name="silicon_run_openlane",
            description=(
                "Run the full OpenLane RTL-to-GDS-II flow for a Verilog design. "
                "Requires OpenLane CLI on PATH (not available in all environments). "
                "Returns {status: 'success'|'error'|'pending', gds_path: str, "
                "log_path: str, returncode: int|null, warnings: [str]}. "
                "Typical flow time: 10–60 minutes for small designs."
            ),
            input_schema={
                "type": "object",
                "required": ["design_name", "verilog_files"],
                "properties": {
                    "design_name": {
                        "type": "string",
                        "description": "Top-level Verilog module name.",
                    },
                    "verilog_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Absolute paths to Verilog source files.",
                    },
                    "pdk": {
                        "type": "string",
                        "description": "PDK identifier (default 'sky130A').",
                        "default": "sky130A",
                    },
                    "clock_period": {
                        "type": "number",
                        "description": "Target clock period in nanoseconds (default 10.0).",
                        "default": 10.0,
                    },
                    "clock_port": {
                        "type": "string",
                        "description": "Primary clock port name (default 'clk').",
                        "default": "clk",
                    },
                    "die_area": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Die bounding box [x0,y0,x1,y1] in µm (default [0,0,100,100]).",
                        "default": [0, 0, 100, 100],
                    },
                    "run_dir": {
                        "type": "string",
                        "description": "Optional absolute path for the run directory.",
                        "default": None,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Subprocess timeout in seconds (default 3600).",
                        "default": 3600,
                    },
                },
            },
        )

        async def _silicon_run_openlane_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"status": "error", "error": f"invalid args: {e}"})

            design_name = a.get("design_name", "").strip()
            verilog_files = a.get("verilog_files", [])
            if not design_name:
                return _json.dumps({"status": "error", "error": "'design_name' is required"})
            if not isinstance(verilog_files, list) or not verilog_files:
                return _json.dumps({"status": "error", "error": "'verilog_files' must be a non-empty list"})

            pdk = a.get("pdk", "sky130A")
            clock_period = float(a.get("clock_period", 10.0))
            clock_port = a.get("clock_port", "clk")
            die_area_raw = a.get("die_area", [0, 0, 100, 100])
            die_area = tuple(die_area_raw) if isinstance(die_area_raw, list) else (0, 0, 100, 100)
            run_dir = a.get("run_dir") or None
            timeout = int(a.get("timeout", 3600))

            try:
                from kerf_silicon.openlane.flow import run_flow
                result = run_flow(
                    design_name=design_name,
                    verilog_files=verilog_files,
                    pdk=pdk,
                    clock_period=clock_period,
                    clock_port=clock_port,
                    die_area=die_area,
                    run_dir=run_dir,
                    timeout=timeout,
                )
                return _json.dumps({
                    "status": result.status,
                    "gds_path": result.gds_path,
                    "log_path": result.log_path,
                    "returncode": result.returncode,
                    "warnings": result.warnings,
                })
            except Exception as exc:
                return _json.dumps({"status": "error", "error": str(exc)})

        ctx.tools.register("silicon_run_openlane", _ol_spec, _silicon_run_openlane_tool)
        provides.append("silicon.openlane")
    except Exception as exc:
        logger.warning("kerf-silicon: failed to load silicon_run_openlane tool: %s", exc)

    # ── 5. silicon_import_ibis ──────────────────────────────────────────────
    try:
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _TS5
        except ImportError:
            from kerf_silicon._compat import ToolSpec as _TS5  # type: ignore

        _ibis_import_spec = _TS5(
            name="silicon_import_ibis",
            description=(
                "Parse an IBIS 7.1 .ibs file and return the component, pin map, "
                "and buffer model summary including IV table sizes and voltage range. "
                "IBIS (Input/Output Buffer Information Specification) is the industry-standard "
                "format for signal-integrity buffer models used in high-speed digital interfaces "
                "(DDR, PCIe, USB, SerDes). "
                "Returns {ok, component, ibis_version, models: [{name, model_type, vcc_typ, "
                "pulldown_points, pullup_points, has_ramp}], pins: [{name, signal, model_name}]}. "
                "NOTE: NOT IBIS-certified. Covers core 7.1 keywords only. "
                "Spec: https://ibis.org/ver7.1/ibis_specs_7_1.pdf"
            ),
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the .ibs file to parse.",
                    },
                },
            },
        )

        async def _silicon_import_ibis_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"ok": False, "error": f"invalid args: {e}", "code": "BAD_ARGS"})
            path = a.get("path", "").strip()
            if not path:
                return _json.dumps({"ok": False, "error": "'path' is required", "code": "BAD_ARGS"})
            try:
                from kerf_silicon.ibis_import import parse_ibis_file
                model = parse_ibis_file(path)
                models_summary = []
                for m_name, buf in model.models.items():
                    models_summary.append({
                        "name": m_name,
                        "model_type": buf.model_type,
                        "vcc_min": buf.vcc_min,
                        "vcc_typ": buf.vcc_typ,
                        "vcc_max": buf.vcc_max,
                        "c_comp_pf": round(buf.c_comp * 1e12, 3),
                        "pulldown_points": len(buf.pulldown.points) if buf.pulldown else 0,
                        "pullup_points": len(buf.pullup.points) if buf.pullup else 0,
                        "gnd_clamp_points": len(buf.gnd_clamp.points) if buf.gnd_clamp else 0,
                        "power_clamp_points": len(buf.power_clamp.points) if buf.power_clamp else 0,
                        "has_ramp": buf.ramp is not None,
                        "ramp_dvdt_rise_v_per_ns": (
                            round(buf.ramp.dv_dt_rise * 1e-9, 4) if buf.ramp else None
                        ),
                    })
                pins_list = [
                    {
                        "name": p.name,
                        "signal": p.signal,
                        "model_name": p.model_name,
                        "R_pin_ohm": p.R_pin,
                        "L_pin_pH": round(p.L_pin * 1e12, 3),
                        "C_pin_pF": round(p.C_pin * 1e12, 3),
                    }
                    for p in model.pins.values()
                ]
                return _json.dumps({
                    "ok": True,
                    "ibis_version": model.ibis_version,
                    "component": {
                        "name": model.component.name,
                        "manufacturer": model.component.manufacturer,
                        "package_type": model.component.package_type,
                    },
                    "models": models_summary,
                    "pins": pins_list,
                    "source_file": model.source_file,
                    "compliance_note": (
                        "IBIS 7.1 spec compliance — NOT IBIS-certified. "
                        "Core keywords parsed; algorithmic models and sub-model matrices not supported."
                    ),
                })
            except FileNotFoundError as exc:
                return _json.dumps({"ok": False, "error": str(exc), "code": "FILE_NOT_FOUND"})
            except Exception as exc:
                return _json.dumps({"ok": False, "error": str(exc), "code": "IBIS_ERROR"})

        ctx.tools.register("silicon_import_ibis", _ibis_import_spec, _silicon_import_ibis_tool)

    except Exception as exc:
        logger.warning("kerf-silicon: failed to load silicon_import_ibis tool: %s", exc)

    # ── 6. silicon_eye_diagram ──────────────────────────────────────────────
    try:
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _TS6
        except ImportError:
            from kerf_silicon._compat import ToolSpec as _TS6  # type: ignore

        _eye_spec = _TS6(
            name="silicon_eye_diagram",
            description=(
                "Compute analytical eye-diagram metrics for a driver pin at a given "
                "bit-rate and termination load. Requires a previously parsed IBIS model "
                "(call silicon_import_ibis first to get the file path validated, then "
                "provide the same path here). "
                "Returns {ok, pin, model_name, frequency_ghz, load_ohm, "
                "opening_height_mV, opening_width_ps, jitter_estimate_ps, "
                "symbol_period_ps, rise_time_ps, r_driver_eff_ohm, vcc_typ}. "
                "Eye opening > 50% Vcc indicates a functional interface margin. "
                "IMPORTANT: This is an analytical approximation based on IBIS IV curves "
                "and ramp data — not a full waveform simulation. "
                "NOT IBIS-certified."
            ),
            input_schema={
                "type": "object",
                "required": ["path", "pin_name"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the .ibs file.",
                    },
                    "pin_name": {
                        "type": "string",
                        "description": "Pin name from the [Pin] section of the .ibs file.",
                    },
                    "frequency_ghz": {
                        "type": "number",
                        "description": "Bit-rate frequency in GHz (e.g. 1.0 for 1 Gbps NRZ). Default 1.0.",
                        "default": 1.0,
                    },
                    "load_impedance_ohm": {
                        "type": "number",
                        "description": "Termination resistance in ohms (e.g. 50 for matched load). Default 50.",
                        "default": 50.0,
                    },
                },
            },
        )

        async def _silicon_eye_diagram_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"ok": False, "error": f"invalid args: {e}", "code": "BAD_ARGS"})
            path = a.get("path", "").strip()
            pin_name = a.get("pin_name", "").strip()
            if not path:
                return _json.dumps({"ok": False, "error": "'path' is required", "code": "BAD_ARGS"})
            if not pin_name:
                return _json.dumps({"ok": False, "error": "'pin_name' is required", "code": "BAD_ARGS"})
            frequency_ghz = float(a.get("frequency_ghz", 1.0))
            load_ohm = float(a.get("load_impedance_ohm", 50.0))
            try:
                from kerf_silicon.ibis_import import (
                    parse_ibis_file,
                    compute_eye_diagram_at_pin,
                )
                model = parse_ibis_file(path)
                eye = compute_eye_diagram_at_pin(pin_name, model, frequency_ghz, load_ohm)
                vcc = model.models[model.pins[pin_name].model_name].vcc_typ
                eye_pct = (eye.opening_height_mV / (vcc * 1000.0)) * 100.0 if vcc > 0 else 0.0
                return _json.dumps({
                    "ok": True,
                    "pin": pin_name,
                    "model_name": eye.model_name,
                    "frequency_ghz": frequency_ghz,
                    "load_ohm": load_ohm,
                    "opening_height_mV": round(eye.opening_height_mV, 2),
                    "opening_height_pct_vcc": round(eye_pct, 1),
                    "opening_width_ps": round(eye.opening_width_ps, 2),
                    "jitter_estimate_ps": round(eye.jitter_estimate_ps, 2),
                    "symbol_period_ps": round(eye.symbol_period_ps, 2),
                    "rise_time_ps": round(eye.rise_time_ps, 2),
                    "r_driver_eff_ohm": round(eye.r_driver_eff_ohm, 2),
                    "vcc_typ": eye.vcc_typ,
                    "compliance_note": (
                        "IBIS 7.1 spec compliance — NOT IBIS-certified. "
                        "Analytical approximation only."
                    ),
                })
            except FileNotFoundError as exc:
                return _json.dumps({"ok": False, "error": str(exc), "code": "FILE_NOT_FOUND"})
            except (KeyError, ValueError) as exc:
                return _json.dumps({"ok": False, "error": str(exc), "code": "BAD_ARGS"})
            except Exception as exc:
                return _json.dumps({"ok": False, "error": str(exc), "code": "EYE_ERROR"})

        ctx.tools.register("silicon_eye_diagram", _eye_spec, _silicon_eye_diagram_tool)
        provides.append("silicon.ibis")
    except Exception as exc:
        logger.warning("kerf-silicon: failed to load silicon_eye_diagram tool: %s", exc)
