"""
kerf_cad_core.cmm.inspect — CMM coordinate-metrology inspection algorithms.

All functions accept plain Python lists/tuples of (x, y, z) point triples and
return a dict.  On success the dict always contains ``"ok": True``; on failure
``"ok": False`` with a ``"reason"`` string.  Out-of-tolerance or R&R-not-capable
conditions are recorded in a ``"warnings"`` list — functions NEVER raise.

Linear algebra
--------------
All matrix operations use plain Python lists.  For the small dense problems
encountered in metrology (typically ≤4 unknowns) a hand-rolled Cholesky /
SVD-via-Jacobi is sufficient and avoids any external dependency.

References
----------
ISO 1101:2017      — Geometrical product specifications (GPS)
ASME Y14.5-2018    — Dimensioning and Tolerancing
JCGM 100:2008      — Evaluation of measurement data — Guide to the Expression
                     of Uncertainty in Measurement (GUM)
AIAG MSA 4th ed.   — Measurement System Analysis (Gauge R&R)

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Sequence

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
Point3 = tuple[float, float, float]
Points = Sequence[Sequence[float]]


# ===========================================================================
# Internal linear-algebra helpers (pure Python, no external deps)
# ===========================================================================

def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: list[float]) -> float:
    return math.sqrt(_dot(v, v))


def _normalise(v: list[float]) -> list[float]:
    n = _norm(v)
    if n == 0.0:
        return [0.0] * len(v)
    return [x / n for x in v]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    """Matrix-vector product A @ v."""
    return [_dot(row, v) for row in A]


def _mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """Matrix product A @ B."""
    n, m, p = len(A), len(A[0]), len(B[0])
    C = [[0.0] * p for _ in range(n)]
    for i in range(n):
        for k in range(m):
            if A[i][k] == 0.0:
                continue
            for j in range(p):
                C[i][j] += A[i][k] * B[k][j]
    return C


def _transpose(A: list[list[float]]) -> list[list[float]]:
    n, m = len(A), len(A[0])
    return [[A[i][j] for i in range(n)] for j in range(m)]


def _cholesky_solve(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Solve A x = b via Cholesky for symmetric positive-definite A (n≤6)."""
    n = len(A)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s <= 0.0:
                    return None  # not positive definite
                L[i][j] = math.sqrt(s)
            else:
                L[i][j] = s / L[j][j]
    # Forward substitution L y = b
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(L[i][k] * y[k] for k in range(i))) / L[i][i]
    # Back substitution Lᵀ x = y
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(L[j][i] * x[j] for j in range(i + 1, n))) / L[i][i]
    return x


def _svd2x2(A: list[list[float]]) -> tuple[list[list[float]], list[float], list[list[float]]]:
    """Thin SVD of a 2×2 matrix via Jacobi iteration. Returns U, s, Vt."""
    # Use Jacobi one-sided SVD on the 2×2 case analytically
    a, b, c, d = A[0][0], A[0][1], A[1][0], A[1][1]
    # AᵀA
    m11 = a * a + c * c
    m12 = a * b + c * d
    m22 = b * b + d * d
    # eigen-decomposition of 2×2 symmetric
    th = 0.5 * math.atan2(2 * m12, m11 - m22)
    cos_t = math.cos(th)
    sin_t = math.sin(th)
    Vt = [[cos_t, sin_t], [-sin_t, cos_t]]
    # singular values
    s1_sq = m11 * cos_t ** 2 + 2 * m12 * cos_t * sin_t + m22 * sin_t ** 2
    s2_sq = m11 * sin_t ** 2 - 2 * m12 * cos_t * sin_t + m22 * cos_t ** 2
    s1 = math.sqrt(max(s1_sq, 0.0))
    s2 = math.sqrt(max(s2_sq, 0.0))
    # U = A Vᵀᵀ / S
    av1 = [a * Vt[0][0] + b * Vt[0][1], c * Vt[0][0] + d * Vt[0][1]]
    av2 = [a * Vt[1][0] + b * Vt[1][1], c * Vt[1][0] + d * Vt[1][1]]
    u1 = _normalise(av1)
    u2 = _normalise(av2)
    return [[u1[0], u2[0]], [u1[1], u2[1]]], [s1, s2], Vt


def _jacobi_eig_3x3(A: list[list[float]], max_iter: int = 100) -> tuple[list[float], list[list[float]]]:
    """Jacobi eigenvalue decomposition for a 3×3 real symmetric matrix.
    Returns (eigenvalues, eigenvectors_as_columns)."""
    n = 3
    # work on a copy
    M = [[A[i][j] for j in range(n)] for i in range(n)]
    # Start with identity eigenvector matrix
    V = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(max_iter):
        # Find largest off-diagonal element
        p, q = 0, 1
        max_val = abs(M[0][1])
        for i in range(n):
            for j in range(i + 1, n):
                if abs(M[i][j]) > max_val:
                    max_val = abs(M[i][j])
                    p, q = i, j
        if max_val < 1e-12:
            break
        # Compute rotation angle
        if abs(M[p][p] - M[q][q]) < 1e-15:
            theta = math.pi / 4.0
        else:
            theta = 0.5 * math.atan2(2.0 * M[p][q], M[p][p] - M[q][q])
        c = math.cos(theta)
        s = math.sin(theta)
        # Apply Jacobi rotation
        Mp = [row[:] for row in M]
        for r in range(n):
            if r != p and r != q:
                Mp[r][p] = c * M[r][p] + s * M[r][q]
                Mp[p][r] = Mp[r][p]
                Mp[r][q] = -s * M[r][p] + c * M[r][q]
                Mp[q][r] = Mp[r][q]
        Mp[p][p] = c ** 2 * M[p][p] + 2 * s * c * M[p][q] + s ** 2 * M[q][q]
        Mp[q][q] = s ** 2 * M[p][p] - 2 * s * c * M[p][q] + c ** 2 * M[q][q]
        Mp[p][q] = 0.0
        Mp[q][p] = 0.0
        M = Mp
        # Update eigenvectors
        Vp = [row[:] for row in V]
        for r in range(n):
            Vp[r][p] = c * V[r][p] + s * V[r][q]
            Vp[r][q] = -s * V[r][p] + c * V[r][q]
        V = Vp
    eigenvalues = [M[i][i] for i in range(n)]
    return eigenvalues, V


