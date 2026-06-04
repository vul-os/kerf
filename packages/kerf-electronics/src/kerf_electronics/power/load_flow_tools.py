"""
kerf_electronics.power.load_flow_tools — LLM tool wrappers for AC power flow.

Registers tools:
    power_build_y_bus        — build bus admittance matrix from system data
    power_ac_load_flow       — Newton-Raphson AC load flow (N-R)

All tools return JSON-serialisable dicts.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Stevenson, W.D. (1982). "Elements of Power System Analysis", 4th ed.
Grainger, J.J. & Stevenson, W.D. (1994). "Power System Analysis."

Author: imranparuk
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

from kerf_electronics.power.ac_load_flow import (
    PowerBus,
    PowerLine,
    PowerSystem,
    build_y_bus,
)


# ---------------------------------------------------------------------------
# Helper: parse system from dict payload
# ---------------------------------------------------------------------------

def _parse_system(payload: dict) -> tuple[PowerSystem | None, str | None]:
    """
    Parse a PowerSystem from a dict payload.

    Expected payload structure:
    {
        "buses": [
            {"bus_id": "B1", "bus_type": "slack", "P_specified_mw": 0,
             "Q_specified_mvar": 0, "V_specified_pu": 1.0, "angle_deg": 0},
            ...
        ],
        "lines": [
            {"line_id": "L1", "from_bus": "B1", "to_bus": "B2",
             "R_pu": 0.01, "X_pu": 0.05, "B_pu": 0.0},
            ...
        ],
        "base_mva": 100.0
    }
    """
    try:
        buses_raw = payload.get("buses", [])
        lines_raw = payload.get("lines", [])
        base_mva = float(payload.get("base_mva", 100.0))

        buses = []
        for b in buses_raw:
            buses.append(PowerBus(
                bus_id=str(b["bus_id"]),
                bus_type=str(b["bus_type"]),
                P_specified_mw=float(b.get("P_specified_mw", 0.0)),
                Q_specified_mvar=float(b.get("Q_specified_mvar", 0.0)),
                V_specified_pu=float(b.get("V_specified_pu", 1.0)),
                angle_deg=float(b.get("angle_deg", 0.0)),
            ))

        lines = []
        for ln in lines_raw:
            lines.append(PowerLine(
                line_id=str(ln["line_id"]),
                from_bus=str(ln["from_bus"]),
                to_bus=str(ln["to_bus"]),
                R_pu=float(ln["R_pu"]),
                X_pu=float(ln["X_pu"]),
                B_pu=float(ln.get("B_pu", 0.0)),
            ))

        system = PowerSystem(buses=buses, lines=lines, base_mva=base_mva)
        return system, None

    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Tool definitions (plain dicts — no registry dependency)
# ---------------------------------------------------------------------------

def _handle_power_build_y_bus(payload: dict) -> dict:
    """
    Build the bus admittance matrix for a power system.

    Returns the Y-bus (G + jB) as separate real/imaginary arrays.
    """
    system, err = _parse_system(payload)
    if err:
        return {"ok": False, "reason": f"Failed to parse system: {err}"}

    try:
        Y = build_y_bus(system)
        n = Y.shape[0]
        bus_ids = [b.bus_id for b in system.buses]
        return {
            "ok": True,
            "n_buses": n,
            "bus_ids": bus_ids,
            "G": [[float(Y.real[i, j]) for j in range(n)] for i in range(n)],
            "B": [[float(Y.imag[i, j]) for j in range(n)] for i in range(n)],
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _handle_power_ac_load_flow(payload: dict) -> dict:
    """
    Run Newton-Raphson AC load flow on the given power system.

    Returns converged flag, bus voltages, powers, and line flows.
    """
    system, err = _parse_system(payload)
    if err:
        return {"ok": False, "reason": f"Failed to parse system: {err}"}

    max_iter = int(payload.get("max_iter", 20))
    tol = float(payload.get("tol", 1e-6))

    try:
        result = system.newton_raphson_load_flow(max_iter=max_iter, tol=tol)
        result["ok"] = True
        return result
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# TOOLS registry list (for plugin.py discovery)
# ---------------------------------------------------------------------------

_power_y_bus_spec = {
    "name": "power_build_y_bus",
    "description": (
        "Build the bus admittance matrix (Y_bus = G + jB) for an AC power system.\n"
        "\n"
        "Accepts a list of buses and lines (in per-unit on base_mva).\n"
        "Returns the G and B matrices separately.\n"
        "\n"
        "References: Stevenson (1982) §5; Grainger-Stevenson (1994) §6."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "buses": {
                "type": "array",
                "description": "List of bus objects with bus_id, bus_type, etc.",
            },
            "lines": {
                "type": "array",
                "description": "List of line objects with line_id, from_bus, to_bus, R_pu, X_pu, B_pu.",
            },
            "base_mva": {
                "type": "number",
                "description": "System MVA base (default 100).",
            },
        },
        "required": ["buses", "lines"],
    },
}

_power_load_flow_spec = {
    "name": "power_ac_load_flow",
    "description": (
        "Newton-Raphson AC load flow for a power system.\n"
        "\n"
        "Accepts bus and line data in per-unit. Exactly one slack bus required.\n"
        "Returns converged flag, bus voltages (|V|, θ), injected powers, "
        "and line MW/Mvar flows.\n"
        "\n"
        "References: Stevenson (1982) §9; Grainger-Stevenson (1994) §9."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "buses": {
                "type": "array",
                "description": "List of bus objects.",
            },
            "lines": {
                "type": "array",
                "description": "List of line objects.",
            },
            "base_mva": {
                "type": "number",
                "description": "System MVA base (default 100).",
            },
            "max_iter": {
                "type": "integer",
                "description": "Maximum N-R iterations (default 20).",
            },
            "tol": {
                "type": "number",
                "description": "Convergence tolerance in pu (default 1e-6).",
            },
        },
        "required": ["buses", "lines"],
    },
}


TOOLS = [
    ("power_build_y_bus", _power_y_bus_spec, _handle_power_build_y_bus),
    ("power_ac_load_flow", _power_load_flow_spec, _handle_power_ac_load_flow),
]
