"""
kerf-lca plugin entry-point.

Registers the following LLM tools via ctx.tools.register:
  - lca_report                  — embodied-carbon BOM sweep (ICE v3 factors)
  - lifecycle_phases             — full ISO 14040/44 multi-phase lifecycle GWP
  - multi_impact                 — multi-impact characterisation (AP, EP, HTP, water, PM2.5)
  - lca_lookup_material          — resolve material name → ICE v3 entry (embodied carbon DB)
  - lca_compute_embodied_carbon  — mass × ICE v3 factor → kg CO2-eq (cradle-to-gate + EoL)

Data: ICE v3.0 (Hammond & Jones, University of Bath, 2019).
NOT Ecoinvent (license-restricted).
No heavy deps — pure Python.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    _tool_modules = [
        ("kerf_lca.tools.lca_report",        "lca_report_spec",                   "run_lca_report"),
        ("kerf_lca.tools.lifecycle_phases",   "lifecycle_phases_spec",             "run_lifecycle_phases"),
        ("kerf_lca.tools.multi_impact",       "multi_impact_spec",                 "run_multi_impact"),
        ("kerf_lca.tools.embodied_carbon",    "lca_lookup_material_spec",          "run_lca_lookup_material"),
        ("kerf_lca.tools.embodied_carbon",    "lca_compute_embodied_carbon_spec",  "run_lca_compute_embodied_carbon"),
    ]

    for module_path, spec_name, handler_name in _tool_modules:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            spec = getattr(mod, spec_name)
            handler = getattr(mod, handler_name)
            ctx.tools.register(spec.name, spec, handler)
        except Exception as exc:
            logger.warning("kerf-lca: failed to register %s: %s", spec_name, exc)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="lca",
            version="0.2.0",
            provides=[
                "lca.report", "lca.lifecycle", "lca.multi_impact",
                "lca.lookup_material", "lca.compute_embodied_carbon",
            ],
            depends=[],
        )
    except ImportError:
        return {
            "name": "lca",
            "version": "0.2.0",
            "provides": [
                "lca.report", "lca.lifecycle", "lca.multi_impact",
                "lca.lookup_material", "lca.compute_embodied_carbon",
            ],
            "depends": [],
        }
