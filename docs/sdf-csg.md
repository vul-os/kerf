# SDF CSG and Marching Cubes

> Blend, subtract, and intersect signed-distance fields with smooth k-blending, then extract a triangle mesh via marching cubes — implicit modelling without BRep.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/sdf_csg.py`
**Shipped**: Wave 7 (GK-P22)
**LLM tools**: `feature_sdf_union`, `feature_sdf_subtract`, `feature_sdf_intersect`, `feature_marching_cubes`

---

## What it is

A signed-distance field (SDF) assigns to every point in space its signed distance to a surface — negative inside, positive outside. SDF-based modelling lets you build complex shapes from simple primitives combined with smooth boolean operations, avoiding the topological bookkeeping of BRep.

This module provides SDF primitives (sphere, box, cylinder), smooth CSG operators (union, subtract, intersect), and a Lorensen-Cline marching-cubes extractor that converts an SDF to a triangle mesh. Smooth-union with blend radius `k > 0` produces a fillet-like blend between two shapes without any explicit fillet geometry, matching ZBrush DynaMesh and Blender geometry nodes in capability. All operations are pure Python + NumPy; no OCCT is required.

## How to use it

### From chat (natural language)

> "Create a sphere of radius 10 smoothly blended with a box at the top, blend radius 3mm, then extract a mesh at resolution 64"

The LLM calls `feature_sdf_union` with `k=3.0` then `feature_marching_cubes`.

### From Python

```python
from kerf_cad_core.geom.sdf_csg import (
    sdf_sphere, sdf_box, sdf_cylinder,
    sdf_union, sdf_subtract, sdf_intersect,
    marching_cubes,
)

sphere = sdf_sphere(0, 0, 0, r=10.0)
box    = sdf_box(0, 0, 5, hx=8, hy=8, hz=8)

blended = sdf_union(sphere, box, k=3.0)  # smooth blend
result  = marching_cubes(
    blended,
    bounds=((-20,-20,-20), (20,20,20)),
    resolution=64,
)
print(len(result["vertices"]))  # triangle mesh vertices
```

### From an LLM tool spec

```json
{"tool": "feature_sdf_union", "a_id": "sphere1", "b_id": "box1", "k": 3.0}
```

## How it works

SDF primitives are Python callables that return the signed distance at any 3-D point. CSG operations compose them: `sdf_union(a, b)` returns `min(a(p), b(p))`; smooth union replaces `min` with the exponential smooth-min of Quilez: `smin(a, b, k) = -log(exp(-a/k) + exp(-b/k)) * k`. Marching cubes evaluates the field on a regular grid, classifies each cube's 8 corners as inside/outside, and produces triangles from the 256-case look-up table (Lorensen & Cline 1987).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `sdf_sphere(cx, cy, cz, r)` | `SdfField` | Sphere primitive |
| `sdf_box(cx, cy, cz, hx, hy, hz)` | `SdfField` | Axis-aligned box |
| `sdf_cylinder(cx, cy, cz, r, h)` | `SdfField` | Cylinder |
| `sdf_union(a, b, k)` | `SdfField` | Union (smooth if k>0) |
| `sdf_subtract(a, b, k)` | `SdfField` | Boolean subtract |
| `sdf_intersect(a, b, k)` | `SdfField` | Boolean intersect |
| `marching_cubes(field, bounds, resolution)` | `dict` | Extract triangle mesh |

`marching_cubes` returns `{"vertices": List[List[float]], "faces": List[List[int]]}`.

## Example

```python
s = sdf_sphere(0, 0, 0, r=5.0)
c = sdf_cylinder(0, 0, 0, r=3.0, h=12.0)
holed = sdf_subtract(s, c, k=0.0)
mesh = marching_cubes(holed, bounds=((-6,-6,-6),(6,6,6)), resolution=48)
print(f"{len(mesh['faces'])} triangles")
```

## Honest caveats

The marching-cubes extractor is pure Python — resolution > 128 becomes slow (tens of seconds). Use 64 for interactive preview, 128 for final export. Smooth-blend fields (`k > 0`) are approximations; they do not maintain exact Euclidean distance after composition. The resulting mesh may have T-junction vertices; run mesh repair before BRep conversion or FEA meshing.

## References

- Lorensen & Cline (1987). "Marching Cubes: A high-resolution 3D surface construction algorithm." *SIGGRAPH* 1987.
- Quilez (2013). "Smooth minimum." iquilezles.org.
