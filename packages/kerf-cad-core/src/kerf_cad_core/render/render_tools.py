"""
kerf_cad_core.render.render_tools — LLM tool wrappers for the render + fluid modules.

Registers the following tools:
  render_parse_ies_file           — parse an IES LM-63 photometric file
  render_theatrical_lighting_plot — build a lighting plot + SVG
  render_lux_simulation           — compute lux/luminance at measurement points
  render_archviz_scene            — render an archviz scene to an image
  render_fluid_smoke_step         — advance a Stam smoke simulation
  render_fluid_flip_step          — advance a FLIP liquid simulation

Author: imranparuk
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Lazy imports to keep registration fast
def _get_theatrical():
    from kerf_cad_core.render.theatrical_lighting import (
        IesPhotometricFile,
        TheatricalFixture,
        TheatricalLightingPlot,
        read_ies_file,
    )
    return IesPhotometricFile, TheatricalFixture, TheatricalLightingPlot, read_ies_file


def _get_lux():
    from kerf_cad_core.render.luminance_lux_sim import (
        DaylightConditions,
        ElectricLuminaire,
        compute_daylight_lux,
    )
    return DaylightConditions, ElectricLuminaire, compute_daylight_lux


def _get_archviz():
    from kerf_cad_core.render.archviz_pipeline import (
        ArchVizScene,
        render_archviz,
        make_simple_room_scene,
    )
    return ArchVizScene, render_archviz, make_simple_room_scene


def _get_fluid():
    from kerf_cad_core.fluid.visual_fluid import (
        FluidSimState,
        make_fluid_state,
        step_flip,
        step_smoke,
    )
    return FluidSimState, make_fluid_state, step_flip, step_smoke


# ── Tool registration ─────────────────────────────────────────────────────────

try:
    from kerf_core.tools import register as _register, ToolResult  # type: ignore[import]
except ImportError:
    def _register(fn=None, *, name: str = "", description: str = "", schema: dict = None):
        """Stub @register when kerf_core is not installed."""
        if fn is not None:
            return fn
        def decorator(f):
            return f
        return decorator

    class ToolResult:  # type: ignore[no-redef]
        def __init__(self, content: Any = None, error: str = ""):
            self.content = content
            self.error = error


@_register(
    name="render_parse_ies_file",
    description=(
        "Parse an IES LM-63-2002 ASCII photometric data file and return the "
        "luminaire name, total lumens, and a summary of the candela grid. "
        "Input: the full text of the .ies file."
    ),
    schema={
        "type": "object",
        "properties": {
            "ies_content": {
                "type": "string",
                "description": "Full text content of the IES LM-63 ASCII file.",
            }
        },
        "required": ["ies_content"],
    },
)
def render_parse_ies_file(ies_content: str) -> ToolResult:
    """Parse an IES LM-63 photometric file."""
    try:
        _, _, _, read_ies_file = _get_theatrical()
        ies = read_ies_file(ies_content)
        result = {
            "luminaire_name": ies.luminaire_name,
            "lumens": ies.lumens,
            "n_vertical_angles": len(ies.vertical_angles),
            "n_horizontal_angles": len(ies.horizontal_angles),
            "candela_grid_shape": list(ies.candela_grid.shape),
            "peak_candela": float(ies.candela_grid.max()),
            "vertical_angles_deg": ies.vertical_angles.tolist(),
            "horizontal_angles_deg": ies.horizontal_angles.tolist(),
        }
        return ToolResult(content=result)
    except Exception as exc:
        return ToolResult(error=str(exc))


@_register(
    name="render_theatrical_lighting_plot",
    description=(
        "Build a theatrical lighting plot from a list of fixtures and truss lines. "
        "Returns an SVG string (plan-view Vectorworks-style plot) and illuminance "
        "at a specified measurement point."
    ),
    schema={
        "type": "object",
        "properties": {
            "fixtures": {
                "type": "array",
                "description": (
                    "List of fixture objects, each with: fixture_id, type, "
                    "position [x,y,z], aim_target [x,y,z], color [r,g,b], "
                    "intensity_pct (0..100), channel, circuit, purpose."
                ),
                "items": {"type": "object"},
            },
            "truss_lines": {
                "type": "array",
                "description": "List of [[x0,y0,z0],[x1,y1,z1]] truss line pairs.",
                "items": {"type": "array"},
            },
            "stage_width": {"type": "number", "default": 10.0},
            "stage_depth": {"type": "number", "default": 8.0},
            "measurement_point": {
                "type": "array",
                "description": "[x,y,z] point to compute illuminance at (metres).",
                "items": {"type": "number"},
            },
        },
        "required": ["fixtures"],
    },
)
def render_theatrical_lighting_plot(
    fixtures: List[Dict],
    truss_lines: Optional[List] = None,
    stage_width: float = 10.0,
    stage_depth: float = 8.0,
    measurement_point: Optional[List[float]] = None,
) -> ToolResult:
    """Build and return a theatrical lighting plot SVG."""
    try:
        _, TheatricalFixture, TheatricalLightingPlot, _ = _get_theatrical()

        fix_objs = []
        for f in fixtures:
            fix_objs.append(TheatricalFixture(
                fixture_id=str(f.get("fixture_id", "FX")),
                type=str(f.get("type", "PAR64")),
                position=tuple(f.get("position", [0.0, 0.0, 5.0])),
                aim_target=tuple(f.get("aim_target", [0.0, 0.0, 0.0])),
                color=tuple(f.get("color", [1.0, 1.0, 1.0])),
                intensity_pct=float(f.get("intensity_pct", 100.0)),
                ies_file=None,
                channel=int(f.get("channel", 1)),
                circuit=str(f.get("circuit", "")),
                purpose=str(f.get("purpose", "")),
            ))

        truss = []
        if truss_lines:
            for tl in truss_lines:
                a, b = tl[0], tl[1]
                truss.append((tuple(a), tuple(b)))

        plot = TheatricalLightingPlot(
            fixtures=fix_objs,
            truss_lines=truss,
            stage_width=stage_width,
            stage_depth=stage_depth,
        )

        svg = plot.to_svg()

        result: Dict[str, Any] = {
            "fixture_count": plot.fixture_count(),
            "total_load_watts": plot.total_load_watts(),
            "svg": svg,
        }

        if measurement_point:
            result["illuminance_at_point_lux"] = plot.illuminance_at(
                tuple(measurement_point)
            )

        return ToolResult(content=result)
    except Exception as exc:
        return ToolResult(error=str(exc))


@_register(
    name="render_lux_simulation",
    description=(
        "Compute illuminance (lux) and luminance at measurement points using "
        "two-pass simplified radiosity. Supports CIE daylight sky models and "
        "supplementary electric luminaires."
    ),
    schema={
        "type": "object",
        "properties": {
            "measurement_points": {
                "type": "array",
                "description": "List of [x,y,z] measurement locations (metres).",
                "items": {"type": "array"},
            },
            "sky_model": {
                "type": "string",
                "enum": ["cie_overcast", "cie_clear", "cie_intermediate"],
                "default": "cie_clear",
            },
            "latitude_deg": {"type": "number", "default": 0.0},
            "longitude_deg": {"type": "number", "default": 0.0},
            "date_iso": {"type": "string", "default": "2026-06-21"},
            "time_local": {"type": "string", "default": "12:00"},
            "timezone_offset_h": {"type": "number", "default": 0.0},
            "electric_luminaires": {
                "type": "array",
                "description": (
                    "Optional list of electric luminaires: each with "
                    "position [x,y,z], intensity_cd, direction [x,y,z], beam_angle_deg."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["measurement_points"],
    },
)
def render_lux_simulation(
    measurement_points: List[List[float]],
    sky_model: str = "cie_clear",
    latitude_deg: float = 0.0,
    longitude_deg: float = 0.0,
    date_iso: str = "2026-06-21",
    time_local: str = "12:00",
    timezone_offset_h: float = 0.0,
    electric_luminaires: Optional[List[Dict]] = None,
) -> ToolResult:
    """Compute lux/luminance via simplified two-pass radiosity."""
    try:
        DaylightConditions, ElectricLuminaire, compute_daylight_lux = _get_lux()

        conditions = DaylightConditions(
            sky_model=sky_model,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            date_iso=date_iso,
            time_local=time_local,
            timezone_offset_h=timezone_offset_h,
        )

        lum_list = None
        if electric_luminaires:
            lum_list = [
                ElectricLuminaire(
                    position=tuple(lm.get("position", [0.0, 0.0, 3.0])),
                    intensity_cd=float(lm.get("intensity_cd", 1000.0)),
                    direction=tuple(lm.get("direction", [0.0, 0.0, -1.0])),
                    beam_angle_deg=float(lm.get("beam_angle_deg", 30.0)),
                )
                for lm in electric_luminaires
            ]

        pts = [tuple(p) for p in measurement_points]
        report = compute_daylight_lux(
            scene_geometry=[],
            measurement_points=pts,
            conditions=conditions,
            electric_luminaires=lum_list,
        )

        return ToolResult(content={
            "average_lux": report.average_lux,
            "min_lux": report.min_lux,
            "max_lux": report.max_lux,
            "uniformity_ratio": report.uniformity_ratio,
            "point_lux_values": report.lux_values,
            "sky_model": sky_model,
            "solar_altitude_hint": (
                f"lat={latitude_deg}, lon={longitude_deg}, "
                f"date={date_iso}, time={time_local}"
            ),
        })
    except Exception as exc:
        return ToolResult(error=str(exc))


@_register(
    name="render_archviz_scene",
    description=(
        "Render a simple room archviz scene and return image metadata. "
        "Uses photon-map indirect lighting (Jensen 1996) + Cook-Torrance BRDF. "
        "Returns image shape and a summary of brightness statistics."
    ),
    schema={
        "type": "object",
        "properties": {
            "room_width": {"type": "number", "default": 6.0},
            "room_depth": {"type": "number", "default": 5.0},
            "room_height": {"type": "number", "default": 3.0},
            "resolution_w": {"type": "integer", "default": 64},
            "resolution_h": {"type": "integer", "default": 48},
            "samples": {"type": "integer", "default": 64},
            "sun_intensity": {"type": "number", "default": 1.2},
        },
        "required": [],
    },
)
def render_archviz_scene(
    room_width: float = 6.0,
    room_depth: float = 5.0,
    room_height: float = 3.0,
    resolution_w: int = 64,
    resolution_h: int = 48,
    samples: int = 64,
    sun_intensity: float = 1.2,
) -> ToolResult:
    """Render a simple archviz room scene."""
    try:
        ArchVizScene, render_archviz, make_simple_room_scene = _get_archviz()
        scene = make_simple_room_scene(room_width, room_depth, room_height)
        scene.sun_intensity = sun_intensity
        image = render_archviz(scene, (resolution_w, resolution_h), samples=samples)

        return ToolResult(content={
            "image_shape": list(image.shape),
            "dtype": str(image.dtype),
            "mean_brightness": float(image.mean()),
            "max_brightness": int(image.max()),
            "min_brightness": int(image.min()),
            "note": (
                "Preview-quality render. Not Vray/Lumion quality. "
                "Photon-map indirect lighting (Jensen 1996) + Cook-Torrance BRDF."
            ),
        })
    except Exception as exc:
        return ToolResult(error=str(exc))


@_register(
    name="render_fluid_smoke_step",
    description=(
        "Advance a Stam (1999) smoke simulation by one time step. "
        "Returns grid density statistics and a summary of the velocity field."
    ),
    schema={
        "type": "object",
        "properties": {
            "grid_nx": {"type": "integer", "default": 16},
            "grid_ny": {"type": "integer", "default": 16},
            "grid_nz": {"type": "integer", "default": 16},
            "cell_size": {"type": "number", "default": 0.1},
            "dt": {"type": "number", "default": 0.05},
            "n_steps": {"type": "integer", "default": 5},
            "buoyancy": {"type": "number", "default": 1.0},
            "dissipation": {"type": "number", "default": 0.99},
            "source_position": {
                "type": "array",
                "description": "[ix,iy,iz] grid index of density source.",
                "items": {"type": "integer"},
            },
            "source_rate": {"type": "number", "default": 0.5},
        },
        "required": [],
    },
)
def render_fluid_smoke_step(
    grid_nx: int = 16,
    grid_ny: int = 16,
    grid_nz: int = 16,
    cell_size: float = 0.1,
    dt: float = 0.05,
    n_steps: int = 5,
    buoyancy: float = 1.0,
    dissipation: float = 0.99,
    source_position: Optional[List[int]] = None,
    source_rate: float = 0.5,
) -> ToolResult:
    """Advance a Stam smoke simulation."""
    try:
        FluidSimState, make_fluid_state, _, step_smoke = _get_fluid()

        state = make_fluid_state(
            grid_nx, grid_ny, grid_nz,
            cell_size=cell_size,
            with_temperature=False,
        )

        # Build density source array
        src = np.zeros((grid_nx, grid_ny, grid_nz), dtype=float)
        if source_position:
            ix, iy, iz = (
                int(source_position[0]),
                int(source_position[1]) if len(source_position) > 1 else grid_ny // 2,
                int(source_position[2]) if len(source_position) > 2 else 1,
            )
            ix = max(0, min(grid_nx - 1, ix))
            iy = max(0, min(grid_ny - 1, iy))
            iz = max(0, min(grid_nz - 1, iz))
            src[ix, iy, iz] = source_rate
        else:
            # Default source: centre of bottom layer
            src[grid_nx // 2, grid_ny // 2, 1] = source_rate

        for _ in range(n_steps):
            state = step_smoke(
                state, dt,
                buoyancy=buoyancy,
                dissipation=dissipation,
                add_density_sources=src,
            )

        return ToolResult(content={
            "grid_resolution": list(state.grid_resolution),
            "n_steps": n_steps,
            "density_max": float(state.density.max()),
            "density_mean": float(state.density.mean()),
            "velocity_max": float(np.abs(state.velocity).max()),
            "cell_size": cell_size,
            "dt": dt,
        })
    except Exception as exc:
        return ToolResult(error=str(exc))


@_register(
    name="render_fluid_flip_step",
    description=(
        "Advance a FLIP (Fluid Implicit Particle) liquid simulation by one time step. "
        "Returns particle count and density statistics after stepping. "
        "Reference: Zhu & Bridson (2005)."
    ),
    schema={
        "type": "object",
        "properties": {
            "grid_nx": {"type": "integer", "default": 8},
            "grid_ny": {"type": "integer", "default": 8},
            "grid_nz": {"type": "integer", "default": 8},
            "cell_size": {"type": "number", "default": 0.1},
            "dt": {"type": "number", "default": 0.02},
            "n_steps": {"type": "integer", "default": 3},
            "gravity": {
                "type": "array",
                "items": {"type": "number"},
                "default": [0.0, 0.0, -9.81],
            },
            "emitter_center": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x,y,z] emitter centre (metres).",
            },
            "emitter_radius": {"type": "number", "default": 0.05},
            "emitter_rate": {"type": "integer", "default": 4},
        },
        "required": [],
    },
)
def render_fluid_flip_step(
    grid_nx: int = 8,
    grid_ny: int = 8,
    grid_nz: int = 8,
    cell_size: float = 0.1,
    dt: float = 0.02,
    n_steps: int = 3,
    gravity: Optional[List[float]] = None,
    emitter_center: Optional[List[float]] = None,
    emitter_radius: float = 0.05,
    emitter_rate: int = 4,
) -> ToolResult:
    """Advance a FLIP liquid simulation."""
    try:
        FluidSimState, make_fluid_state, step_flip, _ = _get_fluid()

        if gravity is None:
            gravity = [0.0, 0.0, -9.81]

        state = make_fluid_state(
            grid_nx, grid_ny, grid_nz,
            cell_size=cell_size,
            with_particles=True,
            n_particles=0,
        )

        center = emitter_center or [
            grid_nx * cell_size / 2,
            grid_ny * cell_size / 2,
            grid_nz * cell_size * 0.75,
        ]

        emitters = [{
            "center": center,
            "radius": emitter_radius,
            "velocity": [0.0, 0.0, -0.5],
            "rate": emitter_rate,
        }]

        for _ in range(n_steps):
            state = step_flip(
                state, dt,
                gravity=tuple(gravity),
                emitters=emitters,
            )

        n_parts = len(state.particles) if state.particles is not None else 0

        return ToolResult(content={
            "grid_resolution": list(state.grid_resolution),
            "n_steps": n_steps,
            "particle_count": n_parts,
            "density_max": float(state.density.max()),
            "density_mean": float(state.density.mean()),
            "velocity_max": float(np.abs(state.velocity).max()),
            "cell_size": cell_size,
            "dt": dt,
        })
    except Exception as exc:
        return ToolResult(error=str(exc))
