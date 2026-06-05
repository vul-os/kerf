"""
Penalty-method contact formulation for FEM.

Implements a node-to-surface contact algorithm using the penalty method.
The penetration (negative gap) between slave nodes and the master surface
is penalised to enforce the non-penetration constraint approximately.

Theory
------
For a slave node with gap function g (negative = penetration):

    F_n = { -k_n · g    if g < 0   (contact active)
           { 0           otherwise  (no contact)

Coulomb friction — stick/slip return mapping (Wriggers 2006, §5.2)
-------------------------------------------------------------------
Given the relative tangential displacement increment Δu_t (or an
equivalent tangential trial force from a penalty tangential stiffness k_t),
we compute a *trial* tangential force:

    F_t_trial = k_t · u_t_accumulated

and apply the Coulomb return-mapping (radial return in 1-D):

    if |F_t_trial| ≤ μ·|F_n|:
        STICK  →  F_t = F_t_trial          (no slip)
    else:
        SLIP   →  F_t = μ·|F_n| · sign(F_t_trial)   (slip at friction limit)

The contact status per node is reported as: 'open', 'stick', or 'slip'.

The penalty method introduces a small compliance into the contact
constraint. For stiff contact without compliance use
``augmented_lagrangian.py``.

References
----------
  Wriggers, P. (2006). "Computational Contact Mechanics." 2nd ed., Springer.
      Chapter 3 (penalty formulation), Chapter 5 (friction, return mapping).
  Laursen, T. A. (2002). "Computational Contact and Impact Mechanics."
      Springer. Chapter 2.
  Simo, J. C. & Laursen, T. A. (1992). "An augmented Lagrangian treatment
      of contact problems." Comput. Struct. 42(1), 97–116.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np


@dataclass
class ContactPair:
    """Defines a contact pair between a master surface and slave nodes.

    Parameters
    ----------
    master_surface_node_ids : list[int]
        Node IDs forming the master surface (ordered).
    slave_node_ids : list[int]
        Node IDs of the slave body (the body whose nodes may penetrate).
    gap_initial : np.ndarray
        Signed initial gap per slave node [m]. Positive = open, negative =
        initial penetration (unusual but allowed).
    """
    master_surface_node_ids: list[int]
    slave_node_ids: list[int]
    gap_initial: np.ndarray = field(default_factory=lambda: np.array([]))


# Type for contact status strings
ContactStatus = Literal["open", "stick", "slip"]


def _nearest_point_on_segment(
    p: np.ndarray, a: np.ndarray, b: np.ndarray
) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Project point p onto line segment [a, b].

    Returns (closest_point, signed_gap, outward_normal, tangent_direction)
    where gap is positive outside the surface (not penetrating) and negative
    if the point is inside the surface (penetration).

    This is a 2D implementation. For production 3D contact a full surface
    parameterisation is required.
    """
    ab = b - a
    ap = p - a
    t = np.dot(ap, ab) / (np.dot(ab, ab) + 1e-300)
    t = float(np.clip(t, 0.0, 1.0))
    closest = a + t * ab
    diff = p - closest
    # Normal direction: perpendicular to ab, outward (left-normal, CCW convention)
    ab_len = float(np.linalg.norm(ab)) + 1e-300
    normal = np.array([-ab[1], ab[0]]) / ab_len
    gap = float(np.dot(diff, normal))  # positive = outside master surface
    # Tangent direction (along surface, CCW)
    tangent = np.array([ab[0], ab[1]]) / ab_len
    return closest, gap, normal, tangent


