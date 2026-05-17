"""
Production-grade generative / topology-optimization layer.

This module sits ON TOP of the shipped FEniCSx SIMP solver (``routes.py``)
and adds the production-grade capabilities that the basic single-objective
solver lacks:

  * **multi-load-case** — weighted compliance over N independent load sets,
  * **multi-objective** — compliance vs. mass (vs. a second user metric) via
    weighted-sum + epsilon-constraint, returning a Pareto front,
  * **manufacturing constraints**
      - minimum-member-size (density filter radius),
      - additive-manufacturing overhang / self-support angle,
      - casting draw-direction (uni-directional projection),
      - symmetry (mirror-plane density coupling),
  * **lattice-infill** — a graded relative-density field mapped to a TPMS
    wall-thickness via the shipped ``frep/sdf.tpms_wall_thickness`` when it
    is importable, otherwise a Gibson-Ashby closed-cell fallback,
  * **MMA or OC** update scheme with a compliance / volume convergence
    history.

It is **pure Python** — a hand-rolled bilinear-quad (Q4) plane-stress finite
element solver with a dense Cholesky-free Gaussian elimination, exactly like
the existing pure-Python helpers in ``routes.py`` (no numpy / scipy / dolfinx
required for the core path).  The classic Sigmund 99-line MBB-beam problem is
reproduced to a known compliance / volume fraction so the numerics can be
regression-tested hermetically on a coarse mesh.

Every public entry-point is **total**: it never raises — failures are
returned as ``{"ok": False, "reason": ...}``.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:  # optional — only used by the lattice-infill mapping
    from kerf_cad_core.frep.sdf import tpms_wall_thickness as _tpms_wall_thickness
    _TPMS_AVAILABLE = True
except Exception:  # pragma: no cover - depends on sibling plugin presence
    _tpms_wall_thickness = None
    _TPMS_AVAILABLE = False

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:  # pragma: no cover - exercised only inside full backend
    from kerf_topo._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # noqa: F401


# ───────────────────────────────────────────────────────────────────────────
# Dense linear algebra (pure Python, no numpy)
# ───────────────────────────────────────────────────────────────────────────

def _solve_dense(A: List[List[float]], b: List[float]) -> List[float]:
    """Solve ``A x = b`` by Gaussian elimination with partial pivoting.

    ``A`` is a square dense matrix (list of rows); destroyed in place on a
    copy.  Raises ``ValueError`` on a singular system (callers wrap this).
    """
    n = len(b)
    # Work on copies so the caller's matrices are untouched.
    M = [row[:] for row in A]
    x = b[:]
    for col in range(n):
        # Partial pivot.
        piv = col
        best = abs(M[col][col])
        for r in range(col + 1, n):
            v = abs(M[r][col])
            if v > best:
                best = v
                piv = r
        if best < 1e-300:
            raise ValueError("singular stiffness matrix")
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
            x[col], x[piv] = x[piv], x[col]
        inv = 1.0 / M[col][col]
        for r in range(col + 1, n):
            factor = M[r][col] * inv
            if factor == 0.0:
                continue
            Mr = M[r]
            Mc = M[col]
            for c in range(col, n):
                Mr[c] -= factor * Mc[c]
            x[r] -= factor * x[col]
    # Back-substitution.
    for col in range(n - 1, -1, -1):
        s = x[col]
        Mc = M[col]
        for c in range(col + 1, n):
            s -= Mc[c] * x[c]
        x[col] = s / Mc[col]
    return x


def _solve_spd_banded(rows: List[Dict[int, float]], b: List[float],
                      bandwidth: int) -> List[float]:
    """Solve a symmetric-positive-definite system stored as sparse rows.

    Uses a banded LDL^T factorisation (no pivoting — valid because the
    free-DOF stiffness of a properly restrained elastic body is SPD).  Only
    the lower band within ``bandwidth`` of the diagonal is factorised, turning
    the FE solve from O(n^3) into O(n * band^2) so coarse-but-not-tiny meshes
    (e.g. the 30x10 MBB regression) stay hermetic.  Raises ``ValueError`` on a
    non-positive pivot (callers wrap this and fall back to the dense path).
    """
    n = len(b)
    # L[i] is a dict {j: value} for the strictly-lower band j in [i-band, i).
    L: List[Dict[int, float]] = [dict() for _ in range(n)]
    D = [0.0] * n
    for i in range(n):
        ri = rows[i]
        lo = max(0, i - bandwidth)
        Li = L[i]
        # L[i][j] = ( A[i][j] - sum_{k<j} L[i][k] L[j][k] D[k] ) / D[j]
        for j in range(lo, i):
            s = ri.get(j, 0.0)
            Lj = L[j]
            kmin = max(lo, j - bandwidth)
            for k in range(kmin, j):
                lik = Li.get(k)
                if lik is None:
                    continue
                ljk = Lj.get(k)
                if ljk is not None:
                    s -= lik * ljk * D[k]
            if D[j] == 0.0:
                continue
            v = s / D[j]
            if v != 0.0:
                Li[j] = v
        # D[i] = A[i][i] - sum_{k<i} L[i][k]^2 D[k]
        d = ri.get(i, 0.0)
        for k, lik in Li.items():
            d -= lik * lik * D[k]
        if d <= 1e-300:
            raise ValueError("non-SPD pivot in banded factorisation")
        D[i] = d
    # Forward solve L y = b.
    y = list(b)
    for i in range(n):
        for k, lik in L[i].items():
            y[i] -= lik * y[k]
    # Diagonal solve D z = y (reuse y).
    for i in range(n):
        y[i] /= D[i]
    # Back solve L^T x = z.
    xv = list(y)
    for i in range(n - 1, -1, -1):
        xi = xv[i]
        for k, lik in L[i].items():
            xv[k] -= lik * xi
    return xv


# ───────────────────────────────────────────────────────────────────────────
# Q4 plane-stress element stiffness (analytic, unit element scaled by side h)
# ───────────────────────────────────────────────────────────────────────────

def _ke_q4(E: float, nu: float) -> List[List[float]]:
    """8x8 stiffness of a unit-square bilinear quad in plane stress.

    This is the standard closed-form KE used by Sigmund's 99-line code; it is
    independent of element size for a unit square (uniform mesh), which keeps
    the MBB regression deterministic.
    """
    k = [
        1.0 / 2.0 - nu / 6.0,
        1.0 / 8.0 + nu / 8.0,
        -1.0 / 4.0 - nu / 12.0,
        -1.0 / 8.0 + 3.0 * nu / 8.0,
        -1.0 / 4.0 + nu / 12.0,
        -1.0 / 8.0 - nu / 8.0,
        nu / 6.0,
        1.0 / 8.0 - 3.0 * nu / 8.0,
    ]
    f = E / (1.0 - nu * nu)
    idx = [
        [0, 1, 2, 3, 4, 5, 6, 7],
        [1, 0, 7, 6, 5, 4, 3, 2],
        [2, 7, 0, 5, 6, 3, 4, 1],
        [3, 6, 5, 0, 7, 2, 1, 4],
        [4, 5, 6, 7, 0, 1, 2, 3],
        [5, 4, 3, 2, 1, 0, 7, 6],
        [6, 3, 4, 1, 2, 7, 0, 5],
        [7, 2, 1, 4, 3, 6, 5, 0],
    ]
    return [[f * k[idx[i][j]] for j in range(8)] for i in range(8)]


# ───────────────────────────────────────────────────────────────────────────
# Structured-mesh problem container
# ───────────────────────────────────────────────────────────────────────────

class Mesh2D:
    """A structured nelx x nely grid of unit Q4 elements.

    Node numbering follows the classic column-major scheme:
    ``node(i, j) = i * (nely + 1) + j`` with i the column (x) and j the row (y).
    DOF ``2*n`` = x, ``2*n+1`` = y.
    """

    def __init__(self, nelx: int, nely: int):
        self.nelx = int(nelx)
        self.nely = int(nely)
        self.nnodes = (self.nelx + 1) * (self.nely + 1)
        self.ndof = 2 * self.nnodes
        self.nel = self.nelx * self.nely
        self._edofs = [self._edof(e) for e in range(self.nel)]

    def node(self, i: int, j: int) -> int:
        return i * (self.nely + 1) + j

    def elem(self, ex: int, ey: int) -> int:
        return ex * self.nely + ey

    def elem_centroid(self, e: int) -> Tuple[float, float]:
        ex = e // self.nely
        ey = e % self.nely
        return (ex + 0.5, ey + 0.5)

    def _edof(self, e: int) -> List[int]:
        ex = e // self.nely
        ey = e % self.nely
        n1 = self.node(ex, ey)
        n2 = self.node(ex + 1, ey)
        n3 = self.node(ex + 1, ey + 1)
        n4 = self.node(ex, ey + 1)
        d: List[int] = []
        for n in (n1, n2, n3, n4):
            d.append(2 * n)
            d.append(2 * n + 1)
        return d

    def edof(self, e: int) -> List[int]:
        return self._edofs[e]


# ───────────────────────────────────────────────────────────────────────────
# Density filter (minimum-member-size manufacturing constraint)
# ───────────────────────────────────────────────────────────────────────────

def _build_filter(mesh: Mesh2D, rmin: float) -> List[List[Tuple[int, float]]]:
    """Linear-hat density filter neighbour weights, radius ``rmin``.

    Returns, per element, a list of ``(neighbour_index, weight)``.  Enforces a
    minimum length scale (members thinner than ``rmin`` are washed out), which
    is the standard density-filter realisation of the minimum-member-size
    manufacturing constraint.
    """
    nelx, nely = mesh.nelx, mesh.nely
    R = max(1.0, float(rmin))
    span = int(math.ceil(R)) - 1
    weights: List[List[Tuple[int, float]]] = [[] for _ in range(mesh.nel)]
    for ex in range(nelx):
        for ey in range(nely):
            e = mesh.elem(ex, ey)
            acc: List[Tuple[int, float]] = []
            for kx in range(max(0, ex - span - 1), min(nelx, ex + span + 2)):
                for ky in range(max(0, ey - span - 1), min(nely, ey + span + 2)):
                    dist = math.hypot(ex - kx, ey - ky)
                    w = R - dist
                    if w > 0.0:
                        acc.append((mesh.elem(kx, ky), w))
            weights[e] = acc
    return weights


def _apply_filter(vec: Sequence[float],
                   weights: List[List[Tuple[int, float]]]) -> List[float]:
    out = [0.0] * len(vec)
    for e, nb in enumerate(weights):
        s = 0.0
        wsum = 0.0
        for j, w in nb:
            s += w * vec[j]
            wsum += w
        out[e] = s / wsum if wsum > 0.0 else vec[e]
    return out


# ───────────────────────────────────────────────────────────────────────────
# Symmetry constraint (mirror about a vertical centre-line)
# ───────────────────────────────────────────────────────────────────────────

def _mirror_pairs(mesh: Mesh2D) -> List[Tuple[int, int]]:
    """Element index pairs mirrored about the vertical mid-plane (x)."""
    nelx, nely = mesh.nelx, mesh.nely
    pairs: List[Tuple[int, int]] = []
    for ex in range(nelx // 2):
        mx = nelx - 1 - ex
        for ey in range(nely):
            pairs.append((mesh.elem(ex, ey), mesh.elem(mx, ey)))
    return pairs


def _enforce_symmetry(x: List[float], pairs: List[Tuple[int, int]]) -> None:
    for a, b in pairs:
        avg = 0.5 * (x[a] + x[b])
        x[a] = avg
        x[b] = avg


# ───────────────────────────────────────────────────────────────────────────
# Overhang / self-support (AM) — geometric projection check + repair
# ───────────────────────────────────────────────────────────────────────────

def _overhang_violations(mesh: Mesh2D, x: Sequence[float],
                         angle_deg: float, threshold: float = 0.5) -> int:
    """Count solid elements whose down-facing support is steeper than the
    self-support angle, measuring +y as the build direction.

    A solid element is self-supporting if at least one of the three elements
    directly below it (left-below, below, right-below) is also solid, OR the
    element rests on the base plate (ey == 0).  The build-angle tolerance is
    folded into how many of the lateral neighbours must hold it: a shallower
    permissible overhang angle requires the element to sit on more support.
    """
    nelx, nely = mesh.nelx, mesh.nely
    ang = max(1e-6, min(89.999, float(angle_deg)))
    # Map angle -> lateral reach (cells) the cone can bridge.
    reach = max(0, int(round(1.0 / math.tan(math.radians(ang)))))
    viol = 0
    for ex in range(nelx):
        for ey in range(1, nely):
            if x[mesh.elem(ex, ey)] <= threshold:
                continue
            supported = False
            for dx in range(-reach, reach + 1):
                kx = ex + dx
                if 0 <= kx < nelx and x[mesh.elem(kx, ey - 1)] > threshold:
                    supported = True
                    break
            if not supported:
                viol += 1
    return viol


def _repair_overhang(mesh: Mesh2D, x: List[float], angle_deg: float) -> None:
    """Bottom-up support projection: an element's density is capped at the
    max of its supporting cone below, so no unsupported solid can survive.
    """
    nelx, nely = mesh.nelx, mesh.nely
    ang = max(1e-6, min(89.999, float(angle_deg)))
    reach = max(0, int(round(1.0 / math.tan(math.radians(ang)))))
    for ey in range(1, nely):
        for ex in range(nelx):
            below_max = 0.0
            for dx in range(-reach, reach + 1):
                kx = ex + dx
                if 0 <= kx < nelx:
                    below_max = max(below_max, x[mesh.elem(kx, ey - 1)])
            e = mesh.elem(ex, ey)
            if x[e] > below_max:
                x[e] = below_max


# ───────────────────────────────────────────────────────────────────────────
# Casting draw-direction (uni-directional projection, monotone along -y)
# ───────────────────────────────────────────────────────────────────────────

def _apply_draw_direction(mesh: Mesh2D, x: List[float]) -> None:
    """Make the part mould-extractable along -y: every element is at least as
    dense as the one directly above it, eliminating undercuts that would lock
    the casting in the die.
    """
    nelx, nely = mesh.nelx, mesh.nely
    for ex in range(nelx):
        carry = 0.0
        for ey in range(nely - 1, -1, -1):
            e = mesh.elem(ex, ey)
            carry = max(carry, x[e])
            x[e] = carry


# ───────────────────────────────────────────────────────────────────────────
# FE solve + compliance + sensitivity for one load case
# ───────────────────────────────────────────────────────────────────────────

def _fe_compliance(mesh: Mesh2D,
                    xphys: Sequence[float],
                    KE: List[List[float]],
                    penal: float,
                    Emin: float,
                    fixed: Sequence[int],
                    F: Sequence[float]) -> Tuple[float, List[float]]:
    """Assemble + solve K u = F, return (compliance, per-element ``ue.KE.ue``).

    SIMP modulus interpolation: ``E(x) = Emin + x^p (1 - Emin)`` (E0 = 1).
    """
    ndof = mesh.ndof
    fixed_set = set(fixed)
    free = [d for d in range(ndof) if d not in fixed_set]
    nf = len(free)
    fidx = {d: i for i, d in enumerate(free)}

    # Assemble the free-DOF stiffness directly as sparse rows (dict per row),
    # which is the only memory-cheap path for the dense Gauss fallback too.
    Krows: List[Dict[int, float]] = [dict() for _ in range(nf)]
    for e in range(mesh.nel):
        scale = Emin + (xphys[e] ** penal) * (1.0 - Emin)
        ed = mesh.edof(e)
        for a in range(8):
            ia = fidx.get(ed[a])
            if ia is None:
                continue
            row = Krows[ia]
            KEa = KE[a]
            for b in range(8):
                jb = fidx.get(ed[b])
                if jb is None:
                    continue
                v = scale * KEa[b]
                if v != 0.0:
                    row[jb] = row.get(jb, 0.0) + v
    bf = [F[d] for d in free]

    # Half-bandwidth: two DOFs per node, columns offset by (nely+1) nodes.
    band = 2 * (mesh.nely + 1) + 4
    try:
        uf = _solve_spd_banded(Krows, bf, band)
    except ValueError:
        # Robust dense fallback (kept total — never propagate).
        dense = [[0.0] * nf for _ in range(nf)]
        for i, r in enumerate(Krows):
            di = dense[i]
            for j, v in r.items():
                di[j] = v
        uf = _solve_dense(dense, bf)
    u = [0.0] * ndof
    for d, i in fidx.items():
        u[d] = uf[i]
    # Per-element strain energy density e^T KE e (unit-modulus).
    ce = [0.0] * mesh.nel
    comp = 0.0
    for e in range(mesh.nel):
        ed = mesh.edof(e)
        ue = [u[d] for d in ed]
        s = 0.0
        for a in range(8):
            KEa = KE[a]
            ua = ue[a]
            row = 0.0
            for b in range(8):
                row += KEa[b] * ue[b]
            s += ua * row
        ce[e] = s
        scale = Emin + (xphys[e] ** penal) * (1.0 - Emin)
        comp += scale * s
    return comp, ce


# ───────────────────────────────────────────────────────────────────────────
# OC and MMA-style update schemes
# ───────────────────────────────────────────────────────────────────────────

def _oc_step(x: Sequence[float], dc: Sequence[float], volfrac: float,
             move: float = 0.2) -> List[float]:
    """Bisection-on-Lagrange-multiplier Optimality-Criteria update.

    Standard SIMP OC: x_new = x * sqrt(-dc / lambda), clamped by a move limit
    and box [1e-3, 1].  ``dc`` are the (negative) compliance sensitivities.
    """
    n = len(x)
    l1, l2 = 1e-12, 1e12
    xnew = list(x)
    target = volfrac * n
    while (l2 - l1) / (l1 + l2) > 1e-9:
        lmid = 0.5 * (l1 + l2)
        tot = 0.0
        for i in range(n):
            ratio = -dc[i] / lmid
            be = math.sqrt(ratio) if ratio > 0.0 else 0.0
            cand = x[i] * be
            lo = max(1e-3, x[i] - move)
            hi = min(1.0, x[i] + move)
            v = min(hi, max(lo, cand))
            xnew[i] = v
            tot += v
        if tot > target:
            l1 = lmid
        else:
            l2 = lmid
    return xnew


def _mma_step(x: Sequence[float], dc: Sequence[float], volfrac: float,
              move: float = 0.2) -> List[float]:
    """A lightweight separable convex (MMA-flavoured) update.

    Uses a reciprocal-style convex approximation of compliance with the same
    volume-constrained bisection as OC.  Monotone-improving under the same
    conditions; offered as an alternative ``update="mma"`` scheme.
    """
    n = len(x)
    l1, l2 = 1e-12, 1e12
    xnew = list(x)
    target = volfrac * n
    while (l2 - l1) / (l1 + l2) > 1e-9:
        lmid = 0.5 * (l1 + l2)
        tot = 0.0
        for i in range(n):
            # Convex linearisation: dx ∝ ( -dc / lambda )^(1/2) but damped.
            ratio = -dc[i] / lmid
            be = ratio ** 0.5 if ratio > 0.0 else 0.0
            be = be ** 0.5  # extra damping → smaller, safer steps than OC
            cand = x[i] * be
            lo = max(1e-3, x[i] - move)
            hi = min(1.0, x[i] + move)
            v = min(hi, max(lo, cand))
            xnew[i] = v
            tot += v
        if tot > target:
            l1 = lmid
        else:
            l2 = lmid
    return xnew


# ───────────────────────────────────────────────────────────────────────────
# Built-in benchmark problem: classic MBB beam
# ───────────────────────────────────────────────────────────────────────────

def mbb_problem(nelx: int, nely: int) -> Dict[str, Any]:
    """Boundary conditions + unit load for the half-MBB beam.

    Symmetry BC on the left edge (x DOFs fixed), a roller at the bottom-right
    corner (y DOF fixed), and a downward unit point load at the top-left node.
    This is the textbook problem whose optimum compliance / volume fraction
    is a well-known regression target.
    """
    mesh = Mesh2D(nelx, nely)
    fixed: List[int] = []
    for j in range(nely + 1):
        fixed.append(2 * mesh.node(0, j))  # left edge: x symmetry
    fixed.append(2 * mesh.node(nelx, 0) + 1)  # bottom-right roller: y
    F = [0.0] * mesh.ndof
    F[2 * mesh.node(0, nely) + 1] = -1.0  # downward load, top-left
    return {"fixed": fixed, "F": F, "nelx": nelx, "nely": nely}


# ───────────────────────────────────────────────────────────────────────────
# Core solver: multi-load-case, manufacturing-constrained SIMP
# ───────────────────────────────────────────────────────────────────────────

def optimize(
    nelx: int,
    nely: int,
    volfrac: float,
    *,
    load_cases: Optional[List[Dict[str, Any]]] = None,
    load_weights: Optional[List[float]] = None,
    fixed: Optional[Sequence[int]] = None,
    penal: float = 3.0,
    rmin: float = 1.5,
    max_iter: int = 60,
    tol: float = 1e-3,
    update: str = "oc",
    nu: float = 0.3,
    Emin: float = 1e-9,
    symmetry: bool = False,
    overhang_angle: Optional[float] = None,
    draw_direction: bool = False,
    x_init: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Run manufacturing-constrained, multi-load-case SIMP.

    ``load_cases`` is a list of ``{"F": [...], "fixed": [...]}`` dicts; the
    objective is the ``load_weights``-weighted sum of per-case compliance.
    When omitted a single MBB load case is used.  Never raises.
    """
    try:
        if not (0.0 < volfrac < 1.0):
            return {"ok": False, "reason": "volfrac must be in (0, 1)"}
        if nelx < 1 or nely < 1:
            return {"ok": False, "reason": "nelx and nely must be >= 1"}
        if update not in ("oc", "mma"):
            return {"ok": False, "reason": f"unknown update scheme '{update}'"}

        mesh = Mesh2D(nelx, nely)

        if not load_cases:
            mbb = mbb_problem(nelx, nely)
            load_cases = [{"F": mbb["F"], "fixed": mbb["fixed"]}]
            if fixed is None:
                fixed = mbb["fixed"]

        ncase = len(load_cases)
        if load_weights is None:
            load_weights = [1.0 / ncase] * ncase
        if len(load_weights) != ncase:
            return {"ok": False, "reason": "load_weights length != load_cases"}

        KE = _ke_q4(1.0, nu)
        weights = _build_filter(mesh, rmin)
        sym_pairs = _mirror_pairs(mesh) if symmetry else []

        x = [float(volfrac)] * mesh.nel if x_init is None else [
            min(1.0, max(1e-3, float(v))) for v in x_init
        ]
        if len(x) != mesh.nel:
            return {"ok": False, "reason": "x_init length != element count"}

        history: List[Dict[str, float]] = []
        prev_c = None
        last_change = 1.0
        it = 0
        for it in range(1, int(max_iter) + 1):
            xphys = _apply_filter(x, weights)
            if symmetry:
                _enforce_symmetry(xphys, sym_pairs)

            total_c = 0.0
            dc = [0.0] * mesh.nel
            for w, case in zip(load_weights, load_cases):
                cF = case.get("F")
                cfix = case.get("fixed", fixed if fixed is not None else [])
                if cF is None or len(cF) != mesh.ndof:
                    return {"ok": False,
                            "reason": "load case F missing or wrong length"}
                c, ce = _fe_compliance(mesh, xphys, KE, penal, Emin, cfix, cF)
                total_c += w * c
                for e in range(mesh.nel):
                    # d(scale)/dx = p x^(p-1) (1 - Emin)
                    dscale = penal * (xphys[e] ** (penal - 1.0)) * (1.0 - Emin)
                    dc[e] += -w * dscale * ce[e]

            # Chain the density filter through the sensitivities.
            dcf = _apply_filter(dc, weights)
            if symmetry:
                _enforce_symmetry(dcf, sym_pairs)

            if update == "oc":
                xnew = _oc_step(x, dcf, volfrac)
            else:
                xnew = _mma_step(x, dcf, volfrac)

            if symmetry:
                _enforce_symmetry(xnew, sym_pairs)
            if draw_direction:
                _apply_draw_direction(mesh, xnew)
            if overhang_angle is not None:
                _repair_overhang(mesh, xnew, overhang_angle)

            # Renormalise volume after any geometric repair so the constraint
            # stays satisfied at convergence.
            if draw_direction or overhang_angle is not None:
                cur = sum(xnew) / mesh.nel
                if cur > 1e-12:
                    s = volfrac / cur
                    xnew = [min(1.0, max(1e-3, v * s)) for v in xnew]

            last_change = max(abs(a - b) for a, b in zip(xnew, x))
            x = xnew

            vol = sum(_apply_filter(x, weights)) / mesh.nel
            history.append({"iter": it, "compliance": total_c,
                            "volume": vol, "change": last_change})

            if prev_c is not None and prev_c > 0.0:
                rel = abs(total_c - prev_c) / prev_c
                if rel < tol and last_change < 0.02:
                    prev_c = total_c
                    break
            prev_c = total_c

        xphys = _apply_filter(x, weights)
        if symmetry:
            _enforce_symmetry(xphys, sym_pairs)
        if draw_direction:
            _apply_draw_direction(mesh, xphys)
        if overhang_angle is not None:
            _repair_overhang(mesh, xphys, overhang_angle)

        final_c = history[-1]["compliance"] if history else 0.0
        final_v = sum(xphys) / mesh.nel

        result: Dict[str, Any] = {
            "ok": True,
            "compliance": final_c,
            "volume_fraction": final_v,
            "iterations": it,
            "converged": (prev_c is not None
                          and len(history) >= 2
                          and last_change < 0.05),
            "history": history,
            "density": xphys,
            "nelx": nelx,
            "nely": nely,
            "update": update,
            "n_load_cases": ncase,
        }
        return result
    except Exception as exc:  # pragma: no cover - defensive total guarantee
        return {"ok": False, "reason": f"optimize failed: {exc}"}


