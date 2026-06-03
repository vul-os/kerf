"""
LLM tool wrappers for Wave 9C advanced CFD capabilities.

Exposes three LLM-callable tools:

  cfd_combustion_ebu      — Magnussen EBU non-premixed combustion step
  cfd_lagrangian_track    — Lagrangian particle tracking (one-way)
  cfd_fsi_displace_mesh   — ALE dynamic mesh displacement + GCL correction

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM or experimental benchmarks.  Do not use for safety-critical design.

# Wave 9C: OpenFOAM combustion + Lagrangian + FSI
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
# Tool: cfd_combustion_ebu
# ---------------------------------------------------------------------------

_combustion_spec = ToolSpec(
    name="cfd_combustion_ebu",
    description=(
        "Run one time step of the Magnussen-Hjertager (1976) Eddy Break-Up "
        "non-premixed combustion model on an array of cells. "
        "Returns updated species mass fractions and temperature. "
        "DESIGN EXPLORATION ONLY — not OpenFOAM-validated."
    ),
    input_schema={
        "type": "object",
        "required": ["Y_fuel", "Y_oxidizer", "Y_products", "temperature",
                     "epsilon_over_k", "dt"],
        "properties": {
            "fuel_name": {
                "type": "string",
                "description": "Fuel species name: 'CH4' | 'C8H18' | 'H2'",
                "default": "CH4",
            },
            "Y_fuel": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Per-cell fuel mass fractions [-]",
            },
            "Y_oxidizer": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Per-cell oxidizer mass fractions [-]",
            },
            "Y_products": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Per-cell product mass fractions [-]",
            },
            "temperature": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Per-cell static temperature [K]",
            },
            "epsilon_over_k": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Per-cell turbulent time-scale ε/k [1/s]",
            },
            "dt": {
                "type": "number",
                "description": "Time step [s]",
            },
            "A_ebu": {
                "type": "number",
                "description": "Magnussen mixing constant (default 4.0)",
                "default": 4.0,
            },
            "B_ebu": {
                "type": "number",
                "description": "Products constant (default 0.5)",
                "default": 0.5,
            },
        },
    },
)

# Built-in fuel database
_FUEL_DB = {
    "CH4": {
        "name": "CH4", "molar_mass_kg_per_mol": 0.01604,
        "LHV_J_per_kg": 50_050_000.0, "stoichiometric_AFR": 17.2,
    },
    "C8H18": {
        "name": "C8H18", "molar_mass_kg_per_mol": 0.11423,
        "LHV_J_per_kg": 44_400_000.0, "stoichiometric_AFR": 15.1,
    },
    "H2": {
        "name": "H2", "molar_mass_kg_per_mol": 0.002016,
        "LHV_J_per_kg": 119_960_000.0, "stoichiometric_AFR": 34.3,
    },
}


@register(_combustion_spec, write=False)
async def run_cfd_combustion_ebu(params: dict, ctx: Any = None) -> str:
    """LLM tool handler for cfd_combustion_ebu."""
    try:
        from kerf_cfd.combustion.reacting_flow import (
            CombustionMixture, FuelSpecies, step_combustion,
        )

        fuel_name = params.get("fuel_name", "CH4")
        fd = _FUEL_DB.get(fuel_name, _FUEL_DB["CH4"])
        fuel = FuelSpecies(**fd)

        mix = CombustionMixture(
            fuel=fuel,
            Y_fuel=np.array(params["Y_fuel"], dtype=float),
            Y_oxidizer=np.array(params["Y_oxidizer"], dtype=float),
            Y_products=np.array(params["Y_products"], dtype=float),
            temperature=np.array(params["temperature"], dtype=float),
        )
        eps_k = np.array(params["epsilon_over_k"], dtype=float)
        dt = float(params["dt"])
        A = float(params.get("A_ebu", 4.0))
        B = float(params.get("B_ebu", 0.5))

        from kerf_cfd.combustion.reacting_flow import magnussen_ebu_reaction_rate
        omega = magnussen_ebu_reaction_rate(mix, eps_k, A_ebu=A, B_ebu=B)
        mix_new = step_combustion(mix, fuel, eps_k, dt)

        return ok_payload({
            "fuel": fuel_name,
            "n_cells": len(mix_new.Y_fuel),
            "mean_omega_dot_kg_m3_s": float(np.mean(omega)),
            "max_omega_dot_kg_m3_s": float(np.max(omega)),
            "mean_temperature_K": float(np.mean(mix_new.temperature)),
            "max_temperature_K": float(np.max(mix_new.temperature)),
            "mean_Y_fuel": float(np.mean(mix_new.Y_fuel)),
            "mean_Y_products": float(np.mean(mix_new.Y_products)),
            "model": "Magnussen-Hjertager EBU (1976)",
            "honest_flag": "design-exploration only — not OpenFOAM-validated",
        })
    except Exception as exc:
        return err_payload(str(exc), "CFD_COMBUSTION_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_lagrangian_track
# ---------------------------------------------------------------------------

_lagrangian_spec = ToolSpec(
    name="cfd_lagrangian_track",
    description=(
        "Track a cloud of particles through a carrier fluid for one time step "
        "using Lagrangian one-way coupling (Schiller-Naumann drag + gravity). "
        "Returns updated particle positions and velocities. "
        "DESIGN EXPLORATION ONLY — not OpenFOAM-validated."
    ),
    input_schema={
        "type": "object",
        "required": ["particles", "fluid_velocity", "fluid_density",
                     "fluid_viscosity", "dt"],
        "properties": {
            "particles": {
                "type": "array",
                "description": "List of particle dicts with keys: position[3], velocity[3], diameter_m, density_kg_per_m3",
                "items": {
                    "type": "object",
                    "required": ["position", "velocity", "diameter_m", "density_kg_per_m3"],
                    "properties": {
                        "position": {"type": "array", "items": {"type": "number"}},
                        "velocity": {"type": "array", "items": {"type": "number"}},
                        "diameter_m": {"type": "number"},
                        "density_kg_per_m3": {"type": "number"},
                    },
                },
            },
            "fluid_velocity": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Uniform carrier-fluid velocity [vx, vy, vz] m/s",
            },
            "fluid_density": {
                "type": "number",
                "description": "Carrier-fluid density [kg/m³]",
            },
            "fluid_viscosity": {
                "type": "number",
                "description": "Carrier-fluid dynamic viscosity [Pa·s]",
            },
            "gravity": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[gx, gy, gz] m/s² (default [0, -9.81, 0])",
                "default": [0.0, -9.81, 0.0],
            },
            "dt": {
                "type": "number",
                "description": "Time step [s]",
            },
        },
    },
)


@register(_lagrangian_spec, write=False)
async def run_cfd_lagrangian_track(params: dict, ctx: Any = None) -> str:
    """LLM tool handler for cfd_lagrangian_track."""
    try:
        from kerf_cfd.lagrangian.particle_tracking import (
            Particle, ParticleField, step_particles_one_way,
        )

        u_f_uniform = np.array(params["fluid_velocity"], dtype=float)

        particles = []
        for pd in params["particles"]:
            particles.append(Particle(
                position=np.array(pd["position"], dtype=float),
                velocity=np.array(pd["velocity"], dtype=float),
                diameter_m=float(pd["diameter_m"]),
                density_kg_per_m3=float(pd["density_kg_per_m3"]),
            ))

        field = ParticleField(particles=particles)
        gravity = tuple(params.get("gravity", [0.0, -9.81, 0.0]))

        field_new = step_particles_one_way(
            field=field,
            fluid_velocity_at=lambda pos: u_f_uniform,
            fluid_density=float(params["fluid_density"]),
            fluid_viscosity=float(params["fluid_viscosity"]),
            gravity=gravity,
            dt=float(params["dt"]),
        )

        result_particles = [
            {
                "position": p.position.tolist(),
                "velocity": p.velocity.tolist(),
                "diameter_m": p.diameter_m,
                "density_kg_per_m3": p.density_kg_per_m3,
            }
            for p in field_new.particles
        ]

        return ok_payload({
            "n_particles": len(result_particles),
            "particles": result_particles,
            "model": "Schiller-Naumann drag, Crowe et al. (1998)",
            "honest_flag": "design-exploration only — not OpenFOAM-validated",
        })
    except Exception as exc:
        return err_payload(str(exc), "CFD_LAGRANGIAN_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_fsi_displace_mesh
# ---------------------------------------------------------------------------

_fsi_spec = ToolSpec(
    name="cfd_fsi_displace_mesh",
    description=(
        "Displace boundary nodes of an ALE mesh and propagate motion to "
        "the interior via Laplacian smoothing (Lohner-Yang 1996). "
        "Optionally compute GCL correction. "
        "DESIGN EXPLORATION ONLY — not OpenFOAM-validated."
    ),
    input_schema={
        "type": "object",
        "required": ["vertices", "cell_connectivity",
                     "boundary_node_ids", "boundary_displacement", "dt"],
        "properties": {
            "vertices": {
                "type": "array",
                "description": "Vertex coordinates (Nv, 3) [m]",
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "cell_connectivity": {
                "type": "array",
                "description": "Cell vertex indices (Nc, nv_per_cell)",
                "items": {"type": "array", "items": {"type": "integer"}},
            },
            "boundary_node_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Global vertex indices of boundary nodes",
            },
            "boundary_displacement": {
                "type": "array",
                "description": "Displacement for each boundary node (Nb, 3) [m]",
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "dt": {
                "type": "number",
                "description": "Time step [s]",
            },
            "smoothing_iterations": {
                "type": "integer",
                "description": "Laplacian smoothing sweeps (default 5)",
                "default": 5,
            },
        },
    },
)


@register(_fsi_spec, write=False)
async def run_cfd_fsi_displace_mesh(params: dict, ctx: Any = None) -> str:
    """LLM tool handler for cfd_fsi_displace_mesh."""
    try:
        from kerf_cfd.fsi.dynamic_mesh import (
            DynamicMeshState, displace_mesh_rigid,
        )

        verts = np.array(params["vertices"], dtype=float)
        conn = np.array(params["cell_connectivity"], dtype=int)
        n_verts = len(verts)

        state_old = DynamicMeshState(
            vertices=verts,
            cell_connectivity=conn,
            vertex_velocity=np.zeros((n_verts, 3)),
        )

        boundary_disp = np.array(params["boundary_displacement"], dtype=float)
        boundary_ids = list(params["boundary_node_ids"])
        dt = float(params["dt"])
        n_smooth = int(params.get("smoothing_iterations", 5))

        state_new = displace_mesh_rigid(
            state=state_old,
            boundary_displacement=boundary_disp,
            boundary_node_ids=boundary_ids,
            dt=dt,
            smoothing_iterations=n_smooth,
        )

        max_mesh_vel = float(np.max(np.linalg.norm(state_new.vertex_velocity, axis=1)))
        mean_mesh_vel = float(np.mean(np.linalg.norm(state_new.vertex_velocity, axis=1)))

        return ok_payload({
            "n_vertices": n_verts,
            "n_cells": len(conn),
            "max_mesh_velocity_m_s": max_mesh_vel,
            "mean_mesh_velocity_m_s": mean_mesh_vel,
            "new_vertices": state_new.vertices.tolist(),
            "model": "Laplacian ALE smoothing (Lohner-Yang 1996)",
            "honest_flag": "design-exploration only — not OpenFOAM-validated",
        })
    except Exception as exc:
        return err_payload(str(exc), "CFD_FSI_ERROR")
