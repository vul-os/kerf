"""
kerf_cfd.internal_airflow.room_cfd_tool — LLM tool: cfd_room_airflow_3d.

Exposes the 3-D room SIMPLE CFD solver as an LLM-callable tool.

Tool schema
-----------
  name:   cfd_room_airflow_3d
  inputs: room geometry + diffuser config + heat sources + occupants
  outputs: velocity/temperature field slices + comfort metrics (PMV/PPD/DR/age-of-air)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from kerf_cfd.internal_airflow.room_cfd_3d import (
    Diffuser,
    ExhaustGrille,
    HeatSource,
    RoomAirflow3DSpec,
    run_room_cfd_3d,
)


# ---------------------------------------------------------------------------
# Tool spec (JSON Schema compatible dict)
# ---------------------------------------------------------------------------

cfd_room_airflow_3d_spec: Dict[str, Any] = {
    "name": "cfd_room_airflow_3d",
    "description": (
        "3-D room internal-airflow CFD (IES VE MicroFlo-style). "
        "Solves steady incompressible RANS on a structured Cartesian grid with "
        "SIMPLE pressure-velocity coupling, algebraic mixing-length turbulence, "
        "and Boussinesq buoyancy (temperature-coupled). "
        "Outputs: velocity + temperature field slices (plan / section), "
        "thermal-comfort metrics per occupant (PMV/PPD per Fanger 1972, "
        "draught rate per ISO 7730:2005, mean age-of-air per Sandberg 1981, "
        "vertical temperature gradient), and ventilation effectiveness. "
        "HONEST: algebraic mixing-length turbulence, steady-state, coarse grid (~0.25 m), "
        "no radiation, not validated against MicroFlo benchmark cases."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["room_dims_m", "diffusers"],
        "properties": {
            "room_dims_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "[Lx, Ly, Lz] room dimensions in metres (length, width, height)."
            },
            "diffusers": {
                "type": "array",
                "description": "Supply air diffusers.",
                "items": {
                    "type": "object",
                    "required": ["position_m", "face"],
                    "properties": {
                        "position_m": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                            "description": "[x, y, z] diffuser centre [m]."
                        },
                        "face": {
                            "type": "string",
                            "enum": ["ceiling", "floor", "wall_x0", "wall_x1", "wall_y0", "wall_y1"],
                            "description": "Room face on which the diffuser is mounted."
                        },
                        "velocity_m_s": {
                            "type": "number",
                            "default": 2.0,
                            "description": "Supply jet speed [m/s]. Typical: 1–4 m/s."
                        },
                        "T_supply_C": {
                            "type": "number",
                            "default": 14.0,
                            "description": "Supply air temperature [°C]. Typical cooling: 13–16°C."
                        },
                        "area_m2": {
                            "type": "number",
                            "default": 0.04,
                            "description": "Diffuser face area [m²]."
                        },
                    }
                }
            },
            "exhausts": {
                "type": "array",
                "description": "Return / exhaust grilles (outflow boundaries).",
                "items": {
                    "type": "object",
                    "required": ["position_m", "face"],
                    "properties": {
                        "position_m": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3
                        },
                        "face": {
                            "type": "string",
                            "enum": ["ceiling", "floor", "wall_x0", "wall_x1", "wall_y0", "wall_y1"]
                        },
                    }
                },
                "default": []
            },
            "heat_sources": {
                "type": "array",
                "description": "Internal heat sources: occupants (~100 W), equipment (~150 W), etc.",
                "items": {
                    "type": "object",
                    "required": ["position_m", "watts"],
                    "properties": {
                        "position_m": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3
                        },
                        "watts": {"type": "number"},
                        "label": {"type": "string", "default": "source"}
                    }
                },
                "default": []
            },
            "occupant_positions": {
                "type": "array",
                "description": "Occupant head positions [x, y, z] in metres for comfort evaluation.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3, "maxItems": 3
                },
                "default": []
            },
            "T_ambient_C": {
                "type": "number",
                "default": 22.0,
                "description": "Ambient / initial room temperature [°C]."
            },
            "humidity_rh": {
                "type": "number",
                "default": 50.0,
                "description": "Relative humidity [%] for PMV/PPD calculation."
            },
            "met": {
                "type": "number",
                "default": 1.2,
                "description": "Occupant metabolic rate [met] (1.2 = seated light activity)."
            },
            "clo": {
                "type": "number",
                "default": 0.5,
                "description": "Clothing insulation [clo] (0.5 = light summer; 1.0 = indoor winter)."
            },
            "grid_step_m": {
                "type": "number",
                "default": 0.25,
                "description": "Grid cell size [m]. Smaller = finer (slower). Typical: 0.2–0.5 m."
            },
            "n_outer": {
                "type": "integer",
                "default": 80,
                "description": "SIMPLE outer iterations. 40–100 typical for steady convergence."
            },
        }
    }
}


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

def _serialize_field_slice(
    arr: np.ndarray,
    axis: int,
    slice_idx: int,
) -> List[List[float]]:
    """Extract 2-D slice from 3-D array for JSON serialisation."""
    if axis == 0:
        sl = arr[min(slice_idx, arr.shape[0]-1), :, :]
    elif axis == 1:
        sl = arr[:, min(slice_idx, arr.shape[1]-1), :]
    else:
        sl = arr[:, :, min(slice_idx, arr.shape[2]-1)]
    return sl.tolist()


async def run_cfd_room_airflow_3d(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    LLM tool handler for cfd_room_airflow_3d.

    Runs the 3-D SIMPLE room-airflow solver and returns field slices +
    comfort metrics in a JSON-serialisable dict.
    """
    # Build spec
    room_dims_m = tuple(params["room_dims_m"])

    diffusers = []
    for d in params.get("diffusers", []):
        diffusers.append(Diffuser(
            position_m=tuple(d["position_m"]),
            face=d.get("face", "ceiling"),
            velocity_m_s=float(d.get("velocity_m_s", 2.0)),
            T_supply_C=float(d.get("T_supply_C", 14.0)),
            area_m2=float(d.get("area_m2", 0.04)),
        ))

    exhausts = []
    for e in params.get("exhausts", []):
        exhausts.append(ExhaustGrille(
            position_m=tuple(e["position_m"]),
            face=e.get("face", "wall_x1"),
        ))

    heat_sources = []
    for hs in params.get("heat_sources", []):
        heat_sources.append(HeatSource(
            position_m=tuple(hs["position_m"]),
            watts=float(hs["watts"]),
            label=hs.get("label", "source"),
        ))

    occupants = [tuple(p) for p in params.get("occupant_positions", [])]

    spec = RoomAirflow3DSpec(
        room_dims_m=room_dims_m,
        diffusers=diffusers,
        exhausts=exhausts,
        heat_sources=heat_sources,
        occupant_positions=occupants,
        T_ambient_C=float(params.get("T_ambient_C", 22.0)),
        humidity_rh=float(params.get("humidity_rh", 50.0)),
        met=float(params.get("met", 1.2)),
        clo=float(params.get("clo", 0.5)),
    )

    result = run_room_cfd_3d(
        spec,
        grid_step_m=float(params.get("grid_step_m", 0.25)),
        n_outer=int(params.get("n_outer", 80)),
    )

    nX, nY, nZ = result.grid_dims

    # Field slices for visualisation (mid-plane plan view and vertical section)
    plan_slice_z  = nZ // 2                        # horizontal mid-height plan
    sect_slice_y  = nY // 2                        # vertical longitudinal section

    # Comfort dict list
    comfort_out = []
    for oc in result.occupant_comfort:
        comfort_out.append({
            "occupant_idx": oc.occupant_idx,
            "position_m": list(oc.position_m),
            "T_air_C": oc.T_air_C,
            "T_mrt_C": oc.T_mrt_C,
            "velocity_m_s": oc.velocity_m_s,
            "turbulence_intensity": oc.turbulence_intensity,
            "pmv": oc.pmv,
            "ppd": oc.ppd,
            "draught_rate_pct": oc.draught_rate,
            "age_of_air_min": oc.age_of_air_min,
            "vertical_dT_K_m": oc.dT_dz_K_m,
        })

    return {
        "grid_dims": list(result.grid_dims),
        "grid_spacing_m": [result.dx_m, result.dy_m, result.dz_m],
        "room_dims_m": list(room_dims_m),

        # Plan (XY) slices at mid-height
        "plan_velocity_mag": _serialize_field_slice(result.velocity_mag, 2, plan_slice_z),
        "plan_temperature_C": _serialize_field_slice(result.T, 2, plan_slice_z),
        "plan_age_of_air_min": _serialize_field_slice(result.age_of_air / 60.0, 2, plan_slice_z),

        # Vertical section (XZ) slices at mid-width
        "section_velocity_u": _serialize_field_slice(result.U, 1, sect_slice_y),
        "section_velocity_w": _serialize_field_slice(result.W, 1, sect_slice_y),
        "section_temperature_C": _serialize_field_slice(result.T, 1, sect_slice_y),

        # Summary scalars
        "T_mean_C": round(float(np.mean(result.T)), 2),
        "T_max_C": round(float(np.max(result.T)), 2),
        "T_min_C": round(float(np.min(result.T)), 2),
        "velocity_max_m_s": round(float(np.max(result.velocity_mag)), 3),
        "velocity_mean_m_s": round(float(np.mean(result.velocity_mag)), 4),
        "mass_continuity_residual": round(result.mass_residual, 6),
        "ventilation_effectiveness": result.ventilation_effectiveness,
        "max_vertical_dT_K_m": result.max_vertical_dT_K_m,

        # Per-occupant comfort
        "occupant_comfort": comfort_out,

        # Honest model notes
        "model_notes": result.model_notes,
    }
