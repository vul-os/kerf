"""
kerf_cad_core.turbo — turbomachinery blade/stage design.

Blade-level velocity-triangle design for axial and centrifugal
turbomachinery stages.  Distinct from pumpsys (system-curve / pump
selection) and aero (external aerodynamics).

Public API (re-exported for convenience):

    from kerf_cad_core.turbo import (
        euler_work,
        velocity_triangles_axial,
        velocity_triangles_centrifugal,
        dimensionless_groups,
        specific_speed_diameter,
        cordier_optimum,
        degree_of_reaction,
        axial_stage,
        centrifugal_impeller,
        fan_affinity,
        stage_efficiency,
        surge_choke_margin,
    )

References
----------
Dixon, S.L. & Hall, C.A. "Fluid Mechanics and Thermodynamics of
  Turbomachinery", 7th ed., Butterworth-Heinemann (2014).
Saravanamuttoo, H.I.H. et al. "Gas Turbine Theory", 7th ed.,
  Pearson (2017).
Cumpsty, N.A. "Compressor Aerodynamics", 2nd ed., Krieger (2004).

Author: imranparuk
"""

from kerf_cad_core.turbo.stage import (
    euler_work,
    velocity_triangles_axial,
    velocity_triangles_centrifugal,
    dimensionless_groups,
    specific_speed_diameter,
    cordier_optimum,
    degree_of_reaction,
    axial_stage,
    centrifugal_impeller,
    fan_affinity,
    stage_efficiency,
    surge_choke_margin,
)

__all__ = [
    "euler_work",
    "velocity_triangles_axial",
    "velocity_triangles_centrifugal",
    "dimensionless_groups",
    "specific_speed_diameter",
    "cordier_optimum",
    "degree_of_reaction",
    "axial_stage",
    "centrifugal_impeller",
    "fan_affinity",
    "stage_efficiency",
    "surge_choke_margin",
]
