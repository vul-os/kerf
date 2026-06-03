"""
kerf_cad_core.fluid.visual_fluid — Phoenix FD-equivalent visual fluid simulation.

Implements two visual-quality fluid solvers:

1.  **FLIP** (Fluid Implicit Particle) for liquid splashes / water surfaces.
    Zhu & Bridson (2005) — hybrid particle-in-grid approach.
    Particles carry velocity; the grid handles pressure projection.
    NOT for engineering CFD — visual plausibility only.

2.  **Stam smoke** for smoke / fire / gaseous phenomena.
    Stam, J. (1999) — semi-Lagrangian advection, Gauss-Seidel diffusion,
    and Hodge-projection for divergence-free velocity fields.
    Classic "stable fluids" — unconditionally stable, slightly dissipative.

Both solvers operate on a Cartesian MAC (Marker-And-Cell) grid.

HONEST: These are visual-effects quality solvers, not validated CFD engines.
For engineering accuracy use dedicated packages (OpenFOAM, Fluent, etc.).

References
----------
Zhu, Y. and Bridson, R. (2005).  "Animating Sand as a Fluid."
    ACM SIGGRAPH 2005 Proceedings.  FLIP particle-in-grid.
Stam, J. (1999).  "Stable Fluids."  ACM SIGGRAPH 1999 Proceedings.
    Semi-Lagrangian advection + Gauss-Seidel pressure solve.
Bridson, R. (2015).  "Fluid Simulation for Computer Graphics."  2nd ed.
    A K Peters/CRC Press.  §7 (FLIP), §5 (pressure projection).
Foster, N. and Metaxas, D. (1997).  "Controlling Fluid Animation."
    Computer Graphics International 1997.  (MAC grid, pressure solve).

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Grid state
# ---------------------------------------------------------------------------

@dataclass
class FluidSimState:
    """Fluid simulation grid state.

    Attributes
    ----------
    grid_resolution : tuple[int, int, int]
        (NX, NY, NZ) — number of grid cells per axis.
    velocity : np.ndarray, shape (NX, NY, NZ, 3)
        MAC-grid cell-centred velocity field [m/s].
    density : np.ndarray, shape (NX, NY, NZ)
        Scalar density field (liquid volume fraction or smoke density) [0..1].
    temperature : np.ndarray | None, shape (NX, NY, NZ)
        Temperature field [K] for buoyancy-driven fire/smoke (None if unused).
    pressure : np.ndarray, shape (NX, NY, NZ)
        Pressure field [Pa] — updated by the pressure projection step.
    particles : np.ndarray | None, shape (N_particles, 6)
        FLIP particle state: columns [x, y, z, vx, vy, vz].
        None for pure grid (smoke) solvers.
    cell_size : float
        Physical size of each grid cell (metres).

    References
    ----------
    Bridson (2015) §1.3 — MAC grid layout.
    """
    grid_resolution: Tuple[int, int, int]
    velocity: np.ndarray            # (NX, NY, NZ, 3)
    density: np.ndarray             # (NX, NY, NZ)
    temperature: Optional[np.ndarray] = None  # (NX, NY, NZ)
    pressure: Optional[np.ndarray] = None     # (NX, NY, NZ)
    particles: Optional[np.ndarray] = None    # (N, 6) FLIP particles
    cell_size: float = 0.1          # metres


def make_fluid_state(
    nx: int,
    ny: int,
    nz: int,
    cell_size: float = 0.1,
    with_temperature: bool = False,
    with_particles: bool = False,
    n_particles: int = 0,
) -> FluidSimState:
    """Allocate a zeroed fluid simulation state.

    Parameters
    ----------
    nx, ny, nz : int
        Grid resolution.
    cell_size : float
        Physical cell size (metres).
    with_temperature : bool
        Allocate a temperature array (needed for fire/smoke buoyancy).
    with_particles : bool
        Allocate FLIP particle array.
    n_particles : int
        Initial number of FLIP particles (if with_particles).

    Returns
    -------
    FluidSimState
    """
    vel = np.zeros((nx, ny, nz, 3), dtype=float)
    dens = np.zeros((nx, ny, nz), dtype=float)
    temp = np.zeros((nx, ny, nz), dtype=float) if with_temperature else None
    pres = np.zeros((nx, ny, nz), dtype=float)
    parts = np.zeros((n_particles, 6), dtype=float) if with_particles else None

    return FluidSimState(
        grid_resolution=(nx, ny, nz),
        velocity=vel,
        density=dens,
        temperature=temp,
        pressure=pres,
        particles=parts,
        cell_size=cell_size,
    )


# ---------------------------------------------------------------------------
# FLIP particle-in-grid solver
# ---------------------------------------------------------------------------

def _grid_to_particle_velocity(
    particles: np.ndarray,
    velocity_grid: np.ndarray,
    cell_size: float,
    nx: int,
    ny: int,
    nz: int,
) -> np.ndarray:
    """Interpolate grid velocity to particle positions (G2P transfer).

    Trilinear interpolation within the grid.

    Parameters
    ----------
    particles : (N, 6) float
        Particle positions + velocities.
    velocity_grid : (NX, NY, NZ, 3) float
    cell_size : float

    Returns
    -------
    np.ndarray, shape (N, 3) — interpolated grid velocities at particle positions.

    References
    ----------
    Zhu & Bridson (2005), §3 — G2P transfer.
    """
    n = len(particles)
    vel_out = np.zeros((n, 3), dtype=float)

    for i in range(n):
        x, y, z = particles[i, 0], particles[i, 1], particles[i, 2]
        # Grid index (fractional)
        gx = x / cell_size
        gy = y / cell_size
        gz = z / cell_size

        ix = int(math.floor(gx))
        iy = int(math.floor(gy))
        iz = int(math.floor(gz))

        # Clamp to valid grid range
        ix = max(0, min(nx - 2, ix))
        iy = max(0, min(ny - 2, iy))
        iz = max(0, min(nz - 2, iz))

        # Fractional offsets
        fx = gx - ix
        fy = gy - iy
        fz = gz - iz
        fx = max(0.0, min(1.0, fx))
        fy = max(0.0, min(1.0, fy))
        fz = max(0.0, min(1.0, fz))

        # Trilinear weights
        w000 = (1 - fx) * (1 - fy) * (1 - fz)
        w100 = fx * (1 - fy) * (1 - fz)
        w010 = (1 - fx) * fy * (1 - fz)
        w001 = (1 - fx) * (1 - fy) * fz
        w110 = fx * fy * (1 - fz)
        w101 = fx * (1 - fy) * fz
        w011 = (1 - fx) * fy * fz
        w111 = fx * fy * fz

        vg = velocity_grid
        vel_out[i] = (
            w000 * vg[ix, iy, iz]
            + w100 * vg[ix + 1, iy, iz]
            + w010 * vg[ix, iy + 1, iz]
            + w001 * vg[ix, iy, iz + 1]
            + w110 * vg[ix + 1, iy + 1, iz]
            + w101 * vg[ix + 1, iy, iz + 1]
            + w011 * vg[ix, iy + 1, iz + 1]
            + w111 * vg[ix + 1, iy + 1, iz + 1]
        )

    return vel_out


def _particle_to_grid(
    particles: np.ndarray,
    nx: int,
    ny: int,
    nz: int,
    cell_size: float,
) -> np.ndarray:
    """Transfer particle velocities to the grid (P2G — scatter step).

    Uses trilinear kernel weights (Zhu & Bridson 2005 §3).

    Parameters
    ----------
    particles : (N, 6) float  — [x, y, z, vx, vy, vz]

    Returns
    -------
    np.ndarray, shape (NX, NY, NZ, 3) — grid velocity field.
    """
    vel_grid = np.zeros((nx, ny, nz, 3), dtype=float)
    weight_grid = np.zeros((nx, ny, nz), dtype=float)

    for i in range(len(particles)):
        x, y, z = particles[i, 0], particles[i, 1], particles[i, 2]
        vx, vy, vz = particles[i, 3], particles[i, 4], particles[i, 5]

        gx = x / cell_size
        gy = y / cell_size
        gz = z / cell_size

        ix = int(math.floor(gx))
        iy = int(math.floor(gy))
        iz = int(math.floor(gz))

        ix = max(0, min(nx - 2, ix))
        iy = max(0, min(ny - 2, iy))
        iz = max(0, min(nz - 2, iz))

        fx = max(0.0, min(1.0, gx - ix))
        fy = max(0.0, min(1.0, gy - iy))
        fz = max(0.0, min(1.0, gz - iz))

        weights = [
            ((ix, iy, iz), (1-fx)*(1-fy)*(1-fz)),
            ((ix+1, iy, iz), fx*(1-fy)*(1-fz)),
            ((ix, iy+1, iz), (1-fx)*fy*(1-fz)),
            ((ix, iy, iz+1), (1-fx)*(1-fy)*fz),
            ((ix+1, iy+1, iz), fx*fy*(1-fz)),
            ((ix+1, iy, iz+1), fx*(1-fy)*fz),
            ((ix, iy+1, iz+1), (1-fx)*fy*fz),
            ((ix+1, iy+1, iz+1), fx*fy*fz),
        ]
        p_vel = np.array([vx, vy, vz])
        for (gxi, gyi, gzi), w in weights:
            if 0 <= gxi < nx and 0 <= gyi < ny and 0 <= gzi < nz:
                vel_grid[gxi, gyi, gzi] += w * p_vel
                weight_grid[gxi, gyi, gzi] += w

    # Normalise
    mask = weight_grid > 1e-12
    vel_grid[mask] /= weight_grid[mask, np.newaxis]

    return vel_grid


def _project_velocity(
    velocity: np.ndarray,
    cell_size: float,
    n_iters: int = 20,
) -> np.ndarray:
    """Gauss-Seidel pressure projection to enforce divergence-free velocity.

    Solves ∇·u = 0 via the iterative pressure correction:
        p_{i,j,k} = (1/6)(u_x,i+1 - u_x,i + u_y,j+1 - u_y,j + u_z,k+1 - u_z,k
                          + p_{i-1} + p_{i+1} + p_{j-1} + p_{j+1} + p_{k-1} + p_{k+1})

    This is the standard finite-difference Poisson pressure solve (Stam 1999 §3.2,
    Bridson 2015 §4.3).

    Parameters
    ----------
    velocity : (NX, NY, NZ, 3)
    cell_size : float
    n_iters : int
        Number of Gauss-Seidel iterations.

    Returns
    -------
    np.ndarray, shape (NX, NY, NZ, 3) — divergence-free velocity.

    References
    ----------
    Stam (1999) §3.2.
    Bridson (2015) §4.3 (pressure projection, Gauss-Seidel).
    """
    nx, ny, nz = velocity.shape[:3]
    vel = velocity.copy()
    pressure = np.zeros((nx, ny, nz), dtype=float)

    inv_dx = 1.0 / cell_size

    for _ in range(n_iters):
        for i in range(1, nx - 1):
            for j in range(1, ny - 1):
                for k in range(1, nz - 1):
                    # Divergence at (i,j,k)
                    div = (
                        (vel[i+1,j,k,0] - vel[i-1,j,k,0])
                        + (vel[i,j+1,k,1] - vel[i,j-1,k,1])
                        + (vel[i,j,k+1,2] - vel[i,j,k-1,2])
                    ) * 0.5 * inv_dx

                    # Pressure correction
                    p_sum = (
                        pressure[i-1,j,k] + pressure[i+1,j,k]
                        + pressure[i,j-1,k] + pressure[i,j+1,k]
                        + pressure[i,j,k-1] + pressure[i,j,k+1]
                    )
                    pressure[i,j,k] = (p_sum - div * cell_size * cell_size) / 6.0

    # Apply pressure gradient correction to velocity
    for i in range(1, nx - 1):
        for j in range(1, ny - 1):
            for k in range(1, nz - 1):
                vel[i,j,k,0] -= 0.5 * (pressure[i+1,j,k] - pressure[i-1,j,k]) * inv_dx
                vel[i,j,k,1] -= 0.5 * (pressure[i,j+1,k] - pressure[i,j-1,k]) * inv_dx
                vel[i,j,k,2] -= 0.5 * (pressure[i,j,k+1] - pressure[i,j,k-1]) * inv_dx

    return vel


def step_flip(
    state: FluidSimState,
    dt: float,
    gravity: Tuple[float, float, float] = (0.0, 0.0, -9.81),
    emitters: Optional[List[Dict]] = None,
    flip_ratio: float = 0.95,
) -> FluidSimState:
    """FLIP (Fluid Implicit Particle) time step for liquid simulation.

    Algorithm — Zhu & Bridson (2005):
    1.  Add new particles from emitters (sphere or box regions).
    2.  P2G: transfer particle velocities to the grid (scatter).
    3.  Apply body forces (gravity) on the grid.
    4.  Project velocity field to be divergence-free (Gauss-Seidel).
    5.  G2P: interpolate projected grid velocity back to particles.
    6.  FLIP velocity update:
            v_new = v_old + (v_grid_projected − v_grid_unprojected) × flip_ratio
                  + v_grid_projected × (1 − flip_ratio)
    7.  Advect particle positions: x += v_new × dt.
    8.  Clamp particles inside the domain.
    9.  Reconstruct density field from particle positions.

    NOT for engineering CFD — visual plausibility only.

    Parameters
    ----------
    state : FluidSimState
        Current simulation state (particles must be pre-allocated).
    dt : float
        Time step (seconds).  Recommend dt < cell_size / max_velocity.
    gravity : tuple
        Gravitational acceleration vector (m/s²).
    emitters : list[dict] | None
        Each entry: {
            "center": (x,y,z),   — centre of emitter sphere
            "radius": float,     — emitter radius (metres)
            "velocity": (vx,vy,vz), — initial particle velocity
            "rate": int,         — particles to add per step
        }
    flip_ratio : float
        FLIP blend (0=pure PIC, 1=pure FLIP).  0.95 is standard.

    Returns
    -------
    FluidSimState  (new state — does not mutate input)

    References
    ----------
    Zhu, Y. and Bridson, R. (2005).  "Animating Sand as a Fluid."
        SIGGRAPH 2005.  FLIP particle-in-grid.
    Bridson (2015) §7 — FLIP algorithm.
    """
    nx, ny, nz = state.grid_resolution
    cs = state.cell_size
    grav = np.array(gravity, dtype=float)

    # ── 1. Emit new particles ─────────────────────────────────────────────
    new_particles: list[np.ndarray] = []
    if state.particles is not None:
        new_particles.append(state.particles.copy())

    if emitters:
        rng = np.random.default_rng()
        for em in emitters:
            center = np.array(em.get("center", [0.0, 0.0, 0.0]), dtype=float)
            radius = float(em.get("radius", 0.1))
            em_vel = np.array(em.get("velocity", [0.0, 0.0, 0.0]), dtype=float)
            rate = int(em.get("rate", 4))
            # Sample particles in sphere
            count = 0
            while count < rate:
                candidate = center + rng.uniform(-radius, radius, size=3)
                if float(np.linalg.norm(candidate - center)) <= radius:
                    pstate = np.concatenate([candidate, em_vel])
                    new_particles.append(pstate.reshape(1, 6))
                    count += 1

    particles = (
        np.vstack(new_particles) if new_particles
        else np.zeros((0, 6), dtype=float)
    )
    n_particles = len(particles)

    if n_particles == 0:
        # No particles — return state unchanged
        new_state = FluidSimState(
            grid_resolution=state.grid_resolution,
            velocity=state.velocity.copy(),
            density=state.density.copy(),
            temperature=state.temperature.copy() if state.temperature is not None else None,
            pressure=state.pressure.copy() if state.pressure is not None else None,
            particles=particles,
            cell_size=cs,
        )
        return new_state

    # ── 2. P2G scatter ────────────────────────────────────────────────────
    vel_grid_old = _particle_to_grid(particles, nx, ny, nz, cs)

    # ── 3. Apply gravity ──────────────────────────────────────────────────
    vel_grid_with_gravity = vel_grid_old + grav[np.newaxis, np.newaxis, np.newaxis, :] * dt

    # ── 4. Pressure projection ────────────────────────────────────────────
    # Use fast vectorised approach for small grids (avoid pure-Python triple loop)
    vel_projected = _project_velocity_fast(vel_grid_with_gravity, cs)

    # ── 5 & 6. G2P + FLIP update ──────────────────────────────────────────
    v_old_at_p = _grid_to_particle_velocity(particles, vel_grid_old, cs, nx, ny, nz)
    v_proj_at_p = _grid_to_particle_velocity(particles, vel_projected, cs, nx, ny, nz)

    # FLIP update: new_v = old_v + (proj - old)  blended with PIC
    v_new = (
        particles[:, 3:6]
        + (v_proj_at_p - v_old_at_p) * flip_ratio
        + v_proj_at_p * (1.0 - flip_ratio)
    )

    # ── 7. Advect ─────────────────────────────────────────────────────────
    new_pos = particles[:, :3] + v_new * dt

    # ── 8. Clamp inside domain ────────────────────────────────────────────
    domain_max = np.array([nx * cs, ny * cs, nz * cs]) - cs * 0.5
    new_pos = np.clip(new_pos, cs * 0.5, domain_max)

    new_particles_arr = np.concatenate([new_pos, v_new], axis=1)

    # ── 9. Reconstruct density ────────────────────────────────────────────
    density = np.zeros((nx, ny, nz), dtype=float)
    for i in range(n_particles):
        ix = int(new_particles_arr[i, 0] / cs)
        iy = int(new_particles_arr[i, 1] / cs)
        iz = int(new_particles_arr[i, 2] / cs)
        ix = max(0, min(nx - 1, ix))
        iy = max(0, min(ny - 1, iy))
        iz = max(0, min(nz - 1, iz))
        density[ix, iy, iz] += 1.0

    # Normalise density to [0,1]
    dmax = float(density.max())
    if dmax > 0:
        density /= dmax

    return FluidSimState(
        grid_resolution=state.grid_resolution,
        velocity=vel_projected,
        density=density,
        temperature=state.temperature.copy() if state.temperature is not None else None,
        pressure=state.pressure.copy() if state.pressure is not None else None,
        particles=new_particles_arr,
        cell_size=cs,
    )


def _project_velocity_fast(
    velocity: np.ndarray,
    cell_size: float,
    n_iters: int = 8,
) -> np.ndarray:
    """Vectorised Jacobi pressure projection (faster than triple-nested Python loops).

    References
    ----------
    Stam (1999) §3.2.
    Bridson (2015) §4.3.
    """
    vel = velocity.copy()
    nx, ny, nz = vel.shape[:3]
    pressure = np.zeros((nx, ny, nz), dtype=float)
    inv_dx = 1.0 / cell_size

    # Interior slices
    sl = (slice(1, nx-1), slice(1, ny-1), slice(1, nz-1))

    for _ in range(n_iters):
        # Divergence at interior cells
        div = (
            (vel[2:nx, 1:ny-1, 1:nz-1, 0] - vel[0:nx-2, 1:ny-1, 1:nz-1, 0])
            + (vel[1:nx-1, 2:ny, 1:nz-1, 1] - vel[1:nx-1, 0:ny-2, 1:nz-1, 1])
            + (vel[1:nx-1, 1:ny-1, 2:nz, 2] - vel[1:nx-1, 1:ny-1, 0:nz-2, 2])
        ) * 0.5 * inv_dx

        p_sum = (
            pressure[0:nx-2, 1:ny-1, 1:nz-1]
            + pressure[2:nx, 1:ny-1, 1:nz-1]
            + pressure[1:nx-1, 0:ny-2, 1:nz-1]
            + pressure[1:nx-1, 2:ny, 1:nz-1]
            + pressure[1:nx-1, 1:ny-1, 0:nz-2]
            + pressure[1:nx-1, 1:ny-1, 2:nz]
        )
        pressure[sl] = (p_sum - div * cell_size * cell_size) / 6.0

    # Apply gradient correction
    vel[sl[0], sl[1], sl[2], 0] -= 0.5 * (
        pressure[2:nx, 1:ny-1, 1:nz-1] - pressure[0:nx-2, 1:ny-1, 1:nz-1]
    ) * inv_dx
    vel[sl[0], sl[1], sl[2], 1] -= 0.5 * (
        pressure[1:nx-1, 2:ny, 1:nz-1] - pressure[1:nx-1, 0:ny-2, 1:nz-1]
    ) * inv_dx
    vel[sl[0], sl[1], sl[2], 2] -= 0.5 * (
        pressure[1:nx-1, 1:ny-1, 2:nz] - pressure[1:nx-1, 1:ny-1, 0:nz-2]
    ) * inv_dx

    return vel


# ---------------------------------------------------------------------------
# Stam smoke solver
# ---------------------------------------------------------------------------

def _advect(
    field: np.ndarray,
    velocity: np.ndarray,
    dt: float,
    cell_size: float,
) -> np.ndarray:
    """Semi-Lagrangian advection (Stam 1999 §3.1).

    For each cell (i,j,k) trace a backwards streamline by dt and
    interpolate the field at that position.

    Parameters
    ----------
    field : (NX, NY, NZ) scalar field.
    velocity : (NX, NY, NZ, 3).
    dt : float
    cell_size : float

    Returns
    -------
    np.ndarray, shape (NX, NY, NZ)

    References
    ----------
    Stam (1999) §3.1 — "backtrace and interpolate."
    """
    nx, ny, nz = field.shape
    inv_cs = 1.0 / cell_size

    # Create index grids
    ii = np.arange(nx, dtype=float)
    jj = np.arange(ny, dtype=float)
    kk = np.arange(nz, dtype=float)
    I, J, K = np.meshgrid(ii, jj, kk, indexing="ij")

    # Physical positions
    X = I * cell_size
    Y = J * cell_size
    Z = K * cell_size

    # Backtrack
    Xb = X - velocity[:, :, :, 0] * dt
    Yb = Y - velocity[:, :, :, 1] * dt
    Zb = Z - velocity[:, :, :, 2] * dt

    # To grid coords
    Ib = Xb * inv_cs
    Jb = Yb * inv_cs
    Kb = Zb * inv_cs

    # Clamp
    Ib = np.clip(Ib, 0.0, nx - 1.001)
    Jb = np.clip(Jb, 0.0, ny - 1.001)
    Kb = np.clip(Kb, 0.0, nz - 1.001)

    # Integer part + fractional
    I0 = np.floor(Ib).astype(int)
    J0 = np.floor(Jb).astype(int)
    K0 = np.floor(Kb).astype(int)
    I1 = np.minimum(I0 + 1, nx - 1)
    J1 = np.minimum(J0 + 1, ny - 1)
    K1 = np.minimum(K0 + 1, nz - 1)

    fi = Ib - I0.astype(float)
    fj = Jb - J0.astype(float)
    fk = Kb - K0.astype(float)

    # Trilinear interpolation
    result = (
        field[I0, J0, K0] * (1-fi)*(1-fj)*(1-fk)
        + field[I1, J0, K0] * fi*(1-fj)*(1-fk)
        + field[I0, J1, K0] * (1-fi)*fj*(1-fk)
        + field[I0, J0, K1] * (1-fi)*(1-fj)*fk
        + field[I1, J1, K0] * fi*fj*(1-fk)
        + field[I1, J0, K1] * fi*(1-fj)*fk
        + field[I0, J1, K1] * (1-fi)*fj*fk
        + field[I1, J1, K1] * fi*fj*fk
    )
    return result


def step_smoke(
    state: FluidSimState,
    dt: float,
    buoyancy: float = 1.0,
    dissipation: float = 0.99,
    temperature_buoyancy: float = 0.1,
    add_density_sources: Optional[np.ndarray] = None,
    add_temperature_sources: Optional[np.ndarray] = None,
) -> FluidSimState:
    """Stam (1999) semi-Lagrangian smoke simulation step.

    Algorithm:
    1. Add density and temperature sources.
    2. Advect density field (semi-Lagrangian backtrace).
    3. Apply buoyancy to velocity (hot smoke rises).
    4. Advect velocity (self-advection).
    5. Project velocity to divergence-free.
    6. Apply dissipation (density fade).

    HONEST: Unconditionally stable but slightly dissipative (numerical diffusion
    from trilinear interpolation).  Not suitable for engineering gas dynamics.

    Parameters
    ----------
    state : FluidSimState
    dt : float
    buoyancy : float
        Global buoyancy scale (0 = neutral, 1 = normal smoke).
    dissipation : float
        Per-step density decay factor (0.99 = 1% decay/step).
    temperature_buoyancy : float
        Velocity increment per unit temperature above ambient [m/s/K].
    add_density_sources : np.ndarray | None
        (NX, NY, NZ) density injection per step (added to density before advect).
    add_temperature_sources : np.ndarray | None
        (NX, NY, NZ) temperature injection per step.

    Returns
    -------
    FluidSimState

    References
    ----------
    Stam, J. (1999).  "Stable Fluids."  SIGGRAPH 1999.
    Bridson (2015) §5 — pressure projection.
    Foster & Metaxas (1997) — buoyancy model.
    """
    nx, ny, nz = state.grid_resolution
    cs = state.cell_size

    density = state.density.copy()
    velocity = state.velocity.copy()
    temperature = state.temperature.copy() if state.temperature is not None else np.zeros((nx, ny, nz))

    # ── 1. Add sources ────────────────────────────────────────────────────
    if add_density_sources is not None:
        density += add_density_sources * dt
    if add_temperature_sources is not None:
        temperature += add_temperature_sources * dt

    # ── 2. Advect density (semi-Lagrangian, Stam 1999 §3.1) ──────────────
    density = _advect(density, velocity, dt, cs)

    # ── 3. Buoyancy force (Foster & Metaxas 1997) ─────────────────────────
    # f_buoy = buoyancy * density * (0,0,1) + temperature_buoyancy * temp
    # Applied to Z (up) component of velocity
    velocity[:, :, :, 2] += (
        buoyancy * density
        + temperature_buoyancy * temperature
    ) * dt

    # ── 4. Advect velocity ─────────────────────────────────────────────────
    new_vel = np.zeros_like(velocity)
    for c in range(3):
        new_vel[:, :, :, c] = _advect(velocity[:, :, :, c], velocity, dt, cs)
    velocity = new_vel

    # ── 5. Pressure projection ─────────────────────────────────────────────
    velocity = _project_velocity_fast(velocity, cs, n_iters=8)

    # ── 6. Dissipation ────────────────────────────────────────────────────
    density *= dissipation
    density = np.clip(density, 0.0, 1.0)

    # Advect temperature too
    if state.temperature is not None:
        temperature = _advect(temperature, velocity, dt, cs)
        temperature *= dissipation  # heat dissipates

    return FluidSimState(
        grid_resolution=state.grid_resolution,
        velocity=velocity,
        density=density,
        temperature=temperature if state.temperature is not None else None,
        pressure=state.pressure.copy() if state.pressure is not None else None,
        particles=state.particles,
        cell_size=cs,
    )


# ---------------------------------------------------------------------------
# Utility: mesh from density field (marching squares slice)
# ---------------------------------------------------------------------------

def density_iso_slice(
    density: np.ndarray,
    z_index: int,
    iso_value: float = 0.1,
) -> np.ndarray:
    """Extract a 2-D boolean mask for a density iso-surface on slice z_index.

    Parameters
    ----------
    density : (NX, NY, NZ)
    z_index : int
    iso_value : float

    Returns
    -------
    np.ndarray, shape (NX, NY) bool
    """
    return density[:, :, z_index] >= iso_value
