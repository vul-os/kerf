"""
kerf_systems.solver.dae
========================

DAE / ODE integrator for 1D lumped-element systems.

Primary solver: ``solve_system``
---------------------------------
Uses ``scipy.integrate.solve_ivp`` with ``method='BDF'`` for stiff index-1
DAEs that have been reduced to semi-explicit ODE form, and a custom
Newton-BDF-1 fallback for fully implicit DAE F(t, x, dx) = 0.

Architecture
------------
Two integration paths are available:

1. **ODE path** (preferred):
   If the residual ``F(t, x, dx)`` can be written in the form
   ``dx = f(t, x)`` (i.e. the Jacobian w.r.t. dx is the identity), the system
   is automatically recognised as an explicit ODE and handed to scipy's BDF
   solver directly.  This gives adaptive step-size, error control, and event
   detection.

2. **Implicit DAE path** (fallback):
   For fully implicit F(t, x, dx) = 0, a custom BDF-1 (backward Euler)
   Newton iteration is used with fixed step size h.  This handles index-1
   systems.  For index > 1 the user must apply dummy-derivative substitution
   or Pantelides reduction before calling this solver (documented in parser).

Higher-index notes
------------------
scipy's ``solve_ivp`` does not natively solve index > 1 DAEs.  Index-2 and
higher systems must be reduced to index 0 or 1 before use.  Known limits:

- Index 1 (e.g. RC circuit, thermal network): supported natively.
- Index 2 (e.g. rigid-body velocity constraints): must manually differentiate
  the constraint once.
- Index 3 (e.g. position-level rigid constraints): must use Baumgarte
  stabilisation or coordinate partitioning externally.

Public API::

    result = solve_system(F, t_span, x0, dx0=None, h=None, tol=1e-6)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
from scipy.integrate import solve_ivp


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    """Time-domain simulation result."""
    t: list[float]          # time points [s]
    x: list[list[float]]    # state trajectories: x[step][var_idx]
    converged: bool = True
    warnings: list[str] = field(default_factory=list)
    method: str = "BDF"


# ---------------------------------------------------------------------------
# Newton solve (internal — used for implicit DAE path)
# ---------------------------------------------------------------------------

def _newton_solve(
    F: Callable[[list[float]], list[float]],
    x0: list[float],
    tol: float = 1e-10,
    max_iter: int = 50,
) -> tuple[list[float], bool]:
    """Newton-Raphson with finite-difference Jacobian and backtracking."""
    x = list(x0)
    n = len(x)
    eps = 1e-8

    for _it in range(max_iter):
        fx = F(x)
        res_norm = math.sqrt(sum(fi * fi for fi in fx))
        if res_norm <= tol:
            return x, True

        # Forward finite-difference Jacobian
        J = [[0.0] * n for _ in range(n)]
        for j in range(n):
            xp = list(x)
            xp[j] += eps
            fxp = F(xp)
            for i in range(n):
                J[i][j] = (fxp[i] - fx[i]) / eps

        # Solve J*delta = -fx via numpy
        try:
            Jnp = np.array(J, dtype=float)
            b = np.array([-fi for fi in fx], dtype=float)
            delta = np.linalg.solve(Jnp, b).tolist()
        except np.linalg.LinAlgError:
            return x, False

        # Backtracking line search
        step = 1.0
        for _ in range(10):
            x_new = [x[i] + step * delta[i] for i in range(n)]
            norm_new = math.sqrt(sum(fi * fi for fi in F(x_new)))
            if norm_new < res_norm:
                break
            step *= 0.5

        x = [x[i] + step * delta[i] for i in range(n)]

    fx = F(x)
    res_norm = math.sqrt(sum(fi * fi for fi in fx))
    return x, res_norm <= tol * 1e3


# ---------------------------------------------------------------------------
# Implicit DAE BDF-1 fallback
# ---------------------------------------------------------------------------

def _solve_implicit_dae(
    F: Callable[[float, list[float], list[float]], list[float]],
    t_span: tuple[float, float],
    x0: list[float],
    dx0: list[float],
    h: float,
    tol: float = 1e-8,
) -> SimResult:
    """
    Fixed-step BDF-1 (backward Euler) for fully implicit index-1 DAEs.

    F(t, x, dx) = 0  →  at each step: F(t_new, x_new, (x_new-x_old)/h) = 0
    """
    t0, t_end = t_span
    t = t0
    x = list(x0)
    n = len(x)
    t_hist = [t]
    x_hist = [list(x)]
    warnings: list[str] = []
    converged = True

    while t < t_end - 1e-14 * abs(t_end):
        t_new = min(t + h, t_end)
        h_eff = t_new - t
        if h_eff < h * 1e-10:
            t = t_new
            t_hist.append(t)
            x_hist.append(list(x))
            break
        x_old = list(x)

        def _res(x_new: list[float]) -> list[float]:
            dx_new = [(x_new[i] - x_old[i]) / h_eff for i in range(n)]
            return F(t_new, x_new, dx_new)

        x_new, ok = _newton_solve(_res, x, tol=tol)
        if not ok:
            warnings.append(f"Newton not converged at t={t_new:.6g}")
            converged = False

        x = x_new
        t = t_new
        t_hist.append(t)
        x_hist.append(list(x))

    return SimResult(t=t_hist, x=x_hist, converged=converged,
                     warnings=warnings, method="BDF-1-Newton")


# ---------------------------------------------------------------------------
# ODE detection
# ---------------------------------------------------------------------------

def _try_explicit_form(
    F: Callable[[float, list[float], list[float]], list[float]],
    n: int,
    x0: list[float],
    t0: float,
    tol: float = 1e-8,
) -> Callable[[float, list[float]], list[float]] | None:
    """
    Try to convert F(t, x, dx) = 0 to explicit form dx/dt = f(t, x).

    Strategy:
    1. Compute J_dx = dF/d(dx) at (t0, x0, 0) via finite differences.
    2. If J_dx is invertible (all singular values > threshold), then the system
       is a semi-explicit ODE:  dx = -inv(J_dx) * F(t, x, 0)
    3. If J_dx is singular, the system is a true DAE — return None.

    Returns an explicit f(t, x) callable if successful, else None.
    """
    eps = 1e-6
    dx0_probe = [0.0] * n
    try:
        f0 = F(t0, x0, dx0_probe)
    except Exception:
        return None

    # Compute Jacobian of F w.r.t. dx
    J_rows = [[0.0] * n for _ in range(n)]
    for j in range(n):
        dx_probe = [0.0] * n
        dx_probe[j] = eps
        try:
            fj = F(t0, x0, dx_probe)
        except Exception:
            return None
        for i in range(n):
            J_rows[i][j] = (fj[i] - f0[i]) / eps

    # Check invertibility via numpy
    try:
        J_np = np.array(J_rows, dtype=float)
        cond = np.linalg.cond(J_np)
        if cond > 1e10:
            return None  # singular / near-singular → true DAE
        J_inv = np.linalg.inv(J_np)
    except np.linalg.LinAlgError:
        return None

    # Semi-explicit ODE: dx = -J_inv * F(t, x, 0)
    J_inv_list = J_inv.tolist()

    def f_explicit(t: float, x: list[float]) -> list[float]:
        f_val = F(t, list(x), [0.0] * n)
        result = [0.0] * n
        for i in range(n):
            result[i] = -sum(J_inv_list[i][j] * f_val[j] for j in range(n))
        return result

    return f_explicit


# ---------------------------------------------------------------------------
# Public: solve_system
# ---------------------------------------------------------------------------

def solve_system(
    F: Callable[[float, list[float], list[float]], list[float]],
    t_span: tuple[float, float],
    x0: list[float],
    dx0: list[float] | None = None,
    h: float | None = None,
    tol: float = 1e-10,
    rtol: float = 1e-8,
    atol: float = 1e-10,
    t_eval: list[float] | None = None,
    max_step: float = float("inf"),
) -> SimResult:
    """
    Solve a DAE / ODE system  F(t, x, dx) = 0.

    Parameters
    ----------
    F : callable(t, x, dx) -> list[float]
        Residual vector.  len(F) == len(x).
    t_span : (t0, t_end)
    x0 : list[float]
        Initial state.
    dx0 : list[float] or None
        Initial derivatives.  If None, zeros are used.
    h : float or None
        Fixed time step for implicit fallback.  If None: auto (t_end/2000).
    tol : float
        Newton convergence tolerance for implicit path.
    rtol, atol : float
        Relative and absolute tolerances for scipy BDF solver.
    t_eval : list[float] or None
        Specific times at which to return the solution.
    max_step : float
        Maximum step size for scipy solver.

    Returns
    -------
    SimResult

    Integration strategy
    --------------------
    1. Try to detect explicit ODE form F(t,x,dx)=dx-g(t,x); use scipy BDF.
    2. Fall back to fixed-step Newton-BDF-1 for fully implicit DAE.

    Higher-index systems
    --------------------
    For index > 1 the user must differentiate algebraic constraints before
    calling this function.  See ``kerf_systems.parser`` module docstring.
    """
    n = len(x0)
    if dx0 is None:
        dx0 = [0.0] * n
    t0, t_end = t_span

    # Path 1: try explicit ODE
    f_explicit = _try_explicit_form(F, n, x0, t0)
    if f_explicit is not None:
        def _f_scipy(t: float, y):
            return f_explicit(t, list(y))

        dense = t_eval is not None
        sol = solve_ivp(
            _f_scipy,
            t_span,
            x0,
            method="BDF",
            rtol=rtol,
            atol=atol,
            t_eval=t_eval,
            max_step=max_step,
            dense_output=False,
        )
        t_arr = sol.t.tolist()
        x_arr = [sol.y[:, k].tolist() for k in range(len(t_arr))]
        converged = sol.success
        warnings = [] if sol.success else [sol.message]
        return SimResult(t=t_arr, x=x_arr, converged=converged,
                         warnings=warnings, method="scipy-BDF")

    # Path 2: implicit BDF-1 Newton fallback
    h_step = h if h is not None else (t_end - t0) / 2000
    return _solve_implicit_dae(F, t_span, x0, dx0, h_step, tol=tol)
