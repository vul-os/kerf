# Architectural Visualisation Rendering Pipeline

> Path-trace an architectural scene with physically based BRDFs, sky lighting, and tone-mapping — for presentation renders without an external GPU renderer.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/render/archviz_pipeline.py`
**Shipped**: Wave 9
**LLM tools**: `render_archviz`

---

## What it is

Architectural visualisation (archviz) requires physically based rendering: correct glossy reflections off polished floors, diffuse interreflection between coloured walls, transparent glass, and accurate sky lighting. This module provides a CPU path tracer for architectural scenes: triangulated geometry with per-face materials, sky and sun lighting, and a Reinhard tone-mapping output.

It is the embedded rendering path for Kerf projects — fast enough for preview renders (256×256 at 32 samples per pixel in seconds) and quality enough for presentation at 1920×1080 with 256 samples. The `make_simple_room_scene` helper bootstraps a test scene.

## How to use it

### From chat (natural language)

> "Render a 1024×768 perspective view of the living room at noon, 128 samples, tone-mapped"

The LLM calls `render_archviz` with the scene and render settings.

### From Python

```python
from kerf_cad_core.render.archviz_pipeline import (
    render_archviz, make_simple_room_scene, ArchVizScene,
)

scene = make_simple_room_scene()
image = render_archviz(
    scene=scene,
    width=1024, height=768,
    samples_per_pixel=64,
    sky_color=(0.53, 0.81, 0.98),
    camera_pos=(3, 2, 1.5),
    camera_target=(0, 0, 1),
)
# image is np.ndarray[H,W,3] float32, [0,1] tone-mapped
```

### From an LLM tool spec

```json
{"tool": "render_archviz", "scene_id": "living_room",
 "width": 1024, "height": 768, "samples": 64}
```

## How it works

The renderer uses unidirectional path tracing with explicit next-event estimation (direct light sampling). For each pixel, `samples_per_pixel` rays are traced from the camera through the scene. At each bounce, a material BRDF (Lambertian diffuse, Phong specular, or glass transmittance) determines the scattered direction. The sky hemisphere is sampled with cosine-weighted importance sampling. Russian roulette terminates paths after a minimum depth with probability proportional to throughput.

`_ray_triangle_intersect` uses the Möller-Trumbore algorithm for fast ray-triangle intersection.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `render_archviz(scene, width, height, samples_per_pixel, ...)` | `np.ndarray[H,W,3]` | Full path-traced render |
| `make_simple_room_scene()` | `ArchVizScene` | Test scene (box room + furniture) |

`ArchVizScene` fields: `triangles`, `materials`, `lights`, `camera`.

## Example

```python
scene = make_simple_room_scene()
img = render_archviz(scene, 512, 384, samples_per_pixel=32)
print(f"Rendered {img.shape} image, max pixel: {img.max():.3f}")
```

## Honest caveats

The CPU path tracer is single-threaded Python — 1920×1080 at 256 spp takes several minutes. Use 512×384 at 32 spp for interactive previews. The material model supports Lambertian diffuse and Phong specular only — no subsurface scattering, no anisotropic BRDFs. WebGPU-accelerated rendering (see `optics-webgpu-pathtracer`) is the production path for high-quality images.

## References

- Kajiya (1986). "The rendering equation." *SIGGRAPH* 1986.
- Möller & Trumbore (1997). "Fast, minimum storage ray-triangle intersection." *Journal of Graphics Tools* 2(1).
- Reinhard et al. (2002). "Photographic tone reproduction for digital images." *SIGGRAPH* 2002.
