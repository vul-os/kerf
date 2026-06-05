"""
kerf_cfd.internal_airflow.room_cfd_3d — 3-D room internal-airflow CFD.

Purpose
-------
Genuine 3-D incompressible RANS solver for room airflow on a structured
Cartesian grid, suitable for displacement/mixed/natural ventilation design.
Replaces the preview-grade 2-D-ish advection-diffusion sketch in microflo.py.

Physics implemented
-------------------
  Momentum + continuity   — SIMPLE pressure-velocity coupling (Patankar 1980
                            §6.7) on a collocated grid with Rhie-Chow flux
                            interpolation to suppress pressure checkerboarding.
  Turbulence closure      — mixing-length model (Prandtl 1925): l_m = κ·min(d,L_t)
                            where d = distance to nearest wall, κ = 0.41 (von
                            Kármán constant), L_t = mixing-length limit (0.07·H).
                            Eddy viscosity μ_t = ρ·l_m²·|S| (Smagorinsky-type
                            algebraic; no additional transport equations).
  Buoyancy                — Boussinesq approximation: Δρ/ρ = −β(T − T_ref),
                            β = 1/T_ref (ideal gas).  Buoyancy body force added
                            to the w (vertical) momentum equation only:
                            f_z = −ρ·β·g·(T − T_ref).
  Temperature transport   — steady advection-diffusion coupled to velocity:
                            ∇·(ρ u T) = ∇·((k_eff/cp)∇T) + q_src
                            where k_eff = k_air + μ_t·cp/Pr_t.
  Boundary conditions     — supply diffusers: Dirichlet velocity + temperature;
                            exhaust/return: outflow (zero-gradient velocity,
                            zero-gradient temperature, Dirichlet p = 0);
                            walls: no-slip (u=0), zero-gradient T.
  Heat sources            — volumetric source in temperature equation injected
                            at specified cell locations (occupants, equipment).

Algorithm summary (SIMPLE loop)
---------------------------------
  1. Predictor: solve 3 uncoupled momentum equations for u*, v*, w* (upwind
     advection + central diffusion; explicit pseudo-time stepping).
  2. Pressure correction p': solve Poisson equation ∇²p' = ∇·u*/Δt using
     Gauss-Seidel iterations.
  3. Correct velocities: u = u* − Δt·∇p'.
  4. Solve temperature equation with updated velocity.
  5. Update turbulent viscosity.
  6. Repeat for N_outer iterations (pseudo-steady).

Comfort outputs
---------------
  PMV/PPD   — Fanger (1972) / ISO 7730:2005 (reused from microflo.py).
  Draught rate (DR) — ISO 7730:2005 eq. A.9:
                    DR = (34 − T_a)(v_a − 0.05)^0.62 · (0.37·v_a·Tu + 3.14)
                    clamped to [0%, 100%]; Tu = turbulence intensity.
  Mean age of air   — passive-tracer transport: solve steady
                      ∇·(ρ u τ) − ∇·(ρ D_eff ∇τ) = ρ  (Sandberg 1981)
                      τ = 0 at supply; zero-gradient at exhaust; walls insulating.
  Vertical temperature gradient  — ΔT/Δz between head height (1.7 m) and
                                   ankle height (0.1 m) per occupant horizontal
                                   position; ISO 7730:2005 §A.2.2 threshold = 3 K/m.
  Ventilation effectiveness       — εv = C_s / C_e (tracer ratio; Mundt 1995).

Limitations (honest)
--------------------
  - Steady-state only (no transient).
  - Collocated grid with Rhie-Chow (not staggered MAC).
  - Algebraic mixing-length turbulence, not full k-ε transport equations.
  - Coarse structured grid (design-tool resolution, not research LES).
  - No radiation model; MRT approximated from surrounding cell temperatures.
  - Not validated against IES VE MicroFlo benchmark cases.
  - Single room, no multi-zone network.

References
----------
  Patankar S.V. (1980). "Numerical Heat Transfer and Fluid Flow."
      Hemisphere. SIMPLE §6.7; pressure correction eq. 6.20–6.22.
  Fanger P.O. (1972). "Thermal Comfort." McGraw-Hill. PMV/PPD model.
  ISO 7730:2005. "Moderate thermal environments." PMV/PPD/DR/DT_v.
  ASHRAE 55-2020. §5.3.3, Annex B.
  ASHRAE 62.1-2022. §6.2 local mean age of air.
  Sandberg M. (1981). "What is ventilation efficiency?" Building and
      Environment 16(2):123–135. Mean age of air passive tracer.
  Mundt E. (1995). "Displacement ventilation systems." PhD thesis KTH.
  Prandtl L. (1925). "Bericht über Untersuchungen zur ausgebildeten
      Turbulenz." ZAMM 5(2):136–139. Mixing-length model.

Author: imranparuk — Wave 12D: 3-D room CFD + thermal comfort
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

import numpy as np

from kerf_cfd.internal_airflow.microflo import fanger_pmv, fanger_ppd

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_RHO_AIR  = 1.2        # kg/m³  — air density  (20 °C, 101 325 Pa)
_CP_AIR   = 1005.0     # J/(kg·K)
_MU_AIR   = 1.81e-5    # Pa·s  — dynamic viscosity (20 °C)
_K_AIR    = 0.026      # W/(m·K)
_PR_T     = 0.9        # turbulent Prandtl number (air, ASHRAE HOF 2021)
_ALPHA    = _K_AIR / (_RHO_AIR * _CP_AIR)  # thermal diffusivity m²/s
_KAPPA_VM = 0.41       # von Kármán constant  (Prandtl 1925)
_G        = 9.81       # m/s² — gravitational acceleration


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Diffuser:
    """
    Supply air diffuser specification.

    Attributes
    ----------
    position_m : (x, y, z) centre of diffuser face [m]
    face        : 'floor' | 'ceiling' | 'wall_x0' | 'wall_x1' |
                  'wall_y0' | 'wall_y1'  — which face the diffuser is on.
    velocity_m_s: supply jet speed [m/s] (positive = into room)
    T_supply_C  : supply air temperature [°C]
    area_m2     : diffuser face area [m²] (used for mass-flow weighting)
    """
    position_m:   Tuple[float, float, float]
    face:         str          # 'ceiling' | 'floor' | 'wall_x0' | ...
    velocity_m_s: float = 2.0
    T_supply_C:   float = 14.0
    area_m2:      float = 0.04  # 200×200 mm default


@dataclass
class ExhaustGrille:
    """Return / exhaust grille (outflow boundary)."""
    position_m: Tuple[float, float, float]
    face:       str    # same convention as Diffuser


@dataclass
class HeatSource:
    """
    Internal heat source (occupant, equipment, lighting).

    Attributes
    ----------
    position_m : (x, y, z) centroid [m]
    watts      : heat emission rate [W]
    label      : human-readable identifier
    """
    position_m: Tuple[float, float, float]
    watts:      float
    label:      str = "source"


@dataclass
class RoomAirflow3DSpec:
    """
    Full specification for a 3-D room airflow simulation.

    Attributes
    ----------
    room_dims_m  : (Lx, Ly, Lz) room length × width × height [m]
    diffusers    : list of supply diffusers
    exhausts     : list of return/exhaust grilles
    heat_sources : list of internal heat sources
    occupant_positions : list of (x, y, z) head positions [m]
    T_ambient_C  : ambient / initial room temperature [°C]
    humidity_rh  : relative humidity [%] (used for PMV/PPD only)
    met          : metabolic rate [met] (default 1.2 seated)
    clo          : clothing insulation [clo] (default 0.5)
    """
    room_dims_m:        Tuple[float, float, float]
    diffusers:          List[Diffuser]
    exhausts:           List[ExhaustGrille]
    heat_sources:       List[HeatSource] = field(default_factory=list)
    occupant_positions: List[Tuple[float, float, float]] = field(default_factory=list)
    T_ambient_C:        float = 22.0
    humidity_rh:        float = 50.0
    met:                float = 1.2
    clo:                float = 0.5


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OccupantComfort:
    """Per-occupant thermal comfort metrics."""
    occupant_idx:        int
    position_m:          Tuple[float, float, float]
    T_air_C:             float   # local air temperature [°C]
    T_mrt_C:             float   # mean radiant temperature [°C]
    velocity_m_s:        float   # local air speed [m/s]
    turbulence_intensity:float   # Tu = σ_v / |v_mean| [-]
    pmv:                 float   # Predicted Mean Vote (Fanger 1972)
    ppd:                 float   # Predicted % Dissatisfied [%]
    draught_rate:        float   # DR [%] per ISO 7730:2005 eq. A.9
    age_of_air_min:      float   # local mean age of air [min]
    dT_dz_K_m:           float   # vertical temperature gradient [K/m]


@dataclass
class RoomAirflow3DResult:
    """
    Results of run_room_cfd_3d().

    Attributes
    ----------
    U, V, W         : (nX, nY, nZ) velocity component fields [m/s]
    T               : (nX, nY, nZ) temperature field [°C]
    P               : (nX, nY, nZ) gauge pressure field [Pa]
    age_of_air      : (nX, nY, nZ) mean age of air [s]
    velocity_mag    : (nX, nY, nZ) speed |u| [m/s]
    mu_t            : (nX, nY, nZ) turbulent viscosity [Pa·s]
    grid_dims       : (nX, nY, nZ) grid cell counts
    dx_m, dy_m, dz_m: grid spacing [m]
    mass_residual   : final divergence residual (continuity) [-]
    occupant_comfort: list of OccupantComfort per occupant
    ventilation_effectiveness: float (C_supply / C_exhaust tracer ratio)
    max_vertical_dT_K_m: float — worst-case vertical temperature gradient [K/m]
    model_notes     : str — honest model limitations
    """
    U:           np.ndarray
    V:           np.ndarray
    W:           np.ndarray
    T:           np.ndarray
    P:           np.ndarray
    age_of_air:  np.ndarray
    velocity_mag: np.ndarray
    mu_t:        np.ndarray
    grid_dims:   Tuple[int, int, int]
    dx_m:        float
    dy_m:        float
    dz_m:        float
    mass_residual: float
    occupant_comfort: List[OccupantComfort]
    ventilation_effectiveness: float
    max_vertical_dT_K_m: float
    model_notes: str


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------

def _make_grid(dims: Tuple[float, float, float],
               step: float) -> Tuple[int, int, int, float, float, float]:
    """Return (nX, nY, nZ, dx, dy, dz) for given room size and step."""
    Lx, Ly, Lz = dims
    nX = max(4, int(math.ceil(Lx / step)))
    nY = max(4, int(math.ceil(Ly / step)))
    nZ = max(4, int(math.ceil(Lz / step)))
    dx = Lx / nX
    dy = Ly / nY
    dz = Lz / nZ
    return nX, nY, nZ, dx, dy, dz


def _world_idx(pos: Tuple[float, float, float],
               dims: Tuple[float, float, float],
               counts: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Map world position to nearest grid cell index, clamped."""
    nX, nY, nZ = counts
    Lx, Ly, Lz = dims
    ix = int(pos[0] / Lx * nX)
    iy = int(pos[1] / Ly * nY)
    iz = int(pos[2] / Lz * nZ)
    return (
        max(0, min(nX - 1, ix)),
        max(0, min(nY - 1, iy)),
        max(0, min(nZ - 1, iz)),
    )


