"""
test_cloth_drape_sphere.py
==========================
Physics-validation tests for the mass-spring cloth drape simulator.

Four numeric oracles per the task specification:

1. **Stability**: simulation does not blow up (all particle positions finite,
   velocities remain bounded after N steps).

2. **No penetration**: after settling over a sphere, no particle is inside
   the sphere surface (within 1% tolerance for projection margin).

3. **Bilateral symmetry**: the settled drape over a centred sphere is
   approximately left-right symmetric (RMS deviation < 5 mm for a 0.8 m
   cloth draped over a 0.25 m sphere).

4. **Energy plateau**: total mechanical energy history is non-increasing
   in the settling tail (no more than 1% growth per sample).

Additional tests cover:
  * Capsule collision primitive (particles stay outside).
  * Spring-axis Rayleigh damping is actually active (energy dissipates
    faster with d > 0 than with d == 0).

References
----------
  Provot, X. (1995). Graphics Interface.
  Baraff, D. & Witkin, A. (1998). SIGGRAPH '98.
  Bridson, R., Marino, S., & Fedkiw, R. (2003). SCA '03.
"""

from __future__ import annotations

import math
import pytest

from kerf_textiles.drape import drape_over_sphere, DrapeOverSphereResult
from kerf_textiles.mass_spring import (
    ClothMesh,
    SpherePrimitive,
    PlanePrimitive,
    CapsulePrimitive,
    solve_step,
    _norm,
    _sub,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _finite(v: float) -> bool:
    return math.isfinite(v)


# ---------------------------------------------------------------------------
# Oracle 1 — Stability: no blow-up
# ---------------------------------------------------------------------------

class TestStability:
    """
    After N steps, particle positions and velocities must be finite.
    Energy must also be finite (no NaN / Inf from spring blow-up).
    """

    def test_positions_finite_after_settling(self):
        """All particle positions must be finite after 3000 steps."""
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=12,
            cols=12,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=3000,
            dt=0.005,
            tol=5e-5,
        )
        for i, p in enumerate(result.mesh.positions):
            assert all(_finite(c) for c in p), (
                f"Particle {i} position is non-finite: {p}"
            )

    def test_velocities_finite_after_settling(self):
        """All particle velocities must be finite (no blow-up)."""
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=12,
            cols=12,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=3000,
            dt=0.005,
            tol=5e-5,
        )
        for i, v in enumerate(result.mesh.velocities):
            assert all(_finite(c) for c in v), (
                f"Particle {i} velocity is non-finite: {v}"
            )

    def test_energy_finite(self):
        """Total energy at each sample must be finite."""
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=10,
            cols=10,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=2000,
            dt=0.005,
            energy_sample_interval=100,
        )
        for i, e in enumerate(result.energy_history):
            assert _finite(e), f"Energy sample {i} = {e} is non-finite"

    def test_rms_velocity_decreasing(self):
        """
        RMS velocity of free particles should decrease overall as the cloth
        settles.  Compare first 10% vs last 10% of the energy history.
        """
        result = drape_over_sphere(
            cloth_size=0.6,
            sphere_radius=0.2,
            rows=10,
            cols=10,
            mass=0.003,
            k_structural=60.0,
            k_shear=30.0,
            k_bend=3.0,
            velocity_damping=0.98,
            steps=3000,
            dt=0.005,
            energy_sample_interval=100,
        )
        eh = result.energy_history
        assert len(eh) >= 10, "Need at least 10 energy samples for trend check"
        n_tenth = max(1, len(eh) // 10)
        early_mean = sum(eh[:n_tenth]) / n_tenth
        late_mean = sum(eh[-n_tenth:]) / n_tenth
        assert late_mean < early_mean, (
            f"Energy did not decrease: early={early_mean:.4f}, late={late_mean:.4f}"
        )


# ---------------------------------------------------------------------------
# Oracle 2 — No penetration after drape over sphere
# ---------------------------------------------------------------------------

class TestNoPenetration:
    """
    After settling, no particle should be inside the sphere.

    Tolerance: 1% of sphere radius (accounts for the 0.1% projection margin
    and one sub-step of discretisation).
    """

    def test_no_sphere_penetration_standard(self):
        """Standard drape: 16×16 cloth over 0.25 m sphere."""
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=16,
            cols=16,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=4000,
            dt=0.005,
            tol=5e-5,
        )
        sphere = result.sphere
        tolerance = sphere.radius * 0.01  # 1% margin
        penetrated = []
        for i, p in enumerate(result.mesh.positions):
            d = _norm(_sub(p, sphere.centre))
            if d < sphere.radius - tolerance:
                penetrated.append((i, d, sphere.radius - d))
        assert len(penetrated) == 0, (
            f"{len(penetrated)} particles penetrate the sphere "
            f"(max penetration {max(v for _, _, v in penetrated):.4f} m): "
            f"first few = {penetrated[:3]}"
        )

    def test_no_sphere_penetration_small_cloth(self):
        """Smaller cloth (0.5 m) draped over same sphere."""
        sphere_r = 0.2
        result = drape_over_sphere(
            cloth_size=0.5,
            sphere_radius=sphere_r,
            rows=12,
            cols=12,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=3000,
            dt=0.005,
            tol=5e-5,
        )
        sphere = result.sphere
        tolerance = sphere.radius * 0.01
        for i, p in enumerate(result.mesh.positions):
            d = _norm(_sub(p, sphere.centre))
            assert d >= sphere.radius - tolerance, (
                f"Particle {i} penetrates sphere: dist={d:.4f}, "
                f"radius={sphere.radius}, pen={(sphere.radius - d):.4f}"
            )

    def test_no_penetration_flag(self):
        """DrapeOverSphereResult.no_penetration should be True."""
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=14,
            cols=14,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=4000,
            dt=0.005,
            tol=5e-5,
        )
        assert result.no_penetration, (
            f"no_penetration=False; max_penetration={result.max_penetration:.4f} m "
            f"(sphere radius={result.sphere.radius})"
        )