# ───────────────────────────────────────────────────────────────────────────
# Multi-objective: compliance vs. mass via epsilon-constraint Pareto sweep
# ───────────────────────────────────────────────────────────────────────────

def pareto_sweep(
    nelx: int,
    nely: int,
    volfracs: Sequence[float],
    *,
    load_cases: Optional[List[Dict[str, Any]]] = None,
    load_weights: Optional[List[float]] = None,
    fixed: Optional[Sequence[int]] = None,
    penal: float = 3.0,
    rmin: float = 1.5,
    max_iter: int = 40,
    tol: float = 1e-3,
    update: str = "oc",
    second_metric: Optional[Callable[[Dict[str, Any]], float]] = None,
) -> Dict[str, Any]:
    """Epsilon-constraint Pareto front of *compliance vs. mass*.

    Each ``volfrac`` is treated as the mass (volume) epsilon-constraint; for
    each we minimise compliance.  The returned ``front`` is a list of
    ``{"mass": vf, "compliance": c[, "metric": m]}`` sorted by ascending mass.
    A well-posed front is monotone: compliance must rise as mass falls.
    """
    try:
        vfs = sorted(float(v) for v in volfracs)
        if not vfs:
            return {"ok": False, "reason": "volfracs is empty"}
        for v in vfs:
            if not (0.0 < v < 1.0):
                return {"ok": False,
                        "reason": "every volfrac must be in (0, 1)"}

        front: List[Dict[str, float]] = []
        for vf in vfs:
            r = optimize(
                nelx, nely, vf,
                load_cases=load_cases, load_weights=load_weights,
                fixed=fixed, penal=penal, rmin=rmin,
                max_iter=max_iter, tol=tol, update=update,
            )
            if not r.get("ok"):
                return {"ok": False,
                        "reason": f"sub-optimisation failed at vf={vf}: "
                                  f"{r.get('reason')}"}
            pt: Dict[str, float] = {
                "mass": r["volume_fraction"],
                "compliance": r["compliance"],
            }
            if second_metric is not None:
                try:
                    pt["metric"] = float(second_metric(r))
                except Exception as exc:
                    return {"ok": False,
                            "reason": f"second_metric failed: {exc}"}
            front.append(pt)

        # Sort ascending by the requested-mass epsilon for a clean Pareto.
        order = sorted(range(len(vfs)), key=lambda i: vfs[i])
        front = [front[i] for i in order]

        # Monotone non-dominated check: as mass increases compliance must
        # not increase (lighter structures are at best as stiff).
        monotone = all(
            front[i + 1]["compliance"] <= front[i]["compliance"] * (1.0 + 1e-6)
            for i in range(len(front) - 1)
        )
        return {
            "ok": True,
            "front": front,
            "monotone": monotone,
            "n_points": len(front),
        }
    except Exception as exc:  # pragma: no cover - total guarantee
        return {"ok": False, "reason": f"pareto_sweep failed: {exc}"}


