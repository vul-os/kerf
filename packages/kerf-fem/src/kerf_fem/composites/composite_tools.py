"""
LLM tool wrappers for composite laminate analysis.

Wave 12E: thermal-structural coupled + composite laminate + Tsai-Wu.

Tools
-----
composite_laminate_abd        : Compute ABD stiffness matrix via CLT
composite_laminate_analyze    : CLT analysis under loads (ply-by-ply stresses)
composite_failure_criterion   : Apply a failure criterion to a ply stress state
composite_first_ply_failure   : First-ply failure analysis of a loaded laminate

All tools follow the kerf_fem convention:
  - ToolSpec descriptor
  - async run_* handler
  - Pure dict I/O
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

from kerf_fem.composites.laminate_classical import (
    LaminaPly,
    Laminate,
    analyze_laminate,
)
from kerf_fem.composites.failure_criteria import (
    first_ply_failure_analysis,
    tsai_wu,
    tsai_hill,
    maximum_stress,
    maximum_strain,
    puck,
    hashin,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLY_SCHEMA = {
    "type": "object",
    "properties": {
        "material_name":    {"type": "string"},
        "E1_pa":            {"type": "number", "description": "Fibre-direction modulus [Pa]"},
        "E2_pa":            {"type": "number", "description": "Transverse modulus [Pa]"},
        "G12_pa":           {"type": "number", "description": "In-plane shear modulus [Pa]"},
        "nu12":             {"type": "number", "description": "Major Poisson ratio"},
        "thickness_mm":     {"type": "number", "description": "Ply thickness [mm]"},
        "orientation_deg":  {"type": "number", "description": "Fibre angle from x-axis [°]"},
        "sigma_1_T_pa":     {"type": "number", "description": "Fibre tensile strength X_T [Pa]"},
        "sigma_1_C_pa":     {"type": "number", "description": "Fibre compressive strength X_C [Pa]"},
        "sigma_2_T_pa":     {"type": "number", "description": "Matrix tensile strength Y_T [Pa]"},
        "sigma_2_C_pa":     {"type": "number", "description": "Matrix compressive strength Y_C [Pa]"},
        "tau_12_pa":        {"type": "number", "description": "Shear strength S [Pa]"},
    },
    "required": [
        "E1_pa", "E2_pa", "G12_pa", "nu12", "thickness_mm", "orientation_deg",
        "sigma_1_T_pa", "sigma_1_C_pa", "sigma_2_T_pa", "sigma_2_C_pa", "tau_12_pa",
    ],
}


def _ply_from_dict(d: dict) -> LaminaPly:
    return LaminaPly(
        material_name=d.get("material_name", ""),
        E1_pa=float(d["E1_pa"]),
        E2_pa=float(d["E2_pa"]),
        G12_pa=float(d["G12_pa"]),
        nu12=float(d["nu12"]),
        thickness_mm=float(d["thickness_mm"]),
        orientation_deg=float(d["orientation_deg"]),
        sigma_1_T_pa=float(d["sigma_1_T_pa"]),
        sigma_1_C_pa=float(d["sigma_1_C_pa"]),
        sigma_2_T_pa=float(d["sigma_2_T_pa"]),
        sigma_2_C_pa=float(d["sigma_2_C_pa"]),
        tau_12_pa=float(d["tau_12_pa"]),
    )


def _laminate_from_plies(plies_data: list) -> Laminate:
    return Laminate(plies=[_ply_from_dict(p) for p in plies_data])


def _safe_float(x) -> float:
    if math.isinf(x):
        return 1e308
    return float(x)


# ---------------------------------------------------------------------------
# Tool: composite_laminate_abd
# ---------------------------------------------------------------------------

_composite_laminate_abd_spec = ToolSpec(
    name="composite_laminate_abd",
    description=(
        "Compute the Classical Laminate Theory (CLT) ABD stiffness matrix "
        "for a composite laminate stack. Returns the 6×6 [A B; B D] matrix "
        "representing extensional (A), coupling (B), and bending (D) stiffnesses. "
        "CLT is valid for thin laminates (span/thickness > ~20). "
        "Reference: Jones (1999) Ch. 4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "items": _PLY_SCHEMA,
                "description": "Ply stack from bottom to top.",
            },
        },
        "required": ["plies"],
    },
)


@register(_composite_laminate_abd_spec, write=False)
async def run_composite_laminate_abd(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    try:
        laminate = _laminate_from_plies(a["plies"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"ply parameter error: {e}", "BAD_ARGS")

    try:
        ABD = laminate.compute_ABD_matrix()
    except Exception as e:
        return err_payload(f"ABD computation error: {e}", "SOLVER_ERROR")

    return ok_payload({
        "ok": True,
        "ABD_matrix": ABD.tolist(),
        "A_matrix": ABD[:3, :3].tolist(),
        "B_matrix": ABD[:3, 3:].tolist(),
        "D_matrix": ABD[3:, 3:].tolist(),
        "total_thickness_mm": laminate.total_thickness_mm,
        "n_plies": len(laminate.plies),
    })


# ---------------------------------------------------------------------------
# Tool: composite_laminate_analyze
# ---------------------------------------------------------------------------

_composite_laminate_analyze_spec = ToolSpec(
    name="composite_laminate_analyze",
    description=(
        "Perform Classical Laminate Theory (CLT) analysis: compute mid-plane "
        "strains, curvatures, and ply-by-ply stresses in the material frame "
        "under applied in-plane loads and bending moments. "
        "Reference: Jones (1999) Ch. 4; Reddy (2003) §3.3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "items": _PLY_SCHEMA,
                "description": "Ply stack from bottom to top.",
            },
            "in_plane_loads": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[N_x, N_y, N_xy] in-plane stress resultants [N/m].",
            },
            "bending_moments": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[M_x, M_y, M_xy] bending moments [N·m/m].",
            },
        },
        "required": ["plies", "in_plane_loads", "bending_moments"],
    },
)


@register(_composite_laminate_analyze_spec, write=False)
async def run_composite_laminate_analyze(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    try:
        laminate = _laminate_from_plies(a["plies"])
        Nv = np.asarray(a["in_plane_loads"], dtype=float)
        Mv = np.asarray(a["bending_moments"], dtype=float)
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"parameter error: {e}", "BAD_ARGS")

    try:
        resp = analyze_laminate(laminate, Nv, Mv)
    except Exception as e:
        return err_payload(f"CLT analysis error: {e}", "SOLVER_ERROR")

    return ok_payload({
        "ok": True,
        "midplane_strain":    resp.midplane_strain.tolist(),
        "curvature":          resp.curvature.tolist(),
        "ply_stresses_mat":   [s.tolist() for s in resp.ply_stresses],
        "ply_strains_global": [e.tolist() for e in resp.ply_strains_global],
    })


# ---------------------------------------------------------------------------
# Tool: composite_failure_criterion
# ---------------------------------------------------------------------------

_composite_failure_criterion_spec = ToolSpec(
    name="composite_failure_criterion",
    description=(
        "Apply a failure criterion to a single ply stress state. "
        "Criteria: tsai_wu, tsai_hill, maximum_stress, maximum_strain, puck, hashin. "
        "Returns failure index (FI < 1 safe, FI ≥ 1 failed), safety factor, and mode. "
        "References: Tsai & Wu (1971); Hashin (1980); Puck & Schürmann (1998)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "criterion": {
                "type": "string",
                "enum": ["tsai_wu", "tsai_hill", "maximum_stress", "maximum_strain",
                         "puck", "hashin"],
                "description": "Failure criterion to apply.",
            },
            "stress_material_frame": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[σ_1, σ_2, τ_12] ply stress in material frame [Pa]. "
                               "For maximum_strain, provide strain instead.",
            },
            "ply": _PLY_SCHEMA,
            "F12_interaction": {
                "type": "number",
                "description": "Tsai-Wu F_12 interaction term. Default 0.",
            },
        },
        "required": ["criterion", "stress_material_frame", "ply"],
    },
)


@register(_composite_failure_criterion_spec, write=False)
async def run_composite_failure_criterion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    try:
        criterion = a["criterion"]
        stress = np.asarray(a["stress_material_frame"], dtype=float)
        ply = _ply_from_dict(a["ply"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"parameter error: {e}", "BAD_ARGS")

    try:
        if criterion == "tsai_wu":
            f12 = float(a.get("F12_interaction", 0.0))
            result = tsai_wu(stress, ply, F12_interaction=f12)
        elif criterion == "tsai_hill":
            result = tsai_hill(stress, ply)
        elif criterion == "maximum_stress":
            result = maximum_stress(stress, ply)
        elif criterion == "maximum_strain":
            result = maximum_strain(stress, ply)  # stress array treated as strain here
        elif criterion == "puck":
            result = puck(stress, ply)
        elif criterion == "hashin":
            result = hashin(stress, ply)
        else:
            return err_payload(f"unknown criterion {criterion!r}", "BAD_ARGS")
    except Exception as e:
        return err_payload(f"failure criterion error: {e}", "SOLVER_ERROR")

    return ok_payload({
        "ok": True,
        "criterion":      result.criterion,
        "failure_index":  result.failure_index,
        "failed":         result.failed,
        "failed_mode":    result.failed_mode,
        "safety_factor":  _safe_float(result.safety_factor),
    })


# ---------------------------------------------------------------------------
# Tool: composite_first_ply_failure
# ---------------------------------------------------------------------------

_composite_first_ply_failure_spec = ToolSpec(
    name="composite_first_ply_failure",
    description=(
        "First-ply failure (FPF) analysis: find which ply in the laminate "
        "fails first under the applied loads, and the associated safety factor. "
        "Runs CLT analysis then applies the chosen failure criterion to each ply. "
        "References: Jones (1999) §4.5; Tsai & Wu (1971); Hashin (1980)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "items": _PLY_SCHEMA,
                "description": "Ply stack from bottom to top.",
            },
            "in_plane_loads": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[N_x, N_y, N_xy] [N/m].",
            },
            "bending_moments": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[M_x, M_y, M_xy] [N·m/m].",
            },
            "criterion": {
                "type": "string",
                "enum": ["tsai_wu", "tsai_hill", "maximum_stress", "hashin", "puck"],
                "description": "Failure criterion. Default 'tsai_wu'.",
            },
        },
        "required": ["plies", "in_plane_loads", "bending_moments"],
    },
)


@register(_composite_first_ply_failure_spec, write=False)
async def run_composite_first_ply_failure(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    try:
        laminate = _laminate_from_plies(a["plies"])
        Nv = np.asarray(a["in_plane_loads"], dtype=float)
        Mv = np.asarray(a["bending_moments"], dtype=float)
        criterion = a.get("criterion", "tsai_wu")
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"parameter error: {e}", "BAD_ARGS")

    try:
        response = analyze_laminate(laminate, Nv, Mv)
        fpf = first_ply_failure_analysis(laminate, response, criterion=criterion)
    except Exception as e:
        return err_payload(f"FPF analysis error: {e}", "SOLVER_ERROR")

    # Sanitise infinities for JSON serialisation
    fpf["safety_factor_to_first_ply_failure"] = _safe_float(
        fpf["safety_factor_to_first_ply_failure"]
    )
    for pr in fpf["ply_results"]:
        pr["safety_factor"] = _safe_float(pr["safety_factor"])

    return ok_payload({"ok": True, **fpf})
