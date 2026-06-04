# ZBrush PolyPaint — Vertex Colour and UV Bake

> Paint RGBA colour directly onto mesh vertices, then bake to a UV texture map.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/sculpt/polypaint.py`
**Shipped**: Wave 9B1
**LLM tools**: `sculpt_polypaint`

---

## What it is

PolyPaint stores per-vertex RGBA colour channels on a mesh, mirroring ZBrush's PolyPaint workflow. Strokes are applied to a `PolyPaintLayer` with a brush radius and falloff. Once painting is complete, the vertex colours are baked into a UV-space texture image by rasterising each triangle's barycentric colour interpolation into the UV atlas. The output is a PNG texture ready for game engines, renderers, or manufacturing review.

## How to use it

### From chat

> "Paint a rust-coloured patch on my sculpt near vertex 4200, radius 15 mm, then bake to a 2048×2048 UV texture."

### From Python

```python
from kerf_cad_core.sculpt.polypaint import (
    PolyPaintLayer, polypaint_stroke, bake_polypaint_to_uv_texture,
)

layer = PolyPaintLayer(n_vertices=n_verts)

layer = polypaint_stroke(
    layer=layer,
    vertices=v,
    faces=f,
    center=v[4200],
    color=(0.72, 0.25, 0.05, 1.0),  # RGBA
    radius=0.015,   # metres
    falloff="smooth",
)
texture = bake_polypaint_to_uv_texture(layer, vertices=v, faces=f, uvs=uv, size=2048)
texture.save("diffuse.png")
```

### From an LLM tool spec

```json
{"tool": "sculpt_polypaint", "input": {"center_vertex": 4200, "color": [0.72, 0.25, 0.05, 1.0], "radius_mm": 15, "falloff": "smooth"}}
```

## How it works

`polypaint_stroke` finds all vertices within `radius` of the stroke centre using a KD-tree query and blends the stroke colour with the existing vertex colour using a smooth falloff weight (cubic or Gaussian). `bake_polypaint_to_uv_texture` rasterises each UV triangle into a pixel buffer, interpolating vertex colours barycentrically per pixel.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `polypaint_stroke(layer, vertices, faces, center, color, radius, falloff)` | `PolyPaintLayer` | Apply a paint stroke |
| `bake_polypaint_to_uv_texture(layer, vertices, faces, uvs, size)` | `PIL.Image` | Bake vertex colours to UV texture |
| `PolyPaintLayer(n_vertices)` | instance | Per-vertex RGBA colour store |

## Example

```python
layer = polypaint_stroke(layer, v, f, center=v[100], color=(1,0,0,1), radius=0.01)
texture = bake_polypaint_to_uv_texture(layer, v, f, uv, size=1024)
# PIL.Image of size 1024×1024 RGBA
```

## Honest caveats

PolyPaint resolution is limited by vertex density — low-poly meshes (< 50k verts) will show faceting in the baked texture. The bake does not support multiple UV tiles (UDIM); all geometry must fit within the [0, 1] UV square. Specular, roughness, and normal channels are not supported — polypaint is diffuse colour only.

## References

- Pixologic, *ZBrush PolyPaint* documentation (2023).
- Sander et al., "Texture Mapping Progressive Meshes," *SIGGRAPH* (2001).
