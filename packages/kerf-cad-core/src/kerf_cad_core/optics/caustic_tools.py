"""
kerf_cad_core.optics.caustic_tools — Wave 8 LLM tool for photon-map caustic rendering.

Wave 8 modules
--------------
  kerf_cad_core.optics.photon_map    — Jensen 1996 photon tracing
  kerf_cad_core.optics.caustic_solver — Pass 2 caustic gather onto image plane

Tool registered
---------------
  optics_render_caustic — Trace photons through a glass sphere + floor scene
    and render the caustic pattern on the floor plane.

Scene (fixed v1): point light above, glass sphere in centre, floor plane below.
The LLM controls light position, sphere position/radius/glass material,
image-plane position/size, and photon count.

References
----------
Jensen, H.W. (1996). "Global Illumination Using Photon Maps." EGWR, pp. 21–30.
Jensen, H.W. (2001). "Realistic Image Synthesis Using Photon Mapping." A K Peters.
Sellmeier, W. (1871). Annalen der Physik 219(6):272–282.
"""
from __future__ import annotations

import json
import math

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.optics.photon_map import (
    Light,
    PhotonMap,
    RefractiveMaterial,
    emit_photons,
    material_from_glass,
    trace_photons,
)
from kerf_cad_core.optics.caustic_solver import render_caustic


# ---------------------------------------------------------------------------
# Simple scene intersector: glass sphere + floor plane
# ---------------------------------------------------------------------------

def _make_sphere_floor_scene(
    sphere_center: np.ndarray,
    sphere_radius: float,
    material: RefractiveMaterial,
    floor_y: float,
):
    """Return a scene_intersect callable for a glass sphere above a floor plane."""

    def scene_intersect(origin: np.ndarray, direction: np.ndarray):
        # Ray: P = origin + t * direction

        # ── Sphere intersection ────────────────────────────────────────────
        oc = origin - sphere_center
        a = float(np.dot(direction, direction))
        b = 2.0 * float(np.dot(oc, direction))
        c = float(np.dot(oc, oc)) - sphere_radius ** 2
        disc = b * b - 4.0 * a * c

        t_sphere = math.inf
        hit_inside = False
        if disc >= 0.0:
            sq = math.sqrt(disc)
            t1 = (-b - sq) / (2.0 * a)
            t2 = (-b + sq) / (2.0 * a)
            if t1 > 1e-4:
                t_sphere = t1
            elif t2 > 1e-4:
                t_sphere = t2
                hit_inside = True

        # ── Floor plane intersection (y = floor_y) ─────────────────────────
        t_floor = math.inf
        if abs(direction[1]) > 1e-9:
            t_f = (floor_y - origin[1]) / direction[1]
            if t_f > 1e-4:
                t_floor = t_f

        # Return closest hit
        if t_sphere < t_floor and t_sphere < math.inf:
            hit_pos = origin + t_sphere * direction
            normal = (hit_pos - sphere_center) / sphere_radius
            if hit_inside:
                normal = -normal
            return {
                "t": t_sphere,
                "position": hit_pos,
                "normal": normal,
                "surface": "glass",
                "material": material,
                "n_inside": None,
            }

        if t_floor < math.inf:
            hit_pos = origin + t_floor * direction
            return {
                "t": t_floor,
                "position": hit_pos,
                "normal": np.array([0.0, 1.0, 0.0]),
                "surface": "diffuse",
                "material": None,
                "n_inside": None,
            }

        return None

    return scene_intersect


# ---------------------------------------------------------------------------
# Tool: optics_render_caustic
# ---------------------------------------------------------------------------