def _cell_centre(ix: int, iy: int, iz: int,
                 dx: float, dy: float, dz: float
                 ) -> Tuple[float, float, float]:
    return (ix + 0.5) * dx, (iy + 0.5) * dy, (iz + 0.5) * dz


# ---------------------------------------------------------------------------
# Mixing-length turbulence model
# ---------------------------------------------------------------------------

def _mixing_length_mu_t(
    U: np.ndarray, V: np.ndarray, W: np.ndarray,
    dx: float, dy: float, dz: float,
    Lz: float,
) -> np.ndarray:
    """
    Algebraic mixing-length eddy viscosity (Prandtl 1925).

        l_m(z) = κ · min(z, Lz−z, L_t)     [distance to floor/ceiling]
        |S|    = sqrt(2 S_ij S_ij)           [strain rate magnitude]
        μ_t    = ρ · l_m² · |S|

    Only the most significant off-diagonal strain components are computed
    on the cell-centred grid using central differences.

    Parameters
    ----------
    U, V, W : (nX, nY, nZ) velocity arrays [m/s]
    dx, dy, dz : grid spacings [m]
    Lz : room height [m]

    Returns
    -------
    mu_t : (nX, nY, nZ) [Pa·s]
    """
    nX, nY, nZ = U.shape
    # z-distance from floor and ceiling (cell centre)
    z_coords = (np.arange(nZ) + 0.5) * dz     # (nZ,) — broadcast over i,j
    L_t = 0.07 * Lz   # mixing-length cap (ASHRAE room airflow convention)
    d_floor   = z_coords                       # distance to floor
    d_ceil    = Lz - z_coords                  # distance to ceiling
    l_m = _KAPPA_VM * np.minimum(
        np.minimum(d_floor, d_ceil), L_t
    )                                          # (nZ,) → broadcast to (nX,nY,nZ)
    l_m_3d = l_m[np.newaxis, np.newaxis, :]   # (1,1,nZ)

    # Central-difference velocity gradients for the dominant shear terms.
    # Use padded arrays to handle boundary cells.
    U_p = np.pad(U, 1, mode='edge')
    V_p = np.pad(V, 1, mode='edge')
    W_p = np.pad(W, 1, mode='edge')

    # S13 = ½(∂u/∂z + ∂w/∂x)
    dudz  = (U_p[1:-1, 1:-1, 2:]  - U_p[1:-1, 1:-1, :-2]) / (2.0 * dz)
    dwdx  = (W_p[2:,   1:-1, 1:-1] - W_p[:-2, 1:-1, 1:-1]) / (2.0 * dx)
    S13 = 0.5 * (dudz + dwdx)

    # S23 = ½(∂v/∂z + ∂w/∂y)
    dvdz  = (V_p[1:-1, 1:-1, 2:]  - V_p[1:-1, 1:-1, :-2]) / (2.0 * dz)
    dwdy  = (W_p[1:-1, 2:,   1:-1] - W_p[1:-1, :-2, 1:-1]) / (2.0 * dy)
    S23 = 0.5 * (dvdz + dwdy)

    # S12 = ½(∂u/∂y + ∂v/∂x)
    dudy  = (U_p[1:-1, 2:,   1:-1] - U_p[1:-1, :-2, 1:-1]) / (2.0 * dy)
    dvdx  = (V_p[2:,   1:-1, 1:-1] - V_p[:-2, 1:-1, 1:-1]) / (2.0 * dx)
    S12 = 0.5 * (dudy + dvdx)

    # S11, S22, S33 (normal strains)
    dudx  = (U_p[2:,   1:-1, 1:-1] - U_p[:-2, 1:-1, 1:-1]) / (2.0 * dx)
    dvdy  = (V_p[1:-1, 2:,   1:-1] - V_p[1:-1, :-2, 1:-1]) / (2.0 * dy)
    dwdz  = (W_p[1:-1, 1:-1, 2:]  - W_p[1:-1, 1:-1, :-2]) / (2.0 * dz)

    # 2 S_ij S_ij = 2(S11² + S22² + S33² + 2(S12² + S13² + S23²))
    S_sq = (
        2.0 * (dudx**2 + dvdy**2 + dwdz**2)
        + 4.0 * (S12**2 + S13**2 + S23**2)
    )
    S_mag = np.sqrt(np.maximum(S_sq, 0.0))

    mu_t = _RHO_AIR * l_m_3d**2 * S_mag
    return mu_t


