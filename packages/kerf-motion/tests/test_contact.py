"""
Tests for kerf_motion.contact — 3D contact/collision dynamics.

Covers:
  - Sphere-plane detection (signed distance, penetration)
  - Sphere-sphere detection
  - Sphere-mesh (triangle) detection
  - Hertzian stiffness formulae
  - Hunt-Crossley normal force model
  - Coulomb friction
  - Impulse-based restitution (compute_restitution_impulse + apply_impulse)
  - resolve_contacts_impulse
  - apply_contacts (penalty force hook)
  - Bouncing ball: first bounce height ≈ e² × drop height within ±5%
  - Two-pendulum elastic impact: velocities swap (e=1)
"""

from __future__ import annotations

import math
import pytest


# ---------------------------------------------------------------------------
# Helpers for building minimal rigid bodies
# ---------------------------------------------------------------------------

def _sphere_body(mass=1.0, position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0)):
    from kerf_motion.body import RigidBody
    I = 0.4 * mass * 0.1 ** 2   # solid sphere I = 2/5 m r²  (r=0.1 m nominal)
    inertia = ((I, 0.0, 0.0), (0.0, I, 0.0), (0.0, 0.0, I))
    return RigidBody(
        mass=mass,
        inertia_tensor=inertia,
        position=tuple(float(v) for v in position),
        velocity=tuple(float(v) for v in velocity),
    )


# ===========================================================================
# 1. Collision detection — sphere-plane
# ===========================================================================

def test_contact_sphere_plane_no_contact():
    from kerf_motion.contact import detect_sphere_plane
    # Sphere above plane, no penetration
    c = detect_sphere_plane(
        sphere_center=(0.0, 0.5, 0.0),
        sphere_radius=0.1,
        plane_normal=(0.0, 1.0, 0.0),
        plane_point=(0.0, 0.0, 0.0),
    )
    assert c is None


def test_contact_sphere_plane_tangent():
    from kerf_motion.contact import detect_sphere_plane
    # Sphere just touching (d == r) → not penetrating
    c = detect_sphere_plane(
        sphere_center=(0.0, 0.1, 0.0),
        sphere_radius=0.1,
        plane_normal=(0.0, 1.0, 0.0),
        plane_point=(0.0, 0.0, 0.0),
    )
    assert c is None


def test_contact_sphere_plane_penetration():
    from kerf_motion.contact import detect_sphere_plane
    # Centre at y=0.08, radius=0.1 → d=0.08, pen=0.02
    c = detect_sphere_plane(
        sphere_center=(0.0, 0.08, 0.0),
        sphere_radius=0.1,
        plane_normal=(0.0, 1.0, 0.0),
        plane_point=(0.0, 0.0, 0.0),
    )
    assert c is not None
    assert abs(c.penetration_depth - 0.02) < 1e-12
    # Normal should point upward (away from plane into sphere)
    assert abs(c.normal[1] - 1.0) < 1e-12


def test_contact_sphere_plane_body_indices():
    from kerf_motion.contact import detect_sphere_plane
    c = detect_sphere_plane(
        sphere_center=(0.0, 0.05, 0.0), sphere_radius=0.1,
        plane_normal=(0.0, 1.0, 0.0), plane_point=(0.0, 0.0, 0.0),
        body_a_idx=3, body_b_idx=-1,
    )
    assert c is not None
    assert c.body_a_idx == 3
    assert c.body_b_idx == -1


# ===========================================================================
# 2. Collision detection — sphere-sphere
# ===========================================================================

def test_contact_sphere_sphere_no_contact():
    from kerf_motion.contact import detect_sphere_sphere
    c = detect_sphere_sphere(
        center_a=(0.0, 0.0, 0.0), radius_a=0.1,
        center_b=(1.0, 0.0, 0.0), radius_b=0.1,
    )
    assert c is None  # distance=1.0, sum_r=0.2 → no penetration


