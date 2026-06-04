# SubD Cage to NURBS Body

> Convert an organic Catmull-Clark cage to a watertight NURBS body for STEP export, FEA meshing, or machining — one bicubic patch per quad face.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/mesh_to_nurbs.py`
**Shipped**: Wave 7 (GK-P12/P13)
**LLM tools**: `feature_subd_to_nurbs`, `feature_subd_limit_convert`

---

## What it is

After authoring an organic shape as a SubD cage, engineers often need exact NURBS geometry for downstream manufacturing: STEP export, FEA meshing, or tolerance analysis. This module converts a quad-mesh SubD cage to a watertight NURBS Body by fitting one bicubic patch per quad face using Catmull-Clark-derived Stam limit positions.

Extraordinary vertices (valence ≠ 4) are handled via the closed-form Stam (1998) limit formula, which evaluates the exact limit surface position and tangents at any cage vertex. The resulting patches are sewn into a closed shell; shared edge curves are compared and the gap-closing sew operation enforces positional continuity to the specified tolerance.

## How to use it

### From chat (natural language)

> "Convert the SubD cage to a NURBS body for STEP export, tolerance 1e-5"

The LLM calls `feature_subd_to_nurbs` with the cage ID and tolerance.

### From Python

```python
from kerf_cad_core.geom.mesh_to_nurbs import (
    mesh_to_nurbs_strips, quad_to_bicubic_patch,
)

# Convert a full quad mesh to a set of NURBS strip patches
strips = mesh_to_nurbs_strips(cage, tol=1e-6)

# Convert a single quad face to a bicubic patch
patch = quad_to_bicubic_patch(verts, quad_face, neighbours)
```

### From an LLM tool spec

```json
{"tool": "feature_subd_to_nurbs", "cage_id": "organic_handle", "tol": 1e-5}
```

## How it works

Each quad face is converted to a bicubic Hermite patch using the Stam limit positions as the four corner points and the Stam limit tangent vectors as the Hermite derivatives at each corner. The bicubic Hermite coefficients are transformed to NURBS control points via the standard conversion (4×4 linear map). Shared edges between adjacent patches are compared in parameter space; patches with gap > `sew_tol` have their boundary rows adjusted via a G0 seam-close pass.

Stam's algorithm computes the exact limit position at an extraordinary vertex as a weighted sum of the 2n+8 surrounding vertices (n = valence) using the eigenvectors of the subdivision matrix.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `mesh_to_nurbs_strips(cage, tol)` | `List[NurbsSurface]` | Convert quad mesh to NURBS strips |
| `quad_to_bicubic_patch(verts, face, neighbours)` | `NurbsSurface` | Single quad → bicubic patch |

## Example

```python
from kerf_cad_core.geom.subd_authoring import create_subd_primitive
from kerf_cad_core.geom.mesh_to_nurbs import mesh_to_nurbs_strips

cage = create_subd_primitive("cube", w=1.0, h=1.0, d=1.0)
patches = mesh_to_nurbs_strips(cage, tol=1e-5)
print(f"{len(patches)} NURBS patches generated")  # 6 for a cube
```

## Honest caveats

G1 continuity across shared edges at extraordinary vertices is enforced, but G2 curvature continuity is not guaranteed at extraordinary points. For engineering-grade fillets, convert the cage to NURBS and then use `match_surface_edge` to enforce G2 locally. Very irregular cages (many extraordinary vertices close together) can produce poor patch shapes.

## References

- Stam (1998). "Exact evaluation of Catmull-Clark subdivision surfaces at arbitrary parameter values." *SIGGRAPH* 1998.
- Catmull & Clark (1978). "Recursively generated B-spline surfaces on arbitrary topological meshes." *CAD* 10(6).
