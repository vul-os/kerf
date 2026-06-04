"""
LLM tool wrappers for thermo-elastic coupled FEA.

Wave 12E: thermal-structural coupled + composite laminate + Tsai-Wu.

Tools
-----
fem_thermo_elastic_staggered  : staggered coupling on a 1-D bar
fem_thermo_elastic_monolithic : monolithic coupling on a 1-D bar

All tools follow the kerf_fem convention:
  - ToolSpec descriptor
  - async run_* handler
  - Pure dict I/O (no numpy in payload)
  - err_payload / ok_payload helpers
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_fem.multiphysics.thermal_structural import (
    ThermoElasticMaterial,
    solve_thermo_elastic_staggered,
    solve_thermo_elastic_monolithic,
)


# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

_MATERIAL_SCHEMA = {
    "type": "object",
    "description": "Isotropic thermo-elastic material properties.",
    "properties": {
        "youngs_modulus_pa":          {"type": "number", "description": "Young's modulus E [Pa]"},
        "poisson":                    {"type": "number", "description": "Poisson ratio ν"},
        "thermal_conductivity_w_m_k": {"type": "number", "description": "Thermal conductivity k [W/(m·K)]"},
        "thermal_expansion_per_k":    {"type": "number", "description": "CTE α [1/K]"},
        "specific_heat_j_kg_k":       {"type": "number", "description": "Specific heat c_p [J/(kg·K)]"},
        "density_kg_m3":              {"type": "number", "description": "Density ρ [kg/m³]"},
        "thermal_softening_beta":     {"type": "number", "description": "Linear softening β: E(T)=E₀(1-β(T-Tref))"},
    },
    "required": [
        "youngs_modulus_pa", "poisson", "thermal_conductivity_w_m_k",
        "thermal_expansion_per_k", "specific_heat_j_kg_k", "density_kg_m3",
    ],
}

_MESH_SCHEMA = {
    "type": "object",
    "description": "1-D bar mesh definition.",
    "properties": {
        "nodes": {
            "type": "array",
            "items": {"type": "number"},
            "description": "Nodal x-coordinates [m], uniformly spaced.",
        },
        "area": {"type": "number", "description": "Cross-section area [m²]. Default 1.0."},
    },
    "required": ["nodes"],
}

_THERMAL_BCS_SCHEMA = {
    "type": "object",
    "description": "Thermal boundary conditions.",
    "properties": {
        "temperature": {
            "type": "object",
            "description": "Dirichlet temperature BCs: {node_index: temperature_K}.",
            "additionalProperties": {"type": "number"},
        },
        "flux": {
            "type": "object",
            "description": "Neumann heat-flux BCs: {node_index: flux_W_per_m2}.",
            "additionalProperties": {"type": "number"},
        },
    },
}

_STRUCTURAL_BCS_SCHEMA = {
    "type": "object",
    "description": "Structural boundary conditions.",
    "properties": {
        "displacement": {
            "type": "object",
            "description": "Dirichlet displacement BCs: {node_index: displacement_m} or [dx,dy,dz].",
            "additionalProperties": {},
        },
        "force": {
            "type": "object",
            "description": "Nodal forces: {node_index: [Fx, Fy, Fz]} [N].",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "number"},
            },
        },
    },
}


def _material_from_dict(d: dict) -> ThermoElasticMaterial:
    return ThermoElasticMaterial(
        youngs_modulus_pa=float(d["youngs_modulus_pa"]),
        poisson=float(d["poisson"]),
        thermal_conductivity_w_m_k=float(d["thermal_conductivity_w_m_k"]),
        thermal_expansion_per_k=float(d["thermal_expansion_per_k"]),
        specific_heat_j_kg_k=float(d["specific_heat_j_kg_k"]),
        density_kg_m3=float(d["density_kg_m3"]),
        thermal_softening_beta=float(d.get("thermal_softening_beta", 0.0)),
    )


def _result_to_dict(res) -> dict:
    return {
        "temperatures_K":        res.temperatures.tolist(),
        "displacements_m":       res.displacements.tolist(),
        "stress_at_nodes_Pa":    res.stress_at_nodes.tolist(),
        "thermal_strain":        res.thermal_strain_at_nodes.tolist(),
        "iterations_converged":  res.iterations_converged,
        "residual_norm":         float(res.residual_norm),
        "max_temperature_K":     float(np.max(res.temperatures)),
        "max_displacement_m":    float(np.max(np.abs(res.displacements))),
        "max_stress_Pa":         float(np.max(np.abs(res.stress_at_nodes))),
    }


# ---------------------------------------------------------------------------
# Tool: fem_thermo_elastic_staggered
# ---------------------------------------------------------------------------

_fem_thermo_elastic_staggered_spec = ToolSpec(
    name="fem_thermo_elastic_staggered",
    description=(
        "Solve a 1-D thermo-elastic coupled problem using the staggered (Picard) "
        "scheme. Computes steady-state temperature distribution, axial displacements "
        "due to thermal expansion, and thermal stresses. Supports temperature-dependent "
        "Young's modulus. "
        "Reference: Zienkiewicz & Taylor (2000) §13."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mesh":            _MESH_SCHEMA,
            "material":        _MATERIAL_SCHEMA,
            "thermal_bcs":     _THERMAL_BCS_SCHEMA,
            "structural_bcs":  _STRUCTURAL_BCS_SCHEMA,
            "T_reference":     {"type": "number", "description": "Stress-free reference temperature [K]. Default 293.15."},
            "max_iter":        {"type": "integer", "description": "Max Picard iterations. Default 30."},
            "tol":             {"type": "number",  "description": "Convergence tolerance. Default 1e-5."},
        },
        "required": ["mesh", "material", "thermal_bcs", "structural_bcs"],
    },
)


@register(_fem_thermo_elastic_staggered_spec, write=False)
async def run_fem_thermo_elastic_staggered(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    try:
        mesh = a["mesh"]
        material = _material_from_dict(a["material"])
        thermal_bcs = a.get("thermal_bcs", {})
        structural_bcs = a.get("structural_bcs", {})
        T_ref = float(a.get("T_reference", 293.15))
        max_iter = int(a.get("max_iter", 30))
        tol = float(a.get("tol", 1e-5))
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"parameter error: {e}", "BAD_ARGS")

    try:
        result = solve_thermo_elastic_staggered(
            mesh=mesh,
            material=material,
            thermal_bcs=thermal_bcs,
            structural_bcs=structural_bcs,
            T_reference=T_ref,
            max_iter=max_iter,
            tol=tol,
        )
    except Exception as e:
        return err_payload(f"solver error: {e}", "SOLVER_ERROR")

    return ok_payload({"ok": True, **_result_to_dict(result)})


# ---------------------------------------------------------------------------
# Tool: fem_thermo_elastic_monolithic
# ---------------------------------------------------------------------------

_fem_thermo_elastic_monolithic_spec = ToolSpec(
    name="fem_thermo_elastic_monolithic",
    description=(
        "Solve a 1-D thermo-elastic coupled problem using the monolithic scheme. "
        "Assembles and solves the full coupled system [K_uu K_uT; 0 K_TT]{u,T}={F,Q} "
        "in one direct solve. More accurate than staggered for strong coupling. "
        "Reference: Lewis et al. (2004) §7; Zienkiewicz & Taylor (2000) §13."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mesh":           _MESH_SCHEMA,
            "material":       _MATERIAL_SCHEMA,
            "thermal_bcs":    _THERMAL_BCS_SCHEMA,
            "structural_bcs": _STRUCTURAL_BCS_SCHEMA,
            "T_reference":    {"type": "number", "description": "Stress-free reference temperature [K]. Default 293.15."},
        },
        "required": ["mesh", "material", "thermal_bcs", "structural_bcs"],
    },
)


@register(_fem_thermo_elastic_monolithic_spec, write=False)
async def run_fem_thermo_elastic_monolithic(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    try:
        mesh = a["mesh"]
        material = _material_from_dict(a["material"])
        thermal_bcs = a.get("thermal_bcs", {})
        structural_bcs = a.get("structural_bcs", {})
        T_ref = float(a.get("T_reference", 293.15))
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"parameter error: {e}", "BAD_ARGS")

    try:
        result = solve_thermo_elastic_monolithic(
            mesh=mesh,
            material=material,
            thermal_bcs=thermal_bcs,
            structural_bcs=structural_bcs,
            T_reference=T_ref,
        )
    except Exception as e:
        return err_payload(f"solver error: {e}", "SOLVER_ERROR")

    return ok_payload({"ok": True, **_result_to_dict(result)})
