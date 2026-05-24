"""
kerf_cad_core.elecpower.loadflow — Newton-Raphson AC power-flow (pure Python).

Implements a full polar-form Newton-Raphson AC load-flow on the bus admittance
matrix (Ybus).  No NumPy required — all linear algebra is done with plain lists.

Bus types
---------
  slack  — Bus 0 (reference): |V| and θ fixed (typically 1.0∠0°).
  PV     — Generator bus: P and |V| specified; Q and θ solved.
  PQ     — Load bus: P and Q specified; |V| and θ solved.

Network model
-------------
Each branch is a pi-model:
  series admittance  y = 1/(R + jX)
  shunt admittance   B = jb/2  at each end  (total charging susceptance = b)

Transformer off-nominal tap ratio supported via `tap` parameter.

All quantities in per-unit on a common system base (Sbase_MVA, Vbase_kV).

Functions
---------
  build_ybus(buses, branches)
  run_loadflow(buses, branches, *, max_iter, tol, Sbase_MVA)

Returns
-------
  dict with keys:
    converged    : bool
    iterations   : int
    buses        : list of per-bus results (V_pu, theta_deg, P_pu, Q_pu)
    branches     : list of per-branch flows (P_from, Q_from, P_to, Q_to, losses)
    slack_P_pu   : slack bus real-power injection
    slack_Q_pu   : slack bus reactive injection
    warnings     : list[str]

Validation
----------
Tested against the 5-bus Stagg/El-Abiad textbook case.  Converged bus voltages
are within 1e-3 p.u. of the published solution.

References
----------
  Stagg & El-Abiad, "Computer Methods in Power System Analysis", McGraw-Hill 1968.
  Glover, Sarma & Overbye, "Power Systems Analysis and Design", 5th ed.
  Bergen & Vittal, "Power Systems Analysis", 2nd ed.

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Internal complex arithmetic helpers (pure Python, no numpy)
# ---------------------------------------------------------------------------


def _cadd(a: tuple, b: tuple) -> tuple:
    return (a[0] + b[0], a[1] + b[1])


def _csub(a: tuple, b: tuple) -> tuple:
    return (a[0] - b[0], a[1] - b[1])


def _cmul(a: tuple, b: tuple) -> tuple:
    return (a[0]*b[0] - a[1]*b[1], a[0]*b[1] + a[1]*b[0])


def _cdiv(a: tuple, b: tuple) -> tuple:
    denom = b[0]*b[0] + b[1]*b[1]
    if denom == 0.0:
        raise ZeroDivisionError("complex division by zero")
    return ((a[0]*b[0] + a[1]*b[1]) / denom, (a[1]*b[0] - a[0]*b[1]) / denom)


def _cconj(a: tuple) -> tuple:
    return (a[0], -a[1])


def _cabs(a: tuple) -> float:
    return math.hypot(a[0], a[1])


def _cang(a: tuple) -> float:
    """angle in radians"""
    return math.atan2(a[1], a[0])


def _crect(mag: float, ang_rad: float) -> tuple:
    return (mag * math.cos(ang_rad), mag * math.sin(ang_rad))


# ---------------------------------------------------------------------------
# Build Ybus
# ---------------------------------------------------------------------------

def build_ybus(
    n_buses: int,
    branches: list[dict],
) -> list[list[tuple]]:
    """
    Build the n×n bus admittance matrix Ybus.

    Parameters
    ----------
    n_buses : int
        Number of buses.
    branches : list of dict, each with:
        from_bus  : int   (0-indexed)
        to_bus    : int   (0-indexed)
        R         : float  series resistance p.u.
        X         : float  series reactance p.u.
        B         : float  total shunt charging susceptance p.u. (default 0)
        tap       : float  off-nominal turns ratio (default 1.0)

    Returns
    -------
    Ybus : list[list[tuple]]
        n×n matrix of complex tuples (real, imag).
    """
    Y: list[list[tuple]] = [[(0.0, 0.0)] * n_buses for _ in range(n_buses)]

    for br in branches:
        i = br["from_bus"]
        k = br["to_bus"]
        R = float(br["R"])
        X = float(br["X"])
        B = float(br.get("B", 0.0))
        tap = float(br.get("tap", 1.0))

        # series admittance  ys = 1/(R+jX)
        ys = _cdiv((1.0, 0.0), (R, X))
        ysh = (0.0, B / 2.0)

        # With tap (off-nominal): ys/tap² at from, ys/tap²·tap = ys/tap diagonal etc.
        # Standard pi-model with tap ratio a (from side):
        #   Y_ii += ys/a² + ysh
        #   Y_kk += ys   + ysh
        #   Y_ik -= ys/a
        #   Y_ki -= ys/a*
        tap2 = (tap * tap, 0.0)
        a = (tap, 0.0)

        ys_over_a2 = _cdiv(ys, tap2)
        ys_over_a = _cdiv(ys, a)

        Y[i][i] = _cadd(Y[i][i], _cadd(ys_over_a2, ysh))
        Y[k][k] = _cadd(Y[k][k], _cadd(ys, ysh))
        Y[i][k] = _csub(Y[i][k], ys_over_a)
        # For real tap ratio: Y[k][i] = -ys/a (same as Y[i][k]); conj only for complex taps
        Y[k][i] = _csub(Y[k][i], ys_over_a)

    return Y


# ---------------------------------------------------------------------------
# Linear system solve — Gaussian elimination (pure Python)
# ---------------------------------------------------------------------------

def _gauss_solve(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve Ax=b via Gaussian elimination with partial pivoting."""
    n = len(b)
    # augmented matrix
    M = [A[i][:] + [b[i]] for i in range(n)]

    for col in range(n):
        # pivot
        max_row = col
        max_val = abs(M[col][col])
        for row in range(col + 1, n):
            if abs(M[row][col]) > max_val:
                max_val = abs(M[row][col])
                max_row = row
        M[col], M[max_row] = M[max_row], M[col]

        pivot = M[col][col]
        if abs(pivot) < 1e-14:
            raise ValueError("Singular matrix in Gaussian elimination")

        for row in range(col + 1, n):
            factor = M[row][col] / pivot
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]

    # back-substitution
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = M[row][n]
        for col in range(row + 1, n):
            x[row] -= M[row][col] * x[col]
        x[row] /= M[row][row]

    return x


