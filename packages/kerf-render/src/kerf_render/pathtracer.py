"""
pathtracer.py — a genuine CPU unidirectional Monte-Carlo path tracer.

This is a real, self-contained global-illumination renderer (no Blender, no
external process). It implements:

  * A BVH (median-split, surface-area-ish) over triangle meshes for O(log n)
    ray traversal.
  * Möller–Trumbore ray/triangle intersection.
  * Multi-bounce GI with Russian-roulette path termination.
  * Importance sampling per BSDF:
      - Lambertian diffuse: cosine-weighted hemisphere sampling.
      - Metal: GGX microfacet reflection (perfectly-smooth → mirror).
      - Dielectric: Fresnel-weighted reflection / refraction (glass, gems).
  * Next-event estimation (direct light sampling) against emissive area
    triangles to cut variance.
  * A constant / gradient environment that also contributes via NEE-friendly
    sampling on diffuse bounces.
  * Progressive sample accumulation in a linear HDR framebuffer, with an
    ACES-ish tonemap + sRGB encode on read-out.

The math is double-precision numpy with plain Python control flow. It is not
fast, but it is correct and converges — suitable for small validation scenes
(Cornell box) and as the reference backend behind the `pathtrace_render_scene`
LLM tool.

Coordinate convention: right-handed, +Y up. Camera looks down -Z by default but
is fully specified by (eye, look_at, up, vfov).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

EPS = 1e-6
INF = float("inf")


# ───────────────────────── vector helpers ──────────────────────────────────

def _v(x, y, z):
    return np.array([x, y, z], dtype=np.float64)


def _norm(v):
    n = math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))
    if n < EPS:
        return v
    return v / n


def _reflect(d, n):
    return d - 2.0 * float(np.dot(d, n)) * n


def _refract(d, n, eta):
    """Snell refraction. d, n unit; eta = n_from / n_to. Returns refracted dir
    or None on total internal reflection."""
    cosi = -float(np.dot(d, n))
    sin2t = eta * eta * (1.0 - cosi * cosi)
    if sin2t > 1.0:
        return None  # TIR
    cost = math.sqrt(1.0 - sin2t)
    return eta * d + (eta * cosi - cost) * n


def _onb(n):
    """Orthonormal basis from a unit normal."""
    if abs(n[0]) > 0.9:
        a = _v(0.0, 1.0, 0.0)
    else:
        a = _v(1.0, 0.0, 0.0)
    t = _norm(np.cross(a, n))
    b = np.cross(n, t)
    return t, b


def fresnel_schlick(cos_theta, f0):
    """Schlick's Fresnel approximation, scalar f0 or RGB."""
    m = max(0.0, 1.0 - cos_theta)
    return f0 + (1.0 - f0) * (m ** 5)


def fresnel_dielectric(cosi, eta):
    """Exact (unpolarized) dielectric Fresnel reflectance.

    cosi : cosine of incidence angle (>=0), eta = n_i / n_t.
    Returns reflectance R in [0,1].
    """
    cosi = min(1.0, max(0.0, cosi))
    sint = eta * math.sqrt(max(0.0, 1.0 - cosi * cosi))
    if sint >= 1.0:
        return 1.0  # total internal reflection
    cost = math.sqrt(max(0.0, 1.0 - sint * sint))
    rs = (eta * cosi - cost) / (eta * cosi + cost)
    rp = (cosi - eta * cost) / (cosi + eta * cost)
    return 0.5 * (rs * rs + rp * rp)


# ───────────────────────── materials ───────────────────────────────────────

DIFFUSE = "diffuse"
METAL = "metal"
DIELECTRIC = "dielectric"