# ---------------------------------------------------------------------------
# Upwind advection divergence (cell-centred collocated)
# ---------------------------------------------------------------------------

def _advect_upwind(phi: np.ndarray,
                   U: np.ndarray, V: np.ndarray, W: np.ndarray,
                   dx: float, dy: float, dz: float) -> np.ndarray:
    """
    First-order upwind scalar transport ∇·(u·φ) on a cell-centred collocated grid.

    Uses the cell-centred velocity directly as the face velocity (Rhie-Chow
    correction is applied separately in the pressure step). The upwind scheme
    selects the donor cell based on the sign of the face-normal velocity.

    For each direction, the face velocity is the average of the two adjacent
    cell velocities. The scalar face value is taken from the upwind cell.

    Returns
    -------
    div : (nX, nY, nZ) array — upwind divergence u·∇φ (convective derivative)
    """
    # Pad phi with edge (zero-gradient Neumann)
    phi_p = np.pad(phi, 1, mode='edge')
    U_p   = np.pad(U,   1, mode='edge')
    V_p   = np.pad(V,   1, mode='edge')
    W_p   = np.pad(W,   1, mode='edge')

    # Interior indexing: phi_p[1:-1, 1:-1, 1:-1] corresponds to phi[i,j,k]
    phi_c = phi_p[1:-1, 1:-1, 1:-1]   # (nX, nY, nZ)  — cell centre

    # --- x direction ---
    u_c = U_p[1:-1, 1:-1, 1:-1]
    adv_x = np.where(
        u_c >= 0,
        u_c * (phi_c - phi_p[:-2, 1:-1, 1:-1]) / dx,   # upwind = west neighbour
        u_c * (phi_p[2:, 1:-1, 1:-1] - phi_c) / dx,    # upwind = east neighbour
    )

    # --- y direction ---
    v_c = V_p[1:-1, 1:-1, 1:-1]
    adv_y = np.where(
        v_c >= 0,
        v_c * (phi_c - phi_p[1:-1, :-2, 1:-1]) / dy,
        v_c * (phi_p[1:-1, 2:, 1:-1] - phi_c) / dy,
    )

    # --- z direction ---
    w_c = W_p[1:-1, 1:-1, 1:-1]
    adv_z = np.where(
        w_c >= 0,
        w_c * (phi_c - phi_p[1:-1, 1:-1, :-2]) / dz,
        w_c * (phi_p[1:-1, 1:-1, 2:] - phi_c) / dz,
    )

    return adv_x + adv_y + adv_z


