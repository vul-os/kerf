"""
pathtrace_tools.py — LLM tool for the in-process CPU Monte-Carlo path tracer.

Unlike `run_render` (which shells out to a Blender Cycles pyworker), this tool
runs a genuine unidirectional path tracer entirely in-process (kerf_render.
pathtracer) and returns a base64 PNG. It is the reference renderer behind the
"production render" toggle in the Hero Render panel.

The scene can be supplied three ways:
  * "preset": "cornell"  → built-in Cornell box (great for demos / validation).
  * "scene": {...}        → inline triangle/material/environment description.
  * mesh refs via "scene_file_id"  → (loaded as an OBJ-ish triangle soup).

It is intentionally capped on resolution/samples so a single call stays bounded.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_render import pathtracer as pt

# Safety caps so a single tool call stays bounded on CPU.
MAX_DIM = 256
MAX_SAMPLES = 256
MAX_DEPTH = 16


pathtrace_render_scene_spec = ToolSpec(
    name="pathtrace_render_scene",
    description=(
        "Render an image with Kerf's in-process CPU Monte-Carlo path tracer "
        "(multi-bounce global illumination: BVH acceleration, Moller-Trumbore "
        "ray/triangle, cosine-importance + GGX + dielectric Fresnel BSDFs, "
        "next-event estimation, Russian-roulette termination, ACES tonemap). "
        "Returns a base64-encoded PNG plus convergence stats. Use preset "
        "'cornell' for a validation scene, or pass an inline 'scene' of "
        "materials + triangles. Resolution and samples are capped for a single "
        "synchronous call."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "preset": {
                "type": "string",
                "enum": ["cornell"],
                "description": "Built-in scene. 'cornell' = Cornell box.",
            },
            "width": {"type": "integer", "description": f"Pixels, <= {MAX_DIM}."},
            "height": {"type": "integer", "description": f"Pixels, <= {MAX_DIM}."},
            "samples": {
                "type": "integer",
                "description": f"Samples per pixel, <= {MAX_SAMPLES}.",
            },
            "max_depth": {
                "type": "integer",
                "description": f"Max path bounces, <= {MAX_DEPTH}.",
            },
            "seed": {"type": "integer"},
            "scene": {
                "type": "object",
                "description": (
                    "Inline scene: {materials:[{kind,albedo,emission,roughness,"
                    "ior}], triangles:[{v:[[x,y,z]x3],material}], quads:[...], "
                    "environment:{top,bottom}}."
                ),
            },
            "camera": {
                "type": "object",
                "description": "{eye,look_at,up,vfov_deg}. Defaults to a Cornell view.",
            },
        },
        "required": [],
    },
)


@register(pathtrace_render_scene_spec, write=False)
async def pathtrace_render_scene(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    width = max(8, min(int(a.get("width", 128)), MAX_DIM))
    height = max(8, min(int(a.get("height", 128)), MAX_DIM))
    samples = max(1, min(int(a.get("samples", 64)), MAX_SAMPLES))
    max_depth = max(1, min(int(a.get("max_depth", 8)), MAX_DEPTH))
    seed = int(a.get("seed", 0))

    preset = a.get("preset")
    scene_dict = a.get("scene")

    if preset == "cornell" or (not scene_dict and not preset):
        scene = pt.build_cornell_box()
        default_cam = pt.cornell_camera(width, height)
    elif scene_dict:
        try:
            scene = pt.scene_from_dict(scene_dict)
        except Exception as e:
            return err_payload(f"invalid scene: {e}", "BAD_ARGS")
        default_cam = pt.cornell_camera(width, height)
    else:
        return err_payload(f"unknown preset: {preset}", "BAD_ARGS")

    if a.get("camera"):
        try:
            camera = pt.camera_from_dict(a["camera"], width, height)
        except Exception as e:
            return err_payload(f"invalid camera: {e}", "BAD_ARGS")
    else:
        camera = default_cam

    if not scene.tri_mat:
        return err_payload("scene has no triangles", "BAD_ARGS")

    fb = pt.render(scene, camera, width, height, samples,
                   max_depth=max_depth, seed=seed)
    img = fb.tonemapped_uint8()
    png_b64 = pt.encode_png_base64(img)

    mean = fb.mean()
    avg_luminance = float(mean.mean())
    peak = float(mean.max())

    return ok_payload({
        "status": "ok",
        "format": "png",
        "width": width,
        "height": height,
        "samples": fb.samples,
        "max_depth": max_depth,
        "triangles": len(scene.tri_mat),
        "emissive_triangles": len(scene.emissive_tris),
        "avg_luminance": avg_luminance,
        "peak_luminance": peak,
        "image_b64": png_b64,
        "engine": "kerf-cpu-pathtracer",
    })


TOOLS = [
    (pathtrace_render_scene_spec.name, pathtrace_render_scene_spec,
     pathtrace_render_scene),
]
