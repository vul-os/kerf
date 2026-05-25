"""
kerf-optics plugin entry-point.

Registers:
  - LLM tools: optics_trace_ray, optics_lens_design
  - LLM tools: gaussian_beam_propagate, gaussian_beam_focus
  - LLM tools: optics_tolerancing, optics_mtf, optics_nonsequential_trace
  - Capability: optics.pop  (angular-spectrum + Fresnel/Fraunhofer scalar POP)
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
    )
    ctx.tools.register("optics_trace_ray", optics_trace_ray_spec, run_optics_trace_ray)
    ctx.tools.register("optics_lens_design", optics_lens_design_spec, run_optics_lens_design)
    ctx.tools.register("optics_pop_propagate", optics_pop_propagate_spec, run_optics_pop_propagate)
    ctx.tools.register("optics_tolerancing", optics_tolerancing_spec, run_optics_tolerancing)
    ctx.tools.register("optics_mtf", optics_mtf_spec, run_optics_mtf)

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

    provides = [
        "optics.paraxial", "optics.abcd", "optics.gaussian", "optics.pop",
        "optics.tolerancing", "optics.mtf", "optics.nonsequential",
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
