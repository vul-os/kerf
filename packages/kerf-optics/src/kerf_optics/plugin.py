"""
kerf-optics plugin entry-point.

Registers:
  - LLM tools: optics_trace_ray, optics_lens_design
  - LLM tools: gaussian_beam_propagate, gaussian_beam_focus
  - LLM tools: optics_tolerancing, optics_mtf, optics_nonsequential_trace
  - LLM tools: optics_lighting_simulation, optics_daylighting_simulation
  - Capability: optics.pop  (angular-spectrum + Fresnel/Fraunhofer scalar POP)
  - Capability: optics.daylighting  (CIE S 011 sky models, Spencer sun position)
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_optics.tools import (
        optics_trace_ray_spec, run_optics_trace_ray,
        optics_lens_design_spec, run_optics_lens_design,
        optics_pop_propagate_spec, run_optics_pop_propagate,
        optics_tolerancing_spec, run_optics_tolerancing,
        optics_mtf_spec, run_optics_mtf,
        optics_sequential_trace_spec, run_optics_sequential_trace,
        optics_nest_tolerancing_spec, run_optics_nest_tolerancing,
        optics_lighting_simulation_spec, run_optics_lighting_simulation,
        optics_daylighting_simulation_spec, run_optics_daylighting_simulation,
    )
    ctx.tools.register("optics_trace_ray", optics_trace_ray_spec, run_optics_trace_ray)
    ctx.tools.register("optics_lens_design", optics_lens_design_spec, run_optics_lens_design)
    ctx.tools.register("optics_pop_propagate", optics_pop_propagate_spec, run_optics_pop_propagate)
    ctx.tools.register("optics_tolerancing", optics_tolerancing_spec, run_optics_tolerancing)
    ctx.tools.register("optics_mtf", optics_mtf_spec, run_optics_mtf)
    ctx.tools.register(
        "optics_sequential_trace",
        optics_sequential_trace_spec,
        run_optics_sequential_trace,
    )
    ctx.tools.register(
        "optics_nest_tolerancing",
        optics_nest_tolerancing_spec,
        run_optics_nest_tolerancing,
    )
    ctx.tools.register(
        "optics_lighting_simulation",
        optics_lighting_simulation_spec,
        run_optics_lighting_simulation,
    )
    ctx.tools.register(
        "optics_daylighting_simulation",
        optics_daylighting_simulation_spec,
        run_optics_daylighting_simulation,
    )

    from kerf_optics.gaussian_tools import (
        gaussian_beam_propagate_spec, run_gaussian_beam_propagate,
        gaussian_beam_focus_spec, run_gaussian_beam_focus,
    )
    ctx.tools.register(
        "gaussian_beam_propagate", gaussian_beam_propagate_spec, run_gaussian_beam_propagate
    )
    ctx.tools.register(
        "gaussian_beam_focus", gaussian_beam_focus_spec, run_gaussian_beam_focus
    )

    from kerf_optics.nonsequential import (
        optics_nonsequential_trace_spec, run_optics_nonsequential_trace,
    )
    ctx.tools.register(
        "optics_nonsequential_trace",
        optics_nonsequential_trace_spec,
        run_optics_nonsequential_trace,
    )

    from kerf_optics.zernike_tools import (
        optics_fit_zernike_spec, run_optics_fit_zernike,
        optics_aberration_breakdown_spec, run_optics_aberration_breakdown,
    )
    ctx.tools.register(
        "optics_fit_zernike",
        optics_fit_zernike_spec,
        run_optics_fit_zernike,
    )
    ctx.tools.register(
        "optics_aberration_breakdown",
        optics_aberration_breakdown_spec,
        run_optics_aberration_breakdown,
    )

    provides = [
        "optics.paraxial", "optics.abcd", "optics.gaussian", "optics.pop",
        "optics.tolerancing", "optics.tolerancing.nest", "optics.mtf",
        "optics.nonsequential", "optics.zernike",
        "optics.sequential_trace", "optics.lighting", "optics.daylighting",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="optics",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "optics",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
