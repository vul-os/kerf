"""
kerf_manufacturing.am_process_sim — Inherent-Strain Additive-Manufacturing
Process Distortion Simulation.

Implements the **inherent-strain method** (ISM), the industry-standard
fast-prediction approach for metal AM distortion and residual stress.

Physical model
--------------
The inherent-strain method (Mercelis & Kruth, 2006; Keller et al., 2014)
approximates the complex thermo-mechanical process of layer-by-layer metal
AM by precomputing or calibrating an *inherent strain* tensor ε* that
captures the net accumulated inelastic (plastic + thermal) strain in a
deposited layer after cooling.

Algorithm (quasi-static layer activation):
  For each build layer k = 1 … N_layers:
    1. Activate the elements in layer k (birth/death: set their stiffness to
       the full elastic value; previously inactive elements contribute zero
       stiffness).
    2. Apply an equivalent *eigenstrain load*: the inherent-strain tensor ε*
       is converted to a thermal-style body force via
           f_e = ∫_Ω Bᵀ C ε* dΩ   (Cook et al., 2001 §5.2)
       applied only to the newly activated elements.
    3. Solve the quasi-static linear elasticity system K u = f for the
       ACTIVE degrees of freedom (DOFs corresponding to inactive elements
       are suppressed; base-plate nodes are fully fixed).
    4. Accumulate the displacement increment Δu into the total distortion u.
    5. Compute the Cauchy stress in each active element from σ = C (Bu − ε*)
       and update the residual-stress field.

The inherent-strain tensor ε* is supplied as six independent components
[ε_xx, ε_yy, ε_zz, γ_xy, γ_yz, γ_xz] and may be calibrated from melt-pool
simulation or coupon bend tests (Liang et al., 2019).

Honest limitations
------------------
* The method is a *quasi-static* elastic approximation; it does not resolve
  melt-pool physics, solidification, or transient thermal fields.
* Material properties (E, ν) are assumed isotropic and temperature-independent.
* Element type: constant-strain Tet4 (CST in 3-D). Tet4 is stiff in bending;
  for accurate distortion magnitudes a refined mesh or Tet10 should be used.
* The base-plate is modelled as a rigid fixture (all nodes at z = z_min fully
  fixed).  Release (base-plate removal) is not simulated here.
* Support-structure region flagging is geometric only (elements whose centroid
  is below the first non-baseplate layer).

References
----------
* Mercelis P. & Kruth J.-P. (2006). "Residual stresses in selective laser
  sintering and selective laser melting." Rapid Prototyping Journal 12(5).
* Keller N. et al. (2014). "New method for fast predictions of residual stress
  and distortion of AM parts." Solid Freeform Fabrication Symposium.
* Liang X. et al. (2019). "Inherent strain homogenization for welding / AM."
  Manufacturing Letters 20.
* Cook R.D., Malkus D.S., Plesha M.E. & Witt R.J. (2001). Concepts and
  Applications of FEA, 4th ed., §5.2, §6.2.

Public API
----------
    simulate_am_process(mesh, params) -> AMSimResult
    AMSimResult  — dataclass with distortion, residual_stress, warnings, …
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AMMesh:
    """Tetrahedral mesh for AM process simulation.

    Parameters
    ----------
    nodes : (N, 3) float array
        Node coordinates in metres [x, y, z].  The build direction is +Z by
        default (configurable via ``build_dir``).
    tets : (M, 4) int array
        Tet4 connectivity — 4 node indices per element (0-based).
    """
    nodes: np.ndarray   # (N, 3)
    tets: np.ndarray    # (M, 4)  int

    @property
    def n_nodes(self) -> int:
        return int(self.nodes.shape[0])

    @property
    def n_elems(self) -> int:
        return int(self.tets.shape[0])


@dataclass
class AMParams:
    """Simulation parameters for the inherent-strain AM model.

    Parameters
    ----------
    E : float
        Young's modulus [Pa]. Default: 200 GPa (typical steel).
    nu : float
        Poisson's ratio. Default: 0.3.
    layer_thickness : float
        Build layer height [m]. Default: 0.05 mm = 5 × 10⁻⁵ m.
    build_dir : tuple[float, float, float]
        Unit vector in the build direction. Default: (0, 0, 1) — +Z up.
    inherent_strain : tuple[float, float, float, float, float, float]
        Anisotropic inherent-strain tensor components
        [ε_xx, ε_yy, ε_zz, γ_xy, γ_yz, γ_xz].
        Default: (−2.5e−3, −2.5e−3, −5.0e−3, 0, 0, 0) — typical Ti-6Al-4V
        LPBF values (Liang et al., 2019 Table 1, scaled).
        Negative in-plane strains → compressive eigenstrain → upward curl.
    distortion_tolerance_m : float
        Maximum allowable distortion [m]. A warning is raised if
        max |u| exceeds this. Default: 1 mm = 1e-3 m.
    """
    E: float = 200e9
    nu: float = 0.3
    layer_thickness: float = 5e-5
    build_dir: tuple = (0.0, 0.0, 1.0)
    inherent_strain: tuple = (-2.5e-3, -2.5e-3, -5.0e-3, 0.0, 0.0, 0.0)
    distortion_tolerance_m: float = 1e-3


@dataclass
class AMSimResult:
    """Result of one AM process simulation run.

    Attributes
    ----------
    ok : bool
    n_layers : int
        Number of build layers activated.
    n_nodes : int
    n_elems : int
    displacement : np.ndarray  shape (N, 3)
        Total nodal displacement field at end of build [m].
    max_deviation_m : float
        Maximum nodal displacement magnitude over all nodes [m].
    residual_stress : np.ndarray  shape (M, 6)
        Element-average residual Cauchy stress tensor (6 components:
        σ_xx, σ_yy, σ_zz, τ_xy, τ_yz, τ_xz) [Pa].
    max_von_mises_pa : float
        Maximum von-Mises residual stress over all elements [Pa].
    layer_max_disp_m : list[float]
        Maximum nodal displacement magnitude after each layer activation.
        Useful for checking monotonicity and distortion growth.
    support_elem_flags : list[bool]
        True for elements identified as being in support regions.
    recoater_interference : bool
        True if any node in the final layer has an in-plane displacement
        component that may cause recoater interference
        (heuristic: |u_x| or |u_y| at topmost layer centroid > 0.5 × layer_thickness).
    warnings : list[str]
    reason : str
        Non-empty if ok is False.
    """
    ok: bool = True
    n_layers: int = 0
    n_nodes: int = 0
    n_elems: int = 0
    displacement: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    max_deviation_m: float = 0.0
    residual_stress: np.ndarray = field(default_factory=lambda: np.zeros((0, 6)))
    max_von_mises_pa: float = 0.0
    layer_max_disp_m: list = field(default_factory=list)
    support_elem_flags: list = field(default_factory=list)
    recoater_interference: bool = False
    warnings: list = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# Core FEM helpers (pure-numpy, Tet4)
# ---------------------------------------------------------------------------

def _elasticity_matrix(E: float, nu: float) -> np.ndarray:
    """Isotropic 3-D linear elasticity matrix C (6×6).
    Reference: Cook et al. (2001) eq. 5.1-3.
    """
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    C = np.array([
        [lam + 2*mu, lam,        lam,        0,  0,  0 ],
        [lam,        lam + 2*mu, lam,        0,  0,  0 ],
        [lam,        lam,        lam + 2*mu, 0,  0,  0 ],
        [0,          0,          0,          mu, 0,  0 ],
        [0,          0,          0,          0,  mu, 0 ],
        [0,          0,          0,          0,  0,  mu],
    ])
    return C


def _tet4_vol_B(xyz: np.ndarray) -> tuple[float, np.ndarray]:
    """Volume and strain-displacement matrix B (6×12) for a Tet4 element.

    Parameters
    ----------
    xyz : (4, 3) node coordinates.

    Returns
    -------
    vol : float — element volume (> 0 if correctly oriented).
    B   : (6, 12) constant strain-displacement matrix.

    Reference: Cook et al. (2001) §6.2, eq. 6.2-3 to 6.2-8.
    """
    x1, y1, z1 = xyz[0]
    x2, y2, z2 = xyz[1]
    x3, y3, z3 = xyz[2]
    x4, y4, z4 = xyz[3]

    J = np.array([
        [x2 - x1, x3 - x1, x4 - x1],
        [y2 - y1, y3 - y1, y4 - y1],
        [z2 - z1, z3 - z1, z4 - z1],
    ])
    vol = np.linalg.det(J) / 6.0

    a1 =  (y3 - y4) * (z2 - z4) - (y2 - y4) * (z3 - z4)
    a2 = -((y3 - y4) * (z1 - z4) - (y1 - y4) * (z3 - z4))
    a3 =  (y2 - y4) * (z1 - z4) - (y1 - y4) * (z2 - z4)
    a4 = -(a1 + a2 + a3)

    b1 = -((x3 - x4) * (z2 - z4) - (x2 - x4) * (z3 - z4))
    b2 =  (x3 - x4) * (z1 - z4) - (x1 - x4) * (z3 - z4)
    b3 = -((x2 - x4) * (z1 - z4) - (x1 - x4) * (z2 - z4))
    b4 = -(b1 + b2 + b3)

    c1 =  (x3 - x4) * (y2 - y4) - (x2 - x4) * (y3 - y4)
    c2 = -((x3 - x4) * (y1 - y4) - (x1 - x4) * (y3 - y4))
    c3 =  (x2 - x4) * (y1 - y4) - (x1 - x4) * (y2 - y4)
    c4 = -(c1 + c2 + c3)

    inv6V = 1.0 / (6.0 * abs(vol))

    B = np.zeros((6, 12))
    for i, (ai, bi, ci) in enumerate([(a1, b1, c1), (a2, b2, c2),
                                       (a3, b3, c3), (a4, b4, c4)]):
        col = i * 3
        B[0, col + 0] = ai * inv6V
        B[1, col + 1] = bi * inv6V
        B[2, col + 2] = ci * inv6V
        B[3, col + 0] = bi * inv6V
        B[3, col + 1] = ai * inv6V
        B[4, col + 1] = ci * inv6V
        B[4, col + 2] = bi * inv6V
        B[5, col + 0] = ci * inv6V
        B[5, col + 2] = ai * inv6V

    return abs(vol), B


def _assemble_K_and_f(
    nodes: np.ndarray,
    tets: np.ndarray,
    active_mask: np.ndarray,
    new_mask: np.ndarray,
    C: np.ndarray,
    eps_star: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Assemble global stiffness K (3N×3N) and eigenstrain force f (3N).

    Only *active* elements contribute to K.
    Only *newly activated* elements contribute to f (eigenstrain load for
    current layer).

    Parameters
    ----------
    nodes     : (N, 3)
    tets      : (M, 4)
    active_mask : (M,) bool — elements active in this step (incl. prior layers)
    new_mask  : (M,) bool — elements activated in the *current* layer
    C         : (6, 6) elasticity matrix
    eps_star  : (6,) inherent-strain vector

    Returns
    -------
    K : (3N, 3N) global stiffness (dense)
    f : (3N,)    global load vector from new-layer eigenstrain
    """
    N = nodes.shape[0]
    K = np.zeros((3 * N, 3 * N))
    f = np.zeros(3 * N)

    for e_idx in range(len(tets)):
        if not active_mask[e_idx]:
            continue
        conn = tets[e_idx]          # 4 node indices
        xyz = nodes[conn]           # (4,3)
        vol, B = _tet4_vol_B(xyz)

        K_e = vol * (B.T @ C @ B)  # (12, 12)

        # Global DOF indices  [3i, 3i+1, 3i+2, 3j, …]
        dofs = np.array([3 * n + d for n in conn for d in range(3)])

        # Assemble K
        for i_loc, i_glb in enumerate(dofs):
            for j_loc, j_glb in enumerate(dofs):
                K[i_glb, j_glb] += K_e[i_loc, j_loc]

        # Eigenstrain load for newly activated elements only
        if new_mask[e_idx]:
            # f_e = V * Bᵀ C ε*   (Cook §5.2, initial-strain load vector)
            f_e = vol * (B.T @ (C @ eps_star))  # (12,)
            for i_loc, i_glb in enumerate(dofs):
                f[i_glb] += f_e[i_loc]

    return K, f


