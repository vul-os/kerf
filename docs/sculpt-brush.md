# Mesh Sculpt Brushes

> Grab, smooth, inflate, and pinch mesh vertices interactively with radial falloff brushes — direct geometric manipulation without cage constraints.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/mesh_sculpt_brushes.py`
**Shipped**: Wave 8
**LLM tools**: `feature_sculpt_brush`

---

## What it is

Sculpt brushes let engineers and designers push and pull mesh geometry directly, bypassing the cage-based editing model. Each brush applies a spatially localised deformation to vertices within a radius, weighted by a smooth falloff kernel. Four modes cover the main sculpting operations: grab (translate vertices along a direction), smooth (Laplacian fairing to reduce noise), inflate (displace along vertex normals), and pinch (pull vertices toward the brush centre).

This module is used for direct mesh editing — fixing import artefacts, adding organic detail to a SubD mesh, or touching up a remeshed scan. It operates on any vertex-face mesh, not only SubD cages.

## How to use it

### From chat (natural language)

> "Grab the top vertices of the fender mesh, radius 20mm, strength 0.4, direction [0,0,1]"

The LLM calls `feature_sculpt_brush` with mode `grab`.

### From Python

```python
from kerf_cad_core.mesh_sculpt_brushes import apply_sculpt_brush, SculptStroke

stroke = SculptStroke(
    center=(0.0, 0.0, 30.0),   # brush centre in 3D space
    radius=20.0,                 # influence radius (mm)
    mode="grab",                 # "grab" | "smooth" | "inflate" | "pinch"
    direction=(0.0, 0.0, 1.0),  # for grab/inflate
    strength=0.4,
)
result = apply_sculpt_brush(mesh, stroke)
modified_verts = result.vertices
```

### From an LLM tool spec

```json
{"tool": "feature_sculpt_brush", "mesh_id": "fender",
 "center": [0,0,30], "radius": 20, "mode": "grab",
 "direction": [0,0,1], "strength": 0.4}
```

## How it works

Vertices within `radius` of `center` receive a displacement weighted by the Wendland C² radial basis function `w(r) = (1-r/R)⁴(4r/R + 1)`. This kernel is smooth, compactly supported, and gives zero weight at the boundary, preventing discontinuities.

- **Grab**: displaces vertices by `strength * w(r) * direction`.
- **Smooth**: replaces each vertex position with a weighted average of its neighbours (cotangent-weighted Laplacian), controlled by `strength`.
- **Inflate**: displaces along the vertex normal by `strength * w(r)`.
- **Pinch**: moves vertices toward the brush centre by `strength * w(r) * (center - vertex)`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `apply_sculpt_brush(mesh, stroke)` | `MeshSculptResult` | Apply one brush stroke |

`SculptStroke` fields: `center`, `radius`, `mode`, `direction`, `strength`.
`MeshSculptResult` fields: `vertices`, `faces` (unchanged), `n_affected`.

## Example

```python
from kerf_cad_core.mesh_sculpt_brushes import apply_sculpt_brush, SculptStroke

stroke = SculptStroke(center=(0,0,0), radius=5.0, mode="smooth", strength=0.3)
result = apply_sculpt_brush(noisy_mesh, stroke)
print(f"Smoothed {result.n_affected} vertices")
```

## Honest caveats

`apply_sculpt_brush` returns an unmodified copy on invalid input — it never raises. The smooth mode uses one Taubin pass per call (λ=+0.5, μ=-0.53); for aggressive smoothing, call it multiple times. Sculpt brushes operate on flat vertex lists — they do not maintain SubD cage topology. For cage-based sculpting that preserves SubD structure, use `subd_deform` in `subd_authoring.py`.

## References

- Botsch & Kobbelt (2004). "An intuitive framework for real-time freeform modeling." *SIGGRAPH* 2004.
- Taubin (1995). "A signal processing approach to fair surface design." *SIGGRAPH* 1995.