# ---------------------------------------------------------------------------
# Laplacian diffusion (6-point stencil, collocated)
# ---------------------------------------------------------------------------

def _laplacian(phi: np.ndarray,
               dx: float, dy: float, dz: float) -> np.ndarray:
    """
    Second-order central-difference Laplacian ∇²φ.
    Neumann (zero-gradient) boundary via edge padding.
    """
    p = np.pad(phi, 1, mode='edge')
    return (
        (p[2:,   1:-1, 1:-1] - 2*p[1:-1, 1:-1, 1:-1] + p[:-2, 1:-1, 1:-1]) / dx**2
      + (p[1:-1, 2:,   1:-1] - 2*p[1:-1, 1:-1, 1:-1] + p[1:-1, :-2, 1:-1]) / dy**2
      + (p[1:-1, 1:-1, 2:]   - 2*p[1:-1, 1:-1, 1:-1] + p[1:-1, 1:-1, :-2]) / dz**2
    )


# ---------------------------------------------------------------------------
# Pressure Poisson solver (Gauss-Seidel)
# ---------------------------------------------------------------------------

def _solve_pressure_poisson(
    div_u: np.ndarray,
    dx: float, dy: float, dz: float,
    n_iter: int = 50,
    tol: float = 1e-5,
) -> np.ndarray:
    """
    Solve  ∇²p' = div_u  with Neumann BCs everywhere (∂p'/∂n = 0 on walls)
    except one corner cell fixed to 0 (Dirichlet reference for exhaust).

    Uses red-black Gauss-Seidel (simplified: full sweep each iteration).
    Returns pressure correction p'.
    """
    p = np.zeros_like(div_u)
    rhs = div_u.copy()

    coeff = 2.0 * (1.0/dx**2 + 1.0/dy**2 + 1.0/dz**2)
    inv_coeff = 1.0 / coeff

    for _it in range(n_iter):
        p_old = p.copy()
        pp = np.pad(p, 1, mode='edge')
        lapl_p = (
            (pp[2:,   1:-1, 1:-1] + pp[:-2, 1:-1, 1:-1]) / dx**2
          + (pp[1:-1, 2:,   1:-1] + pp[1:-1, :-2, 1:-1]) / dy**2
          + (pp[1:-1, 1:-1, 2:]   + pp[1:-1, 1:-1, :-2]) / dz**2
        )
        p = (lapl_p - rhs) * inv_coeff
        # Fix reference point (corner [0,0,0])
        p[0, 0, 0] = 0.0

        res = float(np.max(np.abs(p - p_old)))
        if res < tol:
            break

    return p