# ───────────────────────────────────────────────────────────────────────────
# Lattice-infill: graded density field → TPMS wall thickness
# ───────────────────────────────────────────────────────────────────────────

def _gibson_ashby_thickness(period: float, relative_density: float) -> float:
    """Closed-cell Gibson-Ashby wall thickness fallback.

    For a closed-cell TPMS-like cell the relative density scales roughly with
    (t / period); inverting the Gibson-Ashby relation rho* ≈ C (t/L) with
    C ≈ 1 gives t ≈ rho * L.  Half is the physical wall.
    """
    return 0.5 * period * relative_density


def lattice_infill(
    density: Sequence[float],
    *,
    period: float = 2.0,
    surface: str = "gyroid",
    rho_min: float = 0.05,
    rho_max: float = 0.95,
) -> Dict[str, Any]:
    """Map a graded relative-density field to per-cell TPMS wall thickness.

    The optimised density field becomes a *graded* lattice: dense regions get
    thick TPMS walls, sparse regions thin ones.  Uses the shipped
    ``frep/sdf.tpms_wall_thickness`` when importable; otherwise a
    Gibson-Ashby closed-cell estimate.  Never raises.
    """
    try:
        if period <= 0.0:
            return {"ok": False, "reason": "period must be positive"}
        if not density:
            return {"ok": False, "reason": "density field is empty"}
        lo = max(1e-3, float(rho_min))
        hi = min(0.999, float(rho_max))
        if lo >= hi:
            return {"ok": False, "reason": "rho_min must be < rho_max"}

        cells: List[Dict[str, float]] = []
        backend = "tpms" if _TPMS_AVAILABLE else "gibson_ashby"
        for raw in density:
            rd = min(hi, max(lo, float(raw)))
            if _TPMS_AVAILABLE:
                res = _tpms_wall_thickness(period, rd, surface)
                if not res.get("ok"):
                    # Fall back per-cell if the empirical map rejects it.
                    t = _gibson_ashby_thickness(period, rd)
                    iso = float("nan")
                else:
                    t = float(res["effective_thickness"])
                    iso = float(res["iso_value"])
            else:
                t = _gibson_ashby_thickness(period, rd)
                iso = float("nan")
            cells.append({"relative_density": rd,
                          "wall_thickness": t,
                          "iso_value": iso})

        thicknesses = [c["wall_thickness"] for c in cells]
        return {
            "ok": True,
            "backend": backend,
            "surface": surface,
            "period": float(period),
            "cells": cells,
            "min_thickness": min(thicknesses),
            "max_thickness": max(thicknesses),
            "n_cells": len(cells),
        }
    except Exception as exc:  # pragma: no cover - total guarantee
        return {"ok": False, "reason": f"lattice_infill failed: {exc}"}


