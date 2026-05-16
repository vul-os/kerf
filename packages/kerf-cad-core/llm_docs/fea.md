# Finite Element Analysis (FEA) Solver

Pure-Python FEA solvers. No OCC or numpy dependency. All tools are stateless —
they compute and return results; no DB write. Units: SI (metres, Newtons, Pascals).

---

## When to use

Trigger on: FEA, finite element, truss analysis, pin-jointed truss, structural
analysis, stress analysis, displacement analysis, reaction forces, element
forces, axial stress, bar element, plasticity, elastic-plastic, yield, hardening,
stiffness matrix, direct stiffness method, bilinear hardening, return mapping.

---

## Tools

### `fea_solve_truss`

Assemble and solve a 2D pin-jointed linear elastic truss using the direct
stiffness method.

**Key inputs:**
- `nodes` — list of `[x, y]` node coordinates in metres.
- `elements` — list of `[i, j]` node-index pairs (0-based).
- `supports` — dict `{node_index: {ux: bool, uy: bool}}` for fixed DOFs.
- `loads` — dict `{node_index: {fx: float, fy: float}}` in Newtons.
- `E` — Young's modulus (Pa, default 200e9 for steel).
- `A` — cross-sectional area (m², default 1e-4).

**Computes:** global stiffness matrix assembly, Gaussian elimination, nodal
displacements (m), reaction forces (N), element axial forces (N), stresses
(Pa), and strains.

**Returns:** `{ok, displacements, reactions, element_forces, element_stresses,
element_strains, warnings:[]}`.

---

### `fea_solve_bar_plastic`

Solve a 1D uniaxial bar with bilinear isotropic-hardening plasticity.

**Key inputs:** `length` (m), `area` (m²), `E` (Pa), `sigma_y` (initial yield
stress, Pa), `H` (plastic hardening modulus, Pa; 0 = perfect plasticity),
`force` (N), `steps` (load increments, default 20).

**Computes:** load ramped in equal increments; Newton-Raphson iterations with
consistent tangent and radial return mapping at each step. Returns per-step
history.

**Returns:** `{ok, steps:[{step, force_N, displacement_m, stress_Pa, strain,
plastic_strain, plastic, converged}], warnings:[]}`.

---

## Example

**User:** "Analyse a simple 3-node triangular truss. Nodes at (0,0), (1,0),
(0.5,1) m. Elements 0-1, 1-2, 0-2. Nodes 0 and 1 are pinned. 10 kN downward
load at node 2. Steel, A = 500 mm²."

**Tool:** `fea_solve_truss` with appropriate nodes, elements, supports, loads,
E=200e9, A=500e-6.

Returns displacements at each node, axial force per member, stress and strain,
and support reactions.