@dataclass
class Material:
    kind: str = DIFFUSE
    albedo: np.ndarray = field(default_factory=lambda: _v(0.8, 0.8, 0.8))
    emission: np.ndarray = field(default_factory=lambda: _v(0.0, 0.0, 0.0))
    roughness: float = 0.0            # metal / GGX
    ior: float = 1.5                  # dielectric

    @property
    def is_emissive(self) -> bool:
        return bool(self.emission[0] + self.emission[1] + self.emission[2] > EPS)

    @staticmethod
    def from_dict(d: dict) -> "Material":
        kind = d.get("kind", DIFFUSE)
        alb = d.get("albedo", [0.8, 0.8, 0.8])
        emi = d.get("emission", [0.0, 0.0, 0.0])
        return Material(
            kind=kind,
            albedo=np.array(alb, dtype=np.float64),
            emission=np.array(emi, dtype=np.float64),
            roughness=float(d.get("roughness", 0.0)),
            ior=float(d.get("ior", 1.5)),
        )


# ───────────────────────── triangle soup + BVH ─────────────────────────────

@dataclass
class _Hit:
    t: float
    tri: int
    u: float
    v: float


class _BVHNode:
    __slots__ = ("bmin", "bmax", "left", "right", "start", "count")

    def __init__(self):
        self.bmin = _v(INF, INF, INF)
        self.bmax = _v(-INF, -INF, -INF)
        self.left = None
        self.right = None
        self.start = 0
        self.count = 0

    @property
    def is_leaf(self):
        return self.left is None and self.right is None