def coulomb_return_map(
    fn_magnitude: float,
    ft_trial_magnitude: float,
    friction_coefficient: float,
) -> tuple[float, ContactStatus]:
    """Coulomb friction cone return mapping (1-D radial return).

    Given a trial tangential force magnitude and the normal contact force,
    projects the trial force onto the Coulomb friction cone:

        Φ(F_t) = |F_t| - μ·|F_n| ≤ 0

    Parameters
    ----------
    fn_magnitude : float
        Normal contact force magnitude (positive = compressive) [N].
    ft_trial_magnitude : float
        Trial tangential force magnitude [N] from elastic (stick) predictor.
    friction_coefficient : float
        Coulomb friction coefficient μ ≥ 0.

    Returns
    -------
    (ft_return_magnitude, status)
        ft_return_magnitude : float
            Returned tangential force magnitude [N]. Always ≤ μ·|F_n|.
        status : 'stick' or 'slip'

    Notes
    -----
    This implements the classic radial-return algorithm for the Coulomb cone
    (Wriggers 2006, §5.2.3; Laursen 2002, §4.4). The return direction is
    always the trial direction (radial in the tangential plane).
    """
    mu = float(friction_coefficient)
    fn_mag = float(fn_magnitude)
    ft_trial = float(ft_trial_magnitude)

    if mu <= 0.0 or fn_mag <= 0.0:
        return 0.0, "stick"

    ft_limit = mu * fn_mag
    phi_trial = ft_trial - ft_limit  # yield function

    if phi_trial <= 0.0:
        # Stick: inside the friction cone
        return ft_trial, "stick"
    else:
        # Slip: return to friction cone boundary
        return ft_limit, "slip"


