"""
kerf_cfd.plasma — Low-temperature plasma drift-diffusion solver.

Implements a 1-D / 2-D DC glow-discharge model between parallel electrodes:

  • Electron and ion continuity with drift (μE) + diffusion (D∇n) +
    Townsend ionization source S = α |μ_e E| n_e
  • Poisson equation for self-consistent electric field:
      ∇·(ε E) = q (n_i − n_e)
  • Simple electron temperature / local-field approximation (reduced field E/N)

References
----------
Surendra, M., Graves, D.B. (1991). "Electron acoustic waves in capacitively
coupled, low-pressure rf discharges". IEEE Trans. Plasma Sci. 19, 144–157.

Hagelaar, G.J.M., Pitchford, L.C. (2005). "Solving the Boltzmann equation to
obtain electron transport coefficients and rate coefficients for fluid models".
Plasma Sources Sci. Technol. 14, 722–733.

Townsend, J.S. (1910). "The theory of ionization of gases by collision".
Phil. Mag. 20, 802–808. (1st Townsend coefficient)

Paschen, F. (1889). "Ueber die zum Funkenübergang in Luft, Wasserstoff und
Kohlensäure bei verschiedenen Drucken erforderliche Potentialdifferenz".
Ann. Phys. 273, 69–96.

Lieberman, M.A., Lichtenberg, A.J. (2005). Principles of Plasma Discharges
and Materials Processing. 2nd ed. Wiley.
"""

from kerf_cfd.plasma.drift_diffusion import (
    PlasmaGas,
    PlasmaDischargeSolver,
    run_discharge,
    paschen_voltage,
)

__all__ = [
    "PlasmaGas",
    "PlasmaDischargeSolver",
    "run_discharge",
    "paschen_voltage",
]