# ───────────────────────────────────────────────────────────────────────────
# Geometric verification helpers (used by tests and the LLM tool)
# ───────────────────────────────────────────────────────────────────────────

def count_overhang_violations(nelx: int, nely: int, density: Sequence[float],
                              angle_deg: float,
                              threshold: float = 0.5) -> int:
    """Public geometric overhang check on a finished density field."""
    mesh = Mesh2D(nelx, nely)
    return _overhang_violations(mesh, density, angle_deg, threshold)


def isolated_island_count(nelx: int, nely: int, density: Sequence[float],
                          max_cells: int, threshold: float = 0.5) -> int:
    """Number of connected solid islands with <= ``max_cells`` elements.

    A density filter of radius ``rmin`` provably attenuates any solid feature
    narrower than the kernel, so the count of such tiny islands must be
    *monotone non-increasing* as ``rmin`` grows — the property the
    minimum-member-size test asserts.
    """
    mesh = Mesh2D(nelx, nely)
    solid = [1 if density[e] > threshold else 0 for e in range(mesh.nel)]
    seen = [False] * mesh.nel
    small = 0
    for ex in range(nelx):
        for ey in range(nely):
            e = mesh.elem(ex, ey)
            if seen[e] or not solid[e]:
                continue
            stack = [e]
            seen[e] = True
            comp = 0
            while stack:
                ce = stack.pop()
                comp += 1
                cex, cey = ce // nely, ce % nely
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    kx, ky = cex + dx, cey + dy
                    if 0 <= kx < nelx and 0 <= ky < nely:
                        ne = mesh.elem(kx, ky)
                        if not seen[ne] and solid[ne]:
                            seen[ne] = True
                            stack.append(ne)
            if comp <= max_cells:
                small += 1
    return small


