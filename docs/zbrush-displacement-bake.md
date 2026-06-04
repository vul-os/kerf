# Displacement Map Bake

> Bake a multi-layer displacement stack from a high-resolution sculpt to a 16-bit displacement map.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/mesh_displacement_stack.py`
**Shipped**: Wave 9B1
**LLM tools**: `sculpt_displacement_bake`

---

## What it is

Displacement baking samples the signed difference between a high-poly sculpt mesh and a low-poly base mesh along surface normals, storing the result as a floating-point displacement map. It mirrors ZBrush's "Displacement Map" export and Blender's "Bake → Displacement" workflow. The output is a 16-bit EXR or PNG that can drive displacement modifiers in Blender, Redshift, Arnold, or CNC machining tool paths.

## How to use it

### From chat

> "Bake a 4096×4096 displacement map from my high-res head sculpt to the base mesh."

### From Python

```python
from kerf_cad_core.mesh_displacement_stack import (
    DisplacementStackSpec, apply_displacement_stack,
)

spec = DisplacementStackSpec(
    base_vertices=base_v,
    base_faces=base_f,
    base_uvs=base_uv,
    layers=[
        {"high_poly_vertices": hi_v, "high_poly_faces": hi_f,
         "weight": 1.0, "space": "tangent"},
    ],
    texture_size=4096,
    bit_depth=16,
)
result = apply_displacement_stack(spec)
result.texture.save("displacement.exr")
print(result.min_disp_mm, result.max_disp_mm)
```

### From an LLM tool spec

```json
{"tool": "sculpt_displacement_bake", "input": {"texture_size": 4096, "bit_depth": 16, "space": "tangent"}}
```

## How it works

For each texel in the output image, the corresponding point on the base mesh surface is found via UV lookup. A ray is cast in the local surface-normal direction and the distance to the nearest high-poly surface intersection is recorded. Tangent-space displacement encodes the offset relative to the local TBN frame; world-space encodes it in object coordinates. Layers are composited additively with their weights before writing.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `apply_displacement_stack(spec)` | `DisplacementStackResult` | Baked displacement image and stats |
| `DisplacementStackSpec(...)` | instance | Spec for base mesh, layers, and output |
| `DisplacementLayer(...)` | instance | Single high-poly layer with weight and space |

## Example

```python
result = apply_displacement_stack(spec)
# DisplacementStackResult(texture=<PIL.Image 4096×4096>,
#                         min_disp_mm=-2.1, max_disp_mm=3.4)
```

## Honest caveats

Ray-casting accuracy depends on the proximity of the high-poly and base meshes; gaps larger than 5× the expected displacement magnitude may cause rays to miss. Overlapping UVs produce artefacts; ensure the base mesh has no overlapping UV islands. 8-bit displacement maps introduce quantisation banding on smooth surfaces; use 16-bit or 32-bit float output.

## References

- Cignoni et al., "Metro: Measuring error on simplified surfaces," *Comput. Graph. Forum* 17(2), 1998.
- Piponi, "Seamless texture mapping of subdivision surfaces," *SIGGRAPH* (2000).