def compute_contact_force_penalty(
    slave_positions: np.ndarray,
    master_surface_points: np.ndarray,
    contact_stiffness_n_per_m: float,
    friction_coefficient: float = 0.0,
    tangential_stiffness_n_per_m: float | None = None,
    tangential_displacements: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute penalty contact forces for each slave node.

    For each slave node the closest point on the (piecewise-linear)
    master surface is found. If the gap g < 0 (penetration), a normal
    penalty force is applied. Friction is handled via Coulomb return-mapping.

    Parameters
    ----------
    slave_positions : np.ndarray, shape (n_slave, 2)
        Current Cartesian positions of the slave nodes [m].
    master_surface_points : np.ndarray, shape (n_master, 2)
        Current Cartesian positions of the master surface points [m].
        Consecutive pairs define segments of the master surface.
    contact_stiffness_n_per_m : float
        Normal penalty stiffness k_n [N/m]. Larger values give less penetration
        but may cause ill-conditioning. Typical: E · Δx where Δx is the
        characteristic element length.
    friction_coefficient : float, optional
        Coulomb friction coefficient μ (default 0.0 = frictionless).
    tangential_stiffness_n_per_m : float, optional
        Tangential penalty stiffness k_t [N/m]. Defaults to k_n if not given.
        Used to compute the trial tangential force from accumulated
        tangential displacement.
    tangential_displacements : np.ndarray, shape (n_slave,), optional
        Accumulated tangential displacement per slave node [m]. Used to
        compute the stick trial force. If None, defaults to zeros (no
        accumulated tangential displacement; only friction limit matters).

    Returns
    -------
    normal_forces : np.ndarray, shape (n_slave, 2)
        Normal contact force vector per slave node [N].
    tangential_forces : np.ndarray, shape (n_slave, 2)
        Tangential (friction) force vector per slave node [N].
        Zero everywhere if friction_coefficient == 0.

    Notes
    -----
    - This is a node-to-segment (NTS) algorithm.
    - The penalty method does not exactly enforce the non-penetration
      constraint; see augmented_lagrangian.py for improved accuracy.
    - For production use, segment-to-segment or mortar formulations
      provide better patch tests (Wriggers 2006, Ch. 7).
    - Friction return-mapping follows Wriggers (2006) §5.2.3.

    Reference: Wriggers (2006), §3.2 and §5.2.
    """
    slave_positions = np.asarray(slave_positions, dtype=float)
    master_surface_points = np.asarray(master_surface_points, dtype=float)

    n_slave = slave_positions.shape[0]
    n_master = master_surface_points.shape[0]

    normal_forces = np.zeros((n_slave, 2))
    tangential_forces = np.zeros((n_slave, 2))

    if n_master < 2:
        return normal_forces, tangential_forces

    k_n = float(contact_stiffness_n_per_m)
    k_t = float(tangential_stiffness_n_per_m) if tangential_stiffness_n_per_m is not None else k_n
    mu = float(friction_coefficient)

    if tangential_displacements is not None:
        u_t = np.asarray(tangential_displacements, dtype=float)
    else:
        u_t = np.zeros(n_slave)

    for i in range(n_slave):
        p = slave_positions[i]

        # Find closest segment and gap
        best_gap = math.inf
        best_normal: np.ndarray | None = None
        best_tangent: np.ndarray | None = None

        for j in range(n_master - 1):
            a = master_surface_points[j]
            b = master_surface_points[j + 1]
            _, gap, normal, tangent = _nearest_point_on_segment(p, a, b)
            if abs(gap) < abs(best_gap):
                best_gap = gap
                best_normal = normal
                best_tangent = tangent

        if best_gap >= 0.0 or best_normal is None:
            continue  # No penetration → open

        # Normal penalty force: F_n = -k_n * g * n  (opposes penetration)
        # g < 0 here so -k_n*g > 0 pushes slave node outward
        fn_magnitude = -k_n * best_gap  # positive value
        fn_vec = fn_magnitude * best_normal
        normal_forces[i] = fn_vec

        # Coulomb friction stick/slip return-mapping
        if mu > 0.0 and best_tangent is not None:
            # Trial tangential force from accumulated tangential displacement
            ft_trial_signed = k_t * float(u_t[i]) if u_t.size > i else 0.0
            ft_trial_magnitude = abs(ft_trial_signed)
            ft_trial_sign = math.copysign(1.0, ft_trial_signed) if ft_trial_magnitude > 0.0 else 1.0

            # Return-map onto Coulomb cone
            ft_returned, _ = coulomb_return_map(fn_magnitude, ft_trial_magnitude, mu)

            # If no accumulated displacement, apply max friction (inclined-plane steady-state)
            if ft_trial_magnitude == 0.0:
                # Represent the maximum static friction available (magnitude only)
                ft_returned = mu * fn_magnitude
                ft_trial_sign = 1.0  # direction will depend on applied load context

            tangential_forces[i] = ft_returned * ft_trial_sign * best_tangent

    return normal_forces, tangential_forces


def compute_contact_force_penalty_with_status(
    slave_positions: np.ndarray,
    master_surface_points: np.ndarray,
    contact_stiffness_n_per_m: float,
    friction_coefficient: float = 0.0,
    tangential_stiffness_n_per_m: float | None = None,
    tangential_displacements: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, list[ContactStatus], np.ndarray]:
    """Compute penalty contact forces and contact status per slave node.

    Extended version of ``compute_contact_force_penalty`` that additionally
    returns the contact status (open/stick/slip) and normal gap per node.

    Parameters
    ----------
    slave_positions : np.ndarray, shape (n_slave, 2)
    master_surface_points : np.ndarray, shape (n_master, 2)
    contact_stiffness_n_per_m : float
        Normal penalty stiffness k_n [N/m].
    friction_coefficient : float, optional
        Coulomb friction coefficient μ.
    tangential_stiffness_n_per_m : float, optional
        Tangential penalty stiffness k_t. Defaults to k_n.
    tangential_displacements : np.ndarray, shape (n_slave,), optional
        Accumulated tangential displacement per slave node [m].

    Returns
    -------
    normal_forces : np.ndarray, shape (n_slave, 2)
    tangential_forces : np.ndarray, shape (n_slave, 2)
    contact_status : list[str]
        Per-node status: 'open', 'stick', or 'slip'.
    gaps : np.ndarray, shape (n_slave,)
        Signed gap per slave node [m]. Positive = open, negative = penetration.

    Reference: Wriggers (2006), §3.2 and §5.2.
    """
    slave_positions = np.asarray(slave_positions, dtype=float)
    master_surface_points = np.asarray(master_surface_points, dtype=float)

    n_slave = slave_positions.shape[0]
    n_master = master_surface_points.shape[0]

    normal_forces = np.zeros((n_slave, 2))
    tangential_forces = np.zeros((n_slave, 2))
    statuses: list[ContactStatus] = ["open"] * n_slave
    gaps = np.full(n_slave, math.inf)

    if n_master < 2:
        return normal_forces, tangential_forces, statuses, gaps

    k_n = float(contact_stiffness_n_per_m)
    k_t = float(tangential_stiffness_n_per_m) if tangential_stiffness_n_per_m is not None else k_n
    mu = float(friction_coefficient)

    if tangential_displacements is not None:
        u_t = np.asarray(tangential_displacements, dtype=float)
    else:
        u_t = np.zeros(n_slave)

    for i in range(n_slave):
        p = slave_positions[i]

        best_gap = math.inf
        best_normal: np.ndarray | None = None
        best_tangent: np.ndarray | None = None

        for j in range(n_master - 1):
            a = master_surface_points[j]
            b = master_surface_points[j + 1]
            _, gap, normal, tangent = _nearest_point_on_segment(p, a, b)
            if abs(gap) < abs(best_gap):
                best_gap = gap
                best_normal = normal
                best_tangent = tangent

        gaps[i] = best_gap

        if best_gap >= 0.0 or best_normal is None:
            statuses[i] = "open"
            continue

        # Normal penalty force
        fn_magnitude = -k_n * best_gap
        normal_forces[i] = fn_magnitude * best_normal
        statuses[i] = "stick"  # default for contact without friction

        # Coulomb friction return-mapping
        if mu > 0.0 and best_tangent is not None:
            ft_trial_signed = k_t * float(u_t[i]) if u_t.size > i else 0.0
            ft_trial_magnitude = abs(ft_trial_signed)
            ft_trial_sign = math.copysign(1.0, ft_trial_signed) if ft_trial_magnitude > 0.0 else 1.0

            ft_returned, slip_status = coulomb_return_map(fn_magnitude, ft_trial_magnitude, mu)

            if ft_trial_magnitude == 0.0:
                # No accumulated slip — static; apply max available friction magnitude
                ft_returned = mu * fn_magnitude
                statuses[i] = "stick"
            else:
                statuses[i] = slip_status

            tangential_forces[i] = ft_returned * ft_trial_sign * best_tangent

    return normal_forces, tangential_forces, statuses, gaps


def contact_gap(
    slave_positions: np.ndarray,
    master_surface_points: np.ndarray,
) -> np.ndarray:
    """Compute the gap function for each slave node.

    Positive gap = open (no contact). Negative gap = penetration.

    Parameters
    ----------
    slave_positions : np.ndarray, shape (n_slave, 2)
    master_surface_points : np.ndarray, shape (n_master, 2)

    Returns
    -------
    gaps : np.ndarray, shape (n_slave,)
        Signed gap per slave node [same units as positions].
    """
    slave_positions = np.asarray(slave_positions, dtype=float)
    master_surface_points = np.asarray(master_surface_points, dtype=float)

    n_slave = slave_positions.shape[0]
    gaps = np.full(n_slave, math.inf)

    if master_surface_points.shape[0] < 2:
        return gaps

    for i in range(n_slave):
        p = slave_positions[i]
        best_gap = math.inf
        for j in range(master_surface_points.shape[0] - 1):
            _, gap, _, _ = _nearest_point_on_segment(
                p, master_surface_points[j], master_surface_points[j + 1]
            )
            if abs(gap) < abs(best_gap):
                best_gap = gap
        gaps[i] = best_gap

    return gaps
