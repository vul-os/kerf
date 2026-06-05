"""
kerf_cfd.combustion — turbulent combustion + multi-species reacting-flow models.

Implements:
  1. Magnussen-Hjertager (1976) Eddy Break-Up (EBU) model — single-step
     non-premixed turbulent combustion.
  2. General multi-species finite-rate chemistry solver — N species, Arrhenius
     reactions, species conservation + energy release, 1-D plug-flow reactor.

HONEST FLAG: This module provides design-exploration-level accuracy.
It has NOT been validated against OpenFOAM or experimental benchmarks.
Do not use for safety-critical combustion design without independent validation.

References:
  Magnussen, B.F., Hjertager, B.H. (1976). 16th Symposium on Combustion.
  Westbrook, C.K., Dryer, F.L. (1981). PECS 7, 23-86.
  Williams, F.A. (1985). Combustion Theory. Benjamin Cummings.
  Law, C.K. (2006). Combustion Physics. Cambridge.
"""

from kerf_cfd.combustion.reacting_flow import (
    CombustionMixture,
    FuelSpecies,
    magnussen_ebu_reaction_rate,
    step_combustion,
)

from kerf_cfd.combustion.multispecies_reacting_flow import (
    Species,
    ArrheniusReaction,
    MultispeciesState,
    solve_reactor,
    adiabatic_flame_temperature,
    fuel_conversion,
    ch4_one_step,
    h2_one_step,
    generic_ab_to_c,
)

__all__ = [
    # EBU model
    "CombustionMixture",
    "FuelSpecies",
    "magnussen_ebu_reaction_rate",
    "step_combustion",
    # Multi-species finite-rate chemistry
    "Species",
    "ArrheniusReaction",
    "MultispeciesState",
    "solve_reactor",
    "adiabatic_flame_temperature",
    "fuel_conversion",
    "ch4_one_step",
    "h2_one_step",
    "generic_ab_to_c",
]
