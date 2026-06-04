# Stam Limit Tangents and Curvature

> Evaluate the exact Catmull-Clark limit position, tangent, and curvature at any cage vertex — including extraordinary vertices — using Stam's closed-form eigenvector method.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/subd/stam_limit_tangents.py`
**Shipped**: Wave 8
**LLM tools**: `feature_stam_limit_eval`

---

## What it is

Naively refining a Catmull-Clark mesh to many subdivision levels approximates the limit surface but never reaches it exactly, and breaks down at extraordinary vertices. Stam (1998) derived a closed-form formula that evaluates the exact limit position, tangent vectors, and curvature at any point — including extraordinary vertices — using the eigendecomposition of the local subdivision matrix.

This module implements those formulas. Engineers use it to extract accurate normal vectors at cage vertices for shading, to compute Gaussian and mean curvature at extraordinary points for quality checks, and as the foundation of the SubD-to-NURBS converter.

## How to use it

### From chat (natural language)

> "Compute the limit surface normals at all vertices of the organic handle cage"

The LLM calls `feature_stam_limit_eval` with the cage ID.

### From Python

```python
from kerf_cad_core.subd.stam_limit_tangents import (
    compute_stam_limit_tangents, LimitTangentReport,
)

report: LimitTangentReport = compute_stam_limit_tangents(
    mesh,               # SubDMesh with vertices and faces
    vertex_indices,     # list of vertex indices to evaluate
)

for i, vi in enumerate(vertex_indices):
    print(f"v{vi}: pos={report.positions[i]}, "
          f"T1={report.tangent1[i]}, T2={report.tangent2[i]}")
    print(f"       kG={report.gaussian_curvature[i]:.4f}, "
          f"kH={report.mean_curvature[i]:.4f}")
```

### From an LLM tool spec

```json
{"tool": "feature_stam_limit_eval", "cage_id": "handle", "vertex_ids": [0, 4, 12]}
```

## How it works

At a regular vertex (valence 4), the limit position and tangents are given by standard Catmull-Clark masks. At an extraordinary vertex of valence n, Stam's algorithm diagonalises the (2n+8)×(2n+8) local subdivision matrix and computes the limit as a linear combination of eigenvectors. The subdominant eigenvalue λ₁ determines the tangent magnitudes; its two associated eigenvectors span the tangent plane. Curvature is estimated from the cotangent-weighted Laplacian of the limit positions.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_stam_limit_tangents(mesh, vertex_indices)` | `LimitTangentReport` | Main evaluator |

`LimitTangentReport` fields: `positions`, `tangent1`, `tangent2`, `normal`, `gaussian_curvature`, `mean_curvature`.

`ExtraordinaryVertex` fields: `index`, `valence`, `subdominant_eigenvalue`.

## Example

```python
from kerf_cad_core.geom.subd_authoring import create_subd_primitive
from kerf_cad_core.subd.stam_limit_tangents import compute_stam_limit_tangents

cage = create_subd_primitive("cube", w=1.0, h=1.0, d=1.0)
rpt = compute_stam_limit_tangents(cage, vertex_indices=list(range(8)))
print(f"Corner kG: {rpt.gaussian_curvature[0]:.4f}")  # non-zero at extraordinary corner
```

## Honest caveats

Stam's formula is exact only for the standard Catmull-Clark scheme without creases. Creased edges change the local subdivision matrix; use `fractional_crease.py` for those cases. Curvature estimates at extraordinary vertices are approximations based on the cotangent Laplacian, not the exact limit curvature (which requires the second-order subdivision matrix).

## References

- Stam (1998). "Exact evaluation of Catmull-Clark subdivision surfaces at arbitrary parameter values." *SIGGRAPH* 1998.
- Catmull & Clark (1978). "Recursively generated B-spline surfaces on arbitrary topological meshes." *CAD* 10(6).
