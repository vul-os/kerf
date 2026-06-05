"""
LLM tool: cfd_reacting_flow_multispecies

General multi-species finite-rate chemistry solver for reacting flows.

Exposes a single LLM-callable tool that accepts a user-supplied reaction
mechanism (Arrhenius reactions) and initial conditions, runs a 1-D plug-flow
reactor to steady state, and returns species fields, conversion, and adiabatic
flame temperature.

# Wave: multi-species reacting flow solver (COMSOL compare flip)
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_multispecies_spec = ToolSpec(
    name="cfd_reacting_flow_multispecies",
    description=(
        "General multi-species reacting-flow solver with finite-rate Arrhenius "
        "chemistry. Solves coupled species conservation (∂(ρYk)/∂t + ∇·(ρuYk) = "
        "∇·(ρDk∇Yk) + ωk) for N species with a user-supplied reaction mechanism "
        "(Arrhenius rate = A·T^b·exp(-Ea/RT)·∏[X]^order). "
        "Returns: species mass-fraction profiles along reactor, fuel conversion, "
        "adiabatic flame temperature, and equilibrium composition. "
        "Built-in mechanisms: 'CH4_1step' (Westbrook-Dryer 1981), "
        "'H2_1step' (WD 1981), 'AB_to_C' (generic bimolecular test). "
        "DESIGN EXPLORATION ONLY — not OpenFOAM-validated."
    ),
    input_schema={
        "type": "object",
        "required": ["inlet_composition", "inlet_temperature"],
        "properties": {
            "mechanism": {
                "type": "string",
                "description": (
                    "Built-in mechanism: 'CH4_1step' | 'H2_1step' | 'AB_to_C'. "
                    "If 'custom', provide species_list and reactions."
                ),
                "default": "CH4_1step",
            },
            "species_list": {
                "type": "array",
                "description": (
                    "Custom species definitions (required if mechanism='custom'). "
                    "Each item: {name, molar_mass_kg_per_mol, hf_J_per_kg, "
                    "diffusivity_m2_per_s (opt), cp_J_per_kgK (opt)}"
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "molar_mass_kg_per_mol", "hf_J_per_kg"],
                    "properties": {
                        "name": {"type": "string"},
                        "molar_mass_kg_per_mol": {"type": "number"},
                        "hf_J_per_kg": {"type": "number"},
                        "diffusivity_m2_per_s": {"type": "number", "default": 2.5e-5},
                        "cp_J_per_kgK": {"type": "number", "default": 1100.0},
                    },
                },
            },
            "reactions": {
                "type": "array",
                "description": (
                    "Custom reaction definitions (required if mechanism='custom'). "
                    "Each: {A, b, Ea_J_per_mol, reactant_stoich: {name: coeff}, "
                    "product_stoich: {name: coeff}, reactant_orders: {name: order} (opt)}"
                ),
                "items": {
                    "type": "object",
                    "required": ["A", "b", "Ea_J_per_mol",
                                 "reactant_stoich", "product_stoich"],
                    "properties": {
                        "A": {"type": "number"},
                        "b": {"type": "number"},
                        "Ea_J_per_mol": {"type": "number"},
                        "reactant_stoich": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                        },
                        "product_stoich": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                        },
                        "reactant_orders": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                        },
                    },
                },
            },
            "inlet_composition": {
                "type": "object",
                "description": (
                    "Inlet mass fractions {species_name: fraction}. "
                    "Must sum to 1.0 (remainder assigned to bath species if underdetermined)."
                ),
                "additionalProperties": {"type": "number"},
            },
            "inlet_temperature": {
                "type": "number",
                "description": "Inlet temperature [K].",
            },
            "inlet_density": {
                "type": "number",
                "description": "Inlet mixture density [kg/m³]. Default 1.2.",
                "default": 1.2,
            },
            "reactor_length_m": {
                "type": "number",
                "description": "Reactor / flow domain length [m]. Default 0.1.",
                "default": 0.1,
            },
            "velocity_m_per_s": {
                "type": "number",
                "description": "Axial flow velocity [m/s]. Default 0.5.",
                "default": 0.5,
            },
            "n_cells": {
                "type": "integer",
                "description": "Number of 1-D reactor cells. Default 50.",
                "default": 50,
            },
            "max_steps": {
                "type": "integer",
                "description": "Maximum time steps for convergence. Default 5000.",
                "default": 5000,
            },
            "pressure_Pa": {
                "type": "number",
                "description": "Operating pressure [Pa]. Default 101325.",
                "default": 101325.0,
            },
            "bath_species": {
                "type": "string",
                "description": (
                    "Name of the inert bath-gas species (e.g. 'N2'). "
                    "Defaults to the last species in the mechanism."
                ),
            },
            "return_profiles": {
                "type": "boolean",
                "description": "Include full per-cell species profiles in output. Default false.",
                "default": False,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

@register(_multispecies_spec, write=False)
async def run_cfd_reacting_flow_multispecies(params: dict, ctx: Any = None) -> str:
    """LLM tool handler for cfd_reacting_flow_multispecies."""
    try:
        from kerf_cfd.combustion.multispecies_reacting_flow import (
            Species,
            ArrheniusReaction,
            MultispeciesState,
            solve_reactor,
            adiabatic_flame_temperature,
            fuel_conversion,
            ch4_one_step,
            h2_one_step,
            generic_ab_to_c,
        )

        mechanism = params.get("mechanism", "CH4_1step")

        # ── Build species + reactions ──────────────────────────────────────
        if mechanism == "CH4_1step":
            species_list, reactions = ch4_one_step()
            fuel_name = "CH4"
        elif mechanism == "H2_1step":
            species_list, reactions = h2_one_step()
            fuel_name = "H2"
        elif mechanism == "AB_to_C":
            species_list, reactions = generic_ab_to_c()
            fuel_name = "A"
        elif mechanism == "custom":
            sp_defs = params.get("species_list", [])
            rxn_defs = params.get("reactions", [])
            if not sp_defs or not rxn_defs:
                return err_payload(
                    "mechanism='custom' requires 'species_list' and 'reactions'.",
                    "BAD_ARGS",
                )
            species_list = [
                Species(
                    name=sp["name"],
                    molar_mass=float(sp["molar_mass_kg_per_mol"]),
                    hf=float(sp["hf_J_per_kg"]),
                    diffusivity=float(sp.get("diffusivity_m2_per_s", 2.5e-5)),
                    cp=float(sp.get("cp_J_per_kgK", 1100.0)),
                )
                for sp in sp_defs
            ]
            reactions = [
                ArrheniusReaction(
                    A=float(r["A"]),
                    b=float(r["b"]),
                    Ea=float(r["Ea_J_per_mol"]),
                    reactant_stoich={k: float(v) for k, v in r["reactant_stoich"].items()},
                    product_stoich={k: float(v) for k, v in r["product_stoich"].items()},
                    reactant_orders=(
                        {k: float(v) for k, v in r["reactant_orders"].items()}
                        if r.get("reactant_orders") else None
                    ),
                )
                for r in rxn_defs
            ]
            # Guess fuel = first reactant of first reaction
            fuel_name = list(reactions[0].reactant_stoich.keys())[0]
        else:
            return err_payload(
                f"Unknown mechanism '{mechanism}'. "
                "Use 'CH4_1step', 'H2_1step', 'AB_to_C', or 'custom'.",
                "BAD_ARGS",
            )

        inlet_composition = {k: float(v) for k, v in params["inlet_composition"].items()}
        T_inlet = float(params["inlet_temperature"])
        rho_inlet = float(params.get("inlet_density", 1.2))
        length = float(params.get("reactor_length_m", 0.1))
        velocity = float(params.get("velocity_m_per_s", 0.5))
        n_cells = int(params.get("n_cells", 50))
        max_steps = int(params.get("max_steps", 5000))
        pressure = float(params.get("pressure_Pa", 101325.0))
        bath_sp = params.get("bath_species", None)
        return_profiles = bool(params.get("return_profiles", False))

        # ── Run reactor ────────────────────────────────────────────────────
        state = solve_reactor(
            species_list=species_list,
            reactions=reactions,
            Y_inlet=inlet_composition,
            T_inlet=T_inlet,
            rho_inlet=rho_inlet,
            n_cells=n_cells,
            length=length,
            velocity=velocity,
            max_steps=max_steps,
            bath_species=bath_sp,
            pressure=pressure,
        )

        # ── Diagnostics ────────────────────────────────────────────────────
        # Fuel conversion
        Y_fuel_inlet = inlet_composition.get(fuel_name, 0.0)
        if Y_fuel_inlet > 1e-12:
            conv = fuel_conversion(state, fuel_name, Y_fuel_inlet)
            outlet_conversion = float(conv[-1])
            mean_conversion = float(np.mean(conv))
        else:
            outlet_conversion = 0.0
            mean_conversion = 0.0

        # Adiabatic flame temperature
        T_ad = adiabatic_flame_temperature(
            species_list=species_list,
            Y_react=inlet_composition,
            T_react=T_inlet,
            rho=rho_inlet,
            pressure=pressure,
        )

        # Outlet composition
        outlet_Y = {sp.name: float(state.Y[-1, i]) for i, sp in enumerate(species_list)}
        outlet_T = float(state.temperature[-1])
        max_T = float(np.max(state.temperature))

        # Summary
        result: dict = {
            "mechanism": mechanism,
            "n_species": state.n_species,
            "n_cells": state.n_cells,
            "species_names": [sp.name for sp in species_list],
            "outlet_mass_fractions": outlet_Y,
            "outlet_temperature_K": outlet_T,
            "max_temperature_K": max_T,
            "adiabatic_flame_temperature_K": round(T_ad, 1),
            "fuel": fuel_name,
            "outlet_fuel_conversion": round(outlet_conversion, 6),
            "mean_fuel_conversion": round(mean_conversion, 6),
            "mass_fraction_sum_outlet": round(sum(outlet_Y.values()), 8),
            "reactor_length_m": length,
            "velocity_m_per_s": velocity,
            "references": [
                "Westbrook & Dryer (1981), PECS 7:23-86 — CH4/H2 1-step rates",
                "Williams (1985), Combustion Theory — species transport",
                "Law (2006), Combustion Physics — adiabatic flame temperature",
                "JANAF/NIST (Chase 1998) — species hf values",
            ],
            "honest_flag": (
                "Design-exploration grade; 1-D plug-flow model with simplified "
                "cp and diffusivity.  Not validated against OpenFOAM or "
                "experimental data.  Do not use for safety-critical design."
            ),
        }

        if return_profiles:
            x_arr = np.linspace(0.0, length, n_cells).tolist()
            result["x_m"] = x_arr
            result["temperature_K_profile"] = state.temperature.tolist()
            for i, sp in enumerate(species_list):
                result[f"Y_{sp.name}_profile"] = state.Y[:, i].tolist()
            if Y_fuel_inlet > 1e-12:
                result["fuel_conversion_profile"] = fuel_conversion(
                    state, fuel_name, Y_fuel_inlet
                ).tolist()

        return ok_payload(result)

    except Exception as exc:
        return err_payload(str(exc), "CFD_MULTISPECIES_ERROR")
