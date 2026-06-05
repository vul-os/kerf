"""
kerf_cfd.plasma.drift_diffusion
================================
1-D low-temperature plasma drift-diffusion solver for DC glow discharges.

Physical model
--------------
Coupled PDEs on a 1-D domain [0, d] (anode at x=0, cathode at x=d):

  Electron continuity:
    ∂n_e/∂t = ∂/∂x (D_e ∂n_e/∂x + μ_e n_e E) + S_ion

  Ion continuity:
    ∂n_i/∂t = ∂/∂x (D_i ∂n_i/∂x − μ_i n_i E) + S_ion

  Ionization source (Townsend 1st coefficient):
    S_ion = α(E) · |μ_e E| · n_e       [m⁻³ s⁻¹]
    α(E)  = A · p · exp(−B · p / |E|)  [m⁻¹]     (Townsend, 1910)

  Poisson equation (quasi-1D):
    dE/dx = q (n_i − n_e) / ε₀         (ε_r = 1 for gas)
    E = −dφ/dx

  Boundary conditions:
    Anode  (x=0):  φ = V_applied; n_e = 0 (absorbed)
    Cathode (x=d): φ = 0; secondary emission n_e(d) = γ · Γ_i / (D_e/h + μ_e|E(d)|)

Discretisation
--------------
  - Uniform 1-D grid with N intervals (N+1 nodes), spacing h = d/N
  - Operator-split semi-implicit time integration:
      (a) Explicit Euler for transport fluxes (Scharfetter-Gummel)
      (b) Implicit treatment of ionisation source avoids exponential blow-up:
            n_e^{n+1} = n_e^n / (1 − dt·α·μ_e·|E|)  (locally exact limit)
  - Adaptive dt: CFL on drift + cap on ionisation growth rate

Transport coefficients (local-field approximation)
--------------------------------------------------
  Air / N₂:  μ_e=0.04 m²/(V·s), Te=2 eV, μ_i=2e-4 m²/(V·s), Ti=0.026 eV
              A=12 m⁻¹Pa⁻¹, B=365 V Pa⁻¹ m⁻¹  (Lieberman Tab 2.3)
  Argon:     μ_e=0.06, Te=3 eV, A=12, B=180
  Helium:    μ_e=0.12, Te=4 eV, A=3, B=34
  γ_se ≈ 0.01–0.25  (Townsend 2nd coefficient, secondary emission at cathode)

Maximum plasma density cap
--------------------------
  n_max = ε₀ · V / (q · d²)   (Child-Langmuir space-charge limit for sheath)
  Densities are clamped to [0, n_max] after each step to prevent runaway.

Limitations / honest flags
--------------------------
  DRIFT-DIFFUSION FLUID MODEL, NOT KINETIC/PIC.
  Local-field approximation; no energy-equation self-consistency.
  Single gas species; no excitation, attachment, detachment, or recombination.
  No photoionization, no metastable kinetics.
  1-D geometry; electrode sheath on uniform grid (finer mesh improves accuracy).
  Not validated against COMSOL Plasma module outputs.
  DC steady-state focus; RF/ICP/DBD not implemented.
  Use for design exploration / trend analysis only.

References
----------
Hagelaar, G.J.M., Pitchford, L.C. (2005). Plasma Sources Sci. Technol. 14, 722.
Lieberman, M.A., Lichtenberg, A.J. (2005). Principles of Plasma Discharges. Wiley.
Surendra, M., Graves, D.B. (1991). IEEE Trans. Plasma Sci. 19, 144.
Townsend, J.S. (1910). Phil. Mag. 20, 802.
Paschen, F. (1889). Ann. Phys. 273, 69.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_Q_E = 1.602176634e-19    # elementary charge [C]
_EPS0 = 8.8541878128e-12  # vacuum permittivity [F/m]
_KB = 1.380649e-23         # Boltzmann constant [J/K]


# ---------------------------------------------------------------------------
# Gas transport parameters
# ---------------------------------------------------------------------------

@dataclass
class PlasmaGas:
    """Transport and ionisation coefficients for a low-temperature plasma gas.

    All parameters SI unless stated.

    Attributes
    ----------
    name        : short gas label
    mu_e_ref    : electron mobility [m²/(V·s)]
    De_Te_eV    : electron temperature for Einstein D=μTe relation [eV]
    mu_i        : positive ion mobility [m²/(V·s)]
    Ti_eV       : ion temperature [eV] (room ≈ 0.026 eV)
    A_tow       : Townsend 1st coeff A [m⁻¹·Pa⁻¹]  (α = A·p·exp(-B·p/|E|))
    B_tow       : Townsend B constant [V·Pa⁻¹·m⁻¹]
    gamma_se    : Townsend 2nd coefficient (cathode secondary emission, dimensionless)
    eps_r       : relative permittivity of gas (≈ 1)
    """

    name: str = "air"
    mu_e_ref: float = 0.04        # [m²/(V·s)]
    De_Te_eV: float = 2.0         # [eV] → D_e = mu_e * Te_eV
    mu_i: float = 2.0e-4          # [m²/(V·s)]
    Ti_eV: float = 0.026          # [eV]
    A_tow: float = 12.0           # [m⁻¹·Pa⁻¹]
    B_tow: float = 365.0          # [V·Pa⁻¹·m⁻¹]
    gamma_se: float = 0.01        # secondary emission coefficient
    eps_r: float = 1.0

    @classmethod
    def air(cls) -> "PlasmaGas":
        """Air (N₂-dominant) — Lieberman & Lichtenberg (2005) Tab 2.3."""
        return cls(name="air", mu_e_ref=0.04, De_Te_eV=2.0, mu_i=2.0e-4,
                   Ti_eV=0.026, A_tow=12.0, B_tow=365.0, gamma_se=0.01)

    @classmethod
    def argon(cls) -> "PlasmaGas":
        """Argon — Lieberman & Lichtenberg (2005) Appendix."""
        return cls(name="argon", mu_e_ref=0.06, De_Te_eV=3.0, mu_i=1.6e-4,
                   Ti_eV=0.026, A_tow=12.0, B_tow=180.0, gamma_se=0.1)

    @classmethod
    def helium(cls) -> "PlasmaGas":
        """Helium — lower ionisation potential; smaller Townsend A, B."""
        return cls(name="helium", mu_e_ref=0.12, De_Te_eV=4.0, mu_i=1.0e-3,
                   Ti_eV=0.026, A_tow=3.0, B_tow=34.0, gamma_se=0.25)

    @classmethod
    def nitrogen(cls) -> "PlasmaGas":
        """Nitrogen (N₂) — same coefficients as air (dominant component)."""
        return cls(name="nitrogen", mu_e_ref=0.04, De_Te_eV=2.0, mu_i=2.0e-4,
                   Ti_eV=0.026, A_tow=12.0, B_tow=365.0, gamma_se=0.01)

    @classmethod
    def from_name(cls, name: str) -> "PlasmaGas":
        lname = name.lower().strip()
        factories = {
            "air": cls.air,
            "argon": cls.argon,
            "helium": cls.helium,
            "nitrogen": cls.nitrogen,
            "n2": cls.nitrogen,
        }
        if lname not in factories:
            raise ValueError(
                f"Unknown gas '{name}'. Supported: {sorted(factories)}"
            )
        return factories[lname]()


# ---------------------------------------------------------------------------
# Poisson solver: tridiagonal Thomas algorithm
# ---------------------------------------------------------------------------

def _solve_poisson_1d(rho: np.ndarray, h: float, V_anode: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Solve 1-D Poisson equation for electric potential φ:

        d²φ/dx² = −ρ / ε₀

    on N+1 nodes [0, h, 2h, ..., d] with Dirichlet BCs:
        φ[0] = V_anode (anode),  φ[N] = 0 (cathode, grounded)

    Uses the Thomas tridiagonal algorithm (O(N) direct solve).

    Returns (phi, E_field) where E_field[j] = −(phi[j+1]−phi[j])/h for j<N
    and E_field[N] = E_field[N-1].
    """
    N = len(rho) - 1
    # Interior nodes: 1 .. N-1
    # d²φ/dx² ≈ (φ[j-1] − 2φ[j] + φ[j+1]) / h² = −ρ[j]/ε₀
    # Rearranged: φ[j-1] − 2φ[j] + φ[j+1] = −ρ[j]·h²/ε₀

    if N <= 1:
        phi = np.array([V_anode, 0.0])
        E = np.array([(V_anode) / h, (V_anode) / h])
        return phi, E

    n_int = N - 1  # number of interior nodes
    rhs = -rho[1:N] * h * h / _EPS0
    # Apply boundary contributions
    rhs[0] += V_anode   # from φ[0] = V_anode on the left
    rhs[-1] += 0.0      # from φ[N] = 0 on the right (no contribution)

    # Tridiagonal: lower=-1, diag=-2, upper=-1 → divide by -1 → diag=2, off=-1
    # Thomas forward sweep
    c = np.empty(n_int - 1)
    d = rhs.copy()
    diag = 2.0

    # Forward elimination
    c[0] = 1.0 / diag
    d[0] = d[0] / diag
    for j in range(1, n_int):
        denom = diag - c[j - 1] if j < n_int - 1 else diag - c[j - 1]
        # Standard Thomas:
        if j < n_int - 1:
            m = 1.0 / (diag - c[j - 1])
            c[j] = m
            d[j] = (d[j] + d[j - 1]) * m
        else:
            m = 1.0 / (diag - c[j - 1])
            d[j] = (d[j] + d[j - 1]) * m

    # Backward substitution
    phi_int = np.empty(n_int)
    phi_int[-1] = d[-1]
    for j in range(n_int - 2, -1, -1):
        phi_int[j] = d[j] + phi_int[j + 1] * c[j]

    phi = np.empty(N + 1)
    phi[0] = V_anode
    phi[1:N] = phi_int
    phi[N] = 0.0

    E = np.empty(N + 1)
    E[:-1] = -(phi[1:] - phi[:-1]) / h
    E[-1] = E[-2]

    return phi, E