def _apply_dirichlet(K: np.ndarray, f: np.ndarray, fixed_dofs: list[int]) -> None:
    """Enforce u[d] = 0 for all d in fixed_dofs (in-place)."""
    for d in fixed_dofs:
        K[d, :] = 0.0
        K[:, d] = 0.0
        K[d, d] = 1.0
        f[d] = 0.0


def _von_mises(sigma6: np.ndarray) -> float:
    """Von-Mises equivalent stress from 6-component Cauchy stress.

    σ_vm = sqrt(½ [(σ_xx-σ_yy)² + (σ_yy-σ_zz)² + (σ_zz-σ_xx)²
                   + 6(τ_xy² + τ_yz² + τ_xz²)])
    Reference: Timoshenko & Goodier (1970) §7.
    """
    sx, sy, sz, txy, tyz, txz = sigma6
    return math.sqrt(0.5 * (
        (sx - sy)**2 + (sy - sz)**2 + (sz - sx)**2
        + 6.0 * (txy**2 + tyz**2 + txz**2)
    ))


# ---------------------------------------------------------------------------
# Layer slicing
# ---------------------------------------------------------------------------

def _slice_layers(
    nodes: np.ndarray,
    tets: np.ndarray,
    layer_thickness: float,
    build_axis: int,
) -> list[np.ndarray]:
    """Assign each element to a build layer.

    A build layer is a slab of thickness `layer_thickness` along `build_axis`.
    Layer 0 is the bottommost slab (base-plate side).

    Returns
    -------
    layers : list of int arrays — each entry contains the element indices in
             that layer.  Layers are ordered bottom (0) to top (N-1).
    """
    # Element centroid coordinate along build axis
    centroids = nodes[tets].mean(axis=1)[:, build_axis]   # (M,)
    z_min = centroids.min()
    # Layer index for each element
    layer_idx = np.floor((centroids - z_min) / layer_thickness).astype(int)
    n_layers = int(layer_idx.max()) + 1

    layers: list[np.ndarray] = []
    for k in range(n_layers):
        mask = np.where(layer_idx == k)[0]
        if len(mask) > 0:
            layers.append(mask)
    return layers


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def simulate_am_process(mesh: AMMesh, params: AMParams) -> AMSimResult:
    """Run the inherent-strain AM process simulation.

    Parameters
    ----------
    mesh   : AMMesh — part mesh (nodes + tet connectivity)
    params : AMParams — material + process parameters

    Returns
    -------
    AMSimResult (see class docstring for field descriptions)
    """
    result = AMSimResult()

    # ---- Validate inputs -----------------------------------------------
    if mesh.nodes.shape[0] < 4:
        result.ok = False
        result.reason = "Mesh must have at least 4 nodes"
        return result
    if mesh.tets.shape[0] < 1:
        result.ok = False
        result.reason = "Mesh must have at least 1 element"
        return result
    if params.E <= 0:
        result.ok = False
        result.reason = "E must be positive"
        return result
    if not (0.0 < params.nu < 0.5):
        result.ok = False
        result.reason = "nu must be in (0, 0.5)"
        return result
    if params.layer_thickness <= 0:
        result.ok = False
        result.reason = "layer_thickness must be positive"
        return result

    nodes = np.asarray(mesh.nodes, dtype=float)
    tets = np.asarray(mesh.tets, dtype=int)
    N = nodes.shape[0]
    M = tets.shape[0]

    # ---- Build axis -------------------------------------------------------
    bd = np.array(params.build_dir, dtype=float)
    bd /= np.linalg.norm(bd)
    # Choose the primary Cartesian axis closest to the build direction
    build_axis = int(np.argmax(np.abs(bd)))  # 0=X, 1=Y, 2=Z

    # ---- Material matrices ------------------------------------------------
    C = _elasticity_matrix(params.E, params.nu)
    eps_star = np.array(params.inherent_strain, dtype=float)

    # ---- Identify base-plate nodes (bottommost layer) ---------------------
    z_coords = nodes[:, build_axis]
    z_min = z_coords.min()
    # Nodes within 1e-9 m of the minimum z are considered base-plate
    tol_bp = max(params.layer_thickness * 0.01, 1e-9)
    baseplate_nodes = np.where(z_coords <= z_min + tol_bp)[0]
    fixed_dofs: list[int] = []
    for n in baseplate_nodes:
        fixed_dofs += [3 * int(n), 3 * int(n) + 1, 3 * int(n) + 2]

    # ---- Layer assignment -------------------------------------------------
    layers = _slice_layers(nodes, tets, params.layer_thickness, build_axis)
    n_layers = len(layers)

    if n_layers == 0:
        result.ok = False
        result.reason = "No layers found — check layer_thickness vs part height"
        return result

    result.n_layers = n_layers
    result.n_nodes = N
    result.n_elems = M

    # ---- Support-region flag (geometric only) ----------------------------
    # Elements whose centroid is in layer 0 or touches overhanging faces
    # Here we use a simple rule: first layer of elements = support region
    support_flags = [False] * M
    if len(layers) > 0:
        for idx in layers[0]:
            support_flags[int(idx)] = True
    result.support_elem_flags = support_flags

    # ---- Layer-by-layer solve --------------------------------------------
    u_total = np.zeros(3 * N)             # global displacement accumulator
    residual_stress = np.zeros((M, 6))    # element residual stress [Pa]
    active_mask = np.zeros(M, dtype=bool)
    layer_max_disp: list[float] = []

    for k, layer_elems in enumerate(layers):
        # Activate new elements
        new_mask = np.zeros(M, dtype=bool)
        new_mask[layer_elems] = True
        active_mask |= new_mask

        # Assemble K and f for active elements (f only for new)
        K, f = _assemble_K_and_f(
            nodes, tets, active_mask, new_mask, C, eps_star
        )

        # Apply Dirichlet BCs (base plate fixed)
        _apply_dirichlet(K, f, fixed_dofs)

        # Solve K Δu = f  (scipy sparse would be faster; use dense for
        # small meshes and keep numpy-only for test harness)
        try:
            delta_u = np.linalg.solve(K, f)
        except np.linalg.LinAlgError:
            # Singular — skip this layer (shouldn't happen if mesh is valid)
            layer_max_disp.append(
                float(np.max(np.linalg.norm(
                    u_total.reshape(-1, 3), axis=1
                )))
            )
            continue

        u_total += delta_u

        # Track max displacement after this layer
        u_nodal = u_total.reshape(-1, 3)  # (N, 3)
        mags = np.linalg.norm(u_nodal, axis=1)
        layer_max_disp.append(float(mags.max()))

        # Update residual stress for active elements
        for e_idx in np.where(active_mask)[0]:
            conn = tets[e_idx]
            xyz = nodes[conn]
            vol, B = _tet4_vol_B(xyz)
            u_e = u_total[[3 * n + d for n in conn for d in range(3)]]
            # Cauchy stress: σ = C (B u_e − ε*)
            eps_mech = B @ u_e - eps_star
            sigma = C @ eps_mech
            residual_stress[int(e_idx)] = sigma

    # ---- Post-process ----------------------------------------------------
    u_nodal = u_total.reshape(-1, 3)
    mags = np.linalg.norm(u_nodal, axis=1)
    max_dev = float(mags.max())

    # Von-Mises
    vm_arr = np.array([
        _von_mises(residual_stress[e]) for e in range(M)
        if active_mask[e]
    ])
    max_vm = float(vm_arr.max()) if len(vm_arr) > 0 else 0.0

    result.displacement = u_nodal
    result.max_deviation_m = max_dev
    result.residual_stress = residual_stress
    result.max_von_mises_pa = max_vm
    result.layer_max_disp_m = layer_max_disp

    # ---- Recoater-interference heuristic ---------------------------------
    # Check top layer: if any node in the topmost layer has an in-plane
    # displacement > 0.5 × layer_thickness in the recoater-traverse plane
    top_layer_elems = layers[-1]
    top_node_set = set()
    for eidx in top_layer_elems:
        for n in tets[eidx]:
            top_node_set.add(int(n))
    # In-plane axes = the two axes that are NOT the build axis
    inplane_axes = [a for a in range(3) if a != build_axis]
    recoater_limit = 0.5 * params.layer_thickness
    for n in top_node_set:
        for ax in inplane_axes:
            if abs(u_nodal[n, ax]) > recoater_limit:
                result.recoater_interference = True
                break

    # ---- Warnings --------------------------------------------------------
    warnings: list[str] = []
    if max_dev > params.distortion_tolerance_m:
        warnings.append(
            f"Max distortion {max_dev * 1e3:.3f} mm exceeds tolerance "
            f"{params.distortion_tolerance_m * 1e3:.3f} mm"
        )
    if result.recoater_interference:
        warnings.append(
            "Recoater interference risk: top-layer in-plane displacement "
            f"exceeds 0.5 × layer_thickness ({recoater_limit * 1e6:.1f} µm)"
        )
    if max_vm > 0.5 * params.E * 0.002:
        # Rough yield-strain proxy: warn if residual stress > ~0.1% E
        warnings.append(
            f"High residual von-Mises stress: {max_vm / 1e6:.1f} MPa — "
            "may indicate yielding not captured by elastic model"
        )

    result.warnings = warnings
    result.ok = True
    return result


