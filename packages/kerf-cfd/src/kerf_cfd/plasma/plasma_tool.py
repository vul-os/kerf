"""
kerf_cfd.plasma.plasma_tool
============================
LLM tool: plasma_discharge_simulate

Exposes the 1-D drift-diffusion glow-discharge solver as a JSON-RPC tool.

Tool input schema
-----------------
  gas      : str  — "air" | "argon" | "helium" | "nitrogen"  (default "air")
  pressure : float — gas pressure [Pa] (default 1000 Pa = 10 mbar)
  gap      : float — electrode separation [m] (default 0.01 m = 1 cm)
  voltage  : float — applied DC voltage [V]  (default 400 V)
  n_cells  : int   — spatial grid cells (default 200; range 50–1000)

Tool output (JSON)
------------------
  ok                      : bool
  x_m                     : [float, ...]  — node positions [m]
  n_e_m3                  : [float, ...]  — electron density [m⁻³]
  n_i_m3                  : [float, ...]  — ion density [m⁻³]
  E_field_V_m             : [float, ...]  — electric field [V/m]
  phi_V                   : [float, ...]  — potential [V]
  ionization_rate_m3_s    : [float, ...]  — Townsend source [m⁻³ s⁻¹]
  current_density_A_m2    : float         — discharge current [A/m²]
  converged               : bool
  n_steps                 : int
  breakdown_estimate_V    : float         — Paschen V_bd for these pd conditions
  sheath_thickness_m      : float         — cathode sheath thickness [m]
  peak_E_near_cathode_V_m : float
  peak_n_e_m3             : float
  peak_n_i_m3             : float
  paschen_curve           : {pd_Pa_m: [...], V_bd_V: [...]}  — Paschen curve for this gas
  model_notes             : str           — honest model limitations

Limitations (always returned in model_notes)
--------------------------------------------
  Drift-diffusion fluid model, not kinetic/PIC. Local-field approximation.
  Single gas species. No photoionization, metastables, attachment. DC only.
  Not validated vs COMSOL Plasma module. Design exploration only.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


_PLASMA_TOOL_NOTES = (
    "DRIFT-DIFFUSION FLUID MODEL (not kinetic/PIC). "
    "Local-field approximation; transport coefficients depend only on instantaneous E/N. "
    "Single gas species; no photoionization, no metastable kinetics, no attachment/detachment. "
    "DC steady-state only; no RF/ICP/DBD modes. "
    "Electron temperature estimated from local-field lookup (2–4 eV); not self-consistently solved. "
    "Not validated against COMSOL Plasma module outputs. "
    "Use for design-exploration / trend analysis only — not safety-critical sizing."
)

plasma_discharge_simulate_spec = ToolSpec(
    name="plasma_discharge_simulate",
    description=(
        "Simulate a 1-D DC glow discharge (low-temperature plasma) between parallel electrodes "
        "using a drift-diffusion fluid model with Townsend ionisation and self-consistent Poisson "
        "field (Hagelaar & Pitchford 2005; Lieberman & Lichtenberg 2005). "
        "Returns electron / ion density profiles, electric field, potential, ionisation rate, "
        "current density, Paschen breakdown estimate, and cathode sheath thickness. "
        "Supported gases: air, argon, helium, nitrogen. "
        "NOTE: drift-diffusion fluid model only; not kinetic / PIC; limited chemistry set; "
        "design-exploration accuracy."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gas": {
                "type": "string",
                "enum": ["air", "argon", "helium", "nitrogen"],
                "description": (
                    "Working gas. 'air' (default) uses N₂-dominant Townsend coefficients "
                    "(Lieberman Tab 2.3). 'argon' has lower breakdown voltage. "
                    "'helium' has the lowest Paschen minimum. 'nitrogen' same as air."
                ),
            },
            "pressure": {
                "type": "number",
                "description": (
                    "Gas pressure [Pa]. Typical glow discharges: 100–10 000 Pa (1–100 mbar). "
                    "Default: 1000 Pa (10 mbar)."
                ),
            },
            "gap": {
                "type": "number",
                "description": (
                    "Electrode gap [m]. Typical: 0.005–0.05 m (0.5–5 cm). Default: 0.01 m."
                ),
            },
            "voltage": {
                "type": "number",
                "description": (
                    "Applied DC anode–cathode voltage [V]. Must exceed Paschen V_bd "
                    "for breakdown. Default: 400 V."
                ),
            },
            "n_cells": {
                "type": "integer",
                "description": (
                    "Number of spatial grid cells (default 200; min 50; max 1000). "
                    "Higher values resolve cathode sheath better."
                ),
            },
        },
        "required": [],
    },
)


# ---------------------------------------------------------------------------
# Sync core
# ---------------------------------------------------------------------------

def run_plasma_discharge_sync(
    gas: str = "air",
    pressure: float = 1000.0,
    gap: float = 0.01,
    voltage: float = 400.0,
    n_cells: int = 200,
) -> dict[str, Any]:
    """Run the plasma discharge solver and return JSON-serialisable result."""
    import math

    # Validate
    valid_gases = {"air", "argon", "helium", "nitrogen"}
    if gas.lower() not in valid_gases:
        return {"ok": False, "error": f"gas must be one of {sorted(valid_gases)}", "code": "BAD_ARGS"}
    if pressure <= 0 or not math.isfinite(pressure):
        return {"ok": False, "error": "pressure must be positive and finite [Pa]", "code": "BAD_ARGS"}
    if gap <= 0 or not math.isfinite(gap) or gap > 1.0:
        return {"ok": False, "error": "gap must be in (0, 1] metres", "code": "BAD_ARGS"}
    if voltage <= 0 or not math.isfinite(voltage) or voltage > 1e6:
        return {"ok": False, "error": "voltage must be in (0, 1e6] volts", "code": "BAD_ARGS"}
    if not (50 <= n_cells <= 1000):
        return {"ok": False, "error": "n_cells must be in [50, 1000]", "code": "BAD_ARGS"}

    from kerf_cfd.plasma.drift_diffusion import run_discharge, PlasmaGas, paschen_voltage

    result = run_discharge(
        gas=gas,
        pressure_Pa=pressure,
        gap_m=gap,
        voltage_V=voltage,
        n_cells=n_cells,
    )

    # -- Paschen curve over a range of pd values --
    gas_obj = PlasmaGas.from_name(gas)
    # pd range: from pd_min*0.5 to pd_max = 100 * gap * pressure, log-spaced
    pd_values = np.logspace(-3, 1, 60)  # 1e-3 to 10 Pa·m
    V_bd_arr = np.array([paschen_voltage(gas_obj, pd, 1.0) for pd in pd_values])
    # Cap at 1e6 for plotting
    V_bd_plot = np.clip(V_bd_arr, 0, 1e6)
    # Find Paschen minimum
    finite_mask = np.isfinite(V_bd_arr) & (V_bd_arr < 1e6)
    if finite_mask.any():
        idx_min = int(np.argmin(V_bd_arr[finite_mask]))
        pd_finite = pd_values[finite_mask]
        Vbd_finite = V_bd_arr[finite_mask]
        paschen_min_V = float(Vbd_finite[idx_min])
        paschen_min_pd = float(pd_finite[idx_min])
    else:
        paschen_min_V = float("inf")
        paschen_min_pd = float("nan")

    result["paschen_curve"] = {
        "pd_Pa_m": pd_values.tolist(),
        "V_bd_V": V_bd_plot.tolist(),
        "minimum_V": paschen_min_V,
        "minimum_pd_Pa_m": paschen_min_pd,
    }
    result["model_notes"] = _PLASMA_TOOL_NOTES

    # Summarise key findings
    result["summary"] = {
        "breakdown_voltage_V": result["breakdown_estimate_V"],
        "applied_above_breakdown": voltage > result["breakdown_estimate_V"],
        "sheath_thickness_mm": round(result["sheath_thickness_m"] * 1000, 3),
        "peak_E_cathode_kV_m": round(result["peak_E_near_cathode_V_m"] / 1000, 2),
        "current_density_mA_m2": round(result["current_density_A_m2"] * 1000, 4),
    }

    return result


# ---------------------------------------------------------------------------
# Async LLM handler
# ---------------------------------------------------------------------------

async def run_plasma_discharge_simulate(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        gas = str(args.get("gas", "air"))
        pressure = float(args.get("pressure", 1000.0))
        gap = float(args.get("gap", 0.01))
        voltage = float(args.get("voltage", 400.0))
        n_cells = int(args.get("n_cells", 200))
    except (TypeError, ValueError) as exc:
        return err_payload(f"invalid argument: {exc}", "BAD_ARGS")

    result = run_plasma_discharge_sync(
        gas=gas,
        pressure=pressure,
        gap=gap,
        voltage=voltage,
        n_cells=n_cells,
    )

    if not result.get("ok"):
        return err_payload(result.get("error", "solver error"), result.get("code", "ERROR"))
    return ok_payload(result)