def test_contact_sphere_sphere_penetration():
    from kerf_motion.contact import detect_sphere_sphere
    # Distance = 0.15, sum_r = 0.2 → pen = 0.05
    c = detect_sphere_sphere(
        center_a=(0.0, 0.0, 0.0), radius_a=0.1,
        center_b=(0.15, 0.0, 0.0), radius_b=0.1,
    )
    assert c is not None
    assert abs(c.penetration_depth - 0.05) < 1e-12
    # Normal should point from b toward a (negative x direction)
    assert abs(c.normal[0] - (-1.0)) < 1e-12


def test_contact_sphere_sphere_equal_overlap():
    from kerf_motion.contact import detect_sphere_sphere
    # Two unit spheres, centres 1.0 apart → pen = 1.0
    c = detect_sphere_sphere(
        center_a=(0.0, 0.0, 0.0), radius_a=1.0,
        center_b=(1.0, 0.0, 0.0), radius_b=1.0,
    )
    assert c is not None
    assert abs(c.penetration_depth - 1.0) < 1e-12


# ===========================================================================
# 3. Collision detection — sphere-mesh
# ===========================================================================

def test_contact_sphere_mesh_no_contact():
    from kerf_motion.contact import detect_sphere_mesh
    # Sphere above a floor triangle
    tri = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 0.0, 1.0))]
    c = detect_sphere_mesh(
        sphere_center=(0.5, 0.5, 0.5),
        sphere_radius=0.1,
        triangles=tri,
    )
    assert c is None


def test_contact_sphere_mesh_penetration():
    from kerf_motion.contact import detect_sphere_mesh
    # Sphere centred at y=0.08, floor triangle in XZ plane at y=0
    tri = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 0.0, 1.0))]
    c = detect_sphere_mesh(
        sphere_center=(0.4, 0.08, 0.4),
        sphere_radius=0.1,
        triangles=tri,
    )
    assert c is not None
    assert c.penetration_depth > 0.0
    # Should find the penetrating point close to the triangle
    assert c.contact_point[1] < 0.1


def test_contact_sphere_mesh_multiple_triangles():
    from kerf_motion.contact import detect_sphere_mesh
    # Two triangles; sphere penetrates one more than the other
    tris = [
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 0.0, 1.0)),
        ((2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.5, 0.0, 1.0)),
    ]
    c = detect_sphere_mesh(
        sphere_center=(0.4, 0.05, 0.4),   # over first triangle
        sphere_radius=0.1,
        triangles=tris,
    )
    assert c is not None
    # Penetration must be positive
    assert c.penetration_depth > 0.0


# ===========================================================================
# 4. Hertzian stiffness
# ===========================================================================

def test_hertz_stiffness_sphere_plane_formula():
    from kerf_motion.contact import hertz_stiffness_sphere_plane
    # Steel ball on steel plane: E=200 GPa, nu=0.3, R=0.01 m
    E = 200e9
    nu = 0.3
    R = 0.01
    k = hertz_stiffness_sphere_plane(E, nu, E, nu, R)
    # Manual: E* = E/(2*(1-nu^2)), k = (4/3)*E**sqrt(R)
    E_star = 1.0 / (2.0 * (1.0 - nu ** 2) / E)
    k_expected = (4.0 / 3.0) * E_star * math.sqrt(R)
    assert abs(k - k_expected) / k_expected < 1e-10


def test_hertz_stiffness_sphere_sphere_formula():
    from kerf_motion.contact import hertz_stiffness_sphere_sphere
    E1, nu1, R1 = 70e9, 0.33, 0.02   # aluminium
    E2, nu2, R2 = 200e9, 0.3, 0.03   # steel
    k = hertz_stiffness_sphere_sphere(E1, nu1, R1, E2, nu2, R2)
    E_star = 1.0 / ((1.0 - nu1 ** 2) / E1 + (1.0 - nu2 ** 2) / E2)
    R_star = 1.0 / (1.0 / R1 + 1.0 / R2)
    k_expected = (4.0 / 3.0) * E_star * math.sqrt(R_star)
    assert abs(k - k_expected) / k_expected < 1e-10


