# ALE Dynamic Mesh and Fluid-Structure Interaction

> Deform the CFD mesh to follow moving boundaries (flutter, vibrating blades, sloshing) using ALE kinematics and one-way fluid-structure coupling.

**Module**: `packages/kerf-cfd/src/kerf_cfd/fsi/dynamic_mesh.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_fsi_coupling`

---

## What it is

When a solid structure moves or deforms — a heart valve opening, a bridge deck oscillating in wind, a turbine blade vibrating — the CFD mesh must move with it. The Arbitrary Lagrangian-Eulerian (ALE) formulation allows mesh vertices to move independently of the fluid, maintaining mesh quality while tracking the moving boundary.

This module provides: rigid-body mesh displacement (translate/rotate a boundary patch and diffuse the deformation through the interior mesh), the Geometric Conservation Law (GCL) correction to prevent spurious mass creation from mesh motion, and one-way FSI coupling that takes a structural displacement field and produces a corresponding ALE mesh deformation. Engineers use it to simulate moving valves, vibrating heat-exchanger tubes, and blade flutter.

## How to use it

### From chat (natural language)

> "Apply a 2mm lateral displacement to the blade boundary patch and diffuse it through the interior mesh"

The LLM calls `cfd_fsi_coupling` with the displacement and mesh ID.

### From Python

```python
from kerf_cfd.fsi.dynamic_mesh import (
    DynamicMeshState, displace_mesh_rigid,
    compute_geometric_conservation_law_correction,
    fsi_one_way_coupling,
)

# Rigid displacement of a boundary patch
state = DynamicMeshState(vertices=verts, connectivity=conn,
                          boundary_patches=patches)
state_new = displace_mesh_rigid(
    state, patch_name="blade",
    translation=(0, 0.002, 0),  # 2mm in y
    rotation_angle=0.0,
)

# GCL correction for time-accurate simulations
gcl = compute_geometric_conservation_law_correction(state, state_new, dt=1e-4)

# One-way FSI: apply structural displacement to mesh
state_fsi = fsi_one_way_coupling(state, structural_displacement)
```

### From an LLM tool spec

```json
{"tool": "cfd_fsi_coupling", "mesh_id": "blade_domain",
 "displacement_mm": 2.0, "direction": [0,1,0], "dt": 1e-4}
```

## How it works

Mesh interior vertex displacements are computed by Laplacian mesh diffusion: ∇²δx = 0 with Dirichlet boundary conditions on the moving patch and zero displacement at the far-field. This is solved by a single Jacobi iteration sweep, spreading the boundary motion smoothly through the interior mesh without element folding (for moderate displacements).

The GCL correction ensures that the discrete conservation laws are satisfied on the deforming mesh: the swept volume of each face between old and new mesh positions is computed and subtracted from the convective flux to prevent spurious mass sources.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `displace_mesh_rigid(state, patch_name, translation, rotation_angle)` | `DynamicMeshState` | Move a patch and diffuse |
| `compute_geometric_conservation_law_correction(old, new, dt)` | `np.ndarray` | GCL flux correction |
| `fsi_one_way_coupling(mesh_state, structural_disp)` | `DynamicMeshState` | Apply FEA displacement to mesh |

## Example

```python
state_new = displace_mesh_rigid(state, "valve", translation=(0,0,0.001))
print(f"Min cell quality after deformation: {state_new.min_cell_quality:.4f}")
```

## Honest caveats

Laplacian mesh diffusion works for small to moderate deformations (< 10% of local cell size). Large deformations require mesh remeshing or topological changes, which are not implemented here. One-way coupling ignores the fluid forces on the structure — for true two-way FSI, couple this module with the FEM nonlinear solver. GCL correction is only needed for time-accurate (transient) simulations; steady-state ALE does not require it.

## References

- Donea, Giuliani & Halleux (1982). "An arbitrary Lagrangian-Eulerian finite element method for transient dynamic fluid-structure interactions." *CMAME* 33(1).
- Thomas & Lombard (1979). "Geometric conservation law and its application to flow computations on moving grids." *AIAA J* 17(10).
