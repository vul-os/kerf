"""
kerf_cad_core.vibration.mdof — n-DOF modal analysis and frequency response.

Pure-Python implementation (math module only — no numpy).

Public functions
----------------
mdof_eigen(M_flat, K_flat, n)
    Generalised eigenproblem for an n×n mass matrix M and stiffness matrix K.
    Solves M^{-1} K via full Jacobi iteration to get natural frequencies ωᵢ
    (rad/s) and mass-normalised mode shapes.

mdof_frf(M_flat, K_flat, n, zeta_modal, omega_range)
    Frequency response function matrix H(ω) ∈ ℂⁿˣⁿ for proportional
    (Rayleigh) or uniform modal damping.  H returned as list of (n×n) complex
    values at each ω.

mdof_rayleigh_damping(alpha, beta, M_flat, K_flat, n)
    Assemble the Rayleigh damping matrix C = α M + β K and compute modal
    damping ratios ζᵣ = (α/(2ωᵣ) + β ωᵣ/2) for each mode r.

All functions return plain dicts:
    success → {"ok": True, ...computed fields..., "warnings": [...]}
    failure → {"ok": False, "reason": "<human-readable>"}

Functions NEVER raise.

Matrices are passed as flat lists (row-major): M_flat[i*n + j] = M[i][j].

References
----------
Rao, S.S. "Mechanical Vibrations", 5th ed. — Ch. 6 (MDOF), Ch. 11 (Modal)
Inman, D.J. "Engineering Vibration", 4th ed. — Ch. 4, Ch. 5
Ewins, D.J. "Modal Testing: Theory, Practice and Application", 2nd ed. — Ch. 2

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Internal matrix helpers — pure Python, n×n dense matrices as flat lists
# ---------------------------------------------------------------------------

def _mat_get(A: List[float], i: int, j: int, n: int) -> float:
    return A[i * n + j]


def _mat_set(A: List[float], i: int, j: int, n: int, v: float) -> None:
    A[i * n + j] = v


def _mat_copy(A: List[float]) -> List[float]:
    return A[:]


def _eye_flat(n: int) -> List[float]:
    out = [0.0] * (n * n)
    for i in range(n):
        out[i * n + i] = 1.0
    return out


def _mat_mul_flat(A: List[float], B: List[float], n: int) -> List[float]:
    """Multiply two n×n flat matrices."""
    C = [0.0] * (n * n)
    for i in range(n):
        for k in range(n):
            aik = A[i * n + k]
            if aik == 0.0:
                continue
            for j in range(n):
                C[i * n + j] += aik * B[k * n + j]
    return C


def _mat_transpose_flat(A: List[float], n: int) -> List[float]:
    B = [0.0] * (n * n)
    for i in range(n):
        for j in range(n):
            B[j * n + i] = A[i * n + j]
    return B


def _mat_vec_mul(A: List[float], v: List[float], n: int) -> List[float]:
    """A (n×n flat) times column vector v (len n)."""
    out = [0.0] * n
    for i in range(n):
        s = 0.0
        for j in range(n):
            s += A[i * n + j] * v[j]
        out[i] = s
    return out


def _vec_norm(v: List[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _vec_dot(a: List[float], b: List[float]) -> float:
    return sum(ai * bi for ai, bi in zip(a, b))


def _mat_inv_flat(A: List[float], n: int) -> List[float] | None:
    """
    Invert an n×n matrix using Gauss-Jordan with partial pivoting.
    Returns None if singular.
    """
    aug = [0.0] * (n * 2 * n)
    # Build augmented [A | I]
    for i in range(n):
        for j in range(n):
            aug[i * 2 * n + j] = A[i * n + j]
        aug[i * 2 * n + n + i] = 1.0

    for col in range(n):
        # Pivot
        max_val = abs(aug[col * 2 * n + col])
        max_row = col
        for row in range(col + 1, n):
            v = abs(aug[row * 2 * n + col])
            if v > max_val:
                max_val = v
                max_row = row
        if max_val < 1e-14:
            return None  # singular
        if max_row != col:
            for k in range(2 * n):
                aug[col * 2 * n + k], aug[max_row * 2 * n + k] = \
                    aug[max_row * 2 * n + k], aug[col * 2 * n + k]
        pivot = aug[col * 2 * n + col]
        inv_p = 1.0 / pivot
        for k in range(2 * n):
            aug[col * 2 * n + k] *= inv_p
        for row in range(n):
            if row == col:
                continue
            factor = aug[row * 2 * n + col]
            if factor == 0.0:
                continue
            for k in range(2 * n):
                aug[row * 2 * n + k] -= factor * aug[col * 2 * n + k]

    # Extract inverse
    inv_A = [0.0] * (n * n)
    for i in range(n):
        for j in range(n):
            inv_A[i * n + j] = aug[i * 2 * n + n + j]
    return inv_A


def _jacobi_eigen(A: List[float], n: int, max_iter: int = 200) \
        -> Tuple[List[float], List[List[float]]]:
    """
    Classical Jacobi eigenvalue algorithm for a real symmetric n×n matrix A.

    Returns (eigenvalues, eigenvectors) where eigenvectors[i] is the i-th
    eigenvector (column i of the accumulated rotation matrix V).

    Reference: Golub & Van Loan "Matrix Computations" §8.4.
    """
    D = _mat_copy(A)          # working copy, will converge to diagonal
    V = _eye_flat(n)          # accumulated rotations

    for _ in range(max_iter * n * n):
        # Find off-diagonal element with largest |D[p][q]|
        max_off = 0.0
        p = q = 0
        for i in range(n):
            for j in range(i + 1, n):
                v = abs(D[i * n + j])
                if v > max_off:
                    max_off = v
                    p, q = i, j
        if max_off < 1e-13:
            break

        # Compute Jacobi rotation angle
        Dpp = D[p * n + p]
        Dqq = D[q * n + q]
        Dpq = D[p * n + q]
        tau = (Dqq - Dpp) / (2.0 * Dpq)
        t = (1.0 / (abs(tau) + math.sqrt(1.0 + tau * tau)))
        if tau < 0:
            t = -t
        c = 1.0 / math.sqrt(1.0 + t * t)
        s = t * c

        # Apply rotation to D (similarity transform)
        # Update affected rows/columns
        for r in range(n):
            if r == p or r == q:
                continue
            Drp = D[r * n + p]
            Drq = D[r * n + q]
            D[r * n + p] = c * Drp - s * Drq
            D[p * n + r] = D[r * n + p]
            D[r * n + q] = s * Drp + c * Drq
            D[q * n + r] = D[r * n + q]

        D[p * n + p] = c * c * Dpp - 2.0 * s * c * Dpq + s * s * Dqq
        D[q * n + q] = s * s * Dpp + 2.0 * s * c * Dpq + c * c * Dqq
        D[p * n + q] = 0.0
        D[q * n + p] = 0.0

        # Accumulate V
        for r in range(n):
            Vrp = V[r * n + p]
            Vrq = V[r * n + q]
            V[r * n + p] = c * Vrp - s * Vrq
            V[r * n + q] = s * Vrp + c * Vrq

    eigenvalues = [D[i * n + i] for i in range(n)]
    eigenvectors = [[V[r * n + i] for r in range(n)] for i in range(n)]
    return eigenvalues, eigenvectors


def _sort_eigenpairs(
    eigenvalues: List[float],
    eigenvectors: List[List[float]],
) -> Tuple[List[float], List[List[float]]]:
    """Sort eigenvalues ascending, permute eigenvectors accordingly."""
    idx = sorted(range(len(eigenvalues)), key=lambda i: eigenvalues[i])
    return [eigenvalues[i] for i in idx], [eigenvectors[i] for i in idx]


def _err(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _validate_matrix_flat(flat: List[float], n: int, name: str) -> str | None:
    if len(flat) != n * n:
        return f"{name} must have {n*n} elements for n={n}, got {len(flat)}"
    for v in flat:
        if not math.isfinite(v):
            return f"{name} contains non-finite value: {v}"
    return None


# ===========================================================================
# 1. mdof_eigen — generalised eigenproblem
# ===========================================================================

def mdof_eigen(
    M_flat: List[float],
    K_flat: List[float],
    n: int,
) -> dict:
    """
    Solve the generalised eigenvalue problem (K - ω² M) u = 0 for an n-DOF
    undamped system.

    Computes natural frequencies ωᵣ and mass-normalised mode shapes φᵣ such
    that φᵣᵀ M φᵣ = 1 and φᵣᵀ K φᵣ = ωᵣ².

    Parameters
    ----------
    M_flat : list[float]
        Mass matrix in row-major flat form (length n²). Must be symmetric
        positive definite.
    K_flat : list[float]
        Stiffness matrix in row-major flat form (length n²). Must be symmetric
        positive semi-definite.
    n : int
        Number of degrees of freedom. Must be >= 1.

    Returns
    -------
    dict
        ok              : True
        n               : int — number of DOF
        omega_r         : list[float] — natural frequencies (rad/s), ascending
        fn_hz_r         : list[float] — natural frequencies (Hz), ascending
        mode_shapes     : list[list[float]] — mode_shapes[r] is the r-th
                          mass-normalised mode shape (length n), ordered by ωᵣ
        modal_mass      : list[float] — φᵣᵀ M φᵣ (should be ~1.0)
        modal_stiffness : list[float] — φᵣᵀ K φᵣ (should be ~ωᵣ²)
        warnings        : list[str]

    Method
    ------
    1. Compute A = M⁻¹ K (dynamic matrix).
    2. Solve the standard symmetric eigenproblem on the symmetrised
       Ã = (A + Aᵀ)/2 via the Jacobi algorithm.
    3. Mass-normalise: φᵣ ← φᵣ / √(φᵣᵀ M φᵣ).

    References
    ----------
    Rao §6-3, §6-4; Inman §4.3, §4.4
    """
    try:
        n_i = int(n)
    except (TypeError, ValueError):
        return _err(f"n must be a positive integer, got {n!r}")
    if n_i < 1:
        return _err(f"n must be >= 1, got {n_i}")

    err = _validate_matrix_flat(M_flat, n_i, "M_flat")
    if err:
        return _err(err)
    err = _validate_matrix_flat(K_flat, n_i, "K_flat")
    if err:
        return _err(err)

    M = list(M_flat)
    K = list(K_flat)

    # Invert M
    M_inv = _mat_inv_flat(M, n_i)
    if M_inv is None:
        return _err("Mass matrix M is singular (non-invertible).")

    # Dynamic matrix A = M^{-1} K
    A = _mat_mul_flat(M_inv, K, n_i)

    # Symmetrise to handle floating-point asymmetry
    AT = _mat_transpose_flat(A, n_i)
    A_sym = [(A[k] + AT[k]) * 0.5 for k in range(n_i * n_i)]

    # Jacobi eigensolution
    raw_lambda, raw_vectors = _jacobi_eigen(A_sym, n_i)

    # Sort ascending
    lambdas, vectors = _sort_eigenpairs(raw_lambda, raw_vectors)

    warnings: list[str] = []

    omega_r = []
    fn_hz_r = []
    mode_shapes = []
    modal_mass = []
    modal_stiffness = []

    for r in range(n_i):
        lam = lambdas[r]
        phi = vectors[r][:]   # eigenvector (column of V), length n

        if lam < -1e-8:
            warnings.append(
                f"Mode {r}: negative eigenvalue λ={lam:.6g} "
                "(check K is positive semi-definite)."
            )
        omega = math.sqrt(max(lam, 0.0))
        omega_r.append(omega)
        fn_hz_r.append(omega / (2.0 * math.pi))

        # Mass-normalise: mhat = φᵀ M φ; φ_norm = φ / sqrt(mhat)
        Mphi = _mat_vec_mul(M, phi, n_i)
        mhat = _vec_dot(phi, Mphi)

        if mhat <= 0.0:
            warnings.append(
                f"Mode {r}: modal mass φᵀMφ={mhat:.6g} <= 0; "
                "eigenvector may be near-zero."
            )
            phi_norm = phi[:]
        else:
            scale = 1.0 / math.sqrt(mhat)
            phi_norm = [x * scale for x in phi]

        Mphi_n = _mat_vec_mul(M, phi_norm, n_i)
        Kphi_n = _mat_vec_mul(K, phi_norm, n_i)
        mm = _vec_dot(phi_norm, Mphi_n)
        mk = _vec_dot(phi_norm, Kphi_n)

        mode_shapes.append(phi_norm)
        modal_mass.append(mm)
        modal_stiffness.append(mk)

    return {
        "ok": True,
        "n": n_i,
        "omega_r": omega_r,
        "fn_hz_r": fn_hz_r,
        "mode_shapes": mode_shapes,
        "modal_mass": modal_mass,
        "modal_stiffness": modal_stiffness,
        "warnings": warnings,
    }


# ===========================================================================
# 2. mdof_frf — frequency response function matrix
# ===========================================================================

def mdof_frf(
    M_flat: List[float],
    K_flat: List[float],
    n: int,
    zeta_modal: List[float] | float,
    omega_range: List[float],
) -> dict:
    """
    Frequency response function (FRF) matrix H(ω) for an n-DOF system with
    proportional or uniform modal damping.

    H(ω)[j][k] gives the displacement of DOF j per unit harmonic force at
    DOF k:  x_j(ω) = H(ω)[j][k] × F_k(ω).

    Uses modal superposition:
        H(ω) = Σᵣ φᵣ φᵣᵀ / (ωᵣ² − ω² + 2i ζᵣ ωᵣ ω)

    Parameters
    ----------
    M_flat     : list[float]  — n×n mass matrix, row-major flat.
    K_flat     : list[float]  — n×n stiffness matrix, row-major flat.
    n          : int          — number of DOF.
    zeta_modal : list[float] or float
        Modal damping ratios.  If a single float, all modes share that ζ.
        If a list, must have length n (one ζ per mode).
    omega_range : list[float]
        Excitation frequencies (rad/s) at which to evaluate H.  Must be
        non-empty and all values >= 0.

    Returns
    -------
    dict
        ok          : True
        n           : int
        n_omega     : int — len(omega_range)
        omega_r     : list[float] — natural frequencies (rad/s)
        zeta_r      : list[float] — modal damping ratios used per mode
        H_real      : list[list[list[float]]] — shape [n_omega][n][n]
                      real part of H(ω)
        H_imag      : list[list[list[float]]] — shape [n_omega][n][n]
                      imaginary part of H(ω)
        H_mag       : list[list[list[float]]] — shape [n_omega][n][n]
                      |H(ω)| (magnitude)
        warnings    : list[str]

    References
    ----------
    Rao §6-7, §11-1; Ewins §2.1
    """
    # Solve eigenproblem first
    eig_res = mdof_eigen(M_flat, K_flat, n)
    if not eig_res["ok"]:
        return eig_res

    n_i = eig_res["n"]
    omega_r = eig_res["omega_r"]
    mode_shapes = eig_res["mode_shapes"]  # [r][dof]
    warnings: list[str] = list(eig_res["warnings"])

    # Parse zeta_modal
    if isinstance(zeta_modal, (int, float)):
        zeta_r = [float(zeta_modal)] * n_i
    else:
        try:
            zeta_r = [float(z) for z in zeta_modal]
        except (TypeError, ValueError) as exc:
            return _err(f"zeta_modal must be a float or list of floats: {exc}")
        if len(zeta_r) != n_i:
            return _err(
                f"zeta_modal has {len(zeta_r)} entries but n={n_i}; "
                "provide one ζ per mode (or a single float)."
            )
    for r, z in enumerate(zeta_r):
        if z < 0.0:
            return _err(f"zeta_modal[{r}]={z} must be >= 0.")
        if z >= 1.0:
            warnings.append(
                f"Mode {r}: zeta_modal={z:.4f} >= 1 (overdamped); FRF still computed."
            )

    # Parse omega_range
    try:
        omegas = [float(w) for w in omega_range]
    except (TypeError, ValueError) as exc:
        return _err(f"omega_range must be a list of floats: {exc}")
    if not omegas:
        return _err("omega_range must not be empty.")
    for w in omegas:
        if w < 0.0:
            return _err(f"omega_range contains negative frequency: {w}")

    # Build FRF matrix at each frequency
    # H(ω)[j][k] = Σᵣ φᵣ[j] φᵣ[k] / (ωᵣ² − ω² + 2i ζᵣ ωᵣ ω)
    n_omega = len(omegas)
    H_real = []
    H_imag = []
    H_mag  = []

    for w in omegas:
        w2 = w * w
        Hr_real = [[0.0] * n_i for _ in range(n_i)]
        Hr_imag = [[0.0] * n_i for _ in range(n_i)]

        for r in range(n_i):
            phi_r = mode_shapes[r]
            wr = omega_r[r]
            zr = zeta_r[r]
            wr2 = wr * wr
            # Denominator: (ωᵣ² - ω²) + i(2 ζᵣ ωᵣ ω)
            D_real = wr2 - w2
            D_imag = 2.0 * zr * wr * w
            D_abs2 = D_real * D_real + D_imag * D_imag
            if D_abs2 < 1e-300:
                warnings.append(
                    f"Near-resonance at ω={w:.4g} rad/s for mode {r} "
                    f"(ωᵣ={wr:.4g}, ζ={zr:.4g}): FRF clamped to large finite."
                )
                D_abs2 = 1e-300

            # 1/D = (D_real - i D_imag) / |D|²
            inv_D_real = D_real / D_abs2
            inv_D_imag = -D_imag / D_abs2

            for j in range(n_i):
                for k in range(n_i):
                    coeff = phi_r[j] * phi_r[k]
                    Hr_real[j][k] += coeff * inv_D_real
                    Hr_imag[j][k] += coeff * inv_D_imag

        Hr_mag = [
            [math.sqrt(Hr_real[j][k] ** 2 + Hr_imag[j][k] ** 2) for k in range(n_i)]
            for j in range(n_i)
        ]
        H_real.append(Hr_real)
        H_imag.append(Hr_imag)
        H_mag.append(Hr_mag)

    return {
        "ok": True,
        "n": n_i,
        "n_omega": n_omega,
        "omega_r": omega_r,
        "zeta_r": zeta_r,
        "H_real": H_real,
        "H_imag": H_imag,
        "H_mag": H_mag,
        "warnings": warnings,
    }


# ===========================================================================
# 3. mdof_rayleigh_damping — C = α M + β K
# ===========================================================================

def mdof_rayleigh_damping(
    alpha: float,
    beta: float,
    M_flat: List[float],
    K_flat: List[float],
    n: int,
) -> dict:
    """
    Assemble Rayleigh (proportional) damping matrix C = α M + β K and
    compute modal damping ratios.

    Parameters
    ----------
    alpha : float
        Mass-proportional coefficient (1/s). Must be >= 0.
    beta  : float
        Stiffness-proportional coefficient (s). Must be >= 0.
    M_flat, K_flat, n : same as mdof_eigen.

    Returns
    -------
    dict
        ok          : True
        alpha       : float — used
        beta        : float — used
        C_flat      : list[float] — Rayleigh damping matrix (n² flat, row-major)
        omega_r     : list[float] — natural frequencies (rad/s)
        zeta_r      : list[float] — modal damping ratios ζᵣ = α/(2ωᵣ) + βωᵣ/2
        warnings    : list[str]

    Formula
    -------
    ζᵣ = α/(2 ωᵣ) + β ωᵣ/2

    References
    ----------
    Rao §6-7; Inman §4.5
    """
    try:
        alpha_f = float(alpha)
        beta_f = float(beta)
    except (TypeError, ValueError):
        return _err("alpha and beta must be numbers.")
    if alpha_f < 0.0:
        return _err(f"alpha must be >= 0, got {alpha_f}")
    if beta_f < 0.0:
        return _err(f"beta must be >= 0, got {beta_f}")

    eig_res = mdof_eigen(M_flat, K_flat, n)
    if not eig_res["ok"]:
        return eig_res

    n_i = eig_res["n"]
    omega_r = eig_res["omega_r"]
    warnings: list[str] = list(eig_res["warnings"])

    err = _validate_matrix_flat(M_flat, n_i, "M_flat")
    if err:
        return _err(err)
    err = _validate_matrix_flat(K_flat, n_i, "K_flat")
    if err:
        return _err(err)

    # C = α M + β K
    C_flat = [alpha_f * M_flat[k] + beta_f * K_flat[k] for k in range(n_i * n_i)]

    zeta_r = []
    for r, wr in enumerate(omega_r):
        if wr < 1e-10:
            warnings.append(
                f"Mode {r}: ωᵣ≈0 (rigid body?); modal damping ratio undefined; set to 0."
            )
            zeta_r.append(0.0)
        else:
            zeta_r.append(alpha_f / (2.0 * wr) + beta_f * wr / 2.0)

    return {
        "ok": True,
        "alpha": alpha_f,
        "beta": beta_f,
        "C_flat": C_flat,
        "omega_r": omega_r,
        "zeta_r": zeta_r,
        "warnings": warnings,
    }
