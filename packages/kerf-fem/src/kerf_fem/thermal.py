"""
Steady-state heat-conduction FEM for canonical 1-D and analytic 1-D-fin
problems with citation-grade closed-form oracles.

Public entry-points
-------------------
    solve_1d_conduction(k, L, T_left, T_right, *, n_elem=10, q_vol=0.0) -> dict
        1-D heat conduction in a slab with Dirichlet end-temperatures.

    fin_efficiency(k, h, P, A_c, L) -> dict
        Efficiency of an adiabatic-tip straight rectangular fin:
            η = tanh(mL) / (mL)   ,   m = √(h P / (k A_c))
        Reference: Incropera et al., "Fundamentals of Heat and Mass Transfer",
        7th ed., eq. (3.91).

    thermal_resistance_series(layers) -> dict
        R_total = Σ Δx_i / (k_i A) for a multilayer wall in series.
        Reference: Incropera eq. (3.21).

Formulation
-----------
The 1-D conduction FEM uses linear Lagrange elements (2-node bars) with
constant conductivity per element.  The shape functions are exact for a
linear temperature profile (Poisson's equation in 1-D with constant k and
no volumetric source), so this FEM recovers T(x) = T_L + (T_R − T_L) x/L
to floating-point precision at the nodes.

Heat flux  q = −k dT/dx  is recovered element-wise.

Units: SI (W, K, m).

All routines never raise; errors are returned as {"ok": False, "reason": "..."}.
"""

from __future__ import annotations

import math
from typing import Any


