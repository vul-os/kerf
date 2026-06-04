# Apparel Avatar and Pattern Flattening

> Flatten a 3-D garment draped on an avatar into production-ready 2-D pattern pieces — CLO3D-parity workflow.

**Module**: `packages/kerf-apparel/src/kerf_apparel/pattern_flatten.py`
**Shipped**: Wave 10
**LLM tools**: `apparel_flatten_pattern`

---

## What it is

Pattern flattening unfolds a triangulated 3-D garment mesh (as produced by a cloth simulator or avatar drape) into flat 2-D pattern pieces, minimising both stretching and shearing distortion. The algorithm mirrors the CLO3D "2D pattern from 3D" workflow: it computes a low-distortion UV parameterisation using conformal energy, then scales it to preserve physical area.

## How to use it

### From chat

> "Flatten the bodice front panel from my avatar drape into a 2-D pattern piece."

### From Python

```python
from kerf_apparel.pattern_flatten import TriMesh, flatten_pattern_piece

mesh = TriMesh(
    vertices=v,   # (N, 3) float array, metres
    faces=f,      # (M, 3) int array
)
result = flatten_pattern_piece(mesh, method="arap")
print(result.distortion_mean, result.area_error_pct)
# result.uv  — (N, 2) flat pattern coordinates
```

### From an LLM tool spec

```json
{"tool": "apparel_flatten_pattern", "input": {"mesh_json": {"vertices": [...], "faces": [...]}, "method": "arap"}}
```

## How it works

The `arap` (As-Rigid-As-Possible) method minimises the cotangent-weighted conformal energy over the UV layout using a global Laplacian step followed by local rigid fitting per-triangle. A scaling pass normalises the UV area to match the 3-D surface area so the printed pattern is dimensionally correct. Boundary seams are identified from the mesh boundary loops and preserved as straight or curved grain lines.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `flatten_pattern_piece(mesh, method)` | `FlattenResult` | 2-D UV coordinates and distortion metrics |
| `TriMesh(vertices, faces)` | `TriMesh` | 3-D triangulated mesh container |

## Example

```python
result = flatten_pattern_piece(mesh, method="arap")
# FlattenResult(distortion_mean=0.031, area_error_pct=0.4,
#               uv=array([[...], ...]), seam_loops=[[0,1,2,...]])
```

## Honest caveats

ARAP flattening minimises distortion but cannot achieve zero distortion for doubly-curved (non-developable) surfaces like a bust cup. The area-correction scaling is global; local area errors may remain near high-curvature regions. The method assumes a single connected mesh panel; multi-panel garments must be split before flattening. Grain-line orientation is inferred from the longest boundary edge, which may not match the fabric warp direction.

## References

- Liu et al., "A Local/Global Approach to Mesh Parameterization," *SGP* (2008).
- Sorkine & Alexa, "As-rigid-as-possible surface modeling," *SGP* (2007).