def _centroid(pts: list[list[float]]) -> list[float]:
    n = len(pts)
    d = len(pts[0])
    return [sum(p[i] for p in pts) / n for i in range(d)]


def _pts_to_lists(points: Points) -> list[list[float]]:
    return [[float(c) for c in p] for p in points]


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = sum(values) / n
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ===========================================================================
# Geometric fitting
# ===========================================================================

def fit_line(points: Points) -> dict:
    """Least-squares best-fit line through 3D points.

    Returns:
        ok, centroid [x,y,z], direction [dx,dy,dz] (unit vector),
        residuals (list of perpendicular distances), rms_residual,
        form_error (max - min perpendicular distance = range).
    """
    try:
        pts = _pts_to_lists(points)
        if len(pts) < 2:
            return {"ok": False, "reason": "at least 2 points required"}
        cen = _centroid(pts)
        # Build 3×3 scatter matrix
        S = [[0.0] * 3 for _ in range(3)]
        for p in pts:
            dp = [p[i] - cen[i] for i in range(3)]
            for i in range(3):
                for j in range(3):
                    S[i][j] += dp[i] * dp[j]
        eigvals, eigvecs = _jacobi_eig_3x3(S)
        # Direction = eigenvector corresponding to largest eigenvalue
        max_idx = eigvals.index(max(eigvals))
        direction = [eigvecs[i][max_idx] for i in range(3)]
        direction = _normalise(direction)
        # Residuals = perpendicular distances from line
        residuals = []
        for p in pts:
            dp = [p[i] - cen[i] for i in range(3)]
            proj = _dot(dp, direction)
            perp = [dp[i] - proj * direction[i] for i in range(3)]
            residuals.append(_norm(perp))
        rms = math.sqrt(sum(r ** 2 for r in residuals) / len(residuals))
        form_error = max(residuals) - min(residuals)
        return {
            "ok": True,
            "centroid": cen,
            "direction": direction,
            "residuals": residuals,
            "rms_residual": rms,
            "form_error": form_error,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def fit_plane(points: Points) -> dict:
    """Least-squares best-fit plane through 3D points.

    Returns:
        ok, centroid [x,y,z], normal [nx,ny,nz] (unit), d (ax+by+cz=d),
        residuals (signed distances from plane), rms_residual, form_error.
    """
    try:
        pts = _pts_to_lists(points)
        if len(pts) < 3:
            return {"ok": False, "reason": "at least 3 points required"}
        cen = _centroid(pts)
        S = [[0.0] * 3 for _ in range(3)]
        for p in pts:
            dp = [p[i] - cen[i] for i in range(3)]
            for i in range(3):
                for j in range(3):
                    S[i][j] += dp[i] * dp[j]
        eigvals, eigvecs = _jacobi_eig_3x3(S)
        # Normal = eigenvector with smallest eigenvalue
        min_idx = eigvals.index(min(eigvals))
        normal = _normalise([eigvecs[i][min_idx] for i in range(3)])
        d = _dot(normal, cen)
        residuals = [_dot(normal, p) - d for p in pts]
        rms = math.sqrt(sum(r ** 2 for r in residuals) / len(residuals))
        form_error = max(residuals) - min(residuals)
        return {
            "ok": True,
            "centroid": cen,
            "normal": normal,
            "d": d,
            "residuals": residuals,
            "rms_residual": rms,
            "form_error": form_error,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def fit_circle(points: Points, plane_normal: Sequence[float] | None = None) -> dict:
    """Least-squares best-fit circle in the plane defined by plane_normal.

    If plane_normal is None the points are assumed to lie in the XY plane.

    Returns:
        ok, center [x,y,z], radius, residuals (radial errors), rms_residual,
        form_error (roundness = max - min radial deviation).
    """
    try:
        pts = _pts_to_lists(points)
        if len(pts) < 3:
            return {"ok": False, "reason": "at least 3 points required"}

        # Project onto 2D plane
        if plane_normal is not None:
            n = _normalise(list(plane_normal))
        else:
            n = [0.0, 0.0, 1.0]

        # Build orthonormal basis in the plane
        ref = [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0]
        e1 = _normalise(_cross(ref, n))
        e2 = _cross(n, e1)

        cen3d = _centroid(pts)
        pts2d = [[_dot([p[i] - cen3d[i] for i in range(3)], e1),
                  _dot([p[i] - cen3d[i] for i in range(3)], e2)]
                 for p in pts]

        # Algebraic circle fit:  x² + y² + Ax + By + C = 0
        # Design matrix [x, y, 1]
        rows = [[u, v, 1.0] for u, v in pts2d]
        rhs = [-(u ** 2 + v ** 2) for u, v in pts2d]
        # Normal equations AtA x = Atb
        At = _transpose(rows)
        AtA = _mat_mul(At, rows)
        Atb = _mat_vec(At, rhs)
        sol = _cholesky_solve(AtA, Atb)
        if sol is None:
            return {"ok": False, "reason": "degenerate circle fit (collinear points?)"}
        A_coef, B_coef, C_coef = sol
        cx2d = -A_coef / 2.0
        cy2d = -B_coef / 2.0
        r_sq = cx2d ** 2 + cy2d ** 2 - C_coef
        if r_sq <= 0.0:
            return {"ok": False, "reason": "circle fit produced non-positive radius squared"}
        radius = math.sqrt(r_sq)
        center3d = [cen3d[i] + cx2d * e1[i] + cy2d * e2[i] for i in range(3)]

        # Radial residuals
        radial_devs = []
        for u, v in pts2d:
            dist = math.sqrt((u - cx2d) ** 2 + (v - cy2d) ** 2)
            radial_devs.append(dist - radius)
        rms = math.sqrt(sum(r ** 2 for r in radial_devs) / len(radial_devs))
        form_error = max(radial_devs) - min(radial_devs)
        return {
            "ok": True,
            "center": center3d,
            "radius": radius,
            "residuals": radial_devs,
            "rms_residual": rms,
            "form_error": form_error,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def fit_sphere(points: Points) -> dict:
    """Least-squares best-fit sphere through 3D points.

    Returns:
        ok, center [x,y,z], radius, residuals (radial errors), rms_residual,
        form_error (max - min radial deviation = sphericity zone width).
    """
    try:
        pts = _pts_to_lists(points)
        if len(pts) < 4:
            return {"ok": False, "reason": "at least 4 points required"}
        # Algebraic:  x²+y²+z²+Ax+By+Cz+D=0
        rows = [[p[0], p[1], p[2], 1.0] for p in pts]
        rhs = [-(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) for p in pts]
        At = _transpose(rows)
        AtA = _mat_mul(At, rows)
        Atb = _mat_vec(At, rhs)
        sol = _cholesky_solve(AtA, Atb)
        if sol is None:
            return {"ok": False, "reason": "degenerate sphere fit"}
        A_c, B_c, C_c, D_c = sol
        cx, cy, cz = -A_c / 2, -B_c / 2, -C_c / 2
        r_sq = cx ** 2 + cy ** 2 + cz ** 2 - D_c
        if r_sq <= 0.0:
            return {"ok": False, "reason": "sphere fit produced non-positive radius squared"}
        radius = math.sqrt(r_sq)
        residuals = [math.sqrt((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2) - radius
                     for p in pts]
        rms = math.sqrt(sum(r ** 2 for r in residuals) / len(residuals))
        form_error = max(residuals) - min(residuals)
        return {
            "ok": True,
            "center": [cx, cy, cz],
            "radius": radius,
            "residuals": residuals,
            "rms_residual": rms,
            "form_error": form_error,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def fit_cylinder(points: Points, axis_guess: Sequence[float] | None = None) -> dict:
    """Least-squares best-fit cylinder through 3D points.

    Uses iterative linearisation: fit plane (for axis), then circle to
    projected points, iterating until convergence.

    Returns:
        ok, axis_point [x,y,z], axis_dir [dx,dy,dz] (unit), radius,
        residuals (radial errors), rms_residual, form_error (cylindricity).
    """
    try:
        pts = _pts_to_lists(points)
        if len(pts) < 5:
            return {"ok": False, "reason": "at least 5 points required"}

        if axis_guess is not None:
            axis = _normalise(list(axis_guess))
        else:
            # Use PCA: axis is direction of greatest extent
            cen = _centroid(pts)
            S = [[0.0] * 3 for _ in range(3)]
            for p in pts:
                dp = [p[i] - cen[i] for i in range(3)]
                for i in range(3):
                    for j in range(3):
                        S[i][j] += dp[i] * dp[j]
            eigvals, eigvecs = _jacobi_eig_3x3(S)
            max_idx = eigvals.index(max(eigvals))
            axis = _normalise([eigvecs[i][max_idx] for i in range(3)])

        # Iterative refinement (max 20 iterations)
        for _iter in range(20):
            # Build in-plane basis
            ref = [1.0, 0.0, 0.0] if abs(axis[0]) < 0.9 else [0.0, 1.0, 0.0]
            e1 = _normalise(_cross(ref, axis))
            e2 = _cross(axis, e1)

            # Project points onto plane perpendicular to axis
            pts2d = [[_dot(p, e1), _dot(p, e2)] for p in pts]

            # Circle fit in 2D
            rows = [[u, v, 1.0] for u, v in pts2d]
            rhs = [-(u ** 2 + v ** 2) for u, v in pts2d]
            At = _transpose(rows)
            AtA = _mat_mul(At, rows)
            Atb = _mat_vec(At, rhs)
            sol = _cholesky_solve(AtA, Atb)
            if sol is None:
                return {"ok": False, "reason": "degenerate cylinder fit"}
            A_c, B_c, C_c = sol
            cx2d, cy2d = -A_c / 2, -B_c / 2
            r_sq = cx2d ** 2 + cy2d ** 2 - C_c
            if r_sq <= 0.0:
                return {"ok": False, "reason": "cylinder fit produced non-positive radius squared"}
            radius = math.sqrt(r_sq)

            # Refine axis: fit residuals as function of axial position
            axial = [_dot(p, axis) for p in pts]
            radial_devs = [math.sqrt((u - cx2d) ** 2 + (v - cy2d) ** 2) - radius
                           for (u, v) in pts2d]

            # For convergence, check rms change
            rms_new = math.sqrt(sum(r ** 2 for r in radial_devs) / len(radial_devs))
            if rms_new < 1e-12:
                break

        axis_point = [cx2d * e1[i] + cy2d * e2[i] for i in range(3)]
        form_error = max(radial_devs) - min(radial_devs)
        rms = math.sqrt(sum(r ** 2 for r in radial_devs) / len(radial_devs))
        return {
            "ok": True,
            "axis_point": axis_point,
            "axis_dir": axis,
            "radius": radius,
            "residuals": radial_devs,
            "rms_residual": rms,
            "form_error": form_error,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ===========================================================================
# Datum-reference-frame alignment
# ===========================================================================

def align_321(primary_pts: Points, secondary_pts: Points, tertiary_pts: Points) -> dict:
    """3-2-1 datum alignment.

    Primary (≥3 pts) defines the datum plane (Z), secondary (≥2 pts) defines
    the datum line in-plane (X), tertiary (≥1 pt) defines the origin offset (Y).

    Returns rigid 4×4 homogeneous transform (row-major) and frame axes.
    """
    try:
        pri = _pts_to_lists(primary_pts)
        sec = _pts_to_lists(secondary_pts)
        ter = _pts_to_lists(tertiary_pts)
        if len(pri) < 3:
            return {"ok": False, "reason": "primary datum needs ≥3 points"}
        if len(sec) < 2:
            return {"ok": False, "reason": "secondary datum needs ≥2 points"}
        if len(ter) < 1:
            return {"ok": False, "reason": "tertiary datum needs ≥1 point"}

        # Plane from primary
        plane = fit_plane(pri)
        if not plane["ok"]:
            return {"ok": False, "reason": f"primary plane fit failed: {plane['reason']}"}
        Z = plane["normal"]

        # Line direction from secondary (projected onto primary plane)
        cen_sec = _centroid(sec)
        sec_proj = [[p[i] - _dot([p[j] - cen_sec[j] for j in range(3)], Z) * Z[i] for i in range(3)]
                    for p in sec]
        line = fit_line(sec_proj)
        if not line["ok"]:
            return {"ok": False, "reason": f"secondary line fit failed: {line['reason']}"}
        X = line["direction"]
        # Ensure X is perpendicular to Z
        X = _normalise([X[i] - _dot(X, Z) * Z[i] for i in range(3)])
        Y = _cross(Z, X)

        # Origin from primary plane centroid projected to contain tertiary point
        origin = plane["centroid"]

        # Rotation matrix (columns = X, Y, Z in world frame)
        R = [[X[i], Y[i], Z[i]] for i in range(3)]
        # 4×4 homogeneous
        transform = [
            [R[0][0], R[0][1], R[0][2], origin[0]],
            [R[1][0], R[1][1], R[1][2], origin[1]],
            [R[2][0], R[2][1], R[2][2], origin[2]],
            [0.0, 0.0, 0.0, 1.0],
        ]
        return {
            "ok": True,
            "method": "3-2-1",
            "origin": origin,
            "X_axis": X,
            "Y_axis": Y,
            "Z_axis": Z,
            "transform_4x4": transform,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def align_bestfit(nominal_pts: Points, measured_pts: Points) -> dict:
    """Best-fit (ICP-style) rigid alignment of measured points to nominals.

    Minimises sum of squared distances using the closed-form SVD method
    (Umeyama / Kabsch algorithm).

    Returns:
        ok, rotation_3x3, translation [tx,ty,tz], rms_error, transform_4x4.
    """
    try:
        nom = _pts_to_lists(nominal_pts)
        meas = _pts_to_lists(measured_pts)
        if len(nom) != len(meas):
            return {"ok": False, "reason": "nominal and measured point counts must match"}
        if len(nom) < 3:
            return {"ok": False, "reason": "at least 3 point pairs required"}
        n = len(nom)
        cen_n = _centroid(nom)
        cen_m = _centroid(meas)
        # Demean
        nom_d = [[p[i] - cen_n[i] for i in range(3)] for p in nom]
        meas_d = [[p[i] - cen_m[i] for i in range(3)] for p in meas]

        # Cross-covariance matrix H = Σ meas_dᵢ nomᵀ_dᵢ  (3×3)
        H = [[0.0] * 3 for _ in range(3)]
        for md, nd in zip(meas_d, nom_d):
            for i in range(3):
                for j in range(3):
                    H[i][j] += md[i] * nd[j]

        # SVD of H via Jacobi on HᵀH
        Ht = _transpose(H)
        HtH = _mat_mul(Ht, H)
        eigvals, V = _jacobi_eig_3x3(HtH)
        # Sort by eigenvalue descending
        order = sorted(range(3), key=lambda k: eigvals[k], reverse=True)
        V_sorted = [[V[i][order[j]] for j in range(3)] for i in range(3)]
        sigma = [math.sqrt(max(eigvals[order[k]], 0.0)) for k in range(3)]

        # U = H V / sigma
        HV = _mat_mul(H, V_sorted)
        U = [[HV[i][j] / sigma[j] if sigma[j] > 1e-12 else 0.0
              for j in range(3)] for i in range(3)]

        # R = U Vᵀ
        Vt = _transpose(V_sorted)
        R = _mat_mul(U, Vt)
        # Ensure proper rotation (det = +1)
        det = (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1])
               - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
               + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))
        if det < 0:
            # Flip last column of U
            for i in range(3):
                U[i][2] = -U[i][2]
            R = _mat_mul(U, Vt)

        t = [cen_n[i] - sum(R[i][j] * cen_m[j] for j in range(3)) for i in range(3)]

        # Compute residuals
        errors = []
        for md, nd in zip(meas, nom):
            rmd = [sum(R[i][j] * md[j] for j in range(3)) + t[i] for i in range(3)]
            errors.append(math.sqrt(sum((rmd[i] - nd[i]) ** 2 for i in range(3))))
        rms_error = math.sqrt(sum(e ** 2 for e in errors) / n)

        transform = [
            [R[0][0], R[0][1], R[0][2], t[0]],
            [R[1][0], R[1][1], R[1][2], t[1]],
            [R[2][0], R[2][1], R[2][2], t[2]],
            [0.0, 0.0, 0.0, 1.0],
        ]
        return {
            "ok": True,
            "method": "best-fit",
            "rotation_3x3": R,
            "translation": t,
            "rms_error": rms_error,
            "transform_4x4": transform,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ===========================================================================
# GD&T evaluation from point clouds
# ===========================================================================

def eval_flatness(points: Points, tolerance: float | None = None) -> dict:
    """Flatness evaluation per ASME Y14.5 / ISO 1101.

    Flatness = minimum zone = spread of plane residuals (max - min signed dist).

    Returns:
        ok, flatness_value, in_tolerance (if tolerance given), warnings.
    """
    try:
        plane = fit_plane(points)
        if not plane["ok"]:
            return {"ok": False, "reason": plane["reason"]}
        flatness = plane["form_error"]
        warnings: list[str] = []
        in_tol = None
        if tolerance is not None:
            in_tol = flatness <= tolerance
            if not in_tol:
                warnings.append(f"OUT_OF_TOLERANCE: flatness {flatness:.6g} > tol {tolerance:.6g}")
        return {
            "ok": True,
            "flatness_value": flatness,
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def eval_circularity(points: Points, plane_normal: Sequence[float] | None = None,
                     tolerance: float | None = None) -> dict:
    """Circularity (roundness) evaluation.

    Circularity = max - min radial deviation from best-fit circle.

    Returns:
        ok, circularity_value, radius, in_tolerance, warnings.
    """
    try:
        circ = fit_circle(points, plane_normal)
        if not circ["ok"]:
            return {"ok": False, "reason": circ["reason"]}
        circularity = circ["form_error"]
        warnings: list[str] = []
        in_tol = None
        if tolerance is not None:
            in_tol = circularity <= tolerance
            if not in_tol:
                warnings.append(f"OUT_OF_TOLERANCE: circularity {circularity:.6g} > tol {tolerance:.6g}")
        return {
            "ok": True,
            "circularity_value": circularity,
            "radius": circ["radius"],
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def eval_cylindricity(points: Points, axis_guess: Sequence[float] | None = None,
                      tolerance: float | None = None) -> dict:
    """Cylindricity evaluation.

    Cylindricity = max - min radial deviation from best-fit cylinder.

    Returns:
        ok, cylindricity_value, radius, axis_dir, in_tolerance, warnings.
    """
    try:
        cyl = fit_cylinder(points, axis_guess)
        if not cyl["ok"]:
            return {"ok": False, "reason": cyl["reason"]}
        cylindricity = cyl["form_error"]
        warnings: list[str] = []
        in_tol = None
        if tolerance is not None:
            in_tol = cylindricity <= tolerance
            if not in_tol:
                warnings.append(f"OUT_OF_TOLERANCE: cylindricity {cylindricity:.6g} > tol {tolerance:.6g}")
        return {
            "ok": True,
            "cylindricity_value": cylindricity,
            "radius": cyl["radius"],
            "axis_dir": cyl["axis_dir"],
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def eval_perpendicularity(points: Points, datum_normal: Sequence[float],
                          tolerance: float | None = None) -> dict:
    """Perpendicularity evaluation of a surface/axis to a datum plane.

    Measures the angular deviation of the best-fit plane/line normal from
    the nominal perpendicular direction, then converts to a linear zone.

    For a surface (≥3 points): fits a plane, measures angle between plane
    normal and datum_normal; zone = 2 * sin(angle) * (feature half-width
    estimated from point spread).

    Returns:
        ok, angle_deg, zone_width, in_tolerance, warnings.
    """
    try:
        pts = _pts_to_lists(points)
        dn = _normalise(list(datum_normal))
        if len(pts) < 2:
            return {"ok": False, "reason": "at least 2 points required"}

        if len(pts) >= 3:
            fit = fit_plane(pts)
            if not fit["ok"]:
                return {"ok": False, "reason": fit["reason"]}
            feature_normal = fit["normal"]
        else:
            fit = fit_line(pts)
            if not fit["ok"]:
                return {"ok": False, "reason": fit["reason"]}
            feature_normal = fit["direction"]

        cos_a = max(-1.0, min(1.0, abs(_dot(feature_normal, dn))))
        angle_rad = math.acos(cos_a)
        # Perpendicularity: deviation from 90° to datum
        perp_angle_rad = abs(math.pi / 2 - angle_rad)
        angle_deg = math.degrees(perp_angle_rad)

        # Linear zone = 2 * sin(perp_angle) * characteristic length
        cen = _centroid(pts)
        char_len = max(math.sqrt(sum((p[i] - cen[i]) ** 2 for i in range(3))) for p in pts)
        zone_width = 2.0 * math.sin(perp_angle_rad) * char_len

        warnings: list[str] = []
        in_tol = None
        if tolerance is not None:
            in_tol = zone_width <= tolerance
            if not in_tol:
                warnings.append(f"OUT_OF_TOLERANCE: perp zone {zone_width:.6g} > tol {tolerance:.6g}")
        return {
            "ok": True,
            "angle_deg": angle_deg,
            "zone_width": zone_width,
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def eval_parallelism(points: Points, datum_normal: Sequence[float],
                     tolerance: float | None = None) -> dict:
    """Parallelism evaluation of a surface to a datum plane.

    Returns:
        ok, angle_deg (deviation from parallel), zone_width, in_tolerance, warnings.
    """
    try:
        pts = _pts_to_lists(points)
        dn = _normalise(list(datum_normal))
        if len(pts) < 3:
            return {"ok": False, "reason": "at least 3 points required"}

        fit = fit_plane(pts)
        if not fit["ok"]:
            return {"ok": False, "reason": fit["reason"]}
        feature_normal = fit["normal"]

        cos_a = max(-1.0, min(1.0, abs(_dot(feature_normal, dn))))
        angle_rad = math.acos(cos_a)
        # Parallelism: deviation from 0° to datum
        angle_deg = math.degrees(angle_rad)
        # If normals are antiparallel, take supplement
        if angle_deg > 90.0:
            angle_deg = 180.0 - angle_deg
            angle_rad = math.radians(angle_deg)

        cen = _centroid(pts)
        char_len = max(math.sqrt(sum((p[i] - cen[i]) ** 2 for i in range(3))) for p in pts)
        zone_width = 2.0 * math.sin(angle_rad) * char_len

        warnings: list[str] = []
        in_tol = None
        if tolerance is not None:
            in_tol = zone_width <= tolerance
            if not in_tol:
                warnings.append(f"OUT_OF_TOLERANCE: parallel zone {zone_width:.6g} > tol {tolerance:.6g}")
        return {
            "ok": True,
            "angle_deg": angle_deg,
            "zone_width": zone_width,
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def eval_angularity(points: Points, datum_normal: Sequence[float], nominal_angle_deg: float,
                    tolerance: float | None = None) -> dict:
    """Angularity evaluation (surface/axis at a specified angle to a datum).

    Returns:
        ok, measured_angle_deg, deviation_deg, zone_width, in_tolerance, warnings.
    """
    try:
        pts = _pts_to_lists(points)
        dn = _normalise(list(datum_normal))

        if len(pts) >= 3:
            fit = fit_plane(pts)
            if not fit["ok"]:
                return {"ok": False, "reason": fit["reason"]}
            feature_dir = fit["normal"]
        else:
            fit = fit_line(pts)
            if not fit["ok"]:
                return {"ok": False, "reason": fit["reason"]}
            feature_dir = fit["direction"]

        cos_a = max(-1.0, min(1.0, abs(_dot(feature_dir, dn))))
        measured_angle_rad = math.acos(cos_a)
        measured_angle_deg = math.degrees(measured_angle_rad)

        deviation_deg = abs(measured_angle_deg - nominal_angle_deg)
        deviation_rad = math.radians(deviation_deg)

        cen = _centroid(pts)
        char_len = max(math.sqrt(sum((p[i] - cen[i]) ** 2 for i in range(3))) for p in pts) or 1.0
        zone_width = 2.0 * math.sin(deviation_rad) * char_len

        warnings: list[str] = []
        in_tol = None
        if tolerance is not None:
            in_tol = zone_width <= tolerance
            if not in_tol:
                warnings.append(f"OUT_OF_TOLERANCE: angularity zone {zone_width:.6g} > tol {tolerance:.6g}")
        return {
            "ok": True,
            "measured_angle_deg": measured_angle_deg,
            "deviation_deg": deviation_deg,
            "zone_width": zone_width,
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def eval_position(measured_center: Sequence[float], true_position: Sequence[float],
                  tolerance: float, mmc_size: float | None = None,
                  actual_size: float | None = None) -> dict:
    """True-position evaluation with optional MMC bonus tolerance.

    Positional deviation = 2 × distance from measured_center to true_position.
    MMC bonus = actual_mmc_tolerance - tolerance_at_MMC when actual_size > mmc_size.

    Per ASME Y14.5-2018 §8.

    Returns:
        ok, deviation, effective_tolerance (with bonus), in_tolerance,
        bonus_tolerance, warnings.
    """
    try:
        mc = [float(c) for c in measured_center]
        tp = [float(c) for c in true_position]
        if len(mc) != 3 or len(tp) != 3:
            return {"ok": False, "reason": "measured_center and true_position must each have 3 components"}

        dist = math.sqrt(sum((mc[i] - tp[i]) ** 2 for i in range(3)))
        deviation = 2.0 * dist  # diametral zone

        bonus = 0.0
        if mmc_size is not None and actual_size is not None:
            bonus = max(0.0, abs(actual_size - mmc_size))

        eff_tol = tolerance + bonus
        in_tol = deviation <= eff_tol
        warnings: list[str] = []
        if not in_tol:
            warnings.append(f"OUT_OF_TOLERANCE: position deviation {deviation:.6g} > eff tol {eff_tol:.6g}")

        return {
            "ok": True,
            "deviation": deviation,
            "effective_tolerance": eff_tol,
            "bonus_tolerance": bonus,
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def eval_profile(measured_pts: Points, nominal_pts: Points,
                 tolerance: float | None = None) -> dict:
    """Surface profile evaluation (profile of a surface, ISO 1101 §17).

    For each measured point the nearest nominal point distance is computed.
    Profile = max deviation over all measured points (unilateral zone = t/2 each side).

    Returns:
        ok, profile_value, max_positive_dev, max_negative_dev, rms_dev,
        in_tolerance, warnings.
    """
    try:
        meas = _pts_to_lists(measured_pts)
        nom = _pts_to_lists(nominal_pts)
        if not meas or not nom:
            return {"ok": False, "reason": "both measured and nominal point lists must be non-empty"}

        deviations = []
        for mp in meas:
            dists = [math.sqrt(sum((mp[i] - np[i]) ** 2 for i in range(3))) for np in nom]
            nearest_idx = dists.index(min(dists))
            # Signed: positive if measured is farther from centroid of nominals
            nom_cen = _centroid(nom)
            mp_vec = [mp[i] - nom[nearest_idx][i] for i in range(3)]
            out_vec = [nom[nearest_idx][i] - nom_cen[i] for i in range(3)]
            sign = 1.0 if _dot(mp_vec, out_vec) >= 0 else -1.0
            deviations.append(sign * min(dists))

        profile_value = max(abs(d) for d in deviations) * 2.0  # bilateral zone
        max_pos = max(deviations)
        max_neg = min(deviations)
        rms_dev = math.sqrt(sum(d ** 2 for d in deviations) / len(deviations))

        warnings: list[str] = []
        in_tol = None
        if tolerance is not None:
            in_tol = profile_value <= tolerance
            if not in_tol:
                warnings.append(f"OUT_OF_TOLERANCE: profile {profile_value:.6g} > tol {tolerance:.6g}")
        return {
            "ok": True,
            "profile_value": profile_value,
            "max_positive_dev": max_pos,
            "max_negative_dev": max_neg,
            "rms_dev": rms_dev,
            "in_tolerance": in_tol,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ===========================================================================
# Measurement uncertainty (GUM)
# ===========================================================================

def gum_uncertainty(type_a: list[float], type_b: list[float],
                    coverage_factor: float = 2.0) -> dict:
    """Combined measurement uncertainty per GUM (JCGM 100:2008).

    Parameters
    ----------
    type_a   : list of standard uncertainties from statistical evaluation
               (u_i = s / √n).
    type_b   : list of standard uncertainties from other means
               (e.g. calibration certificates: divide half-width by √3 for
               rectangular distribution, or by √2 for triangular).
    coverage_factor : k factor (default 2.0 ≈ 95 % coverage for normal dist).

    Returns
    -------
    ok, combined_standard_uncertainty (uc), expanded_uncertainty (U = k·uc),
    coverage_factor.
    """
    try:
        if not type_a and not type_b:
            return {"ok": False, "reason": "at least one uncertainty component required"}
        uc_sq = sum(u ** 2 for u in type_a) + sum(u ** 2 for u in type_b)
        uc = math.sqrt(uc_sq)
        U = coverage_factor * uc
        return {
            "ok": True,
            "combined_standard_uncertainty": uc,
            "expanded_uncertainty": U,
            "coverage_factor": coverage_factor,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ===========================================================================
# Probe-radius compensation
# ===========================================================================

def probe_compensate(measured_pts: Points, surface_normals: Points,
                     probe_radius: float) -> dict:
    """Compensate stylus-tip radius from CMM raw hit points.

    Each measured point is offset along the surface normal by probe_radius
    towards the actual surface.  normal vectors must point away from the
    surface (outward).

    Returns:
        ok, compensated_points (list of [x,y,z]).
    """
    try:
        pts = _pts_to_lists(measured_pts)
        nrms = _pts_to_lists(surface_normals)
        if len(pts) != len(nrms):
            return {"ok": False, "reason": "measured_pts and surface_normals must have same length"}
        if probe_radius < 0:
            return {"ok": False, "reason": "probe_radius must be >= 0"}
        compensated = []
        for p, n in zip(pts, nrms):
            nu = _normalise(n)
            comp = [p[i] - probe_radius * nu[i] for i in range(3)]
            compensated.append(comp)
        return {"ok": True, "compensated_points": compensated}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ===========================================================================
# Sampling recommendation
# ===========================================================================

def recommend_samples(expected_harmonics: int, safety_factor: float = 2.5) -> dict:
    """Nyquist-based sampling recommendation for CMM measurement.

    Nyquist: N_min = 2 × max_harmonic.  Applies safety_factor for practical
    use (default 2.5, per ISO/TS 12781-2 guidance).

    Parameters
    ----------
    expected_harmonics : highest harmonic number expected in the form error
                         (e.g. lobing, waviness).  Minimum 1.
    safety_factor      : multiplier above Nyquist (default 2.5).

    Returns
    -------
    ok, nyquist_minimum, recommended_samples.
    """
    try:
        if expected_harmonics < 1:
            return {"ok": False, "reason": "expected_harmonics must be >= 1"}
        if safety_factor <= 0:
            return {"ok": False, "reason": "safety_factor must be > 0"}
        nyquist_min = 2 * expected_harmonics
        recommended = math.ceil(nyquist_min * safety_factor)
        return {
            "ok": True,
            "nyquist_minimum": nyquist_min,
            "recommended_samples": recommended,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ===========================================================================
# Gauge R&R
# ===========================================================================

def gauge_rr_anova(data: list[list[list[float]]], usl: float | None = None,
                   lsl: float | None = None) -> dict:
    """Gauge R&R via ANOVA method (AIAG MSA 4th edition).

    Parameters
    ----------
    data : 3-D list indexed [part][operator][replicate].
           Shape: n_parts × n_operators × n_replicates.
    usl, lsl : upper/lower spec limits (optional; used for %tolerance).

    Returns
    -------
    ok, EV (equipment variation / repeatability), AV (appraiser variation /
    reproducibility), GRR (gauge R&R combined), PV (part variation),
    TV (total variation), pct_study_var_grr, ndc, in_tolerance (if spec given),
    warnings.

    Notes
    -----
    pct_study_var = 100 × GRR / TV.
    ndc = 1.41 × (PV / GRR).   Acceptable if ndc >= 5.
    """
    try:
        n_parts = len(data)
        if n_parts < 2:
            return {"ok": False, "reason": "at least 2 parts required"}
        n_ops = len(data[0])
        if n_ops < 1:
            return {"ok": False, "reason": "at least 1 operator required"}
        n_reps = len(data[0][0])
        if n_reps < 2:
            return {"ok": False, "reason": "at least 2 replicates required"}

        # Validate consistent dimensions
        for i, part in enumerate(data):
            if len(part) != n_ops:
                return {"ok": False, "reason": f"part {i} has inconsistent operator count"}
            for j, op in enumerate(part):
                if len(op) != n_reps:
                    return {"ok": False, "reason": f"part {i} operator {j} has inconsistent replicate count"}

        N = n_parts * n_ops * n_reps  # total observations
        grand_total = sum(data[i][j][k] for i in range(n_parts)
                          for j in range(n_ops) for k in range(n_reps))
        CF = grand_total ** 2 / N  # correction factor

        # Sum of squares
        SST = sum(data[i][j][k] ** 2 for i in range(n_parts)
                  for j in range(n_ops) for k in range(n_reps)) - CF

        # Part means
        part_totals = [sum(data[i][j][k] for j in range(n_ops) for k in range(n_reps))
                       for i in range(n_parts)]
        SSP = sum(t ** 2 for t in part_totals) / (n_ops * n_reps) - CF

        # Operator means
        op_totals = [sum(data[i][j][k] for i in range(n_parts) for k in range(n_reps))
                     for j in range(n_ops)]
        SSO = sum(t ** 2 for t in op_totals) / (n_parts * n_reps) - CF

        # Interaction part×operator
        cell_totals = [[sum(data[i][j][k] for k in range(n_reps))
                        for j in range(n_ops)] for i in range(n_parts)]
        SS_cells = sum(cell_totals[i][j] ** 2 for i in range(n_parts)
                       for j in range(n_ops)) / n_reps - CF
        SSPO = SS_cells - SSP - SSO

        # Within (repeatability / equipment)
        SSE = SST - SS_cells

        # Degrees of freedom
        df_p = n_parts - 1
        df_o = n_ops - 1
        df_po = df_p * df_o
        df_e = N - n_parts * n_ops

        MSP = SSP / df_p
        MSO = SSO / df_o if df_o > 0 else 0.0
        MSPO = SSPO / df_po if df_po > 0 else 0.0
        MSE = SSE / df_e

        # Variance components
        var_e = MSE  # repeatability
        var_po = max((MSPO - MSE) / n_reps, 0.0)
        var_o = max((MSO - MSPO) / (n_parts * n_reps), 0.0)
        var_p = max((MSP - MSPO) / (n_ops * n_reps), 0.0)

        # Sigma estimates (5.15σ study variation convention from AIAG)
        k_study = 5.15
        EV = k_study * math.sqrt(var_e)          # repeatability
        AV_sq = var_o + var_po
        AV = k_study * math.sqrt(AV_sq)          # reproducibility
        GRR = k_study * math.sqrt(var_e + AV_sq) # gauge R&R
        PV = k_study * math.sqrt(var_p)          # part variation
        TV = k_study * math.sqrt(var_e + AV_sq + var_p)  # total variation

        pct_study = 100.0 * GRR / TV if TV > 0 else 0.0
        ndc_val = 1.41 * (PV / GRR) if GRR > 0 else float("inf")

        warnings: list[str] = []
        if pct_study > 30.0:
            warnings.append(f"R&R_NOT_CAPABLE: %study_var {pct_study:.1f}% > 30%")
        elif pct_study > 10.0:
            warnings.append(f"R&R_MARGINAL: %study_var {pct_study:.1f}% is 10-30%")
        if ndc_val < 5:
            warnings.append(f"NDC_NOT_CAPABLE: ndc {ndc_val:.2f} < 5")

        pct_tolerance = None
        if usl is not None and lsl is not None:
            tol_range = usl - lsl
            if tol_range > 0:
                pct_tolerance = 100.0 * GRR / tol_range

        return {
            "ok": True,
            "EV": EV,
            "AV": AV,
            "GRR": GRR,
            "PV": PV,
            "TV": TV,
            "pct_study_var_grr": pct_study,
            "ndc": ndc_val,
            "pct_tolerance": pct_tolerance,
            "var_repeatability": var_e,
            "var_reproducibility": AV_sq,
            "var_part": var_p,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def gauge_rr_avgrange(data: list[list[list[float]]], usl: float | None = None,
                      lsl: float | None = None) -> dict:
    """Gauge R&R via Average-Range method (AIAG MSA 4th edition).

    Parameters
    ----------
    data : 3-D list [part][operator][replicate].
    usl, lsl : spec limits (optional).

    Returns
    -------
    ok, EV, AV, GRR, PV, TV, pct_study_var_grr, ndc, warnings.
    """
    try:
        n_parts = len(data)
        if n_parts < 2:
            return {"ok": False, "reason": "at least 2 parts required"}
        n_ops = len(data[0])
        if n_ops < 1:
            return {"ok": False, "reason": "at least 1 operator required"}
        n_reps = len(data[0][0])
        if n_reps < 2:
            return {"ok": False, "reason": "at least 2 replicates required"}

        # d2 control-chart constant for range based on subgroup size n_reps
        # AIAG table values for n=2..7
        _d2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704}
        d2_rep = _d2.get(n_reps, 2.326)  # fall back to n=5 for larger
        d2_ops = _d2.get(n_ops, 1.128)

        # Average range per operator
        op_ranges: list[float] = []
        op_means: list[float] = []
        for j in range(n_ops):
            ranges_for_op: list[float] = []
            all_readings: list[float] = []
            for i in range(n_parts):
                reps = data[i][j]
                ranges_for_op.append(max(reps) - min(reps))
                all_readings.extend(reps)
            op_ranges.append(_mean(ranges_for_op))
            op_means.append(_mean(all_readings))

        R_bar = _mean(op_ranges)  # grand average range

        # EV (repeatability) = R_bar / d2
        EV_sigma = R_bar / d2_rep
        k_study = 5.15
        EV = k_study * EV_sigma

        # AV (reproducibility)
        X_diff = max(op_means) - min(op_means) if n_ops > 1 else 0.0
        AV_sigma_sq = max((X_diff / d2_ops) ** 2 - EV_sigma ** 2 / (n_parts * n_reps), 0.0)
        AV_sigma = math.sqrt(AV_sigma_sq)
        AV = k_study * AV_sigma

        GRR_sigma = math.sqrt(EV_sigma ** 2 + AV_sigma ** 2)
        GRR = k_study * GRR_sigma

        # PV from part means
        part_means = [_mean([data[i][j][k] for j in range(n_ops) for k in range(n_reps)])
                      for i in range(n_parts)]
        d2_parts = _d2.get(n_parts, 2.326)
        part_range = max(part_means) - min(part_means)
        PV_sigma = part_range / d2_parts
        PV = k_study * PV_sigma

        TV = k_study * math.sqrt(GRR_sigma ** 2 + PV_sigma ** 2)
        pct_study = 100.0 * GRR / TV if TV > 0 else 0.0
        ndc_val = 1.41 * (PV / GRR) if GRR > 0 else float("inf")

        warnings: list[str] = []
        if pct_study > 30.0:
            warnings.append(f"R&R_NOT_CAPABLE: %study_var {pct_study:.1f}% > 30%")
        elif pct_study > 10.0:
            warnings.append(f"R&R_MARGINAL: %study_var {pct_study:.1f}% is 10-30%")
        if ndc_val < 5:
            warnings.append(f"NDC_NOT_CAPABLE: ndc {ndc_val:.2f} < 5")

        pct_tolerance = None
        if usl is not None and lsl is not None:
            tol_range = usl - lsl
            if tol_range > 0:
                pct_tolerance = 100.0 * GRR / tol_range

        return {
            "ok": True,
            "EV": EV,
            "AV": AV,
            "GRR": GRR,
            "PV": PV,
            "TV": TV,
            "pct_study_var_grr": pct_study,
            "ndc": ndc_val,
            "pct_tolerance": pct_tolerance,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ===========================================================================
# Process capability
# ===========================================================================

def process_capability(measurements: list[float], usl: float, lsl: float) -> dict:
    """Compute Cpk and Ppk from a sample of measurements.

    Cp / Cpk  use the within-subgroup (short-term) estimate via moving-range:
      sigma_within = mean(|xi+1 - xi|) / d2   (d2=1.128 for n=2 moving range)

    Pp / Ppk  use the overall (long-term) sample standard deviation.

    Returns:
        ok, mean, sigma_within, sigma_overall, Cp, Cpk, Pp, Ppk,
        pct_out_of_spec, in_spec_count, total_count, warnings.
    """
    try:
        vals = [float(v) for v in measurements]
        if len(vals) < 2:
            return {"ok": False, "reason": "at least 2 measurements required"}
        if usl <= lsl:
            return {"ok": False, "reason": "usl must be > lsl"}

        n = len(vals)
        mu = _mean(vals)
        sigma_overall = _std(vals)

        # Moving range for within-subgroup sigma
        mr = [abs(vals[i + 1] - vals[i]) for i in range(n - 1)]
        mr_bar = _mean(mr)
        d2 = 1.128
        sigma_within = mr_bar / d2 if mr_bar > 0 else sigma_overall

        tol = usl - lsl

        Cp = tol / (6.0 * sigma_within) if sigma_within > 0 else float("inf")
        Cpu = (usl - mu) / (3.0 * sigma_within) if sigma_within > 0 else float("inf")
        Cpl = (mu - lsl) / (3.0 * sigma_within) if sigma_within > 0 else float("inf")
        Cpk = min(Cpu, Cpl)

        Pp = tol / (6.0 * sigma_overall) if sigma_overall > 0 else float("inf")
        Ppu = (usl - mu) / (3.0 * sigma_overall) if sigma_overall > 0 else float("inf")
        Ppl = (mu - lsl) / (3.0 * sigma_overall) if sigma_overall > 0 else float("inf")
        Ppk = min(Ppu, Ppl)

        out_count = sum(1 for v in vals if v < lsl or v > usl)
        pct_oos = 100.0 * out_count / n

        warnings: list[str] = []
        if Cpk < 1.0:
            warnings.append(f"PROCESS_NOT_CAPABLE: Cpk {Cpk:.3f} < 1.0")
        elif Cpk < 1.33:
            warnings.append(f"PROCESS_MARGINAL: Cpk {Cpk:.3f} < 1.33")
        if out_count > 0:
            warnings.append(f"OUT_OF_SPEC: {out_count}/{n} measurements outside spec")

        return {
            "ok": True,
            "mean": mu,
            "sigma_within": sigma_within,
            "sigma_overall": sigma_overall,
            "Cp": Cp,
            "Cpk": Cpk,
            "Pp": Pp,
            "Ppk": Ppk,
            "pct_out_of_spec": pct_oos,
            "in_spec_count": n - out_count,
            "total_count": n,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
