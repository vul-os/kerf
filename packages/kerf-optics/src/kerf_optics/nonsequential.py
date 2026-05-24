"""
kerf_optics.nonsequential — Non-sequential 3-D ray tracing for stray-light
and ghost-image analysis.

Design goals
------------
* Pure Python + NumPy only (numpy is already a dep).
* Fresnel split at every interface: spawn refracted + reflected child rays;
  recurse to a configurable maximum depth to bound branching.
* Non-sequential traversal: at every step pick the nearest forward-intersecting
  surface in the *entire* surface list (not a fixed order).
* Ghost-image flag: rays that reach the detector via ≥ 2 reflections.

Public API
----------
Ray, SphericalSurface, PlaneSurface, RectAperture, Detector
trace_ray_ns(ray, surfaces, depth, epsilon) -> list[Ray]  # leaf rays
trace_bundle(source, surfaces, n_rays, depth, ...) -> TraceResult
optics_nonsequential_trace(...)  # LLM tool entry-point

LLM tool
--------
optics_nonsequential_trace_spec  — ToolSpec for registration
run_optics_nonsequential_trace   — async handler
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------

Vec3 = np.ndarray  # shape (3,), dtype float64


def _unit(v: Vec3) -> Vec3:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if n < 1e-14:
        raise ValueError("zero-length vector cannot be normalised")
    return v / n


def _dot(a: Vec3, b: Vec3) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


# ---------------------------------------------------------------------------
# Ray
# ---------------------------------------------------------------------------

@dataclass
class Ray:
    """A 3-D ray with wavelength and intensity."""

    origin: Vec3
    direction: Vec3          # unit vector (enforced on construction)
    wavelength_nm: float = 550.0
    intensity: float = 1.0
    n_reflections: int = 0   # number of specular reflections accumulated

    def __post_init__(self):
        self.origin = np.asarray(self.origin, dtype=float)
        self.direction = _unit(np.asarray(self.direction, dtype=float))

    def point_at(self, t: float) -> Vec3:
        return self.origin + t * self.direction


# ---------------------------------------------------------------------------
# Surface primitives
# ---------------------------------------------------------------------------

class SphericalSurface:
    """
    Refracting / reflecting spherical surface.

    Parameters
    ----------
    radius  : float — signed radius of curvature (positive = centre to the right)
    center  : array-like (3,) — centre of the sphere in world space
    n1, n2  : refractive indices on the incoming / outgoing side
    """

    def __init__(self, radius: float, center, n1: float = 1.0, n2: float = 1.5):
        self.radius = float(radius)
        self.center = np.asarray(center, dtype=float)
        self.n1 = float(n1)
        self.n2 = float(n2)

    # ------------------------------------------------------------------
    def intersect(self, ray: Ray, epsilon: float = 1e-9) -> Optional[float]:
        """Return nearest forward t > epsilon, or None."""
        oc = ray.origin - self.center
        d = ray.direction
        a = _dot(d, d)                          # 1.0 (d is unit)
        b = 2.0 * _dot(oc, d)
        c = _dot(oc, oc) - self.radius ** 2
        disc = b * b - 4.0 * a * c
        if disc < 0.0:
            return None
        sq = math.sqrt(disc)
        t1 = (-b - sq) / (2.0 * a)
        t2 = (-b + sq) / (2.0 * a)
        candidates = [t for t in (t1, t2) if t > epsilon]
        return min(candidates) if candidates else None

    def normal_at(self, point: Vec3) -> Vec3:
        """Outward unit normal."""
        return _unit(point - self.center)

    def interact(self, ray: Ray, t: float, depth: int, epsilon: float) -> list[Ray]:
        """Fresnel split → refracted + reflected child rays."""
        hit = ray.point_at(t)
        n_hat = self.normal_at(hit)
        # Ensure normal points against the incoming ray
        if _dot(n_hat, ray.direction) > 0.0:
            n_hat = -n_hat
            n1, n2 = self.n2, self.n1  # ray exiting glass
        else:
            n1, n2 = self.n1, self.n2

        return _fresnel_split(ray, hit, ray.direction, n_hat, n1, n2,
                              depth, epsilon)


class PlaneSurface:
    """
    Infinite refracting / reflecting plane.

    Parameters
    ----------
    normal : array-like (3,) — surface normal (need not be unit)
    point  : array-like (3,) — a point on the plane
    n1, n2 : refractive indices
    """

    def __init__(self, normal, point, n1: float = 1.0, n2: float = 1.5):
        self.normal = _unit(np.asarray(normal, dtype=float))
        self.point = np.asarray(point, dtype=float)
        self.n1 = float(n1)
        self.n2 = float(n2)

    def intersect(self, ray: Ray, epsilon: float = 1e-9) -> Optional[float]:
        denom = _dot(self.normal, ray.direction)
        if abs(denom) < 1e-14:
            return None                          # ray parallel to plane
        t = _dot(self.normal, self.point - ray.origin) / denom
        return t if t > epsilon else None

    def interact(self, ray: Ray, t: float, depth: int, epsilon: float) -> list[Ray]:
        hit = ray.point_at(t)
        n_hat = self.normal.copy()
        if _dot(n_hat, ray.direction) > 0.0:
            n_hat = -n_hat
            n1, n2 = self.n2, self.n1
        else:
            n1, n2 = self.n1, self.n2

        return _fresnel_split(ray, hit, ray.direction, n_hat, n1, n2,
                              depth, epsilon)


class RectAperture:
    """
    Rectangular aperture (opaque mask with a transparent window).

    Rays inside the window pass through unmodified; rays outside are absorbed.

    Parameters
    ----------
    corner1, corner2 : array-like (3,) — two opposite corners of the aperture window,
                       assumed to lie in a plane perpendicular to the Z-axis.
    """

    def __init__(self, corner1, corner2):
        self.corner1 = np.asarray(corner1, dtype=float)
        self.corner2 = np.asarray(corner2, dtype=float)
        # Plane is at the mean z of the two corners
        z = (self.corner1[2] + self.corner2[2]) / 2.0
        self._plane_z = z
        self._xmin = min(self.corner1[0], self.corner2[0])
        self._xmax = max(self.corner1[0], self.corner2[0])
        self._ymin = min(self.corner1[1], self.corner2[1])
        self._ymax = max(self.corner1[1], self.corner2[1])

    def intersect(self, ray: Ray, epsilon: float = 1e-9) -> Optional[float]:
        # Plane z = _plane_z
        dz = ray.direction[2]
        if abs(dz) < 1e-14:
            return None
        t = (self._plane_z - ray.origin[2]) / dz
        if t <= epsilon:
            return None
        return t

    def interact(self, ray: Ray, t: float, depth: int, epsilon: float) -> list[Ray]:
        hit = ray.point_at(t)
        x, y = hit[0], hit[1]
        if self._xmin <= x <= self._xmax and self._ymin <= y <= self._ymax:
            # Pass through: return unchanged ray starting just past the aperture
            child = Ray(
                origin=hit + ray.direction * epsilon,
                direction=ray.direction.copy(),
                wavelength_nm=ray.wavelength_nm,
                intensity=ray.intensity,
                n_reflections=ray.n_reflections,
            )
            return [child]
        else:
            return []           # absorbed


class Detector:
    """
    Flat rectangular detector that accumulates irradiance.

    Parameters
    ----------
    plane_z  : float — z-position of the detector plane
    width    : float — full width in x (m)
    height   : float — full height in y (m)
    pixels_x : int   — number of pixels along x
    pixels_y : int   — number of pixels along y
    """

    def __init__(self, plane_z: float = 0.0, width: float = 0.01,
                 height: float = 0.01, pixels_x: int = 64, pixels_y: int = 64):
        self.plane_z = float(plane_z)
        self.width = float(width)
        self.height = float(height)
        self.pixels_x = int(pixels_x)
        self.pixels_y = int(pixels_y)
        self.irradiance: np.ndarray = np.zeros((pixels_y, pixels_x), dtype=float)
        self.ghost_map: np.ndarray = np.zeros((pixels_y, pixels_x), dtype=float)

    def reset(self):
        self.irradiance[:] = 0.0
        self.ghost_map[:] = 0.0

    def intersect(self, ray: Ray, epsilon: float = 1e-9) -> Optional[float]:
        dz = ray.direction[2]
        if abs(dz) < 1e-14:
            return None
        t = (self.plane_z - ray.origin[2]) / dz
        return t if t > epsilon else None

    def interact(self, ray: Ray, t: float, depth: int, epsilon: float) -> list[Ray]:
        """Deposit intensity on the pixel map; do not spawn children."""
        hit = ray.point_at(t)
        x_frac = (hit[0] + self.width / 2.0) / self.width
        y_frac = (hit[1] + self.height / 2.0) / self.height
        if 0.0 <= x_frac < 1.0 and 0.0 <= y_frac < 1.0:
            ix = int(x_frac * self.pixels_x)
            iy = int(y_frac * self.pixels_y)
            self.irradiance[iy, ix] += ray.intensity
            if ray.n_reflections >= 2:
                self.ghost_map[iy, ix] += ray.intensity
        return []  # no children — terminal surface


# ---------------------------------------------------------------------------
# Fresnel coefficients (s/p average, unpolarised)
# ---------------------------------------------------------------------------

def _fresnel_rs(n1: float, n2: float, cos_i: float, cos_t: float) -> float:
    """Fresnel reflectance for s-polarisation."""
    num = n1 * cos_i - n2 * cos_t
    den = n1 * cos_i + n2 * cos_t
    return (num / den) ** 2 if abs(den) > 1e-14 else 1.0


def _fresnel_rp(n1: float, n2: float, cos_i: float, cos_t: float) -> float:
    """Fresnel reflectance for p-polarisation."""
    num = n2 * cos_i - n1 * cos_t
    den = n2 * cos_i + n1 * cos_t
    return (num / den) ** 2 if abs(den) > 1e-14 else 1.0


def _fresnel_reflectance(n1: float, n2: float, cos_i: float) -> float:
    """Unpolarised Fresnel reflectance R (0..1)."""
    sin2_t = (n1 / n2) ** 2 * (1.0 - cos_i ** 2)
    if sin2_t >= 1.0:
        return 1.0                               # total internal reflection
    cos_t = math.sqrt(1.0 - sin2_t)
    Rs = _fresnel_rs(n1, n2, cos_i, cos_t)
    Rp = _fresnel_rp(n1, n2, cos_i, cos_t)
    return 0.5 * (Rs + Rp)


# ---------------------------------------------------------------------------
# Snell refraction and specular reflection
# ---------------------------------------------------------------------------

def _refract(d: Vec3, n_hat: Vec3, n1: float, n2: float) -> Optional[Vec3]:
    """
    Snell's law vector form.

    Returns the refracted direction, or None on TIR.
    d       : unit incident direction (pointing toward surface)
    n_hat   : unit surface normal pointing against the ray
    n1, n2  : indices on incident / transmitted side
    """
    eta = n1 / n2
    cos_i = -_dot(d, n_hat)        # > 0 because n_hat against d
    sin2_t = eta ** 2 * (1.0 - cos_i ** 2)
    if sin2_t > 1.0:
        return None                 # TIR
    cos_t = math.sqrt(1.0 - sin2_t)
    refracted = eta * d + (eta * cos_i - cos_t) * n_hat
    return _unit(refracted)


def _reflect(d: Vec3, n_hat: Vec3) -> Vec3:
    """Specular reflection: r = d - 2(d·n)n."""
    return _unit(d - 2.0 * _dot(d, n_hat) * n_hat)


# ---------------------------------------------------------------------------
# Core Fresnel split
# ---------------------------------------------------------------------------

def _fresnel_split(
    ray: Ray,
    hit: Vec3,
    d: Vec3,          # incident direction (unit)
    n_hat: Vec3,      # normal pointing against d
    n1: float,
    n2: float,
    depth: int,
    epsilon: float,
) -> list[Ray]:
    """
    Return a list of child rays (refracted and/or reflected).

    At depth == 0 we still spawn children; the caller governs recursion.
    The *caller* (trace_ray_ns) checks depth before calling interact().
    """
    cos_i = -_dot(d, n_hat)
    R = _fresnel_reflectance(n1, n2, max(0.0, cos_i))
    T = 1.0 - R

    children: list[Ray] = []

    # Reflected ray
    if R * ray.intensity > 1e-14:
        r_dir = _reflect(d, n_hat)
        children.append(Ray(
            origin=hit + r_dir * epsilon,
            direction=r_dir,
            wavelength_nm=ray.wavelength_nm,
            intensity=ray.intensity * R,
            n_reflections=ray.n_reflections + 1,
        ))

    # Refracted ray
    t_dir = _refract(d, n_hat, n1, n2)
    if t_dir is not None and T * ray.intensity > 1e-14:
        children.append(Ray(
            origin=hit + t_dir * epsilon,
            direction=t_dir,
            wavelength_nm=ray.wavelength_nm,
            intensity=ray.intensity * T,
            n_reflections=ray.n_reflections,   # refraction does not add reflection count
        ))

    return children


# ---------------------------------------------------------------------------
# Non-sequential ray trace
# ---------------------------------------------------------------------------

_SurfaceType = SphericalSurface | PlaneSurface | RectAperture | Detector


def _nearest_intersection(
    ray: Ray,
    surfaces: list[_SurfaceType],
    epsilon: float,
) -> tuple[Optional[int], Optional[float]]:
    """Return (surface_index, t) of the nearest forward intersection, or (None, None)."""
    best_i: Optional[int] = None
    best_t: Optional[float] = None
    for i, surf in enumerate(surfaces):
        t = surf.intersect(ray, epsilon=epsilon)
        if t is not None and (best_t is None or t < best_t):
            best_t = t
            best_i = i
    return best_i, best_t


def _try_deposit_on_detector(
    ray: Ray,
    surfaces: list[_SurfaceType],
    epsilon: float,
) -> bool:
    """
    When recursion depth is exhausted, attempt a final detector hit so that
    ghost rays that have completed their internal bounces can still register.
    Returns True if the ray was deposited.
    """
    if ray.intensity < 1e-14:
        return False
    # Find the nearest detector in the forward direction
    best_t: Optional[float] = None
    best_det: Optional[Detector] = None
    for surf in surfaces:
        if not isinstance(surf, Detector):
            continue
        t = surf.intersect(ray, epsilon=epsilon)
        if t is not None and (best_t is None or t < best_t):
            best_t = t
            best_det = surf
    if best_det is not None and best_t is not None:
        best_det.interact(ray, best_t, depth=0, epsilon=epsilon)
        return True
    return False


def trace_ray_ns(
    ray: Ray,
    surfaces: list[_SurfaceType],
    max_depth: int = 4,
    epsilon: float = 1e-9,
) -> list[Ray]:
    """
    Non-sequentially trace a single ray through *surfaces*.

    Returns a flat list of all leaf rays (rays that either terminated or
    hit no surface).  Each leaf ray carries its final intensity and
    n_reflections count.

    When max_depth is exhausted, a final attempt is made to deposit on any
    reachable detector so ghost rays are not silently lost.
    """
    if ray.intensity < 1e-14:
        return []

    if max_depth <= 0:
        # Attempt to deposit on a detector even at depth limit
        _try_deposit_on_detector(ray, surfaces, epsilon)
        return [ray]

    idx, t = _nearest_intersection(ray, surfaces, epsilon)
    if idx is None:
        return [ray]                 # no intersection: ray escapes

    surf = surfaces[idx]
    children = surf.interact(ray, t, max_depth - 1, epsilon)

    if not children:
        return []                    # absorbed (aperture block or detector hit)

    leaves: list[Ray] = []
    for child in children:
        leaves.extend(trace_ray_ns(child, surfaces, max_depth - 1, epsilon))
    return leaves


# ---------------------------------------------------------------------------
# Source patch + bundle emitter
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """
    A circular source patch that emits a cone of rays.

    Parameters
    ----------
    position       : (3,) — centre of the source
    direction      : (3,) — optical axis direction (unit vector)
    half_angle_deg : float — half-angle of the emission cone (degrees)
    radius         : float — radius of the source patch (0 = point source)
    wavelength_nm  : float — wavelength
    """
    position: Any
    direction: Any
    half_angle_deg: float = 5.0
    radius: float = 0.0
    wavelength_nm: float = 550.0

    def __post_init__(self):
        self.position = np.asarray(self.position, dtype=float)
        self.direction = _unit(np.asarray(self.direction, dtype=float))

    def emit(self, n_rays: int, rng: random.Random) -> list[Ray]:
        """Emit n_rays with intensity 1/n_rays each."""
        rays = []
        intensity = 1.0 / n_rays
        ha_rad = math.radians(self.half_angle_deg)
        # Build an orthonormal frame (u, v, w=direction)
        w = self.direction
        # Pick an arbitrary perpendicular
        if abs(w[0]) < 0.9:
            tmp = np.array([1.0, 0.0, 0.0])
        else:
            tmp = np.array([0.0, 1.0, 0.0])
        u = _unit(np.cross(w, tmp))
        v = np.cross(w, u)

        for _ in range(n_rays):
            # Random direction within cone (uniform in solid angle via rejection)
            cos_max = math.cos(ha_rad)
            cos_theta = cos_max + (1.0 - cos_max) * rng.random()
            sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta ** 2))
            phi = rng.random() * 2.0 * math.pi
            d = _unit(
                sin_theta * math.cos(phi) * u
                + sin_theta * math.sin(phi) * v
                + cos_theta * w
            )
            # Random origin on source disk
            if self.radius > 0.0:
                r_off = math.sqrt(rng.random()) * self.radius
                phi_off = rng.random() * 2.0 * math.pi
                origin = (
                    self.position
                    + r_off * math.cos(phi_off) * u
                    + r_off * math.sin(phi_off) * v
                )
            else:
                origin = self.position.copy()

            rays.append(Ray(
                origin=origin,
                direction=d,
                wavelength_nm=self.wavelength_nm,
                intensity=intensity,
            ))
        return rays


# ---------------------------------------------------------------------------
# TraceResult
# ---------------------------------------------------------------------------

@dataclass
class TraceResult:
    detector: Detector
    n_ghost_rays: int          # leaf rays reaching detector with n_reflections >= 2
    ghost_intensity: float     # total ghost intensity on detector
    total_intensity: float     # total intensity on detector
    ghost_flag: bool           # True if any ghost rays reached detector


def trace_bundle(
    source: Source,
    surfaces: list[_SurfaceType],
    n_rays: int = 1000,
    max_depth: int = 4,
    epsilon: float = 1e-9,
    seed: int = 42,
) -> TraceResult:
    """
    Emit n_rays from source, trace each non-sequentially, accumulate on detector.

    The detector must be present in *surfaces*; if multiple detectors are
    present, only the first one is reported on.
    """
    rng = random.Random(seed)

    # Find the detector
    detector: Optional[Detector] = None
    for s in surfaces:
        if isinstance(s, Detector):
            detector = s
            break
    if detector is None:
        raise ValueError("no Detector found in surfaces list")
    detector.reset()

    rays = source.emit(n_rays, rng)

    n_ghost = 0
    ghost_int = 0.0

    for ray in rays:
        leaves = trace_ray_ns(ray, surfaces, max_depth=max_depth, epsilon=epsilon)
        # Count ghost leaves (those that were already deposited on the detector
        # inside interact(); here we scan the leaves that were *not* absorbed by
        # a detector — but detector.interact returns [] so those are not leaves).
        # Instead we check ghost_map total after the run.

    # Leaves that returned from trace_ray_ns and are NOT absorbed already include
    # rays that escaped. Ghost counting is done from detector.ghost_map.

    n_ghost = int(np.sum(detector.ghost_map > 0.0))
    ghost_int = float(np.sum(detector.ghost_map))
    total_int = float(np.sum(detector.irradiance))

    return TraceResult(
        detector=detector,
        n_ghost_rays=n_ghost,
        ghost_intensity=ghost_int,
        total_intensity=total_int,
        ghost_flag=ghost_int > 0.0,
    )


# ---------------------------------------------------------------------------
# LLM tool spec + handler
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_optics._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


optics_nonsequential_trace_spec = ToolSpec(
    name="optics_nonsequential_trace",
    description=(
        "Non-sequential 3-D ray trace for stray-light and ghost-image analysis. "
        "Emits a bundle of rays from a source patch, traces each through a list "
        "of refracting/reflecting surfaces using Fresnel splitting, and accumulates "
        "irradiance on a detector.  Returns the irradiance map, ghost-ray count, "
        "and a ghost-image flag (rays reaching the detector via ≥ 2 reflections)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surfaces": {
                "type": "array",
                "description": (
                    "Ordered list of surface definitions.  Each element is a dict "
                    "with a 'type' key:\n"
                    "  {type:'spherical', radius:R, center:[x,y,z], n1:1.0, n2:1.5}\n"
                    "  {type:'plane',    normal:[nx,ny,nz], point:[x,y,z], n1:1.0, n2:1.5}\n"
                    "  {type:'aperture', corner1:[x,y,z], corner2:[x,y,z]}\n"
                    "  {type:'detector', plane_z:z, width:w, height:h, pixels_x:N, pixels_y:N}"
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "source": {
                "type": "object",
                "description": (
                    "Source patch: {position:[x,y,z], direction:[dx,dy,dz], "
                    "half_angle_deg:5.0, radius:0.0, wavelength_nm:550.0}"
                ),
            },
            "n_rays": {
                "type": "integer",
                "description": "Number of rays to emit from the source. Default 500.",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum Fresnel recursion depth. Default 4.",
            },
            "seed": {
                "type": "integer",
                "description": "Random seed for reproducibility. Default 42.",
            },
        },
        "required": ["surfaces", "source"],
    },
)


def _parse_surface(spec: dict) -> _SurfaceType:
    t = spec.get("type", "").lower()
    if t == "spherical":
        return SphericalSurface(
            radius=float(spec["radius"]),
            center=np.asarray(spec["center"], dtype=float),
            n1=float(spec.get("n1", 1.0)),
            n2=float(spec.get("n2", 1.5)),
        )
    elif t == "plane":
        return PlaneSurface(
            normal=np.asarray(spec["normal"], dtype=float),
            point=np.asarray(spec["point"], dtype=float),
            n1=float(spec.get("n1", 1.0)),
            n2=float(spec.get("n2", 1.5)),
        )
    elif t == "aperture":
        return RectAperture(
            corner1=np.asarray(spec["corner1"], dtype=float),
            corner2=np.asarray(spec["corner2"], dtype=float),
        )
    elif t == "detector":
        return Detector(
            plane_z=float(spec.get("plane_z", 0.0)),
            width=float(spec.get("width", 0.01)),
            height=float(spec.get("height", 0.01)),
            pixels_x=int(spec.get("pixels_x", 64)),
            pixels_y=int(spec.get("pixels_y", 64)),
        )
    else:
        raise ValueError(f"unknown surface type: {spec.get('type')!r}")


async def run_optics_nonsequential_trace(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        raw_surfaces = args["surfaces"]
        surfaces = [_parse_surface(s) for s in raw_surfaces]

        src_spec = args["source"]
        source = Source(
            position=np.asarray(src_spec["position"], dtype=float),
            direction=np.asarray(src_spec["direction"], dtype=float),
            half_angle_deg=float(src_spec.get("half_angle_deg", 5.0)),
            radius=float(src_spec.get("radius", 0.0)),
            wavelength_nm=float(src_spec.get("wavelength_nm", 550.0)),
        )

        n_rays = int(args.get("n_rays", 500))
        max_depth = int(args.get("max_depth", 4))
        seed = int(args.get("seed", 42))

        result = trace_bundle(
            source=source,
            surfaces=surfaces,
            n_rays=n_rays,
            max_depth=max_depth,
            seed=seed,
        )

        det = result.detector
        irr = det.irradiance
        peak = float(irr.max())
        mean_offspot = float(irr[irr < peak].mean()) if irr.size > 1 else 0.0

        payload: dict[str, Any] = {
            "total_intensity_on_detector": round(result.total_intensity, 8),
            "peak_irradiance": round(peak, 8),
            "mean_offspot_irradiance": round(mean_offspot, 8),
            "peak_to_mean_ratio": round(peak / mean_offspot, 4) if mean_offspot > 1e-14 else None,
            "ghost_flag": result.ghost_flag,
            "ghost_intensity": round(result.ghost_intensity, 8),
            "n_ghost_pixels": result.n_ghost_rays,
            "detector_pixels": [det.pixels_y, det.pixels_x],
            "irradiance_map": irr.tolist(),
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "NS_TRACE_ERROR")