class Scene:
    """A triangle scene with a BVH. Each triangle has a material index and a
    geometric normal. Emissive triangles are tracked for NEE."""

    def __init__(self):
        self.verts: list[np.ndarray] = []          # flat: 3 per tri
        self.tri_mat: list[int] = []               # material index per tri
        self.materials: list[Material] = []
        self.normals: list[np.ndarray] = []        # geometric normal per tri
        self.area: list[float] = []
        self.emissive_tris: list[int] = []
        # environment
        self.env_top = _v(0.0, 0.0, 0.0)
        self.env_bottom = _v(0.0, 0.0, 0.0)
        self._order: list[int] = []
        self._root: _BVHNode | None = None

    # ---- construction -------------------------------------------------------

    def add_material(self, mat: Material) -> int:
        self.materials.append(mat)
        return len(self.materials) - 1

    def add_triangle(self, a, b, c, mat_index: int):
        a = np.asarray(a, dtype=np.float64)
        b = np.asarray(b, dtype=np.float64)
        c = np.asarray(c, dtype=np.float64)
        i = len(self.tri_mat)
        self.verts.extend([a, b, c])
        self.tri_mat.append(mat_index)
        n = np.cross(b - a, c - a)
        area = 0.5 * float(np.linalg.norm(n))
        self.normals.append(_norm(n))
        self.area.append(area)
        if self.materials[mat_index].is_emissive and area > EPS:
            self.emissive_tris.append(i)
        return i

    def add_quad(self, a, b, c, d, mat_index: int):
        """Add a planar quad as two triangles (a,b,c) (a,c,d)."""
        self.add_triangle(a, b, c, mat_index)
        self.add_triangle(a, c, d, mat_index)

    def set_environment(self, top, bottom=None):
        self.env_top = np.asarray(top, dtype=np.float64)
        self.env_bottom = np.asarray(bottom if bottom is not None else top,
                                     dtype=np.float64)

    def env_radiance(self, d):
        """Simple gradient environment along +Y."""
        t = 0.5 * (float(d[1]) + 1.0)
        return (1.0 - t) * self.env_bottom + t * self.env_top

    def _tri_verts(self, i):
        return self.verts[3 * i], self.verts[3 * i + 1], self.verts[3 * i + 2]

    def _tri_bounds(self, i):
        a, b, c = self._tri_verts(i)
        bmin = np.minimum(np.minimum(a, b), c)
        bmax = np.maximum(np.maximum(a, b), c)
        return bmin, bmax

    # ---- BVH build ----------------------------------------------------------

    def build(self):
        n = len(self.tri_mat)
        self._order = list(range(n))
        # Precompute pure-Python scalar triangle data for the hot intersection
        # loop (numpy per-call overhead dominates on 3-vectors).
        self._tri = []          # (ax,ay,az, e1x,e1y,e1z, e2x,e2y,e2z)
        self._tbounds = []      # (minx,miny,minz, maxx,maxy,maxz)
        for i in range(n):
            a, b, c = self._tri_verts(i)
            ax, ay, az = float(a[0]), float(a[1]), float(a[2])
            bx, by, bz = float(b[0]), float(b[1]), float(b[2])
            cx, cy, cz = float(c[0]), float(c[1]), float(c[2])
            self._tri.append((ax, ay, az,
                              bx - ax, by - ay, bz - az,
                              cx - ax, cy - ay, cz - az))
            self._tbounds.append((
                min(ax, bx, cx), min(ay, by, cy), min(az, bz, cz),
                max(ax, bx, cx), max(ay, by, cy), max(az, bz, cz),
            ))
        if n == 0:
            self._root = _BVHNode()
            return
        centroids = np.zeros((n, 3))
        for i in range(n):
            a, b, c = self._tri_verts(i)
            centroids[i] = (a + b + c) / 3.0
        self._centroids = centroids
        self._root = self._build_recursive(0, n)

    def _build_recursive(self, start, end):
        node = _BVHNode()
        bx0 = by0 = bz0 = INF
        bx1 = by1 = bz1 = -INF
        for k in range(start, end):
            tbn = self._tbounds[self._order[k]]
            if tbn[0] < bx0: bx0 = tbn[0]
            if tbn[1] < by0: by0 = tbn[1]
            if tbn[2] < bz0: bz0 = tbn[2]
            if tbn[3] > bx1: bx1 = tbn[3]
            if tbn[4] > by1: by1 = tbn[4]
            if tbn[5] > bz1: bz1 = tbn[5]
        node.bmin = (bx0, by0, bz0)
        node.bmax = (bx1, by1, bz1)
        bmin = _v(bx0, by0, bz0)
        bmax = _v(bx1, by1, bz1)
        count = end - start
        if count <= 2:
            node.start = start
            node.count = count
            return node
        # split on widest axis at median of centroids
        extent = bmax - bmin
        axis = int(np.argmax(extent))
        sub = self._order[start:end]
        sub.sort(key=lambda ti: self._centroids[ti][axis])
        self._order[start:end] = sub
        mid = start + count // 2
        node.left = self._build_recursive(start, mid)
        node.right = self._build_recursive(mid, end)
        return node

    # ---- traversal ----------------------------------------------------------

    @staticmethod
    def _ray_aabb(ox, oy, oz, idx, idy, idz, bmin, bmax, tmax):
        tx0 = (bmin[0] - ox) * idx
        tx1 = (bmax[0] - ox) * idx
        if tx0 > tx1:
            tx0, tx1 = tx1, tx0
        ty0 = (bmin[1] - oy) * idy
        ty1 = (bmax[1] - oy) * idy
        if ty0 > ty1:
            ty0, ty1 = ty1, ty0
        tz0 = (bmin[2] - oz) * idz
        tz1 = (bmax[2] - oz) * idz
        if tz0 > tz1:
            tz0, tz1 = tz1, tz0
        tnear = tx0
        if ty0 > tnear: tnear = ty0
        if tz0 > tnear: tnear = tz0
        if tnear < 0.0: tnear = 0.0
        tfar = tx1
        if ty1 < tfar: tfar = ty1
        if tz1 < tfar: tfar = tz1
        if tmax < tfar: tfar = tmax
        return tnear <= tfar

    def _intersect_tri(self, i, o, d, tmax):
        """Möller–Trumbore (numpy convenience wrapper for tests/brute force)."""
        return self._intersect_tri_s(
            i, float(o[0]), float(o[1]), float(o[2]),
            float(d[0]), float(d[1]), float(d[2]), tmax)

    def _intersect_tri_s(self, i, ox, oy, oz, dx, dy, dz, tmax):
        """Scalar Möller–Trumbore. Returns (t,u,v) or None."""
        (ax, ay, az, e1x, e1y, e1z, e2x, e2y, e2z) = self._tri[i]
        # p = d x e2
        px = dy * e2z - dz * e2y
        py = dz * e2x - dx * e2z
        pz = dx * e2y - dy * e2x
        det = e1x * px + e1y * py + e1z * pz
        if -EPS < det < EPS:
            return None
        inv = 1.0 / det
        tvx = ox - ax
        tvy = oy - ay
        tvz = oz - az
        u = (tvx * px + tvy * py + tvz * pz) * inv
        if u < 0.0 or u > 1.0:
            return None
        # q = tvec x e1
        qx = tvy * e1z - tvz * e1y
        qy = tvz * e1x - tvx * e1z
        qz = tvx * e1y - tvy * e1x
        v = (dx * qx + dy * qy + dz * qz) * inv
        if v < 0.0 or u + v > 1.0:
            return None
        t = (e2x * qx + e2y * qy + e2z * qz) * inv
        if t < EPS or t >= tmax:
            return None
        return t, u, v

    def intersect(self, o, d, tmax=INF):
        """Closest-hit traversal. Returns _Hit or None."""
        if self._root is None:
            self.build()
        ox, oy, oz = float(o[0]), float(o[1]), float(o[2])
        dx, dy, dz = float(d[0]), float(d[1]), float(d[2])
        idx = 1.0 / (dx if abs(dx) > 1e-12 else 1e-12)
        idy = 1.0 / (dy if abs(dy) > 1e-12 else 1e-12)
        idz = 1.0 / (dz if abs(dz) > 1e-12 else 1e-12)
        best = None
        best_t = tmax
        order = self._order
        tris = self._intersect_tri_s
        stack = [self._root]
        while stack:
            node = stack.pop()
            if not self._ray_aabb(ox, oy, oz, idx, idy, idz,
                                  node.bmin, node.bmax, best_t):
                continue
            if node.is_leaf:
                for k in range(node.start, node.start + node.count):
                    ti = order[k]
                    r = tris(ti, ox, oy, oz, dx, dy, dz, best_t)
                    if r is not None:
                        t, u, v = r
                        best_t = t
                        best = _Hit(t, ti, u, v)
            else:
                stack.append(node.left)
                stack.append(node.right)
        return best

    def occluded(self, o, d, tmax):
        """Any-hit shadow query."""
        if self._root is None:
            self.build()
        ox, oy, oz = float(o[0]), float(o[1]), float(o[2])
        dx, dy, dz = float(d[0]), float(d[1]), float(d[2])
        idx = 1.0 / (dx if abs(dx) > 1e-12 else 1e-12)
        idy = 1.0 / (dy if abs(dy) > 1e-12 else 1e-12)
        idz = 1.0 / (dz if abs(dz) > 1e-12 else 1e-12)
        order = self._order
        tris = self._intersect_tri_s
        stack = [self._root]
        while stack:
            node = stack.pop()
            if not self._ray_aabb(ox, oy, oz, idx, idy, idz,
                                  node.bmin, node.bmax, tmax):
                continue
            if node.is_leaf:
                for k in range(node.start, node.start + node.count):
                    ti = order[k]
                    r = tris(ti, ox, oy, oz, dx, dy, dz, tmax)
                    if r is not None:
                        return True
            else:
                stack.append(node.left)
                stack.append(node.right)
        return False