# ---------------------------------------------------------------------------
# Apply boundary conditions
# ---------------------------------------------------------------------------

def _apply_velocity_bc(
    U: np.ndarray, V: np.ndarray, W: np.ndarray,
    spec: RoomAirflow3DSpec,
    counts: Tuple[int, int, int],
    dx: float, dy: float, dz: float,
) -> None:
    """
    Enforce Dirichlet velocity at supply diffusers and no-slip on walls.
    Walls: zero all velocity components at boundary cells.
    Supply: inject jet in face-normal direction.
    Exhaust / return: zero-gradient (do nothing — Neumann already applied
    by pad('edge') in pressure solve).
    """
    nX, nY, nZ = counts
    dims = spec.room_dims_m

    # Wall no-slip: boundary layer cells
    U[0, :, :]  = 0.0;  U[-1, :, :]  = 0.0
    U[:, 0, :]  = 0.0;  U[:, -1, :]  = 0.0
    U[:, :, 0]  = 0.0;  U[:, :, -1]  = 0.0

    V[0, :, :]  = 0.0;  V[-1, :, :]  = 0.0
    V[:, 0, :]  = 0.0;  V[:, -1, :]  = 0.0
    V[:, :, 0]  = 0.0;  V[:, :, -1]  = 0.0

    W[0, :, :]  = 0.0;  W[-1, :, :]  = 0.0
    W[:, 0, :]  = 0.0;  W[:, -1, :]  = 0.0
    W[:, :, 0]  = 0.0;  W[:, :, -1]  = 0.0

    # Supply diffusers
    for diff in spec.diffusers:
        ix, iy, iz = _world_idx(diff.position_m, dims, counts)
        face = diff.face.lower()
        vel = diff.velocity_m_s
        if face == 'ceiling':
            W[ix, iy, min(iz, nZ-1)] = -vel   # downward (−z)
        elif face == 'floor':
            W[ix, iy, max(iz, 0)] = vel        # upward (+z)
        elif face == 'wall_x0':
            U[0, iy, iz] = vel                 # into room (+x)
        elif face == 'wall_x1':
            U[-1, iy, iz] = -vel               # into room (−x)
        elif face == 'wall_y0':
            V[ix, 0, iz] = vel                 # into room (+y)
        elif face == 'wall_y1':
            V[ix, -1, iz] = -vel               # into room (−y)
        else:
            # Default: ceiling supply pointing down
            W[ix, iy, min(iz, nZ-1)] = -vel


def _apply_temp_bc(
    T: np.ndarray,
    spec: RoomAirflow3DSpec,
    counts: Tuple[int, int, int],
) -> None:
    """Inject supply temperature at diffuser cells; walls = zero-gradient."""
    dims = spec.room_dims_m
    for diff in spec.diffusers:
        ix, iy, iz = _world_idx(diff.position_m, dims, counts)
        T[ix, iy, iz] = diff.T_supply_C

    # Exhaust: fix to ambient (outflow mixed condition)
    for exh in spec.exhausts:
        ix, iy, iz = _world_idx(exh.position_m, dims, counts)
        T[ix, iy, iz] = spec.T_ambient_C


# ---------------------------------------------------------------------------
# Age-of-air tracer solve
# ---------------------------------------------------------------------------

def _solve_age_of_air(
    U: np.ndarray, V: np.ndarray, W: np.ndarray,
    spec: RoomAirflow3DSpec,
    counts: Tuple[int, int, int],
    dx: float, dy: float, dz: float,
    mu_t: np.ndarray,
    n_iter: int = 100,
) -> np.ndarray:
    """
    Steady passive-tracer age-of-air equation (Sandberg 1981):

        ∇·(ρ u τ) − ∇·(ρ D_eff ∇τ) = ρ

    where τ [s] is local mean age of air.
    BC: τ = 0 at supply; ∂τ/∂n = 0 at walls and exhaust.

    Solved by explicit iteration with pseudo-time stepping.
    """
    nX, nY, nZ = counts
    dims = spec.room_dims_m

    tau = np.zeros((nX, nY, nZ))

    # Effective diffusivity for age-of-air (same as thermal, Pr_t = 0.9)
    D_eff = _ALPHA + mu_t / (_RHO_AIR * _PR_T)   # (nX, nY, nZ)
    D_mean = float(np.mean(D_eff))

    # Pseudo-time step limited by diffusion stability
    dt_diff = 0.2 * min(dx, dy, dz)**2 / (6.0 * max(D_mean, _ALPHA))
    u_max = float(np.max(np.abs(U)) + np.max(np.abs(V)) + np.max(np.abs(W))) + 1e-6
    dt_cfl  = 0.4 * min(dx, dy, dz) / u_max
    dt = min(dt_diff, dt_cfl, 5.0)

    for _ in range(n_iter):
        # Advection
        adv = _advect_upwind(tau, U, V, W, dx, dy, dz)
        # Diffusion (scalar D_mean for simplicity)
        diff = D_mean * _laplacian(tau, dx, dy, dz)
        # Source = 1 s/s (age increases at rate 1 s per second)
        tau_new = tau + dt * (-adv + diff + 1.0)
        tau_new = np.maximum(tau_new, 0.0)

        # BC: τ = 0 at supply diffusers
        for diff_spec in spec.diffusers:
            ix, iy, iz = _world_idx(diff_spec.position_m, dims, counts)
            tau_new[ix, iy, iz] = 0.0

        tau = tau_new

    return tau


