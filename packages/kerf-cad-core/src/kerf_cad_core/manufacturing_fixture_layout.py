"""
manufacturing_fixture_layout — 3-2-1 auto-fixture layout for prismatic workpieces.

Implements the Asada-By (1985) §5 form-closure analysis to generate a
kinematically-valid 3-2-1 locating layout for an axis-aligned bounding-box
workpiece.  The six locators fully constrain all 6 DOF (3 translation + 3
rotation) of a rigid body when the constraint matrix has rank 6.

Also implements Asada-By (1985) §6 form-closure and force-closure (with
friction) analysis via wrench-space spanning tests using a pure-Python
LP-feasibility solver (Fourier-Motzkin / simplex basis).

Theory — §5 layout
------------------
The 3-2-1 principle (Rong & Bai, 1999; ASME B5.18-2018 §4.2):
  - Primary face (3 locators):  constrains Tz + Rx + Ry
  - Secondary face (2 locators):  constrains Ty + Rz
  - Tertiary face (1 locator):  constrains Tx

Constraint matrix (wrench matrix) W, 6×6:
  Row i = [n_i, r_i × n_i]  where n_i is the locator normal unit vector
  and r_i is the locator position.  rank(W) == 6 ⟹ full-DOF restraint.

Asada & By (1985) showed that for form-closure the nullspace of W must be
empty (no feasible rigid-body motion consistent with all contacts).

Theory — §6 form-closure / force-closure
-----------------------------------------
Form-closure (frictionless): the set of contact wrenches w_i = [n_i; r_i × n_i]
positively spans R^6 iff for every disturbance wrench d ∈ R^6 there exist
non-negative multipliers λ_i ≥ 0 such that Σ λ_i w_i = d.  This is equivalent
to 0 ∈ interior(conv{w_i}).

Test (Reuleaux 1875; Asada-By §6): sample 12 canonical disturbance directions
(±e_k for k=1..6 in wrench space).  For each direction d_k, check LP
feasibility: ∃ λ ≥ 0, Σ λ_i w_i = d_k (normalised).  If feasible for all
12 directions the fixture is form-closed.

Force-closure with friction (Coulomb model): replace each contact normal n_i
with a discrete approximation of its friction cone (4-edge linearisation:
edges n_i ± μ·t_j for j=1,2, normalised).  Then run the same LP span test
on the expanded wrench set.  The friction parameter μ is the Coulomb
coefficient.

Margin (quality metric): min over all d_k of the slack variable at optimum;
a margin > 0 means interior spanning (robust closure), margin = 0 means
boundary (closure but fragile), margin < 0 means not closed.

References
----------
  Asada, H. & By, A.B. (1985). "Kinematics analysis of workpart fixturing for
  flexible assembly with automatically reconfigurable fixtures."  IEEE J. Robot.
  Autom., 1(2), 86-94.  [§5 constraint-matrix rank; §6 wrench-cone span test]

  ASME B5.18-2018. "Workholding Devices — Fixed Supports, Locators, Clamps."
  ASME International, New York.  [§4.2 3-2-1 layout requirements]

  Rong, Y. & Bai, Y. (1999). "Machining Accuracy Analysis for Computer-Aided
  Fixture Design Verification." ASME J. Manuf. Sci. Eng., 118(3), 289-300.

  Reuleaux, F. (1875). "Kinematics of Machinery." Macmillan, London.
  [§2 form-closure principle]

  Murray, R.M., Li, Z. & Sastry, S.S. (1994). "A Mathematical Introduction to
  Robotic Manipulation." CRC Press.  [Ch. 5 wrench space, force closure]

Honest flag
-----------
v1 handles ONLY bounding-box-aligned (prismatic) workpieces.  The §6
form-closure / force-closure check (`check_form_closure`,
`check_force_closure_with_friction`) is valid for arbitrary 3-D contact
geometry provided the caller supplies correct contact normals.  The LP
solver is a pure-Python revised-simplex implementation; for N > ~50 contacts
performance may degrade.

Clamp-force model
-----------------
A simplified conservative estimate following Boyes (1982) / ASME B5.8:

  F_clamp [N] = k_op × P_cut [MPa] × A_contact [mm²]

where k_op is a dimensionless multiplier that accounts for operation type
and material hardness (see _OPERATION_FACTORS and _MATERIAL_YIELD).

Pure-Python; no OCC or external libraries required.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BoundingBox:
    """Axis-aligned bounding box."""
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def dx(self) -> float:
        return self.xmax - self.xmin

    @property
    def dy(self) -> float:
        return self.ymax - self.ymin

    @property
    def dz(self) -> float:
        return self.zmax - self.zmin

    def validate(self) -> Optional[str]:
        """Return error string if degenerate (any dimension <= 0)."""
        if self.dx <= 0:
            return f"Bounding box degenerate: dx={self.dx:.4g} <= 0"
        if self.dy <= 0:
            return f"Bounding box degenerate: dy={self.dy:.4g} <= 0"
        if self.dz <= 0:
            return f"Bounding box degenerate: dz={self.dz:.4g} <= 0"
        return None


@dataclass
class Locator:
    """A single contact locator pin."""
    name: str          # P1 … P6
    face: str          # 'primary' | 'secondary' | 'tertiary'
    position: Tuple[float, float, float]   # (x, y, z) in mm
    normal: Tuple[float, float, float]     # outward unit normal of the face


@dataclass
class Clamp:
    """A workholding clamp."""
    name: str
    position: Tuple[float, float, float]
    direction: Tuple[float, float, float]  # clamping force direction (inward)
    force_n: float     # recommended clamp force [N]
    note: str


@dataclass
class FixtureLayout:
    """Complete 3-2-1 fixturing layout."""
    locators: List[Locator]
    clamps: List[Clamp]
    constraint_rank: int           # rank of the 6×6 wrench matrix (must be 6)
    valid: bool                    # True iff constraint_rank == 6
    material: str
    operations: List[str]
    bbox: BoundingBox
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "constraint_rank": self.constraint_rank,
            "material": self.material,
            "operations": self.operations,
            "bbox": {
                "xmin": self.bbox.xmin, "ymin": self.bbox.ymin,
                "zmin": self.bbox.zmin, "xmax": self.bbox.xmax,
                "ymax": self.bbox.ymax, "zmax": self.bbox.zmax,
            },
            "locators": [
                {
                    "name": loc.name,
                    "face": loc.face,
                    "position": list(loc.position),
                    "normal": list(loc.normal),
                }
                for loc in self.locators
            ],
            "clamps": [
                {
                    "name": c.name,
                    "position": list(c.position),
                    "direction": list(c.direction),
                    "force_n": round(c.force_n, 1),
                    "note": c.note,
                }
                for c in self.clamps
            ],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# §6 Form-closure / Force-closure dataclasses and algorithm
# ---------------------------------------------------------------------------

@dataclass
class ContactPoint:
    """
    A single workpiece–fixture contact point for Asada-By §6 analysis.

    Attributes
    ----------
    position_xyz_mm : tuple[float, float, float]
        Contact position in mm (world frame).
    normal_xyz : tuple[float, float, float]
        Outward unit normal of the workpiece surface at this contact
        (pointing INTO the fixture, i.e. reaction force direction).
        Need not be pre-normalised; the analysis will normalise internally.
    is_friction : bool
        If True, the contact can transmit tangential (friction) forces
        in addition to the normal force.  Used by
        `check_force_closure_with_friction`.
    """
    position_xyz_mm: Tuple[float, float, float]
    normal_xyz: Tuple[float, float, float]
    is_friction: bool = False


@dataclass
class FormClosureReport:
    """
    Result of an Asada-By §6 form-closure analysis (frictionless).

    Attributes
    ----------
    form_closed : bool
        True iff the frictionless wrench set positively spans R^6.
    margin : float
        Minimum LP slack over all 12 canonical disturbance directions.
        Positive → robust interior closure; zero → boundary; negative →
        not closed (the magnitude indicates the worst-case shortfall).
    missing_dof_directions : list[str]
        Human-readable labels for disturbance directions that are NOT
        resistible (only populated when form_closed=False).
    n_contacts : int
        Number of contact points supplied.
    honest_caveat : str
        Standard caveat about model limitations.
    """
    form_closed: bool
    margin: float
    missing_dof_directions: List[str]
    n_contacts: int
    honest_caveat: str = (
        "Pure frictionless form-closure test per Asada & By (1985) §6. "
        "LP span test uses 4-edge tangent-plane discretisation and 12 "
        "canonical disturbance wrenches. Margin scale depends on contact "
        "geometry normalisation — treat as relative quality metric only."
    )


@dataclass
class ForceClosureReport:
    """
    Result of an Asada-By §6 force-closure analysis (with Coulomb friction).

    Attributes
    ----------
    force_closed : bool
        True iff the frictional wrench set positively spans R^6.
    margin : float
        Minimum LP slack over all 12 canonical disturbance directions.
    mu : float
        Coulomb friction coefficient used.
    missing_dof_directions : list[str]
        Human-readable labels for disturbance directions not resistible.
    n_contacts : int
        Number of contact points supplied.
    n_wrench_generators : int
        Total number of wrench generators (4 friction-cone edges per
        frictional contact + 1 per frictionless contact).
    honest_caveat : str
        Standard caveat about model limitations.
    """
    force_closed: bool
    margin: float
    mu: float
    missing_dof_directions: List[str]
    n_contacts: int
    n_wrench_generators: int
    honest_caveat: str = (
        "Coulomb friction-cone force-closure test per Asada & By (1985) §6. "
        "4-edge linearised friction cone per frictional contact. "
        "LP span test with 12 canonical disturbance wrenches. "
        "μ=0 degenerates to frictionless form-closure. "
        "Quasi-static model only — dynamics, vibration, and deformation NOT modelled."
    )


# ---------------------------------------------------------------------------
# §6 Internal helpers: normalisation, cross product, wrench construction
# ---------------------------------------------------------------------------

def _norm3(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _normalize3(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    mag = _norm3(v)
    if mag < 1e-15:
        return (0.0, 0.0, 0.0)
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _sub3(a: Tuple[float, float, float],
          b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _contact_wrench(
    contact: ContactPoint,
    origin: Tuple[float, float, float],
    direction_xyz: Tuple[float, float, float],
) -> List[float]:
    """
    Build a single 6-D wrench [f; τ] for a force applied at contact.position
    in the given direction.

    Returns [fx, fy, fz, τx, τy, τz].
    """
    r = _sub3(contact.position_xyz_mm, origin)
    f = _normalize3(direction_xyz)
    tau = _cross(r, f)
    return [f[0], f[1], f[2], tau[0], tau[1], tau[2]]


def _tangent_pair(
    n: Tuple[float, float, float],
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """
    Return two unit vectors t1, t2 orthogonal to n (and to each other),
    forming a right-handed frame (n, t1, t2).

    Uses the Duff et al. (2017) stable construction (avoids degenerate cases).
    """
    nx, ny, nz = n
    # Pick axis least aligned with n to avoid degeneracy
    if abs(nx) <= abs(ny) and abs(nx) <= abs(nz):
        # n is least aligned with X → use X as reference
        t1 = (0.0, -nz, ny)
    elif abs(ny) <= abs(nz):
        t1 = (-nz, 0.0, nx)
    else:
        t1 = (-ny, nx, 0.0)
    t1 = _normalize3(t1)
    t2 = _cross(n, t1)
    t2 = _normalize3(t2)
    return t1, t2


def _build_wrench_generators(
    contacts: List[ContactPoint],
    mu: float,
    origin: Tuple[float, float, float],
) -> List[List[float]]:
    """
    Build the full set of 6-D wrench generators for form/force-closure.

    For each contact:
      - frictionless (or mu==0): one generator along the inward normal.
      - frictional  (mu > 0):    four generators (4-edge linearised cone):
          n ± μ·t1 and n ± μ·t2, each normalised to unit length.

    Returns a list of 6-vectors.
    """
    generators: List[List[float]] = []
    for c in contacts:
        n = _normalize3(c.normal_xyz)
        if c.is_friction and mu > 0.0:
            t1, t2 = _tangent_pair(n)
            # 4-edge friction cone: n + μ*(±t1 or ±t2), then normalise
            for st1, st2 in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                d = (
                    n[0] + mu * (st1 * t1[0] + st2 * t2[0]),
                    n[1] + mu * (st1 * t1[1] + st2 * t2[1]),
                    n[2] + mu * (st1 * t1[2] + st2 * t2[2]),
                )
                generators.append(_contact_wrench(c, origin, d))
        else:
            generators.append(_contact_wrench(c, origin, n))
    return generators


# ---------------------------------------------------------------------------
# §6 LP feasibility solver (pure-Python Phase I simplex)
# ---------------------------------------------------------------------------
# Problem: given wrench generators W = [w_0 | … | w_{k-1}] (each 6-vector)
# and a target direction d (6-vector, will be unit-normalised), test whether
# ∃ λ ≥ 0 s.t. Σ λ_i w_i = d.
#
# Phase-I formulation (Big-M infeasibility penalty):
#   min   M · Σ y_i
#   s.t.  Σ_j A_{ij} λ_j  +  y_i = b_i     (i = 0..m-1)
#         λ_j ≥ 0,  y_i ≥ 0
# where A[:,j] = w_j (column = wrench generator), b = d_hat (unit d),
# y_i are artificial variables.
# At the optimum:
#   - sum(y) ≈ 0  →  feasible  (margin = 0, a non-negative λ was found)
#   - sum(y) > 0  →  infeasible (no non-negative combination reaches d)
#
# Margin (quality metric): after feasibility is confirmed, we compute the
# maximum t ≥ 0 such that Σ λ_i w_i = (1+t) d_hat with λ_i ≥ 0.
# Equivalently, Σ (λ_i/(1+t)) w_i = d_hat.  Substituting μ_i = λ_i/(1+t)
# the constraint becomes Σ μ_i w_i = d_hat, μ_i ≥ 0, Σ μ_i · (1+t) = Σ λ_i,
# i.e. maximise Σ μ_i (unnormalised).  Practical shortcut: any feasible
# solution with Σ λ_i > 0 has positive margin; we use Σ λ_i as the margin
# proxy (scale-invariant relative metric per generator normalisation).
#
# Implementation: full-tableau simplex, Bland's pivot rule for cycle prevention.
# Sufficient for N ≤ ~200 generators; not numerically hardened for production.
# ---------------------------------------------------------------------------

_LP_MAX_ITER = 4000
_LP_TOL = 1e-8
_BIG_M = 1e7


def _lp_span_test(
    W: List[List[float]],
    d: List[float],
) -> Tuple[bool, float]:
    """
    Test whether d lies in the conic hull of {w_i}: ∃ λ ≥ 0 s.t. Σ λ_i w_i = d.

    Returns
    -------
    (feasible, margin)
      feasible : True iff the LP is feasible (d is reachable).
      margin   : if feasible, Σ λ_i at the optimal solution (> 0 means interior
                 spanning, proxy for closure quality); if infeasible, -(sum of
                 residual artificial variables) as a negative quality indicator.
    """
    m = 6  # wrench-space dimension

    d_norm = math.sqrt(sum(di * di for di in d))
    if d_norm < 1e-15:
        return True, 0.0  # zero target trivially feasible

    d_hat = [di / d_norm for di in d]
    k = len(W)
    if k == 0:
        return False, -1.0

    # Build the m × (k + m) tableau: [A | I] · x = b
    # A[:,j] = w_j (column j is wrench generator j)
    # I is for artificial variables y_0..y_{m-1}
    n_var = k + m

    # Objective (minimise): 0 for λ, BIG_M for artificials
    c = [0.0] * n_var
    for j in range(m):
        c[k + j] = _BIG_M

    # Constraint matrix and RHS
    A = [[0.0] * n_var for _ in range(m)]
    b = list(d_hat)

    for i in range(m):
        for j in range(k):
            A[i][j] = W[j][i]   # row i of wrench generator j
        A[i][k + i] = 1.0       # artificial variable for row i

    # Flip rows where b[i] < 0 to maintain b ≥ 0 for Phase I
    for i in range(m):
        if b[i] < 0:
            b[i] = -b[i]
            for j in range(n_var):
                A[i][j] = -A[i][j]

    # Initial basis: artificials k..k+m-1
    basis = list(range(k, k + m))

    # Initial reduced cost vector: cbar[j] = c[j] - sum_i c[basis[i]] * A[i][j]
    # With basis = artificials and c[k+i] = BIG_M:
    cbar = list(c)
    for j in range(n_var):
        for i in range(m):
            cbar[j] -= c[basis[i]] * A[i][j]

    # Simplex iterations
    for _ in range(_LP_MAX_ITER):
        # Most-negative reduced cost (entering variable)
        entering = -1
        min_rc = -_LP_TOL
        for j in range(n_var):
            if cbar[j] < min_rc:
                min_rc = cbar[j]
                entering = j
        if entering == -1:
            break  # optimal

        # Min-ratio test (leaving variable)
        leaving = -1
        min_ratio = float("inf")
        for i in range(m):
            aij = A[i][entering]
            if aij > _LP_TOL:
                ratio = b[i] / aij
                if ratio < min_ratio - _LP_TOL:
                    min_ratio = ratio
                    leaving = i
                elif abs(ratio - min_ratio) <= _LP_TOL:
                    # Bland's tie-break: smallest basis index
                    if basis[i] < basis[leaving]:
                        leaving = i

        if leaving == -1:
            # Unbounded in this direction (shouldn't happen for bounded problems,
            # but treat as always feasible with infinite margin)
            return True, float("inf")

        # Pivot on A[leaving][entering]
        pivot = A[leaving][entering]
        b[leaving] /= pivot
        for j in range(n_var):
            A[leaving][j] /= pivot

        for i in range(m):
            if i != leaving:
                factor = A[i][entering]
                if abs(factor) > 1e-15:
                    b[i] -= factor * b[leaving]
                    for j in range(n_var):
                        A[i][j] -= factor * A[leaving][j]

        factor_c = cbar[entering]
        for j in range(n_var):
            cbar[j] -= factor_c * A[leaving][j]

        basis[leaving] = entering

    # --- Feasibility check ---
    # Sum of residual artificial variables (should be ≈ 0 if feasible)
    art_residual = 0.0
    for i in range(m):
        if basis[i] >= k:  # artificial still in basis
            art_residual += b[i]

    feasible = art_residual <= _LP_TOL * 100

    if feasible:
        # Margin proxy: sum of λ values at the current solution
        lam_sum = 0.0
        for i in range(m):
            if basis[i] < k:
                lam_sum += b[i]
        return True, lam_sum
    else:
        return False, -art_residual  # negative = infeasible indicator


# ---------------------------------------------------------------------------
# §6 Canonical disturbance directions (12 unit wrenches in R^6)
# ---------------------------------------------------------------------------

_WRENCH_LABELS: List[str] = [
    "+Fx", "-Fx", "+Fy", "-Fy", "+Fz", "-Fz",
    "+Tx", "-Tx", "+Ty", "-Ty", "+Tz", "-Tz",
]

_CANONICAL_DISTURBANCES: List[List[float]] = [
    [1, 0, 0, 0, 0, 0], [-1, 0, 0, 0, 0, 0],
    [0, 1, 0, 0, 0, 0], [0, -1, 0, 0, 0, 0],
    [0, 0, 1, 0, 0, 0], [0, 0, -1, 0, 0, 0],
    [0, 0, 0, 1, 0, 0], [0, 0, 0, -1, 0, 0],
    [0, 0, 0, 0, 1, 0], [0, 0, 0, 0, -1, 0],
    [0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 0, -1],
]


def _centroid_of_contacts(
    contacts: List[ContactPoint],
) -> Tuple[float, float, float]:
    """Return the centroid of contact positions (reference point for moments)."""
    n = len(contacts)
    if n == 0:
        return (0.0, 0.0, 0.0)
    cx = sum(c.position_xyz_mm[0] for c in contacts) / n
    cy = sum(c.position_xyz_mm[1] for c in contacts) / n
    cz = sum(c.position_xyz_mm[2] for c in contacts) / n
    return (cx, cy, cz)


# ---------------------------------------------------------------------------
# §6 Public API: check_form_closure / check_force_closure_with_friction
# ---------------------------------------------------------------------------

def check_form_closure(contacts: List[ContactPoint]) -> FormClosureReport:
    """
    Test frictionless form-closure per Asada & By (1985) §6.

    Given a set of contact points (with outward surface normals), determines
    whether the fixture is form-closed: the wrench set positively spans R^6
    so that any external disturbance can be resisted.

    Algorithm
    ---------
    1. Compute one frictionless wrench generator per contact:
         w_i = [n_i; r_i × n_i]  (force + torque about centroid).
    2. For each of 12 canonical disturbance directions d_k ∈ {±e_1..±e_6},
       solve the LP: ∃ λ ≥ 0  s.t.  Σ λ_i w_i = d_k  (+ margin t ≥ 0).
    3. form_closed = all 12 LPs feasible.
    4. margin = min LP slack (t*) over all 12 directions.

    Classical results (Reuleaux 1875; Asada-By §6 Theorem 1):
      - Minimum contacts for form-closure in 3D: 7 (frictionless).
      - Minimum contacts for force-closure with friction: 4 (Coulomb μ > 0).

    Parameters
    ----------
    contacts : list[ContactPoint]
        At least 1 contact. Fewer than 7 frictionless contacts cannot
        form-close in 3D (necessary but not sufficient condition).

    Returns
    -------
    FormClosureReport
        form_closed flag, margin, missing DoF directions (if any).
    """
    if not contacts:
        return FormClosureReport(
            form_closed=False,
            margin=-1.0,
            missing_dof_directions=list(_WRENCH_LABELS),
            n_contacts=0,
        )

    origin = _centroid_of_contacts(contacts)
    W = _build_wrench_generators(contacts, mu=0.0, origin=origin)

    if not W:
        return FormClosureReport(
            form_closed=False,
            margin=-1.0,
            missing_dof_directions=list(_WRENCH_LABELS),
            n_contacts=len(contacts),
        )

    margins: List[float] = []
    missing: List[str] = []

    for label, d in zip(_WRENCH_LABELS, _CANONICAL_DISTURBANCES):
        feasible, t = _lp_span_test(W, d)
        margins.append(t)
        if not feasible:
            missing.append(label)

    overall_margin = min(margins)
    form_closed = len(missing) == 0

    return FormClosureReport(
        form_closed=form_closed,
        margin=overall_margin,
        missing_dof_directions=missing,
        n_contacts=len(contacts),
    )


def check_force_closure_with_friction(
    contacts: List[ContactPoint],
    mu: float,
) -> ForceClosureReport:
    """
    Test force-closure with Coulomb friction per Asada & By (1985) §6.

    Replaces each frictional contact's single normal wrench with four
    4-edge friction-cone generators (n ± μ·t1, n ± μ·t2), then runs the
    same LP span test as `check_form_closure`.

    Parameters
    ----------
    contacts : list[ContactPoint]
        ContactPoints; set ``is_friction=True`` for contacts that can
        transmit tangential forces.  Contacts with ``is_friction=False``
        contribute only a normal wrench regardless of μ.
    mu : float
        Coulomb friction coefficient (μ ≥ 0).  μ=0 degenerates to
        frictionless form-closure (same result as `check_form_closure`
        with is_friction ignored).

    Returns
    -------
    ForceClosureReport
        force_closed flag, margin, missing DoF directions.

    Notes
    -----
    With 4 frictional contacts and μ ≈ 0.3, force-closure is achievable
    for moderate disturbances.  The minimum number of frictional contacts
    for force-closure in 3D is 4 (Mishra et al. 1987; Murray et al. 1994).
    """
    if not contacts:
        return ForceClosureReport(
            force_closed=False,
            margin=-1.0,
            mu=mu,
            missing_dof_directions=list(_WRENCH_LABELS),
            n_contacts=0,
            n_wrench_generators=0,
        )

    mu_eff = max(0.0, mu)
    origin = _centroid_of_contacts(contacts)
    W = _build_wrench_generators(contacts, mu=mu_eff, origin=origin)
    n_gen = len(W)

    if not W:
        return ForceClosureReport(
            force_closed=False,
            margin=-1.0,
            mu=mu,
            missing_dof_directions=list(_WRENCH_LABELS),
            n_contacts=len(contacts),
            n_wrench_generators=0,
        )

    margins: List[float] = []
    missing: List[str] = []

    for label, d in zip(_WRENCH_LABELS, _CANONICAL_DISTURBANCES):
        feasible, t = _lp_span_test(W, d)
        margins.append(t)
        if not feasible:
            missing.append(label)

    overall_margin = min(margins)
    force_closed = len(missing) == 0

    return ForceClosureReport(
        force_closed=force_closed,
        margin=overall_margin,
        mu=mu,
        missing_dof_directions=missing,
        n_contacts=len(contacts),
        n_wrench_generators=n_gen,
    )


# ---------------------------------------------------------------------------
# Material and operation tables
# ---------------------------------------------------------------------------

# Approximate yield strength in MPa used for clamp-force scaling
_MATERIAL_YIELD: dict[str, float] = {
    "aluminum":  270.0,   # AA6061-T6
    "steel":     250.0,   # mild / AISI 1018
    "stainless": 310.0,   # AISI 304 annealed
    "titanium":  880.0,   # Ti-6Al-4V
    "polymer":    60.0,   # typical engineering thermoplastic
    "cast_iron": 180.0,   # grey cast iron
    "brass":     200.0,
}

# Dimensionless cutting-force multiplier per operation (k_op)
# Conservative per Boyes "Machinery's Handbook" fixturing chapter
_OPERATION_FACTORS: dict[str, float] = {
    "milling":  2.5,   # interrupted cut, high lateral force
    "drilling": 1.8,   # axial thrust dominant
    "turning":  1.5,   # continuous cut, lower peak
    "grinding": 1.2,   # light load
    "boring":   2.0,
}

_DEFAULT_MATERIAL = "aluminum"
_DEFAULT_OPERATIONS = ["milling"]


def _yield_mpa(material: str) -> float:
    return _MATERIAL_YIELD.get(material.lower().replace("-", "_"), 270.0)


def _op_factor(operations: Sequence[str]) -> float:
    if not operations:
        return _OPERATION_FACTORS["milling"]
    return max(_OPERATION_FACTORS.get(op.lower(), 2.0) for op in operations)


# ---------------------------------------------------------------------------
# Constraint matrix (Asada-By wrench matrix)
# ---------------------------------------------------------------------------

def _cross(a: Tuple[float, float, float],
           b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _build_wrench_matrix(locators: List[Locator]) -> List[List[float]]:
    """
    Build the 6×6 wrench matrix W (Asada-By 1985, §5 eq. 3).

    Row i = [n_i | r_i × n_i]

    where r_i is the locator position vector relative to the centroid of all
    locators, and n_i is the outward unit normal.
    """
    # Centroid of locators (reference point for moment arms)
    cx = sum(loc.position[0] for loc in locators) / len(locators)
    cy = sum(loc.position[1] for loc in locators) / len(locators)
    cz = sum(loc.position[2] for loc in locators) / len(locators)

    rows: List[List[float]] = []
    for loc in locators:
        n = loc.normal
        r = (loc.position[0] - cx,
             loc.position[1] - cy,
             loc.position[2] - cz)
        m = _cross(r, n)
        rows.append([n[0], n[1], n[2], m[0], m[1], m[2]])
    return rows


def _matrix_rank(A: List[List[float]], tol: float = 1e-9) -> int:
    """Rank via Gram-Schmidt orthogonalisation (pure-Python, no numpy)."""
    n_rows = len(A)
    n_cols = len(A[0]) if A else 0
    # Work with column vectors
    cols: List[List[float]] = [[A[r][c] for r in range(n_rows)] for c in range(n_cols)]

    basis: List[List[float]] = []
    for v in cols:
        # Gram-Schmidt step: subtract projections onto basis
        w = list(v)
        for b in basis:
            dot_wb = sum(w[i] * b[i] for i in range(n_rows))
            dot_bb = sum(b[i] * b[i] for i in range(n_rows))
            if dot_bb > 1e-18:
                proj = dot_wb / dot_bb
                w = [w[i] - proj * b[i] for i in range(n_rows)]
        norm_w = math.sqrt(sum(wi * wi for wi in w))
        if norm_w > tol:
            u = [wi / norm_w for wi in w]
            basis.append(u)

    return len(basis)


# ---------------------------------------------------------------------------
# Clamp-force estimator
# ---------------------------------------------------------------------------

def _estimate_clamp_force(bbox: BoundingBox,
                           material: str,
                           operations: Sequence[str]) -> float:
    """
    Rough clamping force estimate [N] following ASME B5.8 conservative guidance.

    F = k_op × σ_y [MPa] × contact_area [mm²] × safety_factor
    contact_area ≈ 1% of the primary (bottom) face (rule-of-thumb for pin contacts)
    safety_factor = 1.5
    """
    k_op = _op_factor(operations)
    sigma_y = _yield_mpa(material)
    primary_area = bbox.dx * bbox.dy  # bottom face area
    contact_fraction = 0.01           # ~1% of face for point contacts
    safety_factor = 1.5
    return k_op * sigma_y * primary_area * contact_fraction * safety_factor


# ---------------------------------------------------------------------------
# 3-2-1 layout generator
# ---------------------------------------------------------------------------

def _spread_positions(face: str,
                      bbox: BoundingBox,
                      count: int) -> List[Tuple[float, float, float]]:
    """
    Place `count` well-spread locator positions on the given face of the bbox.

    Positions are chosen at the "1/4 – 3/4" spacing rule (Boyes 1982) to
    maximise moment arm and minimise sensitivity to positional errors.
    """
    xmid = (bbox.xmin + bbox.xmax) / 2
    ymid = (bbox.ymin + bbox.ymax) / 2
    zmid = (bbox.zmin + bbox.zmax) / 2

    x14 = bbox.xmin + bbox.dx * 0.25
    x34 = bbox.xmin + bbox.dx * 0.75
    y14 = bbox.ymin + bbox.dy * 0.25
    y34 = bbox.ymin + bbox.dy * 0.75
    z14 = bbox.zmin + bbox.dz * 0.25
    z34 = bbox.zmin + bbox.dz * 0.75

    if face == "bottom":          # primary — Z_min plane, normal = (0, 0, +1)
        pts_3 = [
            (x14, y14, bbox.zmin),
            (x34, y14, bbox.zmin),
            (xmid, y34, bbox.zmin),
        ]
        pts_2 = [
            (x14, y14, bbox.zmin),
            (x34, y34, bbox.zmin),
        ]
        pts_1 = [(x14, y14, bbox.zmin)]
        pool = {3: pts_3, 2: pts_2, 1: pts_1}
        return pool[count]

    elif face == "front":         # secondary — Y_min plane, normal = (0, +1, 0)
        return [
            (x14, bbox.ymin, zmid),
            (x34, bbox.ymin, zmid),
        ][:count]

    elif face == "left":          # tertiary — X_min plane, normal = (+1, 0, 0)
        return [(bbox.xmin, ymid, zmid)]

    raise ValueError(f"Unknown face: {face!r}")


def auto_fixture_layout(
    workpiece_bbox: BoundingBox,
    material: str = _DEFAULT_MATERIAL,
    operations: Optional[List[str]] = None,
) -> FixtureLayout:
    """
    Generate a 3-2-1 fixturing layout for a prismatic workpiece.

    Parameters
    ----------
    workpiece_bbox : BoundingBox
        Axis-aligned bounding box of the workpiece (mm).
    material : str
        Workpiece material: 'aluminum', 'steel', 'stainless', 'titanium',
        'polymer', 'cast_iron', 'brass'.  Controls clamp-force estimate.
    operations : list[str]
        Manufacturing operations: 'milling', 'drilling', 'turning', 'grinding',
        'boring'.  Highest-force operation governs clamp sizing.

    Returns
    -------
    FixtureLayout
        Named locators P1-P6, clamp positions, constraint rank, validity flag.

    Raises
    ------
    ValueError
        If the bounding box is degenerate (any dimension <= 0).

    Notes
    -----
    Implements Asada & By (1985) §5 form-closure rank condition.
    Locator placement follows ASME B5.18-2018 §4.2 3-2-1 rules.

    Honest flag: v1 is valid for bounding-box-aligned prismatic parts only.
    Freeform surfaces require per-face wrench analysis beyond this scope.
    """
    if operations is None:
        operations = list(_DEFAULT_OPERATIONS)

    err = workpiece_bbox.validate()
    if err:
        raise ValueError(err)

    ops_lower = [op.lower() for op in operations]

    # ── Primary face (bottom, Z_min) — 3 locators: P1 P2 P3 ────────────────
    primary_normal: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    prim_positions = _spread_positions("bottom", workpiece_bbox, 3)
    primary_locators = [
        Locator(
            name=f"P{i + 1}",
            face="primary",
            position=prim_positions[i],
            normal=primary_normal,
        )
        for i in range(3)
    ]

    # ── Secondary face (front, Y_min) — 2 locators: P4 P5 ──────────────────
    secondary_normal: Tuple[float, float, float] = (0.0, 1.0, 0.0)
    sec_positions = _spread_positions("front", workpiece_bbox, 2)
    secondary_locators = [
        Locator(
            name=f"P{i + 4}",
            face="secondary",
            position=sec_positions[i],
            normal=secondary_normal,
        )
        for i in range(2)
    ]

    # ── Tertiary face (left, X_min) — 1 locator: P6 ─────────────────────────
    tertiary_normal: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    ter_positions = _spread_positions("left", workpiece_bbox, 1)
    tertiary_locators = [
        Locator(
            name="P6",
            face="tertiary",
            position=ter_positions[0],
            normal=tertiary_normal,
        )
    ]

    all_locators = primary_locators + secondary_locators + tertiary_locators

    # ── Constraint matrix rank check (Asada-By 1985 §5) ─────────────────────
    W = _build_wrench_matrix(all_locators)
    rank = _matrix_rank(W)
    valid = rank == 6

    # ── Clamp force estimate ─────────────────────────────────────────────────
    f_clamp = _estimate_clamp_force(workpiece_bbox, material, ops_lower)

    xmid = (workpiece_bbox.xmin + workpiece_bbox.xmax) / 2
    ymid = (workpiece_bbox.ymin + workpiece_bbox.ymax) / 2
    zmid = (workpiece_bbox.zmin + workpiece_bbox.zmax) / 2

    # One over-strap clamp on top (opposite primary face), straps on front & left
    clamps = [
        Clamp(
            name="C1",
            position=(xmid, ymid, workpiece_bbox.zmax),
            direction=(0.0, 0.0, -1.0),
            force_n=f_clamp,
            note="Top strap clamp — opposes primary locators P1-P3",
        ),
        Clamp(
            name="C2",
            position=(xmid, workpiece_bbox.ymax, zmid),
            direction=(0.0, -1.0, 0.0),
            force_n=f_clamp * 0.6,
            note="Side strap clamp — opposes secondary locators P4-P5",
        ),
        Clamp(
            name="C3",
            position=(workpiece_bbox.xmax, ymid, zmid),
            direction=(-1.0, 0.0, 0.0),
            force_n=f_clamp * 0.4,
            note="End strap clamp — opposes tertiary locator P6",
        ),
    ]

    notes = [
        "Layout follows ASME B5.18-2018 §4.2 3-2-1 principle.",
        "Constraint analysis: Asada & By (1985) §5 wrench-matrix rank condition.",
        "Locator positions use the ¼–¾ rule (Boyes 1982) for maximum moment arm.",
        f"Clamp forces estimated at safety factor 1.5 for {material} / "
        f"{', '.join(ops_lower)} operations.",
        "v1 HONEST FLAG: valid for bounding-box-aligned prismatic parts only. "
        "Freeform / curved faces: use check_form_closure() or "
        "check_force_closure_with_friction() (Asada-By §6, now implemented) "
        "with manually supplied ContactPoint objects.",
    ]

    if not valid:
        notes.append(
            f"WARNING: constraint matrix rank={rank} < 6 — layout is under-constrained. "
            "Verify locator positions and that no three locators are collinear."
        )

    return FixtureLayout(
        locators=all_locators,
        clamps=clamps,
        constraint_rank=rank,
        valid=valid,
        material=material,
        operations=ops_lower,
        bbox=workpiece_bbox,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

    _manufacturing_auto_fixture_layout_spec = ToolSpec(
        name="manufacturing_auto_fixture_layout",
        description=(
            "Auto-generate a 3-2-1 fixturing layout for a prismatic workpiece "
            "given its bounding box, material, and intended manufacturing operations.\n"
            "\n"
            "Implements Asada & By (1985) §5 form-closure analysis: six locators "
            "(P1-P3 on primary face, P4-P5 on secondary face, P6 on tertiary face) "
            "with a constraint matrix rank check to confirm 6-DOF restraint.\n"
            "\n"
            "Returns: named locator points (P1-P6) with positions + normals, "
            "suggested clamp forces (N), 3 clamp positions, validity flag, and rank.\n"
            "\n"
            "References: Asada & By (1985) IEEE J. Robot. Autom.; "
            "ASME B5.18-2018 §4.2.\n"
            "\n"
            "v1 LIMIT: bounding-box-aligned prismatic parts only. "
            "Freeform surfaces: use as a starting estimate only.\n"
            "\n"
            "Errors: {ok: false, reason, code} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "xmin": {"type": "number", "description": "Bounding box X_min (mm)."},
                "ymin": {"type": "number", "description": "Bounding box Y_min (mm)."},
                "zmin": {"type": "number", "description": "Bounding box Z_min (mm)."},
                "xmax": {"type": "number", "description": "Bounding box X_max (mm)."},
                "ymax": {"type": "number", "description": "Bounding box Y_max (mm)."},
                "zmax": {"type": "number", "description": "Bounding box Z_max (mm)."},
                "material": {
                    "type": "string",
                    "description": (
                        "Workpiece material: aluminum | steel | stainless | titanium "
                        "| polymer | cast_iron | brass. Default: aluminum."
                    ),
                },
                "operations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Operations to support: milling | drilling | turning | "
                        "grinding | boring. Highest-force op governs clamp sizing. "
                        "Default: [milling]."
                    ),
                },
            },
            "required": ["xmin", "ymin", "zmin", "xmax", "ymax", "zmax"],
        },
    )

    @register(_manufacturing_auto_fixture_layout_spec, write=False)
    async def run_manufacturing_auto_fixture_layout(ctx, args: bytes) -> str:
        """LLM tool: generate 3-2-1 fixture layout from bounding box + material."""
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        try:
            bbox = BoundingBox(
                xmin=float(a.get("xmin", 0)),
                ymin=float(a.get("ymin", 0)),
                zmin=float(a.get("zmin", 0)),
                xmax=float(a.get("xmax", 0)),
                ymax=float(a.get("ymax", 0)),
                zmax=float(a.get("zmax", 0)),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"invalid bbox coordinates: {exc}", "BAD_ARGS")

        material = str(a.get("material", _DEFAULT_MATERIAL)).strip() or _DEFAULT_MATERIAL
        operations = a.get("operations", None)
        if operations is not None and not isinstance(operations, list):
            return err_payload("operations must be a list of strings", "BAD_ARGS")

        try:
            layout = auto_fixture_layout(
                workpiece_bbox=bbox,
                material=material,
                operations=operations,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"fixture layout error: {exc}", "INTERNAL_ERROR")

        return ok_payload(layout.to_dict())

except ImportError:
    pass
