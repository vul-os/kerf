"""
MITC4 Mindlin-Reissner plate finite element.

Implements the 4-node MITC4 plate element of Bathe & Dvorkin (1985) to avoid
transverse-shear locking on thin plates.

DOF convention (3 per node, ordering [w, beta_x, beta_y]):
  w      = transverse displacement (positive upward)
  beta_x = rotation of the plate mid-surface about the x-axis
           (= dw/dy in Kirchhoff limit; positive anticlockwise about x)
  beta_y = rotation of the plate mid-surface about the y-axis
           (= -dw/dx in Kirchhoff limit; positive anticlockwise about y)

Shear strains (Mindlin):
  gamma_xz = dw/dx - beta_y
  gamma_yz = dw/dy + beta_x    <- note: some refs define beta_x = -dw/dy; here we use +

Wait — clarify to be consistent with standard refs (e.g. Bathe "Finite Element
Procedures" 1996, eq. 5.96):
  gamma_xz = dw/dx + beta_y
  gamma_yz = dw/dy - beta_x
  kappa_x  = d(beta_x)/dy        (curvature — note: Bathe uses beta rather than theta)
  kappa_y  = -d(beta_y)/dx
  kappa_xy = d(beta_x)/dx - d(beta_y)/dy   (twist)

This matches "beta = fibre rotation" convention of Bathe (1996) §5.4.2.

Node numbering on reference square [-1,1]x[-1,1]:
  4 (-1,+1) --- 3 (+1,+1)
       |              |
  1 (-1,-1) --- 2 (+1,-1)

References
----------
* Bathe & Dvorkin (1985), IJNME 21:367-383 — MITC4 formulation.
* Bathe, "Finite Element Procedures" (1996), §5.4.2, eqs. 5.96-5.111.
* Timoshenko & Woinowsky-Krieger, Theory of Plates and Shells (1959), Table 8.

All routines are pure Python — no numpy, no scipy.
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Dense linear-algebra helpers
# ---------------------------------------------------------------------------

def _zero(r: int, c: int) -> list[list[float]]:
    return [[0.0] * c for _ in range(r)]


def _matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    ra, ca = len(A), len(A[0])
    cb = len(B[0])
    C = _zero(ra, cb)
    for i in range(ra):
        for k in range(ca):
            if A[i][k] == 0.0:
                continue
            for j in range(cb):
                C[i][j] += A[i][k] * B[k][j]
    return C


def _transpose(A: list[list[float]]) -> list[list[float]]:
    r, c = len(A), len(A[0])
    return [[A[i][j] for i in range(r)] for j in range(c)]


def _matvec(A: list[list[float]], v: list[float]) -> list[float]:
    return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(a[i] * b[i] for i in range(len(a)))


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _inv2(J: list[list[float]]) -> list[list[float]]:
    """Inverse of 2x2 matrix."""
    a, b = J[0][0], J[0][1]
    c, d = J[1][0], J[1][1]
    det = a * d - b * c
    inv = 1.0 / det
    return [[d * inv, -b * inv], [-c * inv, a * inv]]


def _gauss_solve(K: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting."""
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
            f = A[row][col] * inv
            if f == 0.0:
                continue
            for j in range(col, n + 1):
                A[row][j] -= f * A[col][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = A[i][n]
        for j in range(i + 1, n):
            s -= A[i][j] * x[j]
        if abs(A[i][i]) < 1e-18:
            return None
        x[i] = s / A[i][i]
    return x


def _apply_dirichlet(K: list[list[float]], rhs: list[float], fixed: dict[int, float]) -> None:
    """In-place: apply homogeneous/prescribed Dirichlet BCs."""
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


# ---------------------------------------------------------------------------
# Shape functions on [-1,1]^2
# Node ordering: 1=(-1,-1), 2=(+1,-1), 3=(+1,+1), 4=(-1,+1)
# ---------------------------------------------------------------------------

def _N(xi: float, eta: float):
    return (
        0.25 * (1.0 - xi) * (1.0 - eta),
        0.25 * (1.0 + xi) * (1.0 - eta),
        0.25 * (1.0 + xi) * (1.0 + eta),
        0.25 * (1.0 - xi) * (1.0 + eta),
    )


def _dNdxi(xi: float, eta: float):
    return (
        -0.25 * (1.0 - eta),
         0.25 * (1.0 - eta),
         0.25 * (1.0 + eta),
        -0.25 * (1.0 + eta),
    )


def _dNdeta(xi: float, eta: float):
    return (
        -0.25 * (1.0 - xi),
        -0.25 * (1.0 + xi),
         0.25 * (1.0 + xi),
         0.25 * (1.0 - xi),
    )


def _jac(x: list[float], y: list[float], xi: float, eta: float):
    """J = [[dx/dxi, dy/dxi],[dx/deta, dy/deta]], returns (J, detJ)."""
    dnxi  = _dNdxi(xi, eta)
    dneta = _dNdeta(xi, eta)
    dxdxi  = sum(dnxi[i]  * x[i] for i in range(4))
    dydxi  = sum(dnxi[i]  * y[i] for i in range(4))
    dxdeta = sum(dneta[i] * x[i] for i in range(4))
    dydeta = sum(dneta[i] * y[i] for i in range(4))
    J = [[dxdxi, dydxi], [dxdeta, dydeta]]
    return J, dxdxi * dydeta - dydxi * dxdeta


# ---------------------------------------------------------------------------
# 2x2 Gauss quadrature
# ---------------------------------------------------------------------------

_G2 = (-1.0 / math.sqrt(3.0), 1.0 / math.sqrt(3.0))
_W2 = (1.0, 1.0)


# ---------------------------------------------------------------------------
# Bending B-matrix (3x12) — Bathe (1996) eq 5.100
#
# DOFs per node I: [w_I, bx_I, by_I], global index: [3I, 3I+1, 3I+2]
#
# Curvatures (Bathe convention):
#   kappa_x  = d(bx)/dx
#   kappa_y  = d(by)/dy          <- wait, Bathe uses -d(by)/dy for kappa_y
#   kappa_xy = d(bx)/dy + d(by)/dx  (or sometimes with factor 1/2)
#
# Using Bathe (1996) §5.4.2, eq. 5.96:
#   kappa_x  =  d(beta_x)/dx
#   kappa_y  = -d(beta_y)/dy
#   kappa_xy =  d(beta_x)/dy - d(beta_y)/dx
# and bending moment-curvature: M = D_b * kappa
# ---------------------------------------------------------------------------

def _Bb(x: list[float], y: list[float], xi: float, eta: float) -> list[list[float]]:
    """3x12 bending strain-displacement matrix at (xi, eta)."""
    J, _ = _jac(x, y, xi, eta)
    Ji = _inv2(J)  # Ji[i][j] = (J^{-1})_{ij}
    # dN/dx = Ji[0][0]*dN/dxi + Ji[0][1]*dN/deta
    # dN/dy = Ji[1][0]*dN/dxi + Ji[1][1]*dN/deta
    dnxi  = _dNdxi(xi, eta)
    dneta = _dNdeta(xi, eta)

    Bb = _zero(3, 12)
    for I in range(4):
        dNdx = Ji[0][0] * dnxi[I] + Ji[0][1] * dneta[I]
        dNdy = Ji[1][0] * dnxi[I] + Ji[1][1] * dneta[I]
        # kappa_x = d(bx)/dx  -> col 3I+1
        Bb[0][3*I+1] = dNdx
        # kappa_y = -d(by)/dy -> col 3I+2
        Bb[1][3*I+2] = -dNdy
        # kappa_xy = d(bx)/dy - d(by)/dx -> cols 3I+1, 3I+2
        Bb[2][3*I+1] = dNdy
        Bb[2][3*I+2] = -dNdx
    return Bb


# ---------------------------------------------------------------------------
# MITC4 shear B-matrix (2x12) — Bathe & Dvorkin (1985)
#
# Covariant shear strains (Bathe 1996, eq. 5.103):
#   e_1t = dw/dxi  + bx*(dy/dxi)  - by*(dx/dxi)
#   e_2t = dw/deta + bx*(dy/deta) - by*(dx/deta)
#
# Wait — need to be careful about sign convention.  From Bathe (1996) eq. 5.101:
#   gamma_xz = dw/dx + beta_x'    where beta_x' is fibre rotation component
# For a flat plate where fibres point in z:
#   gamma_xz = dw/dx + beta_y     (using Bathe's convention)
#   gamma_yz = dw/dy - beta_x
# and covariant (curvilinear) shear strains:
#   e_t1 = dw/dxi  + bx_I*(dy/dxi)  + by_I*(-dx/dxi)    -- wait, need correct signs
#
# Most reliable source: Dvorkin & Bathe IJNME 1984, or Bathe 1996 p. 429, eq 5.103:
#   e_t1 = dw/dxi  - sum_I N_I [bx_I*(dy/dxi) - by_I*(dx/dxi)]
# with physical shear:
#   [gamma_xz; gamma_yz] = J^{-T} [e_t1; e_t2]
# where J^{-T} = transpose of J^{-1}.
#
# DOF sign convention (same as bending above):
#   gamma_xz = dw/dx + beta_y
#   gamma_yz = dw/dy - beta_x
# Covariant from physical via J:
#   e_t1 = dxi/dx * gamma_xz + dxi/dy * gamma_yz
#         = J^{-T}_{11} gamma_xz + J^{-T}_{12} gamma_yz  (row 0 of J^{-T})
# Equivalently, express e_t1, e_t2 in terms of w and beta directly:
#   e_t1 = dw/dxi + sum_I N_I [by_I * (dx/dxi) - bx_I * (dy/dxi)]   -- Bathe sign
#   e_t2 = dw/deta + sum_I N_I [by_I * (dx/deta) - bx_I * (dy/deta)]
#
# MITC4 tying:
#   e_t1 is evaluated at A=(xi=0,eta=-1) and B=(xi=0,eta=+1), then linearly
#   interpolated in eta: e_t1(xi,eta) = (1-eta)/2 * e_t1(A) + (1+eta)/2 * e_t1(B)
#
#   e_t2 is evaluated at C=(xi=-1,eta=0) and D=(xi=+1,eta=0), then linearly
#   interpolated in xi: e_t2(xi,eta) = (1-xi)/2 * e_t2(C) + (1+xi)/2 * e_t2(D)
#
# Physical shear from covariant:
#   gamma_xz = Ji^T_{00} * e_t1 + Ji^T_{10} * e_t2
#            = Ji[0][0] * e_t1  + Ji[1][0] * e_t2   (J^{-T} transpose of Ji)
#   gamma_yz = Ji[0][1] * e_t1  + Ji[1][1] * e_t2
#
# Note: J^{-T}_{ij} = (J^{-1})_{ji} = Ji[j][i].
# So [gamma_xz; gamma_yz] = J^{-T} [e_t1; e_t2]  means:
#   gamma_xz = Ji[0][0]*e_t1 + Ji[1][0]*e_t2
#   gamma_yz = Ji[0][1]*e_t1 + Ji[1][1]*e_t2
# ---------------------------------------------------------------------------

def _cov_shear_xi_row(x: list[float], y: list[float], xi: float, eta: float) -> list[float]:
    """
    1x12 operator row for covariant shear e_t1 (xi-direction) at (xi,eta).
    e_t1 = sum_I dNI/dxi * w_I + sum_I N_I * [by_I * (dx/dxi) - bx_I * (dy/dxi)]
    DOF layout: node I -> [w_I=3I, bx_I=3I+1, by_I=3I+2]
    """
    N  = _N(xi, eta)
    dxi = _dNdxi(xi, eta)
    J, _ = _jac(x, y, xi, eta)
    dxdxi = J[0][0]
    dydxi = J[0][1]

    row = [0.0] * 12
    for I in range(4):
        row[3*I]   += dxi[I]                      # w_I  via dN/dxi
        row[3*I+1] -= N[I] * dydxi                # bx_I contribution
        row[3*I+2] += N[I] * dxdxi                # by_I contribution
    return row


def _cov_shear_eta_row(x: list[float], y: list[float], xi: float, eta: float) -> list[float]:
    """
    1x12 operator row for covariant shear e_t2 (eta-direction) at (xi,eta).
    e_t2 = sum_I dNI/deta * w_I + sum_I N_I * [by_I * (dx/deta) - bx_I * (dy/deta)]
    """
    N    = _N(xi, eta)
    deta = _dNdeta(xi, eta)
    J, _ = _jac(x, y, xi, eta)
    dxdeta = J[1][0]
    dydeta = J[1][1]

    row = [0.0] * 12
    for I in range(4):
        row[3*I]   += deta[I]                     # w_I
        row[3*I+1] -= N[I] * dydeta               # bx_I
        row[3*I+2] += N[I] * dxdeta               # by_I
    return row


def _Bs(x: list[float], y: list[float], xi: float, eta: float) -> list[list[float]]:
    """
    2x12 MITC4 shear strain-displacement matrix (physical shear gamma_xz, gamma_yz).
    """
    # Covariant rows at MITC4 tying points
    rA = _cov_shear_xi_row(x, y,  0.0, -1.0)   # A=(0,-1)
    rB = _cov_shear_xi_row(x, y,  0.0,  1.0)   # B=(0,+1)
    rC = _cov_shear_eta_row(x, y, -1.0,  0.0)  # C=(-1,0)
    rD = _cov_shear_eta_row(x, y,  1.0,  0.0)  # D=(+1,0)

    # Interpolated covariant shear operators
    fa = 0.5 * (1.0 - eta)
    fb = 0.5 * (1.0 + eta)
    fc = 0.5 * (1.0 - xi)
    fd = 0.5 * (1.0 + xi)
    et1 = [fa * rA[j] + fb * rB[j] for j in range(12)]
    et2 = [fc * rC[j] + fd * rD[j] for j in range(12)]

    # Transform to physical shear: [gxz;gyz] = J^{-T} [et1;et2]
    J, _ = _jac(x, y, xi, eta)
    Ji = _inv2(J)
    # Ji[i][j] = (J^{-1})_{ij}
    # J^{-T}_{ij} = Ji[j][i]
    # gxz = Ji[0][0]*et1 + Ji[1][0]*et2
    # gyz = Ji[0][1]*et1 + Ji[1][1]*et2
    Bs = _zero(2, 12)
    for j in range(12):
        Bs[0][j] = Ji[0][0] * et1[j] + Ji[1][0] * et2[j]
        Bs[1][j] = Ji[0][1] * et1[j] + Ji[1][1] * et2[j]
    return Bs


# ---------------------------------------------------------------------------
# Material matrices
# ---------------------------------------------------------------------------

def _Db(E: float, nu: float, t: float) -> list[list[float]]:
    """3x3 bending material matrix D_b = Et^3/(12(1-nu^2)) * [[1,nu,0],[nu,1,0],[0,0,(1-nu)/2]]."""
    D0 = E * t**3 / (12.0 * (1.0 - nu * nu))
    return [
        [D0,       D0 * nu,  0.0],
        [D0 * nu,  D0,       0.0],
        [0.0,      0.0,      D0 * (1.0 - nu) / 2.0],
    ]


def _Ds(E: float, nu: float, t: float) -> list[list[float]]:
    """2x2 shear material matrix D_s = k*G*t*I, k=5/6."""
    G = E / (2.0 * (1.0 + nu))
    kappa = 5.0 / 6.0
    c = kappa * G * t
    return [[c, 0.0], [0.0, c]]


# ---------------------------------------------------------------------------
# MITC4 element stiffness  (12x12)
# ---------------------------------------------------------------------------

def mitc4_stiffness(
    x: list[float],
    y: list[float],
    E: float,
    nu: float,
    t: float,
) -> list[list[float]]:
    """
    12x12 MITC4 element stiffness matrix.

    Parameters
    ----------
    x, y  : 4-node coords [node1..4], CCW ordering
    E     : Young's modulus
    nu    : Poisson ratio
    t     : plate thickness
    """
    Db = _Db(E, nu, t)
    Ds = _Ds(E, nu, t)

    Ke = _zero(12, 12)
    for xi in _G2:
        for eta in _G2:
            _, detJ = _jac(x, y, xi, eta)
            if detJ <= 0.0:
                raise ValueError(f"Non-positive Jacobian at ({xi},{eta}): check node ordering")

            Bb = _Bb(x, y, xi, eta)
            BbT = _transpose(Bb)
            DbBb = _matmul(Db, Bb)
            BbTDbBb = _matmul(BbT, DbBb)

            Bs = _Bs(x, y, xi, eta)
            BsT = _transpose(Bs)
            DsBs = _matmul(Ds, Bs)
            BsTDsBs = _matmul(BsT, DsBs)

            fac = detJ  # weight=1 for each 2x2 Gauss point
            for i in range(12):
                for j in range(12):
                    Ke[i][j] += fac * (BbTDbBb[i][j] + BsTDsBs[i][j])
    return Ke


# ---------------------------------------------------------------------------
# MITC4 element consistent mass matrix  (12x12)
# ---------------------------------------------------------------------------

def mitc4_mass(
    x: list[float],
    y: list[float],
    rho: float,
    t: float,
) -> list[list[float]]:
    """
    12x12 consistent mass matrix for the MITC4 plate element.

    Translational inertia (w DOFs): rho*t
    Rotational inertia (beta DOFs): rho*t^3/12
    """
    Me = _zero(12, 12)
    r_rot = t * t / 12.0

    for xi in _G2:
        for eta in _G2:
            _, detJ = _jac(x, y, xi, eta)
            N = _N(xi, eta)
            fac = rho * t * detJ

            for I in range(4):
                for J in range(4):
                    NN = N[I] * N[J]
                    Me[3*I  ][3*J  ] += fac * NN           # w-w
                    Me[3*I+1][3*J+1] += fac * r_rot * NN   # bx-bx
                    Me[3*I+2][3*J+2] += fac * r_rot * NN   # by-by
    return Me


# ---------------------------------------------------------------------------
# Equivalent nodal load for uniform pressure q [force/area]
# ---------------------------------------------------------------------------

def mitc4_load(
    x: list[float],
    y: list[float],
    q: float,
) -> list[float]:
    """
    12-vector equivalent nodal loads for uniform pressure q.
    Only w DOFs receive load; rotation DOFs are zero.
    """
    fe = [0.0] * 12
    for xi in _G2:
        for eta in _G2:
            _, detJ = _jac(x, y, xi, eta)
            N = _N(xi, eta)
            fac = q * detJ
            for I in range(4):
                fe[3*I] += fac * N[I]
    return fe


# ---------------------------------------------------------------------------
# Rectangular mesh generator
# ---------------------------------------------------------------------------

def _rect_plate_mesh(Lx: float, Ly: float, Nx: int, Ny: int):
    """Alias for backwards compatibility with tests."""
    return _rect_mesh(Lx, Ly, Nx, Ny)


def _rect_mesh(Lx: float, Ly: float, Nx: int, Ny: int):
    """
    Uniform quad mesh over [0,Lx] x [0,Ly].

    Returns
    -------
    nodes    : list of (x,y) tuples, length (Nx+1)*(Ny+1)
    elements : list of (n0,n1,n2,n3) CCW quads (0-based)
    """
    nodes = []
    for j in range(Ny + 1):
        for i in range(Nx + 1):
            nodes.append((i * Lx / Nx, j * Ly / Ny))

    def nid(i: int, j: int) -> int:
        return j * (Nx + 1) + i

    elements = []
    for j in range(Ny):
        for i in range(Nx):
            elements.append((nid(i,j), nid(i+1,j), nid(i+1,j+1), nid(i,j+1)))
    return nodes, elements


# ---------------------------------------------------------------------------
# Global assembly + linear static solve
# ---------------------------------------------------------------------------

def solve_plate_static(
    nodes: list[tuple[float, float]],
    elements: list[tuple[int, int, int, int]],
    E: float,
    nu: float,
    t: float,
    q: float,
    bcs: list[dict],
) -> dict[str, Any]:
    """
    Assemble and solve a Mindlin-Reissner plate under uniform pressure q.

    Parameters
    ----------
    nodes    : list of (x,y) nodal coords
    elements : list of 4-node connectivity (0-based, CCW)
    E, nu, t : material/geometry
    q        : uniform transverse pressure [N/m^2]
    bcs      : boundary condition dicts; supported types:
        {"type": "clamped",          "node": int}   w=bx=by=0
        {"type": "simply_supported", "node": int}   w=0
        {"type": "free",             "node": int}   (no-op)
        {"node": int, "dofs": [0,1,2], "values": [0,0,0]}  generic

    DOF ordering: node i -> global dofs [3i, 3i+1, 3i+2] = [w, bx, by]

    Returns
    -------
    {ok, w, beta_x, beta_y, w_max, reactions, nodal_disp}
    """
    n = len(nodes)
    ndof = 3 * n
    K = _zero(ndof, ndof)
    F = [0.0] * ndof

    for conn in elements:
        n0, n1, n2, n3 = conn
        xe = [nodes[n0][0], nodes[n1][0], nodes[n2][0], nodes[n3][0]]
        ye = [nodes[n0][1], nodes[n1][1], nodes[n2][1], nodes[n3][1]]
        Ke = mitc4_stiffness(xe, ye, E, nu, t)
        fe = mitc4_load(xe, ye, q)

        glb = []
        for ni in conn:
            glb += [3*ni, 3*ni+1, 3*ni+2]

        for i in range(12):
            F[glb[i]] += fe[i]
            for j in range(12):
                K[glb[i]][glb[j]] += Ke[i][j]

    # Parse BCs
    fixed: dict[int, float] = {}
    for bc in bcs:
        btype = bc.get("type", "")
        nd = bc.get("node", 0)
        if btype == "clamped":
            fixed[3*nd]   = 0.0
            fixed[3*nd+1] = 0.0
            fixed[3*nd+2] = 0.0
        elif btype == "simply_supported":
            fixed[3*nd] = 0.0
        elif btype == "free":
            pass
        else:
            dofs = bc.get("dofs", [])
            vals = bc.get("values", [0.0] * len(dofs))
            for d, v in zip(dofs, vals):
                fixed[3*nd + d] = float(v)

    K_unc = [row[:] for row in K]
    F_unc = F[:]
    _apply_dirichlet(K, F, fixed)

    u = _gauss_solve(K, F)
    if u is None:
        return {"ok": False, "reason": "singular stiffness — check boundary conditions"}

    w_nod    = [u[3*i]   for i in range(n)]
    beta_x   = [u[3*i+1] for i in range(n)]
    beta_y   = [u[3*i+2] for i in range(n)]
    w_max    = max(abs(v) for v in w_nod)

    reactions: dict[int, float] = {}
    for d in fixed:
        R = sum(K_unc[d][j] * u[j] for j in range(ndof)) - F_unc[d]
        reactions[d] = R

    return {
        "ok":        True,
        "w":         w_nod,
        "beta_x":    beta_x,
        "beta_y":    beta_y,
        "w_max":     w_max,
        "reactions": reactions,
        "nodal_disp": u,
    }


# ---------------------------------------------------------------------------
# Convenience: simply-supported rectangular plate
# ---------------------------------------------------------------------------

def solve_ss_plate(
    Lx: float,
    Ly: float,
    E: float,
    nu: float,
    t: float,
    q: float,
    Nx: int = 8,
    Ny: int = 8,
) -> dict[str, Any]:
    """
    Solve simply-supported rectangular plate under uniform load.
    SS boundary: w=0 on all four edges (rotations free).
    """
    nodes, elements = _rect_mesh(Lx, Ly, Nx, Ny)
    Nxn = Nx + 1

    bcs = []
    for i in range(Nxn):
        bcs.append({"type": "simply_supported", "node": i})           # bottom row
        bcs.append({"type": "simply_supported", "node": Ny*Nxn + i})  # top row
    for j in range(1, Ny):
        bcs.append({"type": "simply_supported", "node": j*Nxn})       # left col
        bcs.append({"type": "simply_supported", "node": j*Nxn + Nx})  # right col

    return solve_plate_static(nodes, elements, E, nu, t, q, bcs)


# ---------------------------------------------------------------------------
# Modal analysis — inverse iteration
# ---------------------------------------------------------------------------

def _cholesky(A: list[list[float]]) -> list[list[float]] | None:
    n = len(A)
    L = _zero(n, n)
    for i in range(n):
        s = A[i][i] - sum(L[i][k]**2 for k in range(i))
        if s <= 1e-30:
            return None
        L[i][i] = math.sqrt(s)
        for j in range(i+1, n):
            L[j][i] = (A[j][i] - sum(L[j][k]*L[i][k] for k in range(i))) / L[i][i]
    return L


def _fwd_sub(L: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    x = [0.0] * n
    for i in range(n):
        x[i] = (b[i] - sum(L[i][k]*x[k] for k in range(i))) / L[i][i]
    return x


def _bck_sub(L: list[list[float]], b: list[float]) -> list[float]:
    """Solve L^T x = b."""
    n = len(b)
    x = [0.0] * n
    for i in range(n-1, -1, -1):
        x[i] = (b[i] - sum(L[j][i]*x[j] for j in range(i+1, n))) / L[i][i]
    return x


def plate_modal(
    nodes: list[tuple[float, float]],
    elements: list[tuple[int, int, int, int]],
    E: float,
    nu: float,
    t: float,
    rho: float,
    bcs: list[dict],
    n_modes: int = 6,
    max_iter: int = 300,
    tol: float = 1e-7,
) -> dict[str, Any]:
    """
    Natural frequencies via inverse iteration on K phi = omega^2 M phi.

    Returns frequencies [Hz], omega [rad/s], and normalised mode shapes.
    """
    n = len(nodes)
    ndof = 3 * n
    K = _zero(ndof, ndof)
    M = _zero(ndof, ndof)

    for conn in elements:
        n0, n1, n2, n3 = conn
        xe = [nodes[n0][0], nodes[n1][0], nodes[n2][0], nodes[n3][0]]
        ye = [nodes[n0][1], nodes[n1][1], nodes[n2][1], nodes[n3][1]]
        Ke = mitc4_stiffness(xe, ye, E, nu, t)
        Me = mitc4_mass(xe, ye, rho, t)
        glb = []
        for ni in conn:
            glb += [3*ni, 3*ni+1, 3*ni+2]
        for i in range(12):
            for j in range(12):
                K[glb[i]][glb[j]] += Ke[i][j]
                M[glb[i]][glb[j]] += Me[i][j]

    fixed: dict[int, float] = {}
    for bc in bcs:
        btype = bc.get("type", "")
        nd = bc.get("node", 0)
        if btype == "clamped":
            for d in range(3):
                fixed[3*nd+d] = 0.0
        elif btype == "simply_supported":
            fixed[3*nd] = 0.0
        else:
            for d in bc.get("dofs", []):
                fixed[3*nd+d] = 0.0

    F_dum = [0.0] * ndof
    _apply_dirichlet(K, F_dum, fixed)
    for d in fixed:
        for j in range(ndof):
            M[d][j] = 0.0
            M[j][d] = 0.0
        M[d][d] = 1.0

    L = _cholesky(K)
    if L is None:
        return {"ok": False, "reason": "K not positive-definite (under-constrained?)"}

    import random
    rng = random.Random(42)

    freqs, omegas, mode_shapes = [], [], []
    deflated = []

    for _ in range(n_modes):
        # Start with random vector, zero out fixed DOFs
        v = [rng.gauss(0, 1) for _ in range(ndof)]
        for d in fixed:
            v[d] = 0.0
        nrm = _norm(v)
        if nrm < 1e-14:
            break
        v = [vi / nrm for vi in v]

        lam = 0.0
        for it in range(max_iter):
            # --- Deflation against found modes (M-orthogonalisation) ---
            for phi in deflated:
                Mphi = _matvec(M, phi)
                c = _dot(v, Mphi)
                v = [v[j] - c * phi[j] for j in range(ndof)]

            # --- M-normalise v ---
            Mv = _matvec(M, v)
            vMv = _dot(v, Mv)
            if vMv <= 1e-30:
                break
            v = [vi / math.sqrt(vMv) for vi in v]

            # --- Inverse iteration: solve K z = M v ---
            Mv = _matvec(M, v)
            y = _fwd_sub(L, Mv)
            z = _bck_sub(L, y)
            for d in fixed:
                z[d] = 0.0

            # --- Rayleigh quotient on z (M-normalised z gives eigenvalue estimate) ---
            # After solving K z = M v (v is M-normalised), z ≈ (1/lambda)*v_new
            # Rayleigh: lam = (z^T K z)/(z^T M z) is best, but expensive.
            # Use: lam = v^T M v / v^T K^{-1} M v = 1 / (v^T z) since v is M-normalised
            # This is the standard Rayleigh quotient for inverse iteration.
            vz = _dot(v, z)
            lam_new = 1.0 / vz if abs(vz) > 1e-30 else 0.0

            # Update v ← z M-normalised
            Mz = _matvec(M, z)
            zMz = _dot(z, Mz)
            if zMz <= 1e-30:
                break
            v = [zi / math.sqrt(zMz) for zi in z]

            if it > 1 and abs(lam_new - lam) / (abs(lam_new) + 1e-30) < tol:
                lam = lam_new
                break
            lam = lam_new

        # Final Rayleigh quotient on converged v for accuracy
        Kv = _matvec(K, v)
        Mv = _matvec(M, v)
        vKv = _dot(v, Kv)
        vMv = _dot(v, Mv)
        lam_final = vKv / vMv if vMv > 1e-30 else abs(lam)

        omega = math.sqrt(abs(lam_final))
        freqs.append(omega / (2.0 * math.pi))
        omegas.append(omega)

        # M-normalise mode for storage
        if vMv > 0.0:
            v = [vi / math.sqrt(vMv) for vi in v]
        mode_shapes.append(v)
        deflated.append(v)

    return {"ok": True, "frequencies": freqs, "omega": omegas, "modes": mode_shapes}


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


_fem_plate_static_spec = ToolSpec(
    name="fem_plate_static_solve",
    description=(
        "Solve a 2-D Mindlin-Reissner plate under uniform transverse pressure using "
        "the MITC4 element (avoids shear-locking on thin plates). "
        "Returns nodal out-of-plane displacements (w), rotations (beta_x, beta_y), "
        "maximum deflection, and reaction forces.\n"
        "\n"
        "Boundary condition types per node:\n"
        "  clamped          — w = beta_x = beta_y = 0\n"
        "  simply_supported — w = 0 (rotations free)\n"
        "  free             — all DOFs free\n"
        "\n"
        "Quick mode: geometry.plate_type='simply_supported_rect' with Lx, Ly, Nx, Ny "
        "auto-generates mesh and simply-supported BCs on all edges."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "geometry": {
                "type": "object",
                "properties": {
                    "plate_type": {
                        "type": "string",
                        "enum": ["simply_supported_rect", "custom"],
                    },
                    "Lx":  {"type": "number"},
                    "Ly":  {"type": "number"},
                    "Nx":  {"type": "integer", "default": 8},
                    "Ny":  {"type": "integer", "default": 8},
                    "nodes": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
                    "elements": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                    },
                },
                "required": ["plate_type"],
            },
            "material": {
                "type": "object",
                "properties": {
                    "E":   {"type": "number"},
                    "nu":  {"type": "number"},
                    "t":   {"type": "number"},
                    "rho": {"type": "number"},
                },
                "required": ["E", "nu", "t"],
            },
            "load": {
                "type": "object",
                "properties": {"q": {"type": "number"}},
                "required": ["q"],
            },
            "boundary_conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "node": {"type": "integer"},
                    },
                },
            },
        },
        "required": ["geometry", "material", "load"],
    },
)


