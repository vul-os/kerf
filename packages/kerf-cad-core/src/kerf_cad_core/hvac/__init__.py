"""
kerf_cad_core.hvac — HVAC duct sizing for the architect / MEP persona.

Distinct from kerf_cad_core.civil.hydraulics (water pipe networks).

Public API (re-exported for convenience):

    from kerf_cad_core.hvac import (
        cfm_from_sensible_load,
        round_duct_diameter,
        rect_equiv_diameter,
        duct_friction_loss,
        duct_fitting_loss,
        size_duct_equal_friction,
        size_duct_velocity_reduction,
        branch_static_pressure,
        fan_law_scale,
    )

References
----------
ASHRAE Handbook — Fundamentals (2021), Chapter 21: Duct Design
Huebscher (1948) ASHVE Trans. 54 — equivalent diameter formula
Darcy-Weisbach / Altshul friction factor for sheet-metal ducts

Author: imranparuk
"""

from kerf_cad_core.hvac.ducts import (
    cfm_from_sensible_load,
    round_duct_diameter,
    rect_equiv_diameter,
    duct_friction_loss,
    duct_fitting_loss,
    size_duct_equal_friction,
    size_duct_velocity_reduction,
    branch_static_pressure,
    fan_law_scale,
)

__all__ = [
    "cfm_from_sensible_load",
    "round_duct_diameter",
    "rect_equiv_diameter",
    "duct_friction_loss",
    "duct_fitting_loss",
    "size_duct_equal_friction",
    "size_duct_velocity_reduction",
    "branch_static_pressure",
    "fan_law_scale",
]
