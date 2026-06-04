# ZBrush DynaMesh-Style Remeshing

> Remesh a sculpted mesh to uniform triangle density using voxel-based isosurface extraction.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/sculpt/dynamesh.py`
**Shipped**: Wave 9B1
**LLM tools**: `sculpt_remesh`

---

## What it is

DynaMesh-style remeshing converts a high-detail sculpt mesh of arbitrary topology into a uniformly-tessellated closed mesh by voxelising the input at a user-defined resolution, then extracting the isosurface with Marching Cubes. The result has no poles, no seams, and uniform polygon density — equivalent to pressing DynaMesh in ZBrush at a chosen resolution grid.

## How to use it

### From chat

> "Remesh my character head at resolution 256 — I want uniform topology before adding detail."

### From Python

```python
from kerf_cad_core.sculpt.dynamesh import dynamesh_remesh

result = dynamesh_remesh(
    vertices=v,      # (N, 3) float array
    faces=f,         # (M, 3) int array
    resolution=256,  # voxel grid dimension
    smooth_iter=2,   # optional Laplacian smoothing passes
)
print(result["n_vertices"], result["n_faces"])
```

### From an LLM tool spec

```json
{"tool": "sculpt_remesh", "input": {"resolution": 256, "smooth_iter": 2}}
```

## How it works

The mesh is voxelised by rasterising each triangle into a 3-D binary occupancy grid at `resolution³` cells. An inside/outside determination using ray casting fills the interior. Marching Cubes (Lorensen & Cline, 1987) extracts the isosurface as a triangle mesh. Optional Laplacian smoothing (cotangent weights, 1–3 passes) reduces Marching Cubes staircase artefacts while preserving volume.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `dynamesh_remesh(vertices, faces, resolution, smooth_iter)` | `dict` | Remeshed vertices and faces |

## Example

```python
result = dynamesh_remesh(v, f, resolution=128)
# {'vertices': array(...), 'faces': array(...),
#  'n_vertices': 42301, 'n_faces': 84600}
```

## Honest caveats

Voxel remeshing is destructive: all existing UV maps, vertex colours, and crease edges are discarded. Resolution controls the polygon budget — at 256 a typical head produces ~160k triangles; at 512 it is ~640k. Memory usage scales as O(resolution³); above 512 the voxel grid exceeds 1 GB. Sharp features thinner than one voxel (e.g., knife edges, ear rims) may be lost or rounded.

## References

- Lorensen & Cline, "Marching cubes: A high resolution 3D surface construction algorithm," *SIGGRAPH* (1987).
- Carr et al., "Reconstruction and Representation of 3D Objects," *SIGGRAPH* (2001).
