# Quad Remeshing

> Convert a triangulated scan or simulation mesh to a semi-regular quad-dominant mesh — suitable for SubD cage editing, structured hex meshing, and UV unwrapping.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/quad_remesh.py`
**Shipped**: Wave 7
**LLM tools**: `feature_quad_remesh`

---

## What it is

Scan meshes and CFD surface meshes are triangulated, often irregularly. Downstream operations — SubD cage editing, structured hex meshing, UV layout for rendering — work better with quad-dominant meshes aligned to the surface curvature. Quad remeshing converts an arbitrary triangle mesh into such a layout.

Kerf implements a simplified version of the field-based approach: a smooth cross-field is computed over the surface aligned to principal curvature directions, then a global parametrisation snaps mesh edges to field isolines, producing a quad-dominant mesh with a user-controlled target face count. The `instant_meshes_runner.py` subprocess bridge can call the native Instant Meshes binary if installed, which gives higher quality for complex shapes.

## How to use it

### From chat (natural language)

> "Remesh the imported scan to a 500-face quad mesh for SubD editing"

The LLM calls `feature_quad_remesh` with the mesh ID and target face count.

### From Python

```python
from kerf_cad_core.quad_remesh import remesh_to_quads, QuadRemeshResult

result: QuadRemeshResult = remesh_to_quads(
    vertices=verts,           # List[List[float]]
    triangles=tris,           # List[List[int]]
    target_face_count=500,
    smooth_iter=5,
    align_to_boundary=True,
)

print(f"{len(result.quads)} quads, {result.irregular_vertex_count} extraordinary vertices")
```

### From an LLM tool spec

```json
{"tool": "feature_quad_remesh", "mesh_id": "scan_body",
 "target_face_count": 500, "smooth_iter": 5}
```

## How it works

The algorithm operates in two phases. First, a smooth cross-field (4-RoSy field) is computed over the mesh by minimising a Dirichlet energy that penalises misalignment between adjacent face frames, optionally guided by principal curvature directions. Second, a global integer-grid parametrisation snaps the cross-field to integer isolines using a mixed-integer formulation; the resulting grid lines define the quad faces.

Extraordinary vertices (valence ≠ 4) arise where the field has singularities — their count is minimised by the field smoothing but cannot be avoided for genus ≥ 0 surfaces.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `remesh_to_quads(vertices, triangles, target_face_count, smooth_iter, align_to_boundary)` | `QuadRemeshResult` | Main remesher |
| `quad_remesh_options()` | `dict` | Default parameter dict |

`QuadRemeshResult` fields: `vertices`, `quads`, `irregular_vertex_count`, `tri_remainder` (quads that remain triangles).

## Example

```python
result = remesh_to_quads(scan_verts, scan_tris, target_face_count=200, smooth_iter=3)
print(f"Irregular vertices: {result.irregular_vertex_count}")
# Feed result into subd_authoring
from kerf_cad_core.geom.subd_authoring import SubDCage
cage = SubDCage(vertices=result.vertices, faces=result.quads)
```

## Honest caveats

The pure-Python implementation is a simplified field approach and does not replicate all features of the Instant Meshes binary (cage-aligned field guiding, crease constraints). For production work, install the Instant Meshes binary and use `instant_meshes_runner.py` to call it as a subprocess. Results near sharp features may include triangles at valence-5 extraordinary vertices — set `align_to_boundary=True` to improve boundary alignment.

## References

- Jakob, Tarini, Panozzo & Sorkine-Hornung (2015). "Instant field-aligned meshes." *ACM TOG* (SIGGRAPH Asia) 34(6).
