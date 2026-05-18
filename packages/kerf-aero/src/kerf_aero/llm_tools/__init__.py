"""
kerf_aero.llm_tools — LLM-callable aerospace tool registry.

Exposes 12 aerospace simulation tools for LLM use:

  aero_airfoil_coords         — NACA/Selig airfoil coordinates
  aero_airfoil_polar          — CL/CD sweep (panel method)
  aero_vlm_wing               — Vortex Lattice Method full wing analysis
  aero_orbital_elements_to_state — Kepler → Cartesian state vector
  aero_hohmann_transfer       — Hohmann transfer ΔV calculation
  aero_lambert_solve          — Lambert's problem solver
  aero_rocket_dv              — Tsiolkovsky rocket equation
  aero_cea_lite               — Simplified chemical equilibrium analysis
  aero_atmosphere             — ISA 1976 atmosphere model
  aero_attitude_propagate     — ADCS attitude dynamics simulation
  aero_thermal_steady_state   — Lumped thermal network steady-state solver
  aero_material_lookup        — Aerospace materials database lookup

All tools return plain JSON-serializable dicts.
"""

from kerf_aero.llm_tools.aerospace_tools import (
    aero_airfoil_coords,
    aero_airfoil_polar,
    aero_vlm_wing,
    aero_orbital_elements_to_state,
    aero_hohmann_transfer,
    aero_lambert_solve,
    aero_rocket_dv,
    aero_cea_lite,
    aero_atmosphere,
    aero_attitude_propagate,
    aero_thermal_steady_state,
    aero_material_lookup,
    AEROSPACE_TOOLS,
)

__all__ = [
    "aero_airfoil_coords",
    "aero_airfoil_polar",
    "aero_vlm_wing",
    "aero_orbital_elements_to_state",
    "aero_hohmann_transfer",
    "aero_lambert_solve",
    "aero_rocket_dv",
    "aero_cea_lite",
    "aero_atmosphere",
    "aero_attitude_propagate",
    "aero_thermal_steady_state",
    "aero_material_lookup",
    "AEROSPACE_TOOLS",
]