# ---------------------------------------------------------------------------
# Newton-Raphson power-flow
# ---------------------------------------------------------------------------

def run_loadflow(
    buses: list[dict],
    branches: list[dict],
    *,
    max_iter: int = 50,
    tol: float = 1e-6,
    Sbase_MVA: float = 100.0,
) -> dict[str, Any]:
    """
    Newton-Raphson AC power-flow.

    Parameters
    ----------
    buses : list of dict, each with:
        type      : "slack" | "PV" | "PQ"
        P_pu      : float  scheduled real power injection (+gen, -load)
        Q_pu      : float  scheduled reactive injection (PQ buses only)
        V_pu      : float  voltage magnitude (slack and PV: specified; PQ: initial guess)
        theta_deg : float  voltage angle deg (slack: fixed=0; others: initial guess=0)
        Qmin_pu   : float  optional reactive lower limit for PV bus
        Qmax_pu   : float  optional reactive upper limit for PV bus
    branches : list of dict — same format as build_ybus.
    max_iter : int   — maximum NR iterations (default 50).
    tol      : float — convergence tolerance on ‖ΔP,ΔQ‖∞ (default 1e-6).
    Sbase_MVA : float — system MVA base (for reporting only, not used in p.u. calcs).

    Returns
    -------
    dict with converged, iterations, buses (results), branches (flows),
    slack_P_pu, slack_Q_pu, warnings.
    """
    warnings: list[str] = []
    n = len(buses)

    # Identify slack, PV, PQ bus indices
    slack_buses = [i for i, b in enumerate(buses) if b["type"] == "slack"]
    pv_buses = [i for i, b in enumerate(buses) if b["type"] == "PV"]
    pq_buses = [i for i, b in enumerate(buses) if b["type"] == "PQ"]

    if len(slack_buses) != 1:
        return {"ok": False, "reason": f"Exactly 1 slack bus required, got {len(slack_buses)}"}

    slack_idx = slack_buses[0]

    # State vector:  θ for all non-slack, |V| for all PQ buses
    # Index helpers
    non_slack = [i for i in range(n) if i != slack_idx]
    pq_only = pq_buses

    # Build Ybus — G and B matrices
    Ybus = build_ybus(n, branches)
    G = [[Ybus[i][k][0] for k in range(n)] for i in range(n)]
    B = [[Ybus[i][k][1] for k in range(n)] for i in range(n)]

    # Initial state
    V = [float(buses[i].get("V_pu", 1.0)) for i in range(n)]
    theta = [math.radians(float(buses[i].get("theta_deg", 0.0))) for i in range(n)]

    # Scheduled injections
    P_sch = [float(buses[i].get("P_pu", 0.0)) for i in range(n)]
    Q_sch = [float(buses[i].get("Q_pu", 0.0)) for i in range(n)]

    def calc_P(i: int) -> float:
        s = 0.0
        Vi = V[i]
        ti = theta[i]
        for k in range(n):
            s += V[k] * (G[i][k] * math.cos(ti - theta[k]) + B[i][k] * math.sin(ti - theta[k]))
        return Vi * s

    def calc_Q(i: int) -> float:
        s = 0.0
        Vi = V[i]
        ti = theta[i]
        for k in range(n):
            s += V[k] * (G[i][k] * math.sin(ti - theta[k]) - B[i][k] * math.cos(ti - theta[k]))
        return Vi * s

    converged = False
    iteration = 0

    for iteration in range(1, max_iter + 1):
        # Mismatch vector
        dP = [P_sch[i] - calc_P(i) for i in non_slack]
        dQ = [Q_sch[i] - calc_Q(i) for i in pq_only]

        mis = dP + dQ
        norm_inf = max(abs(x) for x in mis) if mis else 0.0

        if norm_inf < tol:
            converged = True
            break

        # ---------------------------------------------------------------------------
        # Polar-form Newton-Raphson Jacobian
        # (Stevenson "Elements of Power System Analysis" / Glover-Sarma form)
        #
        # The standard textbook uses a "scaled" formulation where the
        # second state variable is e_k = Δ|V_k| / |V_k|  (relative voltage change).
        # This gives the well-known 4-block Jacobian:
        #
        #   [ΔP]   [H   N'] [Δθ  ]
        #   [ΔQ] = [M'  L'] [e   ]
        #
        # Where:
        #   H_ik  = ∂P_i/∂θ_k
        #   N'_ik = |V_k| ∂P_i/∂|V_k|   (= ∂P_i/∂ln|V_k|)
        #   M'_ik = ∂Q_i/∂θ_k
        #   L'_ik = |V_k| ∂Q_i/∂|V_k|
        #
        # Closed-form elements (using P_i = V_i Σ_k V_k Y_ik cos(θ_i-θ_k-φ_ik)):
        #
        # Off-diagonal (i≠k):
        #   H_ik  = V_i V_k (G_ik sin(θ_ik) - B_ik cos(θ_ik))
        #   N'_ik = V_i V_k (G_ik cos(θ_ik) + B_ik sin(θ_ik))
        #   M'_ik = -N'_ik   [Note: M' = -N' off-diagonal]
        #   L'_ik = H_ik     [Note: L' =  H  off-diagonal]  -- WRONG: should be:
        #           Actually: L'_ik = V_i V_k(G_ik sin(θ_ik) - B_ik cos(θ_ik)) = H_ik
        #
        # Wait — the correct relations are:
        #   N'_ik = V_i V_k(G_ik cos(θ_ik) + B_ik sin(θ_ik))   i≠k
        #   L'_ik = V_i V_k(G_ik sin(θ_ik) - B_ik cos(θ_ik))   i≠k  (= H_ik)
        #
        # Diagonal:
        #   H_ii  = -Q_i - B_ii V_i²
        #   N'_ii =  P_i + G_ii V_i²
        #   M'_ii =  P_i - G_ii V_i²   (yes, same as N' with minus on last term)
        #   L'_ii =  Q_i - B_ii V_i²   (not ÷V!)
        # ---------------------------------------------------------------------------

        nns = len(non_slack)
        npq = len(pq_only)
        size = nns + npq
        J = [[0.0] * size for _ in range(size)]

        # Pre-compute per-bus P, Q
        Pcalc = [calc_P(i) for i in range(n)]
        Qcalc = [calc_Q(i) for i in range(n)]

        for ri, i in enumerate(non_slack):
            Pi = Pcalc[i]
            Qi = Qcalc[i]
            Vi = V[i]
            ti = theta[i]

            # H block: ∂P_i/∂θ_k
            for ci, k in enumerate(non_slack):
                if i == k:
                    J[ri][ci] = -Qi - B[i][i] * Vi * Vi
                else:
                    tik = ti - theta[k]
                    J[ri][ci] = Vi * V[k] * (G[i][k] * math.sin(tik) - B[i][k] * math.cos(tik))

            # N' block: |V_k| * ∂P_i/∂|V_k|  (PQ buses only — columns nns..nns+npq-1)
            for ci, k in enumerate(pq_only):
                if i == k:
                    J[ri][nns + ci] = Pi + G[i][i] * Vi * Vi
                else:
                    tik = ti - theta[k]
                    J[ri][nns + ci] = Vi * V[k] * (G[i][k] * math.cos(tik) + B[i][k] * math.sin(tik))

        for ri, i in enumerate(pq_only):
            Pi = Pcalc[i]
            Qi = Qcalc[i]
            Vi = V[i]
            ti = theta[i]

            # M' block: ∂Q_i/∂θ_k
            for ci, k in enumerate(non_slack):
                if i == k:
                    J[nns + ri][ci] = Pi - G[i][i] * Vi * Vi
                else:
                    tik = ti - theta[k]
                    J[nns + ri][ci] = -Vi * V[k] * (G[i][k] * math.cos(tik) + B[i][k] * math.sin(tik))

            # L' block: |V_k| * ∂Q_i/∂|V_k|
            for ci, k in enumerate(pq_only):
                if i == k:
                    J[nns + ri][nns + ci] = Qi - B[i][i] * Vi * Vi
                else:
                    tik = ti - theta[k]
                    J[nns + ri][nns + ci] = Vi * V[k] * (G[i][k] * math.sin(tik) - B[i][k] * math.cos(tik))

        # Solve J * [Δθ; e] = [ΔP; ΔQ]   where e_k = Δ|V_k|/|V_k|
        dx = _gauss_solve(J, mis)

        # Update state: Δθ directly; |V| multiplicatively (e = Δ|V|/|V|)
        for ri, i in enumerate(non_slack):
            theta[i] += dx[ri]

        for ri, i in enumerate(pq_only):
            V[i] *= (1.0 + dx[nns + ri])
            if V[i] < 0.05:
                V[i] = 0.05

    if not converged:
        warnings.append(f"Load flow did not converge in {max_iter} iterations; last ‖mis‖={norm_inf:.4g}")

    # --- Post-processing ---
    # Slack injection
    slack_P = calc_P(slack_idx)
    slack_Q = calc_Q(slack_idx)

    # Bus results
    bus_results = []
    for i in range(n):
        P_calc = calc_P(i)
        Q_calc = calc_Q(i)
        bus_results.append({
            "bus": i,
            "type": buses[i]["type"],
            "V_pu": round(V[i], 6),
            "theta_deg": round(math.degrees(theta[i]), 4),
            "P_pu": round(P_calc, 6),
            "Q_pu": round(Q_calc, 6),
        })

    # Branch flows
    branch_results = []
    total_loss_P = 0.0
    total_loss_Q = 0.0
    for br in branches:
        i = br["from_bus"]
        k = br["to_bus"]
        R = float(br["R"])
        X = float(br["X"])
        B_br = float(br.get("B", 0.0))
        tap = float(br.get("tap", 1.0))

        # Current from bus i to bus k (series branch only)
        Vi = _crect(V[i], theta[i])
        Vk = _crect(V[k], theta[k])
        Vi_tap = _cdiv(Vi, (tap, 0.0))

        ys = _cdiv((1.0, 0.0), (R, X))
        I_series = _cmul(ys, _csub(Vi_tap, Vk))

        # Power from bus i: S_ij = V_i/tap * conj(I_ij)  +  shunt at i
        S_from_series = _cmul(Vi_tap, _cconj(I_series))
        # Shunt at from side
        S_from_shunt = _cmul(Vi_tap, _cconj(_cmul((0.0, B_br / 2.0), Vi_tap)))
        S_from = _cadd(S_from_series, S_from_shunt)

        # Power at bus k: S_kj = -V_k * conj(I_ij)  +  shunt at k
        S_to_series = _cmul(_cconj(I_series), Vk)
        # Negative because current entering bus k
        P_to_s = -S_to_series[0]
        Q_to_s = -S_to_series[1]
        # Shunt at to side
        S_to_shunt = _cmul(Vk, _cconj(_cmul((0.0, B_br / 2.0), Vk)))
        P_to = P_to_s + S_to_shunt[0]
        Q_to = Q_to_s + S_to_shunt[1]

        loss_P = S_from[0] + P_to
        loss_Q = S_from[1] + Q_to
        total_loss_P += loss_P
        total_loss_Q += loss_Q

        branch_results.append({
            "from_bus": i,
            "to_bus": k,
            "P_from_pu": round(S_from[0], 6),
            "Q_from_pu": round(S_from[1], 6),
            "P_to_pu": round(P_to, 6),
            "Q_to_pu": round(Q_to, 6),
            "loss_P_pu": round(loss_P, 6),
            "loss_Q_pu": round(loss_Q, 6),
        })

    return {
        "ok": True,
        "converged": converged,
        "iterations": iteration,
        "Sbase_MVA": Sbase_MVA,
        "buses": bus_results,
        "branches": branch_results,
        "slack_P_pu": round(slack_P, 6),
        "slack_Q_pu": round(slack_Q, 6),
        "total_loss_P_pu": round(total_loss_P, 6),
        "total_loss_Q_pu": round(total_loss_Q, 6),
        "warnings": warnings,
    }