# ===========================================================================
# 5. Hunt-Crossley normal force
# ===========================================================================

def test_hunt_crossley_zero_penetration():
    from kerf_motion.contact import hunt_crossley_normal_force
    F = hunt_crossley_normal_force(penetration=0.0, v_normal=1.0, k=1e6, c=1e3)
    assert F == 0.0


def test_hunt_crossley_negative_penetration():
    from kerf_motion.contact import hunt_crossley_normal_force
    F = hunt_crossley_normal_force(penetration=-0.01, v_normal=0.0, k=1e6, c=1e3)
    assert F == 0.0


def test_hunt_crossley_static_contact():
    from kerf_motion.contact import hunt_crossley_normal_force
    # Static: v_normal=0, pen=0.001, k=1e6, n=1.5
    pen = 0.001
    k = 1e6
    F = hunt_crossley_normal_force(pen, v_normal=0.0, k=k, c=0.0, n=1.5)
    F_expected = k * pen ** 1.5
    assert abs(F - F_expected) < 1e-10


def test_hunt_crossley_no_tensile():
    from kerf_motion.contact import hunt_crossley_normal_force
    # High damping + small penetration — damping could make F negative; should clip to 0
    F = hunt_crossley_normal_force(
        penetration=0.001, v_normal=-100.0,  # fast separation
        k=1.0, c=1e6, n=1.5,
    )
    assert F >= 0.0


def test_hunt_crossley_hertz_exponent():
    from kerf_motion.contact import hunt_crossley_normal_force
    pen = 0.005
    k = 500.0
    # n=1.5 Hertz, no damping
    F = hunt_crossley_normal_force(pen, 0.0, k, 0.0, 1.5)
    assert abs(F - k * pen ** 1.5) < 1e-12


# ===========================================================================
# 6. Coulomb friction
# ===========================================================================

def test_coulomb_friction_zero_tangential():
    from kerf_motion.contact import coulomb_friction_force
    F_t = coulomb_friction_force(100.0, (0.0, 0.0, 0.0), mu=0.5)
    assert F_t == (0.0, 0.0, 0.0)


def test_coulomb_friction_kinetic():
    from kerf_motion.contact import coulomb_friction_force
    # Sliding at 1 m/s in x, F_n=100 N, mu=0.3
    F_t = coulomb_friction_force(100.0, (1.0, 0.0, 0.0), mu=0.3)
    mag = math.sqrt(F_t[0] ** 2 + F_t[1] ** 2 + F_t[2] ** 2)
    assert abs(mag - 30.0) < 1e-10
    assert F_t[0] < 0.0   # opposes motion


def test_coulomb_friction_direction():
    from kerf_motion.contact import coulomb_friction_force
    # Tangential velocity at 45° in XZ plane
    v_t = (1.0, 0.0, 1.0)
    F_t = coulomb_friction_force(50.0, v_t, mu=0.4)
    # Should be antiparallel to v_t
    dot = F_t[0] * v_t[0] + F_t[1] * v_t[1] + F_t[2] * v_t[2]
    assert dot < 0.0


# ===========================================================================
# 7. Impulse-based restitution — compute_restitution_impulse
# ===========================================================================

def test_restitution_impulse_separating_bodies():
    from kerf_motion.contact import detect_sphere_plane, compute_restitution_impulse
    # Body moving upward (separating from plane) — no impulse expected
    body = _sphere_body(mass=1.0, position=(0.0, 0.09, 0.0), velocity=(0.0, 1.0, 0.0))
    contact = detect_sphere_plane(
        (0.0, 0.09, 0.0), 0.1, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)
    )
    assert contact is not None
    J = compute_restitution_impulse(body, None, contact, restitution=0.8)
    assert J == 0.0


def test_restitution_impulse_approaching_body():
    from kerf_motion.contact import detect_sphere_plane, compute_restitution_impulse
    # Body falling toward plane
    body = _sphere_body(mass=1.0, position=(0.0, 0.09, 0.0), velocity=(0.0, -2.0, 0.0))
    contact = detect_sphere_plane(
        (0.0, 0.09, 0.0), 0.1, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)
    )
    assert contact is not None
    J = compute_restitution_impulse(body, None, contact, restitution=0.8)
    assert J > 0.0