# ───────────────────────── camera ──────────────────────────────────────────

@dataclass
class Camera:
    eye: np.ndarray
    look_at: np.ndarray
    up: np.ndarray
    vfov_deg: float = 40.0
    aspect: float = 1.0

    def basis(self):
        w = _norm(self.eye - self.look_at)        # points back toward eye
        u = _norm(np.cross(self.up, w))
        v = np.cross(w, u)
        return u, v, w

    def ray(self, sx, sy):
        """sx, sy in [0,1] screen space (origin top-left)."""
        u, v, w = self.basis()
        half_h = math.tan(math.radians(self.vfov_deg) * 0.5)
        half_w = half_h * self.aspect
        # map to [-1,1], flip y so +v is up
        px = (2.0 * sx - 1.0) * half_w
        py = (1.0 - 2.0 * sy) * half_h
        d = _norm(px * u + py * v - w)
        return self.eye.copy(), d


# ───────────────────────── BSDF sampling ───────────────────────────────────

def _ggx_sample(n, rough, rng):
    """Sample a microfacet half-vector via GGX importance sampling, return the
    half-vector h (world space)."""
    a = max(1e-3, rough * rough)
    u1 = rng.random()
    u2 = rng.random()
    phi = 2.0 * math.pi * u1
    cos_t = math.sqrt((1.0 - u2) / (1.0 + (a * a - 1.0) * u2))
    sin_t = math.sqrt(max(0.0, 1.0 - cos_t * cos_t))
    hx = sin_t * math.cos(phi)
    hy = sin_t * math.sin(phi)
    hz = cos_t
    t, b = _onb(n)
    return _norm(hx * t + hy * b + hz * n)


