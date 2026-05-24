"""
kerf_motion.contact
===================
3-D contact / collision dynamics for rigid-body simulation.

Provides:
  - Collision detection primitives (sphere-plane, sphere-sphere, sphere-mesh)
  - Penalty / Hunt-Crossley non-linear spring-damper contact force model
  - Coulomb friction (tangential)
  - Hertzian elastic contact (sphere-plane, sphere-sphere)
  - Impulse-based restitution (coefficient-of-restitution model)
  - apply_contacts() hook for the existing RK4 integrator loop

All pure Python — no numpy, no shared _linalg.

References
----------
* Goldsmith, Impact (2001)
* Hunt & Crossley, J. Appl. Mech 42:440-445 (1975)
* Johnson, Contact Mechanics (1985)
* Mirtich, Fast and Accurate Computation of Polyhedral Mass Properties (1996)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Re-use the pure-Python vector helpers from body.py (same file, guaranteed present)
from kerf_motion.body import (
    RigidBody,
    Vec3,
    vec3_add,
    vec3_sub,
    vec3_scale,
    vec3_dot,
    vec3_cross,
    vec3_norm,
    mat3_vec,
)

# LLM tool registry — optional; gracefully skipped if not in the full stack
try:
    from kerf_chat.tools.registry import ToolSpec, ok_payload, err_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_motion._compat import ToolSpec, ok_payload, err_payload, ProjectCtx


# ---------------------------------------------------------------------------
# Contact descriptor
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    """
    Describes a detected contact between two bodies (or body + world).

    Attributes
    ----------
    normal : Vec3
        Unit contact normal pointing from body_b toward body_a
        (i.e. from surface into the penetrating object).
    penetration_depth : float
        Positive value = how far the objects overlap (m).
    contact_point : Vec3
        World-frame position of the contact point.
    body_a_idx : int
        Index of the first (penetrating) body.  -1 = world/static.
    body_b_idx : int
        Index of the second (surface) body.  -1 = world/static plane.
    """
    normal: Vec3
    penetration_depth: float
    contact_point: Vec3
    body_a_idx: int = 0
    body_b_idx: int = -1


# ---------------------------------------------------------------------------
# Internal vector helpers (not exported)
# ---------------------------------------------------------------------------

def _vec3_normalize(v: Vec3) -> Vec3:
    n = vec3_norm(v)
    if n < 1e-300:
        return (1.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _vec3_project_onto(v: Vec3, n: Vec3) -> Vec3:
    """Component of v along n (n should be unit)."""
    s = vec3_dot(v, n)
    return vec3_scale(n, s)


def _vec3_reject_from(v: Vec3, n: Vec3) -> Vec3:
    """Tangential component of v (perpendicular to n)."""
    return vec3_sub(v, _vec3_project_onto(v, n))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# 1. Collision detection primitives
# ---------------------------------------------------------------------------

def detect_sphere_plane(
    sphere_center: Vec3,
    sphere_radius: float,
    plane_normal: Vec3,
    plane_point: Vec3,
    body_a_idx: int = 0,
    body_b_idx: int = -1,
) -> Optional[Contact]:
    """
    Signed-distance sphere-plane test.

    d = n · (C - P_o)
    penetration = radius - d   (positive when sphere penetrates plane)

    Parameters
    ----------
    sphere_center  : world-frame centre of sphere
    sphere_radius  : radius (m)
    plane_normal   : unit outward normal of the plane (pointing away from solid)
    plane_point    : any point on the plane
    body_a_idx     : index of sphere body
    body_b_idx     : index of plane body (-1 = world)

    Returns
    -------
    Contact if penetrating, else None.
    """
    n = _vec3_normalize(plane_normal)
    diff = vec3_sub(sphere_center, plane_point)
    d = vec3_dot(n, diff)                     # signed distance centre → plane
    penetration = sphere_radius - d
    if penetration <= 0.0:
        return None
    # Contact point: centre - r*n (foot of sphere on plane)
    cp = vec3_sub(sphere_center, vec3_scale(n, sphere_radius - penetration * 0.5))
    return Contact(
        normal=n,
        penetration_depth=penetration,
        contact_point=cp,
        body_a_idx=body_a_idx,
        body_b_idx=body_b_idx,
    )


def detect_sphere_sphere(
    center_a: Vec3,
    radius_a: float,
    center_b: Vec3,
    radius_b: float,
    body_a_idx: int = 0,
    body_b_idx: int = 1,
) -> Optional[Contact]:
    """
    Sphere-sphere collision test.

    d = |C_a - C_b| - (r_a + r_b)   (negative → penetrating)

    Returns
    -------
    Contact if penetrating, else None.
    Normal points from b toward a.
    """
    diff = vec3_sub(center_a, center_b)
    dist = vec3_norm(diff)
    sum_r = radius_a + radius_b
    penetration = sum_r - dist
    if penetration <= 0.0:
        return None
    n: Vec3
    if dist < 1e-300:
        n = (0.0, 1.0, 0.0)   # degenerate: coincident centres
    else:
        n = _vec3_normalize(diff)
    # Contact point: midpoint on overlapping surface
    cp = vec3_add(center_b, vec3_scale(n, radius_b - penetration * 0.5))
    return Contact(
        normal=n,
        penetration_depth=penetration,
        contact_point=cp,
        body_a_idx=body_a_idx,
        body_b_idx=body_b_idx,
    )


def _closest_point_on_triangle(
    p: Vec3,
    a: Vec3,
    b: Vec3,
    c: Vec3,
) -> Vec3:
    """
    Closest point on triangle ABC to point P (Ericson 2005, §5.1.5).
    Pure Python, no numpy.
    """
    ab = vec3_sub(b, a)
    ac = vec3_sub(c, a)
    ap = vec3_sub(p, a)

    d1 = vec3_dot(ab, ap)
    d2 = vec3_dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return a  # vertex A region

    bp = vec3_sub(p, b)
    d3 = vec3_dot(ab, bp)
    d4 = vec3_dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return b  # vertex B region

    cp_pt = vec3_sub(p, c)
    d5 = vec3_dot(ab, cp_pt)
    d6 = vec3_dot(ac, cp_pt)
    if d6 >= 0.0 and d5 <= d6:
        return c  # vertex C region

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        return vec3_add(a, vec3_scale(ab, v))  # edge AB

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        return vec3_add(a, vec3_scale(ac, w))  # edge AC

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return vec3_add(b, vec3_scale(vec3_sub(c, b), w))  # edge BC

    denom = 1.0 / (vc + vb + va)
    v = vb * denom
    w = vc * denom
    # barycentric interior
    return vec3_add(a, vec3_add(vec3_scale(ab, v), vec3_scale(ac, w)))


def detect_sphere_mesh(
    sphere_center: Vec3,
    sphere_radius: float,
    triangles: List[Tuple[Vec3, Vec3, Vec3]],
    body_a_idx: int = 0,
    body_b_idx: int = -1,
) -> Optional[Contact]:
    """
    Sphere-triangle-mesh collision test.

    Iterates over all triangles, finds the one with maximum penetration depth.

    Parameters
    ----------
    sphere_center : world-frame sphere centre
    sphere_radius : sphere radius (m)
    triangles     : list of (A, B, C) vertex tuples in world frame
    body_a_idx    : sphere body index
    body_b_idx    : mesh body index (-1 = static world)

    Returns
    -------
    Contact at deepest triangle, or None if no penetration.
    """
    best: Optional[Contact] = None
    best_depth = 0.0

    for tri in triangles:
        a, b, c = tri
        closest = _closest_point_on_triangle(sphere_center, a, b, c)
        diff = vec3_sub(sphere_center, closest)
        dist = vec3_norm(diff)
        pen = sphere_radius - dist
        if pen <= 0.0:
            continue
        if dist < 1e-300:
            # Centre exactly on triangle — use triangle normal
            ab = vec3_sub(b, a)
            ac = vec3_sub(c, a)
            n = _vec3_normalize(vec3_cross(ab, ac))
        else:
            n = _vec3_normalize(diff)
        if pen > best_depth:
            best_depth = pen
            best = Contact(
                normal=n,
                penetration_depth=pen,
                contact_point=closest,
                body_a_idx=body_a_idx,
                body_b_idx=body_b_idx,
            )

    return best


# ---------------------------------------------------------------------------
# 2. Hertzian contact stiffness helpers
# ---------------------------------------------------------------------------

def hertz_stiffness_sphere_plane(
    E1: float, nu1: float,
    E2: float, nu2: float,
    R: float,
) -> float:
    """
    Hertz contact stiffness k = (4/3) · E* · √R
    for a sphere (radius R, modulus E1, Poisson ν1) on a rigid plane
    (modulus E2, Poisson ν2).

    E* = combined modulus:  1/E* = (1-ν1²)/E1 + (1-ν2²)/E2

    Parameters
    ----------
    E1, E2 : Young's moduli (Pa)
    nu1, nu2 : Poisson's ratios
    R : sphere radius (m)

    Returns
    -------
    k (N/m^(3/2))
    """
    E_star = 1.0 / ((1.0 - nu1 ** 2) / E1 + (1.0 - nu2 ** 2) / E2)
    return (4.0 / 3.0) * E_star * math.sqrt(R)


def hertz_stiffness_sphere_sphere(
    E1: float, nu1: float, R1: float,
    E2: float, nu2: float, R2: float,
) -> float:
    """
    Hertz contact stiffness k = (4/3) · E* · √R*
    for two spheres in contact.

    E* = combined modulus, R* = combined radius:
        1/R* = 1/R1 + 1/R2

    Returns
    -------
    k (N/m^(3/2))
    """
    E_star = 1.0 / ((1.0 - nu1 ** 2) / E1 + (1.0 - nu2 ** 2) / E2)
    R_star = 1.0 / (1.0 / R1 + 1.0 / R2)
    return (4.0 / 3.0) * E_star * math.sqrt(R_star)


# ---------------------------------------------------------------------------
# 3. Contact force models
# ---------------------------------------------------------------------------

def hunt_crossley_normal_force(
    penetration: float,
    v_normal: float,
    k: float,
    c: float,
    n: float = 1.5,
) -> float:
    """
    Hunt-Crossley non-linear spring-damper normal force.

    F_n = k · δ^n - c · δ · v_n

    where:
        δ  = penetration depth  (positive = overlap)
        v_n = relative normal velocity (positive = approaching → compressive)
        k  = stiffness (N/m^n)
        c  = damping coefficient (N·s/m^(n+1))
        n  = Hertz exponent (1.5 for sphere-on-plane, sphere-on-sphere)

    The force is clipped to ≥ 0 (no tensile adhesion).

    Returns
    -------
    F_n : float   (N, positive = repulsive along contact normal)
    """
    if penetration <= 0.0:
        return 0.0
    delta_n = penetration ** n
    F = k * delta_n - c * penetration * v_normal
    return max(0.0, F)


def coulomb_friction_force(
    F_normal: float,
    v_tangential: Vec3,
    mu: float,
    mu_static: Optional[float] = None,
    v_slip_tol: float = 1e-6,
) -> Vec3:
    """
    Coulomb friction tangential force.

    Kinetic: F_t = -μ · |F_n| · v_t / |v_t|
    Static (stiction): if |v_t| < v_slip_tol, clamp to μ_s · |F_n|.

    Parameters
    ----------
    F_normal     : magnitude of normal contact force (N)
    v_tangential : tangential relative velocity vector (m/s)
    mu           : kinetic friction coefficient
    mu_static    : static friction coefficient (defaults to mu)
    v_slip_tol   : velocity below which stiction kicks in (m/s)

    Returns
    -------
    Friction force vector (N) in world frame.
    """
    if mu_static is None:
        mu_static = mu
    vt_mag = vec3_norm(v_tangential)
    F_n_mag = abs(F_normal)

    if vt_mag < v_slip_tol:
        # Static regime: zero friction force (body not sliding)
        return (0.0, 0.0, 0.0)

    # Kinetic regime
    f_mag = mu * F_n_mag
    vt_dir = vec3_scale(v_tangential, 1.0 / vt_mag)
    return vec3_scale(vt_dir, -f_mag)


# ---------------------------------------------------------------------------
# 4. Impulse-based restitution
# ---------------------------------------------------------------------------

def compute_restitution_impulse(
    body_a: RigidBody,
    body_b: Optional[RigidBody],
    contact: Contact,
    restitution: float,
) -> float:
    """
    Impulse-based collision response: J = -(1 + e) · v_rel · n / (1/m_a + 1/m_b + rotational terms)

    Ref: Mirtich & Canny (1995), Baraff rigid body dynamics.

    Parameters
    ----------
    body_a      : first body (may be moving)
    body_b      : second body (None = infinite-mass static surface)
    contact     : Contact descriptor (normal points from b toward a)
    restitution : coefficient of restitution e  (0 = perfectly inelastic, 1 = elastic)

    Returns
    -------
    J : float   (impulse magnitude, to be applied along contact.normal)
    """
    n = contact.normal
    cp = contact.contact_point

    # Relative velocity at contact point (body_a relative to body_b)
    r_a = vec3_sub(cp, body_a.position)
    v_a = vec3_add(body_a.velocity,
                   vec3_cross(body_a.angular_velocity, r_a))

    if body_b is not None:
        r_b = vec3_sub(cp, body_b.position)
        v_b = vec3_add(body_b.velocity,
                       vec3_cross(body_b.angular_velocity, r_b))
    else:
        v_b = (0.0, 0.0, 0.0)

    v_rel = vec3_sub(v_a, v_b)
    v_rel_n = vec3_dot(v_rel, n)

    # Only process if bodies are approaching
    if v_rel_n >= 0.0:
        return 0.0

    # Effective mass term: 1/m_a + 1/m_b + rot_a + rot_b
    m_a_inv = 1.0 / body_a.mass

    # Rotational contribution: n · (r_a × n) / (I_a⁻¹ applied in world frame)
    #   = n · ( I_world_inv_a · (r_a × n) ) ... wait, correct form is:
    #   ( r_a × n )ᵀ I_world_inv_a ( r_a × n )  but for impulse along n:
    #   effective inv mass adds  n · [I⁻¹(r × n)] × r for rotational.
    # Using standard formula: Δ_rot = (r_a × n) · (I_w_inv · (r_a × n))
    I_a_inv_world = body_a.I_world_inv()
    ra_cross_n = vec3_cross(r_a, n)
    Iinv_ra_cross_n_a = mat3_vec(I_a_inv_world, ra_cross_n)
    rot_a = vec3_dot(ra_cross_n, Iinv_ra_cross_n_a)

    denom = m_a_inv + rot_a

    if body_b is not None:
        m_b_inv = 1.0 / body_b.mass
        I_b_inv_world = body_b.I_world_inv()
        rb_cross_n = vec3_cross(r_b, n)
        Iinv_ra_cross_n_b = mat3_vec(I_b_inv_world, rb_cross_n)
        rot_b = vec3_dot(rb_cross_n, Iinv_ra_cross_n_b)
        denom += m_b_inv + rot_b

    if abs(denom) < 1e-300:
        return 0.0

    J = -(1.0 + restitution) * v_rel_n / denom
    return J


def apply_impulse(
    body: RigidBody,
    impulse_vec: Vec3,
    contact_point: Vec3,
    sign: float = 1.0,
) -> RigidBody:
    """
    Apply an impulse to a body, updating velocity and angular velocity.

    Δv = ±J_vec / m
    Δω_body = ±R^T · (r × J_vec) · I_body_inv  (Euler: I·Δω = r × J)

    Returns a new RigidBody with updated velocity / angular_velocity.
    """
    from dataclasses import replace
    from kerf_motion.body import mat3_T, mat3_vec, quat_to_rotmat

    J_vec = vec3_scale(impulse_vec, sign)
    m_inv = 1.0 / body.mass

    # Linear velocity update
    new_vel = vec3_add(body.velocity, vec3_scale(J_vec, m_inv))

    # Angular: r × J in world frame, then Iinv in world frame
    r = vec3_sub(contact_point, body.position)
    r_cross_J = vec3_cross(r, J_vec)
    I_world_inv = body.I_world_inv()
    delta_omega_world = mat3_vec(I_world_inv, r_cross_J)

    # Convert world Δω → body frame
    R = quat_to_rotmat(body.orientation)  # type: ignore[arg-type]
    Rt = mat3_T(R)
    delta_omega_body = mat3_vec(Rt, delta_omega_world)

    new_omega = vec3_add(body.angular_velocity, delta_omega_body)
    return replace(body, velocity=new_vel, angular_velocity=new_omega)


# ---------------------------------------------------------------------------
# 5. apply_contacts — integrator hook
# ---------------------------------------------------------------------------

def apply_contacts(
    bodies: List[RigidBody],
    contacts: List[Contact],
    dt: float,
    *,
    k: float = 1e6,
    c: float = 1e3,
    mu: float = 0.4,
    restitution: float = 0.6,
    hertz_n: float = 1.5,
    impulse_threshold: float = 0.0,
) -> Tuple[List[Vec3], List[Vec3]]:
    """
    Compute and accumulate contact forces and torques for all detected contacts.

    Can be called *before* each RK4 step to add penalty contact forces, or used
    to apply instantaneous impulses when penetration is detected.

    Strategy used here: **penalty forces** (Hunt-Crossley) + Coulomb friction.
    This integrates cleanly with the existing RK4 force-field mechanism.

    For impulse-based response, call `resolve_contacts_impulse` instead (below).

    Parameters
    ----------
    bodies       : current list of RigidBody objects
    contacts     : list of Contact descriptors from collision detection
    dt           : current time step (for velocity estimation)
    k            : contact stiffness (N/m^n)
    c            : contact damping coefficient
    mu           : Coulomb friction coefficient
    restitution  : (unused in penalty mode; kept for API symmetry)
    hertz_n      : Hunt-Crossley exponent (1.5 = Hertz)
    impulse_threshold : unused here; see resolve_contacts_impulse

    Returns
    -------
    forces  : list of Vec3, one per body — contact force contributions (N)
    torques : list of Vec3, one per body — contact torque contributions (N·m)
    """
    n_bodies = len(bodies)
    forces: List[Vec3] = [(0.0, 0.0, 0.0)] * n_bodies
    torques: List[Vec3] = [(0.0, 0.0, 0.0)] * n_bodies

    for contact in contacts:
        idx_a = contact.body_a_idx
        idx_b = contact.body_b_idx
        n = contact.normal          # unit normal from b toward a
        pen = contact.penetration_depth
        cp = contact.contact_point

        # ------- relative velocity at contact point -------
        if 0 <= idx_a < n_bodies:
            ba = bodies[idx_a]
            r_a = vec3_sub(cp, ba.position)
            v_a = vec3_add(ba.velocity, vec3_cross(ba.angular_velocity, r_a))
        else:
            v_a = (0.0, 0.0, 0.0)
            r_a = (0.0, 0.0, 0.0)

        if 0 <= idx_b < n_bodies:
            bb = bodies[idx_b]
            r_b = vec3_sub(cp, bb.position)
            v_b = vec3_add(bb.velocity, vec3_cross(bb.angular_velocity, r_b))
        else:
            v_b = (0.0, 0.0, 0.0)
            r_b = (0.0, 0.0, 0.0)

        v_rel = vec3_sub(v_a, v_b)
        v_n = vec3_dot(v_rel, n)       # normal component (+ = separating)
        v_t = _vec3_reject_from(v_rel, n)  # tangential component

        # ------- Hunt-Crossley normal force -------
        F_n_mag = hunt_crossley_normal_force(pen, -v_n, k, c, hertz_n)
        F_n_vec = vec3_scale(n, F_n_mag)

        # ------- Coulomb friction -------
        F_t_vec = coulomb_friction_force(F_n_mag, v_t, mu)

        # Total contact force
        F_contact = vec3_add(F_n_vec, F_t_vec)

        # Apply equal and opposite forces to each body
        if 0 <= idx_a < n_bodies:
            forces[idx_a] = vec3_add(forces[idx_a], F_contact)
            torque_a = vec3_cross(r_a, F_contact)
            torques[idx_a] = vec3_add(torques[idx_a], torque_a)

        if 0 <= idx_b < n_bodies:
            F_neg = vec3_scale(F_contact, -1.0)
            forces[idx_b] = vec3_add(forces[idx_b], F_neg)
            torque_b = vec3_cross(r_b, F_neg)
            torques[idx_b] = vec3_add(torques[idx_b], torque_b)

    return forces, torques


def resolve_contacts_impulse(
    bodies: List[RigidBody],
    contacts: List[Contact],
    restitution: float = 0.6,
    mu: float = 0.4,
) -> List[RigidBody]:
    """
    Apply instantaneous impulse-based collision response.

    Modifies body velocities/angular velocities for all contacts where
    v_rel · n < 0 (bodies approaching).

    Parameters
    ----------
    bodies      : list of RigidBody objects
    contacts    : list of Contact descriptors
    restitution : e — coefficient of restitution (0=inelastic, 1=elastic)
    mu          : Coulomb friction coefficient

    Returns
    -------
    Updated list of RigidBody objects (non-mutating).
    """
    bodies = list(bodies)  # shallow copy so we can replace elements

    for contact in contacts:
        idx_a = contact.body_a_idx
        idx_b = contact.body_b_idx
        n = contact.normal
        cp = contact.contact_point

        ba = bodies[idx_a] if 0 <= idx_a < len(bodies) else None
        bb = bodies[idx_b] if 0 <= idx_b < len(bodies) else None

        if ba is None:
            continue   # can't apply impulse to static world as body_a

        J_mag = compute_restitution_impulse(ba, bb, contact, restitution)
        if J_mag <= 0.0:
            continue

        J_vec = vec3_scale(n, J_mag)

        # Apply to body_a (along +n)
        bodies[idx_a] = apply_impulse(ba, J_vec, cp, sign=1.0)
        ba = bodies[idx_a]  # updated reference

        # Apply to body_b (along -n)  — only if dynamic
        if bb is not None and 0 <= idx_b < len(bodies):
            bodies[idx_b] = apply_impulse(bb, J_vec, cp, sign=-1.0)

        # Friction impulse (tangential)
        if mu > 0.0 and bb is not None:
            r_a = vec3_sub(cp, ba.position)
            v_a2 = vec3_add(ba.velocity, vec3_cross(ba.angular_velocity, r_a))
            bb2 = bodies[idx_b]
            r_b = vec3_sub(cp, bb2.position)
            v_b2 = vec3_add(bb2.velocity, vec3_cross(bb2.angular_velocity, r_b))
            v_rel2 = vec3_sub(v_a2, v_b2)
            v_t2 = _vec3_reject_from(v_rel2, n)
            vt_mag = vec3_norm(v_t2)
            if vt_mag > 1e-9:
                J_t_mag = min(mu * J_mag, vt_mag / (1.0 / ba.mass + 1.0 / bb2.mass))
                J_t_dir = _vec3_normalize(v_t2)
                J_t_vec = vec3_scale(J_t_dir, -J_t_mag)
                bodies[idx_a] = apply_impulse(bodies[idx_a], J_t_vec, cp, sign=1.0)
                bodies[idx_b] = apply_impulse(bodies[idx_b], J_t_vec, cp, sign=-1.0)
        elif mu > 0.0 and bb is None:
            # body_b is static world — only apply friction to body_a
            ba2 = bodies[idx_a]
            r_a = vec3_sub(cp, ba2.position)
            v_a3 = vec3_add(ba2.velocity, vec3_cross(ba2.angular_velocity, r_a))
            v_t3 = _vec3_reject_from(v_a3, n)
            vt_mag = vec3_norm(v_t3)
            if vt_mag > 1e-9:
                J_t_mag = min(mu * J_mag, vt_mag * ba2.mass)
                J_t_dir = _vec3_normalize(v_t3)
                J_t_vec = vec3_scale(J_t_dir, -J_t_mag)
                bodies[idx_a] = apply_impulse(bodies[idx_a], J_t_vec, cp, sign=1.0)

    return bodies


# ---------------------------------------------------------------------------
# 6. High-level simulation helpers
# ---------------------------------------------------------------------------

def simulate_with_contacts(
    bodies: List[RigidBody],
    static_planes: List[Tuple[Vec3, Vec3]],  # (normal, point)
    sphere_radii: List[float],
    gravity_g: float = 9.80665,
    gravity_axis: int = 1,
    dt: float = 1e-3,
    n_steps: int = 1000,
    restitution: float = 0.6,
    k: float = 1e6,
    c: float = 1e3,
    mu: float = 0.4,
    hertz_n: float = 1.5,
    *,
    use_impulse: bool = True,
    record_every: int = 1,
) -> dict:
    """
    Simple fixed-step simulation with sphere-plane (and sphere-sphere) contact.

    Uses impulse-based response by default (use_impulse=True).
    Set use_impulse=False to use penalty forces instead.

    Parameters
    ----------
    bodies        : rigid bodies; each treated as a sphere with sphere_radii[i]
    static_planes : list of (normal, point) for infinite static planes
    sphere_radii  : one radius per body (m)
    gravity_g     : gravitational acceleration (m/s²)
    gravity_axis  : 0=X, 1=Y, 2=Z
    dt            : time step (s)
    n_steps       : number of steps
    restitution   : coefficient of restitution
    k, c          : penalty contact stiffness/damping (used if use_impulse=False)
    mu            : friction coefficient
    hertz_n       : Hunt-Crossley exponent
    use_impulse   : True = impulse response; False = penalty forces
    record_every  : record snapshot every N steps

    Returns
    -------
    dict with 'ok', 't', 'trajectories', 'final_bodies'
    """
    from kerf_motion.body import quat_normalize
    from dataclasses import replace

    if not bodies:
        return {"ok": False, "reason": "no bodies"}
    if dt <= 0:
        return {"ok": False, "reason": "dt must be positive"}

    n_bodies = len(bodies)
    if len(sphere_radii) != n_bodies:
        return {"ok": False, "reason": "sphere_radii length must match bodies"}

    # gravity vector
    gvec = [0.0, 0.0, 0.0]
    gvec[gravity_axis] = -gravity_g

    trajectories: List[List[dict]] = [[] for _ in range(n_bodies)]
    times: List[float] = []

    current = list(bodies)

    def _snap(b: RigidBody, t: float) -> dict:
        return {
            "t": t,
            "position": list(b.position),
            "velocity": list(b.velocity),
        }

    times.append(0.0)
    for i, b in enumerate(current):
        trajectories[i].append(_snap(b, 0.0))

    for step in range(n_steps):
        t_curr = step * dt

        # --- detect contacts ---
        contacts: List[Contact] = []

        for i, b in enumerate(current):
            # sphere-plane
            for plane_n, plane_pt in static_planes:
                c_obj = detect_sphere_plane(
                    b.position, sphere_radii[i],
                    plane_n, plane_pt,
                    body_a_idx=i, body_b_idx=-1,
                )
                if c_obj is not None:
                    contacts.append(c_obj)

            # sphere-sphere (upper triangle only)
            for j in range(i + 1, n_bodies):
                c_ss = detect_sphere_sphere(
                    b.position, sphere_radii[i],
                    current[j].position, sphere_radii[j],
                    body_a_idx=i, body_b_idx=j,
                )
                if c_ss is not None:
                    contacts.append(c_ss)

        if use_impulse:
            # Apply impulses first (velocity correction)
            current = resolve_contacts_impulse(current, contacts,
                                               restitution=restitution, mu=mu)

        # --- integrate one RK4 step (manual, no shared integrator import to avoid coupling) ---
        # Build per-body derivatives function
        def _derivs_all(state_flat: List[float], _t: float) -> List[float]:
            _bodies_local = []
            for _i in range(n_bodies):
                s = state_flat[_i * 13: (_i + 1) * 13]
                from kerf_motion.body import RigidBody as _RB
                _bodies_local.append(_RB.from_state(current[_i], s))

            derivs_out: List[float] = []
            for _i, _b in enumerate(_bodies_local):
                # Gravity
                fx, fy, fz = (
                    _b.mass * gvec[0],
                    _b.mass * gvec[1],
                    _b.mass * gvec[2],
                )
                net_f: Vec3 = (fx, fy, fz)
                net_tau: Vec3 = (0.0, 0.0, 0.0)

                # Add penalty contact forces if not using impulse
                if not use_impulse:
                    pen_f, pen_tau = apply_contacts(
                        _bodies_local, contacts, dt,
                        k=k, c=c, mu=mu, hertz_n=hertz_n,
                    )
                    net_f = vec3_add(net_f, pen_f[_i])
                    net_tau = vec3_add(net_tau, pen_tau[_i])

                d = _b.state_derivatives(net_f, net_tau)
                derivs_out.extend(d)
            return derivs_out

        # Pack state
        state: List[float] = []
        for b in current:
            state.extend(b.to_state())

        # RK4
        from kerf_motion.integrator import rk4_step
        state = rk4_step(state, _derivs_all, dt)

        # Renormalise quaternions
        for _i in range(n_bodies):
            base = _i * 13 + 6
            q = (state[base], state[base + 1], state[base + 2], state[base + 3])
            qn = quat_normalize(q)
            state[base], state[base + 1], state[base + 2], state[base + 3] = qn

        # Unpack
        new_bodies: List[RigidBody] = []
        for _i, _b in enumerate(current):
            s = state[_i * 13: (_i + 1) * 13]
            new_bodies.append(RigidBody.from_state(_b, s))
        current = new_bodies

        t_new = (step + 1) * dt
        if (step + 1) % record_every == 0:
            times.append(t_new)
            for i, b in enumerate(current):
                trajectories[i].append(_snap(b, t_new))

    return {
        "ok": True,
        "t": times,
        "trajectories": trajectories,
        "final_bodies": current,
        "n_steps": n_steps,
        "dt": dt,
    }


# ---------------------------------------------------------------------------
# 7. LLM Tool specifications
# ---------------------------------------------------------------------------

# ---- motion_contact_sphere_plane ----

motion_contact_sphere_plane_spec = ToolSpec(
    name="motion_contact_sphere_plane",
    description=(
        "Detect and compute contact between a sphere and an infinite plane. "
        "Returns contact normal, penetration depth, and contact point. "
        "Optionally computes Hertzian contact stiffness."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sphere_center": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "World-frame sphere centre [x, y, z] (m).",
            },
            "sphere_radius": {"type": "number", "description": "Sphere radius (m)."},
            "plane_normal": {
                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                "description": "Plane outward unit normal [nx, ny, nz].",
            },
            "plane_point": {
                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                "description": "Any point on the plane [x, y, z] (m).",
            },
            "E1": {"type": "number", "description": "Young's modulus of sphere (Pa). Optional for Hertz."},
            "nu1": {"type": "number", "description": "Poisson ratio of sphere. Optional for Hertz."},
            "E2": {"type": "number", "description": "Young's modulus of plane (Pa). Optional for Hertz."},
            "nu2": {"type": "number", "description": "Poisson ratio of plane. Optional for Hertz."},
        },
        "required": ["sphere_center", "sphere_radius", "plane_normal", "plane_point"],
    },
)


async def run_motion_contact_sphere_plane(params: dict, ctx: ProjectCtx) -> str:
    try:
        sc = tuple(float(v) for v in params["sphere_center"])
        sr = float(params["sphere_radius"])
        pn = tuple(float(v) for v in params["plane_normal"])
        pp = tuple(float(v) for v in params["plane_point"])

        contact = detect_sphere_plane(sc, sr, pn, pp)  # type: ignore[arg-type]
        if contact is None:
            return ok_payload({"contact": False})

        result: dict = {
            "contact": True,
            "normal": list(contact.normal),
            "penetration_depth": contact.penetration_depth,
            "contact_point": list(contact.contact_point),
        }

        # Optional Hertz stiffness
        if all(k in params for k in ("E1", "nu1", "E2", "nu2")):
            k_hertz = hertz_stiffness_sphere_plane(
                float(params["E1"]), float(params["nu1"]),
                float(params["E2"]), float(params["nu2"]),
                sr,
            )
            result["hertz_k"] = k_hertz

        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "CONTACT_ERROR")


# ---- motion_contact_sphere_sphere ----

motion_contact_sphere_sphere_spec = ToolSpec(
    name="motion_contact_sphere_sphere",
    description=(
        "Detect contact between two spheres and compute penetration geometry. "
        "Optionally returns Hertzian stiffness for the sphere-sphere pair."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "center_a": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            "radius_a": {"type": "number"},
            "center_b": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            "radius_b": {"type": "number"},
            "E1": {"type": "number"}, "nu1": {"type": "number"},
            "E2": {"type": "number"}, "nu2": {"type": "number"},
        },
        "required": ["center_a", "radius_a", "center_b", "radius_b"],
    },
)


async def run_motion_contact_sphere_sphere(params: dict, ctx: ProjectCtx) -> str:
    try:
        ca = tuple(float(v) for v in params["center_a"])
        ra = float(params["radius_a"])
        cb = tuple(float(v) for v in params["center_b"])
        rb = float(params["radius_b"])

        contact = detect_sphere_sphere(ca, ra, cb, rb)  # type: ignore[arg-type]
        if contact is None:
            return ok_payload({"contact": False})

        result: dict = {
            "contact": True,
            "normal": list(contact.normal),
            "penetration_depth": contact.penetration_depth,
            "contact_point": list(contact.contact_point),
        }

        if all(k in params for k in ("E1", "nu1", "E2", "nu2")):
            k_hertz = hertz_stiffness_sphere_sphere(
                float(params["E1"]), float(params["nu1"]), ra,
                float(params["E2"]), float(params["nu2"]), rb,
            )
            result["hertz_k"] = k_hertz

        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "CONTACT_ERROR")


# ---- motion_collision_check ----

motion_collision_check_spec = ToolSpec(
    name="motion_collision_check",
    description=(
        "Perform a comprehensive collision check for a set of spherical rigid bodies "
        "against static planes and each other. Returns all active contacts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bodies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                        "radius": {"type": "number"},
                    },
                    "required": ["position", "radius"],
                },
            },
            "planes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "normal": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                        "point": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    },
                    "required": ["normal", "point"],
                },
            },
        },
        "required": ["bodies"],
    },
)


async def run_motion_collision_check(params: dict, ctx: ProjectCtx) -> str:
    try:
        bodies_raw = params["bodies"]
        planes_raw = params.get("planes", [])

        all_contacts = []

        for i, bd in enumerate(bodies_raw):
            center = tuple(float(v) for v in bd["position"])
            radius = float(bd["radius"])

            # sphere-plane
            for plane in planes_raw:
                pn = tuple(float(v) for v in plane["normal"])
                pp = tuple(float(v) for v in plane["point"])
                c_obj = detect_sphere_plane(center, radius, pn, pp,  # type: ignore[arg-type]
                                            body_a_idx=i, body_b_idx=-1)
                if c_obj is not None:
                    all_contacts.append({
                        "type": "sphere_plane",
                        "body_a": i,
                        "normal": list(c_obj.normal),
                        "penetration_depth": c_obj.penetration_depth,
                        "contact_point": list(c_obj.contact_point),
                    })

            # sphere-sphere (upper triangle)
            for j in range(i + 1, len(bodies_raw)):
                center_j = tuple(float(v) for v in bodies_raw[j]["position"])
                radius_j = float(bodies_raw[j]["radius"])
                c_ss = detect_sphere_sphere(center, radius, center_j, radius_j,  # type: ignore[arg-type]
                                            body_a_idx=i, body_b_idx=j)
                if c_ss is not None:
                    all_contacts.append({
                        "type": "sphere_sphere",
                        "body_a": i,
                        "body_b": j,
                        "normal": list(c_ss.normal),
                        "penetration_depth": c_ss.penetration_depth,
                        "contact_point": list(c_ss.contact_point),
                    })

        return ok_payload({
            "ok": True,
            "n_contacts": len(all_contacts),
            "contacts": all_contacts,
        })
    except Exception as exc:
        return err_payload(str(exc), "COLLISION_CHECK_ERROR")