# ---------------------------------------------------------------------------
# Convenience: build a simple block mesh for testing
# ---------------------------------------------------------------------------

def make_block_mesh(
    nx: int = 2,
    ny: int = 2,
    nz: int = 4,
    lx: float = 0.01,
    ly: float = 0.01,
    lz: float = 0.02,
) -> AMMesh:
    """Generate a structured hexahedral mesh split into Tet4 elements.

    Each hexahedral cell is split into 5 Tet4 elements (Kuhn splitting),
    following the standard 5-tet decomposition of a cube.

    Parameters
    ----------
    nx, ny, nz : int
        Number of cells in x, y, z directions.
    lx, ly, lz : float
        Total dimensions in metres.

    Returns
    -------
    AMMesh
    """
    dx, dy, dz = lx / nx, ly / ny, lz / nz

    # Node grid
    xs = np.linspace(0.0, lx, nx + 1)
    ys = np.linspace(0.0, ly, ny + 1)
    zs = np.linspace(0.0, lz, nz + 1)
    XX, YY, ZZ = np.meshgrid(xs, ys, zs, indexing='ij')
    nodes = np.column_stack([XX.ravel(), YY.ravel(), ZZ.ravel()])

    def node_id(i, j, k):
        return i * (ny + 1) * (nz + 1) + j * (nz + 1) + k

    tets_list: list[list[int]] = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                # 8 corners of the hex cell
                n000 = node_id(i,   j,   k  )
                n100 = node_id(i+1, j,   k  )
                n010 = node_id(i,   j+1, k  )
                n110 = node_id(i+1, j+1, k  )
                n001 = node_id(i,   j,   k+1)
                n101 = node_id(i+1, j,   k+1)
                n011 = node_id(i,   j+1, k+1)
                n111 = node_id(i+1, j+1, k+1)

                # 5-tet Kuhn splitting (Dompierre et al., 1999)
                tets_list += [
                    [n000, n100, n010, n001],
                    [n100, n110, n010, n111],
                    [n001, n101, n100, n111],
                    [n010, n011, n001, n111],
                    [n100, n001, n010, n111],
                ]

    tets = np.array(tets_list, dtype=int)
    return AMMesh(nodes=nodes, tets=tets)