def _cosine_sample(n, rng):
    """Cosine-weighted hemisphere sample about normal n."""
    u1 = rng.random()
    u2 = rng.random()
    r = math.sqrt(u1)
    phi = 2.0 * math.pi * u2
    x = r * math.cos(phi)
    y = r * math.sin(phi)
    z = math.sqrt(max(0.0, 1.0 - u1))
    t, b = _onb(n)
    return _norm(x * t + y * b + z * n)


# ───────────────────────── integrator ──────────────────────────────────────

def _sample_light(scene: Scene, p, rng):
    """Pick a uniform point on a uniformly-chosen emissive triangle.
    Returns (light_point, light_normal, emission, pdf_area, tri_index) or None.
    """
    if not scene.emissive_tris:
        return None
    li = scene.emissive_tris[rng.randrange(len(scene.emissive_tris))]
    a, b, c = scene._tri_verts(li)
    r1 = rng.random()
    r2 = rng.random()
    su = math.sqrt(r1)
    bu = 1.0 - su
    bv = r2 * su
    lp = a + bu * (b - a) + bv * (c - a)
    ln = scene.normals[li]
    emis = scene.materials[scene.tri_mat[li]].emission
    # pdf over area of choosing this exact point = 1/(N_lights) * 1/area
    pdf = 1.0 / (len(scene.emissive_tris) * scene.area[li])
    return lp, ln, emis, pdf, li


def _direct_light(scene: Scene, p, n, wo, mat, rng):
    """Next-event estimation for a diffuse surface point. Returns RGB radiance
    contribution (already weighted by BRDF, cosine, geometry, 1/pdf)."""
    s = _sample_light(scene, p, rng)
    if s is None:
        return _v(0.0, 0.0, 0.0)
    lp, ln, emis, pdf_area, li = s
    to_l = lp - p
    dist2 = float(np.dot(to_l, to_l))
    if dist2 < EPS:
        return _v(0.0, 0.0, 0.0)
    dist = math.sqrt(dist2)
    wi = to_l / dist
    cos_surf = float(np.dot(n, wi))
    cos_light = float(np.dot(ln, -wi))
    if cos_surf <= 0.0 or cos_light <= 0.0:
        return _v(0.0, 0.0, 0.0)
    # shadow ray
    if scene.occluded(p + n * 1e-4, wi, dist - 1e-3):
        return _v(0.0, 0.0, 0.0)
    # Lambertian BRDF = albedo/pi
    brdf = mat.albedo / math.pi
    # geometry term: cos_surf * cos_light / dist2, convert area pdf
    g = cos_surf * cos_light / dist2
    return brdf * emis * g / pdf_area


