# 2-D/3-D Structural Frame Analysis

*Domain: Structural · Module: `packages/kerf-cad-core/src/kerf_cad_core/struct/frame.py` · Shipped: Wave 8*

## Overview

Direct stiffness method frame analysis for 2-D and 3-D beam-column structures. Assembles global stiffness matrices from Euler-Bernoulli beam elements with axial degrees of freedom, applies nodal and distributed loads, and solves for nodal displacements and element forces/moments. Used as the analytical backbone for structural framing layout, connection checks, and member sizing.

## When to use

- Computing deflections and internal forces in a multi-storey steel or timber frame.
- Checking if a beam sizing satisfies deflection limits under service loads.
- Generating bending moment and shear force diagrams for a framed structure.

## API

```python
from kerf_cad_core.struct.frame import (
    Node2D, Element2D, NodalLoad2D, UDL2D,
    Frame2D, FrameResult2D,
)

frame = Frame2D()
n0 = frame.add_node(Node2D(x=0, y=0, fixed_dofs={0,1,2}))
n1 = frame.add_node(Node2D(x=5, y=0))
n2 = frame.add_node(Node2D(x=5, y=3))

frame.add_element(Element2D(i=n0, j=n1, E=200e9, A=6.45e-3, I=8.3e-6))
frame.add_load(UDL2D(element=0, w=-10000))  # 10 kN/m downward

result: FrameResult2D = frame.solve()
print(result.node_displacements[n1])
print(result.element_forces[0])  # [N, Vy, Mz] at element start
```

## LLM tools

`feature_frame_analysis`, `feature_struct_framing`

## References

- McGuire, Gallagher & Ziemian, *Matrix Structural Analysis*, 2nd ed. (2000).
- AISC 360-22, *Specification for Structural Steel Buildings*.

## Honest caveats

The frame solver assumes linear-elastic material, small displacements, and Euler-Bernoulli beam theory (no shear deformation). Geometric nonlinearity (P-Δ, P-δ effects) requires iterative second-order analysis, which is not implemented here. For slender structures with significant axial compression, check stability separately with `euler_buckling_load`.
