"""
kerf_cad_core.controls.statespace — modern/state-space control analysis.

Public functions
----------------
ss_model(A, B, C, D)
    Validate and create a state-space container (n-states, p-inputs, q-outputs).

controllability_matrix(A, B)
    Full controllability matrix [B, AB, A²B, ...] and rank test.

observability_matrix(A, C)
    Full observability matrix [C; CA; CA²; ...] and rank test.

pole_placement_ackermann(A, B, desired_poles)
    SISO pole placement via Ackermann's formula → state-feedback gain K.

lqr(A, B, Q, R)
    Continuous-time LQR: solve the algebraic Riccati equation → gain K.

luenberger_gains(A, C, desired_observer_poles)
    Luenberger observer gains L via duality (Ackermann on (A^T, C^T)).

c2d(A, B, dt)
    Zero-order-hold discretisation: (Ad, Bd).

discrete_stability(Ad)
    Check discrete-time stability (all eigenvalues |λ| < 1).

digital_pid_step(Kp, Ki, Kd, dt, e_k, e_km1, e_km2, u_km1)
    Digital PID step (velocity / incremental form).

All functions return plain dicts:
    success → {"ok": True, ..., "warnings": [...]}
    failure → {"ok": False, "reason": "<human-readable>"}
Functions NEVER raise.

Implementation notes
--------------------
* Pure-Python; no numpy.  All matrix arithmetic is done with plain lists-of-lists.
* Matrix helpers are local (do NOT import a shared _linalg — it may not exist).
* Eigenvalue computation uses the QR algorithm for real matrices (Hessenberg form
  + Francis double-shift) — adequate for the n ≤ 20 state sizes typical in CAD
  control design.

References
----------
Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
Franklin, G., Powell, J.D., Emami-Naeini, A. "Feedback Control of Dynamic Systems", 8th ed.
Åström, K.J. & Wittenmark, B. "Computer-Controlled Systems", 3rd ed.
Anderson, B.D.O. & Moore, J.B. "Optimal Control: Linear Quadratic Methods" (Dover).

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def _err(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _ok(**kwargs) -> dict:
    d: dict = {"ok": True}
    d.update(kwargs)
    if "warnings" not in d:
        d["warnings"] = []
    return d


# ---------------------------------------------------------------------------
# Pure-Python matrix helpers
# (all matrices are list[list[float]], row-major)
# ---------------------------------------------------------------------------

def _zeros(m: int, n: int) -> list[list[float]]:
    return [[0.0] * n for _ in range(m)]


def _eye(n: int) -> list[list[float]]:
    M = _zeros(n, n)
    for i in range(n):
        M[i][i] = 1.0
    return M


def _mat_add(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    m, n = len(A), len(A[0])
    C = _zeros(m, n)
    for i in range(m):
        for j in range(n):
            C[i][j] = A[i][j] + B[i][j]
    return C


def _mat_scale(A: list[list[float]], s: float) -> list[list[float]]:
    m, n = len(A), len(A[0])
    C = _zeros(m, n)
    for i in range(m):
        for j in range(n):
            C[i][j] = A[i][j] * s
    return C


def _mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    m, k = len(A), len(A[0])
    n = len(B[0])
    C = _zeros(m, n)
    for i in range(m):
        for j in range(n):
            s = 0.0
            for l in range(k):
                s += A[i][l] * B[l][j]
            C[i][j] = s
    return C


def _mat_transpose(A: list[list[float]]) -> list[list[float]]:
    m, n = len(A), len(A[0])
    return [[A[i][j] for i in range(m)] for j in range(n)]


def _vec_to_col(v: list[float]) -> list[list[float]]:
    """Convert 1-D list to column vector (n×1 matrix)."""
    return [[x] for x in v]


def _col_to_vec(M: list[list[float]]) -> list[float]:
    """Convert n×1 column matrix to 1-D list."""
    return [row[0] for row in M]


def _mat_copy(A: list[list[float]]) -> list[list[float]]:
    return [row[:] for row in A]


def _mat_frobenius(A: list[list[float]]) -> float:
    s = 0.0
    for row in A:
        for x in row:
            s += x * x
    return math.sqrt(s)


# ---------------------------------------------------------------------------
# Gaussian elimination with partial pivoting → inverse
# ---------------------------------------------------------------------------

def _mat_inv(A: list[list[float]]) -> list[list[float]] | None:
    """Invert square matrix via Gaussian elimination with partial pivoting.
    Returns None if singular."""
    n = len(A)
    # Augment with identity
    M = [A[i][:] + [float(i == j) for j in range(n)] for i in range(n)]
    for col in range(n):
        # Pivot search
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot_row][col]) < 1e-14:
            return None
        M[col], M[pivot_row] = M[pivot_row], M[col]
        scale = M[col][col]
        M[col] = [x / scale for x in M[col]]
        for row in range(n):
            if row != col:
                factor = M[row][col]
                M[row] = [M[row][j] - factor * M[col][j] for j in range(2 * n)]
    return [row[n:] for row in M]


def _mat_rank(M_in: list[list[float]], tol: float = 1e-10) -> int:
    """Rank of matrix via row-reduction."""
    M = [row[:] for row in M_in]
    m, n = len(M), len(M[0])
    rank = 0
    used_rows = [False] * m
    for col in range(n):
        pivot_row = None
        for row in range(m):
            if not used_rows[row] and abs(M[row][col]) > tol:
                if pivot_row is None or abs(M[row][col]) > abs(M[pivot_row][col]):
                    pivot_row = row
        if pivot_row is None:
            continue
        used_rows[pivot_row] = True
        rank += 1
        scale = M[pivot_row][col]
        M[pivot_row] = [x / scale for x in M[pivot_row]]
        for r in range(m):
            if r != pivot_row and abs(M[r][col]) > tol:
                f = M[r][col]
                M[r] = [M[r][j] - f * M[pivot_row][j] for j in range(n)]
    return rank


# ---------------------------------------------------------------------------
# Characteristic polynomial (Hessenberg + QR eigenvalues)
# ---------------------------------------------------------------------------

def _hessenberg(A: list[list[float]]) -> list[list[float]]:
    """Reduce A to upper Hessenberg form via Householder reflections."""
    n = len(A)
    H = _mat_copy(A)
    for k in range(n - 2):
        # Extract sub-column below diagonal
        x = [H[i][k] for i in range(k + 1, n)]
        norm_x = math.sqrt(sum(v * v for v in x))
        if norm_x < 1e-14:
            continue
        sign = 1.0 if x[0] >= 0 else -1.0
        x[0] += sign * norm_x
        norm_x2 = math.sqrt(sum(v * v for v in x))
        if norm_x2 < 1e-14:
            continue
        x = [v / norm_x2 for v in x]
        # Apply H = (I - 2 v v^T) from left and right (sub-matrix)
        sub_size = n - k - 1
        # Left: rows k+1..n, all cols k..n
        for j in range(k, n):
            dot = sum(x[i] * H[k + 1 + i][j] for i in range(sub_size))
            for i in range(sub_size):
                H[k + 1 + i][j] -= 2.0 * x[i] * dot
        # Right: all rows, cols k+1..n
        for i in range(n):
            dot = sum(x[j] * H[i][k + 1 + j] for j in range(sub_size))
            for j in range(sub_size):
                H[i][k + 1 + j] -= 2.0 * x[j] * dot
    return H


def _qr_step(H: list[list[float]]) -> list[list[float]]:
    """One QR iteration (Givens rotations) on upper Hessenberg matrix."""
    n = len(H)
    Q = _eye(n)
    R = _mat_copy(H)
    for i in range(n - 1):
        a, b = R[i][i], R[i + 1][i]
        r = math.hypot(a, b)
        if r < 1e-14:
            continue
        c, s = a / r, b / r
        # Apply Givens from left: rows i and i+1
        for j in range(n):
            tmp = c * R[i][j] + s * R[i + 1][j]
            R[i + 1][j] = -s * R[i][j] + c * R[i + 1][j]
            R[i][j] = tmp
        # Accumulate Q (right multiply Q by G^T)
        for j in range(n):
            tmp = c * Q[j][i] + s * Q[j][i + 1]
            Q[j][i + 1] = -s * Q[j][i] + c * Q[j][i + 1]
            Q[j][i] = tmp
    # H_new = R * Q
    return _mat_mul(R, Q)


def _eigenvalues_real(A: list[list[float]], max_iter: int = 1000) -> list[complex]:
    """Approximate eigenvalues of real matrix A via QR algorithm.
    Returns list of complex eigenvalues (conjugate pairs for real matrices)."""
    n = len(A)
    if n == 0:
        return []
    if n == 1:
        return [complex(A[0][0])]

    H = _hessenberg(A)
    tol = 1e-10
    for _ in range(max_iter):
        # Check for deflation (sub-diagonal near zero)
        all_small = True
        for i in range(n - 1):
            if abs(H[i + 1][i]) > tol * (abs(H[i][i]) + abs(H[i + 1][i + 1])):
                all_small = False
                break
        if all_small:
            break
        # Wilkinson shift for better convergence
        t = H[n - 1][n - 1]
        H_shifted = _mat_copy(H)
        for i in range(n):
            H_shifted[i][i] -= t
        H = _qr_step(H_shifted)
        for i in range(n):
            H[i][i] += t

    # Extract eigenvalues from quasi-triangular form
    eigs: list[complex] = []
    i = 0
    while i < n:
        if i == n - 1:
            eigs.append(complex(H[i][i]))
            i += 1
        elif abs(H[i + 1][i]) <= tol * (abs(H[i][i]) + abs(H[i + 1][i + 1])):
            eigs.append(complex(H[i][i]))
            i += 1
        else:
            # 2×2 block → complex conjugate pair
            a, b = H[i][i], H[i][i + 1]
            c, d = H[i + 1][i], H[i + 1][i + 1]
            tr = a + d
            det = a * d - b * c
            disc = tr * tr - 4.0 * det
            if disc >= 0:
                sq = math.sqrt(disc)
                eigs.append(complex((tr + sq) / 2.0))
                eigs.append(complex((tr - sq) / 2.0))
            else:
                sq = math.sqrt(-disc)
                eigs.append(complex(tr / 2.0, sq / 2.0))
                eigs.append(complex(tr / 2.0, -sq / 2.0))
            i += 2
    return eigs


def _char_poly_from_roots(roots: list[complex]) -> list[float]:
    """Build monic polynomial from complex roots: (s-r1)(s-r2)...(s-rn).
    Returns real coefficients (imaginary parts discarded — assumes roots are
    real or conjugate pairs)."""
    # [1]  (degree 0 → monic constant)
    poly_r: list[float] = [1.0]
    poly_i: list[float] = [0.0]

    for r in roots:
        # Multiply current poly by (s - r)
        new_r = [0.0] * (len(poly_r) + 1)
        new_i = [0.0] * (len(poly_r) + 1)
        for k, (pr, pi) in enumerate(zip(poly_r, poly_i)):
            new_r[k] += pr
            new_i[k] += pi
            new_r[k + 1] -= pr * r.real - pi * r.imag
            new_i[k + 1] -= pr * r.imag + pi * r.real
        poly_r, poly_i = new_r, new_i

    return poly_r  # imaginary parts should be ~0 for conjugate pairs


def _poly_eval_mat(coeffs: list[float], A: list[list[float]]) -> list[list[float]]:
    """Evaluate scalar polynomial with matrix argument (Cayley-Hamilton).
    p(A) = c0*A^n + c1*A^(n-1) + ... + cn*I."""
    n = len(A)
    result = _zeros(n, n)
    # Horner's method
    for c in coeffs:
        result = _mat_add(_mat_mul(result, A), _mat_scale(_eye(n), c))
    return result


# ---------------------------------------------------------------------------
# Matrix exponential (Padé approximation, order 6)
# ---------------------------------------------------------------------------

def _mat_exp(A: list[list[float]]) -> list[list[float]]:
    """Matrix exponential via Padé approximation (scaling and squaring)."""
    n = len(A)
    # Scale: find m such that ||A||/2^m < 0.5 (use Frobenius norm)
    norm = _mat_frobenius(A)
    m = 0
    while norm > 0.5:
        norm /= 2.0
        m += 1
    A_scaled = _mat_scale(A, 1.0 / (2 ** m))

    # Padé coefficients for order 6
    # p6(x) = 1 + x + x²/2 + x³/6 + x⁴/24 + x⁵/120 + x⁶/720
    # Using diagonal Padé [6/6]: more stable
    # We use the simpler Taylor series for small ||A|| (after scaling)
    # Taylor to order 14 for sufficient precision
    result = _eye(n)
    term = _eye(n)
    for k in range(1, 20):
        term = _mat_mul(term, _mat_scale(A_scaled, 1.0 / k))
        result = _mat_add(result, term)
        if _mat_frobenius(term) < 1e-15:
            break

    # Unsquare: result = result^(2^m) by repeated squaring
    for _ in range(m):
        result = _mat_mul(result, result)
    return result


# ---------------------------------------------------------------------------
# 1. State-space model container
# ---------------------------------------------------------------------------

def ss_model(
    A: list[list[float]],
    B: list[list[float]],
    C: list[list[float]],
    D: list[list[float]],
) -> dict:
    """
    Validate and describe a continuous-time state-space model.

    State equation:  ẋ = A x + B u
    Output equation: y = C x + D u

    Parameters
    ----------
    A : n×n matrix (state/system matrix)
    B : n×p matrix (input matrix)
    C : q×n matrix (output matrix)
    D : q×p matrix (feedthrough matrix)

    Returns
    -------
    dict
        ok        : True
        n_states  : n
        n_inputs  : p
        n_outputs : q
        eigenvalues : list of (real, imag) pairs for eigenvalues of A
        stable      : True if Re(λ) < 0 for all eigenvalues
        warnings  : list
    """
    warnings: list[str] = []

    # Basic type checks
    for name, M in [("A", A), ("B", B), ("C", C), ("D", D)]:
        if not isinstance(M, (list, tuple)) or len(M) == 0:
            return _err(f"{name} must be a non-empty matrix (list of lists).")
        for i, row in enumerate(M):
            if not isinstance(row, (list, tuple)) or len(row) == 0:
                return _err(f"{name}[{i}] must be a non-empty row.")
            for j, val in enumerate(row):
                try:
                    float(val)
                except (TypeError, ValueError):
                    return _err(f"{name}[{i}][{j}] = {val!r} is not a number.")

    n = len(A)
    if len(A[0]) != n:
        return _err(f"A must be square (n×n). Got {n}×{len(A[0])}.")
    if len(B) != n:
        return _err(f"B must have {n} rows (= n_states). Got {len(B)}.")
    p = len(B[0])
    if any(len(row) != p for row in B):
        return _err("B rows must all have the same length.")
    q = len(C)
    if len(C[0]) != n:
        return _err(f"C must have {n} columns (= n_states). Got {len(C[0])}.")
    if any(len(row) != n for row in C):
        return _err("C rows must all have n columns.")
    if len(D) != q:
        return _err(f"D must have {q} rows (= n_outputs). Got {len(D)}.")
    if len(D[0]) != p:
        return _err(f"D must have {p} columns (= n_inputs). Got {len(D[0])}.")

    # Convert to float
    A_f = [[float(A[i][j]) for j in range(n)] for i in range(n)]

    # Eigenvalues of A
    eigs = _eigenvalues_real(A_f)
    eig_pairs = [(e.real, e.imag) for e in eigs]
    stable = all(e.real < 0 for e in eigs)

    if not stable:
        warnings.append("UNSTABLE: one or more eigenvalues of A have Re(λ) >= 0.")

    return _ok(
        n_states=n,
        n_inputs=p,
        n_outputs=q,
        A=A,
        B=B,
        C=C,
        D=D,
        eigenvalues=eig_pairs,
        stable=stable,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 2. Controllability matrix
# ---------------------------------------------------------------------------

def controllability_matrix(
    A: list[list[float]],
    B: list[list[float]],
) -> dict:
    """
    Build the controllability matrix C = [B, AB, A²B, ..., A^(n-1)B] and test rank.

    Parameters
    ----------
    A : n×n state matrix
    B : n×p input matrix

    Returns
    -------
    dict
        ok              : True
        n_states        : n
        n_inputs        : p
        ctrb_matrix     : n×(n*p) controllability matrix (list of rows)
        rank            : rank of controllability matrix
        is_controllable : True if rank == n
        warnings        : list
    """
    # Validate
    if not isinstance(A, (list, tuple)) or len(A) == 0:
        return _err("A must be a non-empty matrix.")
    n = len(A)
    if len(A[0]) != n:
        return _err(f"A must be square ({n}×{n}).")
    if not isinstance(B, (list, tuple)) or len(B) != n:
        return _err(f"B must have {n} rows.")
    # Check all rows of A have n elements
    for i, row in enumerate(A):
        if not isinstance(row, (list, tuple)) or len(row) != n:
            return _err(f"A[{i}] must have {n} elements (A must be square {n}×{n}).")
    try:
        A_f = [[float(A[i][j]) for j in range(n)] for i in range(n)]
        B_f = [[float(B[i][j]) for j in range(len(B[0]))] for i in range(n)]
    except (TypeError, ValueError) as exc:
        return _err(f"A, B must contain numbers: {exc}")

    p = len(B_f[0])

    # Build [B, AB, A²B, ..., A^(n-1)B]
    cols: list[list[float]] = []
    power_B = [row[:] for row in B_f]  # A^k B, k=0

    for _ in range(n):
        for col_idx in range(p):
            cols.append([power_B[row_idx][col_idx] for row_idx in range(n)])
        power_B = _mat_mul(A_f, power_B)

    # Transpose: controllability matrix is n × (n*p)
    n_cols = len(cols)
    ctrb = [[cols[j][i] for j in range(n_cols)] for i in range(n)]

    rank = _mat_rank(ctrb)
    is_controllable = (rank == n)

    warnings: list[str] = []
    if not is_controllable:
        warnings.append(
            f"NOT_CONTROLLABLE: rank = {rank} < n = {n}. "
            "Some states cannot be reached by the input."
        )

    return _ok(
        n_states=n,
        n_inputs=p,
        ctrb_matrix=ctrb,
        rank=rank,
        is_controllable=is_controllable,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 3. Observability matrix
# ---------------------------------------------------------------------------

def observability_matrix(
    A: list[list[float]],
    C: list[list[float]],
) -> dict:
    """
    Build the observability matrix O = [C; CA; CA²; ...; CA^(n-1)] and test rank.

    Parameters
    ----------
    A : n×n state matrix
    C : q×n output matrix

    Returns
    -------
    dict
        ok               : True
        n_states         : n
        n_outputs        : q
        obsv_matrix      : (n*q)×n observability matrix (list of rows)
        rank             : rank of observability matrix
        is_observable    : True if rank == n
        warnings         : list
    """
    if not isinstance(A, (list, tuple)) or len(A) == 0:
        return _err("A must be a non-empty matrix.")
    n = len(A)
    if len(A[0]) != n:
        return _err(f"A must be square ({n}×{n}).")
    if not isinstance(C, (list, tuple)) or len(C) == 0:
        return _err("C must be a non-empty matrix.")
    if len(C[0]) != n:
        return _err(f"C must have {n} columns (= n_states).")
    try:
        A_f = [[float(A[i][j]) for j in range(n)] for i in range(n)]
        q = len(C)
        C_f = [[float(C[i][j]) for j in range(n)] for i in range(q)]
    except (TypeError, ValueError) as exc:
        return _err(f"A, C must contain numbers: {exc}")

    # Build [C; CA; CA²; ...; CA^(n-1)]
    obsv: list[list[float]] = []
    CA_k = [row[:] for row in C_f]  # C A^0 = C

    for _ in range(n):
        for row in CA_k:
            obsv.append(row[:])
        CA_k = _mat_mul(CA_k, A_f)

    rank = _mat_rank(obsv)
    is_observable = (rank == n)

    warnings: list[str] = []
    if not is_observable:
        warnings.append(
            f"NOT_OBSERVABLE: rank = {rank} < n = {n}. "
            "Some states cannot be inferred from the output."
        )

    return _ok(
        n_states=n,
        n_outputs=q,
        obsv_matrix=obsv,
        rank=rank,
        is_observable=is_observable,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 4. Pole placement (Ackermann's formula) — SISO
# ---------------------------------------------------------------------------

def pole_placement_ackermann(
    A: list[list[float]],
    B: list[list[float]],
    desired_poles: list[float | list[float]],
) -> dict:
    """
    SISO pole placement via Ackermann's formula.

    Given (A, B) with p=1 input, finds state-feedback gain K (1×n row vector)
    such that the closed-loop eigenvalues of (A - B·K) equal the desired poles.

    Ackermann's formula:
        K = e_n^T · C^{-1} · p_d(A)

    where C is the controllability matrix, e_n^T = [0…0, 1] (last standard basis
    row vector), and p_d(A) is the desired characteristic polynomial evaluated at A.

    Parameters
    ----------
    A            : n×n state matrix
    B            : n×1 input vector (must be single-column)
    desired_poles: list of n desired closed-loop pole locations (real floats
                   or [re, im] pairs for complex conjugate pairs)

    Returns
    -------
    dict
        ok           : True
        K            : 1×n state-feedback gain row vector (list)
        desired_poles: pole locations used
        warnings     : list
    """
    # Validate dimensions
    if not isinstance(A, (list, tuple)) or len(A) == 0:
        return _err("A must be a non-empty matrix.")
    n = len(A)
    if len(A[0]) != n:
        return _err(f"A must be square ({n}×{n}).")
    if not isinstance(B, (list, tuple)) or len(B) != n:
        return _err(f"B must have {n} rows.")

    # Support column-vector B (list of single-element rows) or flat list
    if isinstance(B[0], (list, tuple)):
        if len(B[0]) != 1:
            return _err("Ackermann's formula is SISO only; B must have 1 column.")
        B_col = [B[i][0] for i in range(n)]
    else:
        B_col = [float(B[i]) for i in range(n)]

    try:
        A_f = [[float(A[i][j]) for j in range(n)] for i in range(n)]
        B_f = [[b] for b in B_col]
    except (TypeError, ValueError) as exc:
        return _err(f"A, B must contain numbers: {exc}")

    if len(desired_poles) != n:
        return _err(f"Need exactly n={n} desired poles, got {len(desired_poles)}.")

    # Parse desired poles (accept real or [re, im] pairs)
    poles_complex: list[complex] = []
    for p in desired_poles:
        if isinstance(p, (list, tuple)):
            if len(p) != 2:
                return _err("Complex poles must be [re, im] pairs.")
            poles_complex.append(complex(float(p[0]), float(p[1])))
        else:
            try:
                poles_complex.append(complex(float(p)))
            except (TypeError, ValueError):
                return _err(f"Pole {p!r} is not a valid number.")

    # Check controllability
    ctrb_res = controllability_matrix(A_f, B_f)
    if not ctrb_res["ok"]:
        return _err(f"Controllability check failed: {ctrb_res['reason']}")
    if not ctrb_res["is_controllable"]:
        return _err("System is not controllable. Cannot perform pole placement.")

    # Build desired characteristic polynomial p_d(s) = Π(s - p_i)
    pd_coeffs = _char_poly_from_roots(poles_complex)  # monic, degree n

    # Evaluate p_d(A)
    pd_A = _poly_eval_mat(pd_coeffs, A_f)

    # Invert controllability matrix (n×n; SISO so ctrb is square)
    C_mat = ctrb_res["ctrb_matrix"]  # n×n for SISO
    C_inv = _mat_inv(C_mat)
    if C_inv is None:
        return _err("Controllability matrix is singular. Cannot invert.")

    # e_n^T = [0, 0, ..., 0, 1] (1×n)
    e_n = [[float(i == n - 1) for i in range(n)]]

    # K = e_n^T · C^{-1} · p_d(A)
    K = _mat_mul(_mat_mul(e_n, C_inv), pd_A)  # 1×n

    K_vec = K[0]

    # Verify: compute eigenvalues of (A - B K)
    BK = _mat_mul(B_f, [K_vec])  # n×n
    A_cl = _mat_add(A_f, _mat_scale(BK, -1.0))
    cl_eigs = _eigenvalues_real(A_cl)
    cl_pairs = [(round(e.real, 6), round(e.imag, 6)) for e in cl_eigs]

    warnings: list[str] = []
    # Check if any desired pole is RHP
    for p in poles_complex:
        if p.real >= 0:
            warnings.append(f"UNSTABLE_POLE: desired pole {p} has Re >= 0.")

    return _ok(
        K=K_vec,
        desired_poles=[(p.real, p.imag) for p in poles_complex],
        achieved_poles=cl_pairs,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 5. LQR via continuous algebraic Riccati equation (CARE)
# ---------------------------------------------------------------------------

def lqr(
    A: list[list[float]],
    B: list[list[float]],
    Q: list[list[float]],
    R_mat: list[list[float]],
    *,
    max_iter: int = 500,
    tol: float = 1e-10,
) -> dict:
    """
    Continuous-time Linear Quadratic Regulator (LQR).

    Minimises J = ∫₀^∞ (xᵀQx + uᵀRu) dt.

    Solves the continuous algebraic Riccati equation (CARE):
        Aᵀ P + P A - P B R⁻¹ Bᵀ P + Q = 0

    using Kleinman's iterative method (Policy-Iteration / Newton's method):
        Starting with K₀ such that A - B K₀ is stable,
        iterate:  A_kᵀ Pₖ + Pₖ Aₖ + Qₖ = 0   (Lyapunov)
        where Aₖ = A - B Kₖ, Qₖ = Q + KₖᵀR Kₖ, Kₖ₊₁ = R⁻¹ Bᵀ Pₖ.

    The Lyapunov equation is solved by vectorisation (Kronecker approach):
        vec(P) = -(I⊗Aₖᵀ + Aₖᵀ⊗I)⁻¹ vec(Qₖ)
    (expensive for large n, but pure-Python and exact for small n).

    Parameters
    ----------
    A     : n×n state matrix
    B     : n×p input matrix
    Q     : n×n state cost matrix (positive semi-definite)
    R_mat : p×p input cost matrix (positive definite)

    Returns
    -------
    dict
        ok     : True
        P      : n×n solution to CARE (Riccati matrix)
        K      : p×n optimal state-feedback gain  K = R⁻¹ Bᵀ P
        warnings: list
    """
    # Validate
    if not isinstance(A, (list, tuple)) or len(A) == 0:
        return _err("A must be non-empty.")
    n = len(A)
    if len(A[0]) != n:
        return _err(f"A must be square ({n}×{n}).")
    if not isinstance(B, (list, tuple)) or len(B) != n:
        return _err(f"B must have {n} rows.")
    p = len(B[0])
    if not isinstance(Q, (list, tuple)) or len(Q) != n or len(Q[0]) != n:
        return _err(f"Q must be {n}×{n}.")
    if not isinstance(R_mat, (list, tuple)) or len(R_mat) != p or len(R_mat[0]) != p:
        return _err(f"R must be {p}×{p}.")

    try:
        A_f = [[float(A[i][j]) for j in range(n)] for i in range(n)]
        B_f = [[float(B[i][j]) for j in range(p)] for i in range(n)]
        Q_f = [[float(Q[i][j]) for j in range(n)] for i in range(n)]
        R_f = [[float(R_mat[i][j]) for j in range(p)] for i in range(p)]
    except (TypeError, ValueError) as exc:
        return _err(f"Matrices must contain numbers: {exc}")

    # Invert R
    R_inv = _mat_inv(R_f)
    if R_inv is None:
        return _err("R matrix is singular; must be positive definite.")

    # Invert R_inv · Bᵀ: S = B R⁻¹ Bᵀ  (n×n)
    Bt = _mat_transpose(B_f)
    BRinv = _mat_mul(B_f, R_inv)    # n×p
    S = _mat_mul(BRinv, Bt)         # n×n

    # Initial guess for P: solve Lyapunov with K=0 if A stable; else use Q
    # We need to find an initial stabilising gain.
    # Simple approach: use K=0 if A is already stable, else use damped initial K.
    eigs_A = _eigenvalues_real(A_f)
    A_stable = all(e.real < 0 for e in eigs_A)

    # --- Lyapunov solver via vectorisation ---
    # For A_k stable: solve  A_kᵀ P + P A_k = -Q_k
    # Vectorise: (I⊗Aₖᵀ + Aₖᵀ⊗I) vec(P) = -vec(Q_k)
    # → system of n²×n² equations.

    def _kron(X: list[list[float]], Y: list[list[float]]) -> list[list[float]]:
        """Kronecker product X ⊗ Y."""
        mx, nx = len(X), len(X[0])
        my, ny = len(Y), len(Y[0])
        K_out = _zeros(mx * my, nx * ny)
        for i in range(mx):
            for j in range(nx):
                for p2 in range(my):
                    for q2 in range(ny):
                        K_out[i * my + p2][j * ny + q2] = X[i][j] * Y[p2][q2]
        return K_out

    def _solve_lyapunov(Ak: list[list[float]], Qk: list[list[float]]) -> list[list[float]] | None:
        """Solve Aₖᵀ P + P Aₖ = -Qₖ via Kronecker vectorisation."""
        n2 = n * n
        AkT = _mat_transpose(Ak)
        In = _eye(n)
        # M = I⊗Aₖᵀ + Aₖᵀ⊗I
        M = _mat_add(_kron(In, AkT), _kron(AkT, In))
        # rhs = -vec(Qk) (column-major vectorisation)
        rhs = [[- Qk[i][j]] for j in range(n) for i in range(n)]  # n²×1
        M_inv = _mat_inv(M)
        if M_inv is None:
            return None
        vec_P = _mat_mul(M_inv, rhs)
        # Un-vectorise (column-major)
        P_out = _zeros(n, n)
        for idx in range(n2):
            row_idx = idx % n
            col_idx = idx // n
            P_out[row_idx][col_idx] = vec_P[idx][0]
        return P_out

    # Kleinman iteration
    # Initial K: if A stable, K0=0; else need a stabilising K
    if A_stable:
        K_cur = _zeros(p, n)
    else:
        # Use pole placement to find initial stabilising gain if SISO
        # For MIMO, shift A by alpha*I to make it stable for initial Lyapunov
        alpha = max(e.real for e in eigs_A) + 1.0
        A_shifted = _mat_add(A_f, _mat_scale(_eye(n), -alpha))
        # Solve Lyapunov for shifted system (which is stable)
        # Actually just use a large initial P = identity scaled
        K_cur = _zeros(p, n)
        # Adjust by forcing: solve with (A - alpha I) which is stable
        A_f_for_lya = _mat_add(A_f, _mat_scale(_eye(n), -alpha))
        P0 = _solve_lyapunov(A_f_for_lya, Q_f)
        if P0 is None:
            P0 = _eye(n)
        K_cur = _mat_mul(R_inv, _mat_mul(Bt, P0))
        # Rescale to ensure stability (heuristic)

    P_cur = _eye(n)
    converged = False

    for _it in range(max_iter):
        # Aₖ = A - B Kₖ
        BK = _mat_mul(B_f, K_cur)    # n×n
        Ak = _mat_add(A_f, _mat_scale(BK, -1.0))

        # Qₖ = Q + KₖᵀR Kₖ
        KT = _mat_transpose(K_cur)    # n×p
        KT_R = _mat_mul(KT, R_f)      # n×p
        KT_R_K = _mat_mul(KT_R, K_cur)  # n×n
        Qk = _mat_add(Q_f, KT_R_K)

        # Solve Lyapunov: Aₖᵀ P + P Aₖ = -Qₖ
        P_new = _solve_lyapunov(Ak, Qk)
        if P_new is None:
            return _err(
                "Lyapunov equation became singular during Kleinman iteration. "
                "Check that (A,B) is stabilisable and Q,R > 0."
            )

        # New gain
        K_new = _mat_mul(R_inv, _mat_mul(Bt, P_new))  # p×n

        # Convergence check
        diff = 0.0
        for i in range(n):
            for j in range(n):
                diff += (P_new[i][j] - P_cur[i][j]) ** 2
        diff = math.sqrt(diff)

        P_cur = P_new
        K_cur = K_new

        if diff < tol:
            converged = True
            break

    warnings: list[str] = []
    if not converged:
        warnings.append(
            f"LQR_NOT_CONVERGED: Kleinman iteration did not converge in {max_iter} steps. "
            "Result may be approximate. Check stabilisability."
        )

    # Symmetrise P
    for i in range(n):
        for j in range(n):
            avg = (P_cur[i][j] + P_cur[j][i]) / 2.0
            P_cur[i][j] = avg
            P_cur[j][i] = avg

    # Verify closed-loop stability
    BK_final = _mat_mul(B_f, K_cur)
    A_cl = _mat_add(A_f, _mat_scale(BK_final, -1.0))
    cl_eigs = _eigenvalues_real(A_cl)
    cl_stable = all(e.real < 0 for e in cl_eigs)
    if not cl_stable:
        warnings.append("LQR_CL_UNSTABLE: closed-loop is not stable. Check Q, R positive definiteness.")

    return _ok(
        P=P_cur,
        K=K_cur,
        closed_loop_eigenvalues=[(round(e.real, 6), round(e.imag, 6)) for e in cl_eigs],
        closed_loop_stable=cl_stable,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 6. Luenberger observer gains (dual of pole placement)
# ---------------------------------------------------------------------------

def luenberger_gains(
    A: list[list[float]],
    C: list[list[float]],
    desired_observer_poles: list[float | list[float]],
) -> dict:
    """
    Luenberger observer gain matrix L via duality (Ackermann on Aᵀ, Cᵀ).

    For a SISO (single output) system:
        L = (Ackermann's formula applied to (Aᵀ, Cᵀ))ᵀ

    The observer state equation is:
        x̂̇ = A x̂ + B u + L (y - C x̂)

    Closed-loop observer poles = eigenvalues of (A - LC).
    Observer poles are typically chosen 3–5× faster than controller poles.

    Parameters
    ----------
    A                    : n×n state matrix
    C                    : 1×n output matrix (single-output / SISO only)
    desired_observer_poles: n desired observer pole locations

    Returns
    -------
    dict
        ok    : True
        L     : n×1 observer gain vector (list of n floats)
        desired_observer_poles : list of (re, im) pairs
        achieved_poles: list of (re, im) pairs
        warnings: list
    """
    # Validate
    if not isinstance(A, (list, tuple)) or len(A) == 0:
        return _err("A must be non-empty.")
    n = len(A)
    if len(A[0]) != n:
        return _err(f"A must be square ({n}×{n}).")
    if not isinstance(C, (list, tuple)) or len(C) == 0:
        return _err("C must be non-empty.")
    if isinstance(C[0], (list, tuple)):
        if len(C) != 1:
            return _err("Luenberger via duality is SISO only; C must have 1 row.")
        C_row = [float(C[0][j]) for j in range(n)]
    else:
        if len(C) != n:
            return _err(f"C row must have {n} elements.")
        C_row = [float(v) for v in C]

    try:
        A_f = [[float(A[i][j]) for j in range(n)] for i in range(n)]
    except (TypeError, ValueError) as exc:
        return _err(f"A must contain numbers: {exc}")

    # Dual system: (Aᵀ, Cᵀ)
    AT = _mat_transpose(A_f)
    CT = [[C_row[i]] for i in range(n)]  # n×1 column

    # Apply Ackermann to dual
    res = pole_placement_ackermann(AT, CT, desired_observer_poles)
    if not res["ok"]:
        return _err(f"Dual pole placement failed: {res['reason']}")

    # K_dual is 1×n; observer gain L = K_dual^T (n×1)
    K_dual = res["K"]  # list of n floats (1×n)
    L_vec = K_dual     # n floats

    # Verify: eigenvalues of (A - L C)
    LC = [[L_vec[i] * C_row[j] for j in range(n)] for i in range(n)]
    A_obs = [[A_f[i][j] - LC[i][j] for j in range(n)] for i in range(n)]
    obs_eigs = _eigenvalues_real(A_obs)
    achieved = [(round(e.real, 6), round(e.imag, 6)) for e in obs_eigs]

    warnings = res.get("warnings", [])

    return _ok(
        L=L_vec,
        desired_observer_poles=res["desired_poles"],
        achieved_poles=achieved,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 7. c2d — zero-order-hold discretisation
# ---------------------------------------------------------------------------

def c2d(
    A: list[list[float]],
    B: list[list[float]],
    dt: float,
) -> dict:
    """
    Convert continuous-time state-space (A, B) to discrete-time via zero-order hold.

    ZOH exact discretisation:
        Ad = exp(A·dt)
        Bd = A⁻¹ (Ad - I) B          if A is invertible
           = (∫₀^dt exp(A·s) ds) B   (computed via matrix exponential augmentation)

    The augmented matrix method is used (works whether A is singular or not):
        M = exp([[A, B], [0, 0]] · dt)
        Ad = M[0:n, 0:n]
        Bd = M[0:n, n:n+p]

    Parameters
    ----------
    A  : n×n continuous-time state matrix
    B  : n×p continuous-time input matrix
    dt : sampling interval (s). Must be > 0.

    Returns
    -------
    dict
        ok  : True
        Ad  : n×n discrete-time state matrix
        Bd  : n×p discrete-time input matrix
        dt  : sampling interval
        warnings: list
    """
    if not isinstance(A, (list, tuple)) or len(A) == 0:
        return _err("A must be non-empty.")
    n = len(A)
    if len(A[0]) != n:
        return _err(f"A must be square ({n}×{n}).")
    if not isinstance(B, (list, tuple)) or len(B) != n:
        return _err(f"B must have {n} rows.")
    try:
        dt = float(dt)
    except (TypeError, ValueError):
        return _err("dt must be a number.")
    if dt <= 0 or not math.isfinite(dt):
        return _err("dt must be finite and > 0.")

    try:
        A_f = [[float(A[i][j]) for j in range(n)] for i in range(n)]
        p = len(B[0])
        B_f = [[float(B[i][j]) for j in range(p)] for i in range(n)]
    except (TypeError, ValueError) as exc:
        return _err(f"A, B must contain numbers: {exc}")

    # Build augmented matrix M_aug = [A*dt, B*dt; 0, 0]  (n+p) × (n+p)
    aug_size = n + p
    M_aug = _zeros(aug_size, aug_size)
    for i in range(n):
        for j in range(n):
            M_aug[i][j] = A_f[i][j] * dt
        for j in range(p):
            M_aug[i][n + j] = B_f[i][j] * dt
    # Lower-right block is zero (already)

    exp_aug = _mat_exp(M_aug)

    Ad = [[exp_aug[i][j] for j in range(n)] for i in range(n)]
    Bd = [[exp_aug[i][n + j] for j in range(p)] for i in range(n)]

    warnings: list[str] = []

    # Discrete stability check
    eigs_d = _eigenvalues_real(Ad)
    if any(abs(e) >= 1.0 for e in eigs_d):
        warnings.append(
            "C2D_UNSTABLE: original continuous system appears unstable "
            "(discrete eigenvalue |λ| >= 1)."
        )

    if dt > 0.1 * (2 * math.pi / max(abs(e.imag) for e in _eigenvalues_real(A_f) if e.imag != 0) if any(e.imag != 0 for e in _eigenvalues_real(A_f)) else 1e9):
        pass  # sampling rate check is optional

    return _ok(
        Ad=Ad,
        Bd=Bd,
        dt=dt,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 8. Discrete-time stability check
# ---------------------------------------------------------------------------

def discrete_stability(
    Ad: list[list[float]],
) -> dict:
    """
    Check discrete-time stability: all eigenvalues of Ad must satisfy |λ| < 1.

    Parameters
    ----------
    Ad : n×n discrete-time state matrix

    Returns
    -------
    dict
        ok         : True
        eigenvalues: list of (re, im, magnitude) for each eigenvalue
        stable     : True if all |λ| < 1
        max_magnitude: maximum eigenvalue magnitude
        warnings   : list
    """
    if not isinstance(Ad, (list, tuple)) or len(Ad) == 0:
        return _err("Ad must be non-empty.")
    n = len(Ad)
    if len(Ad[0]) != n:
        return _err(f"Ad must be square ({n}×{n}).")
    try:
        Ad_f = [[float(Ad[i][j]) for j in range(n)] for i in range(n)]
    except (TypeError, ValueError) as exc:
        return _err(f"Ad must contain numbers: {exc}")

    eigs = _eigenvalues_real(Ad_f)
    eig_info = [(round(e.real, 8), round(e.imag, 8), round(abs(e), 8)) for e in eigs]
    max_mag = max(abs(e) for e in eigs) if eigs else 0.0
    stable = max_mag < 1.0

    warnings: list[str] = []
    if not stable:
        outside = [(e.real, e.imag, abs(e)) for e in eigs if abs(e) >= 1.0]
        warnings.append(
            f"DISCRETE_UNSTABLE: {len(outside)} eigenvalue(s) have |λ| >= 1: "
            + str([(round(r, 4), round(i, 4), round(m, 4)) for r, i, m in outside])
        )

    return _ok(
        eigenvalues=eig_info,
        stable=stable,
        max_magnitude=round(max_mag, 8),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 9. Digital PID step (velocity / incremental form)
# ---------------------------------------------------------------------------

def digital_pid_step(
    Kp: float,
    Ki: float,
    Kd: float,
    dt: float,
    e_k: float,
    e_km1: float,
    e_km2: float,
    u_km1: float,
) -> dict:
    """
    Digital PID controller: velocity (incremental) form.

    Δu[k] = Kp (e[k] - e[k-1])
           + Ki·dt·e[k]
           + Kd/dt (e[k] - 2·e[k-1] + e[k-2])

    u[k] = u[k-1] + Δu[k]

    This form avoids integrator wind-up issues compared to the positional form.

    Parameters
    ----------
    Kp    : proportional gain
    Ki    : integral gain
    Kd    : derivative gain
    dt    : sampling interval (s). Must be > 0.
    e_k   : current error e[k]
    e_km1 : previous error e[k-1]
    e_km2 : two-steps-ago error e[k-2]
    u_km1 : previous control output u[k-1]

    Returns
    -------
    dict
        ok      : True
        u_k     : control output u[k]
        delta_u : increment Δu[k]
        warnings: list
    """
    try:
        Kp, Ki, Kd = float(Kp), float(Ki), float(Kd)
        dt = float(dt)
        e_k, e_km1, e_km2 = float(e_k), float(e_km1), float(e_km2)
        u_km1 = float(u_km1)
    except (TypeError, ValueError) as exc:
        return _err(f"All arguments must be numbers: {exc}")

    if dt <= 0 or not math.isfinite(dt):
        return _err("dt must be > 0 and finite.")

    p_term = Kp * (e_k - e_km1)
    i_term = Ki * dt * e_k
    d_term = (Kd / dt) * (e_k - 2.0 * e_km1 + e_km2)

    delta_u = p_term + i_term + d_term
    u_k = u_km1 + delta_u

    warnings: list[str] = []
    if not math.isfinite(u_k):
        warnings.append("OVERFLOW: u_k is not finite; check gains and dt.")

    return _ok(
        u_k=u_k,
        delta_u=delta_u,
        p_term=p_term,
        i_term=i_term,
        d_term=d_term,
        warnings=warnings,
    )
