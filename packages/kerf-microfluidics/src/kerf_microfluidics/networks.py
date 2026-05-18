"""
Kirchhoff-law microfluidic network solver.

Models a network of channels (resistors) connecting pressure nodes, then
solves for the nodal pressures and branch flow rates using a conductance
matrix (Laplacian) linear system — the hydraulic analogue of nodal analysis
in electrical circuits.

Pure Python (no NumPy/SciPy); uses Gaussian elimination.

References
----------
Bruus, H. (2008). *Theoretical Microfluidics*. Oxford University Press.
  ch. 2 — equivalent-circuit analogy for microfluidic networks.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Gaussian elimination (pure Python)
# ---------------------------------------------------------------------------

def _gauss_solve(A: list[list[float]], b: list[float]) -> list[float]:
    """
    Solve Ax = b via Gaussian elimination with partial pivoting.

    Parameters
    ----------
    A : list[list[float]]
        n×n coefficient matrix (will be modified in-place).
    b : list[float]
        Right-hand side vector of length n (will be modified in-place).

    Returns
    -------
    list[float]
        Solution vector x of length n.

    Raises
    ------
    ValueError
        If the system is singular or the dimensions are inconsistent.
    """
    n = len(b)
    if len(A) != n or any(len(row) != n for row in A):
        raise ValueError("A must be an n×n matrix matching the length of b")

    # Forward elimination with partial pivoting
    for col in range(n):
        # Find pivot
        pivot_row = max(range(col, n), key=lambda r: abs(A[r][col]))
        if abs(A[pivot_row][col]) < 1e-30:
            raise ValueError(
                f"Singular matrix encountered at column {col}: "
                "the network may be under-constrained (missing pressure BC)."
            )
        # Swap rows
        A[col], A[pivot_row] = A[pivot_row], A[col]
        b[col], b[pivot_row] = b[pivot_row], b[col]

        # Eliminate below
        for row in range(col + 1, n):
            factor = A[row][col] / A[col][col]
            for k in range(col, n):
                A[row][k] -= factor * A[col][k]
            b[row] -= factor * b[col]

    # Back substitution
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = b[row]
        for k in range(row + 1, n):
            x[row] -= A[row][k] * x[k]
        x[row] /= A[row][row]

    return x


# ---------------------------------------------------------------------------
# Network solver
# ---------------------------------------------------------------------------

class MicrofluidicNetwork:
    """
    Kirchhoff-law solver for a microfluidic channel network.

    Usage
    -----
    >>> net = MicrofluidicNetwork()
    >>> net.add_node("in")
    >>> net.add_node("out")
    >>> net.add_node("mid")
    >>> net.add_channel("in", "mid", resistance=1e12)
    >>> net.add_channel("mid", "out", resistance=1e12)
    >>> net.set_pressure("in", 1000.0)   # Pa
    >>> net.set_pressure("out", 0.0)
    >>> result = net.solve()
    >>> result["pressures"]["mid"]  # ~500 Pa
    >>> result["flows"][("in", "mid")]  # flow rate m³/s
    """

    def __init__(self) -> None:
        self._nodes: list[str] = []
        self._channels: list[dict[str, Any]] = []
        self._pressure_bcs: dict[str, float] = {}

    # ------------------------------------------------------------------ setup

    def add_node(self, name: str) -> None:
        """Register a named pressure node."""
        if name in self._nodes:
            raise ValueError(f"Node '{name}' already exists.")
        self._nodes.append(name)

    def add_channel(
        self,
        node_a: str,
        node_b: str,
        *,
        resistance: float,
        label: str | None = None,
    ) -> None:
        """
        Add a channel (resistor) between two nodes.

        Parameters
        ----------
        node_a, node_b : str
            Names of the end nodes (must have been added via add_node).
        resistance : float
            Hydraulic resistance [Pa·s/m³].  Must be > 0.
        label : str, optional
            Human-readable label; defaults to ``"node_a→node_b"``.
        """
        if node_a not in self._nodes:
            raise ValueError(f"Node '{node_a}' not found; call add_node first.")
        if node_b not in self._nodes:
            raise ValueError(f"Node '{node_b}' not found; call add_node first.")
        if resistance <= 0:
            raise ValueError(f"Resistance must be > 0; got {resistance}.")
        self._channels.append(
            {
                "a": node_a,
                "b": node_b,
                "R": resistance,
                "label": label or f"{node_a}→{node_b}",
            }
        )

    def set_pressure(self, node: str, pressure: float) -> None:
        """Fix the pressure at a node (Dirichlet boundary condition)."""
        if node not in self._nodes:
            raise ValueError(f"Node '{node}' not found; call add_node first.")
        self._pressure_bcs[node] = pressure

    # ------------------------------------------------------------------ solve

    def solve(self) -> dict[str, Any]:
        """
        Solve for nodal pressures and channel flow rates.

        Returns
        -------
        dict with keys:
          ``pressures`` : dict[str, float]  — pressure at every node [Pa]
          ``flows``     : dict[tuple, float] — flow rate in every channel [m³/s]
                           keyed by ``(node_a, node_b, label)``

        Raises
        ------
        ValueError
            If no pressure BCs are set, or if the system is singular.
        """
        if not self._pressure_bcs:
            raise ValueError(
                "At least one pressure boundary condition must be set."
            )

        nodes = self._nodes
        n = len(nodes)
        idx = {name: i for i, name in enumerate(nodes)}

        # Build conductance (Laplacian) matrix and RHS
        G = [[0.0] * n for _ in range(n)]
        rhs = [0.0] * n

        for ch in self._channels:
            ia, ib = idx[ch["a"]], idx[ch["b"]]
            g = 1.0 / ch["R"]
            G[ia][ia] += g
            G[ib][ib] += g
            G[ia][ib] -= g
            G[ib][ia] -= g

        # Apply Dirichlet BCs by row replacement
        for node, p in self._pressure_bcs.items():
            i = idx[node]
            G[i] = [0.0] * n
            G[i][i] = 1.0
            rhs[i] = p

        pressures_vec = _gauss_solve(G, rhs)
        pressures = {name: pressures_vec[idx[name]] for name in nodes}

        # Compute flow rates Q = ΔP / R (from node_a to node_b)
        # Ensure unique keys when multiple channels share the same (a, b, label).
        flows: dict[tuple, float] = {}
        _key_counts: dict[tuple, int] = {}
        for ch in self._channels:
            pa = pressures[ch["a"]]
            pb = pressures[ch["b"]]
            Q = (pa - pb) / ch["R"]
            base_key = (ch["a"], ch["b"], ch["label"])
            count = _key_counts.get(base_key, 0)
            _key_counts[base_key] = count + 1
            if count == 0:
                key = base_key
            else:
                key = (ch["a"], ch["b"], f"{ch['label']}#{count}")
            flows[key] = Q

        return {"pressures": pressures, "flows": flows}


# ---------------------------------------------------------------------------
# Convenience: two-terminal equivalent resistance
# ---------------------------------------------------------------------------

def equivalent_resistance(
    channels: list[dict[str, Any]],
    source_node: str,
    sink_node: str,
) -> float:
    """
    Compute the equivalent hydraulic resistance between source and sink nodes
    for a network described as a list of channel dicts.

    Parameters
    ----------
    channels : list of dict
        Each dict must have keys ``node_a``, ``node_b``, ``resistance``.
    source_node : str
        Node at which 1 Pa is applied.
    sink_node : str
        Node held at 0 Pa (reference).

    Returns
    -------
    float
        Equivalent resistance [Pa·s/m³].
    """
    net = MicrofluidicNetwork()
    all_nodes: set[str] = set()
    for ch in channels:
        all_nodes.add(ch["node_a"])
        all_nodes.add(ch["node_b"])
    for node in sorted(all_nodes):
        net.add_node(node)
    for ch in channels:
        net.add_channel(ch["node_a"], ch["node_b"], resistance=ch["resistance"])

    net.set_pressure(source_node, 1.0)
    net.set_pressure(sink_node, 0.0)
    result = net.solve()

    # Total outflow at sink (sum of flows entering sink)
    Q_total = 0.0
    for (a, b, _label), Q in result["flows"].items():
        if b == sink_node:
            Q_total += Q
        elif a == sink_node:
            Q_total -= Q

    if abs(Q_total) < 1e-60:
        raise ValueError("No flow through network; check connectivity.")

    return 1.0 / Q_total  # R_eq = ΔP / Q = 1 Pa / Q