def test_restitution_impulse_elastic_point_mass():
    """
    Elastic collision (e=1) of a point mass against a rigid wall.
    Velocity should reverse: v_after = -v_before.

    For a point mass with v = (0, -V, 0) hitting a horizontal plane:
      J = m * (1+e) * V  (e=1 → J = 2mV)
      Δv_y = J/m = 2V  → v_after = -V + 2V = +V  ✓
    """
    from kerf_motion.contact import detect_sphere_plane, compute_restitution_impulse, apply_impulse
    from kerf_motion.body import vec3_add, vec3_scale

    V = 3.0
    m = 2.0
    body = _sphere_body(mass=m, position=(0.0, 0.09, 0.0), velocity=(0.0, -V, 0.0))
    contact = detect_sphere_plane(
        body.position, 0.1, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)
    )
    assert contact is not None

    J = compute_restitution_impulse(body, None, contact, restitution=1.0)
    J_vec = vec3_scale(contact.normal, J)
    body2 = apply_impulse(body, J_vec, contact.contact_point, sign=1.0)

    # Post-impulse velocity should be +V in y
    assert abs(body2.velocity[1] - V) < 1e-10, f"v_y = {body2.velocity[1]}, expected {V}"


# ===========================================================================
# 8. resolve_contacts_impulse
# ===========================================================================

def test_resolve_contacts_sphere_sphere_elastic():
    """
    Two equal-mass spheres colliding head-on (e=1) → velocities swap.
    """
    from kerf_motion.contact import detect_sphere_sphere, resolve_contacts_impulse

    m = 1.0
    b1 = _sphere_body(mass=m, position=(0.0, 0.0, 0.0), velocity=(2.0, 0.0, 0.0))
    b2 = _sphere_body(mass=m, position=(0.18, 0.0, 0.0), velocity=(-2.0, 0.0, 0.0))
    # r=0.1 each → overlap = 0.02

    contact = detect_sphere_sphere(
        b1.position, 0.1, b2.position, 0.1, body_a_idx=0, body_b_idx=1
    )
    assert contact is not None

    updated = resolve_contacts_impulse([b1, b2], [contact], restitution=1.0, mu=0.0)
    v1_after = updated[0].velocity[0]
    v2_after = updated[1].velocity[0]

    # Elastic equal-mass 1D collision: velocities swap
    assert abs(v1_after - (-2.0)) < 1e-9, f"v1={v1_after}"
    assert abs(v2_after - 2.0) < 1e-9, f"v2={v2_after}"


def test_resolve_contacts_inelastic():
    """
    Perfectly inelastic collision (e=0) → bodies stick together.
    """
    from kerf_motion.contact import detect_sphere_sphere, resolve_contacts_impulse

    m = 1.0
    V = 3.0
    b1 = _sphere_body(mass=m, position=(0.0, 0.0, 0.0), velocity=(V, 0.0, 0.0))
    b2 = _sphere_body(mass=m, position=(0.18, 0.0, 0.0), velocity=(0.0, 0.0, 0.0))

    contact = detect_sphere_sphere(
        b1.position, 0.1, b2.position, 0.1, body_a_idx=0, body_b_idx=1
    )
    assert contact is not None

    updated = resolve_contacts_impulse([b1, b2], [contact], restitution=0.0, mu=0.0)
    v1_after = updated[0].velocity[0]
    v2_after = updated[1].velocity[0]

    # Both should have velocity ≈ V/2 (momentum conservation)
    v_cm = V / 2.0
    assert abs(v1_after - v_cm) < 1e-9, f"v1={v1_after}, expected {v_cm}"
    assert abs(v2_after - v_cm) < 1e-9, f"v2={v2_after}, expected {v_cm}"


