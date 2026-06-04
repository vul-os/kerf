# Quad Remeshing and Instant Meshes

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/quad_remesh.py` · Shipped: Wave 7*

## Overview

Remeshes a triangulated mesh to a semi-regular quad-dominant mesh using the Instant Meshes field-based approach (Jakob et al. 2015). Produces meshes suitable for SubD cage input, CAE structured-mesh conversion, and UV unwrapping. Also provides the `instant_meshes_runner.py` subprocess bridge for the standalone Instant Meshes binary when available.

## When to use

- Converting a scan mesh or simulation mesh into a quad cage for SubD editing.
- Generating a coarse quad layout for a structured hex mesh.
- Retopologising high-poly sculpts for animation or real-time use.

## API

```python
from kerf_cad_core.quad_remesh import (
    quad_remesh_options,
    remesh_to_quads,
    QuadRemeshResult,
)

result: QuadRemeshResult = remesh_to_quads(
    vertices=verts,       # list of [x,y,z]
    triangles=tris,       # list of [i,j,k]
    target_face_count=500,
    smooth_iter=5,
    align_to_boundary=True,
)

print(len(result.quads))   # number of quad faces
print(result.irregular_vertex_count)   # valence != 4 vertices
```

## LLM tools

`feature_quad_remesh`

## References

- Jakob et al., "Instant field-aligned meshes", *SIGGRAPH Asia 2015*, ACM TOG 34(6).

## Honest caveats

The pure-Python quad remesher is a simplified implementation of the orientation field + parametrisation approach. It does not replicate all the features of the Instant Meshes binary (e.g. cage-aligned field guiding, crease-preserving constraints). For production quad remeshing, the `instant_meshes_runner.py` subprocess bridge calls the native binary if installed. Results may contain triangles at extraordinary vertices.
