"""
kerf_cad_core.elecpower.power_tools — LLM tool wrappers for AC power-flow,
protection coordination, and arc-flash.

Registers tools:
  elecpower_loadflow        — Newton-Raphson AC power-flow (Ybus / NR)
  elecpower_relay_trip      — IEEE C37.112-2018 relay trip time
  elecpower_coordinate      — Protection coordination CTI check
  elecpower_arcflash        — IEEE 1584-2018 arc-flash / NFPA 70E PPE

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
  IEEE Std C37.112-2018 — Inverse-time overcurrent relay equations
  IEEE Std 1584-2018    — Arc-flash hazard calculations
  NFPA 70E-2021         — Electrical safety in the workplace

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.elecpower.loadflow import run_loadflow
from kerf_cad_core.elecpower.protection import relay_trip_time, coordinate
from kerf_cad_core.elecpower.arcflash import arc_flash_analysis


# ---------------------------------------------------------------------------
# Tool: elecpower_loadflow
# ---------------------------------------------------------------------------

_loadflow_spec = ToolSpec(
    name="elecpower_loadflow",
    description=(
        "Newton-Raphson AC power-flow on a bus admittance matrix (Ybus).\n"
        "\n"
        "Builds Ybus from pi-model branches (R, X, B, tap) and solves the full "
        "polar-form Newton-Raphson equations to find per-bus voltages, angles, "
        "line flows, losses, and slack injection.\n"
        "\n"
        "Bus types: slack (reference, V/θ fixed), PV (P/|V| specified), PQ (P/Q specified).\n"
        "\n"
        "Returns converged flag, iterations, per-bus V_pu/θ/P/Q, per-branch flows, "
        "and total system losses.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "buses": {
                "type": "array",
                "description": (
                    "List of bus objects. Each: "
                    "{type: 'slack'|'PV'|'PQ', P_pu: float, Q_pu: float (PQ only), "
                    "V_pu: float (initial guess or specified), theta_deg: float (initial)}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["slack", "PV", "PQ"]},
                        "P_pu": {"type": "number"},
                        "Q_pu": {"type": "number"},
                        "V_pu": {"type": "number"},
                        "theta_deg": {"type": "number"},
                    },
                    "required": ["type"],
                },
            },
            "branches": {
                "type": "array",
                "description": (
                    "List of branch (line/transformer) objects. Each: "
                    "{from_bus: int, to_bus: int, R: float, X: float, "
                    "B: float (total shunt susceptance, default 0), "
                    "tap: float (off-nominal turns ratio, default 1.0)}."
                    " All values in per-unit on Sbase_MVA."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "from_bus": {"type": "integer"},
                        "to_bus": {"type": "integer"},
                        "R": {"type": "number"},
                        "X": {"type": "number"},
                        "B": {"type": "number"},
                        "tap": {"type": "number"},
                    },
                    "required": ["from_bus", "to_bus", "R", "X"],
                },
            },
            "Sbase_MVA": {
                "type": "number",
                "description": "System MVA base (default 100). Used for reporting only.",
            },
            "max_iter": {
                "type": "integer",
                "description": "Maximum Newton-Raphson iterations (default 50).",
            },
            "tol": {
                "type": "number",
                "description": "Convergence tolerance on ‖ΔP,ΔQ‖∞ in p.u. (default 1e-6).",
            },
        },
        "required": ["buses", "branches"],
    },
)


@register(_loadflow_spec, write=False)
async def run_loadflow_tool(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    buses = a.get("buses")
    branches = a.get("branches")
    if buses is None:
        return json.dumps({"ok": False, "reason": "buses is required"})
    if branches is None:
        return json.dumps({"ok": False, "reason": "branches is required"})

    kwargs: dict = {}
    for k in ("Sbase_MVA", "max_iter", "tol"):
        if k in a:
            kwargs[k] = a[k]

    result = run_loadflow(buses, branches, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_relay_trip
# ---------------------------------------------------------------------------

_relay_trip_spec = ToolSpec(
    name="elecpower_relay_trip",
    description=(
        "Calculate relay trip time per IEEE C37.112-2018 inverse-time overcurrent curves.\n"
        "\n"
        "Curves: U1 (Standard Inverse), U2 (Very Inverse), U3 (Extremely Inverse), "
        "U4 (Long-Time Inverse), U5 (Short-Time Inverse).\n"
        "\n"
        "Formula: t = TD × [A / (M^P − 1) + B]  where M = I / I_pickup.\n"
        "\n"
        "Returns trip_time_s, M (multiple of pickup), curve, TD.\n"
        "\n"
        "Errors: {ok:false, reason} if I ≤ Ipickup or invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "I": {
                "type": "number",
                "description": "Fault current (A). Must be > Ipickup.",
            },
            "Ipickup": {
                "type": "number",
                "description": "Relay pickup current (A). Must be > 0.",
            },
            "TD": {
                "type": "number",
                "description": "Time dial setting (positive float, typically 0.5–10).",
            },
            "curve": {
                "type": "string",
                "description": (
                    "Curve code: 'U1' (Standard Inverse), 'U2' (Very Inverse), "
                    "'U3' (Extremely Inverse), 'U4' (Long-Time Inverse), "
                    "'U5' (Short-Time Inverse). Default 'U1'."
                ),
            },
        },
        "required": ["I", "Ipickup", "TD"],
    },
)


@register(_relay_trip_spec, write=False)
async def run_relay_trip(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("I", "Ipickup", "TD"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = relay_trip_time(
        a["I"],
        a["Ipickup"],
        a["TD"],
        a.get("curve", "U1"),
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_coordinate
# ---------------------------------------------------------------------------

_coordinate_spec = ToolSpec(
    name="elecpower_coordinate",
    description=(
        "Check protection coordination (CTI) between upstream and downstream relays.\n"
        "\n"
        "For each fault current in fault_currents, computes trip times for both relays "
        "and verifies CTI = t_upstream − t_downstream ≥ cti_min (default 0.3 s).\n"
        "\n"
        "Returns coordinated flag, per-fault CTI table, and list of violation currents.\n"
        "\n"
        "Errors: {ok:false, reason} for empty fault list. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "upstream": {
                "type": "object",
                "description": "Upstream relay: {Ipickup: float (A), TD: float, curve: str}.",
                "properties": {
                    "Ipickup": {"type": "number"},
                    "TD": {"type": "number"},
                    "curve": {"type": "string"},
                },
                "required": ["Ipickup", "TD"],
            },
            "downstream": {
                "type": "object",
                "description": "Downstream relay: {Ipickup: float (A), TD: float, curve: str}.",
                "properties": {
                    "Ipickup": {"type": "number"},
                    "TD": {"type": "number"},
                    "curve": {"type": "string"},
                },
                "required": ["Ipickup", "TD"],
            },
            "fault_currents": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of fault current levels (A) to check coordination across.",
            },
            "cti_min": {
                "type": "number",
                "description": "Minimum coordination time interval (s). Default 0.3.",
            },
        },
        "required": ["upstream", "downstream", "fault_currents"],
    },
)


@register(_coordinate_spec, write=False)
async def run_coordinate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("upstream", "downstream", "fault_currents"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "cti_min" in a:
        kwargs["cti_min"] = a["cti_min"]

    result = coordinate(a["upstream"], a["downstream"], a["fault_currents"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_arcflash
# ---------------------------------------------------------------------------

_arcflash_spec = ToolSpec(
    name="elecpower_arcflash",
    description=(
        "IEEE 1584-2018 arc-flash incident energy and NFPA 70E PPE category.\n"
        "\n"
        "Calculates:\n"
        "  - Arcing current (nominal and 85% minimum)\n"
        "  - Incident energy (cal/cm²) at working distance\n"
        "  - Arc-flash boundary (AFB) in mm and m\n"
        "  - NFPA 70E-2021 PPE category (0–4 or 'danger' if ≥ 40 cal/cm²)\n"
        "\n"
        "Scope: 208 V – 15 kV, 0.5–106 kA, three-phase systems only.\n"
        "\n"
        "Electrode configurations:\n"
        "  VCB  — vertical conductors in box (most common, default)\n"
        "  VCBB — vertical conductors in box with barrier\n"
        "  HCB  — horizontal conductors in box\n"
        "  VOA  — vertical conductors in open air\n"
        "  HOA  — horizontal conductors in open air\n"
        "\n"
        "Errors: {ok:false, reason} for inputs outside IEEE 1584-2018 scope. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V_kV": {
                "type": "number",
                "description": "System voltage (kV). Range 0.208–15.",
            },
            "Ibf_kA": {
                "type": "number",
                "description": "Available bolted fault current (kA). Range 0.5–106.",
            },
            "t_s": {
                "type": "number",
                "description": "Arcing duration — protective-device clearing time (s).",
            },
            "D_mm": {
                "type": "number",
                "description": (
                    "Working distance (mm). NFPA 70E typical defaults: "
                    "480V = 610 mm (24 in), 4160V = 910 mm (36 in)."
                ),
            },
            "config": {
                "type": "string",
                "enum": ["VCB", "VCBB", "HCB", "VOA", "HOA"],
                "description": "Electrode configuration (default 'VCB').",
            },
            "G_mm": {
                "type": "number",
                "description": (
                    "Electrode gap (mm). If omitted, uses IEEE 1584-2018 typical default "
                    "for the configuration."
                ),
            },
            "E_limit_cal_cm2": {
                "type": "number",
                "description": (
                    "Incident-energy limit for arc-flash boundary (cal/cm²). "
                    "Default 1.2 (onset of 2nd-degree burn)."
                ),
            },
        },
        "required": ["V_kV", "Ibf_kA", "t_s"],
    },
)


@register(_arcflash_spec, write=False)
async def run_arcflash(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("V_kV", "Ibf_kA", "t_s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("D_mm", "config", "G_mm", "E_limit_cal_cm2"):
        if k in a:
            kwargs[k] = a[k]

    result = arc_flash_analysis(a["V_kV"], a["Ibf_kA"], a["t_s"], **kwargs)
    return ok_payload(result)
