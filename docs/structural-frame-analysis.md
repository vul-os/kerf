# 2-D/3-D Structural Frame Analysis

> Compute deflections, internal forces, and moment diagrams for multi-member steel or timber frames using the direct stiffness method.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/struct/frame.py`
**Shipped**: Wave 8
**LLM tools**: `feature_frame_analysis`, `feature_struct_framing`

---

## What it is

Direct stiffness method frame analysis assembles global stiffness matrices from Euler-Bernoulli beam-column elements (with axial, shear, and bending DOFs), applies nodal and distributed loads, and solves for nodal displacements and member forces and moments. It covers 2-D portal frames, multi-bay/multi-storey frames, cantilever columns, and simple trusses.

## How to use it

### From chat

> "Compute the deflection at mid-span of a 5 m steel portal frame under 10 kN/m UDL."

### From Python

```python
from kerf_cad_core.struct.frame import (
    Node2D, Element2D, UDL2D, Frame2D,
)

frame = Frame2D()
n0 = frame.add_node(Node2D(x=0, y=0, fixed_dofs={0, 1, 2}))
n1 = frame.add_node(Node2D(x=5, y=0))
n2 = frame.add_node(Node2D(x=5, y=3))

frame.add_element(Element2D(i=n0, j=n1, E=200e9, A=6.45e-3, I=8.3e-6))
frame.add_load(UDL2D(element=0, w=-10000))  # 10 kN/m downward

result = frame.solve()
print(result.node_displacements[n1])
print(result.element_forces[0])  # [N, Vy, Mz] at element start
```

### From an LLM tool spec

```json
{"tool": "feature_frame_analysis", "input": {"nodes": [...], "elements": [...], "loads": [...]}}
```

## How it works

Each beam-column element contributes a 6×6 (2-D) or 12×12 (3-D) local stiffness matrix including axial (EA/L), bending (EI cubic Hermite), and shear terms. Local matrices are assembled into the global K matrix by index scatter. Boundary conditions are applied by row/column elimination. The system Ku = f is solved by Gaussian elimination. Element internal forces are recovered by back-substitution.

## API reference

| Class / Function | Purpose |
|---|---|
| `Frame2D()` | 2-D frame builder |
| `frame.add_node(Node2D(...))` | Add node with optional fixed DOFs |
| `frame.add_element(Element2D(...))` | Add beam-column element |
| `frame.add_load(UDL2D(...))` | Add distributed or nodal load |
| `frame.solve()` | Returns `FrameResult2D` |

## Example

```python
result = frame.solve()
# FrameResult2D:
#   node_displacements[n1] = [0.0012, -0.0041, 0.0003]  (m, m, rad)
#   element_forces[0]      = [45200, -25000, 31200]      (N, N, N·m)
```

## Honest caveats

The frame solver assumes linear-elastic material, small displacements, and Euler-Bernoulli beam theory (no shear deformation). Geometric nonlinearity (P-Δ, P-δ effects) requires second-order iterative analysis, not implemented here. For slender columns under significant axial load, check buckling separately with `euler_buckling_load`.

## References

- McGuire, Gallagher & Ziemian, *Matrix Structural Analysis*, 2nd ed. (2000).
- AISC 360-22, *Specification for Structural Steel Buildings*.