@register(_fem_plate_static_spec)
async def run_fem_plate_static_solve(ctx: ProjectCtx, args: bytes) -> str:
    import json
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    geo  = a.get("geometry", {})
    mat  = a.get("material", {})
    load = a.get("load", {})

    E  = mat.get("E")
    nu = mat.get("nu")
    t  = mat.get("t")
    q  = load.get("q")
    if any(v is None for v in [E, nu, t, q]):
        return err_payload("material.E, material.nu, material.t, load.q required", "BAD_ARGS")

    plate_type = geo.get("plate_type", "custom")
    if plate_type == "simply_supported_rect":
        Lx = geo.get("Lx")
        Ly = geo.get("Ly")
        if Lx is None or Ly is None:
            return err_payload("geometry.Lx and Ly required", "BAD_ARGS")
        Nx = int(geo.get("Nx", 8))
        Ny = int(geo.get("Ny", 8))
        result = solve_ss_plate(float(Lx), float(Ly), float(E), float(nu), float(t), float(q), Nx, Ny)
    else:
        raw_nodes = geo.get("nodes")
        raw_elems = geo.get("elements")
        bcs = a.get("boundary_conditions", [])
        if not raw_nodes or not raw_elems:
            return err_payload("geometry.nodes and .elements required for custom", "BAD_ARGS")
        nds = [tuple(n) for n in raw_nodes]
        els = [tuple(int(v) for v in e) for e in raw_elems]
        result = solve_plate_static(nds, els, float(E), float(nu), float(t), float(q), bcs)

    if not result.get("ok"):
        return err_payload(result.get("reason", "solve failed"), "SOLVE_ERROR")

    out: dict = {"ok": True, "w_max": result["w_max"], "n_nodes": len(result["w"])}
    if plate_type == "simply_supported_rect":
        Nx_val = int(geo.get("Nx", 8))
        Ny_val = int(geo.get("Ny", 8))
        ci = (Ny_val // 2) * (Nx_val + 1) + (Nx_val // 2)
        out["w_center"] = result["w"][ci]

    return ok_payload(out)
