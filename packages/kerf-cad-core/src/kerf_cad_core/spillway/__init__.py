"""
kerf_cad_core.spillway — Dam & spillway hydraulics.

Distinct from:
  channel/     — open-channel flow (Manning, GVF, hydraulic jump in channels)
  hydrology/   — rainfall-runoff (rational method, SCS)
  geotech/     — soil & foundation stability

This module covers:
  - Ogee/WES spillway discharge with head-correction coefficient C, end-contraction,
    approach-velocity, and submergence corrections  (Q = C·L·H^1.5)
  - Crest profile coordinates (WES standard shape)
  - Gated/orifice spillway discharge
  - Chute velocity and terminal (uniform-flow) velocity in chute channel
  - Stilling-basin hydraulic jump design: USBR Type I–IV basin selection,
    sequent depth, basin length, end-sill height, tailwater rating match
  - Energy dissipation and required apron length
  - Scour depth downstream (Lacey / Neill power-law)
  - Reservoir flood routing (modified-Puls / level-pool) given inflow
    hydrograph and storage-discharge curve
  - Dam freeboard: wind setup + wave runup (USBR / Corps of Engineers)
  - Gravity-dam stability quick-check: overturning, sliding, uplift,
    resultant in middle-third rule

Public API (re-exported for convenience):

    from kerf_cad_core.spillway import (
        ogee_discharge,
        ogee_crest_profile,
        orifice_discharge,
        chute_velocity,
        stilling_basin,
        energy_dissipation,
        scour_depth,
        flood_routing_puls,
        dam_freeboard,
        gravity_dam_stability,
    )

References
----------
USBR (1987) Design of Small Canal Structures.
USBR (1977) Design of Small Dams, 3rd ed.
Chaudhry, M.H. (2008) Open-Channel Hydraulics, 2nd ed.
US Army Corps of Engineers EM 1110-2-1601 (1994).
Linsley & Franzini (1979) Water Resources Engineering, 3rd ed.

Author: imranparuk
"""

from kerf_cad_core.spillway.design import (
    ogee_discharge,
    ogee_crest_profile,
    orifice_discharge,
    chute_velocity,
    stilling_basin,
    energy_dissipation,
    scour_depth,
    flood_routing_puls,
    dam_freeboard,
    gravity_dam_stability,
)

__all__ = [
    "ogee_discharge",
    "ogee_crest_profile",
    "orifice_discharge",
    "chute_velocity",
    "stilling_basin",
    "energy_dissipation",
    "scour_depth",
    "flood_routing_puls",
    "dam_freeboard",
    "gravity_dam_stability",
]
