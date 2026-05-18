"""
Thermal-resistance network solver for spacecraft lumped-parameter models.

Model summary
-------------
The network consists of:

  - **Nodes**: each has a lumped thermal capacitance C [J/K], a current
    temperature T [K], and optionally a fixed (Dirichlet) temperature.
    Nodes may also have an external heat input Q_ext [W] (e.g., from solar
    absorption, internal dissipation, or RHU heaters).

  - **Conductive links**: Q = k_cond * (T_i − T_j)  where k_cond = kA/L [W/K].

  - **Radiative links**: Q = σ ε_eff A F (T_i⁴ − T_j⁴)
    where ε_eff is the effective emissivity of the link, A is the reference
    area, and F is the view factor.

The module provides two solvers:

  :func:`solve_steady_state`
      Newton–Raphson iteration on the nonlinear nodal energy balance
      Q_net(T) = 0 (for free nodes).  Radiative links make the system
      nonlinear.

  :func:`solve_transient_step`
      One implicit-Euler time step: C (T^{n+1} − T^n) / Δt = Q_net(T^{n+1}).
      The nonlinear system at each step is solved by Newton–Raphson.

Units: SI (W, K, J, m, s).

Reference
---------
  Gilmore, D.G. (ed.), "Spacecraft Thermal Control Handbook", 2nd ed.,
  Aerospace Press, 2002.  Chapter 5 (Thermal Mathematical Models).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

STEFAN_BOLTZMANN: float = 5.670374419e-8
"""Stefan–Boltzmann constant σ [W m⁻² K⁻⁴] — CODATA 2018."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """
    Lumped thermal node.

    Parameters
    ----------
    node_id : str
        Unique identifier.
    T : float
        Current temperature [K].
    C : float
        Lumped thermal capacitance [J/K].  Ignored in steady-state solver.
    Q_ext : float
        External heat input [W] (positive = into the node).
    fixed : bool
        If True, the node temperature is held constant (Dirichlet BC).
        The solver will not update its temperature.
    """

    node_id: str
    T: float                   # temperature [K]
    C: float = 1.0             # thermal capacitance [J/K]
    Q_ext: float = 0.0         # external heat [W]
    fixed: bool = False        # Dirichlet BC flag


@dataclass
class ConductiveLink:
    """
    Conductive (linear) thermal link between two nodes.

        Q_{i→j} = conductance * (T_i − T_j)

    Parameters
    ----------
    node_a, node_b : str
        IDs of the two connected nodes.
    conductance : float
        Thermal conductance k·A/L [W/K].
    """

    node_a: str
    node_b: str
    conductance: float    # [W/K]  k A / L


@dataclass
class RadiativeLink:
    """
    Radiative (nonlinear) thermal link between two nodes.

        Q_{i→j} = sigma * epsilon_eff * area * F * (T_i⁴ − T_j⁴)

    Parameters
    ----------
    node_a, node_b : str
        IDs of the two connected nodes.
    epsilon_eff : float
        Effective emissivity of the link (0–1).
        For a link between two gray surfaces:
            1 / ε_eff = 1/ε_1 + 1/ε_2 − 1   (parallel plate approximation)
        Caller is responsible for computing this.
    area : float
        Reference area [m²].
    view_factor : float
        View factor F_{a→b} (0–1).
    """

    node_a: str
    node_b: str
    epsilon_eff: float    # effective emissivity (0–1)
    area: float           # reference area [m²]
    view_factor: float    # F_{a→b}

    @property
    def rad_factor(self) -> float:
        """Pre-computed σ ε A F  [W K⁻⁴] (the linearized coupling factor)."""
        return STEFAN_BOLTZMANN * self.epsilon_eff * self.area * self.view_factor


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

class ThermalNetwork:
    """
    Lumped thermal-resistance network.

    Usage
    -----
    >>> net = ThermalNetwork()
    >>> net.add_node(Node("panel", T=300.0, C=1000.0, Q_ext=50.0))
    >>> net.add_node(Node("space", T=3.0, fixed=True))
    >>> net.add_link(RadiativeLink("panel", "space", epsilon_eff=0.85,
    ...                            area=1.0, view_factor=1.0))
    >>> result = net.solve_steady_state()
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._cond_links: list[ConductiveLink] = []
        self._rad_links: list[RadiativeLink] = []

    # ------------------------------------------------------------------
    # Building the network
    # ------------------------------------------------------------------

    def add_node(self, node: Node) -> None:
        """Add (or replace) a node in the network."""
        self._nodes[node.node_id] = node

    def add_link(self, link: ConductiveLink | RadiativeLink) -> None:
        """Add a conductive or radiative link."""
        if isinstance(link, ConductiveLink):
            self._cond_links.append(link)
        elif isinstance(link, RadiativeLink):
            self._rad_links.append(link)
        else:
            raise TypeError(f"Unknown link type: {type(link)}")

    # ------------------------------------------------------------------
    # Internal: net heat flow into node i (Q_ext + incoming from links)
    # ------------------------------------------------------------------

    def _q_net(self, T: dict[str, float]) -> dict[str, float]:
        """
        Compute net heat flow into each free node [W] given temperature map T.

        Parameters
        ----------
        T : dict[str, float]
            Node temperatures.

        Returns
        -------
        dict[str, float]
            Q_net[node_id] = Q_ext + Σ conductive_in + Σ radiative_in
        """
        Q: dict[str, float] = {nid: n.Q_ext for nid, n in self._nodes.items()}

        for lk in self._cond_links:
            dT = T[lk.node_a] - T[lk.node_b]
            heat = lk.conductance * dT
            Q[lk.node_b] += heat    # heat flows from a → b
            Q[lk.node_a] -= heat    # a loses heat

        for lk in self._rad_links:
            Ta4 = T[lk.node_a] ** 4
            Tb4 = T[lk.node_b] ** 4
            heat = lk.rad_factor * (Ta4 - Tb4)
            Q[lk.node_b] += heat
            Q[lk.node_a] -= heat

        return Q

    def _dq_dT(self, T: dict[str, float], node_id: str) -> float:
        """
        Partial derivative ∂Q_net_i / ∂T_i for Newton–Raphson Jacobian
        (diagonal only — sufficient for single-node relaxation; we use
        full Jacobian below but this is useful for the diagonal preconditioner).
        """
        dq = 0.0
        for lk in self._cond_links:
            if lk.node_a == node_id:
                dq -= lk.conductance
            elif lk.node_b == node_id:
                dq -= lk.conductance
        for lk in self._rad_links:
            Ti3 = 4.0 * T[node_id] ** 3
            if lk.node_a == node_id:
                dq -= lk.rad_factor * Ti3
            elif lk.node_b == node_id:
                dq -= lk.rad_factor * Ti3
        return dq

    # ------------------------------------------------------------------
    # Steady-state solver (Newton–Raphson)
    # ------------------------------------------------------------------

    def solve_steady_state(
        self,
        *,
        max_iter: int = 200,
        tol: float = 1e-6,
        relax: float = 0.5,
    ) -> dict[str, float]:
        """
        Solve the steady-state temperature distribution Q_net(T) = 0.

        For fixed nodes, the temperature is unchanged.  Free nodes are
        iterated with a damped Newton–Raphson scheme.

        The Jacobian uses only the diagonal terms (partial derivative of
        Q_net_i w.r.t. T_i), which corresponds to a nonlinear Gauss–Seidel
        sweep.  This is robust for networks without very strong cross-coupling
        and avoids the O(N²) dense-solve overhead.

        Parameters
        ----------
        max_iter : int
            Maximum number of Newton–Raphson iterations.
        tol : float
            Convergence tolerance on max |ΔT| [K].
        relax : float
            Damping factor ∈ (0, 1].  Lower values improve stability for
            strongly nonlinear networks.

        Returns
        -------
        dict[str, float]
            Final temperatures {node_id: T [K]}.

        Raises
        ------
        RuntimeError
            If the solver does not converge.
        """
        T: dict[str, float] = {nid: n.T for nid, n in self._nodes.items()}
        free_ids = [nid for nid, n in self._nodes.items() if not n.fixed]

        for iteration in range(max_iter):
            Q = self._q_net(T)
            max_dT = 0.0

            for nid in free_ids:
                q = Q[nid]
                if abs(q) < 1e-15:
                    continue
                dqdT = self._dq_dT(T, nid)
                if abs(dqdT) < 1e-30:
                    # No connections — temperature is unconstrained; skip.
                    continue
                delta = -q / dqdT
                T[nid] += relax * delta
                # Clamp to physical range (absolute zero floor)
                if T[nid] < 1e-3:
                    T[nid] = 1e-3
                if abs(delta) > max_dT:
                    max_dT = abs(delta)

            if max_dT < tol:
                # Update node temperatures in-place
                for nid, n in self._nodes.items():
                    n.T = T[nid]
                return dict(T)

        raise RuntimeError(
            f"Steady-state solver did not converge in {max_iter} iterations "
            f"(last max_dT={max_dT:.3e} K)."
        )

    # ------------------------------------------------------------------
    # Transient solver: one implicit-Euler step
    # ------------------------------------------------------------------

    def step_transient(
        self,
        dt: float,
        *,
        max_iter: int = 200,
        tol: float = 1e-6,
        relax: float = 0.5,
    ) -> dict[str, float]:
        """
        Advance the thermal network by one implicit-Euler time step Δt.

        The implicit-Euler discretisation of the energy balance is:

            C_i (T_i^{n+1} − T_i^n) / Δt = Q_net(T^{n+1})

        Rearranging:

            R_i(T^{n+1}) ≡ C_i (T_i^{n+1} − T_i^n) / Δt − Q_net(T^{n+1}) = 0

        This is solved with the same diagonal Newton–Raphson scheme used for
        the steady-state solver, adding the capacitance term to the diagonal.

        Parameters
        ----------
        dt : float
            Time step [s].  Must be > 0.
        max_iter, tol, relax : as for :func:`solve_steady_state`.

        Returns
        -------
        dict[str, float]
            Updated temperatures {node_id: T_new [K]}.

        Raises
        ------
        ValueError
            If dt <= 0.
        RuntimeError
            If the nonlinear solve does not converge.
        """
        if dt <= 0:
            raise ValueError(f"dt must be positive, got {dt!r}")

        # T_old = temperatures at the start of the step
        T_old: dict[str, float] = {nid: n.T for nid, n in self._nodes.items()}
        T: dict[str, float] = dict(T_old)  # iterate on T^{n+1}
        free_ids = [nid for nid, n in self._nodes.items() if not n.fixed]

        for iteration in range(max_iter):
            Q = self._q_net(T)
            max_dT = 0.0

            for nid in free_ids:
                node = self._nodes[nid]
                # Residual: R_i = C_i (T_i - T_old_i) / dt - Q_net_i
                residual = node.C * (T[nid] - T_old[nid]) / dt - Q[nid]
                # Jacobian diagonal: dR_i / dT_i = C_i/dt - dQ_net_i/dT_i
                dqdT = self._dq_dT(T, nid)
                jac_diag = node.C / dt - dqdT
                if abs(jac_diag) < 1e-30:
                    continue
                delta = -residual / jac_diag
                T[nid] += relax * delta
                if T[nid] < 1e-3:
                    T[nid] = 1e-3
                if abs(delta) > max_dT:
                    max_dT = abs(delta)

            if max_dT < tol:
                for nid, n in self._nodes.items():
                    n.T = T[nid]
                return dict(T)

        raise RuntimeError(
            f"Transient solver did not converge in {max_iter} iterations "
            f"(last max_dT={max_dT:.3e} K, dt={dt:.3e} s)."
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def temperatures(self) -> dict[str, float]:
        """Return current node temperatures."""
        return {nid: n.T for nid, n in self._nodes.items()}

    def heat_flows(self) -> dict[str, float]:
        """Return current Q_net for each node (at current temperatures)."""
        T = self.temperatures()
        return self._q_net(T)


# ---------------------------------------------------------------------------
# Convenience factory for a simple enclosure node
# ---------------------------------------------------------------------------

def make_space_node(T_space: float = 3.0) -> Node:
    """
    Create a fixed temperature node representing deep-space thermal sink.

    Parameters
    ----------
    T_space : float
        Background temperature [K].  Default 3 K (CMB approximate).

    Returns
    -------
    Node
    """
    return Node(node_id="space", T=T_space, C=1.0, Q_ext=0.0, fixed=True)


def radiative_coupling(
    epsilon1: float,
    epsilon2: float,
    area: float,
    view_factor: float,
    *,
    node_a: str,
    node_b: str,
) -> RadiativeLink:
    """
    Build a :class:`RadiativeLink` with the effective emissivity computed from
    the parallel-plate / large-enclosure approximation:

        1 / ε_eff = 1/ε_1 + 1/ε_2 − 1

    This is exact for infinite parallel gray plates and a reasonable
    approximation for other configurations.

    Parameters
    ----------
    epsilon1, epsilon2 : float
        Individual surface emissivities (0, 1].
    area : float
        Reference area [m²].
    view_factor : float
        F_{a→b}.
    node_a, node_b : str
        Node IDs.

    Returns
    -------
    RadiativeLink
    """
    if not (0 < epsilon1 <= 1):
        raise ValueError(f"epsilon1 must be in (0, 1], got {epsilon1}")
    if not (0 < epsilon2 <= 1):
        raise ValueError(f"epsilon2 must be in (0, 1], got {epsilon2}")
    eps_eff = 1.0 / (1.0 / epsilon1 + 1.0 / epsilon2 - 1.0)
    return RadiativeLink(
        node_a=node_a,
        node_b=node_b,
        epsilon_eff=eps_eff,
        area=area,
        view_factor=view_factor,
    )
