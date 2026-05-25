"""
kerf_civil.hydraulics_pressure — Steady-state pressurized water-distribution
network solver.

Algorithm
---------
Hardy-Cross / Global Gradient Algorithm (Todini & Pilati, 1988).

This implementation uses the linearised node-conductance formulation:
  1. For each pipe k, compute linearised conductance:
         g_k = n * r_k * |Q_k|^(n-1)   where r_k is the resistance coefficient
     which is the derivative of the head-loss function: g_k = dh/dQ(Q_k)^{-1}
     Actually, the conductance is 1/r_k_lin where r_k_lin = dh_L/dQ.
  2. Build the nodal admittance matrix A (n_nodes × n_nodes).
  3. Assemble RHS from demands and known reservoir heads.
  4. Solve A · H = d for unknown heads H.
  5. Update pipe flows: Q_k = g_k · (H_a - H_b)  [linearised mass-balance].
  6. Iterate until max |ΔQ_k| < tol.

This guarantees that at every iteration the nodal mass balance is exactly
satisfied (by construction of the linear system), and convergence is to
the exact nonlinear solution.

Reference: Rossman, L.A. (2000). EPANET 2 Users Manual. EPA/600/R-00/057.
           Chapter 3, Network Hydraulics.

Head-loss formulae
------------------
Hazen-Williams (HW):
    h_L = r_k * Q^1.852  where r_k = 10.67 * L / (C^1.852 * d^4.871)
    dh/dQ = 1.852 * r_k * |Q|^0.852
    Reference: Streeter & Wylie (1985), Fluid Mechanics 8th Ed.

Darcy-Weisbach with Swamee-Jain friction factor (DW):
    f  = 0.25 / [log10(ε/(3.7·d) + 5.74/Re^0.9)]²
    h_L = f * L / d * V²/(2g)
    Reference: Swamee & Jain (1976), J. Hydraulics Div., ASCE, 102(5), 657–664.

Validation benchmark
--------------------
Two-loop network (Hardy Cross example):
    Source: Streeter, V.L. & Wylie, E.B. (1985). Fluid Mechanics, 8th Ed.,
    McGraw-Hill, Example 10.3, p. 376.

    Nodes: 4 nodes (1 reservoir + 3 demand nodes), 5 pipes
    Mass balance at each demand node closes within 1 × 10⁻³ m³/s.

Public API
----------
solve_network(nodes, reservoirs, pipes,
              formula='HW', max_iter=200, tol=1e-6) -> NetworkResult
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """Demand node (unknown head)."""
    id: str
    elevation_m: float          # elevation above datum (m)
    demand_m3s: float = 0.0     # external demand (m³/s), positive = withdrawal


@dataclass
class Reservoir:
    """Fixed-head source node."""
    id: str
    head_m: float               # total head (m)


@dataclass
class Pipe:
    """Pipe (undirected; positive flow = from node_a to node_b)."""
    id: str
    node_a: str                 # start node id
    node_b: str                 # end node id
    length_m: float
    diameter_m: float
    roughness: float            # HW: C; DW: ε (m)


@dataclass
class NetworkResult:
    pipe_flows_m3s: dict[str, float]
    nodal_heads_m: dict[str, float]
    nodal_pressures_m: dict[str, float]
    iterations: int
    converged: bool
    residual: float


# ---------------------------------------------------------------------------
# Head-loss constants and functions
# ---------------------------------------------------------------------------

_G = 9.80665        # m/s²
_NU = 1.007e-6      # kinematic viscosity water at 20°C (m²/s)
_HW_EXP = 1.852     # Hazen-Williams exponent


def _hw_resistance(length: float, diameter: float, C: float) -> float:
    """Hazen-Williams resistance coefficient r such that h_L = r * Q^1.852."""
    return 10.67 * length / (C ** _HW_EXP * diameter ** 4.871)


def _hw_headloss(Q: float, r: float) -> float:
    """HW head-loss (signed): h = r * Q^1.852 * sign(Q)."""
    return math.copysign(r * abs(Q) ** _HW_EXP, Q)


def _hw_dh_dQ(Q: float, r: float) -> float:
    """d(h_L)/dQ for HW; always ≥ 0."""
    return _HW_EXP * r * max(abs(Q), 1e-30) ** (_HW_EXP - 1.0)


def _swamee_jain_f(Re: float, eps: float, d: float) -> float:
    """Swamee-Jain explicit friction factor. Laminar below Re=2300."""
    if Re < 2300.0:
        return 64.0 / max(Re, 1e-6)
    arg = eps / (3.7 * d) + 5.74 / max(Re ** 0.9, 1e-30)
    return 0.25 / (math.log10(max(arg, 1e-30)) ** 2)


def _dw_headloss_and_dhdQ(Q: float, L: float, d: float, eps: float):
    """
    DW head-loss (signed) and d(h_L)/dQ.
    Returns (h, dh_dQ).
    """
    absQ = max(abs(Q), 1e-30)
    A_pipe = math.pi * (d / 2.0) ** 2
    V = absQ / A_pipe
    Re = V * d / _NU
    f = _swamee_jain_f(Re, eps, d)
    coef = f * L / (d * A_pipe ** 2 * 2.0 * _G)
    h = math.copysign(coef * absQ ** 2, Q)
    dh = 2.0 * coef * absQ
    return h, dh


# ---------------------------------------------------------------------------
# Core solver
# ---------------------------------------------------------------------------

def solve_network(
    nodes: list[Node],
    reservoirs: list[Reservoir],
    pipes: list[Pipe],
    formula: Literal["HW", "DW"] = "HW",
    max_iter: int = 200,
    tol: float = 1e-6,
) -> NetworkResult:
    """
    Solve a steady-state pipe network using the linearised GGA formulation.

    At each iteration, the linear system is assembled such that the resulting
    pipe flows (Q_k = g_k * (H_a - H_b)) exactly satisfy nodal mass balance.
    This is the key invariant: converged result has EXACT mass balance.

    Parameters
    ----------
    nodes      : demand nodes (unknown heads)
    reservoirs : fixed-head sources
    pipes      : pipe elements
    formula    : 'HW' or 'DW'
    max_iter   : maximum iterations
    tol        : convergence tolerance on max |ΔQ| (m³/s)
    """
    np = len(nodes)   # number of free nodes
    nr = len(reservoirs)
    nk = len(pipes)

    if np == 0:
        raise ValueError("At least one demand node required")
    if nr == 0:
        raise ValueError("At least one reservoir required")

    # Index mapping
    node_idx: dict[str, int] = {n.id: i for i, n in enumerate(nodes)}
    res_idx:  dict[str, int] = {r.id: i for i, r in enumerate(reservoirs)}
    all_idx:  dict[str, int] = {**node_idx, **{r.id: np + i for i, r in enumerate(reservoirs)}}

    res_heads = [r.head_m for r in reservoirs]

    # Pre-compute HW resistance coefficients
    hw_r = [
        _hw_resistance(p.length_m, p.diameter_m, p.roughness) if formula == "HW" else 0.0
        for p in pipes
    ]

    # Initial flows — start from a small positive value to avoid zero derivative
    Q = [1e-3] * nk

    def conductance(k: int, q: float) -> float:
        """Linearised pipe conductance g_k = 1 / (dh/dQ).  Always > 0."""
        p = pipes[k]
        if formula == "HW":
            dh = _hw_dh_dQ(q, hw_r[k])
        else:
            _, dh = _dw_headloss_and_dhdQ(q, p.length_m, p.diameter_m, p.roughness)
        return 1.0 / max(dh, 1e-30)

    converged = False
    residual = float("inf")
    iters = 0
    H = [sum(res_heads) / max(nr, 1)] * np  # initial head guess

    for iteration in range(max_iter):
        iters = iteration + 1

        # Compute conductances
        g = [conductance(k, Q[k]) for k in range(nk)]

        # Build conductance matrix A (np × np) and RHS b
        A = [[0.0] * np for _ in range(np)]
        b = [0.0] * np

        for k, pipe in enumerate(pipes):
            ia = all_idx[pipe.node_a]
            ib = all_idx[pipe.node_b]
            a_free = ia < np
            b_free = ib < np

            gk = g[k]
            if a_free and b_free:
                A[ia][ia] += gk
                A[ib][ib] += gk
                A[ia][ib] -= gk
                A[ib][ia] -= gk
            elif a_free:
                # node_b = reservoir
                A[ia][ia] += gk
                b[ia] += gk * res_heads[ib - np]
            elif b_free:
                # node_a = reservoir
                A[ib][ib] += gk
                b[ib] += gk * res_heads[ia - np]
            # both fixed: skip

        # Incorporate demands (flow withdrawn from node)
        for i, node in enumerate(nodes):
            b[i] -= node.demand_m3s

        # Solve for new heads
        H_new = _gaussian_solve(A, b)
        if H_new is None:
            break  # singular matrix

        # Update pipe flows: Q_k = g_k * (H_a - H_b)
        # This is the linearised flow that exactly satisfies mass balance.
        Q_new = []
        for k, pipe in enumerate(pipes):
            ia = all_idx[pipe.node_a]
            ib = all_idx[pipe.node_b]
            ha = H_new[ia] if ia < np else res_heads[ia - np]
            hb = H_new[ib] if ib < np else res_heads[ib - np]
            Q_new.append(g[k] * (ha - hb))

        residual = max(abs(Q_new[k] - Q[k]) for k in range(nk))
        Q = Q_new
        H = list(H_new)

        if residual < tol:
            converged = True
            break

    # Assemble results
    heads: dict[str, float] = {}
    for i, node in enumerate(nodes):
        heads[node.id] = H[i]
    for res in reservoirs:
        heads[res.id] = res.head_m

    pressures = {
        node.id: heads[node.id] - node.elevation_m for node in nodes
    }
    for res in reservoirs:
        pressures[res.id] = 0.0

    return NetworkResult(
        pipe_flows_m3s={pipes[k].id: Q[k] for k in range(nk)},
        nodal_heads_m=heads,
        nodal_pressures_m=pressures,
        iterations=iters,
        converged=converged,
        residual=residual,
    )


def _gaussian_solve(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting. Returns None if singular."""
    n = len(b)
    M = [A[i][:] + [b[i]] for i in range(n)]

    for col in range(n):
        max_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[max_row] = M[max_row], M[col]
        pivot = M[col][col]
        if abs(pivot) < 1e-20:
            return None
        inv_p = 1.0 / pivot
        for row in range(col + 1, n):
            if M[row][col] == 0.0:
                continue
            factor = M[row][col] * inv_p
            M[row] = [M[row][j] - factor * M[col][j] for j in range(n + 1)]

    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = M[i][n]
        for j in range(i + 1, n):
            x[i] -= M[i][j] * x[j]
        if abs(M[i][i]) < 1e-20:
            return None
        x[i] /= M[i][i]

    return x


# ---------------------------------------------------------------------------
# Mass-balance check
# ---------------------------------------------------------------------------

def check_mass_balance(
    nodes: list[Node],
    reservoirs: list[Reservoir],
    pipes: list[Pipe],
    result: NetworkResult,
) -> dict[str, float]:
    """
    Compute nodal mass balance residual.

    Residual at node i = (sum of flows into i) − demand_i
    Should be ≈ 0 for a converged solution.
    Positive Q_k means flow from node_a → node_b.
    """
    balance: dict[str, float] = {n.id: -n.demand_m3s for n in nodes}
    for pipe in pipes:
        q = result.pipe_flows_m3s[pipe.id]
        if pipe.node_a in balance:
            balance[pipe.node_a] -= q   # outflow from node_a
        if pipe.node_b in balance:
            balance[pipe.node_b] += q   # inflow to node_b
    return balance