def radiance(scene: Scene, o, d, rng, max_depth=8):
    """Estimate incoming radiance along ray (o,d) via path tracing with NEE +
    Russian roulette."""
    L = _v(0.0, 0.0, 0.0)
    throughput = _v(1.0, 1.0, 1.0)
    specular_bounce = True  # camera ray counts emission directly

    for depth in range(max_depth):
        hit = scene.intersect(o, d)
        if hit is None:
            L = L + throughput * scene.env_radiance(d)
            break

        p = o + hit.t * d
        ng = scene.normals[hit.tri]
        # face-forward geometric normal
        if float(np.dot(ng, d)) > 0.0:
            n = -ng
            outward = False
        else:
            n = ng
            outward = True
        mat = scene.materials[scene.tri_mat[hit.tri]]
        wo = -d

        # Emission: count on camera/specular bounces (avoid double count w/ NEE)
        if mat.is_emissive and specular_bounce and float(np.dot(ng, wo)) > 0.0:
            L = L + throughput * mat.emission

        if mat.kind == DIFFUSE:
            # NEE direct lighting
            L = L + throughput * _direct_light(scene, p, n, wo, mat, rng)
            # indirect: cosine-weighted bounce. With cosine pdf the
            # diffuse estimator simplifies to throughput *= albedo.
            d = _cosine_sample(n, rng)
            o = p + n * 1e-4
            throughput = throughput * mat.albedo
            specular_bounce = False

        elif mat.kind == METAL:
            if mat.roughness <= 1e-3:
                d = _norm(_reflect(d, n))
            else:
                h = _ggx_sample(n, mat.roughness, rng)
                r = _reflect(d, h)
                if float(np.dot(r, n)) <= 0.0:
                    break
                d = _norm(r)
            o = p + n * 1e-4
            # Fresnel-tinted metal reflectance (albedo as F0)
            cos_o = max(0.0, float(np.dot(n, wo)))
            throughput = throughput * fresnel_schlick(cos_o, mat.albedo)
            specular_bounce = True

        elif mat.kind == DIELECTRIC:
            if outward:
                eta = 1.0 / mat.ior
                cosi = max(0.0, float(np.dot(wo, n)))
                fr = fresnel_dielectric(cosi, mat.ior)  # n_i=1, n_t=ior
            else:
                eta = mat.ior
                cosi = max(0.0, float(np.dot(wo, n)))
                fr = fresnel_dielectric(cosi, 1.0 / mat.ior)
            refr = _refract(d, n, eta)
            if refr is None or rng.random() < fr:
                d = _norm(_reflect(d, n))
                o = p + n * 1e-4
            else:
                d = _norm(refr)
                o = p - n * 1e-4
            # clear glass: no absorption tint here (albedo could tint)
            throughput = throughput * mat.albedo
            specular_bounce = True
        else:
            break

        # Russian roulette after a few bounces
        if depth >= 3:
            q = min(0.95, max(float(throughput[0]), float(throughput[1]),
                              float(throughput[2])))
            if q <= 0.0 or rng.random() > q:
                break
            throughput = throughput / q

    return L


# ───────────────────────── tonemap + framebuffer ───────────────────────────

def aces_tonemap(x):
    a = 2.51
    b = 0.03
    c = 2.43
    dd = 0.59
    e = 0.14
    return np.clip((x * (a * x + b)) / (x * (c * x + dd) + e), 0.0, 1.0)


def linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    lo = c * 12.92
    hi = 1.055 * np.power(np.maximum(c, 1e-8), 1.0 / 2.4) - 0.055
    return np.where(c <= 0.0031308, lo, hi)


