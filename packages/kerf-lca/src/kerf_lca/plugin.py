"""
kerf-lca plugin entry-point.

Registers the lca_report LLM tool via ctx.tools.register.
No heavy deps — pure Python.
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_lca.tools.lca_report import lca_report_spec, run_lca_report
    ctx.tools.register("lca_report", lca_report_spec, run_lca_report)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="lca",
            version="0.1.0",
            provides=["lca.report"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "lca",
            "version": "0.1.0",
            "provides": ["lca.report"],
            "depends": [],
        }