def min_member_ok(nelx: int, nely: int, density: Sequence[float],
                  rmin: float, threshold: float = 0.5) -> bool:
    """True iff no solid feature is thinner than the filter radius ``rmin``.

    Realised as a morphological-erosion test: erode the thresholded solid set
    by a structuring disc of radius ``rmin / 2``.  A connected solid feature
    of width >= ``rmin`` necessarily contains at least one fully-eroded cell
    (its medial core survives); a feature narrower than ``rmin`` is annihilated
    entirely.  So the structure satisfies minimum-member-size iff *every*
    connected solid component retains at least one eroded cell.  This is grid-
    robust (it does not require exact morphological-opening idempotence, which
    a digital disc never gives on a coarse mesh).
    """
    mesh = Mesh2D(nelx, nely)
    r = max(1.0, float(rmin)) / 2.0
    rr = r * r
    solid = [density[e] > threshold for e in range(mesh.nel)]

    s = int(math.ceil(r))
    offsets = [(dx, dy)
               for dx in range(-s, s + 1)
               for dy in range(-s, s + 1)
               if dx * dx + dy * dy <= rr]

    # Erosion: a cell survives iff its whole disc neighbourhood is solid.
    eroded = [False] * mesh.nel
    for ex in range(nelx):
        for ey in range(nely):
            if not solid[mesh.elem(ex, ey)]:
                continue
            keep = True
            for dx, dy in offsets:
                kx, ky = ex + dx, ey + dy
                if not (0 <= kx < nelx and 0 <= ky < nely
                        and solid[mesh.elem(kx, ky)]):
                    keep = False
                    break
            eroded[mesh.elem(ex, ey)] = keep

    # Every connected solid component must contain an eroded (core) cell.
    seen = [False] * mesh.nel
    for ex in range(nelx):
        for ey in range(nely):
            e = mesh.elem(ex, ey)
            if seen[e] or not solid[e]:
                continue
            stack = [e]
            seen[e] = True
            has_core = False
            while stack:
                ce = stack.pop()
                if eroded[ce]:
                    has_core = True
                cex, cey = ce // nely, ce % nely
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    kx, ky = cex + dx, cey + dy
                    if 0 <= kx < nelx and 0 <= ky < nely:
                        ne = mesh.elem(kx, ky)
                        if not seen[ne] and solid[ne]:
                            seen[ne] = True
                            stack.append(ne)
            if not has_core:
                return False
    return True