def _gauss_solve(K: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve K x = rhs by Gaussian elimination with partial pivoting."""
    n = len(rhs)
    A = [row[:] + [rhs[i]] for i, row in enumerate(K)]
    for col in range(n):
        max_row, max_val = col, abs(A[col][col])
        for row in range(col + 1, n):
            v = abs(A[row][col])
            if v > max_val:
                max_val, max_row = v, row
        A[col], A[max_row] = A[max_row], A[col]
        pivot = A[col][col]
        if abs(pivot) < 1e-18:
            return None
        inv = 1.0 / pivot
        for row in range(col + 1, n):
            factor = A[row][col] * inv
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                A[row][j] -= factor * A[col][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = A[i][n]
        for j in range(i + 1, n):
            s -= A[i][j] * x[j]
        if abs(A[i][i]) < 1e-18:
            return None
        x[i] = s / A[i][i]
    return x


def _apply_dirichlet(K: list[list[float]], rhs: list[float],
                     fixed: dict[int, float]) -> None:
    n = len(rhs)
    for d, val in fixed.items():
        for i in range(n):
            if i != d:
                rhs[i] -= K[i][d] * val
    for d, val in fixed.items():
        for j in range(n):
            K[d][j] = 0.0
            K[j][d] = 0.0
        K[d][d] = 1.0
        rhs[d] = val


def solve_1d_conduction(
    k: float,
    L: float,
    T_left: float,
    T_right: float,
    *,
    n_elem: int = 10,
    q_vol: float = 0.0,
    area: float = 1.0,
) -> dict[str, Any]:
    """
    Steady-state 1-D heat conduction in a uniform slab.

    Governing equation:        d/dx ( k A dT/dx ) + q_vol A = 0
    BCs:                       T(0) = T_left,  T(L) = T_right

    Closed-form for q_vol = 0 (Incropera eq. 3.6):
        T(x) = T_left + (T_right − T_left) · x / L
        q   = k (T_left − T_right) / L          [W/m²]
        Q   = q · A                              [W]

    Returns
    -------
    {
        "ok"        : bool,
        "T"         : list[float]   nodal temperatures [K]
        "x"         : list[float]   nodal positions [m]
        "q_flux"    : list[float]   element-centroid heat flux  −k dT/dx [W/m²]
        "Q_total"   : float         heat-flow rate through the slab [W]
    }
    """
    if k <= 0:
        return {"ok": False, "reason": "k must be positive"}
    if L <= 0:
        return {"ok": False, "reason": "L must be positive"}
    if area <= 0:
        return {"ok": False, "reason": "area must be positive"}
    if n_elem < 1:
        return {"ok": False, "reason": "n_elem must be >= 1"}

    h = L / n_elem
    n_nodes = n_elem + 1
    x = [i * h for i in range(n_nodes)]

    K = [[0.0] * n_nodes for _ in range(n_nodes)]
    f = [0.0] * n_nodes

    # Element conductivity matrix: k A / h * [[1,-1],[-1,1]]
    # Volumetric source f_e = q_vol A h / 2 * [1, 1]
    ke = k * area / h
    for e in range(n_elem):
        i, j = e, e + 1
        K[i][i] += ke
        K[i][j] -= ke
        K[j][i] -= ke
        K[j][j] += ke
        # Body source (uniformly distributed)
        f[i] += q_vol * area * h / 2.0
        f[j] += q_vol * area * h / 2.0

    _apply_dirichlet(K, f, {0: T_left, n_nodes - 1: T_right})

    T = _gauss_solve(K, f)
    if T is None:
        return {"ok": False, "reason": "singular system"}

    # Heat flux per element (centroid)
    q_flux = []
    for e in range(n_elem):
        dT = (T[e + 1] - T[e]) / h
        q_flux.append(-k * dT)

    # Heat flow: Fourier conduction at the left boundary
    Q_total = -k * area * (T[1] - T[0]) / h

    return {
        "ok": True,
        "T": T,
        "x": x,
        "q_flux": q_flux,
        "Q_total": Q_total,
    }


def fin_efficiency(
    k: float,
    h: float,
    P: float,
    A_c: float,
    L: float,
) -> dict[str, Any]:
    """
    Efficiency of a straight rectangular fin with adiabatic tip
    (Incropera, "Fundamentals of Heat and Mass Transfer", 7th ed., eq. 3.91):

        m = √( h P / (k A_c) )
        η = tanh(m L) / (m L)

    Parameters
    ----------
    k   : thermal conductivity [W/(m K)]
    h   : convection coefficient [W/(m² K)]
    P   : fin perimeter [m]
    A_c : cross-section area [m²]
    L   : fin length [m]

    Returns
    -------
    { ok, eta, m, mL }
    """
    if k <= 0:
        return {"ok": False, "reason": "k must be positive"}
    if h <= 0:
        return {"ok": False, "reason": "h must be positive"}
    if P <= 0:
        return {"ok": False, "reason": "P must be positive"}
    if A_c <= 0:
        return {"ok": False, "reason": "A_c must be positive"}
    if L <= 0:
        return {"ok": False, "reason": "L must be positive"}

    m = math.sqrt(h * P / (k * A_c))
    mL = m * L
    eta = math.tanh(mL) / mL
    return {"ok": True, "eta": eta, "m": m, "mL": mL}


def thermal_resistance_series(layers: list[dict]) -> dict[str, Any]:
    """
    Series conduction resistance for a multilayer wall (Incropera eq. 3.21):

        R_i = Δx_i / (k_i A)
        R_total = Σ R_i

    Parameters
    ----------
    layers : list of dicts, each { "k": W/m K, "dx": thickness [m], "A": area [m²] }

    Returns
    -------
    { ok, R_total: K/W, R_layers: [float, ...] }
    """
    if not layers:
        return {"ok": False, "reason": "layers must be non-empty"}

    R_layers = []
    R_total = 0.0
    for i, layer in enumerate(layers):
        try:
            k = float(layer["k"])
            dx = float(layer["dx"])
            A = float(layer["A"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "reason": f"layer {i}: missing k/dx/A"}
        if k <= 0 or dx <= 0 or A <= 0:
            return {"ok": False, "reason": f"layer {i}: k/dx/A must be positive"}
        R = dx / (k * A)
        R_layers.append(R)
        R_total += R

    return {"ok": True, "R_total": R_total, "R_layers": R_layers}
