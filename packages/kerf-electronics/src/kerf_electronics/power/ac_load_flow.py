"""
kerf_electronics.power.ac_load_flow — Newton-Raphson AC load-flow analysis.

Public API
----------
PowerBus            — bus data (slack / PV / PQ)
PowerLine           — branch data (R, X, B in per-unit)
PowerSystem         — system container + newton_raphson_load_flow()
build_y_bus         — bus admittance matrix (Y_bus = G + jB)

All pure Python + numpy.  No scipy.

Theory
------
The Newton-Raphson load flow iterates on the mismatch vector:

    [ΔP]   [∂P/∂θ   ∂P/∂|V|] [Δθ ]
    [ΔQ] = [∂Q/∂θ   ∂Q/∂|V|] [Δ|V|]

Jacobian sub-matrices (Stevenson 1982 §9):
    J11 = ∂P/∂θ:  J11_ij = |Vi||Vj|(Gij sin θij - Bij cos θij)  i≠j
                             -Qi - Bii|Vi|²                        i=j
    J12 = ∂P/∂|V|: J12_ij = |Vi|(Gij cos θij + Bij sin θij)    i≠j
                               Pi/|Vi| + Gii|Vi|                   i=j
    J21 = ∂Q/∂θ:  J21_ij = -|Vi||Vj|(Gij cos θij + Bij sin θij) i≠j
                              Pi - Gii|Vi|²                         i=j
    J22 = ∂Q/∂|V|: J22_ij = |Vi|(Gij sin θij - Bij cos θij)    i≠j
                               Qi/|Vi| - Bii|Vi|                   i=j

References
----------
Stevenson, W.D. (1982). "Elements of Power System Analysis", 4th ed. McGraw-Hill.
Grainger, J.J. & Stevenson, W.D. (1994). "Power System Analysis." McGraw-Hill.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PowerBus:
    """
    Represents a bus (node) in an AC power system.

    Attributes
    ----------
    bus_id          : unique string identifier
    bus_type        : 'slack' (reference bus), 'PV' (generator), 'PQ' (load)
    P_specified_mw  : specified active power injection (MW);
                      positive = generation, negative = load
                      (not used for slack)
    Q_specified_mvar : specified reactive power injection (Mvar);
                       (used only for PQ buses)
    V_specified_pu  : specified voltage magnitude (pu) — used for slack and PV
    angle_deg       : voltage angle (degrees) — fixed for slack (=0), initial
                      guess for others

    References: Stevenson (1982) §9-1; Grainger-Stevenson (1994) §9.
    """
    bus_id: str
    bus_type: str               # 'slack' | 'PV' | 'PQ'
    P_specified_mw: float       # MW
    Q_specified_mvar: float     # Mvar
    V_specified_pu: float = 1.0
    angle_deg: float = 0.0

    def __post_init__(self) -> None:
        if self.bus_type not in ("slack", "PV", "PQ"):
            raise ValueError(
                f"bus_type must be 'slack', 'PV', or 'PQ'; got {self.bus_type!r}"
            )


@dataclass
class PowerLine:
    """
    Represents a transmission line (branch) in an AC power system.

    Attributes
    ----------
    line_id   : unique string identifier
    from_bus  : bus_id of the sending end
    to_bus    : bus_id of the receiving end
    R_pu      : series resistance (per-unit on system base)
    X_pu      : series reactance (per-unit)
    B_pu      : total shunt susceptance (per-unit), usually charging

    References: Stevenson (1982) §5; Grainger-Stevenson (1994) §5.
    """
    line_id: str
    from_bus: str
    to_bus: str
    R_pu: float
    X_pu: float
    B_pu: float = 0.0


@dataclass
class PowerSystem:
    """
    AC power system container.

    Attributes
    ----------
    buses    : list of PowerBus
    lines    : list of PowerLine
    base_mva : system MVA base (default 100 MVA)

    Methods
    -------
    newton_raphson_load_flow(max_iter, tol)
        Run full N-R AC load flow. Returns convergence info, bus voltages,
        and line power flows.

    References: Stevenson (1982) §9; Grainger-Stevenson (1994) §9.
    """
    buses: list[PowerBus]
    lines: list[PowerLine]
    base_mva: float = 100.0

    def newton_raphson_load_flow(
        self,
        max_iter: int = 20,
        tol: float = 1e-6,
    ) -> dict:
        """
        Newton-Raphson AC load flow.

        Algorithm (Stevenson 1982 §9):
        1. Build Y_bus admittance matrix.
        2. Initialise voltages (flat start or specified values).
        3. Compute power mismatches ΔP, ΔQ.
        4. Form Jacobian J.
        5. Solve J·[Δθ, Δ|V|/|V|] = [ΔP, ΔQ].
        6. Update θ and |V|.
        7. Repeat until max(|ΔP|, |ΔQ|) < tol.

        Returns
        -------
        dict with keys:
            converged    : bool
            iterations   : int
            bus_voltages : dict {bus_id: (V_pu, angle_deg)}
            bus_powers   : dict {bus_id: {'P_mw', 'Q_mvar'}}
            line_flows   : list of dicts with 'line_id', 'from_bus', 'to_bus',
                           'P_from_mw', 'Q_from_mvar', 'P_to_mw', 'Q_to_mvar'
            max_mismatch : float (final |ΔP or ΔQ| in pu)
        """
        return _newton_raphson_load_flow(self, max_iter, tol)


# ---------------------------------------------------------------------------
# Y-bus construction
# ---------------------------------------------------------------------------

def build_y_bus(system: PowerSystem) -> np.ndarray:
    """
    Construct the bus admittance matrix Y_bus (complex, n×n).

    For each line k from bus i to bus j:
        y_series = 1 / (R_pu + j·X_pu)
        Y_bus[i,i] += y_series + j·B_pu/2
        Y_bus[j,j] += y_series + j·B_pu/2
        Y_bus[i,j] -= y_series
        Y_bus[j,i] -= y_series

    Returns Y_bus = G + j·B (complex-valued n×n numpy array).

    References: Stevenson (1982) §5-6; Grainger-Stevenson (1994) §6.
    """
    bus_ids = [b.bus_id for b in system.buses]
    idx = {bid: k for k, bid in enumerate(bus_ids)}
    n = len(system.buses)
    Y = np.zeros((n, n), dtype=complex)

    for line in system.lines:
        i = idx[line.from_bus]
        j = idx[line.to_bus]
        Z = complex(line.R_pu, line.X_pu)
        if abs(Z) < 1e-15:
            raise ValueError(
                f"Line {line.line_id!r}: series impedance is zero (R=X=0)."
            )
        y_s = 1.0 / Z
        y_sh = complex(0.0, line.B_pu / 2.0)  # half shunt admittance at each end

        Y[i, i] += y_s + y_sh
        Y[j, j] += y_s + y_sh
        Y[i, j] -= y_s
        Y[j, i] -= y_s

    return Y


# ---------------------------------------------------------------------------
# Newton-Raphson load flow (internal implementation)
# ---------------------------------------------------------------------------

def _newton_raphson_load_flow(
    system: PowerSystem,
    max_iter: int,
    tol: float,
) -> dict:
    """
    Full Newton-Raphson AC load-flow implementation.

    References: Stevenson (1982) §9-3; Grainger-Stevenson (1994) §9-6.
    """
    bus_ids = [b.bus_id for b in system.buses]
    idx = {bid: k for k, bid in enumerate(bus_ids)}
    n = len(system.buses)

    # Identify bus types
    slack_indices = [k for k, b in enumerate(system.buses) if b.bus_type == "slack"]
    pv_indices = [k for k, b in enumerate(system.buses) if b.bus_type == "PV"]
    pq_indices = [k for k, b in enumerate(system.buses) if b.bus_type == "PQ"]

    if len(slack_indices) != 1:
        return {
            "converged": False,
            "error": f"Exactly one slack bus required; found {len(slack_indices)}.",
            "iterations": 0,
            "bus_voltages": {},
            "bus_powers": {},
            "line_flows": [],
            "max_mismatch": None,
        }

    slack_idx = slack_indices[0]

    # Y-bus
    Y = build_y_bus(system)
    G = Y.real
    B = Y.imag

    # Initialise voltages (flat start)
    V = np.ones(n)       # voltage magnitudes (pu)
    theta = np.zeros(n)  # voltage angles (rad)

    for bus in system.buses:
        k = idx[bus.bus_id]
        if bus.bus_type in ("slack", "PV"):
            V[k] = bus.V_specified_pu
        theta[k] = math.radians(bus.angle_deg)

    # Specified injections in pu
    P_spec = np.zeros(n)
    Q_spec = np.zeros(n)
    for bus in system.buses:
        k = idx[bus.bus_id]
        if bus.bus_type in ("PV", "PQ"):
            P_spec[k] = bus.P_specified_mw / system.base_mva
        if bus.bus_type == "PQ":
            Q_spec[k] = bus.Q_specified_mvar / system.base_mva

    # Variable indices: Δθ for all non-slack; Δ|V| for PQ buses only
    theta_free = [k for k in range(n) if k != slack_idx]
    v_free = pq_indices  # PQ buses: V is a variable

    converged = False
    max_mismatch = float("inf")
    iterations = 0

    for it in range(max_iter):
        # Compute injected power at each bus
        P_calc = np.zeros(n)
        Q_calc = np.zeros(n)
        for i in range(n):
            for j in range(n):
                tij = theta[i] - theta[j]
                P_calc[i] += V[i] * V[j] * (G[i, j] * math.cos(tij) + B[i, j] * math.sin(tij))
                Q_calc[i] += V[i] * V[j] * (G[i, j] * math.sin(tij) - B[i, j] * math.cos(tij))

        # Mismatches
        dP = P_spec - P_calc  # for non-slack buses
        dQ = Q_spec - Q_calc  # for PQ buses

        dP_free = np.array([dP[k] for k in theta_free])
        dQ_free = np.array([dQ[k] for k in v_free])

        mismatch = np.concatenate([dP_free, dQ_free])
        max_mismatch = float(np.max(np.abs(mismatch))) if len(mismatch) > 0 else 0.0

        if max_mismatch < tol:
            converged = True
            iterations = it
            break

        # Build Jacobian
        nf = len(theta_free)
        nv = len(v_free)
        N = nf + nv
        J = np.zeros((N, N))

        # Helper maps
        tf_map = {k: i for i, k in enumerate(theta_free)}
        vf_map = {k: i for i, k in enumerate(v_free)}

        for pi, i in enumerate(theta_free):
            # J11: ∂P/∂θ
            for pj, j in enumerate(theta_free):
                tij = theta[i] - theta[j]
                if i == j:
                    J[pi, pj] = -Q_calc[i] - B[i, i] * V[i] ** 2
                else:
                    J[pi, pj] = V[i] * V[j] * (G[i, j] * math.sin(tij) - B[i, j] * math.cos(tij))

            # J12: ∂P/∂|V| (only PQ buses)
            for qj, j in enumerate(v_free):
                tij = theta[i] - theta[j]
                if i == j:
                    J[pi, nf + qj] = P_calc[i] / V[i] + G[i, i] * V[i]
                else:
                    J[pi, nf + qj] = V[i] * (G[i, j] * math.cos(tij) + B[i, j] * math.sin(tij))

        for qi, i in enumerate(v_free):
            # J21: ∂Q/∂θ
            for pj, j in enumerate(theta_free):
                tij = theta[i] - theta[j]
                if i == j:
                    J[nf + qi, pj] = P_calc[i] - G[i, i] * V[i] ** 2
                else:
                    J[nf + qi, pj] = -V[i] * V[j] * (G[i, j] * math.cos(tij) + B[i, j] * math.sin(tij))

            # J22: ∂Q/∂|V|
            for qj, j in enumerate(v_free):
                tij = theta[i] - theta[j]
                if i == j:
                    J[nf + qi, nf + qj] = Q_calc[i] / V[i] - B[i, i] * V[i]
                else:
                    J[nf + qi, nf + qj] = V[i] * (G[i, j] * math.sin(tij) - B[i, j] * math.cos(tij))

        # Solve J·Δx = mismatch
        try:
            delta_x = np.linalg.solve(J, mismatch)
        except np.linalg.LinAlgError:
            return {
                "converged": False,
                "error": "Jacobian is singular at iteration " + str(it),
                "iterations": it,
                "bus_voltages": {},
                "bus_powers": {},
                "line_flows": [],
                "max_mismatch": max_mismatch,
            }

        # Update θ for non-slack buses
        for pi, k in enumerate(theta_free):
            theta[k] += delta_x[pi]

        # Update |V| for PQ buses (Δ|V|/|V| form)
        for qi, k in enumerate(v_free):
            V[k] += delta_x[nf + qi]  # direct Δ|V|

    if not converged:
        iterations = max_iter

    # Recompute final power at all buses
    P_calc_final = np.zeros(n)
    Q_calc_final = np.zeros(n)
    for i in range(n):
        for j in range(n):
            tij = theta[i] - theta[j]
            P_calc_final[i] += V[i] * V[j] * (G[i, j] * math.cos(tij) + B[i, j] * math.sin(tij))
            Q_calc_final[i] += V[i] * V[j] * (G[i, j] * math.sin(tij) - B[i, j] * math.cos(tij))

    # Build output
    bus_voltages: dict = {}
    bus_powers: dict = {}
    for k, bus in enumerate(system.buses):
        bus_voltages[bus.bus_id] = (
            float(V[k]),
            float(math.degrees(theta[k])),
        )
        bus_powers[bus.bus_id] = {
            "P_mw": float(P_calc_final[k] * system.base_mva),
            "Q_mvar": float(Q_calc_final[k] * system.base_mva),
        }

    # Line flows
    line_flows: list[dict] = []
    for line in system.lines:
        i = idx[line.from_bus]
        j = idx[line.to_bus]
        Z = complex(line.R_pu, line.X_pu)
        y_s = 1.0 / Z if abs(Z) > 1e-15 else complex(0)
        y_sh = complex(0.0, line.B_pu / 2.0)

        Vi = V[i] * complex(math.cos(theta[i]), math.sin(theta[i]))
        Vj = V[j] * complex(math.cos(theta[j]), math.sin(theta[j]))

        I_ij = y_s * (Vi - Vj) + y_sh * Vi
        I_ji = y_s * (Vj - Vi) + y_sh * Vj

        S_ij = Vi * I_ij.conjugate()
        S_ji = Vj * I_ji.conjugate()

        line_flows.append({
            "line_id": line.line_id,
            "from_bus": line.from_bus,
            "to_bus": line.to_bus,
            "P_from_mw": float(S_ij.real * system.base_mva),
            "Q_from_mvar": float(S_ij.imag * system.base_mva),
            "P_to_mw": float(S_ji.real * system.base_mva),
            "Q_to_mvar": float(S_ji.imag * system.base_mva),
        })

    return {
        "converged": converged,
        "iterations": iterations,
        "bus_voltages": bus_voltages,
        "bus_powers": bus_powers,
        "line_flows": line_flows,
        "max_mismatch": max_mismatch,
    }