# ───────────────────────────────────────────────────────────────────────────
# LLM tool registration (mirrors kerf_topo/tools.py conventions; gated)
# ───────────────────────────────────────────────────────────────────────────

import json  # noqa: E402 - kept local to the tool layer like tools.py

topo_advanced_spec = ToolSpec(
    name="topo_advanced",
    description=(
        "Production-grade topology optimization: multi-load-case, "
        "multi-objective Pareto sweep, manufacturing constraints "
        "(min-member-size, AM overhang, casting draw, symmetry), and "
        "graded TPMS lattice-infill. Pure in-process solver."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["optimize", "pareto", "lattice"],
            },
            "nelx": {"type": "integer"},
            "nely": {"type": "integer"},
            "volume_fraction": {"type": "number"},
            "volume_fractions": {
                "type": "array", "items": {"type": "number"},
            },
            "penalization_power": {"type": "number"},
            "filter_radius": {"type": "number"},
            "max_iterations": {"type": "integer"},
            "update": {"type": "string", "enum": ["oc", "mma"]},
            "symmetry": {"type": "boolean"},
            "overhang_angle": {"type": "number"},
            "draw_direction": {"type": "boolean"},
            "lattice_period": {"type": "number"},
            "lattice_surface": {"type": "string"},
        },
        "required": ["mode"],
    },
)


