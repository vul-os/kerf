"""
kerf_cfd.combustion — non-premixed turbulent combustion models.

Implements the Magnussen-Hjertager (1976) Eddy Break-Up (EBU) reaction-rate
model for non-premixed combustion, suitable for design-exploration of
industrial burners, furnaces, and gas-turbine combustors.

HONEST FLAG: This module provides design-exploration-level accuracy.
It has NOT been validated against OpenFOAM or experimental benchmarks.
Do not use for safety-critical combustion design without independent validation.

References:
  Magnussen, B.F., Hjertager, B.H. (1976). "On mathematical modelling of
  turbulent combustion with special emphasis on soot formation and combustion."
  16th Symposium (International) on Combustion, The Combustion Institute,
  pp. 719–729.
"""

from kerf_cfd.combustion.reacting_flow import (
    CombustionMixture,
    FuelSpecies,
    magnussen_ebu_reaction_rate,
    step_combustion,
)

__all__ = [
    "CombustionMixture",
    "FuelSpecies",
    "magnussen_ebu_reaction_rate",
    "step_combustion",
]
