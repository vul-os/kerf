"""
Standard two-equation k-ε turbulence model with wall functions.

Model formulation
-----------------
The standard k-ε model (Launder & Spalding 1974) solves two additional
transport equations alongside the RANS momentum equation.

For fully-developed 1-D channel flow the equations reduce to:

    d/dy [(ν + ν_t) dU/dy] = dp/dx                         (momentum)
    d/dy [(ν + ν_t/σ_k) dk/dy] + P_k − ε = 0              (k)
    d/dy [(ν + ν_t/σ_ε) dε/dy] + C_1ε ε/k P_k − C_2ε ε²/k = 0  (ε)

Turbulent viscosity:

    ν_t = C_μ k²/ε

Production of k (1-D shear):

    P_k = ν_t (dU/dy)²

Standard model constants:
    C_μ  = 0.09
    C_1ε = 1.44
    C_2ε = 1.92
    σ_k  = 1.0
    σ_ε  = 1.3

Wall functions (log-law)
------------------------
The log-law of the wall:

    u+ = (1/κ) ln(y+) + B     for y+ ≳ 30 (log-layer)

with κ = 0.41 (von Kármán constant), B = 5.5 (smooth-wall constant).

At the first cell adjacent to the wall, equilibrium wall functions set:

    U_P  = u_τ [(1/κ) ln(y+_P) + B]
    ε_P  = u_τ³ / (κ y_P)
    k_P  = u_τ² / √C_μ

Channel-flow reference oracle
------------------------------
Fully-developed turbulent channel flow at Re_τ = 395 (bulk Re ≈ 10 000).

The analytic reference is the law-of-the-wall in the log-layer:

    u+(y+) = (1/κ) ln(y+) + B,   y+ ∈ [30, 300]
             κ = 0.41,  B = 5.5

References
----------
[LS74]        Launder B. E., Spalding D. B., Comput. Methods Appl. Mech. Eng.
              3 (1974) 269-289.
[Pope]        Pope S. B., Turbulent Flows, Cambridge UP (2000), §7.1.
[Schlichting] Schlichting H., Boundary-Layer Theory, 8th ed., §17.2.
[Versteeg]    Versteeg H. K., Malalasekera W., An Introduction to Computational
              Fluid Dynamics, 2nd ed. (2007), Chapter 3.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Model constants  [LS74; Versteeg §3.5]
# ---------------------------------------------------------------------------

C_MU:    float = 0.09    # C_μ
C_1E:    float = 1.44    # C_1ε
C_2E:    float = 1.92    # C_2ε
SIGMA_K: float = 1.0     # σ_k
SIGMA_E: float = 1.3     # σ_ε

KAPPA:   float = 0.41    # von Kármán constant          [Pope §7.1]
B_WALL:  float = 5.5     # log-law intercept, smooth wall [Pope §7.1]

C_MU_025: float = C_MU ** 0.25   # C_μ^(1/4)
C_MU_075: float = C_MU ** 0.75   # C_μ^(3/4)


# ---------------------------------------------------------------------------
# Thomas algorithm — tridiagonal solve
# ---------------------------------------------------------------------------

def _tdma(a: list, b: list, c: list, d: list) -> list:
    """
    Solve a tridiagonal system Ax = d using the Thomas (TDMA) algorithm.

    a[i] : sub-diagonal  (a[0] unused)
    b[i] : main diagonal
    c[i] : super-diagonal (c[N-1] unused)
    d[i] : right-hand side
    """
    N = len(b)
    c_ = [0.0] * N
    d_ = [0.0] * N
    x  = [0.0] * N

    c_[0] = c[0] / b[0]
    d_[0] = d[0] / b[0]

    for i in range(1, N):
        denom = b[i] - a[i] * c_[i - 1]
        if abs(denom) < 1e-300:
            denom = 1e-300
        c_[i] = c[i] / denom
        d_[i] = (d[i] - a[i] * d_[i - 1]) / denom

    x[N - 1] = d_[N - 1]
    for i in range(N - 2, -1, -1):
        x[i] = d_[i] - c_[i] * x[i + 1]

    return x


# ---------------------------------------------------------------------------
# Analytic wall-law oracle
# ---------------------------------------------------------------------------

def log_law_uplus(y_plus: float) -> float:
    """
    Return u+ from the log-law of the wall.

    u+ = (1/κ) ln(y+) + B

    Valid in the log-layer (y+ ≈ 30–300). [Pope §7.1; Schlichting §17.2]

    Parameters
    ----------
    y_plus : dimensionless wall distance  y+ = u_τ y / ν

    Returns
    -------
    u+ = U / u_τ
    """
    if y_plus <= 0.0:
        return 0.0
    return (1.0 / KAPPA) * math.log(y_plus) + B_WALL


def channel_flow_oracle(
    Re_tau: float = 395.0,
    n_points: int = 20,
) -> dict[str, Any]:
    """
    Analytic (log-law) oracle for fully-developed turbulent channel flow.

    Returns y+ and u+ values in the log-layer for use as a reference
    against which the k-ε solver is validated.

    Parameters
    ----------
    Re_tau  : friction Reynolds number  Re_τ = u_τ h / ν
              Default 395 → bulk Re ≈ 10 000.
    n_points: number of log-spaced y+ stations in [30, min(0.2*Re_tau, 300)]

    Returns
    -------
    dict with keys:
        ok        : True
        Re_tau    : Re_τ as given
        y_plus    : list of n_points y+ values (log-spaced, log-layer)
        u_plus    : list of corresponding u+ = (1/κ) ln(y+) + B
        kappa     : κ = 0.41
        B         : B = 5.5
        source    : citation string
    """
    if Re_tau <= 0.0:
        return {"ok": False, "reason": "Re_tau must be positive"}
    if n_points < 2:
        return {"ok": False, "reason": "n_points must be >= 2"}

    y_plus_max = min(0.2 * Re_tau, 300.0)
    y_plus_min = 30.0
    if y_plus_min >= y_plus_max:
        return {
            "ok": False,
            "reason": "Re_tau too small for a log-layer (need Re_tau >= 150)",
        }

    log_min = math.log(y_plus_min)
    log_max = math.log(y_plus_max)
    y_plus_out = []
    u_plus_out = []
    for i in range(n_points):
        t = i / (n_points - 1)
        yp = math.exp(log_min + t * (log_max - log_min))
        y_plus_out.append(yp)
        u_plus_out.append(log_law_uplus(yp))

    return {
        "ok": True,
        "Re_tau": Re_tau,
        "y_plus": y_plus_out,
        "u_plus": u_plus_out,
        "kappa": KAPPA,
        "B": B_WALL,
        "source": (
            "Pope S. B., Turbulent Flows, Cambridge UP (2000), §7.1; "
            "Schlichting H., Boundary-Layer Theory, 8th ed., §17.2"
        ),
    }


# ---------------------------------------------------------------------------
# 1-D wall-normal k-ε solver (channel-flow column model)
# ---------------------------------------------------------------------------

def solve_channel_ke(
    Re_tau: float = 395.0,
    n_cells: int = 60,
    max_iter: int = 3000,
    tol: float = 1e-6,
    h: float = 1.0,
    nu: float = None,
) -> dict[str, Any]:
    """
    Solve the 1-D fully-developed turbulent channel-flow k-ε problem.

    Domain: y ∈ [0, h], wall at y=0, symmetry at y=h (half-channel).

    The mean streamwise velocity U(y) satisfies the momentum equation
    driven by a constant streamwise pressure gradient:

        d/dy [(ν + ν_t) dU/dy] + u_τ²/h = 0

    k-ε equations are solved in the interior (y > y_wall_bc); the
    wall-adjacent cell uses equilibrium wall functions.

    Discretisation
    --------------
    Finite-volume on a 1-D wall-normal grid with power-law stretching
    (fine near wall, coarse near centre).  Each equation is cast in
    tridiagonal form and solved with TDMA at each outer iteration.

    Wall-function BCs at node i=0 (closest to wall)
    ------------------------------------------------
        y+_P = u_τ y_P / ν
        U_P  = u_τ [(1/κ) ln(y+_P) + B]     (log-law)
        k_P  = u_τ² / √C_μ                   (equilibrium)
        ε_P  = C_μ^(3/4) k_P^(3/2) / (κ y_P) (local equilibrium)

    Symmetry BCs at node i=N-1 (channel centre)
    --------------------------------------------
        dU/dy = dk/dy = dε/dy = 0  (zero-gradient)

    Parameters
    ----------
    Re_tau  : friction Reynolds number u_τ h / ν  (default 395)
    n_cells : number of cells in wall-normal direction  (default 60)
    max_iter: maximum outer iterations
    tol     : convergence tolerance on max |ΔU| between sweeps
    h       : half-channel height (default 1.0)
    nu      : kinematic viscosity; if None, derived so that u_τ = 1.

    Returns
    -------
    dict with keys:
        ok        : True / False
        y         : list of cell-centre positions [m]
        y_plus    : list of y+ = u_τ y / ν
        U         : list of mean streamwise velocity [m/s]
        u_plus    : list of u+ = U / u_τ
        k         : list of turbulent kinetic energy [m²/s²]
        epsilon   : list of turbulent dissipation rate [m²/s³]
        nu_t      : list of turbulent viscosity [m²/s]
        u_tau     : friction velocity [m/s]
        Re_tau    : Re_τ used
        converged : bool
        iterations: int
    """
    if Re_tau <= 0.0:
        return {"ok": False, "reason": "Re_tau must be positive"}
    if n_cells < 5:
        return {"ok": False, "reason": "n_cells must be >= 5"}

    # ---- friction velocity and viscosity ---------------------------------
    u_tau = 1.0
    if nu is None:
        nu = u_tau * h / Re_tau

    # ---- mesh: power-law stretching toward wall --------------------------
    # y_face[i] = h * (i/N)^alpha,  alpha < 1 clusters near wall
    alpha = 0.65
    N = n_cells
    yf = [h * ((i / N) ** alpha) for i in range(N + 1)]
    yc = [0.5 * (yf[i] + yf[i + 1]) for i in range(N)]
    dy = [yf[i + 1] - yf[i] for i in range(N)]

    # Inter-node distances for diffusion coefficients
    # dist[i] = yc[i+1] - yc[i]  for i in 0..N-2
    dist = [yc[i + 1] - yc[i] for i in range(N - 1)]

    # ---- wall-function boundary values ----------------------------------
    yp_1 = u_tau * yc[0] / nu           # y+ at first cell centre
    yp_1 = max(yp_1, 11.63)             # clamp: below y+=11 viscous sublayer
    U_wf  = u_tau * log_law_uplus(yp_1) # wall-function velocity
    k_wf  = u_tau * u_tau / math.sqrt(C_MU)
    eps_wf = C_MU_075 * k_wf ** 1.5 / (KAPPA * max(yc[0], 1e-30))

    # Driving pressure gradient: τ_w = u_τ² → dp/dx = -u_τ²/h
    src_U = u_tau * u_tau / h

    # ---- initialise fields ----------------------------------------------
    U   = [U_wf * (1.0 - 0.2 * abs(yc[i] / h - 1.0)) for i in range(N)]
    k   = [k_wf for _ in range(N)]
    eps = [eps_wf for _ in range(N)]
    # Initialise ε with distance-based equilibrium profile
    for i in range(N):
        y_loc = max(yc[i], nu / u_tau)
        eps[i] = max(C_MU_075 * k[i] ** 1.5 / (KAPPA * y_loc), 1e-12)

    converged = False
    omega = 0.7   # under-relaxation

    for iteration in range(max_iter):
        U_old = list(U)

        # ---- turbulent viscosity -----------------------------------------
        nut = [C_MU * k[i] * k[i] / max(eps[i], 1e-20) for i in range(N)]

        # ================================================================
        # Solve U  (tridiagonal, Dirichlet at i=0, Neumann at i=N-1)
        # ================================================================
        # Interior nodes: i = 1 .. N-2
        # Boundary:  U[0] = U_wf  (Dirichlet)
        #            dU/dy|_{N-1} = 0  → U[N-1] = U[N-2]  (Neumann)
        # We solve only i = 1 .. N-2 (N-2 unknowns)

        M = N - 2   # interior nodes: indices 1..N-2
        if M > 0:
            a_U = [0.0] * M
            b_U = [0.0] * M
            c_U = [0.0] * M
            d_U = [0.0] * M

            for idx in range(M):
                i = idx + 1
                nu_e = 0.5 * ((nut[i] + nu) + (nut[i + 1] + nu))
                nu_w = 0.5 * ((nut[i] + nu) + (nut[i - 1] + nu))
                ae = nu_e / dist[i]        # i+1 side (dist[i] = yc[i+1]-yc[i])
                aw = nu_w / dist[i - 1]    # i-1 side
                ap = ae + aw
                rhs = src_U * dy[i]

                a_U[idx] = -aw
                b_U[idx] =  ap
                c_U[idx] = -ae
                d_U[idx] = rhs

                # Adjust for Dirichlet BC at left boundary
                if i == 1:
                    d_U[idx] += aw * U_wf

                # Adjust for Neumann BC at right boundary (U[N-1]=U[N-2])
                if i == N - 2:
                    # c * U[N-1] = c * U[N-2] → subtract c from b
                    b_U[idx] -= ae

            U_int = _tdma(a_U, b_U, c_U, d_U)
            for idx in range(M):
                i = idx + 1
                U[i] = omega * U_int[idx] + (1.0 - omega) * U_old[i]

        U[0]     = U_wf
        U[N - 1] = U[N - 2]

        # ================================================================
        # Solve k  (tridiagonal, Dirichlet at i=0, Neumann at i=N-1)
        # ================================================================
        if M > 0:
            a_k = [0.0] * M
            b_k = [0.0] * M
            c_k = [0.0] * M
            d_k = [0.0] * M

            for idx in range(M):
                i = idx + 1
                nu_e = 0.5 * ((nu + nut[i] / SIGMA_K) + (nu + nut[i + 1] / SIGMA_K))
                nu_w = 0.5 * ((nu + nut[i] / SIGMA_K) + (nu + nut[i - 1] / SIGMA_K))
                ae = nu_e / dist[i]
                aw = nu_w / dist[i - 1]

                # Production
                if i < N - 1:
                    dUdy = (U[i + 1] - U[i - 1]) / (yc[i + 1] - yc[i - 1])
                else:
                    dUdy = 0.0
                Pk = nut[i] * dUdy * dUdy

                # Linearise destruction: treat ε as source implicitly
                # -ε dy → treated as -ε/k * k → sp = -ε/k (implicit in k)
                sp = -eps[i] / max(k[i], 1e-15) * dy[i]
                sc = Pk * dy[i]

                ap = ae + aw - sp
                rhs = sc

                a_k[idx] = -aw
                b_k[idx] =  ap
                c_k[idx] = -ae
                d_k[idx] = rhs

                if i == 1:
                    d_k[idx] += aw * k_wf
                if i == N - 2:
                    b_k[idx] -= ae

            k_int = _tdma(a_k, b_k, c_k, d_k)
            for idx in range(M):
                i = idx + 1
                k[i] = max(omega * k_int[idx] + (1.0 - omega) * k[i], 1e-12)

        k[0]     = k_wf
        k[N - 1] = k[N - 2]

        # ================================================================
        # Solve ε  (tridiagonal, Dirichlet at i=0, Neumann at i=N-1)
        # ================================================================
        if M > 0:
            a_e = [0.0] * M
            b_e = [0.0] * M
            c_e = [0.0] * M
            d_e = [0.0] * M

            for idx in range(M):
                i = idx + 1
                nu_e = 0.5 * ((nu + nut[i] / SIGMA_E) + (nu + nut[i + 1] / SIGMA_E))
                nu_w = 0.5 * ((nu + nut[i] / SIGMA_E) + (nu + nut[i - 1] / SIGMA_E))
                ae = nu_e / dist[i]
                aw = nu_w / dist[i - 1]

                if i < N - 1:
                    dUdy = (U[i + 1] - U[i - 1]) / (yc[i + 1] - yc[i - 1])
                else:
                    dUdy = 0.0
                Pk_i = nut[i] * dUdy * dUdy

                k_safe  = max(k[i], 1e-15)
                eps_safe = max(eps[i], 1e-15)

                # Linearise C_2ε ε²/k → sp = -C_2ε ε/k (implicit in ε)
                sp = -C_2E * eps_safe / k_safe * dy[i]
                sc = C_1E * (eps_safe / k_safe) * Pk_i * dy[i]

                ap = ae + aw - sp
                rhs = sc

                a_e[idx] = -aw
                b_e[idx] =  ap
                c_e[idx] = -ae
                d_e[idx] = rhs

                if i == 1:
                    d_e[idx] += aw * eps_wf
                if i == N - 2:
                    b_e[idx] -= ae

            eps_int = _tdma(a_e, b_e, c_e, d_e)
            for idx in range(M):
                i = idx + 1
                eps[i] = max(omega * eps_int[idx] + (1.0 - omega) * eps[i], 1e-12)

        # Wall-BC ε recomputed each iteration from current k
        eps[0]     = C_MU_075 * k[0] ** 1.5 / (KAPPA * max(yc[0], 1e-30))
        eps[N - 1] = eps[N - 2]

        # ---- convergence check ------------------------------------------
        res = max(abs(U[i] - U_old[i]) for i in range(N))
        if res < tol:
            converged = True
            break

    # ---- output ----------------------------------------------------------
    nut_final  = [C_MU * k[i] * k[i] / max(eps[i], 1e-20) for i in range(N)]
    y_plus_out = [u_tau * yc[i] / nu for i in range(N)]
    u_plus_out = [U[i] / u_tau for i in range(N)]

    return {
        "ok": True,
        "y": list(yc),
        "y_plus": y_plus_out,
        "U": list(U),
        "u_plus": u_plus_out,
        "k": list(k),
        "epsilon": list(eps),
        "nu_t": nut_final,
        "u_tau": u_tau,
        "Re_tau": Re_tau,
        "converged": converged,
        "iterations": iteration + 1,
    }


# ---------------------------------------------------------------------------
# Validation helper — compare solver to log-law oracle
# ---------------------------------------------------------------------------

def validate_log_law_fit(
    solver_result: dict[str, Any],
    y_plus_min: float = 30.0,
    y_plus_max: float = 300.0,
    tol_fraction: float = 0.05,
) -> dict[str, Any]:
    """
    Compare k-ε solver u+ profile to the log-law oracle in the log-layer.

    For each solver point with y+ ∈ [y_plus_min, y_plus_max], compute
    the relative deviation from the log-law:

        δ = |u+_solver − u+_oracle| / u+_oracle

    Report the maximum δ and whether it is within tol_fraction (5 %).

    Returns
    -------
    dict with keys:
        ok            : True if validation passes (all points within tol)
        n_log_points  : number of solver points in log-layer
        max_rel_error : maximum relative error in log-layer
        tol_fraction  : tolerance used
        pass_5pct     : bool (max_rel_error <= tol_fraction)
        details       : list of {y_plus, u_plus_solver, u_plus_oracle, rel_err}
    """
    if not solver_result.get("ok"):
        return {"ok": False, "reason": "solver result not ok"}

    y_plus = solver_result["y_plus"]
    u_plus = solver_result["u_plus"]

    details = []
    for yp, up in zip(y_plus, u_plus):
        if y_plus_min <= yp <= y_plus_max:
            up_oracle = log_law_uplus(yp)
            if up_oracle > 0.0:
                rel_err = abs(up - up_oracle) / up_oracle
            else:
                rel_err = abs(up - up_oracle)
            details.append({
                "y_plus": yp,
                "u_plus_solver": up,
                "u_plus_oracle": up_oracle,
                "rel_err": rel_err,
            })

    if not details:
        return {
            "ok": False,
            "reason": (
                "No solver points found in log-layer range "
                "y+ ∈ [{}, {}]".format(y_plus_min, y_plus_max)
            ),
        }

    max_rel_err = max(d["rel_err"] for d in details)
    passes = max_rel_err <= tol_fraction

    return {
        "ok": passes,
        "n_log_points": len(details),
        "max_rel_error": max_rel_err,
        "tol_fraction": tol_fraction,
        "pass_5pct": passes,
        "details": details,
    }
