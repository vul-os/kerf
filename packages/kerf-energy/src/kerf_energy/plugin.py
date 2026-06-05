"""
kerf-energy plugin registration.

Wires energy / daylight / acoustic LLM tools into a Kerf plugin app.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""

    provides: list[str] = []
    _register_tools(ctx, provides)

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "energy",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="energy",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all energy LLM tools."""
    from kerf_energy.tools import (
        energy_rt60_spec,
        run_energy_rt60,
        energy_daylight_spec,
        run_energy_daylight,
        energy_solar_spec,
        run_energy_solar,
        energy_heat_load_spec,
        run_energy_heat_load,
    )
    from kerf_energy.compliance_tools import (
        energy_ashrae901_appendixg_report_spec,
        run_energy_ashrae901_appendixg_report,
        energy_leed_eap2_points_spec,
        run_energy_leed_eap2_points,
        energy_title24_compliance_spec,
        run_energy_title24_compliance,
    )

    _tools = [
        ("energy_rt60", energy_rt60_spec, run_energy_rt60, "energy.acoustic"),
        ("energy_daylight", energy_daylight_spec, run_energy_daylight, "energy.daylight"),
        ("energy_solar", energy_solar_spec, run_energy_solar, "energy.solar"),
        ("energy_heat_load", energy_heat_load_spec, run_energy_heat_load, "energy.heat-load"),
        # ASHRAE 90.1 Appendix G + LEED + Title 24 compliance tools
        (
            "energy_ashrae901_appendixg_report",
            energy_ashrae901_appendixg_report_spec,
            run_energy_ashrae901_appendixg_report,
            "energy.ashrae901-appendixg",
        ),
        (
            "energy_leed_eap2_points",
            energy_leed_eap2_points_spec,
            run_energy_leed_eap2_points,
            "energy.leed-eap2",
        ),
        (
            "energy_title24_compliance",
            energy_title24_compliance_spec,
            run_energy_title24_compliance,
            "energy.title24-compliance",
        ),
    ]

    for name, spec, handler, capability in _tools:
        try:
            ctx.tools.register(name, spec, handler)
            provides.append(capability)
        except Exception as exc:
            logger.warning("kerf-energy: failed to register %s: %s", name, exc)