class Framebuffer:
    """Linear HDR accumulation buffer with progressive averaging."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.accum = np.zeros((height, width, 3), dtype=np.float64)
        self.samples = 0

    def add_pass(self, frame):
        self.accum += frame
        self.samples += 1

    def mean(self):
        if self.samples == 0:
            return self.accum
        return self.accum / self.samples

    def tonemapped_uint8(self):
        m = self.mean()
        ldr = linear_to_srgb(aces_tonemap(m))
        return (np.clip(ldr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


# ───────────────────────── top-level render ────────────────────────────────

def render(scene: Scene, camera: Camera, width: int, height: int,
           samples: int, max_depth: int = 8, seed: int = 0,
           fb: Framebuffer | None = None, on_progress=None):
    """Render `samples` progressive passes into a Framebuffer and return it.

    Each pass is one sample-per-pixel with a stratified jitter; passes are
    averaged. Returns the Framebuffer (call .tonemapped_uint8() for an image).
    """
    import random

    scene.build()
    camera.aspect = width / float(height)
    if fb is None:
        fb = Framebuffer(width, height)

    for s in range(samples):
        rng = random.Random((seed * 1000003) ^ (s + 1) * 2654435761 & 0xFFFFFFFF)
        frame = np.zeros((height, width, 3), dtype=np.float64)
        for y in range(height):
            for x in range(width):
                jx = rng.random()
                jy = rng.random()
                sx = (x + jx) / width
                sy = (y + jy) / height
                o, d = camera.ray(sx, sy)
                frame[y, x] = radiance(scene, o, d, rng, max_depth)
        fb.add_pass(frame)
        if on_progress is not None:
            on_progress(s + 1, samples)
    return fb


def encode_png_base64(uint8_img) -> str:
    """Encode an HxWx3 uint8 array to a base64 PNG string (no data: prefix)."""
    import base64
    import io

    from PIL import Image

    img = Image.fromarray(uint8_img, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ───────────────────────── scene builders ──────────────────────────────────

def build_cornell_box(light_intensity: float = 18.0,
                       left_color=(0.65, 0.05, 0.05),
                       right_color=(0.12, 0.45, 0.15),
                       white=(0.73, 0.73, 0.73)) -> Scene:
    """A classic Cornell box: white floor/ceiling/back, red left wall, green
    right wall, an emissive ceiling panel, and two diffuse blocks. Box spans
    [0,1]^3 roughly; camera should sit in front at +Z looking toward -Z."""
    sc = Scene()
    sc.set_environment(top=(0.0, 0.0, 0.0), bottom=(0.0, 0.0, 0.0))

    m_white = sc.add_material(Material(DIFFUSE, _v(*white)))
    m_red = sc.add_material(Material(DIFFUSE, _v(*left_color)))
    m_green = sc.add_material(Material(DIFFUSE, _v(*right_color)))
    m_light = sc.add_material(
        Material(DIFFUSE, _v(0.0, 0.0, 0.0),
                 emission=_v(light_intensity, light_intensity, light_intensity)))

    # Box corners (x: 0..1 left→right, y: 0..1 floor→ceil, z: 0..1 back→front)
    # Floor
    sc.add_quad(_v(0, 0, 0), _v(1, 0, 0), _v(1, 0, 1), _v(0, 0, 1), m_white)
    # Ceiling
    sc.add_quad(_v(0, 1, 1), _v(1, 1, 1), _v(1, 1, 0), _v(0, 1, 0), m_white)
    # Back wall
    sc.add_quad(_v(0, 0, 0), _v(0, 1, 0), _v(1, 1, 0), _v(1, 0, 0), m_white)
    # Left wall (red)
    sc.add_quad(_v(0, 0, 1), _v(0, 1, 1), _v(0, 1, 0), _v(0, 0, 0), m_red)
    # Right wall (green)
    sc.add_quad(_v(1, 0, 0), _v(1, 1, 0), _v(1, 1, 1), _v(1, 0, 1), m_green)

    # Ceiling light panel (slightly below ceiling, facing down → -Y normal)
    lx0, lx1 = 0.35, 0.65
    lz0, lz1 = 0.35, 0.65
    ly = 0.999
    # wind so the geometric normal points DOWN (-Y) into the room
    sc.add_quad(_v(lx0, ly, lz0), _v(lx1, ly, lz0),
                _v(lx1, ly, lz1), _v(lx0, ly, lz1), m_light)

    # Two diffuse blocks (simple axis-aligned boxes)
    _add_box(sc, (0.13, 0.0, 0.15), (0.42, 0.30, 0.42), m_white)
    _add_box(sc, (0.55, 0.0, 0.45), (0.82, 0.55, 0.72), m_white)
    return sc


def _add_box(sc: Scene, lo, hi, mat):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    p = lambda a, b, c: _v(a, b, c)
    # +Y top
    sc.add_quad(p(x0, y1, z0), p(x0, y1, z1), p(x1, y1, z1), p(x1, y1, z0), mat)
    # -Y bottom
    sc.add_quad(p(x0, y0, z1), p(x0, y0, z0), p(x1, y0, z0), p(x1, y0, z1), mat)
    # +Z front
    sc.add_quad(p(x0, y0, z1), p(x1, y0, z1), p(x1, y1, z1), p(x0, y1, z1), mat)
    # -Z back
    sc.add_quad(p(x1, y0, z0), p(x0, y0, z0), p(x0, y1, z0), p(x1, y1, z0), mat)
    # +X right
    sc.add_quad(p(x1, y0, z1), p(x1, y0, z0), p(x1, y1, z0), p(x1, y1, z1), mat)
    # -X left
    sc.add_quad(p(x0, y0, z0), p(x0, y0, z1), p(x0, y1, z1), p(x0, y1, z0), mat)


def cornell_camera(width, height) -> Camera:
    return Camera(
        eye=_v(0.5, 0.5, 2.2),
        look_at=_v(0.5, 0.5, 0.0),
        up=_v(0.0, 1.0, 0.0),
        vfov_deg=40.0,
        aspect=width / float(height),
    )


# ───────────────────────── scene from JSON ─────────────────────────────────

def scene_from_dict(d: dict) -> Scene:
    """Build a Scene from a plain dict (the JSON the LLM tool accepts).

    {
      "materials": [{"kind":"diffuse","albedo":[..],"emission":[..],...}, ...],
      "triangles": [{"v":[[x,y,z],[..],[..]], "material": 0}, ...],
      "environment": {"top":[..], "bottom":[..]}
    }
    """
    sc = Scene()
    for md in d.get("materials", [{"kind": "diffuse"}]):
        sc.add_material(Material.from_dict(md))
    if not sc.materials:
        sc.add_material(Material())
    env = d.get("environment") or {}
    sc.set_environment(env.get("top", [0.0, 0.0, 0.0]),
                       env.get("bottom", env.get("top", [0.0, 0.0, 0.0])))
    for tri in d.get("triangles", []):
        v = tri["v"]
        mi = int(tri.get("material", 0))
        mi = max(0, min(mi, len(sc.materials) - 1))
        sc.add_triangle(v[0], v[1], v[2], mi)
    # also accept "quads" for convenience
    for q in d.get("quads", []):
        v = q["v"]
        mi = int(q.get("material", 0))
        mi = max(0, min(mi, len(sc.materials) - 1))
        sc.add_quad(v[0], v[1], v[2], v[3], mi)
    return sc


def camera_from_dict(d: dict, width: int, height: int) -> Camera:
    return Camera(
        eye=np.array(d.get("eye", [0.5, 0.5, 2.2]), dtype=np.float64),
        look_at=np.array(d.get("look_at", [0.5, 0.5, 0.0]), dtype=np.float64),
        up=np.array(d.get("up", [0.0, 1.0, 0.0]), dtype=np.float64),
        vfov_deg=float(d.get("vfov_deg", 40.0)),
        aspect=width / float(height),
    )
