# SDF CSG and Marching Cubes

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/geom/sdf_csg.py` · Shipped: Wave 7 (GK-P22)*

## Overview

Provides smooth-union, subtract, and intersect operations on signed-distance fields (SDF), plus a Lorensen-Cline marching-cubes surface extractor. Closes the implicit-modelling loop with ZBrush DynaMesh / Blender geometry-nodes SDF parity. Pure Python + NumPy; no OCC required.

## When to use

- Blending two solids with a smooth fillet radius (smooth CSG, `k > 0`).
- Generating organic shapes that are hard to model with BRep.
- Extracting a mesh from volumetric data or implicit geometry.
- Rapid prototyping of new solid forms before committing to parametric NURBS.

## API

```python
from kerf_cad_core.geom.sdf_csg import (
    SdfField, sdf_sphere, sdf_box, sdf_cylinder,
    sdf_union, sdf_subtract, sdf_intersect,
    marching_cubes,
)

sphere = sdf_sphere(0, 0, 0, r=10.0)
box    = sdf_box(0, 0, 5, hx=8, hy=8, hz=8)

# Smooth union with 3mm blend radius
shape = sdf_union(sphere, box, k=3.0)

# Extract mesh
result = marching_cubes(
    shape,
    bounds=((-20,-20,-20), (20,20,20)),
    resolution=64,
)
# result = {"vertices": [[x,y,z],...], "faces": [[i,j,k],...]}
```

## LLM tools

`feature_sdf_union`, `feature_sdf_subtract`, `feature_sdf_intersect`, `feature_marching_cubes`

## References

- Lorensen & Cline, "Marching Cubes: A High Resolution 3D Surface Construction Algorithm", *SIGGRAPH 1987*.
- Quilez, "Smooth minimum" (IQ exponential smoothing formula), iquilezles.org.

## Honest caveats

The marching-cubes implementation is pure Python and is slow for resolution > 128 — use resolution 64 for interactive feedback and 128 for final export. The resulting mesh contains T-junctions where the isovalue passes through a cube corner; run `mesh_repair` if a watertight mesh is needed for downstream BRep conversion. SDF fields do not automatically maintain exact Euclidean distance after CSG composition — smooth-blend fields are approximations.
