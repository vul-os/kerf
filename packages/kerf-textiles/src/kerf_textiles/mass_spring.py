"""
kerf_textiles.mass_spring
=========================
Physically-based mass-spring-damper cloth simulator.

Method
------
Implements the Provot (1995) spring topology — structural, shear, and bend
springs — with semi-implicit (symplectic) Euler integration and Rayleigh-style
per-spring velocity damping along the spring axis.  This is the stable,
tractable core described in:

  * Provot, X. (1995). "Deformation constraints in a mass-spring model to
    describe rigid cloth behaviour." Graphics Interface, 147–154.
  * Baraff, D. & Witkin, A. (1998). "Large steps in cloth simulation."
    SIGGRAPH '98, 43–54.  (motivation for damping treatment)
  * Bridson, R., Marino, S., & Fedkiw, R. (2003). "Simulation of clothing
    with folds and wrinkles." SCA '03.  (collision response)
  * Choi, K.-J. & Ko, H.-S. (2002). "Stable but responsive cloth."
    SIGGRAPH '02, 604–611.  (stiffness for bending springs)

Architecture
------------
ClothMesh  — holds particle positions, velocities, masses, and spring
             topology (structural / shear / bend).

solve_step — single time-step using semi-implicit Euler (symplectic):
               1. Accumulate spring (Hooke + velocity-axis damping) +
                  gravity forces.
               2. Integrate velocity: v += (F/m) * dt.
               3. Apply per-step velocity damping: v *= velocity_damping.
               4. Integrate position: x += v * dt.
               5. Resolve collisions (projection + velocity correction).

             Auto-substep: the caller may pass any dt; the function
             automatically splits it into stable sub-steps based on the
             maximum spring stiffness.

Springs
-------
Structural springs  connect adjacent grid neighbours (N/S/E/W — 1 cell).
Shear springs       connect diagonal neighbours (NE/NW/SE/SW — √2 cells).
Bend springs        connect second neighbours (2 cells) to resist folding.
                    Stiffness from Choi-Ko (2002): k_bend should be 1–5% of
                    k_structural for physical realism.

Each spring carries a stiffness k (N/m) and a damping coefficient d (N·s/m).
The spring-axis viscous damping force is:

    F_damp = -d * (v_rel · n̂) * n̂

where v_rel = v_j − v_i and n̂ is the unit vector i→j.  This is numerically
stable in semi-implicit Euler because the force is evaluated at the current
step and the velocity update is implicit in the damping direction
(Baraff-Witkin appendix, simplified form).

Stability
---------
Explicit Euler on a spring-mass system is stable when

    dt_sub ≤ C * sqrt(m_min / k_max)

where C < 2 (theoretical) but we use C = 0.2 as a conservative safety
factor for the coupled 2-D lattice.  solve_step computes this automatically
and takes as many sub-steps as required.

Collision
---------
Three primitives:
  * SpherePrimitive    — solid sphere; particles projected to surface.
  * PlanePrimitive     — infinite horizontal plane at fixed y-height.
  * CapsulePrimitive   — capsule (line-segment swept sphere); used as an
                         avatar-limb stand-in (Bridson et al. 2003).

All collision responses use projection + velocity inversion along the normal
(no friction in this formulation; friction can be layered on top).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Vec3 helpers (pure Python — no numpy required)
# ---------------------------------------------------------------------------

Vec3 = tuple[float, float, float]


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vec3) -> Vec3:
    n = _norm(a)
    if n < 1e-15:
        return (0.0, 0.0, 0.0)
    return _scale(a, 1.0 / n)


def _lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """Linear interpolation between a and b."""
    return _add(_scale(a, 1.0 - t), _scale(b, t))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Spring definition
# ---------------------------------------------------------------------------

@dataclass
class Spring:
    """
    A spring connecting two particle indices.

    Forces applied per step (on particle i, negated on j):

        F_hooke =  k * (|pj - pi| - L0) * n̂
        F_damp  = -d * (vrel · n̂) * n̂     [spring-axis Rayleigh damping]

    References: Provot 1995, Baraff-Witkin 1998.
    """
    i: int
    j: int
    rest_length: float
    stiffness: float = 100.0
    damping: float = 0.5   # N·s/m; spring-axis viscous damping


# ---------------------------------------------------------------------------
# ClothMesh
# ---------------------------------------------------------------------------

@dataclass
class ClothMesh:
    """
    Grid cloth mesh: particles + structural/shear/bend spring topology.

    Parameters
    ----------
    rows, cols : int
        Particle grid dimensions.
    spacing : float
        Rest distance between adjacent particles (metres).
    mass : float
        Per-particle mass (kg).
    k_structural : float
        Stiffness of structural (edge) springs (N/m).
    k_shear : float
        Stiffness of shear (diagonal) springs (N/m).
    k_bend : float
        Stiffness of bending (skip-1) springs (N/m).
        Choi-Ko (2002) recommendation: 1–5% of k_structural.
    d_structural, d_shear, d_bend : float
        Spring-axis Rayleigh damping coefficients (N·s/m).
        Typical range: 0.1–2.0; set to 0 to disable.
    """

    rows: int
    cols: int
    spacing: float = 0.1
    mass: float = 0.01
    k_structural: float = 200.0
    k_shear: float = 100.0
    k_bend: float = 50.0
    d_structural: float = 0.5
    d_shear: float = 0.25
    d_bend: float = 0.1

    # Initialised in __post_init__
    positions: list[Vec3] = field(default_factory=list)
    velocities: list[Vec3] = field(default_factory=list)
    masses: list[float] = field(default_factory=list)
    pinned: list[bool] = field(default_factory=list)
    springs: list[Spring] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = self.rows * self.cols
        s = self.spacing
        # Flat grid in XZ plane (Y = 0, hangs downward under gravity).
        # Particles centred at origin.
        x0 = -(self.cols - 1) * s / 2.0
        z0 = -(self.rows - 1) * s / 2.0
        self.positions = [
            (x0 + c * s, 0.0, z0 + r * s)
            for r in range(self.rows)
            for c in range(self.cols)
        ]
        self.velocities = [(0.0, 0.0, 0.0)] * n
        self.masses = [self.mass] * n
        self.pinned = [False] * n
        self._build_springs()

    def _idx(self, r: int, c: int) -> int:
        return r * self.cols + c

    def _build_springs(self) -> None:
        springs: list[Spring] = []
        R, C = self.rows, self.cols
        s = self.spacing

        def add(i: int, j: int, L0: float, k: float, d: float) -> None:
            if k > 0.0:
                springs.append(Spring(i=i, j=j, rest_length=L0, stiffness=k, damping=d))

        for r in range(R):
            for c in range(C):
                idx = self._idx(r, c)
                # Structural — horizontal
                if c + 1 < C:
                    add(idx, self._idx(r, c + 1), s,
                        self.k_structural, self.d_structural)
                # Structural — vertical
                if r + 1 < R:
                    add(idx, self._idx(r + 1, c), s,
                        self.k_structural, self.d_structural)
                # Shear — diagonal NE
                if r + 1 < R and c + 1 < C:
                    add(idx, self._idx(r + 1, c + 1), s * math.sqrt(2),
                        self.k_shear, self.d_shear)
                # Shear — diagonal NW
                if r + 1 < R and c - 1 >= 0:
                    add(idx, self._idx(r + 1, c - 1), s * math.sqrt(2),
                        self.k_shear, self.d_shear)
                # Bend — skip-1 horizontal
                if c + 2 < C:
                    add(idx, self._idx(r, c + 2), 2 * s,
                        self.k_bend, self.d_bend)
                # Bend — skip-1 vertical
                if r + 2 < R:
                    add(idx, self._idx(r + 2, c), 2 * s,
                        self.k_bend, self.d_bend)

        self.springs = springs

    def pin(self, r: int, c: int) -> None:
        """Pin particle (r, c) — it will not move."""
        self.pinned[self._idx(r, c)] = True

    def set_position(self, r: int, c: int, pos: Vec3) -> None:
        self.positions[self._idx(r, c)] = pos

    def total_energy(self) -> float:
        """Return total kinetic + spring potential energy (Joules)."""
        ke = 0.0
        for v, m in zip(self.velocities, self.masses):
            ke += 0.5 * m * _dot(v, v)
        pe = 0.0
        for sp in self.springs:
            d = _norm(_sub(self.positions[sp.j], self.positions[sp.i]))
            stretch = d - sp.rest_length
            pe += 0.5 * sp.stiffness * stretch * stretch
        return ke + pe

    def rms_velocity(self) -> float:
        """RMS speed of free (unpinned) particles (m/s)."""
        free = [(v, m) for v, m, p in zip(self.velocities, self.masses, self.pinned) if not p]
        if not free:
            return 0.0
        return math.sqrt(sum(_dot(v, v) for v, _ in free) / len(free))


# ---------------------------------------------------------------------------
# Collision primitives
# ---------------------------------------------------------------------------

@dataclass
class SpherePrimitive:
    """Solid sphere collision body."""
    centre: Vec3
    radius: float


@dataclass
class PlanePrimitive:
    """Infinite horizontal plane at y = height (default floor at y = 0)."""
    height: float = 0.0


@dataclass
class CapsulePrimitive:
    """
    Capsule: the Minkowski sum of a line segment and a sphere of given radius.

    Defined by two endpoint positions *p0* and *p1* and a *radius*.
    Useful as a simple avatar-limb or torso stand-in (Bridson et al. 2003).

    Collision response: project particle to the nearest point on the segment
    axis and push out by *radius* along the normal.
    """
    p0: Vec3
    p1: Vec3
    radius: float

    def nearest_point_on_axis(self, q: Vec3) -> Vec3:
        """
        Return the point on the capsule axis segment [p0, p1] nearest to q.
        """
        d = _sub(self.p1, self.p0)
        len_sq = _dot(d, d)
        if len_sq < 1e-20:
            return self.p0  # Degenerate capsule → sphere at p0
        t = _clamp(_dot(_sub(q, self.p0), d) / len_sq, 0.0, 1.0)
        return _lerp(self.p0, self.p1, t)


# ---------------------------------------------------------------------------
# Stable time-step computation
# ---------------------------------------------------------------------------

_STABILITY_FACTOR = 0.2   # conservative factor for 2-D coupled lattice


def _safe_dt(k_max: float, m_min: float, d_max: float = 0.0) -> float:
    """
    Return the largest stable sub-step for semi-implicit Euler on a
    spring-mass-damper lattice.

    Two stability constraints apply:

    1. **Stiffness constraint** (Baraff-Witkin 1998, §3):
           dt < 2 / omega_max,   omega_max = sqrt(k_max / m_min)
       We use safety factor 0.2 for a conservative margin on the 2-D lattice.

    2. **Damping constraint** (Cundall-Strack / Newmark):
       For spring-axis velocity damping (Rayleigh), the effective time constant
       of the damping term is τ_d = m / d.  Stability requires dt < τ_d = m/d.
       We apply the same 0.2 safety factor.

    The returned dt is the minimum of the two constraints.
    """
    dt_stiffness = _STABILITY_FACTOR * math.sqrt(m_min / k_max)
    if d_max > 0.0:
        dt_damping = _STABILITY_FACTOR * m_min / d_max
        return min(dt_stiffness, dt_damping)
    return dt_stiffness


# ---------------------------------------------------------------------------
# Force accumulation
# ---------------------------------------------------------------------------

_GRAVITY: Vec3 = (0.0, -9.81, 0.0)


def _accumulate_forces(
    mesh: ClothMesh,
    gravity: Vec3,
) -> list[Vec3]:
    """
    Accumulate all forces on each particle:
      - Gravity: F_g = m * g
      - Hooke spring: F_h = k * (|pj - pi| - L0) * n̂
      - Spring-axis Rayleigh damping: F_d = -d * (vrel · n̂) * n̂

    Returns a list of force Vec3 per particle.
    Pinned particles receive zero force (they are never integrated).

    References: Provot 1995 (spring topology), Baraff-Witkin 1998 (damping).
    """
    n = len(mesh.positions)
    forces: list[Vec3] = [(0.0, 0.0, 0.0)] * n

    # --- Gravity -----------------------------------------------------------
    for i in range(n):
        if not mesh.pinned[i]:
            forces[i] = _scale(gravity, mesh.masses[i])

    # --- Spring forces (Hooke + velocity-axis damping) ---------------------
    pos = mesh.positions
    vel = mesh.velocities
    for sp in mesh.springs:
        pi, pj = pos[sp.i], pos[sp.j]
        delta = _sub(pj, pi)
        dist = _norm(delta)
        if dist < 1e-15:
            continue
        n_hat = _scale(delta, 1.0 / dist)
        stretch = dist - sp.rest_length

        # Hooke force
        f_hooke = _scale(n_hat, sp.stiffness * stretch)

        # Spring-axis damping: F_damp = -d * (vrel · n̂) * n̂
        # This is the component of relative velocity along the spring axis.
        # Applied at current step — stable in semi-implicit Euler because
        # it damps the spring-axis velocity component directly.
        # (Baraff-Witkin 1998, simplified for explicit solver)
        vrel = _sub(vel[sp.j], vel[sp.i])
        vrel_along = _dot(vrel, n_hat)
        f_damp = _scale(n_hat, sp.damping * vrel_along)

        f_total = _add(f_hooke, f_damp)

        if not mesh.pinned[sp.i]:
            forces[sp.i] = _add(forces[sp.i], f_total)
        if not mesh.pinned[sp.j]:
            forces[sp.j] = _sub(forces[sp.j], f_total)

    return forces


# ---------------------------------------------------------------------------
# Collision response
# ---------------------------------------------------------------------------

def _resolve_collisions(
    positions: list[Vec3],
    velocities: list[Vec3],
    pinned: list[bool],
    colliders: Sequence[SpherePrimitive | PlanePrimitive | CapsulePrimitive],
) -> tuple[list[Vec3], list[Vec3]]:
    """
    Project any penetrating particles to the surface of each collider and
    zero out the inward velocity component.

    Uses the penalty-free projection method (Bridson 2003, §4):
      - Compute penetration depth.
      - Translate particle to contact surface (projection).
      - Cancel the inward velocity component (velocity correction).

    Returns updated (positions, velocities).
    """
    n = len(positions)
    pos = list(positions)
    vel = list(velocities)

    for i in range(n):
        if pinned[i]:
            continue
        p = pos[i]
        v = vel[i]
        for col in colliders:
            if isinstance(col, SpherePrimitive):
                d = _sub(p, col.centre)
                dist = _norm(d)
                if dist < col.radius:
                    n_hat = _normalize(d) if dist > 1e-15 else (0.0, 1.0, 0.0)
                    # Project particle to sphere surface with 0.1% margin
                    p = _add(col.centre, _scale(n_hat, col.radius * 1.001))
                    # Cancel inward velocity
                    vn = _dot(v, n_hat)
                    if vn < 0.0:
                        v = _sub(v, _scale(n_hat, vn))

            elif isinstance(col, PlanePrimitive):
                if p[1] < col.height:
                    p = (p[0], col.height, p[2])
                    vy = min(v[1], 0.0)
                    v = (v[0], v[1] - vy, v[2])

            elif isinstance(col, CapsulePrimitive):
                nearest = col.nearest_point_on_axis(p)
                d = _sub(p, nearest)
                dist = _norm(d)
                if dist < col.radius:
                    n_hat = _normalize(d) if dist > 1e-15 else (0.0, 1.0, 0.0)
                    # Project to capsule surface
                    p = _add(nearest, _scale(n_hat, col.radius * 1.001))
                    # Cancel inward velocity
                    vn = _dot(v, n_hat)
                    if vn < 0.0:
                        v = _sub(v, _scale(n_hat, vn))

        pos[i] = p
        vel[i] = v

    return pos, vel


# ---------------------------------------------------------------------------
# Single integration step
# ---------------------------------------------------------------------------

def solve_step(
    mesh: ClothMesh,
    dt: float,
    gravity: Vec3 = _GRAVITY,
    velocity_damping: float = 0.99,
    colliders: Sequence[SpherePrimitive | PlanePrimitive | CapsulePrimitive] | None = None,
    auto_substep: bool = True,
) -> None:
    """
    Advance cloth simulation by one time step *dt* (seconds).

    Integration: semi-implicit (symplectic) Euler:
      1. Accumulate forces (gravity + Hooke springs + spring-axis damping).
      2. Integrate velocity:   v += (F/m) * dt.
      3. Per-step damping:     v *= velocity_damping  (global drag).
      4. Integrate position:   x += v * dt.
      5. Collision response:   project + velocity correction.

    The spring-axis Rayleigh damping in step 1 is the primary dissipation
    mechanism (Baraff-Witkin 1998).  The *velocity_damping* multiplier in
    step 3 provides an additional global damping that is equivalent to a
    linear drag force (air resistance proxy).

    Parameters
    ----------
    mesh : ClothMesh
    dt : float
        Requested time step (seconds).  If *auto_substep* is True (default),
        automatically split into stable sub-steps.
    gravity : Vec3
        Gravitational acceleration vector (default: −g ĵ).
    velocity_damping : float
        Per-sub-step global velocity multiplier (≤ 1).
        NOTE: applied per sub-step; effective per-outer-step damping is
        velocity_damping ** n_substeps.
    colliders : list of collision primitives, optional
        SpherePrimitive, PlanePrimitive, or CapsulePrimitive.
    auto_substep : bool
        If True, split dt into stable sub-steps automatically.
    """
    if auto_substep and mesh.springs:
        k_max = max(sp.stiffness for sp in mesh.springs)
        d_max = max(sp.damping for sp in mesh.springs)
        free_masses = [m for m, p in zip(mesh.masses, mesh.pinned) if not p]
        m_min = min(free_masses) if free_masses else min(mesh.masses)
        dt_sub = _safe_dt(k_max, m_min, d_max)
        if dt_sub < dt:
            n_sub = math.ceil(dt / dt_sub)
            dt_actual = dt / n_sub
            for _ in range(n_sub):
                solve_step(
                    mesh, dt_actual,
                    gravity=gravity,
                    velocity_damping=velocity_damping,
                    colliders=colliders,
                    auto_substep=False,
                )
            return

    n = len(mesh.positions)

    # 1. Accumulate forces
    forces = _accumulate_forces(mesh, gravity)

    # 2. Integrate velocity
    new_vel: list[Vec3] = []
    for i in range(n):
        if mesh.pinned[i]:
            new_vel.append((0.0, 0.0, 0.0))
        else:
            m = mesh.masses[i]
            a = _scale(forces[i], 1.0 / m)
            v_new = _scale(_add(mesh.velocities[i], _scale(a, dt)), velocity_damping)
            new_vel.append(v_new)
    mesh.velocities = new_vel

    # 3. Integrate position
    new_pos: list[Vec3] = []
    for i in range(n):
        if mesh.pinned[i]:
            new_pos.append(mesh.positions[i])
        else:
            new_pos.append(_add(mesh.positions[i], _scale(mesh.velocities[i], dt)))
    mesh.positions = new_pos

    # 4. Collision response
    if colliders:
        mesh.positions, mesh.velocities = _resolve_collisions(
            mesh.positions, mesh.velocities, mesh.pinned, colliders
        )
