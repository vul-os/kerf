"""
LLM-callable tool surface for the OpenFOAM bridge.

Registers two tools:

    cfd_openfoam_export  — generate an OpenFOAM case directory from Kerf
                           parameters (solver, turbulence model, BCs, mesh).
    cfd_openfoam_import  — parse an existing OpenFOAM case result directory
                           and return field summaries (U, p, k, ε).

Both tools operate purely as file I/O — no OpenFOAM install is required for
case generation or result import.  If OpenFOAM binaries are present the
caller can optionally trigger a solver run via the existing ``cfd_run`` tool.

Reference
---------
OpenFOAM v10 User Guide, ch. 2 — case structure;
White F.M., Fluid Mechanics, 8th ed., §6.4 (Hagen-Poiseuille oracle).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# 1. cfd_openfoam_export
# ---------------------------------------------------------------------------

_export_spec = ToolSpec(
    name="cfd_openfoam_export",
    description=(
        "Generate a complete OpenFOAM case directory from Kerf CFD parameters.  "
        "Writes system/{controlDict,fvSchemes,fvSolution,blockMeshDict}, "
        "constant/{transportProperties,turbulenceProperties,polyMesh/…}, "
        "and 0/{U,p,k,epsilon|omega,nut} with boundary conditions mapped from "
        "Kerf BC types (inlet/outlet/wall/symmetry).  "
        "Returns the path to the case root and a file manifest.  "
        "No OpenFOAM install required — pure file generation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "case_dir": {
                "type": "string",
                "description": (
                    "Absolute path to the destination case directory. "
                    "Created if absent.  Defaults to a system temp directory."
                ),
            },
            "solver": {
                "type": "string",
                "enum": ["simpleFoam", "pimpleFoam", "pisoFoam"],
                "description": (
                    "OpenFOAM solver application.  "
                    "'simpleFoam' for steady incompressible RANS; "
                    "'pimpleFoam'/'pisoFoam' for transient incompressible RANS."
                ),
            },
            "turbulence_model": {
                "type": "string",
                "enum": ["laminar", "kEpsilon", "kOmegaSST"],
                "description": (
                    "RANS turbulence model.  "
                    "'laminar' disables turbulence (no k/epsilon/omega fields); "
                    "'kEpsilon' writes k + epsilon fields; "
                    "'kOmegaSST' writes k + omega fields."
                ),
            },
            "nu": {
                "type": "number",
                "description": "Kinematic viscosity ν [m²/s].  Default 1e-5.",
            },
            "u_inlet": {
                "type": "number",
                "description": "Inlet velocity magnitude [m/s].  Default 1.0.",
            },
            "inlet_direction": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Inlet velocity unit direction vector [ux,uy,uz].  Default [1,0,0].",
            },
            "end_time": {
                "type": "number",
                "description": "End time / iteration count.  Default 500.",
            },
            "delta_t": {
                "type": "number",
                "description": "Time step (or iteration step for simpleFoam).  Default 1.0.",
            },
            "write_interval": {
                "type": "number",
                "description": "Result write interval (time steps).  Default 100.",
            },
            "k_inlet": {
                "type": "number",
                "description": "Turbulent kinetic energy k at inlet [m²/s²].  Default 0.001.",
            },
            "omega_inlet": {
                "type": "number",
                "description": "Specific dissipation rate ω at inlet [1/s].  Default 1.0.",
            },
            "epsilon_inlet": {
                "type": "number",
                "description": "Turbulent dissipation rate ε at inlet [m²/s³].  Default 0.001.",
            },
            "bcs": {
                "type": "object",
                "description": (
                    "Boundary condition mapping: patch name → Kerf BC type.  "
                    "BC types: 'inlet', 'outlet', 'wall', 'symmetry', 'empty'.  "
                    "Example: {\"inlet\": \"inlet\", \"outlet\": \"outlet\", \"walls\": \"wall\"}."
                ),
                "additionalProperties": {"type": "string"},
            },
            "geometry": {
                "type": "object",
                "description": (
                    "blockMeshDict geometry overrides for a simple box domain.  "
                    "Keys: x0,y0,z0 (origin), x1,y1,z1 (extent), nx,ny,nz (cell counts)."
                ),
            },
        },
        "required": [],
    },
)


def _export_sync(
    case_dir: str | None,
    solver: str,
    turbulence_model: str,
    nu: float,
    u_inlet: float,
    inlet_direction: list[float],
    end_time: float,
    delta_t: float,
    write_interval: float,
    k_inlet: float,
    omega_inlet: float,
    epsilon_inlet: float,
    bcs: dict[str, str] | None,
    geometry: dict[str, Any] | None,
) -> dict[str, Any]:
    from kerf_cfd.openfoam_bridge import write_case

    # Resolve destination
    _tmp_holder: list[Any] = []
    if case_dir:
        dest = Path(case_dir)
    else:
        tmp = tempfile.mkdtemp(prefix="kerf_of_")
        dest = Path(tmp)
        _tmp_holder.append(tmp)

    try:
        root = write_case(
            dest,
            mesh=None,
            bcs=bcs,
            solver_config={
                "solver": solver,
                "turbulence_model": turbulence_model,
                "nu": nu,
                "u_inlet": u_inlet,
                "inlet_direction": inlet_direction,
                "end_time": end_time,
                "delta_t": delta_t,
                "write_interval": write_interval,
                "k_inlet": k_inlet,
                "omega_inlet": omega_inlet,
                "epsilon_inlet": epsilon_inlet,
                "geometry": geometry or {},
            },
        )
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc), "code": "WRITE_ERROR"}

    # Collect manifest
    manifest: list[str] = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            manifest.append(str(f.relative_to(root)))

    return {
        "ok": True,
        "case_dir": str(root),
        "solver": solver,
        "turbulence_model": turbulence_model,
        "files": manifest,
        "n_files": len(manifest),
    }


@register(_export_spec, write=True)
async def cfd_openfoam_export(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

    solver = a.get("solver", "simpleFoam")
    turbulence_model = a.get("turbulence_model", "laminar")
    nu_raw = a.get("nu", 1e-5)
    u_inlet_raw = a.get("u_inlet", 1.0)
    end_time_raw = a.get("end_time", 500.0)
    delta_t_raw = a.get("delta_t", 1.0)
    write_interval_raw = a.get("write_interval", 100.0)
    k_inlet_raw = a.get("k_inlet", 0.001)
    omega_inlet_raw = a.get("omega_inlet", 1.0)
    epsilon_inlet_raw = a.get("epsilon_inlet", 0.001)
    inlet_direction = a.get("inlet_direction", [1.0, 0.0, 0.0])
    bcs = a.get("bcs")
    geometry = a.get("geometry")
    case_dir = a.get("case_dir")

    # Validate numerics
    try:
        nu = float(nu_raw)
        u_inlet = float(u_inlet_raw)
        end_time = float(end_time_raw)
        delta_t = float(delta_t_raw)
        write_interval = float(write_interval_raw)
        k_inlet = float(k_inlet_raw)
        omega_inlet = float(omega_inlet_raw)
        epsilon_inlet = float(epsilon_inlet_raw)
    except (TypeError, ValueError) as exc:
        return err_payload(f"numeric argument error: {exc}", "BAD_ARGS")

    for name, val in [("nu", nu), ("u_inlet", u_inlet), ("delta_t", delta_t)]:
        if not math.isfinite(val) or val <= 0:
            return err_payload(f"{name} must be a positive finite number", "BAD_ARGS")

    valid_solvers = {"simpleFoam", "pimpleFoam", "pisoFoam"}
    if solver not in valid_solvers:
        return err_payload(f"solver must be one of {sorted(valid_solvers)}", "BAD_ARGS")

    valid_turb = {"laminar", "kEpsilon", "kOmegaSST"}
    if turbulence_model not in valid_turb:
        return err_payload(f"turbulence_model must be one of {sorted(valid_turb)}", "BAD_ARGS")

    import asyncio
    result = await asyncio.to_thread(
        _export_sync,
        case_dir, solver, turbulence_model, nu, u_inlet, inlet_direction,
        end_time, delta_t, write_interval, k_inlet, omega_inlet, epsilon_inlet,
        bcs, geometry,
    )

    if not result.get("ok"):
        return err_payload(result.get("error", "unknown error"), result.get("code", "ERROR"))
    return ok_payload(result)


# ---------------------------------------------------------------------------
# 2. cfd_openfoam_import
# ---------------------------------------------------------------------------

_import_spec = ToolSpec(
    name="cfd_openfoam_import",
    description=(
        "Parse an OpenFOAM case result directory and return field summaries "
        "for the requested time step.  Reads ASCII internalField data for "
        "U, p, k, epsilon, omega, and nut.  "
        "Returns per-field statistics (min, max, mean) plus the number of cells.  "
        "No OpenFOAM install required — pure file parsing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "case_dir": {
                "type": "string",
                "description": "Absolute path to the OpenFOAM case directory.",
            },
            "time_step": {
                "type": "string",
                "description": (
                    "Time step to read.  Use 'latestTime' (default) for the "
                    "highest-numbered time directory, or supply a numeric string "
                    "like '0.5' or '100'."
                ),
            },
        },
        "required": ["case_dir"],
    },
)


def _arr_stats(arr: Any) -> dict[str, float] | None:
    if arr is None:
        return None
    try:
        import numpy as np_  # type: ignore
        a = np_.asarray(arr, dtype=float)
        if a.ndim == 2:
            mags = np_.linalg.norm(a, axis=1)
            return {
                "min_magnitude": float(mags.min()),
                "max_magnitude": float(mags.max()),
                "mean_magnitude": float(mags.mean()),
                "n": int(a.shape[0]),
            }
        return {
            "min": float(a.min()),
            "max": float(a.max()),
            "mean": float(a.mean()),
            "n": int(a.size),
        }
    except ImportError:
        pass
    # Fallback without numpy
    flat: list[float] = []
    if isinstance(arr, list):
        for item in arr:
            if isinstance(item, (int, float)):
                flat.append(float(item))
            elif hasattr(item, "__iter__"):
                mags_item = math.sqrt(sum(x * x for x in item))
                flat.append(mags_item)
    if not flat:
        return None
    return {
        "min": min(flat),
        "max": max(flat),
        "mean": sum(flat) / len(flat),
        "n": len(flat),
    }


def _import_sync(case_dir: str, time_step: str) -> dict[str, Any]:
    from kerf_cfd.openfoam_bridge import read_results

    try:
        bundle = read_results(case_dir, time_step=time_step)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "code": "NOT_FOUND"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "PARSE_ERROR"}

    fields: dict[str, Any] = {}
    for fname in ("U", "p", "k", "epsilon", "omega", "nut"):
        arr = getattr(bundle, fname)
        if arr is not None:
            fields[fname] = _arr_stats(arr)

    return {
        "ok": True,
        "case_dir": str(Path(case_dir).resolve()),
        "time_value": bundle.time_value,
        "n_cells": bundle.n_cells,
        "fields": fields,
    }


@register(_import_spec)
async def cfd_openfoam_import(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

    case_dir = a.get("case_dir", "")
    if not case_dir:
        return err_payload("case_dir is required", "BAD_ARGS")

    time_step = a.get("time_step", "latestTime")

    import asyncio
    result = await asyncio.to_thread(_import_sync, case_dir, time_step)

    if not result.get("ok"):
        return err_payload(result.get("error", "unknown error"), result.get("code", "ERROR"))
    return ok_payload(result)
