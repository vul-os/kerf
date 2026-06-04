"""
kerf_cad_core.controls.state_space — State-space representation with
controllability, observability, pole placement and LQR synthesis.

Public API
----------
StateSpace         — A, B, C, D dataclass with to_transfer_function()
is_controllable    — rank test on [B, AB, ..., A^{n-1}B]
is_observable      — rank test on [C; CA; ...; CA^{n-1}]
place_poles        — Ackermann (1972) SISO pole placement → K
lqr                — continuous ARE (Kleinman iteration) → (K, P)

All pure Python + numpy.  No scipy.

References
----------
Kailath, T. (1980). "Linear Systems." Prentice-Hall.
Ackermann, J. (1972). "Der Entwurf linearer Regelungssysteme im
    Zustandsraum." Regelungstechnik 7, 297–300.
Anderson, B.D.O. & Moore, J.B. (2007). "Optimal Control: Linear
    Quadratic Methods." Dover.
Ogata, K. (2010). "Modern Control Engineering", 5th ed. Pearson.

Author: imranparuk
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from kerf_cad_core.controls.transfer_function import TransferFunction


# ---------------------------------------------------------------------------
# StateSpace dataclass
# ---------------------------------------------------------------------------

@dataclass
class StateSpace:
    """
    Continuous-time state-space model:
        ẋ = A·x + B·u
        y = C·x + D·u

    Parameters
    ----------
    A : n×n state matrix (numpy array or list-of-lists)
    B : n×p input matrix
    C : q×n output matrix
    D : q×p feedthrough matrix

    References: Kailath (1980) §1; Ogata (2010) §10.
    """
    A: np.ndarray
    B: np.ndarray
    C: np.ndarray
    D: np.ndarray

    def __post_init__(self) -> None:
        self.A = np.atleast_2d(np.asarray(self.A, dtype=float))
        self.B = np.atleast_2d(np.asarray(self.B, dtype=float))
        self.C = np.atleast_2d(np.asarray(self.C, dtype=float))
        self.D = np.atleast_2d(np.asarray(self.D, dtype=float))

        n = self.A.shape[0]
        if self.A.shape != (n, n):
            raise ValueError(f"A must be square (n×n), got {self.A.shape}")
        if self.B.shape[0] != n:
            raise ValueError(f"B must have {n} rows, got {self.B.shape[0]}")
        q = self.C.shape[0]
        if self.C.shape[1] != n:
            raise ValueError(f"C must have {n} columns, got {self.C.shape[1]}")
        p = self.B.shape[1]
        if self.D.shape != (q, p):
            raise ValueError(f"D must be ({q}×{p}), got {self.D.shape}")

    # -- Conversion --------------------------------------------------------

    def to_transfer_function(self) -> "TransferFunction":
        """
        Convert SISO state-space to transfer function.

        G(s) = C·(sI - A)^{-1}·B + D

        For SISO systems (p=1, q=1), the result is a scalar rational function.
        Uses the characteristic polynomial of A for the denominator and
        the adjugate formula for numerator computation.

        References: Kailath (1980) §2.4; Ogata (2010) §10-3.
        """
        from kerf_cad_core.controls.transfer_function import TransferFunction

        n = self.A.shape[0]
        p = self.B.shape[1]
        q = self.C.shape[0]

        if p != 1 or q != 1:
            raise NotImplementedError(
                "to_transfer_function() supports SISO only (p=1, q=1). "
                f"Got p={p}, q={q}."
            )

        # Denominator = characteristic polynomial of A = det(sI - A)
        den = _char_poly_numpy(self.A)

        # Numerator from C·adj(sI-A)·B + D·det(sI-A)
        # Evaluated at enough points to reconstruct coefficients
        # Use polynomial interpolation at n+1 frequency points
        n_pts = n + 1 + len(den)  # extra safety
        # Pick s values well away from poles
        s_vals = [complex(float(k + 1) * 10.0, float(k + 1) * 10.0) for k in range(n_pts)]

        # Evaluate G(s) at sample points
        g_vals = []
        for s in s_vals:
            sI_minus_A = s * np.eye(n) - self.A
            try:
                inv_sIA = np.linalg.inv(sI_minus_A)
            except np.linalg.LinAlgError:
                inv_sIA = np.linalg.pinv(sI_minus_A)
            G_s = (self.C @ inv_sIA @ self.B + self.D)[0, 0]
            g_vals.append(complex(G_s))

        # Numerator polynomial: G(s) * den(s)
        # den(s) evaluated at sample points
        def _poly_eval_c(coeffs, s):
            r = complex(0)
            for c in coeffs:
                r = r * s + c
            return r

        # num_vals[k] = G(s_k) * den(s_k)
        num_vals = [g_vals[k] * _poly_eval_c(den, s_vals[k]) for k in range(n_pts)]

        # Fit numerator polynomial of degree <= n using Vandermonde system
        # Degree of numerator: if D=0, it's n-1; if D≠0, it's n
        deg_num = n if abs(self.D[0, 0]) > 1e-14 else n - 1
        vdm = np.zeros((n_pts, deg_num + 1), dtype=complex)
        for k, s in enumerate(s_vals):
            for j in range(deg_num + 1):
                vdm[k, j] = s ** (deg_num - j)

        # Least-squares fit
        num_coeffs_c, _, _, _ = np.linalg.lstsq(vdm, np.array(num_vals), rcond=None)
        num_coeffs = [c.real for c in num_coeffs_c]

        # Strip small leading coefficients
        while len(num_coeffs) > 1 and abs(num_coeffs[0]) < 1e-10:
            num_coeffs = num_coeffs[1:]

        return TransferFunction(num=num_coeffs, den=list(den))

    # -- Properties --------------------------------------------------------

    def poles(self) -> np.ndarray:
        """Eigenvalues of A (open-loop poles)."""
        return np.linalg.eigvals(self.A)

    def is_stable(self) -> bool:
        """True if all eigenvalues of A have negative real parts."""
        return bool(np.all(np.real(self.poles()) < 0))


# ---------------------------------------------------------------------------
# Characteristic polynomial
# ---------------------------------------------------------------------------

def _char_poly_numpy(A: np.ndarray) -> list[float]:
    """
    Characteristic polynomial of matrix A: det(sI - A).
    Returns coefficients [1, c1, c2, ..., cn] (monic, highest degree first).

    Uses Faddeev-LeVerrier algorithm (numerically stable for small n).
    References: Kailath (1980) §3.
    """
    n = A.shape[0]
    # Use numpy to compute characteristic polynomial
    eigs = np.linalg.eigvals(A)
    # Build polynomial from eigenvalues
    poly = np.array([1.0], dtype=complex)
    for e in eigs:
        poly = np.convolve(poly, [1.0, -e])
    return [c.real for c in poly]


# ---------------------------------------------------------------------------
# Controllability
# ---------------------------------------------------------------------------

def is_controllable(ss: StateSpace) -> bool:
    """
    Test controllability via rank of the controllability matrix.

    C = [B, AB, A²B, ..., A^{n-1}B]

    A system is controllable iff rank(C) = n.

    References: Kailath (1980) §6.2; Ogata (2010) §12-4.
    """
    n = ss.A.shape[0]
    ctrb = np.hstack([np.linalg.matrix_power(ss.A, k) @ ss.B for k in range(n)])
    rank = np.linalg.matrix_rank(ctrb)
    return int(rank) == n


def controllability_matrix(ss: StateSpace) -> np.ndarray:
    """Return the full controllability matrix C = [B, AB, ..., A^{n-1}B]."""
    n = ss.A.shape[0]
    return np.hstack([np.linalg.matrix_power(ss.A, k) @ ss.B for k in range(n)])


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

def is_observable(ss: StateSpace) -> bool:
    """
    Test observability via rank of the observability matrix.

    O = [C; CA; CA²; ...; CA^{n-1}]

    A system is observable iff rank(O) = n.

    References: Kailath (1980) §6.3; Ogata (2010) §12-4.
    """
    n = ss.A.shape[0]
    obsv = np.vstack([ss.C @ np.linalg.matrix_power(ss.A, k) for k in range(n)])
    rank = np.linalg.matrix_rank(obsv)
    return int(rank) == n


# ---------------------------------------------------------------------------
# Pole placement — Ackermann's formula (SISO)
# ---------------------------------------------------------------------------

def place_poles(
    A: np.ndarray,
    B: np.ndarray,
    desired_poles: list,
) -> np.ndarray:
    """
    Compute state-feedback gain K such that eig(A - B·K) = desired_poles.

    Ackermann (1972) formula (SISO only):
        K = e_n^T · C^{-1} · p_d(A)

    where C is the controllability matrix, e_n^T = [0…0, 1],
    and p_d(A) is the desired characteristic polynomial evaluated at A.

    Parameters
    ----------
    A             : n×n state matrix
    B             : n×1 input matrix (SISO)
    desired_poles : list of n desired pole locations (complex allowed)

    Returns
    -------
    K : 1×n state-feedback gain row vector (numpy array)

    References: Ackermann (1972); Kailath (1980) §6.4.
    """
    A = np.atleast_2d(np.asarray(A, dtype=float))
    B = np.atleast_2d(np.asarray(B, dtype=float))
    n = A.shape[0]

    if B.shape[1] != 1:
        raise ValueError("Ackermann's formula is SISO only: B must be n×1")

    # Build desired characteristic polynomial p_d(s) = Π(s - p_i)
    pd_coeffs = np.array([1.0], dtype=complex)
    for p in desired_poles:
        pd_coeffs = np.convolve(pd_coeffs, [1.0, -complex(p)])

    # Evaluate p_d(A) using Horner's method
    pd_A = np.zeros_like(A, dtype=complex)
    for coeff in pd_coeffs:
        pd_A = pd_A @ A + coeff * np.eye(n, dtype=complex)

    # Controllability matrix (n×n for SISO)
    ctrb_cols = [np.linalg.matrix_power(A, k) @ B for k in range(n)]
    C_mat = np.hstack(ctrb_cols).astype(float)

    # Check invertibility
    if abs(np.linalg.det(C_mat)) < 1e-12:
        raise ValueError("System is not controllable; cannot place poles.")

    C_inv = np.linalg.inv(C_mat)

    # e_n^T (last standard basis row vector)
    e_n = np.zeros((1, n))
    e_n[0, -1] = 1.0

    K = (e_n @ C_inv @ pd_A.real).flatten()
    return K


# ---------------------------------------------------------------------------
# LQR via continuous algebraic Riccati equation
# ---------------------------------------------------------------------------

def lqr(
    ss: StateSpace,
    Q: np.ndarray,
    R: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Continuous-time Linear Quadratic Regulator.

    Minimises J = ∫₀^∞ (xᵀQx + uᵀRu) dt.

    Solves the continuous ARE:
        Aᵀ P + P A - P B R⁻¹ Bᵀ P + Q = 0

    via Kleinman's iteration (policy iteration / Newton's method):
        Given stabilising K₀, iterate:
            Solve Lyapunov:  Aₖᵀ Pₖ + Pₖ Aₖ = -(Q + KₖᵀR Kₖ)
            Update:          Kₖ₊₁ = R⁻¹ Bᵀ Pₖ
        where Aₖ = A - B Kₖ.

    Parameters
    ----------
    ss : StateSpace
    Q  : n×n state cost matrix (positive semi-definite)
    R  : p×p input cost matrix (positive definite)

    Returns
    -------
    (K_gain, P_riccati) : both numpy arrays

    References: Anderson & Moore (2007) §4; Kailath (1980) §9.3.
    """
    A = ss.A
    B = ss.B
    n = A.shape[0]
    Q = np.atleast_2d(np.asarray(Q, dtype=float))
    R = np.atleast_2d(np.asarray(R, dtype=float))

    R_inv = np.linalg.inv(R)

    # Initial gain: use Q to find a stabilising K₀
    eigs = np.linalg.eigvals(A)
    if np.all(np.real(eigs) < 0):
        K_cur = np.zeros((B.shape[1], n))
    else:
        # Shift A to make it stable for initial Lyapunov
        alpha = float(np.max(np.real(eigs))) + 1.0
        A_shift = A - alpha * np.eye(n)
        P0 = _solve_lyapunov_numpy(A_shift, Q)
        K_cur = R_inv @ B.T @ P0

    P_cur = np.eye(n)
    tol = 1e-10
    max_iter = 500

    for _ in range(max_iter):
        A_k = A - B @ K_cur
        Q_k = Q + K_cur.T @ R @ K_cur

        # Solve Lyapunov: A_kᵀ P + P A_k = -Q_k
        P_new = _solve_lyapunov_numpy(A_k, Q_k)

        K_new = R_inv @ B.T @ P_new

        diff = np.linalg.norm(P_new - P_cur, "fro")
        P_cur = P_new
        K_cur = K_new

        if diff < tol:
            break

    # Symmetrise
    P_cur = (P_cur + P_cur.T) / 2.0

    return K_cur, P_cur


def _solve_lyapunov_numpy(A: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """
    Solve continuous Lyapunov equation: Aᵀ P + P A = -Q
    via Kronecker vectorisation (exact for small n, pure numpy).

    References: Anderson & Moore (2007) App. B.
    """
    n = A.shape[0]
    # (I⊗Aᵀ + Aᵀ⊗I) vec(P) = -vec(Q)
    I = np.eye(n)
    M = np.kron(I, A.T) + np.kron(A.T, I)  # n²×n²
    rhs = -Q.flatten(order="F")  # column-major vectorisation
    vec_P = np.linalg.solve(M, rhs)
    return vec_P.reshape(n, n, order="F")
