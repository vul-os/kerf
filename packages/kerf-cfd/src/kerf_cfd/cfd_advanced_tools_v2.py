"""
LLM tool wrappers for Wave 10C: snappyHexMesh-style mesher + wind engineering.

Exposes three LLM-callable tools:

  cfd_snappy_hex_mesh        — Cartesian + boundary-snap hex mesh generation
  cfd_wind_load              — ASCE 7-22 building wind pressures, drag, base shear
  cfd_vortex_shedding        — Strouhal vortex shedding frequency (Bearman 1984)

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM, CFX, or physical wind-tunnel testing.  Do not use for
safety-critical structural design.

References
----------
Aftosmis, M.J., Berger, M.J., Melton, J.E. (1998). AIAA J. 36(6), 952–960.
Hirt, C.W., Nichols, B.D. (1981). J. Comput. Phys. 39(1), 201–225.
OpenFOAM snappyHexMesh User Guide (public).
ASCE 7-22 Chapters 26–31 (Wind Loads).
Bearman, P.W. (1984). Ann. Rev. Fluid Mech. 16, 195–222.
Holmes, J.D. (2018). "Wind Loading of Structures," 3rd ed. CRC Press.

# Wave 10C: snappyHexMesh-style mesher + wind engineering
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
# Tool: cfd_snappy_hex_mesh
# ---------------------------------------------------------------------------

_snappy_spec = ToolSpec(
    name="cfd_snappy_hex_mesh",
    description=(
        "Generate a Cartesian hex mesh using a snappyHexMesh-equivalent pipeline "
        "(Aftosmis-Berger-Melton 1998):\n"
        "  Phase 1 CASTELLATED: build background Cartesian grid, apply "
        "local refinement in user-defined regions.\n"
        "  Phase 2 SNAP: project boundary vertices onto surface geometry via "
        "Laplacian smoothing + nearest-point snapping.\n"
        "Returns mesh statistics (cell count, quality metrics, bounding box).\n"
        "DESIGN EXPLORATION ONLY — not OpenFOAM-validated."
    ),
    input_schema={
        "type": "object",
        "required": [
            "bbox_min", "bbox_max", "cell_size_m",
        ],
        "properties": {
            "bbox_min": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Background bounding box minimum [x, y, z] [m]",
            },
            "bbox_max": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Background bounding box maximum [x, y, z] [m]",
            },
            "cell_size_m": {
                "type": "number",
                "description": "Background (coarsest) cell size [m]",
            },
            "refinement_regions": {
                "type": "array",
                "description": (
                    "Local refinement regions. Each entry: "
                    "{bbox_min:[x,y,z], bbox_max:[x,y,z], level:int}. "
                    "Level 1 halves cell size (×8 cells), level 2 quarters (×64), etc."
                ),
                "items": {
                    "type": "object",
                    "required": ["bbox_min", "bbox_max", "level"],
                    "properties": {
                        "bbox_min": {"type": "array", "items": {"type": "number"}},
                        "bbox_max": {"type": "array", "items": {"type": "number"}},
                        "level": {"type": "integer", "minimum": 1},
                    },
                },
                "default": [],
            },
            "boundary_surface_points": {
                "type": "array",
                "description": (
                    "Optional surface sample points for snapping [[x,y,z], ...]. "
                    "If omitted, no snapping is performed."
                ),
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "snap_iterations": {
                "type": "integer",
                "description": "Boundary snap iterations (default 4)",
                "default": 4,
            },
        },
    },
)


@register(_snappy_spec, write=False)
async def run_cfd_snappy_hex_mesh(params: dict, ctx: Any = None) -> str:
    """LLM tool handler for cfd_snappy_hex_mesh."""
    try:
        from kerf_cfd.meshing.snappy_hex import HexMeshSpec, snappy_hex_mesh

        bbox_min = tuple(float(x) for x in params["bbox_min"])
        bbox_max = tuple(float(x) for x in params["bbox_max"])
        cell_size = float(params["cell_size_m"])

        refinement_regions = []
        for rr in params.get("refinement_regions", []):
            refinement_regions.append({
                "bbox_min": tuple(float(x) for x in rr["bbox_min"]),
                "bbox_max": tuple(float(x) for x in rr["bbox_max"]),
                "level": int(rr["level"]),
            })

        boundary_geom = None
        bsp = params.get("boundary_surface_points")
        if bsp:
            boundary_geom = np.array(bsp, dtype=float)

        spec = HexMeshSpec(
            background_bbox_min=bbox_min,
            background_bbox_max=bbox_max,
            cell_size_m=cell_size,
            refinement_regions=refinement_regions,
            boundary_geometry=boundary_geom,
            boundary_snap_iterations=int(params.get("snap_iterations", 4)),
        )

        mesh = snappy_hex_mesh(spec)

        return ok_payload({
            "n_cells": int(len(mesh.hex_connectivity)),
            "n_vertices": int(len(mesh.vertices)),
            "n_boundary_faces": int(sum(len(f) for f in mesh.boundary_faces.values())),
            "total_volume_m3": float(mesh.cell_volumes.sum()),
            "min_volume_m3": float(mesh.cell_volumes.min()),
            "max_volume_m3": float(mesh.cell_volumes.max()),
            "quality": mesh.quality_stats,
            "model": "Cartesian + snap (Aftosmis-Berger-Melton 1998)",
            "honest_flag": "design-exploration only — not OpenFOAM-validated",
        })
    except Exception as exc:
        return err_payload(str(exc), "CFD_SNAPPY_HEX_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_wind_load
# ---------------------------------------------------------------------------

_wind_load_spec = ToolSpec(
    name="cfd_wind_load",
    description=(
        "Compute ASCE 7-22 §26.6 wind pressures, drag coefficient, base shear, "
        "and overturning moment for a rectangular building.\n"
        "Profiles: Exposure B (urban), C (open), D (coastal).\n"
        "Includes vortex shedding and galloping checks.\n"
        "DESIGN EXPLORATION ONLY — not CFD/wind-tunnel-validated."
    ),
    input_schema={
        "type": "object",
        "required": [
            "building_name", "footprint_polygon", "height_m",
            "exposure", "reference_velocity_m_s",
        ],
        "properties": {
            "building_name": {
                "type": "string",
                "description": "Building identifier",
            },
            "footprint_polygon": {
                "type": "array",
                "description": "Ordered footprint vertices [[x,y], ...] [m]",
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "height_m": {
                "type": "number",
                "description": "Building height above ground [m]",
            },
            "roof_type": {
                "type": "string",
                "description": "Roof type: 'flat' | 'gable' | 'hip' | 'mansard'",
                "default": "flat",
            },
            "exposure": {
                "type": "string",
                "description": "ASCE 7-22 Exposure Category: 'B' | 'C' | 'D'",
            },
            "reference_velocity_m_s": {
                "type": "number",
                "description": "Basic wind speed at 10 m [m/s] (ASCE 7-22 Figure 26.5-1)",
            },
            "yaw_deg": {
                "type": "number",
                "description": "Wind direction yaw from building normal [degrees]. Default 0.",
                "default": 0.0,
            },
            "damping_ratio": {
                "type": "number",
                "description": "Structural damping ratio for galloping check (default 0.02)",
                "default": 0.02,
            },
        },
    },
)


@register(_wind_load_spec, write=False)
async def run_cfd_wind_load(params: dict, ctx: Any = None) -> str:
    """LLM tool handler for cfd_wind_load."""
    try:
        from kerf_cfd.wind_engineering.wind_tunnel import (
            BuildingGeometry, WindProfile,
            compute_wind_load_aerodynamic,
            galloping_critical_velocity,
            vortex_shedding_frequency,
        )

        footprint = [tuple(pt) for pt in params["footprint_polygon"]]
        building = BuildingGeometry(
            name=str(params["building_name"]),
            footprint_polygon=footprint,
            height_m=float(params["height_m"]),
            roof_type=str(params.get("roof_type", "flat")),
        )

        wind = WindProfile(
            exposure=str(params["exposure"]),
            reference_velocity_m_s=float(params["reference_velocity_m_s"]),
        )

        yaw = float(params.get("yaw_deg", 0.0))
        report = compute_wind_load_aerodynamic(building, wind, yaw_deg=yaw)

        v_h = wind.velocity_at(building.height_m)
        width = building.projected_width_m(yaw)

        f_vs = vortex_shedding_frequency(
            body_width_m=width,
            velocity_m_s=v_h,
            strouhal_number=0.2,
        )

        damping = float(params.get("damping_ratio", 0.02))
        v_gal = galloping_critical_velocity(building, damping_ratio=damping)

        return ok_payload({
            "building": params["building_name"],
            "wind_speed_at_roof_m_s": round(v_h, 3),
            "velocity_pressure_pa": round(report.velocity_pressure_pa, 2),
            "mean_pressure_pa": {k: round(v, 2) for k, v in report.mean_pressure_pa.items()},
            "peak_pressure_pa": {k: round(v, 2) for k, v in report.peak_pressure_pa.items()},
            "drag_coefficient_Cd": round(report.drag_coefficient, 3),
            "base_shear_kN": round(report.base_shear_kn, 2),
            "overturning_moment_kNm": round(report.overturning_moment_kn_m, 2),
            "vortex_shedding_hz": round(f_vs, 4),
            "galloping_critical_velocity_m_s": round(v_gal, 2),
            "exposure": params["exposure"],
            "code": "ASCE 7-22 §26.6",
            "honest_flag": (
                "design-exploration only — buildings h > 60 m require "
                "wind-tunnel testing or validated LES/DES CFD"
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "CFD_WIND_LOAD_ERROR")


# ---------------------------------------------------------------------------
# Tool: cfd_vortex_shedding
# ---------------------------------------------------------------------------

_vs_spec = ToolSpec(
    name="cfd_vortex_shedding",
    description=(
        "Compute vortex shedding frequency and assess lock-in risk for a "
        "bluff body (Bearman 1984 Strouhal relation: f_s = St·v/D).\n"
        "Returns shedding frequency and reduced velocity Ur = v / (f_n · D).\n"
        "Lock-in occurs when Ur ≈ 1/St (i.e. ~ 5 for St = 0.2)."
    ),
    input_schema={
        "type": "object",
        "required": ["body_width_m", "velocity_m_s"],
        "properties": {
            "body_width_m": {
                "type": "number",
                "description": "Characteristic body width D [m]",
            },
            "velocity_m_s": {
                "type": "number",
                "description": "Wind speed [m/s]",
            },
            "strouhal_number": {
                "type": "number",
                "description": "Strouhal number (default 0.2 — sharp-edged section, Bearman 1984)",
                "default": 0.2,
            },
            "natural_frequency_hz": {
                "type": "number",
                "description": (
                    "Structural natural frequency [Hz] for lock-in check. "
                    "If omitted, lock-in risk not assessed."
                ),
            },
        },
    },
)


@register(_vs_spec, write=False)
async def run_cfd_vortex_shedding(params: dict, ctx: Any = None) -> str:
    """LLM tool handler for cfd_vortex_shedding."""
    try:
        from kerf_cfd.wind_engineering.wind_tunnel import vortex_shedding_frequency

        D = float(params["body_width_m"])
        v = float(params["velocity_m_s"])
        St = float(params.get("strouhal_number", 0.2))

        f_s = vortex_shedding_frequency(D, v, St)

        result: dict = {
            "shedding_frequency_hz": round(f_s, 4),
            "strouhal_number": St,
            "body_width_m": D,
            "velocity_m_s": v,
            "model": "Bearman (1984) f_s = St · v / D",
        }

        fn = params.get("natural_frequency_hz")
        if fn is not None:
            fn = float(fn)
            Ur = v / max(fn * D, 1e-9)
            lock_in_threshold = 1.0 / max(St, 1e-6)
            result["natural_frequency_hz"] = fn
            result["reduced_velocity_Ur"] = round(Ur, 3)
            result["lock_in_threshold_Ur"] = round(lock_in_threshold, 2)
            result["lock_in_risk"] = "HIGH" if abs(Ur - lock_in_threshold) < 1.5 else "LOW"

        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "CFD_VORTEX_SHEDDING_ERROR")
