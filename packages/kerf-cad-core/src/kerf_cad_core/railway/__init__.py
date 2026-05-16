"""
kerf_cad_core.railway — railway track & vehicle engineering calculators.

Distinct from:
  civil/alignment  — road horizontal/vertical geometry
  dynamics/        — general structural dynamics
  geotech/         — soil mechanics & geotechnical analysis

Covers:
  • Curve geometry: minimum radius, equilibrium cant, applied/deficiency cant,
    cant gradient, transition (clothoid/cubic spiral) length, gauge widening
  • Vertical curves: crest/sag length
  • Wheel–rail contact: Hertzian semi-axes, max contact pressure
  • Train resistance: Davis formula (A + BV + CV²), grade & curve resistance
  • Tractive effort, adhesion limit, braking distance & deceleration
  • Rail bending: beam-on-elastic-foundation (Winkler), max stress/deflection,
    sleeper/ballast pressure
  • Rail thermal stress; CWR buckling risk flag

Public API (re-exported for convenience):

    from kerf_cad_core.railway import (
        equilibrium_cant,
        applied_cant,
        cant_deficiency,
        cant_gradient_check,
        transition_length,
        gauge_widening,
        vertical_curve_length,
        hertzian_contact,
        davis_resistance,
        tractive_effort,
        braking_distance,
        rail_bending,
        rail_thermal_stress,
    )

References
----------
UIC 703-2:2011 — Track alignment design parameters
EN 13803-1:2010 — Railway applications — Track alignment design parameters
Hay, W.W. (1982) "Railroad Engineering", 2nd ed.
Esveld, C. (2001) "Modern Railway Track", 2nd ed.
Timoshenko, S.P. (1976) "Strength of Materials, Part II"
Johnson, K.L. (1985) "Contact Mechanics"

Author: imranparuk
"""

from kerf_cad_core.railway.track import (
    equilibrium_cant,
    applied_cant,
    cant_deficiency,
    cant_gradient_check,
    transition_length,
    gauge_widening,
    vertical_curve_length,
    hertzian_contact,
    davis_resistance,
    tractive_effort,
    braking_distance,
    rail_bending,
    rail_thermal_stress,
)

__all__ = [
    "equilibrium_cant",
    "applied_cant",
    "cant_deficiency",
    "cant_gradient_check",
    "transition_length",
    "gauge_widening",
    "vertical_curve_length",
    "hertzian_contact",
    "davis_resistance",
    "tractive_effort",
    "braking_distance",
    "rail_bending",
    "rail_thermal_stress",
]
