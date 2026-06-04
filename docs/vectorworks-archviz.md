# Architectural Visualisation Renderer

> Path-trace a room or building scene for design review renders directly from geometry.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/render/archviz_pipeline.py`
**Shipped**: Wave 9B3
**LLM tools**: `render_archviz_scene`

---

## What it is

The archviz renderer is a CPU-based path tracer for architectural interior and exterior scenes. It takes an `ArchVizScene` (geometry, materials with BRDF parameters, camera, sky model) and produces a photorealistic render. The renderer uses Monte Carlo path tracing with Russian roulette termination — suitable for design-review images in the style of Vectorworks Renderworks.

## How to use it

### From chat

> "Render the living room scene with 128 samples per pixel and a warm 4000K sky."

### From Python

```python
from kerf_cad_core.render.archviz_pipeline import (
    ArchVizScene, render_archviz, make_simple_room_scene,
)

scene = make_simple_room_scene(
    room_dims=(5.0, 4.0, 2.8),  # W × D × H, metres
    window_size=(1.5, 1.2),
    sky_color=(1.0, 0.95, 0.85),
)
scene.camera = {"origin": (2.5, -0.5, 1.2), "target": (2.5, 3.5, 1.2)}

img = render_archviz(scene, width=1280, height=720, samples=128)
img.save("living_room.png")
```

### From an LLM tool spec

```json
{"tool": "render_archviz_scene", "input": {"scene_json": {...}, "width": 1280, "height": 720, "samples": 64}}
```

## How it works

The renderer shoots `samples` rays per pixel from the camera origin through the image plane. Each ray is traced against the scene triangles using a brute-force intersection loop (no BVH). On hit, a new ray is sampled from the material BRDF (Lambertian diffuse or Phong specular). Russian roulette terminates paths with probability proportional to the estimated remaining contribution. Sky contribution is sampled from a directional gradient model.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `render_archviz(scene, width, height, samples)` | `PIL.Image` | Path-traced render |
| `make_simple_room_scene(...)` | `ArchVizScene` | Build a simple box-room scene |
| `ArchVizScene(...)` | instance | Scene geometry, materials, camera |

## Example

```python
img = render_archviz(scene, width=640, height=480, samples=32)
# PIL.Image RGBA, 640×480 — ~15 s at 32 spp on a 6-core CPU
```

## Honest caveats

The brute-force intersection loop scales as O(rays × triangles) — complex scenes with > 50k triangles will be very slow without a BVH acceleration structure. At < 256 samples per pixel the image will exhibit visible Monte Carlo noise. Global illumination is physically correct (energy-conserving) but caustics from specular reflections converge slowly. This renderer is for design review, not final-quality production rendering.

## References

- Pharr, Jakob & Humphreys, *Physically Based Rendering*, 4th ed. (2023).
- Kajiya, "The Rendering Equation," *SIGGRAPH* (1986).
