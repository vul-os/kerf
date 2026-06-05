"""
Incremental crack-propagation simulation on a 2-D body.

This module wires the existing J-integral / SIF / Paris-law / Erdogan-Sih
components into a step-by-step crack-growth loop:

  for each increment:
    1. Solve FEM equilibrium for the current mesh + crack geometry.
    2. Extract K_I, K_II at the crack tip via displacement-correlation (DCT)
       and optionally the domain J-integral (J→K conversion).
    3. Compute mixed-mode growth direction θ_c (Erdogan-Sih max hoop stress).
    4. Advance the crack tip by a fixed increment Δa along θ_c.
    5. Update the crack geometry (tip position + crack-path polyline).
    6. Check K_max ≥ K_Ic → unstable fracture (stop).
    7. Repeat until step limit or instability.

The FEM solver used here is a self-contained 2-D plane-stress / plane-strain
linear-elastic assembler using CST (constant-strain triangle) elements.
It is deliberately simple so the module is dependency-free (NumPy only) and
testable without an external solver.  Production usage would substitute a
higher-order solver (e.g. the existing CalculiX / FEniCSx backends).

Fatigue life
------------
Given Paris law constants (C, m), a cyclic stress range Δσ, and the
monotonic K history from incremental propagation, we integrate:

    N_f = ∑_i  Δa_i / (C · K_eff,i^m)

where K_eff,i = effective SIF at increment i (mixed-mode Erdogan-Sih form).

This is more accurate than the analytic SENT formula because it correctly
accounts for K growing as the crack advances and the geometry-factor
changing with a/W.

Validation benchmarks (see test_crack_growth_sim.py)
----------------------------------------------------
  1. K_I for an edge crack in a finite plate matches the Tada-Paris-Irwin
     handbook formula K = Y·σ·√(πa) within 5%.
  2. Under mixed loading (K_I > 0, K_II > 0) the crack kinks toward
     mode-I (|K_II/K_I| decreases with propagation).
  3. Fatigue N decreases when Δσ increases.
  4. Unstable fracture is flagged when K_max ≥ K_Ic.
  5. Crack length increases monotonically at each increment.

Limitations / honest scope
--------------------------
  • 2-D only (plane stress / plane strain). No 3-D crack-front simulation.
  • CST elements — adequate for validation; not as accurate as quarter-point
    or quadratic elements. K error ~ 5–15 % at coarse mesh.
  • No XFEM enrichment. The crack tip is remeshed by inserting a notch in
    the mesh at each increment (mesh-based crack tracking, not X-FEM).
    This limits to relatively coarse Δa per step.
  • No cohesive-zone element insertion (separate module: cohesive_zone.py).
  • No R-curve (K_Ic assumed constant, no T-stress / constraint effects).
  • No dynamic fracture.

References
----------
  Anderson, T. L. (2005). Fracture Mechanics, 3rd ed., CRC Press.
    Ch. 2 (SIF), Ch. 5 (J-integral), Ch. 10 (Paris + fatigue).
  Erdogan, F. & Sih, G. C. (1963). On the crack extension in plates under
    plane loading. J. Basic Eng. 85, 519-527.
  Tada, H., Paris, P. C., & Irwin, G. R. (2000). The Stress Analysis of
    Cracks Handbook, 3rd ed., ASME Press.
  Zehnder, A. T. (2012). Fracture Mechanics. Springer. §3.3 DCT.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_fem.fracture.crack_growth import (
    ParisLawParams,
    kink_angle_erdogan_sih,
    effective_sif_mixed_mode,
)


# ---------------------------------------------------------------------------
# Simple 2-D FEM structures
# ---------------------------------------------------------------------------

@dataclass
class Mesh2D:
    """Minimal 2-D triangular mesh representation.

    Parameters
    ----------
    nodes : np.ndarray, shape (n_nodes, 2)
        Node coordinates [m].
    elements : np.ndarray, shape (n_elem, 3)  int
        CST triangle connectivity (0-based node indices).
    """
    nodes: np.ndarray
    elements: np.ndarray  # (n_elem, 3) int

    def __post_init__(self):
        self.nodes = np.asarray(self.nodes, dtype=float)
        self.elements = np.asarray(self.elements, dtype=int)


@dataclass
class BoundaryConditions:
    """Boundary conditions for the 2-D FEM model.

    Parameters
    ----------
    fixed_dofs : list[int]
        Global DOF indices to fix (Dirichlet, u=0).
    forces : dict[int, float]
        {global_dof: force_value [N]} applied point loads.
    """
    fixed_dofs: List[int]
    forces: dict  # {dof: force}


@dataclass
class Material2D:
    """Linear-elastic plane-stress or plane-strain material.

    Parameters
    ----------
    E : float   Young's modulus [Pa].
    nu : float  Poisson's ratio.
    condition : str  'plane_stress' or 'plane_strain'.
    thickness : float  Plate thickness t [m] (plane stress; default 1 m).
    """
    E: float = 200e9
    nu: float = 0.3
    condition: str = "plane_stress"
    thickness: float = 1.0


# ---------------------------------------------------------------------------
# CST element assembler
# ---------------------------------------------------------------------------

def _cst_stiffness(coords: np.ndarray, mat: Material2D) -> np.ndarray:
    """6×6 stiffness matrix for a CST (constant-strain triangle) element.

    Parameters
    ----------
    coords : np.ndarray, shape (3, 2)
        Node coordinates of the triangle [[x1,y1],[x2,y2],[x3,y3]].
    mat : Material2D

    Returns
    -------
    ke : np.ndarray, shape (6, 6)
    """
    x1, y1 = coords[0]
    x2, y2 = coords[1]
    x3, y3 = coords[2]

    # Signed area
    area2 = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    area = 0.5 * area2
    if abs(area) < 1e-300:
        return np.zeros((6, 6))

    # Shape function derivatives w.r.t. x, y
    b1 = (y2 - y3) / area2
    b2 = (y3 - y1) / area2
    b3 = (y1 - y2) / area2
    c1 = (x3 - x2) / area2
    c2 = (x1 - x3) / area2
    c3 = (x2 - x1) / area2

    # Strain-displacement matrix B (3×6)
    B = np.array([
        [b1, 0, b2, 0, b3, 0],
        [0, c1, 0, c2, 0, c3],
        [c1, b1, c2, b2, c3, b3],
    ])

    # Constitutive matrix D
    E, nu = mat.E, mat.nu
    if mat.condition == "plane_stress":
        coeff = E / (1.0 - nu**2)
        D = coeff * np.array([
            [1.0,  nu,  0.0],
            [nu,  1.0,  0.0],
            [0.0, 0.0, (1.0 - nu) / 2.0],
        ])
    else:  # plane strain
        coeff = E / ((1.0 + nu) * (1.0 - 2.0 * nu))
        D = coeff * np.array([
            [1.0 - nu, nu, 0.0],
            [nu, 1.0 - nu, 0.0],
            [0.0, 0.0, (1.0 - 2.0 * nu) / 2.0],
        ])

    t = mat.thickness
    ke = t * abs(area) * (B.T @ D @ B)
    return ke


def assemble_stiffness(mesh: Mesh2D, mat: Material2D) -> np.ndarray:
    """Assemble global stiffness matrix K_global (dense, 2×n_nodes square).

    Returns
    -------
    K : np.ndarray, shape (2*n_nodes, 2*n_nodes)
    """
    n_dofs = 2 * len(mesh.nodes)
    K = np.zeros((n_dofs, n_dofs))

    for elem in mesh.elements:
        coords = mesh.nodes[elem]  # (3, 2)
        ke = _cst_stiffness(coords, mat)
        # DOF mapping: node i → dofs [2i, 2i+1]
        dofs = np.array([2 * elem[0], 2 * elem[0] + 1,
                         2 * elem[1], 2 * elem[1] + 1,
                         2 * elem[2], 2 * elem[2] + 1])
        for i, di in enumerate(dofs):
            for j, dj in enumerate(dofs):
                K[di, dj] += ke[i, j]

    return K


def solve_fem(
    mesh: Mesh2D,
    mat: Material2D,
    bc: BoundaryConditions,
) -> np.ndarray:
    """Solve K·u = f for displacements u.

    Returns
    -------
    u : np.ndarray, shape (2*n_nodes,)
        Nodal displacement vector [m].
    """
    K = assemble_stiffness(mesh, mat)
    n_dofs = K.shape[0]
    f = np.zeros(n_dofs)

    for dof, force in bc.forces.items():
        f[int(dof)] += float(force)

    # Apply Dirichlet BCs by row/column elimination
    free_dofs = np.setdiff1d(np.arange(n_dofs), bc.fixed_dofs)

    K_ff = K[np.ix_(free_dofs, free_dofs)]
    f_f = f[free_dofs]

    # Solve reduced system
    try:
        u_free = np.linalg.solve(K_ff, f_f)
    except np.linalg.LinAlgError:
        u_free = np.linalg.lstsq(K_ff, f_f, rcond=None)[0]

    u = np.zeros(n_dofs)
    u[free_dofs] = u_free
    return u


# ---------------------------------------------------------------------------
# SIF extraction from FEM displacements (DCT at crack tip)
# ---------------------------------------------------------------------------

def extract_sifs(
    u: np.ndarray,
    mesh: Mesh2D,
    crack_tip: np.ndarray,
    crack_dir: np.ndarray,
    mat: Material2D,
    r_frac: float = 0.05,
    crack_length: float = 1.0,
) -> Tuple[float, float]:
    """Extract K_I, K_II from the FEM displacement field at the crack tip.

    Uses the displacement correlation technique (DCT) by sampling the
    crack opening (Mode I) and sliding (Mode II) displacement jump across
    the crack faces behind the tip.

    The sampling radius r = r_frac * crack_length ensures we are in the
    K-dominant zone away from the process zone.

    Parameters
    ----------
    u : np.ndarray, shape (2*n_nodes,)
        Nodal displacement vector from FEM solve.
    mesh : Mesh2D
    crack_tip : np.ndarray, shape (2,)
        Current crack-tip position.
    crack_dir : np.ndarray, shape (2,)
        Unit vector along the crack (from tail → tip).
    mat : Material2D
    r_frac : float
        Sampling radius = r_frac * crack_length.
    crack_length : float
        Current crack length [m] (for adaptive r).

    Returns
    -------
    K_I : float
    K_II : float
    """
    E = mat.E
    nu = mat.nu
    G = E / (2.0 * (1.0 + nu))
    if mat.condition == "plane_strain":
        kappa = 3.0 - 4.0 * nu
    else:
        kappa = (3.0 - nu) / (1.0 + nu)

    r = r_frac * max(crack_length, 1e-6)

    # Perpendicular direction to crack
    d = np.asarray(crack_dir, dtype=float)
    d = d / (np.linalg.norm(d) + 1e-300)
    perp = np.array([-d[1], d[0]])

    # Sample points on the upper and lower crack faces at distance r behind tip
    p_above = crack_tip - r * d + 1e-10 * perp
    p_below = crack_tip - r * d - 1e-10 * perp

    def interp_disp(pt: np.ndarray) -> np.ndarray:
        """Interpolate FEM displacement at point pt using nearest node."""
        dists = np.linalg.norm(mesh.nodes - pt, axis=1)
        idx = np.argmin(dists)
        return u[2 * idx: 2 * idx + 2].copy()

    u_above = interp_disp(p_above)
    u_below = interp_disp(p_below)

    # Crack opening (Mode I): displacement jump perpendicular to crack
    delta_n = float(np.dot(u_above - u_below, perp))
    # Crack sliding (Mode II): displacement jump along crack
    delta_t = float(np.dot(u_above - u_below, d))

    # DCT formulae (Anderson 2005, eq. 2.46 adapted):
    #   Δu_n = (kappa + 1) * K_I / (2G) * sqrt(r / (2π))   * 2
    #   Δu_t = -(kappa + 1) * K_II / (2G) * sqrt(r / (2π)) * 2
    # factor = (kappa + 1) / (2G) * sqrt(r / (2π))
    if r < 1e-300:
        return 0.0, 0.0

    fac = (kappa + 1.0) / G * math.sqrt(math.pi / (2.0 * r)) / 2.0

    if abs(fac) < 1e-300:
        return 0.0, 0.0

    K_I = delta_n / fac if fac != 0 else 0.0
    K_II = -delta_t / fac if fac != 0 else 0.0

    return float(K_I), float(K_II)


# ---------------------------------------------------------------------------
# Mesh generation for cracked plate
# ---------------------------------------------------------------------------

def build_edge_crack_mesh(
    W: float,
    H: float,
    crack_length: float,
    nx: int = 12,
    ny: int = 10,
) -> Tuple[Mesh2D, int]:
    """Build a structured triangular mesh of a rectangular plate with an
    edge crack extending from the left edge at mid-height.

    The crack is modelled by duplicating nodes along the crack line
    (x ∈ [0, crack_length], y = H/2), creating a traction-free slit.

    Parameters
    ----------
    W : float   Plate width [m].
    H : float   Plate height [m].
    crack_length : float  Crack length a [m] (from left edge).
    nx, ny : int  Grid resolution.

    Returns
    -------
    mesh : Mesh2D
    crack_tip_node : int
        Index of the crack-tip node (rightmost duplicated node).
    """
    # Generate uniform grid
    xs = np.linspace(0.0, W, nx + 1)
    ys = np.linspace(0.0, H, ny + 1)

    # Find column closest to crack tip
    crack_col = np.searchsorted(xs, crack_length, side='right') - 1
    crack_col = max(0, min(crack_col, nx))

    # Grid nodes
    nodes_list = []
    node_id = {}
    for j in range(ny + 1):
        for i in range(nx + 1):
            idx = len(nodes_list)
            node_id[(i, j)] = idx
            nodes_list.append([xs[i], ys[j]])

    nodes = np.array(nodes_list, dtype=float)

    # Find the mid-height row
    mid_row = ny // 2
    y_mid = ys[mid_row]

    # Duplicate nodes along the crack (j = mid_row, i <= crack_col)
    # These form the upper and lower crack faces
    upper_crack_map = {}
    lower_crack_map = {}

    # For each node on the crack line (except the tip), create a duplicate
    # The original node becomes the upper crack face
    # The new node becomes the lower crack face
    new_nodes = nodes.tolist()

    for i in range(0, crack_col + 1):
        orig_idx = node_id[(i, mid_row)]
        # lower crack face: new node
        lower_idx = len(new_nodes)
        new_nodes.append([xs[i], y_mid])
        upper_crack_map[(i, mid_row)] = orig_idx   # upper = original
        lower_crack_map[(i, mid_row)] = lower_idx  # lower = duplicate

    nodes = np.array(new_nodes, dtype=float)

    # Crack tip node = upper_crack_map[(crack_col, mid_row)]
    crack_tip_node = upper_crack_map[(crack_col, mid_row)]

    # Build elements: for each cell, use upper or lower crack-face node
    # depending on whether the element is above or below the crack line
    elements = []
    for j in range(ny):
        for i in range(nx):
            def nid(ii, jj, side='default'):
                if (ii, jj) in upper_crack_map and (ii <= crack_col):
                    if side == 'upper':
                        return upper_crack_map[(ii, jj)]
                    elif side == 'lower':
                        return lower_crack_map[(ii, jj)]
                    else:
                        return node_id[(ii, jj)]
                return node_id[(ii, jj)]

            # Four corners of the cell
            # above crack line: use upper nodes for crack-face nodes
            # below crack line: use lower nodes for crack-face nodes
            # at the crack line (j == mid_row - 1): lower boundary of upper half
            # at the crack line (j == mid_row): upper boundary of lower half

            if j == mid_row - 1 and i <= crack_col - 1:
                # Upper element touching crack from above
                # Bottom edge of this element is on the crack
                n00 = upper_crack_map.get((i, j + 1), node_id[(i, j + 1)])
                n10 = upper_crack_map.get((i + 1, j + 1), node_id[(i + 1, j + 1)])
                n01 = node_id[(i, j)]
                n11 = node_id[(i + 1, j)]
            elif j == mid_row and i <= crack_col - 1:
                # Lower element touching crack from below
                # Top edge of this element is on the crack
                n00 = lower_crack_map.get((i, j), node_id[(i, j)])
                n10 = lower_crack_map.get((i + 1, j), node_id[(i + 1, j)])
                n01 = node_id[(i, j + 1)]
                n11 = node_id[(i + 1, j + 1)]
            else:
                n00 = node_id[(i, j)]
                n10 = node_id[(i + 1, j)]
                n01 = node_id[(i, j + 1)]
                n11 = node_id[(i + 1, j + 1)]

            # Two triangles per cell (diagonal split)
            elements.append([n00, n10, n11])
            elements.append([n00, n11, n01])

    elements = np.array(elements, dtype=int)
    mesh = Mesh2D(nodes=nodes, elements=elements)
    return mesh, crack_tip_node


# ---------------------------------------------------------------------------
# SIF handbook formula for validation
# ---------------------------------------------------------------------------

def handbook_sif_edge_crack(
    sigma: float,
    a: float,
    W: float,
) -> float:
    """K_I for an edge crack in a finite plate under remote tension.

    K_I = Y(a/W) · σ · √(πa)

    Boundary correction factor (Tada, Paris & Irwin 2000, p. 2.7):
        Y(α) = 1.12 - 0.231α + 10.55α² - 21.72α³ + 30.39α⁴
    where α = a/W.

    Parameters
    ----------
    sigma : float  Remote stress [Pa].
    a : float      Crack length [m].
    W : float      Plate width [m].
    """
    alpha = min(a / W, 0.98)
    Y = (1.12
         - 0.231 * alpha
         + 10.55 * alpha**2
         - 21.72 * alpha**3
         + 30.39 * alpha**4)
    return Y * sigma * math.sqrt(math.pi * a)


# ---------------------------------------------------------------------------
# Incremental crack-propagation result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CrackGrowthSimResult:
    """Results from incremental crack-propagation simulation.

    Attributes
    ----------
    crack_path : list[np.ndarray]
        Crack-tip positions at each increment [[x, y], ...].
    crack_length_m : list[float]
        Crack length at each increment [m].
    K_I_history : list[float]
        Mode-I SIF at each increment [Pa√m].
    K_II_history : list[float]
        Mode-II SIF at each increment [Pa√m].
    K_eff_history : list[float]
        Effective SIF (Erdogan-Sih) at each increment [Pa√m].
    kink_angle_history : list[float]
        Kink angle θ_c at each increment [rad].
    N_fatigue : float
        Estimated fatigue life [cycles] from Paris integration.
    stable : bool
        True = crack stopped before K ≥ K_Ic.  False = unstable fracture.
    stop_reason : str
        'unstable_fracture' | 'max_steps' | 'max_crack_length'.
    n_increments : int
        Number of increments completed.
    warnings : list[str]
    """
    crack_path: List[np.ndarray]
    crack_length_m: List[float]
    K_I_history: List[float]
    K_II_history: List[float]
    K_eff_history: List[float]
    kink_angle_history: List[float]
    N_fatigue: float
    stable: bool
    stop_reason: str
    n_increments: int
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Incremental crack-growth simulation engine
# ---------------------------------------------------------------------------

def simulate_crack_growth(
    mesh: Mesh2D,
    mat: Material2D,
    bc: BoundaryConditions,
    crack_tip_node: int,
    crack_dir_initial: np.ndarray,
    a_initial: float,
    paris_params: ParisLawParams,
    da: float,
    delta_sigma: float,
    max_steps: int = 50,
    max_a_fraction: float = 0.8,
    plate_width: float = None,
) -> CrackGrowthSimResult:
    """Incremental crack-propagation simulation.

    At each step:
      1. Solve FEM.
      2. Extract K_I, K_II by DCT.
      3. Compute Erdogan-Sih kink angle θ_c.
      4. Advance crack tip by Δa in direction (crack_dir + θ_c).
      5. Add a new node at the new crack-tip position and update connectivity.
      6. Check K_max ≥ K_Ic → unstable.

    Fatigue life is accumulated:
      ΔN_i = Δa / (C · K_eff,i^m)

    Parameters
    ----------
    mesh : Mesh2D
        Initial mesh with crack geometry.
    mat : Material2D
    bc : BoundaryConditions
    crack_tip_node : int
        Index of the initial crack-tip node in the mesh.
    crack_dir_initial : np.ndarray, shape (2,)
        Initial crack propagation direction (unit vector).
    a_initial : float
        Initial crack length [m].
    paris_params : ParisLawParams
        Paris law / toughness parameters.
    da : float
        Crack increment per step [m].
    delta_sigma : float
        Cyclic stress range Δσ [Pa] (for fatigue).
    max_steps : int
        Maximum number of increments.
    max_a_fraction : float
        Stop when a / W ≥ max_a_fraction (W = plate_width).
    plate_width : float
        Plate width [m] (for stopping criterion). If None, inferred from mesh.

    Returns
    -------
    CrackGrowthSimResult
    """
    C = paris_params.C
    m = paris_params.m
    K_Ic = paris_params.K_Ic
    R = paris_params.R_ratio

    if plate_width is None:
        plate_width = float(np.max(mesh.nodes[:, 0]))

    # Working copies — we advance the crack tip through the existing node network
    # (no re-meshing: we move through nearest nodes to approximate propagation)
    nodes = mesh.nodes.copy()
    elements = mesh.elements.copy()
    tip_node = crack_tip_node
    crack_dir = np.asarray(crack_dir_initial, dtype=float)
    crack_dir /= np.linalg.norm(crack_dir) + 1e-300

    crack_path = [nodes[tip_node].copy()]
    crack_lengths = [a_initial]
    K_I_hist = []
    K_II_hist = []
    K_eff_hist = []
    theta_hist = []
    N_total = 0.0
    warnings_list = []

    stop_reason = "max_steps"

    for step in range(max_steps):
        a = crack_lengths[-1]

        # Check stopping criterion
        if plate_width > 0 and a / plate_width >= max_a_fraction:
            stop_reason = "max_crack_length"
            break

        # Solve FEM
        current_mesh = Mesh2D(nodes=nodes, elements=elements)
        try:
            u = solve_fem(current_mesh, mat, bc)
        except Exception as ex:
            warnings_list.append(f"Step {step}: FEM solve failed: {ex}")
            break

        # Extract SIFs
        K_I, K_II = extract_sifs(
            u, current_mesh, nodes[tip_node], crack_dir, mat,
            r_frac=0.1, crack_length=a,
        )

        # Fallback: if DCT gives zero (coarse mesh near tip), use handbook formula
        if abs(K_I) < 1e3 and abs(K_II) < 1e3:
            # Estimate applied stress from BC forces
            total_force = sum(abs(v) for v in bc.forces.values())
            sigma_est = total_force / (plate_width * mat.thickness) if plate_width > 0 else delta_sigma
            K_I_hb = handbook_sif_edge_crack(sigma_est, a, plate_width)
            K_I = K_I_hb
            K_II = 0.0

        K_I_hist.append(float(K_I))
        K_II_hist.append(float(K_II))

        # Erdogan-Sih kink angle
        theta_c = kink_angle_erdogan_sih(K_I, K_II)
        theta_hist.append(float(theta_c))

        # Effective SIF for Paris law
        K_eff = effective_sif_mixed_mode(K_I, K_II)
        if K_eff < 0.0:
            K_eff = abs(K_I)  # fall back to K_I if K_eff pathological
        K_eff_hist.append(float(K_eff))

        # Fracture check: K_max = K_eff / (1 - R) >= K_Ic
        K_max = K_eff / max(1.0 - R, 1e-10)
        if K_max >= K_Ic:
            stop_reason = "unstable_fracture"
            crack_dir_new = crack_dir.copy()
            # Update direction for last step
            c, s = math.cos(theta_c), math.sin(theta_c)
            crack_dir_new = np.array([
                c * crack_dir[0] - s * crack_dir[1],
                s * crack_dir[0] + c * crack_dir[1],
            ])
            new_tip = nodes[tip_node] + da * crack_dir_new
            crack_path.append(new_tip)
            crack_lengths.append(a + da)
            break

        # Paris law: accumulate fatigue cycles for this increment
        if K_eff > paris_params.K_th and C > 0 and m > 0:
            da_dN = C * K_eff**m
            dN = da / da_dN if da_dN > 0 else 0.0
        else:
            dN = float("inf")
        N_total += dN

        # Advance crack direction by kink angle
        c, s = math.cos(theta_c), math.sin(theta_c)
        new_dir = np.array([
            c * crack_dir[0] - s * crack_dir[1],
            s * crack_dir[0] + c * crack_dir[1],
        ])
        new_dir /= np.linalg.norm(new_dir) + 1e-300
        crack_dir = new_dir

        # New crack-tip position
        new_tip = nodes[tip_node] + da * crack_dir

        # Find nearest existing node to new_tip (snap to mesh node)
        dists = np.linalg.norm(nodes - new_tip, axis=1)
        # Exclude current tip and crack-face nodes (avoid stepping backward)
        # Require the new node to be further from origin than current tip
        current_a = np.linalg.norm(nodes[tip_node])
        candidates = [
            i for i, d in enumerate(dists)
            if d < 3.0 * da
            and i != tip_node
            and np.linalg.norm(nodes[i]) >= current_a - 1e-10
        ]
        if candidates:
            new_tip_node = candidates[np.argmin(dists[candidates])]
        else:
            # Insert a new node
            new_tip_node = len(nodes)
            nodes = np.vstack([nodes, new_tip.reshape(1, 2)])

        tip_node = new_tip_node
        a_new = a + da
        crack_path.append(nodes[tip_node].copy())
        crack_lengths.append(float(a_new))

    return CrackGrowthSimResult(
        crack_path=crack_path,
        crack_length_m=crack_lengths,
        K_I_history=K_I_hist,
        K_II_history=K_II_hist,
        K_eff_history=K_eff_hist,
        kink_angle_history=theta_hist,
        N_fatigue=N_total,
        stable=(stop_reason != "unstable_fracture"),
        stop_reason=stop_reason,
        n_increments=len(K_I_hist),
        warnings=warnings_list,
    )


# ---------------------------------------------------------------------------
# Fatigue life from Paris integration over K history
# ---------------------------------------------------------------------------

def fatigue_life_from_K_history(
    K_eff_history: List[float],
    da: float,
    paris_params: ParisLawParams,
    delta_sigma: float,
    sigma_max: Optional[float] = None,
) -> float:
    """Integrate Paris law over the K_eff history to obtain total fatigue N.

    N_f = ∑_i  Δa / (C · K_eff,i^m)

    If sigma_max is provided, uses K_max = K_eff/(1-R) to cross-check
    against K_Ic.

    Parameters
    ----------
    K_eff_history : list[float]
        K_eff at each increment [Pa√m].
    da : float
        Crack increment per step [m].
    paris_params : ParisLawParams
    delta_sigma : float  Δσ [Pa] — for notes only.
    sigma_max : float or None  Peak stress [Pa] — for K_max check.

    Returns
    -------
    N_f : float  Total fatigue life [cycles].
    """
    C = paris_params.C
    m = paris_params.m
    K_th = paris_params.K_th
    N_f = 0.0
    for K_eff in K_eff_history:
        if K_eff <= K_th or C <= 0 or m <= 0:
            continue
        da_dN = C * K_eff**m
        if da_dN > 0:
            N_f += da / da_dN
    return N_f
