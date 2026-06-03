"""
Non-premixed turbulent combustion — Magnussen-Hjertager Eddy Break-Up model.

Overview
--------
Implements single-step non-premixed combustion for turbulent reacting flows
using the Eddy Break-Up (EBU) model of Magnussen & Hjertager (1976).

Physics summary
---------------
In turbulent non-premixed combustion the reaction rate is controlled by the
rate at which turbulent eddies mix fuel and oxidizer.  The EBU model captures
this mixing-limited kinetics through the local turbulent time-scale ε/k:

    ω̇ = A · ρ · (ε/k) · min(Y_fuel,  Y_ox/s,  B · Y_pr / (1 + s))

where:
  A   = empirical mixing constant (≈ 4.0)
  B   = products constant (≈ 0.5)
  s   = stoichiometric oxygen-to-fuel mass ratio  (= 1/AFR)
  ρ   = local mixture density [kg/m³]   (taken as 1.2 kg/m³ if not provided)
  ε/k = turbulent dissipation / kinetic energy  [1/s]

Energy release per cell per unit time [K/s] follows from:
    dT/dt = ω̇ · LHV / (ρ · c_p)

Species update (single-step irreversible):
    Fuel + s·Oxidizer → (1+s)·Products     [mass basis]

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM or experimental data.  Do not use for safety-critical design.

References
----------
Magnussen, B.F., Hjertager, B.H. (1976). "On mathematical modelling of
turbulent combustion with special emphasis on soot formation and combustion."
16th Symposium (International) on Combustion, The Combustion Institute,
pp. 719–729.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FuelSpecies:
    """Properties of a gaseous fuel species for EBU combustion modelling.

    Attributes
    ----------
    name:
        Short chemical name, e.g. 'CH4', 'C8H18', 'H2'.
    molar_mass_kg_per_mol:
        Molar mass [kg/mol], e.g. 0.016 for CH4.
    LHV_J_per_kg:
        Lower heating value [J/kg], e.g. 50.05e6 for CH4.
    stoichiometric_AFR:
        Stoichiometric air-fuel ratio (mass basis), e.g. ~17.2 for CH4.
    """
    name: str
    molar_mass_kg_per_mol: float
    LHV_J_per_kg: float
    stoichiometric_AFR: float


@dataclass
class CombustionMixture:
    """Cell-centred combustion mixture state.

    All arrays have shape (Ncells,).

    Attributes
    ----------
    fuel:
        FuelSpecies describing the fuel being burned.
    Y_fuel:
        Mass fraction of fuel [-].
    Y_oxidizer:
        Mass fraction of oxidizer (O2 or air) [-].
    Y_products:
        Mass fraction of combustion products (CO2 + H2O) [-].
    temperature:
        Static temperature [K].
    density:
        Mixture density [kg/m³].  Defaults to 1.2 kg/m³ (air at std conditions).
    cp:
        Specific heat capacity [J/(kg·K)].  Defaults to 1005 J/(kg·K).
    """
    fuel: FuelSpecies
    Y_fuel: np.ndarray
    Y_oxidizer: np.ndarray
    Y_products: np.ndarray
    temperature: np.ndarray
    density: np.ndarray = field(default=None)   # type: ignore[assignment]
    cp: float = 1005.0

    def __post_init__(self):
        n = len(self.Y_fuel)
        if self.density is None:
            # Default: dry air at STP
            object.__setattr__(self, "density", np.full(n, 1.2))
        else:
            self.density = np.asarray(self.density, dtype=float)
        self.Y_fuel = np.asarray(self.Y_fuel, dtype=float)
        self.Y_oxidizer = np.asarray(self.Y_oxidizer, dtype=float)
        self.Y_products = np.asarray(self.Y_products, dtype=float)
        self.temperature = np.asarray(self.temperature, dtype=float)


# ---------------------------------------------------------------------------
# EBU reaction rate
# ---------------------------------------------------------------------------

def magnussen_ebu_reaction_rate(
    mix: CombustionMixture,
    epsilon_over_k: np.ndarray,
    A_ebu: float = 4.0,
    B_ebu: float = 0.5,
) -> np.ndarray:
    """Magnussen-Hjertager (1976) Eddy Break-Up reaction rate.

    Computes the fuel consumption rate [kg_fuel / (m³·s)] per cell:

        ω̇ = A · ρ · (ε/k) · min(Y_f,  Y_ox/s,  B · Y_pr / (1+s))

    where s = 1 / stoichiometric_AFR  (oxygen mass per unit fuel mass).

    Parameters
    ----------
    mix:
        Current combustion mixture state.
    epsilon_over_k:
        Turbulent time-scale ε/k [1/s] per cell.  Typically sourced from
        the k-ε or k-ω-SST turbulence model.
    A_ebu:
        Magnussen mixing constant (default 4.0, from Magnussen 1976).
    B_ebu:
        Products constant (default 0.5, from Magnussen 1976).

    Returns
    -------
    omega_dot : np.ndarray, shape (Ncells,)
        Fuel consumption rate [kg_fuel / (m³·s)].  Always >= 0.

    References
    ----------
    Magnussen, B.F., Hjertager, B.H. (1976). 16th Symposium (International)
    on Combustion, pp. 719–729.
    """
    epsilon_over_k = np.asarray(epsilon_over_k, dtype=float)

    # Stoichiometric oxidizer-to-fuel mass ratio
    # AFR = m_air / m_fuel   →   s = m_ox / m_fuel = 1 / AFR
    # (here we treat oxidizer as air for simplicity)
    s = 1.0 / mix.fuel.stoichiometric_AFR  # [-]

    rho = mix.density
    Y_f = np.clip(mix.Y_fuel, 0.0, 1.0)
    Y_ox = np.clip(mix.Y_oxidizer, 0.0, 1.0)
    Y_pr = np.clip(mix.Y_products, 0.0, 1.0)

    # Three limiting terms (each >= 0)
    term_fuel = Y_f
    term_ox = Y_ox / s
    term_pr = B_ebu * Y_pr / (1.0 + s)

    # EBU: rate is controlled by the *smallest* of the three
    omega_dot = A_ebu * rho * epsilon_over_k * np.minimum(
        term_fuel, np.minimum(term_ox, term_pr)
    )

    # Physical constraint: rate cannot be negative
    return np.maximum(omega_dot, 0.0)


# ---------------------------------------------------------------------------
# Time-stepping
# ---------------------------------------------------------------------------

def step_combustion(
    mix: CombustionMixture,
    fuel: FuelSpecies,
    eps_k: np.ndarray,
    dt: float,
) -> CombustionMixture:
    """Advance species mass fractions and temperature by one time step dt.

    Uses an explicit (Euler) update:

        ΔY_fuel     = -ω̇ · dt / ρ
        ΔY_oxidizer = -ω̇ · s  · dt / ρ
        ΔY_products = +ω̇ · (1+s) · dt / ρ
        ΔT          = +ω̇ · LHV · dt / (ρ · c_p)

    Mass fractions are clipped to [0, 1] after update and re-normalised so
    that their sum remains 1.

    Parameters
    ----------
    mix:
        Current mixture state.
    fuel:
        Fuel species (must match mix.fuel).
    eps_k:
        Turbulent time-scale ε/k [1/s] per cell.
    dt:
        Time step [s].

    Returns
    -------
    CombustionMixture
        Updated mixture state (new object; input is not mutated).

    References
    ----------
    Magnussen, B.F., Hjertager, B.H. (1976). 16th Symposium (International)
    on Combustion, pp. 719–729.
    """
    eps_k = np.asarray(eps_k, dtype=float)
    omega_dot = magnussen_ebu_reaction_rate(mix, eps_k)

    rho = mix.density
    s = 1.0 / fuel.stoichiometric_AFR

    # Species changes [1/s] per unit density → integrate over dt
    dY_fuel = -omega_dot * dt / rho
    dY_ox = -omega_dot * s * dt / rho
    dY_pr = omega_dot * (1.0 + s) * dt / rho
    dT = omega_dot * fuel.LHV_J_per_kg * dt / (rho * mix.cp)

    Y_f_new = np.clip(mix.Y_fuel + dY_fuel, 0.0, 1.0)
    Y_ox_new = np.clip(mix.Y_oxidizer + dY_ox, 0.0, 1.0)
    Y_pr_new = np.clip(mix.Y_products + dY_pr, 0.0, 1.0)
    T_new = mix.temperature + dT

    # Note: we do NOT renormalise the three tracked species against each other.
    # The remainder (1 - Y_f - Y_ox - Y_pr) is implicitly the inert diluent
    # (e.g. N2).  Renormalising only the reactive species would artificially
    # inflate Y_fuel as the oxidizer is consumed.

    return CombustionMixture(
        fuel=mix.fuel,
        Y_fuel=Y_f_new,
        Y_oxidizer=Y_ox_new,
        Y_products=Y_pr_new,
        temperature=T_new,
        density=mix.density.copy(),
        cp=mix.cp,
    )
