"""
kerf_cfd.wind_engineering — building wind loads and bluff-body aerodynamics.

Implements:
  - ASCE 7-22 Exposure Category B/C/D power-law wind profiles
  - Building wind pressure coefficients (windward/leeward/side/roof)
  - Drag force, base shear, and overturning moment
  - Vortex-shedding frequency (Bearman 1984)
  - Den Hartog galloping criterion

HONEST FLAG: Simplified ASCE 7-22 §26.6 Cp approach.  Tall buildings
(h > 60 m) require full wind-tunnel testing or validated CFD (LES/DES).
Do not use for structural design without qualified peer review.

References
----------
ASCE 7-22, Chapters 26–31 (Wind Loads).

Bearman, P.W. (1984). "Vortex Shedding from Oscillating Bluff Bodies."
Ann. Rev. Fluid Mech. 16, 195–222.

Holmes, J.D. (2018). "Wind Loading of Structures," 3rd ed. CRC Press.
"""

from kerf_cfd.wind_engineering.wind_tunnel import (
    BuildingGeometry,
    WindPressureReport,
    WindProfile,
    compute_wind_load_aerodynamic,
    galloping_critical_velocity,
    vortex_shedding_frequency,
)

__all__ = [
    "WindProfile",
    "BuildingGeometry",
    "WindPressureReport",
    "compute_wind_load_aerodynamic",
    "vortex_shedding_frequency",
    "galloping_critical_velocity",
]
