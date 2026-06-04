# Multi-Resolution Displacement Sculpting

> Layer fine-detail displacement maps onto a SubD mesh in a ZBrush-style pyramid — sculpt at any resolution level without losing detail at other levels.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/multires_displacement.py`
**Shipped**: Wave 8
**LLM tools**: `feature_multires_evaluate`, `feature_multires_apply`

---

## What it is

Multi-resolution displacement sculpting separates geometric detail by scale: the coarse cage controls global shape, intermediate levels add secondary form, and the finest level holds surface texture or micro-detail. Editing at one level does not disturb detail stored at other levels, unlike flat mesh sculpting where each brush stroke obliterates all pre-existing detail.

This module implements a displacement pyramid: an ordered stack of `DisplacementMap` layers, one per subdivision level, each storing per-vertex signed displacements in the surface normal direction. `encode_pyramid` builds the pyramid from a set of progressively subdivided maps; `decode_pyramid` reconstructs the full-detail mesh from any subset of levels; `build_multires_maps` extracts per-level detail from a high-resolution reference mesh.

## How to use it

### From chat (natural language)

> "Apply the base displacement map at level 0 and the detail map at level 2 to the hull mesh"

The LLM calls `feature_multires_apply` with the pyramid and level selection.

### From Python

```python
from kerf_cad_core.geom.multires_displacement import (
    DisplacementMap, encode_pyramid, decode_pyramid,
    apply_displacement, build_multires_maps,
)

# Build pyramid from per-level displacement maps
pyramid = encode_pyramid([map_level0, map_level1, map_level2])

# Reconstruct mesh at level 1 (coarse + medium detail)
disp = decode_pyramid(pyramid, level=1)

# Apply displacement to a SubD mesh
displaced_mesh = apply_displacement(base_mesh, disp)
```

### From an LLM tool spec

```json
{"tool": "feature_multires_apply", "mesh_id": "hull",
 "pyramid_id": "hull_sculpt", "levels": [0, 1, 2]}
```

## How it works

Each level stores displacement values relative to the subdivided mesh at that level — not absolute positions. When decoding, the pyramid is applied bottom-up: the coarse mesh is first displaced by level 0, then subdivided, then displaced by level 1, and so on. `build_multires_maps` reverses this: it subdivides the cage to each level and extracts the difference between the reference mesh and the smooth subdivision, storing it as the per-level displacement map.

UV coordinates are computed via the Stam limit parametrisation (for SubD meshes) or from vertex barycentric projection (for general meshes).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `encode_pyramid(maps)` | `DisplacementPyramid` | Build pyramid from level maps |
| `decode_pyramid(pyramid, level)` | `DisplacementMap` | Reconstruct map at given level |
| `apply_displacement(mesh, disp_map)` | `SubDMesh` | Apply displacement to mesh |
| `extract_displacement(mesh, reference)` | `DisplacementMap` | Extract disp from reference |
| `build_multires_maps(cage, reference, levels)` | `DisplacementPyramid` | Full pyramid from hi-res reference |

`DisplacementMap` fields: `samples` (n×m float array), `level`, `width`, `height`.

## Example

```python
pyramid = build_multires_maps(cage, hi_res_scan, levels=3)
print(f"Level 2 map: {pyramid.levels[2].width}×{pyramid.levels[2].height} samples")
low_detail = decode_pyramid(pyramid, level=0)
full_detail = decode_pyramid(pyramid, level=2)
```

## Honest caveats

`DisplacementPyramid` stores per-vertex delta lists — coarse-to-fine projection is the caller's responsibility when editing at intermediate levels. UV generation uses centroid-based projection for meshes without explicit UV maps, which can produce seam discontinuities on high-curvature regions. Displacement maps are normal-direction only; tangential displacement requires the full vector-displacement variant (not yet implemented).

## References

- Cignoni, Rocchini & Scopigno (1998). "Metro: Measuring error on simplified surfaces." *Computer Graphics Forum* 17(2).
- Lee, Moreton & Hoppe (2000). "Displaced subdivision surfaces." *SIGGRAPH* 2000.
