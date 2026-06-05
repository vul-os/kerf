"""
General multi-species reacting-flow solver with finite-rate Arrhenius chemistry.

Overview
--------
Solves coupled species conservation equations for N species in a 1-D
plug-flow reactor or coupled to an existing flow field:

    ∂(ρYk)/∂t + ∇·(ρu Yk) = ∇·(ρ Dk ∇Yk) + ωk

where:
  Yk  = mass fraction of species k  [-]
  ρ   = mixture density              [kg/m³]
  u   = flow velocity (1-D: scalar)  [m/s]
  Dk  = species diffusivity          [m²/s]
  ωk  = net mass production rate of k  [kg/(m³·s)]

Reaction kinetics — Arrhenius finite-rate
-----------------------------------------
Each reaction r has the form:

    Σ ν'kr · Mk  →  Σ ν''kr · Mk

Forward rate coefficient:

    kf,r = Ar · T^br · exp(−Ear / R T)

Molar concentration production rate for species k:

    q̇k = Σr (ν''kr − ν'kr) · kf,r · ∏j [Xj]^ν'jr

Mass production rate:

    ωk = q̇k · Wk

Mass-fraction closure (ΣYk = 1) is enforced after each step by
normalising; the "bath gas" (inert) species absorbs the residual.

Energy release coupling:

    ρ cp dT/dt = − Σk ωk · hf,k

where hf,k is the species formation enthalpy [J/kg].

References
----------
Williams, F.A. (1985). *Combustion Theory*, 2nd ed. Benjamin Cummings.
Law, C.K. (2006). *Combustion Physics*. Cambridge University Press.
Turns, S.R. (2011). *An Introduction to Combustion*, 3rd ed. McGraw-Hill.
NIST/JANAF thermochemical tables (Chase, 1998).
Westbrook, C.K., Dryer, F.L. (1981). Prog. Energy Combust. Sci. 7, 23–86.

HONEST FLAG: Design-exploration grade.  Validated against analytic batch-
reactor solutions and adiabatic flame temperature tables; not yet coupled
to a turbulence model or OpenFOAM.  Do not use for safety-critical design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

# Universal gas constant [J/(mol·K)]
R_UNIV: float = 8.31446  # NIST 2018 CODATA


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Species:
    """Properties of a chemical species.

    Attributes
    ----------
    name:
        Chemical name / formula (e.g. 'CH4', 'O2', 'CO2', 'H2O', 'N2').
    molar_mass:
        Molar mass [kg/mol].
    hf:
        Standard heat of formation at 298.15 K [J/kg].
        Positive = endothermic formation.  Combustion products have large
        negative values (CO2: −8943 kJ/mol → −203 kJ/kg; H2O: −242 kJ/mol).
    diffusivity:
        Mass diffusivity in the mixture [m²/s].  Default 2.5e-5 (air-like).
    cp:
        Specific heat capacity [J/(kg·K)].  Used for simplified energy eq.
    """
    name: str
    molar_mass: float          # [kg/mol]
    hf: float                  # [J/kg]  heat of formation (mass basis)
    diffusivity: float = 2.5e-5  # [m²/s]
    cp: float = 1100.0         # [J/(kg·K)]


@dataclass
class ArrheniusReaction:
    """One elementary or global Arrhenius reaction.

    Forward rate:  kf = A · T^b · exp(−Ea / (R·T))

    Stoichiometry is expressed as *molar* coefficients:
        reactant_stoich[k] = ν'k  (stoichiometric coefficient of species k on reactant side)
        product_stoich[k]  = ν''k

    Reaction orders (default = ν'k, i.e. elementary) can be overridden via
    `reactant_orders` for global / fitted mechanisms.

    Attributes
    ----------
    A:
        Pre-exponential factor [units depend on reaction order; consistent with
        concentrations in mol/m³].
    b:
        Temperature exponent [-].
    Ea:
        Activation energy [J/mol].
    reactant_stoich:
        Dict mapping species name → stoichiometric coefficient on LHS.
    product_stoich:
        Dict mapping species name → stoichiometric coefficient on RHS.
    reactant_orders:
        Optional dict mapping species name → reaction order on LHS.
        If None, elementary kinetics assumed (order = stoich coeff).
    """
    A: float
    b: float
    Ea: float                           # [J/mol]
    reactant_stoich: Dict[str, float]
    product_stoich: Dict[str, float]
    reactant_orders: Optional[Dict[str, float]] = None

    def rate_coefficient(self, T: np.ndarray) -> np.ndarray:
        """Compute Arrhenius rate coefficient kf(T) [mol^(1−n)·m^(3n−3)·s^−1].

        Parameters
        ----------
        T:
            Temperature array [K].

        Returns
        -------
        kf : np.ndarray, same shape as T.
        """
        T = np.asarray(T, dtype=float)
        return self.A * (T ** self.b) * np.exp(-self.Ea / (R_UNIV * T))


@dataclass
class MultispeciesState:
    """State of an N-species reacting mixture on a 1-D or cell-array grid.

    Attributes
    ----------
    species:
        Ordered list of Species objects.  Determines column order in Y.
    Y:
        Mass-fraction array, shape (N_cells, N_species).
        Each row sums to 1 (closure enforced after each step).
    temperature:
        Temperature array [K], shape (N_cells,).
    density:
        Mixture density [kg/m³], shape (N_cells,).
    pressure:
        Mixture pressure [Pa], shape (N_cells,) or scalar.
    """
    species: List[Species]
    Y: np.ndarray          # (N_cells, N_species)
    temperature: np.ndarray  # (N_cells,)
    density: np.ndarray    # (N_cells,)
    pressure: float = 101325.0

    @property
    def n_cells(self) -> int:
        return self.Y.shape[0]

    @property
    def n_species(self) -> int:
        return len(self.species)

    def species_index(self, name: str) -> int:
        for i, sp in enumerate(self.species):
            if sp.name == name:
                return i
        raise KeyError(f"Species '{name}' not found in mechanism")

    def mole_fractions(self) -> np.ndarray:
        """Compute mole fractions X from mass fractions Y.

        X_k = (Y_k / W_k) / Σ_j (Y_j / W_j)
        """
        W = np.array([sp.molar_mass for sp in self.species])  # (N_species,)
        inv_W = 1.0 / W
        n_k = self.Y * inv_W[np.newaxis, :]   # (N_cells, N_species)
        n_tot = n_k.sum(axis=1, keepdims=True)
        # Avoid division by zero
        n_tot = np.where(n_tot < 1e-30, 1e-30, n_tot)
        return n_k / n_tot

    def molar_concentrations(self) -> np.ndarray:
        """[X_k] = ρ Y_k / W_k  [mol/m³]."""
        W = np.array([sp.molar_mass for sp in self.species])
        return self.density[:, np.newaxis] * self.Y / W[np.newaxis, :]

    def mean_cp(self) -> np.ndarray:
        """Mass-averaged specific heat [J/(kg·K)], shape (N_cells,)."""
        cp_arr = np.array([sp.cp for sp in self.species])
        return self.Y @ cp_arr  # (N_cells,)

    def enforce_closure(self, bath_idx: int = -1) -> None:
        """Ensure ΣYk = 1 by adjusting the bath-gas species (last by default).

        Clips all species to [0, 1], then assigns residual to bath_idx.
        """
        self.Y = np.clip(self.Y, 0.0, None)
        row_sum = self.Y.sum(axis=1)
        # Normalise rows that exceed 1.0
        over = row_sum > 1.0
        if np.any(over):
            self.Y[over] = self.Y[over] / row_sum[over, np.newaxis]
        # Re-compute after clipping
        row_sum = self.Y.sum(axis=1)
        residual = 1.0 - row_sum
        self.Y[:, bath_idx] = np.clip(self.Y[:, bath_idx] + residual, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Reaction rate evaluation
# ---------------------------------------------------------------------------

def compute_species_production_rates(
    state: MultispeciesState,
    reactions: List[ArrheniusReaction],
) -> np.ndarray:
    """Compute net species mass production rates ωk [kg/(m³·s)].

    For each reaction r:
        q̇r = kf,r(T) · ∏k [Xk]^α'kr

    where [Xk] = ρ Yk / Wk  [mol/m³] and α'kr is the reaction order.

    Net molar production of species k:
        q̇k = Σr (ν''kr − ν'kr) · q̇r    [mol/(m³·s)]

    Mass production:
        ωk = q̇k · Wk                       [kg/(m³·s)]

    Parameters
    ----------
    state:
        Current multi-species mixture state.
    reactions:
        List of Arrhenius reactions.

    Returns
    -------
    omega : np.ndarray, shape (N_cells, N_species)
        Net mass production rate per species per cell [kg/(m³·s)].
    """
    n_cells = state.n_cells
    n_sp = state.n_species
    T = state.temperature
    conc = state.molar_concentrations()   # (N_cells, N_species) [mol/m³]
    W = np.array([sp.molar_mass for sp in state.species])  # (N_species,)

    # Build species name → index map
    sp_idx = {sp.name: i for i, sp in enumerate(state.species)}

    omega_molar = np.zeros((n_cells, n_sp))  # [mol/(m³·s)]

    for rxn in reactions:
        kf = rxn.rate_coefficient(T)   # (N_cells,)

        # Rate of progress variable q̇r [mol/(m³·s)]
        q = kf.copy()
        orders = rxn.reactant_orders or rxn.reactant_stoich
        for sname, alpha in orders.items():
            if sname not in sp_idx:
                continue
            ki = sp_idx[sname]
            c_k = np.maximum(conc[:, ki], 0.0)
            q = q * (c_k ** alpha)

        # Accumulate net production
        # Reactants (consumed): stoich coefficient is negative contribution
        for sname, nu in rxn.reactant_stoich.items():
            if sname not in sp_idx:
                continue
            ki = sp_idx[sname]
            omega_molar[:, ki] -= nu * q

        # Products (formed): positive contribution
        for sname, nu in rxn.product_stoich.items():
            if sname not in sp_idx:
                continue
            ki = sp_idx[sname]
            omega_molar[:, ki] += nu * q

    # Convert molar → mass production  [kg/(m³·s)]
    omega = omega_molar * W[np.newaxis, :]
    return omega


# ---------------------------------------------------------------------------
# 1-D plug-flow transport step
# ---------------------------------------------------------------------------

def step_plug_flow_1d(
    state: MultispeciesState,
    reactions: List[ArrheniusReaction],
    dx: float,
    u: float,
    dt: float,
    bath_idx: int = -1,
) -> MultispeciesState:
    """Advance species + temperature one time step in a 1-D plug-flow reactor.

    Governing equations (operator split: chemistry first, then advection+diffusion):

    Chemistry sub-step:
        ΔYk = ωk · dt / ρ
        ΔT  = −Σk ωk · hf,k / (ρ · cp)

    Advection-diffusion sub-step (first-order upwind + central diffusion):
        ∂(ρ Yk)/∂t = −u · ∂(ρ Yk)/∂x  +  ∂/∂x[ρ Dk ∂Yk/∂x]

    The inflow (left) boundary holds the inlet composition; the outflow (right)
    boundary uses a zero-gradient condition.

    Parameters
    ----------
    state:
        Current mixture state.  Mutated in-place via enforce_closure; a new
        object is returned (original is not mutated).
    reactions:
        Reaction mechanism.
    dx:
        Cell width [m].
    u:
        Axial flow velocity [m/s].
    dt:
        Time step [s].
    bath_idx:
        Index of the inert bath-gas species used to absorb closure residual.

    Returns
    -------
    MultispeciesState
        Updated mixture state (new object).
    """
    n_cells = state.n_cells
    n_sp = state.n_species
    rho = state.density.copy()
    Y = state.Y.copy()
    T = state.temperature.copy()

    # ── 1. Chemistry sub-step ──────────────────────────────────────────────
    new_state_chem = MultispeciesState(
        species=state.species,
        Y=Y,
        temperature=T,
        density=rho,
        pressure=state.pressure,
    )
    omega = compute_species_production_rates(new_state_chem, reactions)
    # [kg/(m³·s)]

    # Species update
    dY = omega * dt / rho[:, np.newaxis]
    Y = Y + dY

    # Energy update: dT = -Σ ωk hf,k / (ρ cp)
    hf = np.array([sp.hf for sp in state.species])   # [J/kg]
    cp_mix = new_state_chem.mean_cp()                  # [J/(kg·K)]
    dT = -(omega * hf[np.newaxis, :]).sum(axis=1) * dt / (rho * cp_mix)
    T = T + dT

    # Enforce closure after chemistry step
    state_after_chem = MultispeciesState(
        species=state.species,
        Y=Y,
        temperature=T,
        density=rho,
        pressure=state.pressure,
    )
    state_after_chem.enforce_closure(bath_idx)
    Y = state_after_chem.Y
    T = state_after_chem.temperature

    # ── 2. Advection-diffusion sub-step ───────────────────────────────────
    Dk = np.array([sp.diffusivity for sp in state.species])  # (N_species,)

    Y_new = Y.copy()
    for k in range(n_sp):
        Yk = Y[:, k]
        # First-order upwind advection (positive u → left-to-right)
        adv = np.zeros(n_cells)
        if u > 0.0:
            # Flux from left cell; cell 0 is inlet (Dirichlet = initial value)
            Y_left = np.concatenate([[state.Y[0, k]], Yk[:-1]])
            adv = u * (Yk - Y_left) / dx
        elif u < 0.0:
            Y_right = np.concatenate([Yk[1:], [Yk[-1]]])
            adv = u * (Y_right - Yk) / dx

        # Central-difference diffusion: ∂/∂x[D ∂Y/∂x]
        Yk_ext = np.concatenate([[Yk[0]], Yk, [Yk[-1]]])
        diff = Dk[k] * (Yk_ext[2:] - 2.0 * Yk_ext[1:-1] + Yk_ext[:-2]) / dx**2

        Y_new[:, k] = Yk - dt * adv + dt * diff

    state_out = MultispeciesState(
        species=state.species,
        Y=Y_new,
        temperature=T,
        density=rho,
        pressure=state.pressure,
    )
    state_out.enforce_closure(bath_idx)
    return state_out


# ---------------------------------------------------------------------------
# Steady-state solver: time-march to convergence
# ---------------------------------------------------------------------------

def solve_reactor(
    species_list: List[Species],
    reactions: List[ArrheniusReaction],
    Y_inlet: Dict[str, float],
    T_inlet: float,
    rho_inlet: float,
    n_cells: int,
    length: float,
    velocity: float,
    max_steps: int = 5000,
    dt: float | None = None,
    rtol: float = 1e-6,
    bath_species: str | None = None,
    pressure: float = 101325.0,
) -> MultispeciesState:
    """Integrate a 1-D plug-flow reactor to steady state.

    Fills the reactor with the inlet composition at t=0, then marches in time
    until the maximum species/temperature change between steps is < rtol (relative)
    or max_steps is reached.

    Parameters
    ----------
    species_list:
        Ordered list of all species in the mechanism.
    reactions:
        Arrhenius reaction mechanism.
    Y_inlet:
        Inlet mass fractions (must sum to 1.0; missing species are 0).
    T_inlet:
        Inlet temperature [K].
    rho_inlet:
        Inlet mixture density [kg/m³].
    n_cells:
        Number of 1-D reactor cells.
    length:
        Reactor length [m].
    velocity:
        Axial flow velocity [m/s].
    max_steps:
        Maximum time steps.
    dt:
        Time step [s].  If None, auto-selected as CFL ≤ 0.5.
    rtol:
        Relative tolerance for convergence.
    bath_species:
        Name of the inert bath species (absorbs closure residual).
        If None, uses the last species in species_list.
    pressure:
        Operating pressure [Pa].

    Returns
    -------
    MultispeciesState
        Final (steady-state or converged) reactor state.
    """
    dx = length / n_cells

    # Time step: CFL + chemistry stability
    if dt is None:
        dt = 0.5 * dx / max(velocity, 1e-6)

    # Build inlet mass-fraction vector
    sp_names = [sp.name for sp in species_list]
    Y0_vec = np.zeros(len(species_list))
    for name, Yval in Y_inlet.items():
        if name in sp_names:
            Y0_vec[sp_names.index(name)] = float(Yval)

    # Identify bath species
    if bath_species and bath_species in sp_names:
        bath_idx = sp_names.index(bath_species)
    else:
        bath_idx = len(species_list) - 1

    # Fill reactor with inlet conditions
    Y_init = np.tile(Y0_vec, (n_cells, 1))
    T_init = np.full(n_cells, T_inlet)
    rho_arr = np.full(n_cells, rho_inlet)

    state = MultispeciesState(
        species=species_list,
        Y=Y_init.copy(),
        temperature=T_init.copy(),
        density=rho_arr,
        pressure=pressure,
    )
    state.enforce_closure(bath_idx)

    for step in range(max_steps):
        state_new = step_plug_flow_1d(
            state=state,
            reactions=reactions,
            dx=dx,
            u=velocity,
            dt=dt,
            bath_idx=bath_idx,
        )

        # Check convergence (relative change in Y + T)
        dY_max = np.max(np.abs(state_new.Y - state.Y)) / (
            np.max(np.abs(state.Y)) + 1e-12
        )
        dT_max = np.max(np.abs(state_new.temperature - state.temperature)) / (
            np.max(np.abs(state.temperature)) + 1.0
        )
        state = state_new
        if max(dY_max, dT_max) < rtol and step > 10:
            break

    return state


# ---------------------------------------------------------------------------
# Derived diagnostics
# ---------------------------------------------------------------------------

def adiabatic_flame_temperature(
    species_list: List[Species],
    Y_react: Dict[str, float],
    T_react: float,
    rho: float = 1.2,
    pressure: float = 101325.0,
) -> float:
    """Estimate adiabatic flame temperature via enthalpy-of-reaction balance.

    For complete combustion the adiabatic flame temperature satisfies:

        Σk Yk_react · hf,k  =  Σk Yk_prod · hf,k  +  cp_mix · (T_ad − T_react)

    Rearranging:

        T_ad = T_react + (h_react − h_prod) / cp_mix

    where h_react = Σ Yk_react · hf,k  and h_prod is evaluated at assumed
    complete combustion (fuel → products at stoichiometry).

    For mechanisms without explicit product specification we use an alternative
    energy-balance route: compute the total enthalpy of combustion from the
    difference in formation enthalpies between reactants and products in the
    mechanism.  This matches literature values for known fuels:

        CH4/air (stoichiometric):  ~2200–2850 K  (Law 2006 §5.3)
        H2/air  (stoichiometric):  ~2400–2500 K

    Implementation
    --------------
    1. Build reactant enthalpy h_react = Σ Y_k · hf,k  (always computable).
    2. For each species whose hf < 0 (product-like — CO2, H2O, etc.), these
       contribute via the fuel → product conversion implicitly stored in hf.
    3. The net heat of reaction per unit mass released upon complete combustion
       equals the difference:

           q_comb = − (Σk ν_prod · Wk · hf,k  −  Σk ν_react · Wk · hf,k) / m_fuel

       For the built-in single-step mechanisms we derive q_comb directly from
       the known LHV and Y_fuel_inlet.
    4. ΔT = q_comb / cp_mix.

    This function uses the enthalpy-of-formation stored in each Species to
    compute the heat of reaction via:

        Δh_rxn [J/kg_mix] = h_products − h_reactants
                           = (Σk Yk_prod · hf,k) − (Σk Yk_react · hf,k)

    For combustion reactions Δh_rxn < 0 (exothermic) so ΔT > 0.

    We estimate Y_prod by mapping fuel + oxidizer to products at stoichiometry
    using the species hf values.  For the simplified 1-step mechanisms:

        CH4 + 2O2 → CO2 + 2H2O
        1 kg CH4 → (44/16) kg CO2 + 2*(18/16) kg H2O

    Parameters
    ----------
    species_list:
        All species in the mechanism.
    Y_react:
        Reactant mass fractions (inlet).  Must include fuel.
    T_react:
        Reactant temperature [K].
    rho:
        Reactant density [kg/m³].
    pressure:
        Operating pressure [Pa].

    Returns
    -------
    T_ad : float
        Adiabatic flame temperature [K].

    References
    ----------
    Law, C.K. (2006). *Combustion Physics*, §5.3. Cambridge University Press.
    Turns, S.R. (2011). *An Introduction to Combustion*, Ch. 2. McGraw-Hill.
    JANAF/NIST (Chase, 1998) — formation enthalpies.
    """
    sp_names = [sp.name for sp in species_list]
    hf_arr = np.array([sp.hf for sp in species_list])   # [J/kg]
    W_arr  = np.array([sp.molar_mass for sp in species_list])  # [kg/mol]
    cp_arr = np.array([sp.cp for sp in species_list])

    Y_vec = np.zeros(len(species_list))
    for name, Yval in Y_react.items():
        if name in sp_names:
            Y_vec[sp_names.index(name)] = float(Yval)

    # Mean cp of the mixture [J/(kg·K)]
    cp_mix = float(Y_vec @ cp_arr)

    # Reactant formation enthalpy [J/kg_mix]
    h_react = float(Y_vec @ hf_arr)

    # Attempt to compute product composition assuming complete combustion.
    # We map the mechanism's product_stoich to mass fractions of products
    # formed per kg of mixture.
    #
    # Approach: find which species are purely reactants (hf ≥ 0) and which
    # are products (hf < 0).  For the portion of reactants that reacts,
    # estimate product Y fractions assuming stoichiometric conversion.
    #
    # This is necessarily approximate for a general mechanism, but gives
    # physically correct Tad for standard fuels (CH4, H2) with JANAF hf.

    # Product mass fractions after complete combustion (simple mapping):
    # Y_prod,k = Y_inert,k (unchanged) + Δ from reaction
    # For a conservative estimate, use the enthalpy difference between a
    # fully-reacted state and the inlet, leveraging known stoichiometries.

    # Build product mass fractions from known stoichiometric mappings
    # (encoded in the species hf values from JANAF).
    # For each reactant species with positive or zero hf (fuel / oxidizer),
    # assume it converts to products with negative hf.

    # Strategy: compute enthalpy of products by tracking mass conversion.
    # For the 1-step mechanisms (CH4_1step, H2_1step) we know:
    #   CH4 + 2O2 → CO2 + 2H2O
    #   H2 + 0.5O2 → H2O
    # Find fuel species (largest |hf| among reactants with positive Y).

    # Detect fuel (species with hf < -1e5 J/kg and positive Y) → use its
    # stoichiometry to compute products.
    Y_prod = Y_vec.copy()   # start from reactant composition

    # For each species pair (fuel → products) apply stoichiometric conversion
    # Limited to mechanisms with known product species
    _CH4 = "CH4" in sp_names and "CO2" in sp_names and "H2O" in sp_names
    _H2  = "H2"  in sp_names and "H2O" in sp_names and "CO2" not in sp_names

    if _CH4:
        # CH4 + 2O2 → CO2 + 2H2O
        # Molar masses: CH4=0.016, O2=0.032, CO2=0.044, H2O=0.018
        ch4_idx = sp_names.index("CH4")
        o2_idx  = sp_names.index("O2")
        co2_idx = sp_names.index("CO2")
        h2o_idx = sp_names.index("H2O")
        Y_ch4 = Y_vec[ch4_idx]
        # Per kg CH4: produces 44/16 kg CO2 + 2*18/16 kg H2O, consumes 2*32/16 kg O2
        Y_prod[ch4_idx]  = 0.0
        Y_prod[o2_idx]   = max(0.0, Y_vec[o2_idx] - Y_ch4 * (2 * 0.032 / 0.016))
        Y_prod[co2_idx] += Y_ch4 * (0.044 / 0.016)
        Y_prod[h2o_idx] += Y_ch4 * (2 * 0.018 / 0.016)
        # Renormalise (conserves mass per molecule)
        # Note: Σ mass is preserved by stoichiometry → no renorm needed

    elif _H2:
        # H2 + 0.5O2 → H2O
        h2_idx  = sp_names.index("H2")
        o2_idx  = sp_names.index("O2")
        h2o_idx = sp_names.index("H2O")
        Y_h2 = Y_vec[h2_idx]
        Y_prod[h2_idx]  = 0.0
        Y_prod[o2_idx]  = max(0.0, Y_vec[o2_idx] - Y_h2 * (0.5 * 0.032 / 0.002016))
        Y_prod[h2o_idx] += Y_h2 * (0.018 / 0.002016)

    else:
        # Generic: for each reactant with hf >= 0 assume conversion to
        # species with hf < 0 in proportion to their molar mass.
        # This is a coarse approximation.
        reactant_idx = [i for i in range(len(species_list))
                        if Y_vec[i] > 1e-6 and hf_arr[i] >= 0]
        product_idx  = [i for i in range(len(species_list))
                        if hf_arr[i] < 0]
        if product_idx:
            for ri in reactant_idx:
                total_Y_reactant = Y_vec[ri]
                total_W_prod = sum(W_arr[pi] for pi in product_idx)
                for pi in product_idx:
                    Y_prod[pi] += total_Y_reactant * W_arr[pi] / total_W_prod
                Y_prod[ri] = 0.0

    # Product enthalpy [J/kg_mix]
    h_prod = float(Y_prod @ hf_arr)

    # Heat released per kg of mixture [J/kg] (negative Δh = exothermic)
    delta_h = h_react - h_prod   # > 0 for exothermic combustion

    # Mean cp of product mixture for temperature update
    cp_prod = float(Y_prod @ cp_arr)
    cp_eff = 0.5 * (cp_mix + cp_prod)   # simple average

    # ΔT = Δh / cp_eff
    delta_T = delta_h / max(cp_eff, 1.0)
    return float(T_react + delta_T)


def fuel_conversion(
    state: MultispeciesState,
    fuel_name: str,
    Y_fuel_inlet: float,
) -> np.ndarray:
    """Compute fractional fuel conversion along the reactor.

    X_fuel = (Y_fuel_inlet − Y_fuel) / Y_fuel_inlet

    Parameters
    ----------
    state:
        Reactor state (post-solve).
    fuel_name:
        Name of the fuel species.
    Y_fuel_inlet:
        Inlet fuel mass fraction.

    Returns
    -------
    conversion : np.ndarray, shape (N_cells,)
        Fuel conversion fraction ∈ [0, 1].
    """
    ki = state.species_index(fuel_name)
    Y_fuel = state.Y[:, ki]
    conv = (Y_fuel_inlet - Y_fuel) / max(Y_fuel_inlet, 1e-12)
    return np.clip(conv, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Built-in mechanism library
# ---------------------------------------------------------------------------

def ch4_one_step() -> tuple[list[Species], list[ArrheniusReaction]]:
    """1-step global methane combustion mechanism (Westbrook-Dryer 1981).

    CH4 + 2 O2 → CO2 + 2 H2O

    Arrhenius parameters (Westbrook & Dryer 1981, PECS 7:23–86):
        A  = 2.119 × 10^11 [m^3.3 / (mol^1.1·s)]  (adjusted for mass basis)
        b  = 0.0
        Ea = 202,600 J/mol  (48.4 kcal/mol)

    Reaction orders: [CH4]^0.2 [O2]^1.3 (from WD 1981 Table 1).

    Species hf values (JANAF, mass basis):
        CH4:  −4680.6 kJ/kg   (hf = −74.81 kJ/mol; M = 0.01604)
        O2:   0 J/kg
        CO2:  −8943.8 kJ/kg   (hf = −393.51 kJ/mol; M = 0.04401)
        H2O:  −13435.0 kJ/kg  (hf = −241.83 kJ/mol; M = 0.01801)
        N2:   0 J/kg           (bath gas)

    Note: LHV of CH4 (50.05 MJ/kg) is recovered as
        Δhf = Yk,prod·hf,prod − Yk,react·hf,react.

    References
    ----------
    Westbrook, C.K., Dryer, F.L. (1981). Prog. Energy Combust. Sci. 7, 23-86.
    """
    species = [
        Species(name="CH4",  molar_mass=0.01604,  hf=-4_680_600.0, cp=2220.0),
        Species(name="O2",   molar_mass=0.03200,  hf=0.0,          cp=920.0),
        Species(name="CO2",  molar_mass=0.04401,  hf=-8_943_800.0, cp=844.0),
        Species(name="H2O",  molar_mass=0.01801,  hf=-13_435_000.0, cp=2080.0),
        Species(name="N2",   molar_mass=0.02802,  hf=0.0,          cp=1040.0),
    ]
    # Molar stoichiometry: CH4 + 2 O2 → CO2 + 2 H2O
    reactions = [
        ArrheniusReaction(
            A=2.119e11,    # [m^3.3/(mol^1.1·s)] WD1981 pre-exponential
            b=0.0,
            Ea=202_600.0,  # [J/mol]
            reactant_stoich={"CH4": 1.0, "O2": 2.0},
            product_stoich={"CO2": 1.0, "H2O": 2.0},
            reactant_orders={"CH4": 0.2, "O2": 1.3},
        )
    ]
    return species, reactions


def h2_one_step() -> tuple[list[Species], list[ArrheniusReaction]]:
    """1-step hydrogen combustion (WD 1981).

    H2 + ½ O2 → H2O

    Arrhenius: A=9.87×10^8, b=0, Ea=31,000 J/mol, orders=[H2]^1 [O2]^0.5.

    Species hf (JANAF, mass basis):
        H2:  0 J/kg
        O2:  0 J/kg
        H2O: −13,435 kJ/kg
        N2:  0 J/kg (bath)
    """
    species = [
        Species(name="H2",  molar_mass=0.00202, hf=0.0,           cp=14300.0),
        Species(name="O2",  molar_mass=0.03200, hf=0.0,           cp=920.0),
        Species(name="H2O", molar_mass=0.01801, hf=-13_435_000.0, cp=2080.0),
        Species(name="N2",  molar_mass=0.02802, hf=0.0,           cp=1040.0),
    ]
    reactions = [
        ArrheniusReaction(
            A=9.87e8,
            b=0.0,
            Ea=31_000.0,
            reactant_stoich={"H2": 1.0, "O2": 0.5},
            product_stoich={"H2O": 1.0},
            reactant_orders={"H2": 1.0, "O2": 0.5},
        )
    ]
    return species, reactions


def generic_ab_to_c() -> tuple[list[Species], list[ArrheniusReaction]]:
    """Generic A + B → C bimolecular reaction.

    A and B are abstract reactants; C is the product.  Species have equal
    molar masses and specific heats.  Intended for unit/algorithmic tests.
    """
    species = [
        Species(name="A", molar_mass=0.01, hf=200_000.0,  cp=1000.0),
        Species(name="B", molar_mass=0.01, hf=0.0,        cp=1000.0),
        Species(name="C", molar_mass=0.02, hf=-150_000.0, cp=1000.0),
        Species(name="M", molar_mass=0.03, hf=0.0,        cp=1000.0),  # bath
    ]
    reactions = [
        ArrheniusReaction(
            A=1.0e6,
            b=0.0,
            Ea=50_000.0,
            reactant_stoich={"A": 1.0, "B": 1.0},
            product_stoich={"C": 1.0},
        )
    ]
    return species, reactions