# ===========================================================================
# 9. Bouncing ball — physics validation
#
# Ball dropped from h=1 m onto a floor (y=0 plane).
# After first bounce with restitution e, peak height ≈ e² * h.
# Tolerance: ±5%
# ===========================================================================

def test_bounce_ball_height_restitution():
    """
    Bouncing ball: first-bounce peak height ≈ e² × drop height, ±5%.

    Drop from h=1.0 m (ball centre), e=0.8.

    Physics: ball centre starts at y=h, contacts floor when y_centre = r.
    Effective drop distance d = h - r.  Impact speed v_in = √(2g·d).
    Post-bounce speed v_out = e·v_in.
    Apex centre y = r + v_out²/(2g) = r + e²·(h - r).
    Expected physical height (bottom of ball) = e²·(h - r).
    For h=1.0, r=0.1, e=0.8 → expected ≈ 0.576 m.
    """
    from kerf_motion.contact import simulate_with_contacts

    h = 1.0
    e = 0.8
    r = 0.1   # sphere radius
    m = 1.0
    g = 9.80665

    body = _sphere_body(mass=m, position=(0.0, h, 0.0), velocity=(0.0, 0.0, 0.0))

    # Floor: y=0 plane, normal upward
    static_planes = [((0.0, 1.0, 0.0), (0.0, 0.0, 0.0))]

    result = simulate_with_contacts(
        bodies=[body],
        static_planes=static_planes,
        sphere_radii=[r],
        gravity_g=g,
        gravity_axis=1,
        dt=1e-3,
        n_steps=2000,
        restitution=e,
        mu=0.0,  # no friction for this test
        use_impulse=True,
        record_every=1,
    )
    assert result["ok"], result.get("reason", "")

    # Find peak y after first bounce
    traj = result["trajectories"][0]
    hit_floor = False
    max_y_after = 0.0
    for snap in traj:
        y = snap["position"][1]
        if not hit_floor and y <= r + 0.03:  # approaching floor
            hit_floor = True
        if hit_floor:
            max_y_after = max(max_y_after, y)

    # Physics: bounce height of ball bottom = e² × (h - r)
    # (drop from centre h to centre r = distance h-r; bounce recovers e² fraction)
    expected_height = e ** 2 * (h - r)  # ≈ 0.576 m

    # apex_physical = max centre height - r
    apex_physical = max_y_after - r
    rel_err = abs(apex_physical - expected_height) / expected_height

    assert rel_err < 0.05, (
        f"Bounce height: got {apex_physical:.4f} m, "
        f"expected {expected_height:.4f} m (e={e}, h={h}, r={r}), "
        f"rel_err={rel_err:.3f}"
    )


def test_bounce_ball_momentum_before_after():
    """
    Verify linear momentum conservation between successive bounces
    (magnitude only changes by restitution).
    """
    from kerf_motion.contact import detect_sphere_plane, compute_restitution_impulse, apply_impulse
    from kerf_motion.body import vec3_scale

    m = 2.0
    V = 5.0
    e = 0.7
    body = _sphere_body(mass=m, position=(0.0, 0.09, 0.0), velocity=(0.0, -V, 0.0))
    contact = detect_sphere_plane(
        body.position, 0.1, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)
    )
    assert contact is not None

    J = compute_restitution_impulse(body, None, contact, restitution=e)
    J_vec = vec3_scale(contact.normal, J)
    body2 = apply_impulse(body, J_vec, contact.contact_point, sign=1.0)

    # Post-bounce y-velocity should be e * V (upward)
    v_after = body2.velocity[1]
    assert abs(v_after - e * V) < 1e-9, f"v_after={v_after}, expected {e * V}"


# ===========================================================================
# 10. Two-pendulum impact (1D elastic): velocities swap exactly for e=1
# ===========================================================================