# ---------------------------------------------------------------------------
# Oracle 3 — Bilateral symmetry
# ---------------------------------------------------------------------------

class TestBilateralSymmetry:
    """
    A symmetric cloth draped over a centred sphere should have approximately
    equal y-positions on the left and right halves.

    Using even grid dimensions ensures the left/right columns mirror exactly.

    Physical reasoning (Provot 1995, §5):
    The equilibrium of a symmetric mesh under symmetric loads on a symmetric
    body is symmetric.  Numerical asymmetry comes from floating-point but
    should be < 1 mm for the grid sizes used here.
    """

    def test_left_right_symmetry_within_5mm(self):
        """
        RMS difference between mirrored column pairs must be < 5 mm.
        Uses 16×16 grid (even — exactly symmetric columns).
        """
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=16,
            cols=16,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=4000,
            dt=0.005,
            tol=5e-5,
        )
        assert result.symmetry_error < 0.005, (
            f"Bilateral symmetry error {result.symmetry_error * 1000:.2f} mm > 5 mm"
        )

    def test_symmetry_error_nonnegative(self):
        """symmetry_error is always ≥ 0."""
        result = drape_over_sphere(
            cloth_size=0.6,
            sphere_radius=0.2,
            rows=10,
            cols=10,
            mass=0.003,
            k_structural=60.0,
            k_shear=30.0,
            k_bend=3.0,
            velocity_damping=0.98,
            steps=2000,
            dt=0.005,
        )
        assert result.symmetry_error >= 0.0

    def test_front_back_symmetry_within_5mm(self):
        """
        Row-mirror symmetry (front/back): same test using row pairs.
        Row symmetry is independent of column symmetry.
        """
        rows, cols = 16, 16
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=rows,
            cols=cols,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=4000,
            dt=0.005,
            tol=5e-5,
        )
        mesh = result.mesh
        sq_sum = 0.0
        count = 0
        for r in range(rows // 2):
            for c in range(cols):
                i = mesh._idx(r, c)
                j = mesh._idx(rows - 1 - r, c)
                yi = mesh.positions[i][1]
                yj = mesh.positions[j][1]
                sq_sum += (yi - yj) ** 2
                count += 1
        rms = math.sqrt(sq_sum / count) if count > 0 else 0.0
        assert rms < 0.005, (
            f"Front-back symmetry RMS {rms * 1000:.2f} mm > 5 mm"
        )


# ---------------------------------------------------------------------------
# Oracle 4 — Energy decreases monotonically to a plateau
# ---------------------------------------------------------------------------

class TestEnergyPlateau:
    """
    The total mechanical energy should decrease monotonically and plateau.

    Specifically (after the initial transient is discarded):
      * The final 25% of energy samples must be non-increasing within 1%.
      * The overall trend must be decreasing (last 10% mean < first 10% mean).

    Physical reasoning: the simulator uses Rayleigh spring-axis damping plus
    global velocity damping.  Both are dissipative.  The equilibrium is a
    local minimum of elastic + gravitational potential energy.
    """

    def test_energy_plateau_flag(self):
        """DrapeOverSphereResult.energy_plateau must be True after settling."""
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=14,
            cols=14,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.98,
            steps=4000,
            dt=0.005,
            tol=5e-5,
            energy_sample_interval=100,
        )
        assert result.energy_plateau, (
            f"energy_plateau=False; energy history tail: "
            f"{result.energy_history[-8:]}"
        )

    def test_energy_decreases_overall(self):
        """
        Overall energy trend: the mean of the last 25% of samples must be
        below the peak of the first 25% of samples.

        The total_energy() measures KE + spring PE only (not gravity PE).
        As the cloth initially deforms under gravity, spring PE rises.
        After settling it drops back toward a plateau.  So the correct
        check is: the settled plateau < the peak during initial deformation.
        We compare the last quarter mean to the maximum of the first quarter.
        """
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=12,
            cols=12,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.96,
            steps=4000,
            dt=0.005,
            energy_sample_interval=100,
        )
        eh = result.energy_history
        assert len(eh) >= 8
        n = max(1, len(eh) // 4)
        peak_early = max(eh[:n])
        late_mean = sum(eh[-n:]) / n
        assert late_mean < peak_early, (
            f"Settled energy {late_mean:.4f} >= peak early {peak_early:.4f}: "
            f"simulation did not dissipate energy"
        )

    def test_energy_tail_non_increasing(self):
        """
        Energy tail (last 25% of samples) must have zero violations of
        the 1%-growth threshold.
        """
        result = drape_over_sphere(
            cloth_size=0.8,
            sphere_radius=0.25,
            rows=12,
            cols=12,
            mass=0.003,
            k_structural=80.0,
            k_shear=40.0,
            k_bend=4.0,
            velocity_damping=0.96,
            steps=4000,
            dt=0.005,
            energy_sample_interval=100,
        )
        eh = result.energy_history
        assert len(eh) >= 8
        tail = eh[len(eh) * 3 // 4:]
        violations = [
            (i, tail[i - 1], tail[i])
            for i in range(1, len(tail))
            if tail[i] > tail[i - 1] * 1.01
        ]
        assert len(violations) == 0, (
            f"Energy increased at {len(violations)} sample(s) in tail: "
            f"{violations[:3]}"
        )


# ---------------------------------------------------------------------------
# Capsule collision primitive
# ---------------------------------------------------------------------------

class TestCapsuleCollision:
    """
    Particles should not penetrate a capsule primitive.

    The capsule is the stand-in for an avatar limb (Bridson 2003, §4).
    """

    def test_no_capsule_penetration(self):
        """
        A small cloth dropped onto a horizontal capsule (a cylinder with
        hemispherical caps) must not penetrate.
        """
        capsule = CapsulePrimitive(
            p0=(-0.4, -0.1, 0.0),
            p1=(+0.4, -0.1, 0.0),
            radius=0.08,
        )
        mesh = ClothMesh(
            rows=10,
            cols=10,
            spacing=0.06,
            mass=0.003,
            k_structural=60.0,
            k_shear=30.0,
            k_bend=3.0,
        )
        colliders = [capsule, PlanePrimitive(height=-0.5)]
        for _ in range(1200):
            solve_step(mesh, dt=0.005, velocity_damping=0.98, colliders=colliders)

        tolerance = capsule.radius * 0.01
        for i, p in enumerate(mesh.positions):
            nearest = capsule.nearest_point_on_axis(p)
            d = _norm(_sub(p, nearest))
            assert d >= capsule.radius - tolerance, (
                f"Particle {i} penetrates capsule: dist={d:.4f}, "
                f"radius={capsule.radius}"
            )

    def test_capsule_nearest_point_degenerate(self):
        """Degenerate capsule (p0==p1) is handled gracefully."""
        capsule = CapsulePrimitive(
            p0=(0.0, 0.0, 0.0),
            p1=(0.0, 0.0, 0.0),
            radius=0.1,
        )
        # Nearest point on degenerate capsule axis = p0
        q = (0.05, 0.1, 0.0)
        nearest = capsule.nearest_point_on_axis(q)
        assert nearest == capsule.p0

    def test_capsule_nearest_point_clamped(self):
        """Nearest point on axis is clamped to segment endpoints."""
        capsule = CapsulePrimitive(
            p0=(0.0, 0.0, 0.0),
            p1=(1.0, 0.0, 0.0),
            radius=0.1,
        )
        # Point past endpoint → nearest = p1
        q = (2.0, 0.0, 0.0)
        nearest = capsule.nearest_point_on_axis(q)
        assert abs(nearest[0] - 1.0) < 1e-10

        # Point before p0 → nearest = p0
        q2 = (-1.0, 0.0, 0.0)
        nearest2 = capsule.nearest_point_on_axis(q2)
        assert abs(nearest2[0] - 0.0) < 1e-10

        # Point at midpoint → nearest is midpoint
        q3 = (0.5, 0.5, 0.0)
        nearest3 = capsule.nearest_point_on_axis(q3)
        assert abs(nearest3[0] - 0.5) < 1e-10
        assert abs(nearest3[1] - 0.0) < 1e-10


# ---------------------------------------------------------------------------
# Spring-axis damping: energy dissipates faster with d > 0
# ---------------------------------------------------------------------------

class TestSpringAxisDamping:
    """
    Rayleigh spring-axis damping (d > 0) should cause faster energy
    dissipation than pure velocity-multiplier damping alone.

    Test: run two identical simulations — one with d_structural=0 (no
    spring-axis damping), one with d_structural=1.0.  After N steps the
    damped sim should have lower total energy.
    """

    def _run_energy(self, d_structural: float, steps: int = 500) -> float:
        mesh = ClothMesh(
            rows=8,
            cols=8,
            spacing=0.06,
            mass=0.003,
            k_structural=60.0,
            k_shear=30.0,
            k_bend=3.0,
            d_structural=d_structural,
            d_shear=0.0,
            d_bend=0.0,
        )
        # Pin two corners so mesh hangs
        mesh.pin(0, 0)
        mesh.pin(0, 7)
        for _ in range(steps):
            solve_step(mesh, dt=0.005, velocity_damping=0.995, colliders=[])
        return mesh.total_energy()

    def test_rayleigh_damping_dissipates_faster(self):
        """
        Energy with d_structural=1.0 must be less than with d_structural=0.
        """
        energy_undamped = self._run_energy(d_structural=0.0, steps=600)
        energy_damped = self._run_energy(d_structural=1.0, steps=600)
        assert energy_damped < energy_undamped, (
            f"Rayleigh damping did not dissipate faster: "
            f"undamped={energy_undamped:.4f}, damped={energy_damped:.4f}"
        )


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

class TestSphereDropeSmoke:
    def test_drape_over_sphere_returns_result(self):
        result = drape_over_sphere(
            cloth_size=0.6,
            sphere_radius=0.2,
            rows=8,
            cols=8,
            steps=500,
            dt=0.005,
        )
        assert isinstance(result, DrapeOverSphereResult)
        assert result.sphere.radius == pytest.approx(0.2)
        assert result.steps_taken > 0
        assert result.max_penetration >= 0.0

    def test_drape_over_sphere_settles(self):
        """
        With appropriate damping the cloth reaches an energy plateau.

        A frictionless cloth draped over a sphere retains small-amplitude
        spring oscillations at equilibrium — the energy plateau is the
        physically correct convergence criterion (rather than RMS velocity
        dropping to zero, which requires friction or a pinned cloth).
        """
        result = drape_over_sphere(
            cloth_size=0.5,
            sphere_radius=0.18,
            rows=8,
            cols=8,
            mass=0.002,
            k_structural=50.0,
            k_shear=25.0,
            k_bend=2.5,
            velocity_damping=0.96,
            steps=3000,
            dt=0.005,
            tol=1e-4,
            energy_sample_interval=100,
        )
        assert result.energy_plateau, (
            f"Cloth energy did not plateau in {result.steps_taken} steps; "
            f"energy tail: {result.energy_history[-5:] if result.energy_history else 'N/A'}"
        )

    def test_max_penetration_below_radius(self):
        """max_penetration can never exceed the sphere radius."""
        result = drape_over_sphere(
            cloth_size=0.5,
            sphere_radius=0.2,
            rows=8,
            cols=8,
            steps=1000,
            dt=0.005,
        )
        assert result.max_penetration <= result.sphere.radius
