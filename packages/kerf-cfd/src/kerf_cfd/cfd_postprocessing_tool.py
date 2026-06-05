"""
CFD post-processing LLM tool — probe sampling, residual extraction,
field statistics, and y⁺ / wall-function diagnostics.

Registers three LLM tools:

    cfd_postprocess_results  — field stats, probe samples, wall y⁺,
                               residuals from an OpenFOAM case directory
    cfd_extract_residuals    — extract convergence residuals from
                               OpenFOAM log (simpleFoam / pimpleFoam)
    cfd_probe_field          — sample scalar/vector fields at N points
                               and return per-probe values + statistics

All tools are pure Python (no OpenFOAM install required).

References
----------
OpenFOAM v10 User Guide §6.2 — postProcessing function objects.
Launder B.E., Spalding D.B. (1974) §3 — wall functions, y⁺.
White F.M. (2011) "Fluid Mechanics" 7th ed. §6.4 — wall units.

# Wave parity: close openfoam.postprocessing partial gap
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field_stats(arr: np.ndarray, is_vector: bool = False) -> dict:
    """Return min/max/mean/rms statistics for a field array."""
    if arr is None or arr.size == 0:
        return {}
    if is_vector and arr.ndim == 2:
        mags = np.linalg.norm(arr, axis=1)
        return {
            "min_mag": float(mags.min()),
            "max_mag": float(mags.max()),
            "mean_mag": float(mags.mean()),
            "rms_mag": float(np.sqrt(np.mean(mags ** 2))),
            "n_cells": int(mags.size),
        }
    a = arr.ravel()
    return {
        "min": float(a.min()),
        "max": float(a.max()),
        "mean": float(a.mean()),
        "rms": float(np.sqrt(np.mean(a ** 2))),
        "n_cells": int(a.size),
    }


def _yplus_estimate(
    U_ref: float,
    L_ref: float,
    nu: float,
    *,
    target_yplus: float = 30.0,
) -> dict:
    """
    Estimate first-cell wall distance Δy for a target y⁺.

    y⁺ = u_τ · Δy / ν,  u_τ ≈ U_ref · √(C_f / 2)

    where C_f is estimated from the Schlichting flat-plate correlation:
      C_f ≈ 0.058 · Re_L^(-0.2)   (turbulent flat plate, Re > 5×10⁵)

    Parameters
    ----------
    U_ref        : reference velocity [m/s]
    L_ref        : reference length [m]
    nu           : kinematic viscosity [m²/s]
    target_yplus : desired y⁺ (default 30 for log-law wall functions)

    References
    ----------
    White (2011) §7.4 — friction coefficient, turbulent flat plate.
    Launder & Spalding (1974) §3 — log-law wall function y⁺.
    """
    Re_L = U_ref * L_ref / nu
    if Re_L < 1.0:
        return {"error": "Re_L < 1 — not turbulent"}
    # Schlichting (1979) turbulent flat-plate skin friction
    Cf = 0.058 * Re_L ** (-0.2)
    u_tau = U_ref * math.sqrt(Cf / 2.0)
    if u_tau < 1e-12:
        return {"error": "u_tau ≈ 0 — check inputs"}
    delta_y = target_yplus * nu / u_tau
    return {
        "Re_L": Re_L,
        "Cf_schlichting": Cf,
        "u_tau_m_s": u_tau,
        "target_yplus": target_yplus,
        "first_cell_height_m": delta_y,
        "note": (
            "Schlichting turbulent flat-plate Cf correlation. "
            "White (2011) §7.4. Adjust for geometry."
        ),
    }


def _parse_of_log_residuals(log_text: str) -> list[dict]:
    """
    Parse OpenFOAM simpleFoam / pimpleFoam log for per-iteration residuals.

    Matches lines like:
      smoothSolver:  Solving for Ux, Initial residual = 0.01234, ...
      GAMG:          Solving for p,  Initial residual = 0.00567, ...

    Returns list of dicts: {iteration, field, initial_residual, final_residual}
    """
    # Pattern for GAMG / smoothSolver / PCG residual lines
    pattern = re.compile(
        r"(?:GAMG|smoothSolver|PCG|PBiCGStab|BiCGStab)\s*:\s*"
        r"Solving for (\w+),\s*"
        r"Initial residual = ([0-9.eE+\-]+),\s*"
        r"Final residual = ([0-9.eE+\-]+)",
    )
    iter_pattern = re.compile(r"^Time\s*=\s*([\d.eE+\-]+)", re.MULTILINE)

    results: list[dict] = []
    current_iter: float | None = None

    for line in log_text.splitlines():
        tm = iter_pattern.match(line)
        if tm:
            current_iter = float(tm.group(1))
            continue
        m = pattern.search(line)
        if m:
            results.append({
                "time": current_iter,
                "field": m.group(1),
                "initial_residual": float(m.group(2)),
                "final_residual": float(m.group(3)),
            })

    return results


# ---------------------------------------------------------------------------
# Tool 1: cfd_postprocess_results
# ---------------------------------------------------------------------------

_postprocess_spec = ToolSpec(
    name="cfd_postprocess_results",
    description=(
        "Post-process an OpenFOAM case directory: compute field statistics "
        "(U, p, k, ε, ω), estimate wall y⁺ from flow conditions, "
        "and parse postProcessing/ function-object data.\n"
        "Returns:\n"
        "  • field_stats   — min/max/mean/rms per field at the given time step\n"
        "  • yplus_estimate — first-cell Δy for target y⁺ (Launder-Spalding 1974)\n"
        "  • postprocessing_summary — function-object names and row counts\n"
        "No OpenFOAM install required — pure file parsing.\n"
        "Reference: OpenFOAM v10 User Guide §6.2; White (2011) §7.4."
    ),
    input_schema={
        "type": "object",
        "required": ["case_dir"],
        "properties": {
            "case_dir": {
                "type": "string",
                "description": "Absolute path to the OpenFOAM case directory.",
            },
            "time_step": {
                "type": "string",
                "description": "Time step to read. 'latestTime' (default) or numeric string.",
                "default": "latestTime",
            },
            "U_ref": {
                "type": "number",
                "description": "Reference velocity [m/s] for y⁺ estimation.",
            },
            "L_ref": {
                "type": "number",
                "description": "Reference length [m] for y⁺ estimation.",
            },
            "nu": {
                "type": "number",
                "description": "Kinematic viscosity [m²/s] for y⁺ estimation.",
            },
            "target_yplus": {
                "type": "number",
                "description": "Target y⁺ for first-cell spacing (default 30).",
                "default": 30.0,
            },
        },
    },
)


def _postprocess_sync(a: dict) -> dict:
    from kerf_cfd.openfoam_bridge import read_results, parse_postprocessing

    case_dir = a.get("case_dir", "")
    time_step = a.get("time_step", "latestTime")

    # Field stats
    field_stats: dict = {}
    time_value: Any = None
    n_cells: int = 0
    try:
        bundle = read_results(case_dir, time_step=time_step)
        time_value = bundle.time_value
        n_cells = bundle.n_cells
        for fname, is_vec in [("U", True), ("p", False), ("k", False),
                               ("epsilon", False), ("omega", False), ("nut", False)]:
            arr = getattr(bundle, fname)
            if arr is not None:
                field_stats[fname] = _field_stats(np.asarray(arr), is_vector=is_vec)
    except (FileNotFoundError, ValueError) as exc:
        field_stats["_error"] = str(exc)

    # y⁺ estimate
    yplus: dict = {}
    U_ref = a.get("U_ref")
    L_ref = a.get("L_ref")
    nu = a.get("nu")
    if U_ref and L_ref and nu:
        yplus = _yplus_estimate(
            float(U_ref), float(L_ref), float(nu),
            target_yplus=float(a.get("target_yplus", 30.0)),
        )

    # postProcessing summary
    pp = parse_postprocessing(case_dir)
    pp_summary = {
        "status": pp.get("status"),
        "function_names": pp.get("function_names", []),
        "total_data_rows": sum(
            len(v) for v in pp.get("data", {}).values()
        ),
    }

    return {
        "ok": True,
        "case_dir": case_dir,
        "time_value": time_value,
        "n_cells": n_cells,
        "field_stats": field_stats,
        "yplus_estimate": yplus,
        "postprocessing_summary": pp_summary,
    }


@register(_postprocess_spec)
async def cfd_postprocess_results(ctx: ProjectCtx, args: bytes) -> str:
    import asyncio
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    if not a.get("case_dir"):
        return err_payload("case_dir is required", "BAD_ARGS")
    result = await asyncio.to_thread(_postprocess_sync, a)
    if not result.get("ok"):
        return err_payload(result.get("error", "unknown"), result.get("code", "ERROR"))
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool 2: cfd_extract_residuals
# ---------------------------------------------------------------------------

_residuals_spec = ToolSpec(
    name="cfd_extract_residuals",
    description=(
        "Extract solver convergence residuals from an OpenFOAM log file "
        "(simpleFoam, pimpleFoam, pisoFoam, rhoSimpleFoam).\n"
        "Returns per-field residual timeseries and convergence assessment.\n"
        "Matches 'Initial residual = ...' lines for Ux/Uy/Uz/p/k/epsilon/omega.\n"
        "Convergence criterion: all final residuals < tol (default 1e-4).\n"
        "Reference: OpenFOAM simpleFoam solver log format."
    ),
    input_schema={
        "type": "object",
        "required": ["log_text"],
        "properties": {
            "log_text": {
                "type": "string",
                "description": "Full text of the OpenFOAM solver log file.",
            },
            "convergence_tol": {
                "type": "number",
                "description": "Residual tolerance for convergence check (default 1e-4).",
                "default": 1e-4,
            },
        },
    },
)


def _extract_residuals_sync(log_text: str, tol: float = 1e-4) -> dict:
    rows = _parse_of_log_residuals(log_text)
    if not rows:
        return {
            "ok": True,
            "n_iterations": 0,
            "fields_found": [],
            "convergence_table": {},
            "converged": False,
            "note": "No residual lines found — check log format.",
        }

    # Group by field — track (initial_residual, final_residual) pairs
    from collections import defaultdict
    by_field_initial: dict[str, list[float]] = defaultdict(list)
    by_field_final: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_field_initial[r["field"]].append(r["initial_residual"])
        by_field_final[r["field"]].append(r["final_residual"])

    # Last 5 iterations per field — use final_residual for convergence check
    convergence_table: dict = {}
    all_converged = True
    for field in by_field_initial:
        initials = by_field_initial[field]
        finals = by_field_final[field]
        last_5_final = finals[-5:]
        final = finals[-1]
        conv = final < tol
        if not conv:
            all_converged = False
        convergence_table[field] = {
            "initial": initials[0],
            "final": final,
            "last_5": last_5_final,
            "converged": conv,
        }

    return {
        "ok": True,
        "n_iterations": len(rows),
        "fields_found": sorted(by_field_initial.keys()),
        "convergence_table": convergence_table,
        "converged": all_converged,
        "tolerance": tol,
    }


@register(_residuals_spec)
async def cfd_extract_residuals(ctx: ProjectCtx, args: bytes) -> str:
    import asyncio
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    log_text = a.get("log_text")
    if log_text is None:
        return err_payload("log_text is required", "BAD_ARGS")
    log_text = str(log_text)
    tol = float(a.get("convergence_tol", 1e-4))
    result = await asyncio.to_thread(_extract_residuals_sync, log_text, tol)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool 3: cfd_probe_field
# ---------------------------------------------------------------------------

_probe_spec = ToolSpec(
    name="cfd_probe_field",
    description=(
        "Sample scalar/vector field values at N probe points using nearest-cell lookup "
        "from an OpenFOAM case result directory.\n"
        "Returns per-probe values for U, p, k, T (if present) and "
        "global field statistics (min/max/mean).\n"
        "Equivalent to OpenFOAM 'probes' function object.\n"
        "Reference: OpenFOAM v10 §6.2.3 probes function object;\n"
        "           White (2011) §6.4 pressure coefficient Cp = (p-p∞)/(½ρV²).\n"
        "No OpenFOAM install required."
    ),
    input_schema={
        "type": "object",
        "required": ["case_dir", "probe_points"],
        "properties": {
            "case_dir": {
                "type": "string",
                "description": "Absolute path to the OpenFOAM case directory.",
            },
            "probe_points": {
                "type": "array",
                "description": "Probe locations [[x,y,z], ...] in metres.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 3,
                },
                "minItems": 1,
                "maxItems": 200,
            },
            "time_step": {
                "type": "string",
                "description": "Time step ('latestTime' default).",
                "default": "latestTime",
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Fields to probe. Default: ['U','p','k'].",
                "default": ["U", "p", "k"],
            },
            "cell_centres_xyz": {
                "type": "array",
                "description": (
                    "Optional list of cell-centre coordinates [[x,y,z], ...] "
                    "for nearest-cell interpolation.  If omitted, probes return "
                    "global field stats only."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
        },
    },
)


def _probe_sync(a: dict) -> dict:
    from kerf_cfd.openfoam_bridge import read_results

    case_dir = a["case_dir"]
    probe_points = [np.array(pt, dtype=float) for pt in a["probe_points"]]
    time_step = a.get("time_step", "latestTime")
    fields_req = a.get("fields", ["U", "p", "k"])

    try:
        bundle = read_results(case_dir, time_step=time_step)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "NOT_FOUND"}

    field_map = {
        "U": bundle.U,
        "p": bundle.p,
        "k": bundle.k,
        "epsilon": bundle.epsilon,
        "omega": bundle.omega,
        "nut": bundle.nut,
    }

    # Global stats
    global_stats: dict = {}
    for fname in fields_req:
        arr = field_map.get(fname)
        if arr is not None:
            is_vec = fname == "U"
            global_stats[fname] = _field_stats(np.asarray(arr), is_vector=is_vec)

    # Nearest-cell probe lookup
    cell_centres_raw = a.get("cell_centres_xyz")
    probe_results: list[dict] = []

    if cell_centres_raw and bundle.n_cells > 0:
        centres = np.array(cell_centres_raw, dtype=float)
        # Ensure 3-D
        if centres.ndim == 1:
            centres = centres[np.newaxis, :]
        if centres.shape[1] == 2:
            centres = np.hstack([centres, np.zeros((len(centres), 1))])

        for i, pt in enumerate(probe_points):
            pt3 = np.zeros(3)
            pt3[:len(pt)] = pt
            # Nearest cell by Euclidean distance
            dists = np.linalg.norm(centres - pt3, axis=1)
            ci = int(np.argmin(dists))
            probe_dict: dict = {
                "probe_id": i,
                "x": float(pt3[0]),
                "y": float(pt3[1]),
                "z": float(pt3[2]),
                "nearest_cell_idx": ci,
                "distance_m": float(dists[ci]),
            }
            for fname in fields_req:
                arr = field_map.get(fname)
                if arr is None:
                    continue
                arr_np = np.asarray(arr)
                if arr_np.ndim == 2 and ci < len(arr_np):
                    v = arr_np[ci]
                    probe_dict[fname] = v.tolist()
                    probe_dict[f"{fname}_mag"] = float(np.linalg.norm(v))
                elif arr_np.ndim == 1 and ci < len(arr_np):
                    probe_dict[fname] = float(arr_np[ci])
            probe_results.append(probe_dict)
    else:
        # Return probe stubs with global field refs
        for i, pt in enumerate(probe_points):
            pt3 = np.zeros(3)
            pt3[:len(pt)] = pt
            probe_results.append({
                "probe_id": i,
                "x": float(pt3[0]), "y": float(pt3[1]), "z": float(pt3[2]),
                "note": "cell_centres_xyz not provided — global stats only",
            })

    return {
        "ok": True,
        "case_dir": case_dir,
        "time_value": bundle.time_value,
        "n_cells": bundle.n_cells,
        "global_stats": global_stats,
        "probes": probe_results,
        "n_probes": len(probe_results),
    }


@register(_probe_spec)
async def cfd_probe_field(ctx: ProjectCtx, args: bytes) -> str:
    import asyncio
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    if not a.get("case_dir"):
        return err_payload("case_dir is required", "BAD_ARGS")
    if not a.get("probe_points"):
        return err_payload("probe_points is required", "BAD_ARGS")
    result = await asyncio.to_thread(_probe_sync, a)
    if not result.get("ok"):
        return err_payload(result.get("error", "unknown"), result.get("code", "ERROR"))
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool 4: cfd_flow_setup
# ---------------------------------------------------------------------------

_flow_setup_spec = ToolSpec(
    name="cfd_flow_setup",
    description=(
        "Configure a CFD case for internal or external flow.\n"
        "Returns recommended solver, turbulence model, boundary conditions, "
        "mesh resolution guidelines, and y⁺ requirements.\n"
        "Internal flow: pipe/duct/channel — fixedValue inlet, zeroGradient outlet.\n"
        "External flow: bluff body/aerofoil — freestream farfield BCs, "
        "pressureInletOutletVelocity at outlet.\n\n"
        "References:\n"
        "  OpenFOAM v10 Tutorial Guide §2 (pitzDaily, motorBike).\n"
        "  White (2011) §8 (internal), §9 (external).\n"
        "  Menter (1994) k-ω SST — recommended for external flows.\n"
        "  Launder & Spalding (1974) k-ε — recommended for internal flows."
    ),
    input_schema={
        "type": "object",
        "required": ["flow_type"],
        "properties": {
            "flow_type": {
                "type": "string",
                "enum": ["internal", "external"],
                "description": "internal = enclosed duct/pipe/channel; external = body in open stream.",
            },
            "Re": {
                "type": "number",
                "description": "Characteristic Reynolds number.",
            },
            "U_ref": {
                "type": "number",
                "description": "Reference velocity magnitude [m/s].",
            },
            "L_ref": {
                "type": "number",
                "description": "Reference length (hydraulic diameter or chord) [m].",
            },
            "nu": {
                "type": "number",
                "description": "Kinematic viscosity [m²/s]. Default 1.5e-5 (air at 25°C).",
            },
            "requires_heat_transfer": {
                "type": "boolean",
                "description": "Include thermal BCs (buoyantSimpleFoam).",
                "default": False,
            },
            "mach_number": {
                "type": "number",
                "description": "Approximate Mach number. If > 0.3 compressible solver recommended.",
            },
        },
    },
)


def _flow_setup_sync(a: dict) -> dict:
    flow_type = a.get("flow_type", "internal")
    Re = a.get("Re")
    U_ref = a.get("U_ref")
    L_ref = a.get("L_ref")
    nu = float(a.get("nu", 1.5e-5))
    heat = bool(a.get("requires_heat_transfer", False))
    Ma = a.get("mach_number")

    # Derive Re if not given
    if Re is None and U_ref and L_ref:
        Re = float(U_ref) * float(L_ref) / nu

    # Solver selection
    if Ma is not None and float(Ma) > 0.3:
        solver = "rhoSimpleFoam"
        notes = ["Mach > 0.3 → compressible solver (rhoSimpleFoam). "
                 "Set rhoCentralFoam for M > 0.7."]
    elif heat:
        solver = "buoyantSimpleFoam"
        notes = ["Conjugate heat transfer → buoyantSimpleFoam."]
    else:
        solver = "simpleFoam"
        notes = []

    # Turbulence model
    if Re is None:
        turb_model = "kOmegaSST"
        turb_reason = "Re unknown — k-ω SST is the safest default."
    elif Re < 2300:
        turb_model = "laminar"
        turb_reason = f"Re={Re:.0f} < 2300 — laminar flow, no turbulence model needed."
    elif flow_type == "external":
        turb_model = "kOmegaSST"
        turb_reason = (
            f"External flow at Re={Re:.2e}: k-ω SST (Menter 1994) recommended — "
            "handles boundary-layer separation and adverse pressure gradients well."
        )
    else:
        # Internal
        if Re >= 1e5:
            turb_model = "kEpsilon"
            turb_reason = (
                f"Internal flow at Re={Re:.2e}: k-ε (Launder-Spalding 1974) "
                "is standard for fully turbulent pipe/duct flows."
            )
        else:
            turb_model = "kOmegaSST"
            turb_reason = (
                f"Internal flow at Re={Re:.2e}: k-ω SST recommended for "
                "transitional-turbulent flows (2300 ≤ Re < 1e5)."
            )

    # Boundary conditions
    if flow_type == "internal":
        bcs = {
            "inlet": {
                "U": "fixedValue (specify u_inlet vector)",
                "p": "zeroGradient",
                "k": "fixedValue (k = 1.5·(I·U_ref)²; I ≈ 0.05)",
                "epsilon_omega": "fixedValue (from turbulence intensity + mixing length)",
            },
            "outlet": {
                "U": "zeroGradient",
                "p": "fixedValue p=0 (gauge)",
                "k": "zeroGradient",
                "epsilon_omega": "zeroGradient",
            },
            "walls": {
                "U": "noSlip",
                "p": "zeroGradient",
                "k": "kqRWallFunction (y+ > 30) or lowReWallFunction (y+ < 5)",
                "epsilon_omega": "epsilonWallFunction / omegaWallFunction",
            },
        }
    else:
        # External
        bcs = {
            "inlet_farfield": {
                "U": "freestream (fixedValue with U_inf vector)",
                "p": "freestreamPressure (p=p_inf)",
                "k": "fixedValue (k = 1.5·(I·U_inf)²; I ≈ 0.001 for freestream)",
                "epsilon_omega": "fixedValue (from turbulence length scale ~ 0.01·L_ref)",
            },
            "outlet_farfield": {
                "U": "inletOutlet (pressureInletOutletVelocity)",
                "p": "freestreamPressure",
                "k": "zeroGradient",
                "epsilon_omega": "zeroGradient",
            },
            "body_surface": {
                "U": "noSlip",
                "p": "zeroGradient",
                "k": "kqRWallFunction",
                "epsilon_omega": "epsilonWallFunction / omegaWallFunction",
            },
            "symmetry_planes": {
                "all_fields": "symmetry (slip wall)",
            },
        }

    # Mesh guidelines
    if turb_model != "laminar":
        yplus_note = "y⁺ ≈ 30–300 for wall functions; y⁺ < 5 for low-Re approach."
    else:
        yplus_note = "Laminar — resolve viscous sublayer, y⁺ < 1 at walls."

    yplus_data: dict = {}
    if U_ref and L_ref:
        yplus_data = _yplus_estimate(float(U_ref), float(L_ref), nu, target_yplus=30.0)

    # Turbulence IC estimates
    turb_ics: dict = {}
    if Re is not None and U_ref is not None and Re >= 2300:
        I = 0.05 if flow_type == "internal" else 0.001
        k_est = 1.5 * (I * float(U_ref)) ** 2
        L_mix = 0.07 * float(L_ref) if L_ref else 0.01
        Cmu = 0.09
        eps_est = Cmu ** 0.75 * k_est ** 1.5 / L_mix
        omega_est = Cmu ** (-0.25) * k_est ** 0.5 / L_mix
        turb_ics = {
            "turbulence_intensity_I": I,
            "k_inlet_m2_s2": k_est,
            "epsilon_inlet_m2_s3": eps_est,
            "omega_inlet_1_s": omega_est,
            "mixing_length_m": L_mix,
            "note": "IC from Launder-Spalding (1974) §4 + Menter (1994) §2.",
        }

    return {
        "ok": True,
        "flow_type": flow_type,
        "Re": Re,
        "solver": solver,
        "turbulence_model": turb_model,
        "turbulence_model_rationale": turb_reason,
        "boundary_conditions": bcs,
        "turbulence_initial_conditions": turb_ics,
        "yplus_guideline": yplus_note,
        "yplus_estimate": yplus_data,
        "notes": notes,
        "references": [
            "OpenFOAM v10 Tutorial Guide §2",
            "White (2011) §8–9",
            "Menter (1994) AIAA J. 32(8) — k-ω SST",
            "Launder & Spalding (1974) — k-ε",
        ],
    }


@register(_flow_setup_spec)
async def cfd_flow_setup(ctx: ProjectCtx, args: bytes) -> str:
    import asyncio
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    flow_type = a.get("flow_type", "")
    if flow_type not in ("internal", "external"):
        return err_payload("flow_type must be 'internal' or 'external'", "BAD_ARGS")
    result = await asyncio.to_thread(_flow_setup_sync, a)
    if not result.get("ok"):
        return err_payload(result.get("error", "unknown"), result.get("code", "ERROR"))
    return ok_payload(result)
