# SubD Cage Authoring

> Build, edit, and crease Catmull-Clark cage geometry with extrude, bevel, loop-cut, and sculpt — the organic-modelling layer under Kerf's NURBS pipeline.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/subd_authoring.py`
**Shipped**: Wave 7 (GK-P45)
**LLM tools**: `feature_subd_poke`, `feature_subd_extrude_along`, `feature_sculpt_brush`, `feature_multires_evaluate`

---

## What it is

Subdivision surfaces let designers sculpt smooth organic shapes from a low-polygon cage. The Catmull-Clark algorithm refines each quad face into four child quads per subdivision level, smoothing vertices by weighted averages of their neighbours. The limit surface is smooth G1 everywhere except at extraordinary vertices (valence ≠ 4).

This module provides the full cage-editing toolkit: create primitives (box, cylinder, sphere, torus), extrude faces, bevel edges, insert loop cuts, split edges, set fractional crease weights, poke faces, sculpt with grab/smooth/inflate brushes, and build multi-resolution displacement stacks. It is the authoring layer; the companion `subd-to-nurbs` converter takes the finished cage to exact NURBS patches.

## How to use it

### From chat (natural language)

> "Extrude the top face of the box 1.5m and add a 0.8 crease weight on edge 5"

The LLM calls `feature_subd_extrude_along` then `feature_sculpt_brush` (or sets creases via `feature_subd_poke`).

### From Python

```python
from kerf_cad_core.geom.subd_authoring import (
    create_subd_primitive, subd_extrude, subd_loop_cut,
    subd_set_crease, subd_bevel, subd_poke,
)

cage = create_subd_primitive("cube", w=2.0, h=2.0, d=2.0)
cage = subd_extrude(cage, face_id=4, offset=1.5)
cage = subd_loop_cut(cage, edge_id=2)
cage = subd_set_crease(cage, edge_id=5, weight=0.8)
cage = subd_bevel(cage, edge_id=3, width=0.1, segments=2)
```

### From an LLM tool spec

```json
{"tool": "feature_subd_extrude_along", "face_id": 4, "direction": [0,1,0], "distance": 1.5}
```

## How it works

Catmull-Clark subdivision applies three rules per level: face point = centroid of face vertices; edge point = average of the two adjacent face points and the two endpoint positions; vertex point = weighted blend of face points, edge midpoints, and the original position (weights depend on valence n). Crease handling blends the sharp edge-point rule with the smooth rule by the crease weight (DeRose et al. 1998).

Sculpt brushes apply a spatial falloff (Wendland C² radial basis) to vertex displacements within the brush radius, with per-mode operators: grab displaces along a direction, smooth applies Laplacian fairing, inflate displaces along vertex normals.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `create_subd_primitive(kind, **dims)` | `SubDCage` | Box, cylinder, sphere, torus |
| `subd_extrude(cage, face_id, offset)` | `SubDCage` | Extrude face along normal |
| `subd_loop_cut(cage, edge_id)` | `SubDCage` | Insert edge loop |
| `subd_bevel(cage, edge_id, width, segments)` | `SubDCage` | Bevel edge |
| `subd_set_crease(cage, edge_id, weight)` | `SubDCage` | Crease sharpness 0–1 |
| `subd_poke(cage, face_id)` | `SubDCage` | Fan-triangulate face |

## Example

```python
cage = create_subd_primitive("sphere", r=1.0, su=8, sv=6)
cage = subd_loop_cut(cage, edge_id=0)
cage = subd_set_crease(cage, edge_id=0, weight=1.0)
print(len(cage.faces))  # original faces + loop-inserted faces
```

## Honest caveats

`sculpt_brush` returns an unmodified copy on invalid input — it never raises. `MultiresStack` displacement maps are per-vertex delta lists; coarse-to-fine projection is the caller's responsibility. Loop subdivision (`loop_subdivide`) targets triangle meshes; Catmull-Clark is for quad cages. Extraordinary vertices produce G1 (not G2) limit surfaces, so keep them away from curvature-critical regions in Class-A work.

## References

- Catmull & Clark (1978). "Recursively generated B-spline surfaces on arbitrary topological meshes." *CAD* 10(6).
- DeRose, Kass & Truong (1998). "Subdivision surfaces in character animation." *SIGGRAPH* 1998.
