"""
kerf_textiles.drape
===================
Cloth drape simulation — settle a cloth mesh under gravity and optional
collision bodies, then compute the BS 5058 / ASTM D 4399 drape coefficient.

Quick start
-----------
::

    from kerf_textiles.drape import drape_simulate, drape_on_disc, drape_over_sphere

    # Square cloth pinned at two top corners, hanging freely
    result = drape_simulate(
        rows=20, cols=20, spacing=0.05,
        k_structural=100.0, k_shear=50.0, k_bend=10.0,
        pin_indices=[(0, 0), (0, 19)],
        steps=2000, dt=0.005,
    )
    print(result.max_sag)             # metres

    # BS 5058 drape-coefficient test
    dc_result = drape_on_disc(
        cloth_radius=0.14, disc_radius=0.07,
        k_structural=100.0, k_bend=10.0,
    )
    print(dc_result.drape_coefficient)   # dimensionless, 0–1

    # Square sheet draped over a sphere (physics validation)
    sphere_result = drape_over_sphere(
        cloth_size=0.8, sphere_radius=0.25,
    )
    print(sphere_result.no_penetration)   # True if settled penetration-free
    print(sphere_result.energy_plateau)   # True if energy stabilised

Drape coefficient (BS 5058 / ASTM D 4399)
------------------------------------------

    DC = (A_projected - A_disc) / (A_cloth - A_disc)

where:
  * A_cloth     = area of the original flat cloth circle.
  * A_disc      = area of the supporting pedestal disc.
  * A_projected = projected area of the draped cloth onto the
                  horizontal reference plane.

DC ≈ 1.0  →  stiff fabric (barely droops — projected area ≈ A_cloth).
DC ≈ 0.0  →  very limp (hangs close to vertical — projected area ≈ A_disc).

Published range for real textiles: 0.30 – 0.95.
Stiffer fabric (higher k_bend) → higher DC.

Sphere-drape validation (Bridson et al. 2003)
---------------------------------------------
A square sheet draped over a sphere should:
  1. Settle to a stable equilibrium (energy reaches a plateau).
  2. Have no particle inside the sphere (penetration-free).
  3. Exhibit approximate bilateral symmetry if the cloth is symmetric.

These three properties are the canonical numeric validation for a cloth
simulator (see also Nealen et al. 2006, "Physically Based Deformable Models
in Computer Graphics", EUROGRAPHICS survey).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from kerf_textiles.mass_spring import (
    ClothMesh,
    SpherePrimitive,
    PlanePrimitive,
    CapsulePrimitive,
    solve_step,
    Vec3,
    _norm,
    _sub,
    _add,
    _scale,
    _dot,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DrapeResult:
    """
    Output of :func:`drape_simulate` and :func:`drape_on_disc`.

    Attributes
    ----------
    mesh : ClothMesh
        Final settled cloth mesh (positions are the draped geometry).
    max_sag : float
        Maximum downward displacement from the initial plane (metres, ≥ 0).
    drape_coefficient : float | None
        BS 5058 projected-area drape coefficient (dimensionless, 0–1).
        ``None`` if a circular disc pedestal was not used.
    energy_history : list[float]
        Total mechanical energy sampled every ``energy_sample_interval`` steps.
    converged : bool
        ``True`` if RMS velocity dropped below *tol* before the step limit.
    steps_taken : int
        Actual number of outer integration steps executed.
    """
    mesh: ClothMesh
    max_sag: float
    drape_coefficient: float | None
    energy_history: list[float]
    converged: bool
    steps_taken: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def drape_simulate(
    rows: int = 20,
    cols: int = 20,
    spacing: float = 0.05,
    mass: float = 0.005,
    k_structural: float = 100.0,
    k_shear: float = 50.0,
    k_bend: float = 10.0,
    velocity_damping: float = 0.98,
    pin_indices: list[tuple[int, int]] | None = None,
    pin_positions: dict[tuple[int, int], Vec3] | None = None,
    colliders: list[SpherePrimitive | PlanePrimitive | CapsulePrimitive] | None = None,
    gravity: Vec3 = (0.0, -9.81, 0.0),
    steps: int = 3000,
    dt: float = 0.005,
    tol: float = 1e-4,
    energy_sample_interval: int = 100,
) -> DrapeResult:
    """
    Simulate cloth draping under gravity, optionally colliding with primitives.

    Parameters
    ----------
    rows, cols : int
        Cloth grid resolution.
    spacing : float
        Rest length between adjacent particles (metres).
    mass : float
        Per-particle mass (kg).
    k_structural, k_shear, k_bend : float
        Spring stiffnesses (N/m).  Higher *k_bend* → stiffer fabric → higher DC.
    velocity_damping : float
        Per-sub-step velocity multiplier (0 < d ≤ 1).  Values < 1 dissipate
        kinetic energy.  Default 0.98 provides moderate damping.
    pin_indices : list of (row, col) tuples
        Particles fixed in space throughout the simulation.
    pin_positions : dict mapping (row, col) → Vec3, optional
        Override initial position of specified particles.  Useful for setting
        the horizontal span of a hanging strip shorter than the natural length,
        which creates a catenary configuration.  Interior particles in a
        single-column strip are linearly interpolated between the two pins.
    colliders : list of collision primitives
        :class:`~kerf_textiles.mass_spring.SpherePrimitive` or
        :class:`~kerf_textiles.mass_spring.PlanePrimitive`.
    gravity : Vec3
        Gravitational acceleration vector (default: −g ĵ).
    steps : int
        Maximum integration steps.
    dt : float
        Outer time step (seconds).  Automatically sub-stepped for stability.
    tol : float
        RMS velocity convergence tolerance (m/s).
    energy_sample_interval : int
        Record total energy every this many outer steps.

    Returns
    -------
    DrapeResult
    """
    mesh = ClothMesh(
        rows=rows,
        cols=cols,
        spacing=spacing,
        mass=mass,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
    )

    if pin_indices:
        for r, c in pin_indices:
            mesh.pin(r, c)

    # Override initial positions of specific particles (e.g. to set pin span)
    if pin_positions:
        for (r, c), pos in pin_positions.items():
            idx = mesh._idx(r, c)
            mesh.positions[idx] = pos
            # Also linearly interpolate all free particles in the strip if
            # this is a single-column strip (cols=1) and both end pins are given.
        # If this is a 1-column strip with exactly 2 pin-position overrides,
        # re-distribute interior particles linearly between the two endpoints.
        if cols == 1 and pin_indices and len(pin_positions) == 2:
            sorted_pins = sorted(pin_positions.keys(), key=lambda rc: rc[0])
            (r0, _), (rN, _) = sorted_pins
            p0 = pin_positions[(r0, 0)]
            pN = pin_positions[(rN, 0)]
            for ri in range(r0 + 1, rN):
                frac = (ri - r0) / (rN - r0)
                mesh.positions[mesh._idx(ri, 0)] = (
                    p0[0] + frac * (pN[0] - p0[0]),
                    p0[1] + frac * (pN[1] - p0[1]),
                    p0[2] + frac * (pN[2] - p0[2]),
                )

    energy_history: list[float] = []
    converged = False
    step = 0

    for step in range(1, steps + 1):
        solve_step(
            mesh, dt=dt,
            gravity=gravity,
            velocity_damping=velocity_damping,
            colliders=colliders or [],
        )

        if step % energy_sample_interval == 0:
            energy_history.append(mesh.total_energy())

        # Convergence: check RMS velocity of free particles
        if step % 50 == 0:
            n_free = sum(1 for p in mesh.pinned if not p)
            if n_free > 0:
                rms_v = math.sqrt(
                    sum(_norm(v) ** 2 for v, p in zip(mesh.velocities, mesh.pinned) if not p)
                    / n_free
                )
                if rms_v < tol:
                    converged = True
                    break

    # --- Max sag (drop below initial y=0 plane) -------------------------
    max_sag = max(0.0, -min(p[1] for p in mesh.positions))

    return DrapeResult(
        mesh=mesh,
        max_sag=max_sag,
        drape_coefficient=None,
        energy_history=energy_history,
        converged=converged,
        steps_taken=step,
    )


def drape_on_disc(
    cloth_radius: float = 0.14,
    disc_radius: float = 0.07,
    spacing: float = 0.02,
    mass: float = 0.001,
    k_structural: float = 5.0,
    k_shear: float = 2.5,
    k_bend: float = 0.5,
    velocity_damping: float = 0.97,
    disc_height: float = 0.0,
    steps: int = 2000,
    dt: float = 0.005,
    tol: float = 1e-4,
) -> DrapeResult:
    """
    Simulate a circular cloth draped over a cylindrical disc pedestal,
    replicating the BS 5058 drape-coefficient test.

    Geometry
    --------
    * Circular cloth of radius *cloth_radius* centred on a disc of radius
      *disc_radius*.
    * Disc particles (r ≤ disc_radius) are pinned to the pedestal surface.
    * Ring particles (disc_radius < r ≤ cloth_radius) hang freely.
    * Particles outside the cloth circle are removed from the simulation
      (their spring connections to ring-edge particles are cut).

    The cloth ring hangs under gravity.  With low bending stiffness the ring
    hangs nearly vertical (DC → 0); with high bending stiffness it barely
    droops (DC → 1).

    Drape coefficient
    -----------------
    The horizontal projection of the hanging ring determines DC.  As the
    outer edge swings INWARD under gravity, the projected area shrinks below
    A_cloth, giving DC < 1.

    Returns a :class:`DrapeResult` with a populated ``drape_coefficient``.
    """
    from kerf_textiles.mass_spring import Spring

    # Build a square mesh large enough to cover the cloth circle
    half = int(math.ceil(cloth_radius / spacing))
    n_cells = 2 * half + 1
    mesh = ClothMesh(
        rows=n_cells,
        cols=n_cells,
        spacing=spacing,
        mass=mass,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
    )

    cx = (n_cells - 1) / 2.0
    cy = (n_cells - 1) / 2.0
    cloth_r2 = cloth_radius ** 2
    disc_r2 = disc_radius ** 2

    # Classify particles
    outside_ids: set[int] = set()
    disc_ids: set[int] = set()
    for r in range(n_cells):
        for c in range(n_cells):
            dx = (c - cx) * spacing
            dz = (r - cy) * spacing
            d2 = dx * dx + dz * dz
            idx = mesh._idx(r, c)
            if d2 > cloth_r2:
                outside_ids.add(idx)
            elif d2 <= disc_r2:
                disc_ids.add(idx)

    # Pin disc particles (resting on pedestal)
    for i in disc_ids:
        mesh.pinned[i] = True

    # REMOVE springs that connect to outside-cloth particles.
    # This allows the ring's outer edge to hang freely without being anchored
    # to fixed outside particles, which would prevent inward collapse.
    mesh.springs = [
        sp for sp in mesh.springs
        if sp.i not in outside_ids and sp.j not in outside_ids
    ]

    # Lift all cloth-ring particles to disc height
    for r in range(n_cells):
        for c in range(n_cells):
            idx = mesh._idx(r, c)
            if idx in outside_ids:
                continue  # don't touch outside particles (irrelevant)
            p = mesh.positions[idx]
            mesh.positions[idx] = (p[0], disc_height, p[2])

    # Floor collider — prevents particles from falling forever
    floor = PlanePrimitive(height=disc_height - cloth_radius * 2.0)

    energy_history: list[float] = []
    converged = False
    step = 0
    ring_ids = [i for i in range(len(mesh.positions))
                if i not in outside_ids and i not in disc_ids]

    for step in range(1, steps + 1):
        solve_step(
            mesh, dt=dt,
            gravity=(0.0, -9.81, 0.0),
            velocity_damping=velocity_damping,
            colliders=[floor],
        )

        if step % 100 == 0:
            energy_history.append(mesh.total_energy())

        if step % 50 == 0 and ring_ids:
            rms_v = math.sqrt(
                sum(_norm(mesh.velocities[i]) ** 2 for i in ring_ids) / len(ring_ids)
            )
            if rms_v < tol:
                converged = True
                break

    # --- Drape coefficient (BS 5058 / ASTM D 4399) ----------------------
    # The draped cloth projects onto the horizontal plane.
    # Disc particles project to their fixed positions (A_disc area).
    # Ring particles swing inward → their projected radius shrinks.
    # We count unique (gx, gz) cells occupied by ring + disc particles.

    projected_set: set[tuple[int, int]] = set()

    # Disc: add cells at original grid positions within disc
    for r in range(n_cells):
        for c in range(n_cells):
            dx = (c - cx) * spacing
            dz = (r - cy) * spacing
            if dx * dx + dz * dz <= disc_r2:
                gx = int(round(dx / spacing))
                gz = int(round(dz / spacing))
                projected_set.add((gx, gz))

    # Ring: use actual simulated positions
    for i in ring_ids:
        px, _, pz = mesh.positions[i]
        if px != px or pz != pz:  # NaN guard
            continue
        gx = int(round(px / spacing))
        gz = int(round(pz / spacing))
        projected_set.add((gx, gz))

    cell_area = spacing * spacing
    A_projected = len(projected_set) * cell_area
    A_cloth = math.pi * cloth_radius ** 2
    A_disc = math.pi * disc_radius ** 2

    if A_cloth <= A_disc:
        dc = None
    else:
        dc = max(0.0, min(1.0, (A_projected - A_disc) / (A_cloth - A_disc)))

    # Max sag
    sag_vals = [disc_height - mesh.positions[i][1]
                for i in ring_ids
                if mesh.positions[i][1] == mesh.positions[i][1]]  # NaN check
    max_sag = max(0.0, max(sag_vals)) if sag_vals else 0.0

    return DrapeResult(
        mesh=mesh,
        max_sag=max_sag,
        drape_coefficient=dc,
        energy_history=energy_history,
        converged=converged,
        steps_taken=step,
    )


# ---------------------------------------------------------------------------
# Catenary reference
# ---------------------------------------------------------------------------

def catenary_max_sag(span: float, total_length: float) -> float:
    """
    Compute the maximum sag (dip) of a catenary with given horizontal span
    and total arc length, using the standard catenary equation.

    Parameters
    ----------
    span : float
        Horizontal distance between the two support points (metres).
    total_length : float
        Total arc length of the hanging chain / cloth strip (metres).

    Returns
    -------
    float
        Maximum vertical sag at the midpoint (metres).

    Notes
    -----
    The catenary is y = a*(cosh(x/a) - 1) with vertex at the midpoint.
    Arc length L = 2*a*sinh(S/(2*a)) where S = span.
    Sag f = a*(cosh(S/(2*a)) - 1).
    We solve for *a* via Newton's method on g(a) = 2*a*sinh(S/(2a)) - L = 0.
    """
    if total_length <= span + 1e-12:
        return 0.0  # Taut — no sag

    S = span
    L = total_length

    # Initial guess from parabolic approximation: sag ≈ sqrt(3*(L-S)*S)/2
    a_init = S * S / (8.0 * max(L - S, 1e-12))
    a = max(a_init, 1e-6)

    for _ in range(200):
        arg = S / (2.0 * a)
        sinh_val = math.sinh(arg)
        cosh_val = math.cosh(arg)
        f = 2.0 * a * sinh_val - L
        df = 2.0 * sinh_val - (S / a) * cosh_val
        if abs(df) < 1e-15:
            break
        a_new = a - f / df
        if a_new < 1e-9:
            a_new = a / 2.0
        if abs(a_new - a) < 1e-12:
            a = a_new
            break
        a = a_new

    return a * (math.cosh(S / (2.0 * a)) - 1.0)


# ---------------------------------------------------------------------------
# Sphere-drape result
# ---------------------------------------------------------------------------

@dataclass
class DrapeOverSphereResult:
    """
    Output of :func:`drape_over_sphere`.

    Attributes
    ----------
    mesh : ClothMesh
        Final settled cloth mesh.
    max_penetration : float
        Maximum penetration depth into the sphere among all particles
        (positive = inside; 0.0 = penetration-free).
    no_penetration : bool
        True if no particle penetrates the sphere beyond 1% of the radius.
    energy_history : list[float]
        Total mechanical energy sampled every ``energy_sample_interval`` steps.
    energy_plateau : bool
        True if the energy tail (last 25% of samples) is non-increasing
        within a 1% tolerance.
    symmetry_error : float
        RMS difference between the left-half and right-half y-positions of
        the final cloth, measuring bilateral (X-mirror) symmetry.
        Zero for a perfectly symmetric result.
    converged : bool
        True if RMS velocity dropped below *tol* before the step limit.
    steps_taken : int
        Actual number of outer integration steps executed.
    sphere : SpherePrimitive
        The sphere used as the collision body.
    """
    mesh: ClothMesh
    max_penetration: float
    no_penetration: bool
    energy_history: list[float]
    energy_plateau: bool
    symmetry_error: float
    converged: bool
    steps_taken: int
    sphere: SpherePrimitive


# ---------------------------------------------------------------------------
# Sphere-drape simulation
# ---------------------------------------------------------------------------

def drape_over_sphere(
    cloth_size: float = 0.8,
    sphere_radius: float = 0.25,
    sphere_centre: Vec3 | None = None,
    rows: int = 16,
    cols: int = 16,
    mass: float = 0.003,
    k_structural: float = 80.0,
    k_shear: float = 40.0,
    k_bend: float = 4.0,
    d_structural: float = 0.3,
    d_shear: float = 0.15,
    d_bend: float = 0.06,
    velocity_damping: float = 0.96,
    steps: int = 4000,
    dt: float = 0.005,
    tol: float = 5e-5,
    energy_sample_interval: int = 100,
    floor_margin: float = 2.0,
) -> DrapeOverSphereResult:
    """
    Drape a square cloth sheet over a sphere and settle to equilibrium.

    This is the canonical physics-validation scenario for cloth simulators
    (Provot 1995, Bridson 2003, Nealen 2006):

    * A square cloth is initialised flat in the XZ plane directly above
      a sphere of given radius.
    * Gravity pulls it downward; the sphere acts as a rigid collision body.
    * The cloth settles around the sphere to a stable, penetration-free,
      approximately symmetric drape.

    Validation checks performed:
    1. **No penetration**: all particles outside the sphere surface
       (within 1% radius tolerance).
    2. **Energy plateau**: total mechanical energy is non-increasing in the
       tail of the simulation (energy stabilised = converged to equilibrium).
    3. **Bilateral symmetry**: the X-mirror of the left half of the cloth
       matches the right half within a small tolerance (RMS error reported).

    Parameters
    ----------
    cloth_size : float
        Side length of the square cloth (metres).  Default 0.8 m.
    sphere_radius : float
        Radius of the sphere (metres).  Default 0.25 m.
    sphere_centre : Vec3, optional
        Centre of the sphere.  Default: (0, -sphere_radius * 0.5, 0) so the
        sphere top is at y = sphere_radius * 0.5, and the cloth starts at y = 0
        directly above the sphere.
    rows, cols : int
        Cloth grid resolution.  Use even numbers for symmetric sampling.
    mass : float
        Per-particle mass (kg).
    k_structural, k_shear, k_bend : float
        Spring stiffnesses (N/m).  Lower k_bend → more drape, more folds.
    d_structural, d_shear, d_bend : float
        Spring-axis Rayleigh damping coefficients (N·s/m).
    velocity_damping : float
        Per-sub-step global velocity multiplier (≤ 1).
    steps : int
        Maximum outer integration steps.
    dt : float
        Outer time step (seconds).
    tol : float
        RMS velocity convergence tolerance (m/s).
    energy_sample_interval : int
        Record total energy every this many outer steps.
    floor_margin : float
        A floor plane is placed at sphere_centre.y - sphere_radius * floor_margin
        to prevent particles from falling indefinitely.

    Returns
    -------
    DrapeOverSphereResult
    """
    if sphere_centre is None:
        # Top of sphere is at y = 0 (cloth starts flush above)
        sphere_centre = (0.0, -sphere_radius, 0.0)

    sphere = SpherePrimitive(centre=sphere_centre, radius=sphere_radius)

    # Build cloth mesh — initial flat XZ plane at y = 0 (just above sphere top)
    spacing = cloth_size / (max(rows, cols) - 1)
    mesh = ClothMesh(
        rows=rows,
        cols=cols,
        spacing=spacing,
        mass=mass,
        k_structural=k_structural,
        k_shear=k_shear,
        k_bend=k_bend,
        d_structural=d_structural,
        d_shear=d_shear,
        d_bend=d_bend,
    )

    # Floor prevents infinite fall
    floor_y = sphere_centre[1] - sphere_radius * floor_margin
    floor = PlanePrimitive(height=floor_y)
    colliders = [sphere, floor]

    energy_history: list[float] = []
    converged = False
    step = 0

    for step in range(1, steps + 1):
        solve_step(
            mesh, dt=dt,
            gravity=(0.0, -9.81, 0.0),
            velocity_damping=velocity_damping,
            colliders=colliders,
        )

        if step % energy_sample_interval == 0:
            energy_history.append(mesh.total_energy())

        if step % 50 == 0:
            rms_v = mesh.rms_velocity()
            if rms_v < tol:
                converged = True
                break

    # --- Penetration analysis -------------------------------------------
    max_pen = 0.0
    for p in mesh.positions:
        d = _sub(p, sphere.centre)
        dist = _norm(d)
        pen = sphere.radius - dist  # positive = inside sphere
        if pen > max_pen:
            max_pen = pen

    no_penetration = (max_pen <= sphere.radius * 0.01)

    # --- Energy plateau check -------------------------------------------
    # Last 25% of samples must be non-increasing within 1% tolerance.
    energy_plateau = False
    if len(energy_history) >= 8:
        tail_start = len(energy_history) * 3 // 4
        tail = energy_history[tail_start:]
        violations = sum(
            1 for i in range(1, len(tail))
            if tail[i] > tail[i - 1] * 1.01
        )
        energy_plateau = (violations == 0)
    elif len(energy_history) >= 2:
        # Fewer samples: just check last two
        energy_plateau = (energy_history[-1] <= energy_history[-2] * 1.01)

    # --- Bilateral (X-mirror) symmetry check ----------------------------
    # For each particle at column c, compare y-position with its mirror at
    # column (cols - 1 - c).  An even grid is symmetric by construction.
    sym_sq_sum = 0.0
    sym_count = 0
    for r in range(rows):
        for c in range(cols // 2):
            i = mesh._idx(r, c)
            j = mesh._idx(r, cols - 1 - c)
            yi = mesh.positions[i][1]
            yj = mesh.positions[j][1]
            sym_sq_sum += (yi - yj) ** 2
            sym_count += 1
    symmetry_error = math.sqrt(sym_sq_sum / sym_count) if sym_count > 0 else 0.0

    return DrapeOverSphereResult(
        mesh=mesh,
        max_penetration=max_pen,
        no_penetration=no_penetration,
        energy_history=energy_history,
        energy_plateau=energy_plateau,
        symmetry_error=symmetry_error,
        converged=converged,
        steps_taken=step,
        sphere=sphere,
    )
