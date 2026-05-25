"""Kerf plugin registration for kerf-horology.

Registers 7 LLM tools via ctx.tools.register:
  - horology_train_calculator
  - horology_check_tooth_profile
  - horology_escapement_geometry
  - horology_mainspring_torque
  - horology_power_reserve
  - horology_balance_period
  - horology_isochronism
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx) -> None:
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""
    from kerf_horology.tools_spec import (
        horology_train_calculator_spec, run_horology_train_calculator,
        horology_check_tooth_profile_spec, run_horology_check_tooth_profile,
        horology_escapement_geometry_spec, run_horology_escapement_geometry,
        horology_mainspring_torque_spec, run_horology_mainspring_torque,
        horology_power_reserve_spec, run_horology_power_reserve,
        horology_balance_period_spec, run_horology_balance_period,
        horology_isochronism_spec, run_horology_isochronism,
    )

    ctx.tools.register("horology_train_calculator",
                       horology_train_calculator_spec, run_horology_train_calculator)
    ctx.tools.register("horology_check_tooth_profile",
                       horology_check_tooth_profile_spec, run_horology_check_tooth_profile)
    ctx.tools.register("horology_escapement_geometry",
                       horology_escapement_geometry_spec, run_horology_escapement_geometry)
    ctx.tools.register("horology_mainspring_torque",
                       horology_mainspring_torque_spec, run_horology_mainspring_torque)
    ctx.tools.register("horology_power_reserve",
                       horology_power_reserve_spec, run_horology_power_reserve)
    ctx.tools.register("horology_balance_period",
                       horology_balance_period_spec, run_horology_balance_period)
    ctx.tools.register("horology_isochronism",
                       horology_isochronism_spec, run_horology_isochronism)

    provides = [
        "horology.train_calculator",
        "horology.tooth_profile",
        "horology.escapement",
        "horology.mainspring",
        "horology.power_reserve",
        "horology.balance",
        "horology.isochronism",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="horology",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "horology",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
