"""
kerf_mates.mbd.mbd_tools — LLM tool wrappers for Wave 9C MBD modules.

Registers four LLM tools:
  craig_bampton_reduce_tool   — modal reduction of FE matrices
  step_vehicle_tool           — one-step vehicle dynamics
  steady_state_cornering_tool — vehicle steady-state cornering analysis
  gear_mesh_force_tool        — gear-pair mesh force
  belt_drive_force_tool       — belt-drive tension calculation

All tools are registered via ctx.tools.register() in plugin.py.
Never raises — all failures returned as {"ok": False, "reason": ...}.

Wave 9C: Adams flex-body + vehicle + machinery MBD.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mates._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

import numpy as np

from kerf_mates.mbd.flexible_body import (
    FlexBody, craig_bampton_reduce, step_flex_body, make_flex_body_state,
)
from kerf_mates.mbd.vehicle_dynamics import (
    TireModel, SuspensionLink, VehicleSpec,
    step_vehicle, steady_state_cornering,
)
from kerf_mates.mbd.machinery import (
    GearMeshDynamics, BeltDrive,
    gear_mesh_force, belt_drive_force,
)


# ---------------------------------------------------------------------------
# craig_bampton_reduce_tool
# ---------------------------------------------------------------------------

craig_bampton_reduce_spec = ToolSpec(
    name="craig_bampton_reduce",
    description=(
        "Craig-Bampton (1968) modal reduction of a finite-element model. "
        "Accepts K and M as flat lists (row-major), returns reduced K_red and M_red "
        "and the transformation matrix T_CB.  n_dof_reduced = len(interface_dof) + n_internal_modes."
    ),
    input_schema={
        "type": "object",
        "required": ["K_full", "M_full", "n_dof", "interface_dof", "n_internal_modes"],
        "properties": {
            "K_full": {"type": "array", "description": "Row-major flat list of N×N stiffness matrix entries."},
            "M_full": {"type": "array", "description": "Row-major flat list of N×N mass matrix entries."},
            "n_dof": {"type": "integer", "description": "N — matrix dimension."},
            "interface_dof": {"type": "array", "items": {"type": "integer"},
                              "description": "0-based indices of interface (boundary) DOFs."},
            "n_internal_modes": {"type": "integer", "description": "Number of fixed-interface normal modes to keep."},
        },
    },
)


async def run_craig_bampton_reduce(params: dict, ctx: ProjectCtx) -> str:
    try:
        N = int(params["n_dof"])
        K = np.array(params["K_full"], dtype=float).reshape(N, N)
        M = np.array(params["M_full"], dtype=float).reshape(N, N)
        interface_dof = [int(d) for d in params["interface_dof"]]
        n_modes = int(params["n_internal_modes"])

        T_CB, K_red, M_red = craig_bampton_reduce(K, M, interface_dof, n_modes)

        n_red = K_red.shape[0]
        return ok_payload({
            "ok": True,
            "n_dof_original": N,
            "n_dof_reduced": n_red,
            "n_interface": len(interface_dof),
            "n_internal_modes": n_modes,
            "K_red_shape": list(K_red.shape),
            "M_red_shape": list(M_red.shape),
            "T_CB_shape": list(T_CB.shape),
            # Return matrices as nested lists for JSON
            "K_red": K_red.tolist(),
            "M_red": M_red.tolist(),
            "T_CB": T_CB.tolist(),
        })
    except Exception as exc:
        return err_payload(f"craig_bampton_reduce failed: {exc}", "MBD_ERROR")


# ---------------------------------------------------------------------------
# step_vehicle_tool
# ---------------------------------------------------------------------------

step_vehicle_spec = ToolSpec(
    name="step_vehicle_dynamics",
    description=(
        "Advance the single-track (bicycle) vehicle model by one time step. "
        "Uses Pacejka Magic Formula tires and weight-transfer.  "
        "Returns updated state with position, velocity, slip angles, tyre forces."
    ),
    input_schema={
        "type": "object",
        "required": ["mass_kg", "wheelbase_m", "dt"],
        "properties": {
            "mass_kg": {"type": "number"},
            "wheelbase_m": {"type": "number"},
            "cg_height_m": {"type": "number", "default": 0.55},
            "cg_front_ratio": {"type": "number", "default": 0.45},
            "steering_deg": {"type": "number", "default": 0.0,
                             "description": "Front wheel steer angle [degrees]."},
            "throttle": {"type": "number", "default": 0.0},
            "brake": {"type": "number", "default": 0.0},
            "dt": {"type": "number"},
            "initial_speed_m_s": {"type": "number", "default": 10.0},
            "drive": {"type": "string", "default": "rear"},
        },
    },
)


async def run_step_vehicle(params: dict, ctx: ProjectCtx) -> str:
    try:
        import math as _math
        spec = VehicleSpec(
            mass_kg=float(params["mass_kg"]),
            wheelbase_m=float(params["wheelbase_m"]),
            cg_height_m=float(params.get("cg_height_m", 0.55)),
            cg_front_ratio=float(params.get("cg_front_ratio", 0.45)),
            drive=str(params.get("drive", "rear")),
        )
        state = {"vx": float(params.get("initial_speed_m_s", 10.0))}
        result = step_vehicle(
            state=state,
            spec=spec,
            steering_rad=_math.radians(float(params.get("steering_deg", 0.0))),
            throttle=float(params.get("throttle", 0.0)),
            brake=float(params.get("brake", 0.0)),
            dt=float(params["dt"]),
        )
        result["ok"] = True
        return ok_payload(result)
    except Exception as exc:
        return err_payload(f"step_vehicle failed: {exc}", "MBD_ERROR")


# ---------------------------------------------------------------------------
# steady_state_cornering_tool
# ---------------------------------------------------------------------------

steady_state_cornering_spec = ToolSpec(
    name="steady_state_cornering",
    description=(
        "Compute steady-state cornering steering angle, slip angles, and lateral g "
        "for a vehicle at given speed and corner radius.  "
        "Uses Pacejka linear cornering stiffness model."
    ),
    input_schema={
        "type": "object",
        "required": ["mass_kg", "wheelbase_m", "speed_m_s", "radius_m"],
        "properties": {
            "mass_kg": {"type": "number"},
            "wheelbase_m": {"type": "number"},
            "cg_height_m": {"type": "number", "default": 0.55},
            "cg_front_ratio": {"type": "number", "default": 0.45},
            "speed_m_s": {"type": "number"},
            "radius_m": {"type": "number"},
        },
    },
)


async def run_steady_state_cornering(params: dict, ctx: ProjectCtx) -> str:
    try:
        spec = VehicleSpec(
            mass_kg=float(params["mass_kg"]),
            wheelbase_m=float(params["wheelbase_m"]),
            cg_height_m=float(params.get("cg_height_m", 0.55)),
            cg_front_ratio=float(params.get("cg_front_ratio", 0.45)),
        )
        result = steady_state_cornering(
            spec=spec,
            speed_m_s=float(params["speed_m_s"]),
            radius_m=float(params["radius_m"]),
        )
        return ok_payload(result)
    except Exception as exc:
        return err_payload(f"steady_state_cornering failed: {exc}", "MBD_ERROR")


# ---------------------------------------------------------------------------
# gear_mesh_force_tool
# ---------------------------------------------------------------------------

gear_mesh_force_spec = ToolSpec(
    name="gear_mesh_force",
    description=(
        "Compute tangential and normal tooth-contact force for a spur-gear pair. "
        "Uses Litvin (2004) mesh-stiffness model with backlash dead-band. "
        "Returns (F_tangential_N, F_normal_N) per ISO 6336-1:2019 §6."
    ),
    input_schema={
        "type": "object",
        "required": ["pinion_teeth", "gear_teeth", "module_mm", "mesh_stiffness_n_per_m",
                     "omega_pinion_rad_s", "omega_gear_rad_s", "dt"],
        "properties": {
            "pinion_teeth": {"type": "integer"},
            "gear_teeth": {"type": "integer"},
            "module_mm": {"type": "number"},
            "mesh_stiffness_n_per_m": {"type": "number"},
            "backlash_mm": {"type": "number", "default": 0.05},
            "omega_pinion_rad_s": {"type": "number"},
            "omega_gear_rad_s": {"type": "number"},
            "dt": {"type": "number"},
        },
    },
)


async def run_gear_mesh_force(params: dict, ctx: ProjectCtx) -> str:
    try:
        mesh = GearMeshDynamics(
            pinion_teeth=int(params["pinion_teeth"]),
            gear_teeth=int(params["gear_teeth"]),
            module_mm=float(params["module_mm"]),
            mesh_stiffness_n_per_m=float(params["mesh_stiffness_n_per_m"]),
            backlash_mm=float(params.get("backlash_mm", 0.05)),
        )
        F_t, F_n = gear_mesh_force(
            omega_p_rad_s=float(params["omega_pinion_rad_s"]),
            omega_g_rad_s=float(params["omega_gear_rad_s"]),
            mesh=mesh,
            dt=float(params["dt"]),
        )
        return ok_payload({
            "ok": True,
            "F_tangential_n": F_t,
            "F_normal_n": F_n,
            "gear_ratio": mesh.gear_ratio,
            "contact_ratio": mesh.contact_ratio,
            "pitch_radius_pinion_m": mesh.pitch_radius_pinion_m,
            "pitch_radius_gear_m": mesh.pitch_radius_gear_m,
        })
    except Exception as exc:
        return err_payload(f"gear_mesh_force failed: {exc}", "MBD_ERROR")


# ---------------------------------------------------------------------------
# belt_drive_force_tool
# ---------------------------------------------------------------------------

belt_drive_force_spec = ToolSpec(
    name="belt_drive_force",
    description=(
        "Compute tight-side and slack-side belt tensions for an open flat-belt "
        "or V-belt drive using the Euler belt equation T1/T2 = e^(μ·θ).  "
        "Reference: Shigley (2014) §17.2."
    ),
    input_schema={
        "type": "object",
        "required": ["pulley_a_radius_m", "pulley_b_radius_m", "belt_pitch_m",
                     "belt_youngs_modulus_pa", "pretension_n",
                     "omega_a_rad_s", "omega_b_rad_s"],
        "properties": {
            "pulley_a_radius_m": {"type": "number"},
            "pulley_b_radius_m": {"type": "number"},
            "belt_pitch_m": {"type": "number"},
            "belt_youngs_modulus_pa": {"type": "number"},
            "pretension_n": {"type": "number"},
            "mu": {"type": "number", "default": 0.35},
            "groove_angle_deg": {"type": "number", "default": 0.0},
            "omega_a_rad_s": {"type": "number"},
            "omega_b_rad_s": {"type": "number"},
        },
    },
)


async def run_belt_drive_force(params: dict, ctx: ProjectCtx) -> str:
    try:
        belt = BeltDrive(
            pulley_a_radius_m=float(params["pulley_a_radius_m"]),
            pulley_b_radius_m=float(params["pulley_b_radius_m"]),
            belt_pitch_m=float(params["belt_pitch_m"]),
            belt_youngs_modulus_pa=float(params["belt_youngs_modulus_pa"]),
            pretension_n=float(params["pretension_n"]),
            mu=float(params.get("mu", 0.35)),
            groove_angle_deg=float(params.get("groove_angle_deg", 0.0)),
        )
        T1, T2 = belt_drive_force(
            omega_a=float(params["omega_a_rad_s"]),
            omega_b=float(params["omega_b_rad_s"]),
            belt=belt,
        )
        return ok_payload({
            "ok": True,
            "T1_tight_n": T1,
            "T2_slack_n": T2,
            "tension_ratio": T1 / max(T2, 1e-9),
            "theoretical_ratio": belt.tension_ratio(),
            "wrap_angle_rad": belt.wrap_angle_small(),
        })
    except Exception as exc:
        return err_payload(f"belt_drive_force failed: {exc}", "MBD_ERROR")
