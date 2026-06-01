"""
kerf_cad_core.optics.skew_ray_tracer — full 3-D skew-ray tracing engine.

A skew ray is any ray that does NOT lie in the meridional (Y-Z) plane.
Skew rays are essential for off-axis aberrations (sagittal coma, astigmatism,
field curvature) that are invisible to 2-D meridional tracing.

Public API
----------
trace_skew_ray(ray, surfaces) -> RayTraceResult
    Propagate a 3-D ray through a sequential list of conicoid surfaces.

Dataclasses
-----------
Ray3D
    origin_xyz, direction_xyz (unit vector), wavelength_nm
OpticalSurface
    vertex_z_mm, radius_mm (signed), refractive_index_after, conic_k
RayTraceResult
    ray_history, final_position_xyz, final_direction_xyz,
    tir_occurred, honest_caveat

Algorithm  (Born & Wolf §4.6; Welford 1986 §5)
-----------------------------------------------
Each surface is a conicoid of revolution about the z-axis with vertex at
z = vertex_z_mm:

    (x² + y²) / (R + sqrt(R² - (1+k)(x²+y²)))  =  z - v_z     [sag form]

equivalently (the implicit form used for intersection):

    F(x,y,z) = c(x²+y²+z'²) - 2z' + k·c·z'² = 0
    where z' = z - v_z,  c = 1/R

Intersection: parametric ray P(t) = origin + t·direction, substitute into F,
solve the quadratic for t.  Take the smallest positive root.

Surface normal at intersection P*:
    grad F = (2cx*, 2cy*, 2(c·(1+k)·z'* - 1))  — then normalise.

Refracted direction (Born & Wolf §1.5.3 eq. 1.5.23 vector form):
    n' d' = n d + (n' cos θ_t - n cos θ_i) N̂
where
    cos θ_i = d · N̂  (signed; flip N̂ if negative)
    cos θ_t = sqrt(1 - (n/n')² (1 - cos²θ_i))   [TIR if negative]

Scope / honest caveats
----------------------
* Monochromatic: one wavelength per ray; polychromatic requires multi-ray fan.
* Sequential surfaces only: ray is tested against surfaces in order; no
  backtracing or non-sequential paths.
* Plane surfaces (R=0, c=0) handled correctly (flat intersection).
* Higher-order aspheric terms (A4, A6, …) are NOT supported; only conic.
* No vignetting or aperture-stop clipping; caller must filter on aperture.

References
----------
Born, M. & Wolf, E. — "Principles of Optics", 7th ed. (1999), §1.5.3, §4.6.
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §5.
Kingslake, R. — "Lens Design Fundamentals", Academic Press, 1978, §2.
Hecht, E. — "Optics", 5th ed. (2017).

Units: lengths in mm; angles implicitly via direction cosines.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Ray3D:
    """
    A monochromatic ray in 3-D space.

    Parameters
    ----------
    origin_xyz : tuple[float, float, float]
        Starting position (x, y, z) in mm.
    direction_xyz : tuple[float, float, float]
        Unit direction vector (dx, dy, dz).  Automatically normalised on
        construction.  Must not be the zero vector.
    wavelength_nm : float
        Vacuum wavelength in nm.  Default 587.6 nm (Fraunhofer d-line).
    """
    origin_xyz: tuple[float, float, float]
    direction_xyz: tuple[float, float, float]
    wavelength_nm: float = 587.6

    def __post_init__(self) -> None:
        dx, dy, dz = self.direction_xyz
        mag = math.sqrt(dx * dx + dy * dy + dz * dz)
        if mag < 1e-18:
            raise ValueError("direction_xyz must not be the zero vector")
        self.direction_xyz = (dx / mag, dy / mag, dz / mag)


@dataclass
class OpticalSurface:
    """
    A conicoid surface of revolution about the z-axis.

    Parameters
    ----------
    vertex_z_mm : float
        z-coordinate of the surface vertex (mm).
    radius_mm : float
        Signed radius of curvature (mm).  Use 0.0 for a flat surface.
        Sign convention: R > 0 means centre of curvature is to the right (+z).
    refractive_index_after : float
        Refractive index of the medium *after* (to the right of) this surface.
        Must be >= 1.0.
    conic_k : float
        Conic constant.  0.0 = sphere, -1.0 = paraboloid, < -1 = hyperboloid,
        > 0 = oblate ellipsoid.  Default 0.0.
    """
    vertex_z_mm: float
    radius_mm: float
    refractive_index_after: float
    conic_k: float = 0.0


@dataclass
class RayTraceResult:
    """
    Result of tracing a Ray3D through a surface sequence.

    Fields
    ------
    ray_history : list[Ray3D]
        The ray state (origin, direction) at each surface intersection,
        including the refracted ray after the last surface.  The first
        entry is the input ray.
    final_position_xyz : tuple[float, float, float]
        Position at the last intersection (or starting position if no
        surfaces were traversed).
    final_direction_xyz : tuple[float, float, float]
        Propagation direction after the last refraction.
    tir_occurred : bool
        True if total internal reflection was encountered.
    honest_caveat : str
        Human-readable caveats about limitations of this trace.
    """
    ray_history: list[Ray3D] = field(default_factory=list)
    final_position_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    final_direction_xyz: tuple[float, float, float] = (0.0, 0.0, 1.0)
    tir_occurred: bool = False
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Internal vector helpers
# ---------------------------------------------------------------------------

def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _scale(a: tuple[float, float, float], s: float) -> tuple[float, float, float]:
    return (a[0] * s, a[1] * s, a[2] * s)


def _add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v: tuple[float, float, float]) -> tuple[float, float, float]:
    mag = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if mag < 1e-18:
        return v
    return (v[0] / mag, v[1] / mag, v[2] / mag)


# ---------------------------------------------------------------------------
# Surface intersection
# ---------------------------------------------------------------------------

def _intersect_conic(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    vertex_z: float,
    c: float,     # curvature = 1/R (0 for flat)
    k: float,     # conic constant
) -> Optional[float]:
    """
    Find the smallest positive parameter t such that
    origin + t*direction lies on the conicoid surface.

    The conicoid in coordinates relative to the vertex (z' = z - vertex_z):

        F(x, y, z') = c*(x² + y²) + c*(1+k)*z'² - 2*z' = 0

    For a flat surface (c=0):  z' = 0  →  t = (vertex_z - oz) / dz

    For a curved surface:  substitute P = O + t*D, form a quadratic in t.

    Returns t, or None if no positive intersection exists.
    """
    ox, oy, oz = origin
    dx, dy, dz = direction

    # Translate origin to surface-local frame (vertex at origin)
    sz = oz - vertex_z

    if abs(c) < 1e-18:
        # Flat surface: plane z' = 0
        if abs(dz) < 1e-18:
            return None  # ray parallel to plane, never hits
        t = -sz / dz
        return t if t > 1e-9 else None

    # Conicoid quadratic: A*t² + B*t + C = 0
    # A = c*(dx² + dy²) + c*(1+k)*dz²
    # B = 2*c*(ox'*dx + oy'*dy) + 2*c*(1+k)*sz*dz - 2*dz
    # C = c*(ox'² + oy'²) + c*(1+k)*sz² - 2*sz
    # where ox' = ox, oy' = oy (already perpendicular to axis)

    A = c * (dx * dx + dy * dy) + c * (1.0 + k) * dz * dz
    B = 2.0 * (c * (ox * dx + oy * dy) + c * (1.0 + k) * sz * dz - dz)
    C = c * (ox * ox + oy * oy) + c * (1.0 + k) * sz * sz - 2.0 * sz

    if abs(A) < 1e-18:
        # Degenerate: linear equation B*t + C = 0
        if abs(B) < 1e-18:
            return None
        t = -C / B
        return t if t > 1e-9 else None

    disc = B * B - 4.0 * A * C
    if disc < 0.0:
        return None  # no real intersection

    sqrt_disc = math.sqrt(disc)
    t1 = (-B - sqrt_disc) / (2.0 * A)
    t2 = (-B + sqrt_disc) / (2.0 * A)

    # Choose the smallest positive root, skipping values at or behind origin
    best: Optional[float] = None
    for t in (t1, t2):
        if t > 1e-9:
            if best is None or t < best:
                best = t
    return best


# ---------------------------------------------------------------------------
# Surface normal
# ---------------------------------------------------------------------------

def _surface_normal(
    p: tuple[float, float, float],
    vertex_z: float,
    c: float,
    k: float,
    n_before: float,
    direction: tuple[float, float, float],
) -> tuple[float, float, float]:
    """
    Outward unit surface normal at intersection point p.

    grad F (with z' = z - vertex_z):
        dF/dx = 2*c*x
        dF/dy = 2*c*y
        dF/dz = 2*c*(1+k)*z' - 2

    For a flat surface (c=0): normal is always (0, 0, -1) or (0, 0, +1);
    we orient it against the incoming ray so cos_i > 0.

    The normal is oriented to oppose the incoming ray direction,
    i.e. dot(normal, direction) < 0 after orientation.
    """
    x, y, z = p
    zp = z - vertex_z  # z relative to vertex

    if abs(c) < 1e-18:
        # Flat surface: normal is along z-axis
        # Orient so that it faces against the incoming ray
        if direction[2] > 0:
            return (0.0, 0.0, -1.0)
        else:
            return (0.0, 0.0, 1.0)

    nx = 2.0 * c * x
    ny = 2.0 * c * y
    nz = 2.0 * c * (1.0 + k) * zp - 2.0
    normal = _norm((nx, ny, nz))

    # Orient to oppose incoming ray
    if _dot(normal, direction) > 0:
        normal = _scale(normal, -1.0)
    return normal


# ---------------------------------------------------------------------------
# 3-D Snell's law (vector form)
# ---------------------------------------------------------------------------

def _refract_3d(
    d: tuple[float, float, float],
    normal: tuple[float, float, float],
    n1: float,
    n2: float,
) -> tuple[tuple[float, float, float], bool]:
    """
    Compute the refracted direction using the 3-D vector Snell's law.

    Convention (Wikipedia 'Snell's law' vector form; Born & Wolf §1.5.3):

        N̂  = unit surface normal pointing INTO the incident medium (medium 1),
              i.e. N̂ · d < 0 for a ray entering the surface.
        cos_i = -d · N̂   (positive, the cosine of the angle of incidence)
        cos_t = sqrt(1 - (n1/n2)² · sin²_i)
        d' = (n1/n2) · d + (n1/n2 · cos_i - cos_t) · N̂

    This is the standard form used by Shirley, Pharr & Humphreys "Physically
    Based Rendering" §8.2 and matches Born & Wolf §1.5.3 eq. 1.5.23.

    The ``normal`` argument is expected to oppose the incoming direction
    (i.e. _dot(normal, d) <= 0).  If it does not (surface hit from wrong side),
    the normal is flipped automatically so the formula remains valid.

    Returns (refracted_direction, tir_occurred).
    """
    # Ensure normal opposes the incoming ray so cos_i = -d . N̂ > 0
    dot = _dot(d, normal)
    if dot > 0.0:
        normal = _scale(normal, -1.0)
        dot = -dot
    cos_i = -dot  # positive

    ratio = n1 / n2
    sin2_t = ratio * ratio * (1.0 - cos_i * cos_i)

    if sin2_t > 1.0:
        # Total internal reflection
        return d, True

    cos_t = math.sqrt(1.0 - sin2_t)

    # d' = (n1/n2) * d + (n1/n2 * cos_i - cos_t) * N̂
    # (Born & Wolf §1.5.3; Shirley & Humphreys §8.2)
    coeff = ratio * cos_i - cos_t
    d_refracted = _add(_scale(d, ratio), _scale(normal, coeff))
    # Result is already unit-length (Snell's law preserves |d'|=1 for unit |d|)
    # but re-normalise to suppress floating-point drift.
    d_refracted = _norm(d_refracted)
    return d_refracted, False


# ---------------------------------------------------------------------------
# Main trace function
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "3-D skew-ray trace (Born & Wolf §4.6 / Welford §5). "
    "Monochromatic only. "
    "Sequential surfaces only; no non-sequential paths. "
    "Conic surfaces only (sphere, paraboloid, etc.); "
    "no higher-order aspheric terms (A4, A6, ...). "
    "No aperture-stop clipping; caller must filter on aperture radius. "
    "Plane surfaces (R=0) handled as z=const planes."
)


def trace_skew_ray(
    ray: Ray3D,
    surfaces: list[OpticalSurface],
    n_before_first: float = 1.0,
) -> RayTraceResult:
    """
    Propagate ``ray`` through a sequential list of optical surfaces.

    Each surface is a conicoid of revolution about the z-axis (Born & Wolf
    §4.6; Welford 1986 §5).  The algorithm at each surface:

      1. Find the ray–surface intersection (parametric quadratic solve).
      2. Compute the outward unit surface normal at the intersection.
      3. Apply 3-D vector Snell's law to get the refracted direction.
      4. Advance to the next surface.

    Parameters
    ----------
    ray : Ray3D
        Incident ray with origin (mm) and unit direction.
    surfaces : list[OpticalSurface]
        Ordered sequence of refracting surfaces.  The refractive index of
        the medium *before* the first surface is given by ``n_before_first``
        (default 1.0, i.e. air/vacuum).
    n_before_first : float
        Refractive index of the object-space medium.  Default 1.0.

    Returns
    -------
    RayTraceResult
        Full ray history, final position/direction, TIR flag, honest caveats.
    """
    result = RayTraceResult(honest_caveat=_HONEST_CAVEAT)
    result.ray_history.append(ray)

    pos = ray.origin_xyz
    direction = ray.direction_xyz
    n_current = n_before_first

    for surf in surfaces:
        c = (1.0 / surf.radius_mm) if abs(surf.radius_mm) > 1e-18 else 0.0
        k = surf.conic_k
        n_next = surf.refractive_index_after

        # 1. Find intersection
        t = _intersect_conic(pos, direction, surf.vertex_z_mm, c, k)
        if t is None:
            # Ray misses surface — propagation ends here
            result.final_position_xyz = pos
            result.final_direction_xyz = direction
            result.honest_caveat = (
                _HONEST_CAVEAT
                + " WARNING: ray missed a surface; trace terminated early."
            )
            return result

        # 2. Intersection point
        intersection = _add(pos, _scale(direction, t))

        # 3. Surface normal (oriented against incoming ray)
        normal = _surface_normal(intersection, surf.vertex_z_mm, c, k,
                                  n_current, direction)

        # 4. Refraction
        refracted_dir, tir = _refract_3d(direction, normal, n_current, n_next)

        if tir:
            result.tir_occurred = True
            result.final_position_xyz = intersection
            result.final_direction_xyz = direction  # unchanged on TIR
            result.ray_history.append(
                Ray3D(
                    origin_xyz=intersection,
                    direction_xyz=direction,
                    wavelength_nm=ray.wavelength_nm,
                )
            )
            result.honest_caveat = (
                _HONEST_CAVEAT
                + " NOTE: total internal reflection occurred; ray not transmitted."
            )
            return result

        # 5. Advance
        pos = intersection
        direction = refracted_dir
        n_current = n_next

        result.ray_history.append(
            Ray3D(
                origin_xyz=pos,
                direction_xyz=direction,
                wavelength_nm=ray.wavelength_nm,
            )
        )

    result.final_position_xyz = pos
    result.final_direction_xyz = direction
    return result
