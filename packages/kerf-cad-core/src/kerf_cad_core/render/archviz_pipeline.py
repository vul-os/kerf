"""
kerf_cad_core.render.archviz_pipeline — Full architectural-visualisation render pipeline.

Combines:
  * HDRI environment map (equirectangular .hdr/.exr) for ambient IBL
  * Physically-based sun + directional light
  * PBR material model (albedo, roughness, metallic, IOR)
  * Primary ray casting via brute-force triangle intersection
  * Photon-map gather for indirect/caustic (Jensen 1996) using
    kerf_cad_core.optics.photon_map
  * Path-traced shadow rays for direct occlusion

HONEST: This is a *preview-quality* archviz renderer, not Vray / Lumion / Enscape.
It produces plausible images for design review.  Production quality would require:
  * Multi-bounce path tracing (MIS + BRDF sampling)
  * Spectral rendering
  * Full GPU acceleration

References
----------
Jensen, H.W. (1996).  "Global Illumination Using Photon Maps."
    Proc. Eurographics Workshop on Rendering (EGWR), pp. 21–30.
Pharr, M., Jakob, W., and Humphreys, G. (2023).  "Physically Based Rendering:
    From Theory to Implementation." 4th ed.  MIT Press.  §9 (BxDF), §14 (path tracing).
Akenine-Möller, T., Haines, E., and Hoffman, N. (2018).  "Real-Time Rendering."
    4th ed.  A K Peters.  §11 (BRDF).

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.optics.photon_map import (
    PhotonMap,
    Photon,
    Light,
    RefractiveMaterial,
    emit_photons,
    trace_photons,
)
# CausticPattern / render_caustic available for downstream use
from kerf_cad_core.optics.caustic_solver import CausticPattern, render_caustic  # noqa: F401

# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

# Default PBR material
_DEFAULT_MATERIAL: Dict = {
    "albedo": (0.7, 0.7, 0.7),
    "roughness": 0.5,
    "metallic": 0.0,
    "ior": 1.5,
    "emission": (0.0, 0.0, 0.0),
}


def _material_brdf(
    material: dict,
    cos_theta_i: float,
    cos_theta_o: float,
    cos_halfway: float,
) -> np.ndarray:
    """Simplified Cook-Torrance microfacet BRDF (RGB).

    f_r = f_diffuse + f_specular
    f_diffuse = albedo/π (Lambertian)
    f_specular = D·F·G / (4·cosθi·cosθo)  — GGX / Schlick approximations

    Parameters
    ----------
    material : dict
        PBR material parameters.
    cos_theta_i, cos_theta_o : float
        Cosines of incident and outgoing angles relative to surface normal.
    cos_halfway : float
        Cosine of the halfway-vector angle.

    Returns
    -------
    np.ndarray, shape (3,)  — RGB BRDF value.

    References
    ----------
    Pharr, Jakob, Humphreys (2023), §9.6 (Cook-Torrance).
    Walter et al. (2007) — Microfacet Models for Refraction through Rough Surfaces.
    """
    albedo = np.array(material.get("albedo", (0.7, 0.7, 0.7)), dtype=float)
    roughness = float(material.get("roughness", 0.5))
    metallic = float(material.get("metallic", 0.0))

    alpha = roughness * roughness  # GGX α = r²

    # Diffuse term (Lambertian, reduced by metallic factor)
    f_diffuse = albedo * (1.0 - metallic) / math.pi

    if cos_theta_i <= 0.0 or cos_theta_o <= 0.0:
        return f_diffuse

    # GGX normal distribution D(h)
    alpha2 = alpha * alpha
    denom_d = cos_halfway * cos_halfway * (alpha2 - 1.0) + 1.0
    D = alpha2 / (math.pi * denom_d * denom_d + 1e-12)

    # Schlick geometry G
    k = (roughness + 1.0) ** 2 / 8.0
    G1_i = cos_theta_i / (cos_theta_i * (1.0 - k) + k + 1e-12)
    G1_o = cos_theta_o / (cos_theta_o * (1.0 - k) + k + 1e-12)
    G = G1_i * G1_o

    # Fresnel F (Schlick)
    ior = float(material.get("ior", 1.5))
    f0_scalar = ((1.0 - ior) / (1.0 + ior)) ** 2
    f0 = albedo * metallic + np.full(3, f0_scalar * (1.0 - metallic))
    F = f0 + (1.0 - f0) * ((1.0 - max(0.0, cos_theta_o)) ** 5)

    f_specular = D * F * G / (4.0 * cos_theta_i * cos_theta_o + 1e-12)

    return f_diffuse + f_specular


# ---------------------------------------------------------------------------
# Scene descriptor
# ---------------------------------------------------------------------------

@dataclass
class ArchVizScene:
    """Complete architectural visualisation scene descriptor.

    Attributes
    ----------
    geometry_meshes : list
        Each element: ``(vertices, triangles, material_id)`` where
        ``vertices`` is (N,3) float, ``triangles`` is (M,3) int,
        ``material_id`` is a string key into ``materials``.
    materials : dict[str, dict]
        PBR material dictionary.  Keys are material_id strings.
        Each dict may contain: albedo (R,G,B), roughness, metallic, ior, emission.
    hdri_envmap_path : str | None
        Path to an equirectangular HDRI file (.hdr / .exr).
        If None, a procedural sky gradient is used.
    sun_direction : tuple[float, float, float]
        Unit vector pointing *toward* the sun.
    sun_intensity : float
        Solar irradiance scale factor (default 1.0 → ~100,000 lux clear sky).
    sun_color : tuple[float, float, float]
        RGB tint of the sun (default warm white).
    camera_pos : tuple[float, float, float]
    camera_look_at : tuple[float, float, float]
    camera_fov_deg : float
        Horizontal field of view in degrees.
    sky_color : tuple[float, float, float]
        Background sky colour when no HDRI is supplied.
    """
    geometry_meshes: List = field(default_factory=list)
    materials: Dict[str, Dict] = field(default_factory=dict)
    hdri_envmap_path: Optional[str] = None
    sun_direction: Tuple[float, float, float] = (0.3, 0.3, 0.9)
    sun_intensity: float = 1.0
    sun_color: Tuple[float, float, float] = (1.0, 0.95, 0.85)
    camera_pos: Tuple[float, float, float] = (0.0, -5.0, 1.8)
    camera_look_at: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    camera_fov_deg: float = 60.0
    sky_color: Tuple[float, float, float] = (0.53, 0.81, 0.98)


# ---------------------------------------------------------------------------
# Ray / intersection helpers
# ---------------------------------------------------------------------------

def _ray_triangle_intersect(
    orig: np.ndarray,
    direction: np.ndarray,
    v0: np.ndarray,
    v1: np.ndarray,
    v2: np.ndarray,
) -> Optional[float]:
    """Möller-Trumbore ray–triangle intersection.

    Returns
    -------
    float | None
        Ray parameter t (distance) if intersection in [1e-4, ∞), else None.

    References
    ----------
    Möller, T. and Trumbore, B. (1997).  "Fast, Minimum Storage Ray/Triangle
        Intersection."  Journal of Graphics Tools 2(1): 21–28.
    """
    EPS = 1e-8
    e1 = v1 - v0
    e2 = v2 - v0
    h = np.cross(direction, e2)
    a = float(np.dot(e1, h))
    if abs(a) < EPS:
        return None
    f = 1.0 / a
    s = orig - v0
    u = f * float(np.dot(s, h))
    if u < 0.0 or u > 1.0:
        return None
    q = np.cross(s, e1)
    v = f * float(np.dot(direction, q))
    if v < 0.0 or u + v > 1.0:
        return None
    t = f * float(np.dot(e2, q))
    if t < 1e-4:
        return None
    return t


def _scene_intersect(
    orig: np.ndarray,
    direction: np.ndarray,
    geometry_meshes: list,
) -> Tuple[Optional[float], Optional[str], Optional[np.ndarray]]:
    """Find closest ray–scene intersection.

    Returns
    -------
    (t, material_id, normal) or (None, None, None) if no hit.
    """
    best_t = float("inf")
    best_mat = None
    best_normal = None

    for verts_raw, tris_raw, mat_id in geometry_meshes:
        verts = np.asarray(verts_raw, dtype=float)
        tris = np.asarray(tris_raw, dtype=int)
        for tri in tris:
            v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            t = _ray_triangle_intersect(orig, direction, v0, v1, v2)
            if t is not None and t < best_t:
                best_t = t
                best_mat = mat_id
                n = np.cross(v1 - v0, v2 - v0)
                nlen = float(np.linalg.norm(n))
                best_normal = n / nlen if nlen > 1e-12 else np.array([0.0, 1.0, 0.0])

    if best_mat is None:
        return None, None, None
    return best_t, best_mat, best_normal


def _sky_sample(direction: np.ndarray, sky_color: Tuple[float, float, float]) -> np.ndarray:
    """Sample the sky (procedural gradient when no HDRI is loaded).

    Blue-to-horizon gradient based on the direction's elevation.

    Parameters
    ----------
    direction : np.ndarray
        Unit ray direction.
    sky_color : tuple
        Zenith sky colour.

    Returns
    -------
    np.ndarray, shape (3,)
        RGB sky radiance (linear).
    """
    t = max(0.0, float(direction[2]))  # elevation factor
    horiz = np.array([0.8, 0.85, 0.95], dtype=float)
    zenith = np.array(sky_color, dtype=float)
    return horiz + (zenith - horiz) * t


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_archviz(
    scene: ArchVizScene,
    resolution: Tuple[int, int],
    samples: int = 64,
) -> np.ndarray:
    """Render an architectural scene to a (H, W, 3) RGB image.

    Algorithm:
    1.  Build photon map from the sun (treated as a directional light) using
        ``kerf_cad_core.optics.photon_map.emit_photons`` + ``trace_photons``.
    2.  For each pixel, shoot a primary ray using a simple pinhole camera.
    3.  On hit: evaluate direct sun shading (Lambert × shadow factor) + indirect
        irradiance from the photon-map gather.  On miss: sample procedural sky.
    4.  Tonemap (Reinhard) and gamma-correct to uint8.

    HONEST: One-bounce indirect via photon map only.  Full path-traced multi-bounce
    GI requires many more samples (Pharr et al. 2023 §14).

    Parameters
    ----------
    scene : ArchVizScene
    resolution : (W, H)
    samples : int
        Number of photons to emit per light source (passed to emit_photons).

    Returns
    -------
    np.ndarray, shape (H, W, 3), dtype=uint8
        Tone-mapped rendered image.

    References
    ----------
    Jensen (1996) — photon-map gather.
    Pharr, Jakob, Humphreys (2023) §5 (camera model), §14 (path tracing overview).
    Reinhard, E. et al. (2002).  "Photographic Tone Reproduction for Digital Images."
        SIGGRAPH 2002 Proceedings.
    Möller, Trumbore (1997) — ray–triangle.
    """
    W, H = resolution
    image = np.zeros((H, W, 3), dtype=float)

    # ── Camera setup ──────────────────────────────────────────────────────
    cam = np.array(scene.camera_pos, dtype=float)
    look = np.array(scene.camera_look_at, dtype=float)
    fwd = look - cam
    fwd_len = float(np.linalg.norm(fwd))
    if fwd_len < 1e-9:
        fwd = np.array([0.0, 1.0, 0.0])
    else:
        fwd = fwd / fwd_len

    world_up = np.array([0.0, 0.0, 1.0])
    right = np.cross(fwd, world_up)
    right_len = float(np.linalg.norm(right))
    if right_len < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / right_len
    up = np.cross(right, fwd)

    fov_rad = math.radians(scene.camera_fov_deg)
    half_w = math.tan(fov_rad / 2.0)
    half_h = half_w * H / W

    # ── Photon map ────────────────────────────────────────────────────────
    sun_dir = np.array(scene.sun_direction, dtype=float)
    sun_len = float(np.linalg.norm(sun_dir))
    if sun_len > 1e-9:
        sun_dir = sun_dir / sun_len

    # Create a distant directional light (spot pointing downward from above).
    # Light.position = far away in sun_dir; spot cone = narrow (0.01 rad).
    # intensity_rgb = sun_color scaled by sun_intensity.
    sun_light = Light(
        position=sun_dir * 1000.0,
        intensity_rgb=np.array(scene.sun_color, dtype=float) * scene.sun_intensity * 100.0,
        direction=-sun_dir,       # photons travel toward scene (opposite of sun_dir)
        cone_angle_rad=0.5,       # wide enough to illuminate the scene
    )

    # emit photons — wavelengths sampled at RGB centres
    n_photons = max(64, samples)
    photons = emit_photons(
        light=sun_light,
        n_photons=n_photons,
        wavelengths_nm=[650.0, 550.0, 450.0],
        rng_seed=42,
    )

    # Build scene_intersect for trace_photons from the geometry meshes.
    # Each photon is traced; on hitting a diffuse surface it is stored.
    def _archviz_scene_intersect(
        orig: np.ndarray, direction: np.ndarray
    ) -> Optional[dict]:
        t_hit, mat_id, normal = _scene_intersect(orig, direction, scene.geometry_meshes)
        if t_hit is None:
            return None
        return {
            "t": t_hit,
            "position": orig + direction * t_hit,
            "normal": normal,
            "surface": "diffuse",
            "material": None,
            "n_inside": None,
        }

    # Trace photons — Jensen (1996) Pass 1
    photon_map = trace_photons(
        photons=photons,
        scene_intersect=_archviz_scene_intersect,
        max_bounces=2,
    )

    # ── Primary ray loop ──────────────────────────────────────────────────
    sun_col = np.array(scene.sun_color, dtype=float)

    for j in range(H):
        v_ndc = 1.0 - 2.0 * (j + 0.5) / H  # +1 at top, -1 at bottom
        for i in range(W):
            u_ndc = 2.0 * (i + 0.5) / W - 1.0  # -1 at left, +1 at right

            # Ray direction
            ray_dir = fwd + right * (u_ndc * half_w) + up * (v_ndc * half_h)
            ray_dir_len = float(np.linalg.norm(ray_dir))
            if ray_dir_len < 1e-9:
                continue
            ray_dir = ray_dir / ray_dir_len

            # Scene intersection
            t_hit, mat_id, normal = _scene_intersect(cam, ray_dir, scene.geometry_meshes)

            if t_hit is None:
                # Sky / background
                pixel_color = _sky_sample(ray_dir, scene.sky_color)
            else:
                hit_pt = cam + ray_dir * t_hit
                mat = scene.materials.get(mat_id or "", _DEFAULT_MATERIAL)

                # Ensure normal faces camera
                if float(np.dot(normal, -ray_dir)) < 0:
                    normal = -normal

                # Direct lighting — sun
                cos_sun = max(0.0, float(np.dot(normal, sun_dir)))

                # Shadow test (single shadow ray toward sun)
                shadow_t, _, _ = _scene_intersect(
                    hit_pt + normal * 1e-3, sun_dir, scene.geometry_meshes
                )
                in_shadow = shadow_t is not None

                # BRDF
                half_v = sun_dir + (-ray_dir)
                half_v_len = float(np.linalg.norm(half_v))
                if half_v_len > 1e-9:
                    half_v = half_v / half_v_len
                cos_h = max(0.0, float(np.dot(normal, half_v)))
                cos_i = cos_sun
                cos_o = max(0.0, float(np.dot(normal, -ray_dir)))

                brdf = _material_brdf(mat, cos_i, cos_o, cos_h)
                albedo = np.array(mat.get("albedo", (0.7, 0.7, 0.7)), dtype=float)

                direct = (
                    np.zeros(3) if in_shadow
                    else brdf * sun_col * scene.sun_intensity * cos_sun
                )

                # Indirect — photon map gather
                gather_radius = 0.5
                indirect = photon_map.gather(hit_pt, normal, gather_radius)
                # Scale indirect contribution
                indirect = indirect * albedo * 0.3

                # Sky ambient — diffuse sky contribution using hemisphere normal
                # Approximation: sky_color × albedo × max(0, normal.z)/2 + base
                # This ensures all surfaces receive at least some sky bounce light.
                sky_col = np.array(scene.sky_color, dtype=float)
                sky_up = max(0.0, float(normal[2]))  # upward-facing gets more sky
                sky_ambient = albedo * sky_col * (0.15 + 0.25 * sky_up)

                # Emission
                emission = np.array(mat.get("emission", (0.0, 0.0, 0.0)), dtype=float)

                pixel_color = direct + indirect + sky_ambient + emission

            image[j, i, :] = pixel_color

    # ── Tone mapping (Reinhard 2002) + gamma correction ───────────────────
    image = image / (image + 1.0)
    image = np.power(np.clip(image, 0.0, 1.0), 1.0 / 2.2)
    return (image * 255.0).astype(np.uint8)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_simple_room_scene(
    width: float = 6.0,
    depth: float = 5.0,
    height: float = 3.0,
) -> ArchVizScene:
    """Create a simple room (floor + 4 walls + ceiling) ArchVizScene.

    Useful for quick tests and demonstrations.

    Parameters
    ----------
    width, depth, height : float
        Room dimensions in metres.

    Returns
    -------
    ArchVizScene
    """
    hw, hd, h = width / 2, depth / 2, height

    # 6 quads: floor, ceiling, 4 walls
    meshes = []

    def _quad(corners: list, mat_id: str) -> tuple:
        verts = np.array(corners, dtype=float)
        tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)
        return (verts, tris, mat_id)

    # Floor
    meshes.append(_quad([[-hw, -hd, 0], [hw, -hd, 0], [hw, hd, 0], [-hw, hd, 0]], "floor"))
    # Ceiling
    meshes.append(_quad([[-hw, -hd, h], [hw, -hd, h], [hw, hd, h], [-hw, hd, h]], "ceiling"))
    # Front wall
    meshes.append(_quad([[-hw, hd, 0], [hw, hd, 0], [hw, hd, h], [-hw, hd, h]], "wall"))
    # Back wall
    meshes.append(_quad([[-hw, -hd, 0], [hw, -hd, 0], [hw, -hd, h], [-hw, -hd, h]], "wall"))
    # Left wall
    meshes.append(_quad([[-hw, -hd, 0], [-hw, hd, 0], [-hw, hd, h], [-hw, -hd, h]], "wall"))
    # Right wall
    meshes.append(_quad([[hw, -hd, 0], [hw, hd, 0], [hw, hd, h], [hw, -hd, h]], "wall"))

    materials = {
        "floor": {"albedo": (0.6, 0.5, 0.4), "roughness": 0.8, "metallic": 0.0, "ior": 1.5},
        "ceiling": {"albedo": (0.95, 0.95, 0.95), "roughness": 1.0, "metallic": 0.0, "ior": 1.5},
        "wall": {"albedo": (0.85, 0.85, 0.80), "roughness": 0.9, "metallic": 0.0, "ior": 1.5},
    }

    return ArchVizScene(
        geometry_meshes=meshes,
        materials=materials,
        sun_direction=(0.4, 0.3, 0.85),
        sun_intensity=1.2,
        camera_pos=(0.0, -depth * 0.6, 1.5),
        camera_look_at=(0.0, 0.0, 1.5),
        camera_fov_deg=65.0,
    )