_optics_render_caustic_spec = ToolSpec(
    name="optics_render_caustic",
    description=(
        "Trace photons through a glass sphere + floor scene and render the\n"
        "caustic pattern on the floor plane via Jensen 1996 photon mapping.\n"
        "\n"
        "Pass 1 (photon tracing): emit photons from a point light, refract\n"
        "through the glass sphere using Sellmeier dispersion.\n"
        "Pass 2 (caustic gather): accumulate photon power on the floor image plane.\n"
        "\n"
        "Scene (v1 fixed): point light above sphere; glass sphere; horizontal floor.\n"
        "All coordinates in scene units (e.g. metres or mm — consistent).\n"
        "\n"
        "Returns:\n"
        "  rgb_image     — (H×W×3) array as [[row of [r,g,b], ...], ...]\n"
        "  n_photons_stored — int (diffuse floor hits)\n"
        "  peak_rgb      — [r,g,b] maximum irradiance in image\n"
        "  resolution    — [W, H]\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "light_position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Point light world position [x, y, z]. Default [0, 5, 0].",
            },
            "light_intensity": {
                "type": "array",
                "items": {"type": "number"},
                "description": "RGB radiant intensity [r, g, b] W/sr. Default [100, 100, 100].",
            },
            "sphere_center": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Glass sphere center [x, y, z]. Default [0, 1, 0].",
            },
            "sphere_radius": {
                "type": "number",
                "description": "Glass sphere radius. Default 0.5.",
            },
            "glass_name": {
                "type": "string",
                "description": "Schott glass name: 'BK7', 'F2', 'SF11', 'N-BAK4'. Default 'BK7'.",
            },
            "floor_y": {
                "type": "number",
                "description": "Y-coordinate of the floor plane. Default 0.",
            },
            "image_origin": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Bottom-left corner of image plane [x, y, z]. Default [-1, 0.001, -1].",
            },
            "image_width": {
                "type": "number",
                "description": "Physical width of image plane. Default 2.0.",
            },
            "image_height": {
                "type": "number",
                "description": "Physical height of image plane. Default 2.0.",
            },
            "resolution": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[W, H] pixel resolution. Default [32, 32]. Max [128, 128].",
            },
            "n_photons": {
                "type": "integer",
                "description": "Number of photons to emit. Default 5000. Max 50000.",
            },
            "gather_radius": {
                "type": "number",
                "description": "Photon gather radius for irradiance estimate. Default 0.05.",
            },
            "n_wavelengths": {
                "type": "integer",
                "description": "Number of wavelength samples (spectral resolution). Default 5.",
            },
        },
        "required": [],
    },
)


@register(_optics_render_caustic_spec, write=False)
async def run_optics_render_caustic(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        light_pos = np.array(a.get("light_position", [0.0, 5.0, 0.0]), dtype=np.float64)
        light_int = np.array(a.get("light_intensity", [100.0, 100.0, 100.0]), dtype=np.float64)
        sphere_center = np.array(a.get("sphere_center", [0.0, 1.0, 0.0]), dtype=np.float64)
        sphere_radius = float(a.get("sphere_radius", 0.5))
        glass_name = str(a.get("glass_name", "BK7")).strip()
        floor_y = float(a.get("floor_y", 0.0))

        image_origin = np.array(a.get("image_origin", [-1.0, 0.001, -1.0]), dtype=np.float64)
        image_width = float(a.get("image_width", 2.0))
        image_height = float(a.get("image_height", 2.0))

        res_raw = a.get("resolution", [32, 32])
        res_w = min(int(res_raw[0]), 128)
        res_h = min(int(res_raw[1]), 128)

        n_photons = min(int(a.get("n_photons", 5000)), 50000)
        gather_radius = float(a.get("gather_radius", 0.05))
        n_wavelengths = max(1, min(int(a.get("n_wavelengths", 5)), 20))

    except Exception as exc:
        return err_payload(f"invalid parameters: {exc}", "BAD_ARGS")

    try:
        material = material_from_glass(glass_name)
    except Exception as exc:
        return err_payload(
            f"Unknown glass name '{glass_name}'. Try 'BK7', 'F2', 'SF11', 'N-BAK4'.",
            "BAD_ARGS",
        )

    # Wavelengths: visible spectrum 450..700 nm
    wavelengths = np.linspace(450.0, 700.0, n_wavelengths).tolist()

    light = Light(position=light_pos, intensity_rgb=light_int)
    scene_fn = _make_sphere_floor_scene(sphere_center, sphere_radius, material, floor_y)

    try:
        photons = emit_photons(light, n_photons, wavelengths, rng_seed=42)
        photon_map = trace_photons(photons, scene_fn, max_bounces=8)
    except Exception as exc:
        return err_payload(f"photon tracing error: {exc}", "EVAL_ERROR")

    # Image plane axes: u = +X, v = +Z (floor plane)
    u_axis = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    v_axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    plane_normal = np.array([0.0, 1.0, 0.0], dtype=np.float64)

    try:
        caustic = render_caustic(
            photon_map=photon_map,
            image_plane_origin=image_origin,
            image_plane_u=u_axis,
            image_plane_v=v_axis,
            image_plane_normal=plane_normal,
            width=image_width,
            height=image_height,
            resolution=(res_w, res_h),
            gather_radius=gather_radius,
        )
    except Exception as exc:
        return err_payload(f"caustic render error: {exc}", "EVAL_ERROR")

    rgb = caustic.rgb
    peak_rgb = rgb.max(axis=(0, 1)).tolist()

    return ok_payload({
        "rgb_image": rgb.tolist(),
        "n_photons_stored": len(photon_map.photons),
        "n_photons_emitted": n_photons,
        "peak_rgb": peak_rgb,
        "resolution": [res_w, res_h],
        "glass": glass_name,
        "gather_radius": gather_radius,
    })


__all__ = ["run_optics_render_caustic"]
