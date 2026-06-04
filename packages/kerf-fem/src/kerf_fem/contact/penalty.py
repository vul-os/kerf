"""
Penalty-method contact formulation for FEM.

Implements a node-to-surface contact algorithm using the penalty method.
The penetration (negative gap) between slave nodes and the master surface
is penalised to enforce the non-penetration constraint approximately.

Theory
------
For a slave node with gap function g (negative = penetration):

    F_n = { -k · g    if g < 0   (contact active)
           { 0         otherwise  (no contact)

Friction is handled via the Coulomb friction model:
    |F_t| ≤ μ · |F_n|

The penalty method introduces a small compliance into the contact
constraint. For stiff contact without compliance use
``augmented_lagrangian.py``.

References
----------
  Wriggers, P. (2006). "Computational Contact Mechanics." 2nd ed., Springer.
      Chapter 3 (penalty formulation), Chapter 5 (friction).
  Laursen, T. A. (2002). "Computational Contact and Impact Mechanics."
      Springer. Chapter 2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

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


def _nearest_point_on_segment(
    p: np.ndarray, a: np.ndarray, b: np.ndarray
) -> tuple[np.ndarray, float]:
    """Project point p onto line segment [a, b].

    Returns (closest_point, signed_gap) where gap is positive outside the
    segment (to the left in 2D) and negative if the point is inside the
    surface (notional penetration direction).

    This is a simplified 2D implementation. For production 3D contact
    a full surface parameterisation is required.
    """
    ab = b - a
    ap = p - a
    t = np.dot(ap, ab) / (np.dot(ab, ab) + 1e-300)
    t = float(np.clip(t, 0.0, 1.0))
    closest = a + t * ab
    diff = p - closest
    dist = float(np.linalg.norm(diff))
    # Normal direction: perpendicular to ab, pointing outward (away from surface)
    # For a 2D segment [a, b], outward normal is the left-normal of the
    # direction from a→b (CCW convention).
    ab_len = float(np.linalg.norm(ab)) + 1e-300
    normal = np.array([-ab[1], ab[0]]) / ab_len
    gap = float(np.dot(diff, normal))  # positive = outside master surface
    return closest, gap


def compute_contact_force_penalty(
    slave_positions: np.ndarray,
    master_surface_points: np.ndarray,
    contact_stiffness_n_per_m: float,
    friction_coefficient: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute penalty contact forces for each slave node.

    For each slave node the closest point on the (piecewise-linear)
    master surface is found. If the gap g < 0 (penetration), a normal
    penalty force is applied. Friction is handled using the Coulomb
    criterion (regularised stick-slip).

    Parameters
    ----------
    slave_positions : np.ndarray, shape (n_slave, 2)
        Current Cartesian positions of the slave nodes [m].
    master_surface_points : np.ndarray, shape (n_master, 2)
        Current Cartesian positions of the master surface points [m].
        Consecutive pairs define segments of the master surface.
    contact_stiffness_n_per_m : float
        Penalty stiffness k [N/m]. Larger values give less penetration
        but may cause ill-conditioning. Typical: E · Δx where Δx is the
        characteristic element length.
    friction_coefficient : float, optional
        Coulomb friction coefficient μ (default 0.0 = frictionless).

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

    Reference: Wriggers (2006), §3.2.
    """
    slave_positions = np.asarray(slave_positions, dtype=float)
    master_surface_points = np.asarray(master_surface_points, dtype=float)

    n_slave = slave_positions.shape[0]
    n_master = master_surface_points.shape[0]

    normal_forces = np.zeros((n_slave, 2))
    tangential_forces = np.zeros((n_slave, 2))

    if n_master < 2:
        return normal_forces, tangential_forces

    k = float(contact_stiffness_n_per_m)
    mu = float(friction_coefficient)

    for i in range(n_slave):
        p = slave_positions[i]

        # Find closest segment and gap
        best_gap = math.inf
        best_closest = None
        best_normal = None

        for j in range(n_master - 1):
            a = master_surface_points[j]
            b = master_surface_points[j + 1]
            ab = b - a
            ab_len = float(np.linalg.norm(ab)) + 1e-300
            # Outward normal (left-normal for CCW surface)
            normal = np.array([-ab[1], ab[0]]) / ab_len

            closest, gap = _nearest_point_on_segment(p, a, b)
            if abs(gap) < abs(best_gap):
                best_gap = gap
                best_closest = closest
                best_normal = normal

        if best_gap is None or best_gap >= 0.0:
            continue  # No penetration

        # Normal penalty force: F_n = -k * g * n  (opposes penetration)
        # g < 0 here so -k*g > 0 pushes slave node outward
        fn_magnitude = -k * best_gap  # positive value
        fn_vec = fn_magnitude * best_normal
        normal_forces[i] = fn_vec

        # Coulomb friction: tangential force bounded by μ|F_n|
        if mu > 0.0 and best_closest is not None:
            # Tangential direction (perpendicular to normal, in 2D)
            tang = np.array([best_normal[1], -best_normal[0]])
            # For static / stick condition, apply full tangential resistance
            # (simplified: we apply max friction in the direction opposing slip)
            # In a full FEM implementation this would use displacement increments
            ft_max = mu * fn_magnitude
            tangential_forces[i] = ft_max * tang

    return normal_forces, tangential_forces


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
            _, gap = _nearest_point_on_segment(
                p, master_surface_points[j], master_surface_points[j + 1]
            )
            if abs(gap) < abs(best_gap):
                best_gap = gap
        gaps[i] = best_gap

    return gaps