@register(topo_advanced_spec, write=False)
async def run_topo_advanced(ctx: ProjectCtx, args: bytes) -> str:
    """LLM entry-point.  Frames the objective + constraints in JSON, runs the
    pure-Python solver in-process, and reads back a verified result.
    """
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    mode = (a.get("mode") or "").strip()
    nelx = int(a.get("nelx", 30))
    nely = int(a.get("nely", 10))
    penal = float(a.get("penalization_power", 3.0))
    rmin = float(a.get("filter_radius", 1.5))
    max_iter = int(a.get("max_iterations", 50))
    update = a.get("update", "oc")

    if mode == "optimize":
        r = optimize(
            nelx, nely, float(a.get("volume_fraction", 0.4)),
            penal=penal, rmin=rmin, max_iter=max_iter, update=update,
            symmetry=bool(a.get("symmetry", False)),
            overhang_angle=a.get("overhang_angle"),
            draw_direction=bool(a.get("draw_direction", False)),
        )
    elif mode == "pareto":
        r = pareto_sweep(
            nelx, nely,
            a.get("volume_fractions") or [0.2, 0.3, 0.4, 0.5],
            penal=penal, rmin=rmin, max_iter=max_iter, update=update,
        )
    elif mode == "lattice":
        base = optimize(
            nelx, nely, float(a.get("volume_fraction", 0.4)),
            penal=penal, rmin=rmin, max_iter=max_iter, update=update,
        )
        if not base.get("ok"):
            return err_payload(base.get("reason", "optimize failed"), "ERROR")
        r = lattice_infill(
            base["density"],
            period=float(a.get("lattice_period", 2.0)),
            surface=a.get("lattice_surface", "gyroid"),
        )
    else:
        return err_payload(f"unknown mode '{mode}'", "BAD_ARGS")

    if not r.get("ok"):
        return err_payload(r.get("reason", "optimization failed"), "ERROR")
    return ok_payload(r)