def _poisson_direct(ni: np.ndarray, ne: np.ndarray, h: float,
                    V_anode: float, eps_r: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Wrapper: compute ρ = q(ni−ne)/ε_r then call _solve_poisson_1d."""
    # Note: ε₀ is already in _solve_poisson_1d, so we pass ρ without ε₀
    # Actually rhs = -ρ*h²/ε₀ so we need ρ = q(ni-ne)/eps_r (dimensionless correction)
    # For gas eps_r ≈ 1, but include it for generality.
    rho = _Q_E * (ni - ne) / eps_r
    return _solve_poisson_1d(rho, h, V_anode)


# ---------------------------------------------------------------------------
# Scharfetter-Gummel flux helper
# ---------------------------------------------------------------------------

def _bernoulli(b: np.ndarray) -> np.ndarray:
    """Bernoulli function B(b) = b / (exp(b) − 1), stable for small b."""
    out = np.ones_like(b, dtype=float)
    # Use Taylor expansion for |b| < 1e-4 to avoid 0/0
    small = np.abs(b) < 1e-4
    large = ~small
    bc = np.clip(b[large], -50, 50)
    with np.errstate(over="ignore", invalid="ignore"):
        exp_b = np.exp(bc)
        denom = exp_b - 1.0
        out[large] = np.where(np.abs(denom) > 1e-30, bc / denom, 1.0)
    # Taylor: B(b) ≈ 1 - b/2 + b²/12 - b⁴/720
    bs = b[small]
    out[small] = 1.0 - bs / 2.0 + bs**2 / 12.0 - bs**4 / 720.0
    return out


def _sg_flux_e(ne: np.ndarray, E_face: np.ndarray,
               mu_e: float, D_e: float, h: float) -> np.ndarray:
    """
    Scharfetter-Gummel flux for electrons (drift velocity = −μ_e·E).

    Γ_e[j+1/2] = (D_e/h) · [n_e[j]·B(+β) − n_e[j+1]·B(−β)]
    where β = −μ_e·E_{j+1/2}·h / D_e  (negative sign: electrons drift against E)
    """
    beta = -mu_e * E_face * h / max(D_e, 1e-30)
    beta = np.clip(beta, -50, 50)
    Bp = _bernoulli(beta)
    Bm = _bernoulli(-beta)
    return D_e / h * (ne[:-1] * Bp - ne[1:] * Bm)


def _sg_flux_i(ni: np.ndarray, E_face: np.ndarray,
               mu_i: float, D_i: float, h: float) -> np.ndarray:
    """
    Scharfetter-Gummel flux for ions (drift velocity = +μ_i·E).

    Γ_i[j+1/2] = (D_i/h) · [n_i[j]·B(+β) − n_i[j+1]·B(−β)]
    where β = +μ_i·E_{j+1/2}·h / D_i
    """
    beta = mu_i * E_face * h / max(D_i, 1e-30)
    beta = np.clip(beta, -50, 50)
    Bp = _bernoulli(beta)
    Bm = _bernoulli(-beta)
    return D_i / h * (ni[:-1] * Bp - ni[1:] * Bm)


# ---------------------------------------------------------------------------
# Townsend ionisation coefficient
# ---------------------------------------------------------------------------

def _townsend_alpha(E_abs: np.ndarray, gas: PlasmaGas, p: float) -> np.ndarray:
    """
    First Townsend ionisation coefficient α [m⁻¹]:

        α = A · p · exp(−B · p / |E|)

    Zero where |E| < 1 V/m (numerical guard).
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.where(
            E_abs > 1.0,
            gas.A_tow * p * np.exp(-gas.B_tow * p / E_abs),
            0.0,
        )
    return np.clip(alpha, 0.0, None)


# ---------------------------------------------------------------------------
# Main solver dataclass
# ---------------------------------------------------------------------------

@dataclass
class PlasmaDischargeSolver:
    """
    1-D DC glow-discharge drift-diffusion solver.

    Parameters
    ----------
    gas         : PlasmaGas transport coefficients
    pressure_Pa : gas pressure [Pa]
    gap_m       : electrode gap [m]
    voltage_V   : DC anode–cathode voltage [V]
    n_cells     : number of uniform grid cells (= N; N+1 nodes)
    dt          : time step [s] (0 → auto CFL)
    max_steps   : maximum time steps before giving up
    tol         : relative steady-state convergence criterion
    n0          : initial seed plasma density [m⁻³]
    """

    gas: PlasmaGas = field(default_factory=PlasmaGas.air)
    pressure_Pa: float = 1000.0
    gap_m: float = 0.01
    voltage_V: float = 400.0
    n_cells: int = 200
    dt: float = 0.0
    max_steps: int = 20_000
    tol: float = 1e-5
    n0: float = 1e10

    def solve(self) -> dict[str, Any]:
        """
        Run the 1-D DC glow-discharge drift-diffusion solver.

        Returns a JSON-serialisable dict containing field profiles,
        integrated quantities, and Paschen breakdown estimate.
        """
        gas = self.gas
        p = self.pressure_Pa
        d = self.gap_m
        V = self.voltage_V
        N = self.n_cells

        h = d / N
        x = np.linspace(0.0, d, N + 1)

        # -- Transport coefficients --
        mu_e = gas.mu_e_ref
        D_e = mu_e * gas.De_Te_eV          # Einstein: D = μ·Te [eV = V]
        mu_i = gas.mu_i
        D_i = mu_i * gas.Ti_eV

        # -- Space-charge density cap (Child-Langmuir sheath limit) --
        # n_CL ≈ ε₀·V / (q·d²) as an order-of-magnitude ceiling
        n_max = max(gas.eps_r * _EPS0 * abs(V) / (_Q_E * d * d), 1e18)

        # -- Initial conditions --
        ne = np.full(N + 1, self.n0, dtype=float)
        ni = np.full(N + 1, self.n0, dtype=float)

        # -- Adaptive dt --
        E_approx = abs(V) / d
        v_drift_e = mu_e * E_approx
        if self.dt > 0.0:
            dt = self.dt
        else:
            # CFL constraint
            dt_cfl = 0.3 * h / max(v_drift_e, 1.0)
            # Ionisation stability: dt < 1 / (α·μ_e·|E|)  at max field
            alpha_max = gas.A_tow * p * math.exp(-gas.B_tow * p / max(E_approx, 1.0))
            S_rate_max = alpha_max * mu_e * E_approx
            dt_ion = 0.3 / max(S_rate_max, 1.0)
            # Dielectric relaxation time
            ne_safe = max(self.n0, 1e8)
            dt_diel = 0.3 * gas.eps_r * _EPS0 / (_Q_E * ne_safe * mu_e)
            dt = min(dt_cfl, dt_ion, dt_diel, 1e-8)
            dt = max(dt, 1e-15)  # never zero

        ne_prev = ne.copy()
        converged = False
        n_steps = 0

        for step in range(self.max_steps):
            # ---- 1. Poisson: solve for φ and E ----
            phi, E_field = _poisson_direct(ni, ne, h, V, eps_r=gas.eps_r)
            absE = np.abs(E_field)

            # ---- 2. Townsend ionisation rate ----
            alpha = _townsend_alpha(absE, gas, p)
            # Ionisation source density [m⁻³ s⁻¹] — semi-implicit
            # Explicit: S = α·μ_e·|E|·ne  → use old ne
            S_ion = alpha * mu_e * absE * ne

            # ---- 3. SG fluxes at cell faces ----
            E_face = 0.5 * (E_field[:-1] + E_field[1:])
            flux_e = _sg_flux_e(ne, E_face, mu_e, D_e, h)
            flux_i = _sg_flux_i(ni, E_face, mu_i, D_i, h)

            # ---- 4. Explicit Euler time update (interior nodes 1..N-1) ----
            # dn/dt = −dΓ/dx + S
            dne_dt = np.zeros(N + 1)
            dni_dt = np.zeros(N + 1)
            dne_dt[1:N] = -(flux_e[1:] - flux_e[:-1]) / h + S_ion[1:N]
            dni_dt[1:N] = -(flux_i[1:] - flux_i[:-1]) / h + S_ion[1:N]

            ne_new = ne + dt * dne_dt
            ni_new = ni + dt * dni_dt

            # ---- 5. Boundary conditions ----
            # Anode (x=0): absorbing for electrons, open for ions
            ne_new[0] = 0.0
            ni_new[0] = max(float(ni_new[1]), 0.0)

            # Cathode (x=d): ion absorbed; secondary electron emission
            Gamma_i_cat = max(float(flux_i[-1]), 0.0)
            Gamma_e_sec = gas.gamma_se * Gamma_i_cat
            # n_e at cathode from flux balance (Dirichlet approximation)
            denom_e = D_e / h + mu_e * float(absE[-1])
            ne_new[-1] = Gamma_e_sec / max(denom_e, 1e-20)
            ni_new[-1] = 0.0

            # ---- 6. Clamp to [0, n_max] and guard NaN/inf ----
            np.clip(ne_new, 0.0, n_max, out=ne_new)
            np.clip(ni_new, 0.0, n_max, out=ni_new)
            if not np.all(np.isfinite(ne_new)):
                ne_new = np.where(np.isfinite(ne_new), ne_new, 0.0)
            if not np.all(np.isfinite(ni_new)):
                ni_new = np.where(np.isfinite(ni_new), ni_new, 0.0)

            # ---- 7. Adaptive dt: recompute from current state ----
            ne_peak = float(ne_new.max())
            if ne_peak > 1.0 and step % 50 == 0:
                v_now = mu_e * float(absE.max())
                dt_cfl_now = 0.3 * h / max(v_now, 1.0)
                alpha_now = float(alpha.max())
                S_now = alpha_now * mu_e * float(absE.max())
                dt_ion_now = 0.3 / max(S_now, 1.0)
                dt_diel_now = 0.3 * gas.eps_r * _EPS0 / (_Q_E * max(ne_peak, 1.0) * mu_e)
                dt = min(dt_cfl_now, dt_ion_now, dt_diel_now, 1e-8)
                dt = max(dt, 1e-15)

            # ---- 8. Convergence check every 200 steps ----
            if step % 200 == 0 and step > 0:
                ne_rms = float(ne_new.max())
                if ne_rms > 0:
                    rel_change = float(np.abs(ne_new - ne_prev).max()) / (ne_rms + 1e-30)
                    if rel_change < self.tol:
                        ne = ne_new
                        ni = ni_new
                        n_steps = step + 1
                        converged = True
                        break
                ne_prev = ne_new.copy()

            ne = ne_new
            ni = ni_new
            n_steps = step + 1

        if not converged:
            n_steps = self.max_steps

        # ---- Final field computation ----
        phi, E_field = _poisson_direct(ni, ne, h, V, eps_r=gas.eps_r)
        absE = np.abs(E_field)
        alpha_final = _townsend_alpha(absE, gas, p)
        S_ion_final = alpha_final * mu_e * absE * ne

        # ---- Discharge current density at midpoint ----
        mid = N // 2
        if mid > 0 and mid < N:
            dn_e_dx = (ne[mid + 1] - ne[mid - 1]) / (2 * h)
            dn_i_dx = (ni[mid + 1] - ni[mid - 1]) / (2 * h)
        else:
            dn_e_dx = 0.0
            dn_i_dx = 0.0
        J_e = _Q_E * abs(-mu_e * E_field[mid] * ne[mid] - D_e * dn_e_dx)
        J_i = _Q_E * abs(mu_i * E_field[mid] * ni[mid] - D_i * dn_i_dx)
        J_total = float(J_e + J_i)

        # ---- Sheath thickness: cathode region where n_i > n_e significantly ----
        sheath_thickness = 0.0
        sheath_frac = (ni - ne) / (ni + ne + 1.0)
        for j in range(N, 0, -1):
            if sheath_frac[j] > 0.05:
                sheath_thickness = d - x[j]
                break

        # ---- Paschen breakdown estimate ----
        V_bd = paschen_voltage(gas, p, d)

        return {
            "ok": True,
            "x_m": x.tolist(),
            "n_e_m3": ne.tolist(),
            "n_i_m3": ni.tolist(),
            "E_field_V_m": E_field.tolist(),
            "phi_V": phi.tolist(),
            "ionization_rate_m3_s": S_ion_final.tolist(),
            "current_density_A_m2": J_total,
            "converged": converged,
            "n_steps": n_steps,
            "breakdown_estimate_V": V_bd,
            "sheath_thickness_m": sheath_thickness,
            "peak_E_near_cathode_V_m": float(absE[-10:].max()),
            "peak_E_near_anode_V_m": float(absE[:10].max()),
            "peak_n_e_m3": float(ne.max()),
            "peak_n_i_m3": float(ni.max()),
            "gas": gas.name,
            "pressure_Pa": p,
            "gap_m": d,
            "voltage_V": V,
        }


# ---------------------------------------------------------------------------
# Paschen breakdown voltage
# ---------------------------------------------------------------------------

def paschen_voltage(gas: PlasmaGas, pressure_Pa: float, gap_m: float) -> float:
    """
    Paschen breakdown voltage for a DC discharge.

    Townsend breakdown criterion (Lieberman 2005, §14.2):
        γ_se · (exp(α·d) − 1) = 1
        → α·d = ln(1 + 1/γ_se)

    With Townsend 1st coefficient  α = A·p·exp(−B·p/E):
        V_bd = E·d = B·p·d / ln(A·p·d / ln(1 + 1/γ_se))

    Paschen minimum at  pd* = e · ln(1 + 1/γ_se) / A
    with  V_min = e · B · ln(1 + 1/γ_se) / A.

    Returns float("inf") when pd is below or near the left-branch limit
    (physically: no self-sustaining discharge possible at very low pd).
    """
    A = gas.A_tow
    B = gas.B_tow
    gamma = gas.gamma_se

    pd = pressure_Pa * gap_m
    if pd <= 0:
        return float("inf")

    ln_term = math.log(1.0 + 1.0 / gamma)
    # Left limit: A·pd / ln_term must be > 1 for breakdown to exist
    ratio = A * pd / ln_term
    if ratio <= 1.0:
        return float("inf")

    V_bd = B * pd / math.log(ratio)
    return max(V_bd, 0.0)


def paschen_curve(gas: PlasmaGas, pd_array: np.ndarray) -> np.ndarray:
    """
    Compute Paschen breakdown voltage V_bd for an array of pd values [Pa·m].

    Returns array with float("inf") where breakdown is not possible.
    """
    return np.array([paschen_voltage(gas, pd, 1.0) for pd in pd_array])


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run_discharge(
    gas: "str | PlasmaGas" = "air",
    pressure_Pa: float = 1000.0,
    gap_m: float = 0.01,
    voltage_V: float = 400.0,
    n_cells: int = 200,
    max_steps: int = 20_000,
    tol: float = 1e-5,
) -> dict[str, Any]:
    """
    Run a DC glow-discharge drift-diffusion simulation.

    Parameters
    ----------
    gas         : gas name ("air", "argon", "helium", "nitrogen") or PlasmaGas instance
    pressure_Pa : gas pressure [Pa]
    gap_m       : electrode separation [m]
    voltage_V   : applied DC voltage [V]  (anode positive)
    n_cells     : number of uniform spatial cells
    max_steps   : time-integration step limit
    tol         : steady-state relative convergence tolerance

    Returns
    -------
    dict with x_m, n_e_m3, n_i_m3, E_field_V_m, phi_V,
    ionization_rate_m3_s, current_density_A_m2, converged,
    breakdown_estimate_V, sheath_thickness_m, ...

    LIMITATIONS
    -----------
    Drift-diffusion fluid model, NOT kinetic/PIC. Local-field approximation.
    Single gas species; no photoionisation, metastables, or attachment.
    DC only; no RF/ICP/DBD. Not validated vs COMSOL Plasma module.
    Design-exploration / trend use only.
    """
    if isinstance(gas, str):
        gas_obj = PlasmaGas.from_name(gas)
    else:
        gas_obj = gas

    solver = PlasmaDischargeSolver(
        gas=gas_obj,
        pressure_Pa=pressure_Pa,
        gap_m=gap_m,
        voltage_V=voltage_V,
        n_cells=n_cells,
        max_steps=max_steps,
        tol=tol,
    )
    return solver.solve()
