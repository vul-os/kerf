"""Stability and control derivatives for conventional fixed-wing aircraft.

Public API
----------
compute_derivatives(geom: AircraftGeom, flight: FlightCondition) -> StabilityDerivatives

Lifting-surface terms are computed via the shipped VLM (kerf_aero.vlm).
Fuselage and propeller contributions use DATCOM / Roskam closed-form methods.

Example
-------
>>> from kerf_aero.stability import (
...     compute_derivatives, AircraftGeom, WingGeom,
...     HTailGeom, VTailGeom, FuselageGeom, FlightCondition,
... )
>>> geom = AircraftGeom(
...     wing=WingGeom(span=11.0, root_chord=1.73, tip_chord=1.09),
...     htail=HTailGeom(span=3.96, root_chord=1.02, moment_arm=5.72),
...     vtail=VTailGeom(span=1.83, root_chord=1.37, moment_arm=5.14),
...     fuselage=FuselageGeom(length=8.28, max_width=1.07, max_height=1.52),
... )
>>> flight = FlightCondition(mach=0.12, altitude_m=600.0, alpha_deg=4.0)
>>> derivs = compute_derivatives(geom, flight)
>>> print(f"Cl_alpha = {derivs.CL_alpha_per_deg:.4f} /deg")
"""

from .derivatives import (
    compute_derivatives,
    AircraftGeom,
    WingGeom,
    HTailGeom,
    VTailGeom,
    FuselageGeom,
    FlightCondition,
    StabilityDerivatives,
)

__all__ = [
    "compute_derivatives",
    "AircraftGeom",
    "WingGeom",
    "HTailGeom",
    "VTailGeom",
    "FuselageGeom",
    "FlightCondition",
    "StabilityDerivatives",
]