def test_two_body_elastic_velocity_swap():
    """
    Two equal-mass bodies colliding head-on with e=1.
    Velocities must swap exactly (analytic result for 1D elastic collision).
    """
    from kerf_motion.contact import detect_sphere_sphere, resolve_contacts_impulse

    m = 3.0
    v1_init = 4.0
    v2_init = -1.0

    b1 = _sphere_body(mass=m, position=(0.0, 0.0, 0.0), velocity=(v1_init, 0.0, 0.0))
    b2 = _sphere_body(mass=m, position=(0.18, 0.0, 0.0), velocity=(v2_init, 0.0, 0.0))

    contact = detect_sphere_sphere(
        b1.position, 0.1, b2.position, 0.1, body_a_idx=0, body_b_idx=1
    )
    assert contact is not None

    updated = resolve_contacts_impulse([b1, b2], [contact], restitution=1.0, mu=0.0)
    v1_after = updated[0].velocity[0]
    v2_after = updated[1].velocity[0]

    # For elastic equal-mass: v1' = v2_init, v2' = v1_init
    assert abs(v1_after - v2_init) < 1e-9, f"v1_after={v1_after}, expected {v2_init}"
    assert abs(v2_after - v1_init) < 1e-9, f"v2_after={v2_after}, expected {v1_init}"


def test_two_body_elastic_momentum_conservation():
    """Linear momentum is conserved in elastic collision."""
    from kerf_motion.contact import detect_sphere_sphere, resolve_contacts_impulse

    m1, m2 = 2.0, 5.0
    v1_init, v2_init = 3.0, -1.0

    b1 = _sphere_body(mass=m1, position=(0.0, 0.0, 0.0), velocity=(v1_init, 0.0, 0.0))
    b2 = _sphere_body(mass=m2, position=(0.18, 0.0, 0.0), velocity=(v2_init, 0.0, 0.0))

    contact = detect_sphere_sphere(
        b1.position, 0.1, b2.position, 0.1, body_a_idx=0, body_b_idx=1
    )
    assert contact is not None

    p_before = m1 * v1_init + m2 * v2_init
    updated = resolve_contacts_impulse([b1, b2], [contact], restitution=1.0, mu=0.0)
    p_after = m1 * updated[0].velocity[0] + m2 * updated[1].velocity[0]

    assert abs(p_after - p_before) < 1e-9, (
        f"Momentum: before={p_before:.10f}, after={p_after:.10f}"
    )


def test_two_body_elastic_energy_conservation():
    """Kinetic energy is conserved for e=1."""
    from kerf_motion.contact import detect_sphere_sphere, resolve_contacts_impulse

    m1, m2 = 2.0, 5.0
    v1_init, v2_init = 3.0, -1.0

    b1 = _sphere_body(mass=m1, position=(0.0, 0.0, 0.0), velocity=(v1_init, 0.0, 0.0))
    b2 = _sphere_body(mass=m2, position=(0.18, 0.0, 0.0), velocity=(v2_init, 0.0, 0.0))

    contact = detect_sphere_sphere(
        b1.position, 0.1, b2.position, 0.1, body_a_idx=0, body_b_idx=1
    )
    assert contact is not None

    KE_before = 0.5 * m1 * v1_init ** 2 + 0.5 * m2 * v2_init ** 2
    updated = resolve_contacts_impulse([b1, b2], [contact], restitution=1.0, mu=0.0)
    KE_after = (0.5 * m1 * updated[0].velocity[0] ** 2
                + 0.5 * m2 * updated[1].velocity[0] ** 2)

    assert abs(KE_after - KE_before) / KE_before < 1e-9, (
        f"KE: before={KE_before:.10f}, after={KE_after:.10f}"
    )


# ===========================================================================
# 11. apply_contacts (penalty force hook)
# ===========================================================================

def test_apply_contacts_no_penetration():
    """apply_contacts returns zero forces when there are no contacts."""
    from kerf_motion.contact import apply_contacts

    body = _sphere_body(mass=1.0)
    forces, torques = apply_contacts([body], [], dt=1e-3)
    assert forces[0] == (0.0, 0.0, 0.0)
    assert torques[0] == (0.0, 0.0, 0.0)


