"""
kerf-civil plugin entry-point.

Registers:
  - LLM tools: civil_crs_transform, civil_tin_build
"""

from __future__ import annotations

from fastapi import FastAPI

# Check for optional pyproj
_PYPROJ_AVAILABLE = False
try:
    import pyproj  # noqa: F401
    _PYPROJ_AVAILABLE = True
except ImportError:
    pass


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_civil.tools import (
        civil_crs_transform_spec, run_civil_crs_transform,
        civil_tin_build_spec, run_civil_tin_build,
    )
    ctx.tools.register("civil_crs_transform", civil_crs_transform_spec, run_civil_crs_transform)
    ctx.tools.register("civil_tin_build", civil_tin_build_spec, run_civil_tin_build)

    provides = ["civil.tin", "civil.crs"]
    if _PYPROJ_AVAILABLE:
        provides.append("civil.crs.full")  # full EPSG library via pyproj

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="civil",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "civil",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