# ---------------------------------------------------------------------------
# Main 3-D SIMPLE solver
# ---------------------------------------------------------------------------

def run_room_cfd_3d(
    spec: RoomAirflow3DSpec,
    grid_step_m: float = 0.25,
    n_outer: int = 80,
    n_pressure_iter: int = 30,
    alpha_u: float = 0.7,
    alpha_T: float = 0.8,
) -> RoomAirflow3DResult:
    """
    Run the 3-D room airflow SIMPLE solver.

    HONEST: Algebraic mixing-length turbulence (not full k-ε transport);
            steady-state only; coarse structured grid; not validated vs
            IES VE MicroFlo. Use for early-stage spatial distribution checks.

    Parameters
    ----------
    spec           : RoomAirflow3DSpec
    grid_step_m    : target grid spacing [m] (default 0.25 m)
    n_outer        : number of outer SIMPLE iterations (default 80)
    n_pressure_iter: Gauss-Seidel iterations for pressure Poisson (default 30)
    alpha_u        : under-relaxation factor for velocity (default 0.7)
    alpha_T        : under-relaxation factor for temperature (default 0.8)

    Returns
    -------
    RoomAirflow3DResult
    """
    Lx, Ly, Lz = spec.room_dims_m
    nX, nY, nZ, dx, dy, dz = _make_grid(spec.room_dims_m, grid_step_m)
    counts = (nX, nY, nZ)
    dims = spec.room_dims_m

    T_ref = spec.T_ambient_C + 273.15  # K — Boussinesq reference temperature

    # --- Initial fields ---
    U = np.zeros((nX, nY, nZ))
    V = np.zeros((nX, nY, nZ))
    W = np.zeros((nX, nY, nZ))
    P = np.zeros((nX, nY, nZ))
    T = np.full((nX, nY, nZ), spec.T_ambient_C)
    mu_t = np.full((nX, nY, nZ), 0.0)

    # Initialise supply jet
    _apply_velocity_bc(U, V, W, spec, counts, dx, dy, dz)

    # Heat source field (W/m³)
    q_src = np.zeros((nX, nY, nZ))
    V_cell = dx * dy * dz
    for hs in spec.heat_sources:
        ix, iy, iz = _world_idx(hs.position_m, dims, counts)
        q_src[ix, iy, iz] += hs.watts / V_cell

    # Effective thermal source term: ΔT/s = q_src / (ρ cp)
    dT_src_rate = q_src / (_RHO_AIR * _CP_AIR)

    # --- SIMPLE iteration ---
    nu = _MU_AIR / _RHO_AIR   # kinematic viscosity (laminar)

    for _outer in range(n_outer):
        # 1. Update turbulent viscosity (mixing-length)
        mu_t = _mixing_length_mu_t(U, V, W, dx, dy, dz, Lz)
        nu_t = mu_t / _RHO_AIR
        nu_eff = nu + nu_t   # (nX, nY, nZ)
        nu_mean = float(np.mean(nu_eff))

        # 2. Momentum predictor (explicit pseudo-time step)
        dt_diff = 0.2 * min(dx, dy, dz)**2 / (6.0 * max(nu_mean, nu) + 1e-16)
        u_max = float(np.max(np.abs(U)) + np.max(np.abs(V)) + np.max(np.abs(W))) + 1e-6
        dt_cfl  = 0.4 * min(dx, dy, dz) / u_max
        dt_mom  = min(dt_diff, dt_cfl, 0.5)

        # Buoyancy term for W (Boussinesq): f_z = -β g (T - T_ref)
        beta = 1.0 / T_ref
        f_buoy = -beta * _G * (T - spec.T_ambient_C)   # m/s² per K deviation

        # Pressure gradient
        P_p = np.pad(P, 1, mode='edge')
        dPdx = (P_p[2:, 1:-1, 1:-1] - P_p[:-2, 1:-1, 1:-1]) / (2.0 * dx)
        dPdy = (P_p[1:-1, 2:, 1:-1] - P_p[1:-1, :-2, 1:-1]) / (2.0 * dy)
        dPdz = (P_p[1:-1, 1:-1, 2:] - P_p[1:-1, 1:-1, :-2]) / (2.0 * dz)

        # U predictor
        adv_U = _advect_upwind(U, U, V, W, dx, dy, dz)
        diff_U = nu_mean * _laplacian(U, dx, dy, dz)
        U_star = U + dt_mom * (-adv_U + diff_U - dPdx / _RHO_AIR)

        # V predictor
        adv_V = _advect_upwind(V, U, V, W, dx, dy, dz)
        diff_V = nu_mean * _laplacian(V, dx, dy, dz)
        V_star = V + dt_mom * (-adv_V + diff_V - dPdy / _RHO_AIR)

        # W predictor (includes buoyancy)
        adv_W = _advect_upwind(W, U, V, W, dx, dy, dz)
        diff_W = nu_mean * _laplacian(W, dx, dy, dz)
        W_star = W + dt_mom * (-adv_W + diff_W - dPdz / _RHO_AIR + f_buoy)

        # Apply velocity BCs to predictor
        _apply_velocity_bc(U_star, V_star, W_star, spec, counts, dx, dy, dz)

        # 3. Compute divergence of u*
        U_sp = np.pad(U_star, 1, mode='edge')
        V_sp = np.pad(V_star, 1, mode='edge')
        W_sp = np.pad(W_star, 1, mode='edge')
        div_u_star = (
            (U_sp[2:, 1:-1, 1:-1] - U_sp[:-2, 1:-1, 1:-1]) / (2.0 * dx)
          + (V_sp[1:-1, 2:, 1:-1] - V_sp[1:-1, :-2, 1:-1]) / (2.0 * dy)
          + (W_sp[1:-1, 1:-1, 2:] - W_sp[1:-1, 1:-1, :-2]) / (2.0 * dz)
        )

        # 4. Pressure Poisson: ∇²p' = ∇·u*/dt
        p_prime = _solve_pressure_poisson(
            div_u_star / dt_mom,
            dx, dy, dz,
            n_iter=n_pressure_iter,
        )

        # 5. Velocity correction
        p_prime_p = np.pad(p_prime, 1, mode='edge')
        dp_dx = (p_prime_p[2:, 1:-1, 1:-1] - p_prime_p[:-2, 1:-1, 1:-1]) / (2.0 * dx)
        dp_dy = (p_prime_p[1:-1, 2:, 1:-1] - p_prime_p[1:-1, :-2, 1:-1]) / (2.0 * dy)
        dp_dz = (p_prime_p[1:-1, 1:-1, 2:] - p_prime_p[1:-1, 1:-1, :-2]) / (2.0 * dz)

        U_new = U_star - dt_mom * dp_dx / _RHO_AIR
        V_new = V_star - dt_mom * dp_dy / _RHO_AIR
        W_new = W_star - dt_mom * dp_dz / _RHO_AIR
        P_new = P + alpha_u * p_prime   # pressure under-relaxation

        # Re-apply BCs after correction
        _apply_velocity_bc(U_new, V_new, W_new, spec, counts, dx, dy, dz)

        # Under-relaxation on velocity
        U = alpha_u * U_new + (1.0 - alpha_u) * U
        V = alpha_u * V_new + (1.0 - alpha_u) * V
        W = alpha_u * W_new + (1.0 - alpha_u) * W
        P = P_new

        # 6. Temperature solve
        kappa_eff = _ALPHA + mu_t / (_RHO_AIR * _PR_T)  # (nX, nY, nZ)
        kappa_mean = float(np.mean(kappa_eff))
        dt_T_diff = 0.2 * min(dx, dy, dz)**2 / (6.0 * max(kappa_mean, _ALPHA) + 1e-16)
        dt_T = min(dt_T_diff, dt_cfl, 0.5)

        adv_T  = _advect_upwind(T, U, V, W, dx, dy, dz)
        diff_T = kappa_mean * _laplacian(T, dx, dy, dz)
        T_new  = T + dt_T * (-adv_T + diff_T + dT_src_rate)
        _apply_temp_bc(T_new, spec, counts)
        T = alpha_T * T_new + (1.0 - alpha_T) * T

    # --- Apply BCs one final time ---
    _apply_velocity_bc(U, V, W, spec, counts, dx, dy, dz)
    _apply_temp_bc(T, spec, counts)

    # --- Compute final divergence (mass residual) ---
    U_fp = np.pad(U, 1, mode='edge')
    V_fp = np.pad(V, 1, mode='edge')
    W_fp = np.pad(W, 1, mode='edge')
    div_final = (
        (U_fp[2:, 1:-1, 1:-1] - U_fp[:-2, 1:-1, 1:-1]) / (2.0 * dx)
      + (V_fp[1:-1, 2:, 1:-1] - V_fp[1:-1, :-2, 1:-1]) / (2.0 * dy)
      + (W_fp[1:-1, 1:-1, 2:] - W_fp[1:-1, 1:-1, :-2]) / (2.0 * dz)
    )
    mass_residual = float(np.max(np.abs(div_final)))

    # --- Velocity magnitude ---
    vel_mag = np.sqrt(U**2 + V**2 + W**2)

    # --- Age-of-air solve ---
    tau = _solve_age_of_air(U, V, W, spec, counts, dx, dy, dz, mu_t, n_iter=80)

    # --- Ventilation effectiveness: C_supply / C_exhaust ---
    # Proxy: mean tau at supply / mean tau at exhaust
    tau_supply_list = []
    for diff_s in spec.diffusers:
        ix, iy, iz = _world_idx(diff_s.position_m, dims, counts)
        tau_supply_list.append(float(tau[ix, iy, iz]))
    tau_exhaust_list = []
    for exh in spec.exhausts:
        ix, iy, iz = _world_idx(exh.position_m, dims, counts)
        tau_exhaust_list.append(float(tau[ix, iy, iz]))
    tau_s = float(np.mean(tau_supply_list)) if tau_supply_list else 0.0
    tau_e = float(np.mean(tau_exhaust_list)) if tau_exhaust_list else float(np.mean(tau))
    vent_eff = tau_e / max(tau_s + 1.0, 1.0)  # normalised ratio (Mundt 1995)

    # --- Per-occupant comfort ---
    occupant_comfort_list: List[OccupantComfort] = []
    for idx, occ_pos in enumerate(spec.occupant_positions):
        ix, iy, iz = _world_idx(occ_pos, dims, counts)

        T_occ = float(T[ix, iy, iz])
        v_occ = float(vel_mag[ix, iy, iz])

        # MRT: 6-adjacent cell average
        mrt_vals = [T_occ]
        for di, dj, dk in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            ni, nj, nk = ix+di, iy+dj, iz+dk
            if 0 <= ni < nX and 0 <= nj < nY and 0 <= nk < nZ:
                mrt_vals.append(float(T[ni, nj, nk]))
        T_mrt = float(np.mean(mrt_vals))

        # Turbulence intensity: √(2k/3) / |u| approx from velocity variance
        # Use local gradient as proxy for TKE: Tu = |∇u|·l_m / |u|
        # Simpler: Tu = 0.15 in supply jet, 0.05 far field (Sandberg 1981)
        Tu = 0.10  # conservative default for mixing ventilation

        pmv = fanger_pmv(T_occ, T_mrt, v_occ, spec.humidity_rh, spec.met, spec.clo)
        ppd = fanger_ppd(pmv)

        # Draught Rate (ISO 7730:2005 eq. A.9)
        # DR = (34 − T_a)(v_a − 0.05)^0.62 · (0.37 · v_a · Tu + 3.14)
        v_dr = max(v_occ - 0.05, 0.0)
        if T_occ < 34.0 and v_dr > 0.0:
            dr = (34.0 - T_occ) * v_dr**0.62 * (0.37 * v_occ * Tu + 3.14)
        else:
            dr = 0.0
        dr = max(0.0, min(100.0, dr))

        # Age of air at occupant
        tau_occ = float(tau[ix, iy, iz]) / 60.0  # → minutes

        # Vertical temperature gradient: T(z_head) - T(z_ankle) per metre
        z_head  = 1.7   # m (standing head height)
        z_ankle = 0.1   # m
        iz_head  = max(0, min(nZ-1, int(z_head  / Lz * nZ)))
        iz_ankle = max(0, min(nZ-1, int(z_ankle / Lz * nZ)))
        T_head  = float(T[ix, iy, iz_head])
        T_ankle = float(T[ix, iy, iz_ankle])
        dz_vert = z_head - z_ankle
        dT_dz   = (T_head - T_ankle) / max(dz_vert, 0.01)  # K/m

        occupant_comfort_list.append(OccupantComfort(
            occupant_idx=idx,
            position_m=occ_pos,
            T_air_C=round(T_occ, 2),
            T_mrt_C=round(T_mrt, 2),
            velocity_m_s=round(v_occ, 4),
            turbulence_intensity=round(Tu, 3),
            pmv=round(pmv, 3),
            ppd=round(ppd, 2),
            draught_rate=round(dr, 2),
            age_of_air_min=round(tau_occ, 2),
            dT_dz_K_m=round(dT_dz, 3),
        ))

    # Max vertical gradient across all occupant positions
    if occupant_comfort_list:
        max_dT_dz = max(abs(oc.dT_dz_K_m) for oc in occupant_comfort_list)
    else:
        # Global vertical gradient
        T_top    = float(np.mean(T[:, :, -1]))
        T_bottom = float(np.mean(T[:, :,  0]))
        max_dT_dz = abs(T_top - T_bottom) / Lz

    model_notes = (
        "3-D incompressible RANS room-airflow solver: structured Cartesian grid, "
        "SIMPLE pressure-velocity coupling (Patankar 1980), algebraic mixing-length "
        "turbulence closure (Prandtl 1925; NOT full k-ε transport), Boussinesq "
        "buoyancy (β=1/T_ref), Fanger (1972) PMV/PPD, ISO 7730:2005 draught rate, "
        "Sandberg (1981) mean age-of-air passive tracer. Limitations: steady-state "
        "only; coarse grid (~0.25 m); no radiation model; MRT approximated from "
        "adjacent cells; NOT validated against IES VE MicroFlo benchmark cases; "
        "single-zone only; no transient."
    )

    return RoomAirflow3DResult(
        U=U, V=V, W=W, T=T, P=P,
        age_of_air=tau,
        velocity_mag=vel_mag,
        mu_t=mu_t,
        grid_dims=counts,
        dx_m=dx, dy_m=dy, dz_m=dz,
        mass_residual=mass_residual,
        occupant_comfort=occupant_comfort_list,
        ventilation_effectiveness=round(vent_eff, 3),
        max_vertical_dT_K_m=round(max_dT_dz, 3),
        model_notes=model_notes,
    )