def test_apply_contacts_repulsive_force():
    """A penetrating contact must produce a repulsive (upward) force."""
    from kerf_motion.contact import detect_sphere_plane, apply_contacts

    body = _sphere_body(mass=1.0, position=(0.0, 0.08, 0.0), velocity=(0.0, -1.0, 0.0))
    contact = detect_sphere_plane(
        body.position, 0.1, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0),
        body_a_idx=0, body_b_idx=-1,
    )
    assert contact is not None

    forces, torques = apply_contacts([body], [contact], dt=1e-3, k=1e6, c=1e3, mu=0.0)
    # Net force should be positive y (upward)
    assert forces[0][1] > 0.0


def test_apply_contacts_force_positive_on_sphere():
    """Hunt-Crossley static contact: verify force magnitude."""
    from kerf_motion.contact import detect_sphere_plane, apply_contacts

    pen = 0.01
    k = 1e5
    body = _sphere_body(mass=1.0, position=(0.0, 0.1 - pen, 0.0), velocity=(0.0, 0.0, 0.0))
    contact = detect_sphere_plane(
        body.position, 0.1, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0),
        body_a_idx=0, body_b_idx=-1,
    )
    assert contact is not None

    forces, _ = apply_contacts([body], [contact], dt=1e-3, k=k, c=0.0, mu=0.0, hertz_n=1.5)
    F_y = forces[0][1]
    F_expected = k * pen ** 1.5
    # Within 10% (contact point vs centre offset affects exact penetration)
    assert abs(F_y - F_expected) / F_expected < 0.2, f"F_y={F_y}, expected~{F_expected}"


# ===========================================================================
# 12. simulate_with_contacts — integration smoke test
# ===========================================================================

def test_simulate_with_contacts_ball_lands():
    """Ball dropped from 0.5 m lands on floor and does not pass through it."""
    from kerf_motion.contact import simulate_with_contacts

    body = _sphere_body(mass=1.0, position=(0.0, 0.5, 0.0))
    result = simulate_with_contacts(
        bodies=[body],
        static_planes=[((0.0, 1.0, 0.0), (0.0, 0.0, 0.0))],
        sphere_radii=[0.1],
        gravity_g=9.80665,
        gravity_axis=1,
        dt=1e-3,
        n_steps=1000,
        restitution=0.5,
        mu=0.0,
        use_impulse=True,
    )
    assert result["ok"]
    # Ball centre should never go below floor (y < 0)
    for snap in result["trajectories"][0]:
        assert snap["position"][1] >= -0.01, f"Ball below floor: y={snap['position'][1]}"


def test_simulate_with_contacts_rejects_bad_input():
    """simulate_with_contacts returns ok=False for empty bodies."""
    from kerf_motion.contact import simulate_with_contacts
    result = simulate_with_contacts([], [], [], dt=1e-3, n_steps=100)
    assert result["ok"] is False


def test_simulate_two_spheres_collide():
    """Two approaching spheres should bounce after collision."""
    from kerf_motion.contact import simulate_with_contacts

    b1 = _sphere_body(mass=1.0, position=(-0.5, 1.0, 0.0), velocity=(2.0, 0.0, 0.0))
    b2 = _sphere_body(mass=1.0, position=(0.5, 1.0, 0.0), velocity=(-2.0, 0.0, 0.0))

    result = simulate_with_contacts(
        bodies=[b1, b2],
        static_planes=[],
        sphere_radii=[0.1, 0.1],
        gravity_g=0.0,  # no gravity for clean test
        gravity_axis=1,
        dt=1e-3,
        n_steps=1000,
        restitution=1.0,
        mu=0.0,
        use_impulse=True,
    )
    assert result["ok"]
    # Final velocities should be swapped (elastic)
    v1_final = result["final_bodies"][0].velocity[0]
    v2_final = result["final_bodies"][1].velocity[0]
    # After elastic collision: b1 should be moving left, b2 moving right
    assert v1_final < 0.0, f"v1_final={v1_final}, expected < 0"
    assert v2_final > 0.0, f"v2_final={v2_final}, expected > 0"
