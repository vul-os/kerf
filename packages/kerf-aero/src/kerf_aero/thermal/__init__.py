"""
Spacecraft thermal control analysis.

Sub-modules
-----------
network      — lumped thermal-resistance network (nodes, links, steady-state
               and transient solvers)
view_factors — analytic view-factor formulas (Howell catalogue)
solar_flux   — solar irradiance at arbitrary heliocentric distance,
               eclipse geometry, absorbed flux
coatings     — spacecraft surface-coating catalogue (α, ε pairs)

Quick-start
-----------
>>> from kerf_aero.thermal.network import ThermalNetwork, Node, RadiativeLink
>>> from kerf_aero.thermal.solar_flux import solar_flux_at_distance
>>> from kerf_aero.thermal.view_factors import parallel_rectangles_equal
>>> from kerf_aero.thermal.coatings import COATINGS
"""

from kerf_aero.thermal import coatings, network, solar_flux, view_factors

__all__ = ["coatings", "network", "solar_flux", "view_factors"]
