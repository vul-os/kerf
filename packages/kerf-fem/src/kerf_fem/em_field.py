"""
Low-frequency 2-D electromagnetics via triangular FEM.

Implements:
  electrostatics  — scalar potential φ, E-field, capacitance
  magnetostatics  — vector potential Az, B-field, inductance, force on a region
  solenoid_inductance     — analytic helper (infinite solenoid)
  parallel_plate_capacitance — analytic helper
  field_energy_electric   — ½ εE² integrated over mesh
  field_energy_magnetic   — ½ μ⁻¹B² integrated over mesh

All routines are pure Python (no numpy / scipy / external deps).
They never raise; errors are returned via {"ok": False, "reason": "..."}.

FEM convention
--------------
Mesh dict:
    {
      "nodes":    [[x0,y0], [x1,y1], ...],          # float coords
      "elements": [[n0,n1,n2], ...],                 # 0-based CCW triangles
    }

Physical parameter dicts may be:
  - a scalar  → uniform over all elements
  - a list    → one value per element

Dirichlet BC dict  { node_index: value, ... }

All SI units throughout (metres, volts, amperes, farads, henries, tesla).
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Internal linear-algebra helpers (Gaussian elimination, pure Python)
# ---------------------------------------------------------------------------

def _gauss_solve(A: list[list[float]], b: list[float]) -> list[float] | None:
    """
    Solve Ax = b via partial-pivot Gaussian elimination.
    Returns x or None if the system is singular.
    """
    n = len(b)
    # Build augmented matrix
    aug = [A[i][:] + [b[i]] for i in range(n)]

    for col in range(n):
        # Find pivot
        max_row, max_val = col, abs(aug[col][col])
        for row in range(col + 1, n):
            v = abs(aug[row][col])
            if v > max_val:
                max_val = v
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]

        pivot = aug[col][col]
        if abs(pivot) < 1e-15:
            return None  # singular

        inv_pivot = 1.0 / pivot
        for row in range(col + 1, n):
            factor = aug[row][col] * inv_pivot
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]

    # Back-substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = aug[i][n]
        for j in range(i + 1, n):
            x[i] -= aug[i][j] * x[j]
        if abs(aug[i][i]) < 1e-15:
            return None
        x[i] /= aug[i][i]
    return x


# ---------------------------------------------------------------------------
# Triangle geometry helpers
# ---------------------------------------------------------------------------

def _tri_area_and_grad(
    x0: float, y0: float,
    x1: float, y1: float,
    x2: float, y2: float,
) -> tuple[float, list[float], list[float]]:
    """
    Return (area, b_coeffs, c_coeffs) for a linear triangle.

    Shape functions:  N_i = (a_i + b_i·x + c_i·y) / (2·area)
    b = [y1-y2, y2-y0, y0-y1]
    c = [x2-x1, x0-x2, x1-x0]
    """
    b = [y1 - y2, y2 - y0, y0 - y1]
    c = [x2 - x1, x0 - x2, x1 - x0]
    area = 0.5 * (b[0] * c[1] - b[1] * c[0])
    return area, b, c


def _scalar_value(param: Any, e_idx: int, n_elem: int) -> float:
    """Return per-element scalar: param may be float/int or list."""
    if isinstance(param, (int, float)):
        return float(param)
    return float(param[e_idx])


# ---------------------------------------------------------------------------
# FEM assembly — scalar Poisson/Laplace
# ---------------------------------------------------------------------------

def _assemble_poisson(
    nodes: list,
    elements: list,
    coeff: Any,
    rhs_density: Any,
) -> tuple[list[list[float]], list[float]] | None:
    """
    Assemble global stiffness K and load vector f for:

        -∇·(coeff ∇u) = rhs_density   in Ω

    K_ij += coeff · (b_i·b_j + c_i·c_j) / (4·area)
    f_i  += rhs_density · area / 3   (uniform source per triangle)

    Returns (K, f) or None if a degenerate element is found.
    """
    n_nodes = len(nodes)
    n_elem = len(elements)

    K = [[0.0] * n_nodes for _ in range(n_nodes)]
    f = [0.0] * n_nodes

    for e_idx, tri in enumerate(elements):
        n0, n1, n2 = tri
        x0, y0 = nodes[n0]
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]

        area, b, c = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
        if abs(area) < 1e-30:
            continue  # degenerate triangle — skip

        if area < 0.0:
            # Flip to CCW orientation
            n1, n2 = n2, n1
            area = -area
            b = [-bv for bv in b]
            c = [-cv for cv in c]
            b[1], b[2] = -b[2], -b[1]
            c[1], c[2] = -c[2], -c[1]
            # Recompute properly
            x0, y0 = nodes[n0]
            x1, y1 = nodes[n1]
            x2, y2 = nodes[n2]
            area, b, c = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
            if abs(area) < 1e-30:
                continue

        alpha = _scalar_value(coeff, e_idx, n_elem)
        rho   = _scalar_value(rhs_density, e_idx, n_elem)

        local_nodes = [n0, n1, n2]
        # Stiffness contribution
        for i_loc in range(3):
            for j_loc in range(3):
                val = alpha * (b[i_loc] * b[j_loc] + c[i_loc] * c[j_loc]) / (4.0 * area)
                K[local_nodes[i_loc]][local_nodes[j_loc]] += val
            # Load contribution (body source)
            f[local_nodes[i_loc]] += rho * area / 3.0

    return K, f


def _apply_dirichlet(
    K: list[list[float]],
    f: list[float],
    dirichlet_bc: dict,
) -> None:
    """
    Apply Dirichlet BCs in-place using row/column zeroing.

    For each constrained DOF d with value g:
      - Zero row d and column d in K
      - Set K[d][d] = 1, f[d] = g
      - Modify remaining rows: f[i] -= K_old[i][d] * g  (done before zeroing col)
    """
    n = len(f)
    for d_str, g in dirichlet_bc.items():
        d = int(d_str) if isinstance(d_str, str) else d_str
        g = float(g)
        # Subtract column contribution from RHS
        for i in range(n):
            if i != d:
                f[i] -= K[i][d] * g
        # Zero row and column
        for j in range(n):
            K[d][j] = 0.0
            K[j][d] = 0.0
        K[d][d] = 1.0
        f[d] = g


# ---------------------------------------------------------------------------
# Public API — electrostatics
# ---------------------------------------------------------------------------

def electrostatics(
    mesh: dict,
    permittivity: Any,
    dirichlet_bc: dict,
    charge_density: Any = 0.0,
) -> dict[str, Any]:
    """
    Solve 2-D electrostatic problem:

        -∇·(ε ∇φ) = ρ_free

    Parameters
    ----------
    mesh          : {"nodes": [...], "elements": [...]}
    permittivity  : ε — scalar or per-element list  [F/m]
    dirichlet_bc  : {node_index: voltage, ...}
    charge_density: ρ — scalar or per-element list  [C/m²]

    Returns
    -------
    dict with keys:
        ok            bool
        phi           list[float]   nodal potential  [V]
        E_field       list[[float,float]]  E at each element centroid  [V/m]
        capacitance   float   Q/ΔV between first two distinct Dirichlet groups [F/m]
        energy        float   ½ ε |E|² integrated  [J/m]
    """
    if not isinstance(mesh, dict):
        return {"ok": False, "reason": "mesh must be a dict"}
    nodes = mesh.get("nodes", [])
    elements = mesh.get("elements", [])
    if len(nodes) < 3:
        return {"ok": False, "reason": "mesh must have at least 3 nodes"}
    if len(elements) < 1:
        return {"ok": False, "reason": "mesh must have at least 1 element"}
    if len(dirichlet_bc) < 1:
        return {"ok": False, "reason": "at least one Dirichlet BC required"}

    result = _assemble_poisson(nodes, elements, permittivity, charge_density)
    if result is None:
        return {"ok": False, "reason": "mesh assembly failed"}

    K, f = result
    _apply_dirichlet(K, f, dirichlet_bc)

    phi = _gauss_solve(K, f)
    if phi is None:
        return {"ok": False, "reason": "linear system is singular — check boundary conditions"}

    # Recover E = -∇φ at each element centroid
    E_field = []
    energy = 0.0
    n_elem = len(elements)
    for e_idx, tri in enumerate(elements):
        n0, n1, n2 = tri
        x0, y0 = nodes[n0]
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]
        area, b, c = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
        if abs(area) < 1e-30:
            E_field.append([0.0, 0.0])
            continue
        if area < 0.0:
            area = abs(area)

        phi_e = [phi[n0], phi[n1], phi[n2]]

        # grad(φ) = Σ φ_i * [b_i, c_i] / (2 area)
        dph_dx = (phi_e[0] * b[0] + phi_e[1] * b[1] + phi_e[2] * b[2]) / (2.0 * area)
        dph_dy = (phi_e[0] * c[0] + phi_e[1] * c[1] + phi_e[2] * c[2]) / (2.0 * area)
        Ex = -dph_dx
        Ey = -dph_dy
        E_field.append([Ex, Ey])

        eps_e = _scalar_value(permittivity, e_idx, n_elem)
        energy += 0.5 * eps_e * (Ex * Ex + Ey * Ey) * area

    # Capacitance between the two conductor groups (if exactly 2 distinct values)
    capacitance = _compute_capacitance(nodes, elements, phi, permittivity, dirichlet_bc)

    return {
        "ok": True,
        "phi": phi,
        "E_field": E_field,
        "capacitance": capacitance,
        "energy": energy,
    }


def _compute_capacitance(
    nodes: list,
    elements: list,
    phi: list[float],
    permittivity: Any,
    dirichlet_bc: dict,
) -> float:
    """
    Estimate capacitance per unit depth [F/m] from field energy:

        C = 2 W / ΔV²

    where ΔV = (max Dirichlet voltage) − (min Dirichlet voltage).
    """
    if len(dirichlet_bc) < 2:
        return 0.0

    vals = [float(v) for v in dirichlet_bc.values()]
    v_max = max(vals)
    v_min = min(vals)
    delta_v = v_max - v_min
    if abs(delta_v) < 1e-30:
        return 0.0

    # Re-compute energy
    n_elem = len(elements)
    energy = 0.0
    for e_idx, tri in enumerate(elements):
        n0, n1, n2 = tri
        x0, y0 = nodes[n0]
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]
        area, b, c = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
        if abs(area) < 1e-30:
            continue
        area = abs(area)
        phi_e = [phi[n0], phi[n1], phi[n2]]
        dph_dx = (phi_e[0] * b[0] + phi_e[1] * b[1] + phi_e[2] * b[2]) / (2.0 * area)
        dph_dy = (phi_e[0] * c[0] + phi_e[1] * c[1] + phi_e[2] * c[2]) / (2.0 * area)
        eps_e = _scalar_value(permittivity, e_idx, n_elem)
        energy += 0.5 * eps_e * (dph_dx * dph_dx + dph_dy * dph_dy) * area

    return 2.0 * energy / (delta_v * delta_v)


# ---------------------------------------------------------------------------
# Public API — magnetostatics
# ---------------------------------------------------------------------------

def magnetostatics(
    mesh: dict,
    permeability: Any,
    current_density: Any,
    bc: dict,
    force_region: list[int] | None = None,
) -> dict[str, Any]:
    """
    Solve 2-D magnetostatic problem in the Az (out-of-plane) formulation:

        -∇·(μ⁻¹ ∇Az) = Jz

    Parameters
    ----------
    mesh          : {"nodes": [...], "elements": [...]}
    permeability  : μ — scalar or per-element list  [H/m]
    current_density: Jz — scalar or per-element list  [A/m²]
    bc            : Dirichlet BC {node_index: Az_value}
                    (typically Az = 0 on outer boundary)
    force_region  : list of element indices over which to integrate force
                    (Lorentz: F = J × B); None → no force computation

    Returns
    -------
    dict with keys:
        ok            bool
        Az            list[float]   nodal vector potential  [Wb/m]
        B_field       list[[float,float]]  Bx, By per element  [T]
        inductance    float   2W / I²  [H/m]  (I = total current in mesh)
        force         [float,float]  Lorentz force on force_region  [N/m]
        energy        float   ½ μ⁻¹ |B|² integrated  [J/m]
    """
    if not isinstance(mesh, dict):
        return {"ok": False, "reason": "mesh must be a dict"}
    nodes = mesh.get("nodes", [])
    elements = mesh.get("elements", [])
    if len(nodes) < 3:
        return {"ok": False, "reason": "mesh must have at least 3 nodes"}
    if len(elements) < 1:
        return {"ok": False, "reason": "mesh must have at least 1 element"}

    # μ⁻¹ as the diffusion coefficient
    n_elem = len(elements)
    inv_mu = [1.0 / _scalar_value(permeability, e, n_elem) for e in range(n_elem)]

    result = _assemble_poisson(nodes, elements, inv_mu, current_density)
    if result is None:
        return {"ok": False, "reason": "mesh assembly failed"}

    K, f = result

    # Apply Dirichlet BCs (Az = 0 on boundary if provided)
    if bc:
        _apply_dirichlet(K, f, bc)
    else:
        # Pin first node to zero to remove rigid body mode
        _apply_dirichlet(K, f, {0: 0.0})

    Az = _gauss_solve(K, f)
    if Az is None:
        return {"ok": False, "reason": "linear system is singular — check boundary conditions"}

    # B = curl Az = (∂Az/∂y, -∂Az/∂x)
    B_field = []
    energy = 0.0
    force_x = 0.0
    force_y = 0.0

    for e_idx, tri in enumerate(elements):
        n0, n1, n2 = tri
        x0, y0 = nodes[n0]
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]
        area, b, c = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
        if abs(area) < 1e-30:
            B_field.append([0.0, 0.0])
            continue
        area = abs(area)

        Az_e = [Az[n0], Az[n1], Az[n2]]

        # ∂Az/∂x = Σ Az_i * b_i / (2 area)
        dAz_dx = (Az_e[0] * b[0] + Az_e[1] * b[1] + Az_e[2] * b[2]) / (2.0 * area)
        # ∂Az/∂y = Σ Az_i * c_i / (2 area)
        dAz_dy = (Az_e[0] * c[0] + Az_e[1] * c[1] + Az_e[2] * c[2]) / (2.0 * area)

        Bx =  dAz_dy   # ∂Az/∂y
        By = -dAz_dx   # -∂Az/∂x
        B_field.append([Bx, By])

        mu_e = _scalar_value(permeability, e_idx, n_elem)
        energy += 0.5 / mu_e * (Bx * Bx + By * By) * area

        # Lorentz force on designated region
        if force_region is not None and e_idx in force_region:
            Jz = _scalar_value(current_density, e_idx, n_elem)
            # F = J × B  (Jz ẑ × B) = Jz (Bx ŷ - By x̂)  per unit volume, × area = per unit depth
            force_x += Jz * (-By) * area
            force_y += Jz * Bx * area

    # Inductance from energy:  L = 2W / I²
    # Total current I = Σ_e Jz * area_e
    I_total = 0.0
    for e_idx, tri in enumerate(elements):
        n0, n1, n2 = tri
        x0, y0 = nodes[n0]
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]
        area, _, _ = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
        area = abs(area)
        Jz = _scalar_value(current_density, e_idx, n_elem)
        I_total += Jz * area

    if abs(I_total) > 1e-30:
        inductance = 2.0 * energy / (I_total * I_total)
    else:
        inductance = 0.0

    return {
        "ok": True,
        "Az": Az,
        "B_field": B_field,
        "inductance": inductance,
        "force": [force_x, force_y],
        "energy": energy,
    }


# ---------------------------------------------------------------------------
# Analytic helpers
# ---------------------------------------------------------------------------

def solenoid_inductance(
    n_turns: float,
    length: float,
    radius: float,
    mu_r: float = 1.0,
) -> dict[str, Any]:
    """
    Analytic inductance of a long air-core solenoid.

        L = μ₀ μ_r n² π r² / ℓ

    Parameters
    ----------
    n_turns : total number of turns N
    length  : solenoid length ℓ  [m]
    radius  : inner radius r  [m]
    mu_r    : relative permeability of core (default 1.0)

    Returns
    -------
    dict  ok, L [H], B_inside [T] per amp
    """
    if n_turns <= 0:
        return {"ok": False, "reason": "n_turns must be positive"}
    if length <= 0:
        return {"ok": False, "reason": "length must be positive"}
    if radius <= 0:
        return {"ok": False, "reason": "radius must be positive"}
    if mu_r <= 0:
        return {"ok": False, "reason": "mu_r must be positive"}

    mu0 = 4.0 * math.pi * 1e-7
    mu = mu0 * mu_r
    n_density = n_turns / length           # turns per metre
    area = math.pi * radius * radius
    L = mu * n_density * n_density * area * length   # = μ n² A ℓ / ℓ = μ n² A
    B_per_amp = mu * n_density             # B = μ n I  →  B/I = μ n

    return {"ok": True, "L": L, "B_inside_per_amp": B_per_amp}


def parallel_plate_capacitance(
    area: float,
    separation: float,
    eps_r: float = 1.0,
) -> dict[str, Any]:
    """
    Analytic capacitance of a parallel-plate capacitor (no fringing).

        C = ε₀ ε_r A / d

    Parameters
    ----------
    area       : plate area A  [m²]
    separation : plate separation d  [m]
    eps_r      : relative permittivity (default 1.0)

    Returns
    -------
    dict  ok, C [F], E_per_volt [V/m per V]
    """
    if area <= 0:
        return {"ok": False, "reason": "area must be positive"}
    if separation <= 0:
        return {"ok": False, "reason": "separation must be positive"}
    if eps_r <= 0:
        return {"ok": False, "reason": "eps_r must be positive"}

    eps0 = 8.854187817e-12
    eps = eps0 * eps_r
    C = eps * area / separation
    E_per_volt = 1.0 / separation

    return {"ok": True, "C": C, "E_per_volt": E_per_volt}


def coaxial_capacitance(
    inner_radius: float,
    outer_radius: float,
    eps_r: float = 1.0,
) -> dict[str, Any]:
    """
    Analytic capacitance per unit length of a coaxial cable.

        C/L = 2πε / ln(b/a)

    Parameters
    ----------
    inner_radius : a  [m]
    outer_radius : b  [m]
    eps_r        : relative permittivity

    Returns
    -------
    dict  ok, C_per_length [F/m]
    """
    if inner_radius <= 0:
        return {"ok": False, "reason": "inner_radius must be positive"}
    if outer_radius <= inner_radius:
        return {"ok": False, "reason": "outer_radius must be greater than inner_radius"}
    if eps_r <= 0:
        return {"ok": False, "reason": "eps_r must be positive"}

    eps0 = 8.854187817e-12
    eps = eps0 * eps_r
    C_per_length = 2.0 * math.pi * eps / math.log(outer_radius / inner_radius)

    return {"ok": True, "C_per_length": C_per_length}


# ---------------------------------------------------------------------------
# Field-energy helpers
# ---------------------------------------------------------------------------

def field_energy_electric(
    mesh: dict,
    permittivity: Any,
    E_field: list,
) -> dict[str, Any]:
    """
    Integrate electric field energy: W = ½ ∫ ε |E|² dΩ

    Parameters
    ----------
    mesh         : {"nodes": [...], "elements": [...]}
    permittivity : ε per element or scalar
    E_field      : list of [Ex, Ey] per element (from electrostatics())

    Returns
    -------
    dict  ok, energy [J/m]
    """
    nodes = mesh.get("nodes", [])
    elements = mesh.get("elements", [])
    n_elem = len(elements)
    if len(E_field) != n_elem:
        return {"ok": False, "reason": "E_field length must match number of elements"}

    energy = 0.0
    for e_idx, tri in enumerate(elements):
        n0, n1, n2 = tri
        x0, y0 = nodes[n0]
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]
        area, _, _ = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
        area = abs(area)
        if area < 1e-30:
            continue
        eps_e = _scalar_value(permittivity, e_idx, n_elem)
        Ex, Ey = E_field[e_idx]
        energy += 0.5 * eps_e * (Ex * Ex + Ey * Ey) * area

    return {"ok": True, "energy": energy}


def field_energy_magnetic(
    mesh: dict,
    permeability: Any,
    B_field: list,
) -> dict[str, Any]:
    """
    Integrate magnetic field energy: W = ½ ∫ μ⁻¹ |B|² dΩ

    Parameters
    ----------
    mesh         : {"nodes": [...], "elements": [...]}
    permeability : μ per element or scalar
    B_field      : list of [Bx, By] per element (from magnetostatics())

    Returns
    -------
    dict  ok, energy [J/m]
    """
    nodes = mesh.get("nodes", [])
    elements = mesh.get("elements", [])
    n_elem = len(elements)
    if len(B_field) != n_elem:
        return {"ok": False, "reason": "B_field length must match number of elements"}

    energy = 0.0
    for e_idx, tri in enumerate(elements):
        n0, n1, n2 = tri
        x0, y0 = nodes[n0]
        x1, y1 = nodes[n1]
        x2, y2 = nodes[n2]
        area, _, _ = _tri_area_and_grad(x0, y0, x1, y1, x2, y2)
        area = abs(area)
        if area < 1e-30:
            continue
        mu_e = _scalar_value(permeability, e_idx, n_elem)
        Bx, By = B_field[e_idx]
        energy += 0.5 / mu_e * (Bx * Bx + By * By) * area

    return {"ok": True, "energy": energy}


# ---------------------------------------------------------------------------
# LLM tool registration (gated — only when kerf_chat is available)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, register
except ImportError:
    try:
        from kerf_fem._compat import ToolSpec, register
    except ImportError:
        ToolSpec = None
        register = None


def _maybe_register():
    if ToolSpec is None or register is None:
        return

    import json

    _electrostatics_spec = ToolSpec(
        name="fem_electrostatics",
        description=(
            "Solve a 2-D electrostatics problem on a triangular mesh. "
            "Returns nodal potential, E-field per element, capacitance, and field energy."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mesh": {
                    "type": "object",
                    "description": '{"nodes":[[x,y],...], "elements":[[n0,n1,n2],...]}',
                },
                "permittivity": {
                    "description": "ε — scalar or per-element list [F/m]",
                },
                "dirichlet_bc": {
                    "type": "object",
                    "description": "Boundary conditions: {node_index: voltage}",
                },
                "charge_density": {
                    "description": "ρ — scalar or per-element list [C/m²] (default 0)",
                },
            },
            "required": ["mesh", "permittivity", "dirichlet_bc"],
        },
    )

    _magnetostatics_spec = ToolSpec(
        name="fem_magnetostatics",
        description=(
            "Solve a 2-D magnetostatics problem on a triangular mesh (Az formulation). "
            "Returns vector potential, B-field, inductance, Lorentz force, and field energy."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mesh": {"type": "object"},
                "permeability": {"description": "μ — scalar or per-element list [H/m]"},
                "current_density": {"description": "Jz — scalar or per-element list [A/m²]"},
                "bc": {
                    "type": "object",
                    "description": "Dirichlet BC {node_index: Az_value}; {} pins node 0",
                },
                "force_region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Element indices for Lorentz force integration",
                },
            },
            "required": ["mesh", "permeability", "current_density", "bc"],
        },
    )

    @register(_electrostatics_spec)
    async def _run_electrostatics(ctx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as e:
            try:
                from kerf_fem._compat import err_payload
            except ImportError:
                from kerf_chat.tools.registry import err_payload
            return err_payload(f"invalid args: {e}", "BAD_ARGS")
        try:
            from kerf_fem._compat import ok_payload, err_payload
        except ImportError:
            from kerf_chat.tools.registry import ok_payload, err_payload
        result = electrostatics(
            mesh=a.get("mesh", {}),
            permittivity=a.get("permittivity", 8.854187817e-12),
            dirichlet_bc=a.get("dirichlet_bc", {}),
            charge_density=a.get("charge_density", 0.0),
        )
        return ok_payload(result)

    @register(_magnetostatics_spec)
    async def _run_magnetostatics(ctx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as e:
            try:
                from kerf_fem._compat import err_payload
            except ImportError:
                from kerf_chat.tools.registry import err_payload
            return err_payload(f"invalid args: {e}", "BAD_ARGS")
        try:
            from kerf_fem._compat import ok_payload, err_payload
        except ImportError:
            from kerf_chat.tools.registry import ok_payload, err_payload
        result = magnetostatics(
            mesh=a.get("mesh", {}),
            permeability=a.get("permeability", 4.0 * math.pi * 1e-7),
            current_density=a.get("current_density", 0.0),
            bc=a.get("bc", {}),
            force_region=a.get("force_region"),
        )
        return ok_payload(result)


_maybe_register()
