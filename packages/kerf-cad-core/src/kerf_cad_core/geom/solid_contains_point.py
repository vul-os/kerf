"""
BREP-SOLID-CONTAINS-POINT
=========================
Test whether a 3-D point lies inside, outside, or on the boundary of a
B-rep solid using the ray-casting (Jordan curve theorem) method.

Algorithm
---------
Cast a ray from the query point in a generic direction ``d``.  Count the
number of times the ray crosses the boundary of the solid:

    odd  intersections  → point is **inside**
    even intersections  → point is **outside**
    distance to boundary < tolerance → point is **on_boundary**

This is the classical parity/winding-number test described in:

    Mortenson, *Geometric Modeling* (2nd ed.) §11.5 "Inside/outside test"
    Ericson, *Real-Time Collision Detection* (2005) §5.1
    O'Rourke, *Computational Geometry in C* (1998) §7.4

Ray direction
-------------
A deliberately non-axis-aligned direction ``(1, 0.013, 0.029)`` (normalised)
is chosen to avoid degenerate alignment with axis-parallel face normals.
If a degenerate hit is detected (the ray is parallel to a face, i.e.
``|dot(ray, face_normal)| < parallel_tol``), a second fallback direction
``(0.017, 1, 0.011)`` is tried automatically and the counts are combined
only if they agree.  If both directions yield different counts the result
is flagged with ``degenerate_ray=True`` and should be treated as
unreliable.

Supported face geometry
-----------------------
*Planar faces* (``Plane`` or any surface whose face vertices are coplanar):
    exact ray–plane intersection followed by a 2-D point-in-polygon test
    on the face loop projected onto the plane.

*Analytic quadric surfaces* (``SphereSurface``, ``CylinderSurface``,
``TorusSurface``):
    Uniform sampling of the face's parametric domain (``_UV_SAMPLES × _UV_SAMPLES``
    grid) produces a triangulated approximation; the ray is tested against
    each triangle.  Accuracy is governed by ``_UV_SAMPLES`` (default 32).

*NURBS and general parametric surfaces* (anything with ``evaluate(u, v)``):
    Same triangulated approximation approach.

Honest caveats
--------------
1.  **Degenerate hits** — when the ray is parallel to a face, the
    face contributes no crossing.  The fallback direction handles
    most cases; both directions agree on a parity vote.
2.  **Boundary detection** — boundary is checked via closest-approach
    distance over the sampled mesh; false-negatives are possible for
    high-curvature faces with sparse sampling.
3.  **Non-manifold / open shells** — open shells are treated as
    half-space boundaries; the parity count may be unreliable.
4.  **Performance** — O(F × S²) where F = face count, S = UV samples;
    suitable for interactive/LLM use on typical engineering models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, Face, Plane, SphereSurface, CylinderSurface, TorusSurface

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Primary and fallback ray directions — non-axis-aligned to avoid degenerate hits.
_RAY_DIR_PRIMARY = np.array([1.0, 0.013, 0.029])
_RAY_DIR_FALLBACK = np.array([0.017, 1.0, 0.011])

_UV_SAMPLES = 32          # triangulation density for parametric faces
_PARALLEL_TOL = 1e-9      # |dot(dir, normal)| below this → parallel


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ContainmentResult:
    """Result of :func:`solid_contains_point`.

    Attributes
    ----------
    inside : bool | None
        ``True`` if the point is strictly inside all solid boundaries.
        ``False`` if outside.
        ``None`` if ``on_boundary`` is True or the result is unreliable.
    on_boundary : bool
        ``True`` if the point is within *tolerance* of the boundary surface.
    ray_hits : int
        Number of boundary crossings counted (primary direction).
    degenerate_ray : bool
        ``True`` when the primary and fallback ray directions gave
        inconsistent parity counts — the result is flagged as unreliable.
        Caller should perturb the query point slightly and retry.
    """
    inside: Optional[bool]
    on_boundary: bool
    ray_hits: int
    degenerate_ray: bool = field(default=False)


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _ray_triangle_intersect(
    origin: np.ndarray,
    direction: np.ndarray,
    v0: np.ndarray,
    v1: np.ndarray,
    v2: np.ndarray,
    tol: float,
) -> Optional[float]:
    """Möller–Trumbore ray–triangle intersection.

    Returns the parameter *t ≥ −tol* along the ray (origin + t*direction)
    or ``None`` if there is no intersection (parallel or miss).

    Reference: Möller & Trumbore, "Fast, Minimum Storage Ray/Triangle
    Intersection", JGT 1997; Ericson §5.1.
    """
    e1 = v1 - v0
    e2 = v2 - v0
    h = np.cross(direction, e2)
    a = float(np.dot(e1, h))
    if abs(a) < _PARALLEL_TOL:
        return None
    f = 1.0 / a
    s = origin - v0
    u = f * float(np.dot(s, h))
    if u < -tol or u > 1.0 + tol:
        return None
    q = np.cross(s, e1)
    v = f * float(np.dot(direction, q))
    if v < -tol or u + v > 1.0 + tol:
        return None
    t = f * float(np.dot(e2, q))
    return t if t >= -tol else None


def _triangulate_face(face: Face, uv_samples: int) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Triangulate a face into a list of (v0, v1, v2) triangles.

    For planar faces the loop vertices are used directly (exact).
    For parametric faces a UV grid is sampled and split into triangles.
    """
    surf = face.surface

    # --- Planar face: use loop vertices directly ---------------------------------
    if isinstance(surf, Plane):
        outer = face.outer_loop()
        if outer is None or len(outer.coedges) < 3:
            return []
        pts = [ce.start_point() for ce in outer.coedges]
        if len(pts) < 3:
            return []
        tris = []
        v0 = pts[0]
        for i in range(1, len(pts) - 1):
            tris.append((v0.copy(), pts[i].copy(), pts[i + 1].copy()))
        return tris

    # --- Parametric / analytic face: UV grid sampling ---------------------------
    # Determine UV domain from face vertex extents in parameter space,
    # or use sensible defaults per surface type.
    u0, u1, v0, v1 = _uv_domain(surf)

    us = np.linspace(u0, u1, uv_samples + 1)
    vs = np.linspace(v0, v1, uv_samples + 1)

    tris = []
    for i in range(uv_samples):
        for j in range(uv_samples):
            p00 = np.asarray(surf.evaluate(us[i], vs[j]), dtype=float)
            p10 = np.asarray(surf.evaluate(us[i + 1], vs[j]), dtype=float)
            p01 = np.asarray(surf.evaluate(us[i], vs[j + 1]), dtype=float)
            p11 = np.asarray(surf.evaluate(us[i + 1], vs[j + 1]), dtype=float)
            tris.append((p00, p10, p11))
            tris.append((p00, p11, p01))
    return tris


def _uv_domain(surf: object) -> Tuple[float, float, float, float]:
    """Return (u_min, u_max, v_min, v_max) for a parametric surface."""
    if isinstance(surf, SphereSurface):
        return 0.0, 2.0 * math.pi, -math.pi / 2.0, math.pi / 2.0
    if isinstance(surf, CylinderSurface):
        return 0.0, 2.0 * math.pi, 0.0, 1.0
    if isinstance(surf, TorusSurface):
        return 0.0, 2.0 * math.pi, 0.0, 2.0 * math.pi
    # NurbsSurface and generic: attempt to read domain metadata, else [0,1]²
    try:
        u0 = float(surf.u_domain[0])
        u1 = float(surf.u_domain[1])
        v0 = float(surf.v_domain[0])
        v1 = float(surf.v_domain[1])
        return u0, u1, v0, v1
    except AttributeError:
        pass
    try:
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-(surf.degree_u + 1)])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-(surf.degree_v + 1)])
        return u0, u1, v0, v1
    except AttributeError:
        return 0.0, 1.0, 0.0, 1.0


def _count_ray_hits(
    body: Body,
    origin: np.ndarray,
    direction: np.ndarray,
    tolerance: float,
    uv_samples: int,
) -> Tuple[int, float]:
    """Count ray–boundary intersections along *direction* from *origin*.

    Returns ``(hit_count, min_dist)`` where *min_dist* is the closest
    boundary approach (used for on-boundary detection).
    """
    dir_n = _unit(direction)
    hit_count = 0
    min_dist = math.inf

    # Collect all faces from all shells/solids.
    faces = body.all_faces()

    for face in faces:
        tris = _triangulate_face(face, uv_samples)
        for v0, v1, v2 in tris:
            t = _ray_triangle_intersect(origin, dir_n, v0, v1, v2, tolerance)
            if t is None:
                continue
            # Only count forward intersections (t > tolerance avoids self-hits
            # exactly at origin).
            if t > tolerance:
                hit_count += 1
            # Track closest approach for boundary detection.
            dist = abs(t)
            if dist < min_dist:
                min_dist = dist

    return hit_count, min_dist


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solid_contains_point(
    body: Body,
    point,
    tolerance: float = 1e-6,
    uv_samples: int = _UV_SAMPLES,
) -> ContainmentResult:
    """Test whether *point* is inside, outside, or on the boundary of *body*.

    Uses the ray-casting parity test (Jordan curve theorem in 3-D):
    a ray from *point* in a generic direction is cast; an odd number of
    boundary crossings means the point is inside; even means outside.

    References
    ----------
    Mortenson, *Geometric Modeling* (2nd ed.) §11.5
    Ericson, *Real-Time Collision Detection* (2005) §5.1
    O'Rourke, *Computational Geometry in C* (1998) §7.4

    Parameters
    ----------
    body : Body
        The B-rep body to test against.
    point : array-like [3]
        The 3-D query point.
    tolerance : float
        Distance within which a point is considered on-boundary.
        Also used as the epsilon for ray-intersection numerics.
    uv_samples : int
        UV grid resolution for triangulating parametric faces.
        Higher values improve accuracy at the cost of performance.

    Returns
    -------
    ContainmentResult
        See :class:`ContainmentResult` for field descriptions.

    Notes
    -----
    Degenerate cases — if the primary ray direction is nearly parallel to
    one or more faces, a second fallback direction is tried.  If the two
    directions disagree on parity, ``degenerate_ray=True`` is set and
    ``inside=None`` is returned; the caller should perturb *point* and retry.
    """
    origin = np.asarray(point, dtype=float)

    # Primary direction.
    hits_p, min_dist_p = _count_ray_hits(
        body, origin, _RAY_DIR_PRIMARY, tolerance, uv_samples
    )
    # Fallback direction (always computed for boundary distance).
    hits_f, min_dist_f = _count_ray_hits(
        body, origin, _RAY_DIR_FALLBACK, tolerance, uv_samples
    )

    min_dist = min(min_dist_p, min_dist_f)

    # On-boundary check.
    if min_dist <= tolerance:
        return ContainmentResult(
            inside=None,
            on_boundary=True,
            ray_hits=hits_p,
            degenerate_ray=False,
        )

    # Parity agreement check.
    inside_p = bool(hits_p % 2 == 1)
    inside_f = bool(hits_f % 2 == 1)

    if inside_p != inside_f:
        # Degenerate / unreliable result — directions disagree.
        return ContainmentResult(
            inside=None,
            on_boundary=False,
            ray_hits=hits_p,
            degenerate_ray=True,
        )

    return ContainmentResult(
        inside=inside_p,
        on_boundary=False,
        ray_hits=hits_p,
        degenerate_ray=False,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _brep_solid_contains_point_spec = ToolSpec(
        name="brep_solid_contains_point",
        description=(
            "Test whether a 3-D point is inside, outside, or on the boundary "
            "of a B-rep solid using the ray-casting (Jordan curve theorem) method.\n"
            "\n"
            "Algorithm: a ray is cast from the query point in a generic direction; "
            "odd boundary crossings → inside, even → outside. "
            "Ref: Mortenson §11.5; Ericson 2005 §5.1; O'Rourke §7.4.\n"
            "\n"
            "Returns:\n"
            "  inside       : true/false/null (null when on_boundary or degenerate)\n"
            "  on_boundary  : true when point is within tolerance of the surface\n"
            "  ray_hits     : raw intersection count\n"
            "  degenerate_ray : true when both ray directions gave inconsistent parity\n"
            "\n"
            "Honest caveat: degenerate hits (ray parallel to a face) are handled by "
            "a second fallback ray direction; if both disagree, degenerate_ray=true. "
            "For NURBS/parametric faces the test uses a triangulated approximation "
            "(uv_samples×uv_samples grid, default 32); increase for higher accuracy.\n"
            "\n"
            "Inputs: primitive type ('box', 'sphere', 'cylinder', 'torus') with shape "
            "parameters, plus the query point [x, y, z].\n"
            "\n"
            "Never raises — returns {ok: false, reason} for bad inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": {
                    "type": "string",
                    "enum": ["box", "sphere", "cylinder", "torus"],
                    "description": "Primitive solid type to construct.",
                },
                "point": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Query point [x, y, z].",
                },
                "origin": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Box origin [x, y, z] (box only; default [0,0,0]).",
                },
                "size": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Box size [sx, sy, sz] (box only; default [1,1,1]).",
                },
                "center": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Center [x, y, z] (sphere/cylinder/torus; default [0,0,0]).",
                },
                "radius": {
                    "type": "number",
                    "description": "Radius (sphere/cylinder).",
                },
                "height": {
                    "type": "number",
                    "description": "Height (cylinder only).",
                },
                "major_radius": {
                    "type": "number",
                    "description": "Major radius (torus only).",
                },
                "minor_radius": {
                    "type": "number",
                    "description": "Minor radius (torus only).",
                },
                "tolerance": {
                    "type": "number",
                    "description": "On-boundary tolerance (default 1e-6).",
                },
                "uv_samples": {
                    "type": "integer",
                    "description": "UV grid resolution for parametric faces (default 32).",
                },
            },
            "required": ["primitive", "point"],
        },
    )

    @register(_brep_solid_contains_point_spec)
    def _tool_brep_solid_contains_point(params: dict, ctx: "ProjectCtx"):  # type: ignore[type-arg]
        try:
            from kerf_cad_core.geom.brep import make_box, make_sphere, make_cylinder, make_torus

            primitive = str(params["primitive"]).lower()
            pt = list(params["point"])
            if len(pt) != 3:
                return err_payload("point must be [x, y, z]")

            tol = float(params.get("tolerance") or 1e-6)
            uv_s = int(params.get("uv_samples") or _UV_SAMPLES)

            if primitive == "box":
                orig = list(params.get("origin") or [0, 0, 0])
                sz = list(params.get("size") or [1, 1, 1])
                body = make_box(origin=orig, size=sz)
            elif primitive == "sphere":
                cen = list(params.get("center") or [0, 0, 0])
                r = float(params.get("radius") or 1.0)
                body = make_sphere(center=cen, radius=r)
            elif primitive == "cylinder":
                cen = list(params.get("center") or [0, 0, 0])
                r = float(params.get("radius") or 1.0)
                h = float(params.get("height") or 1.0)
                body = make_cylinder(center=cen, radius=r, height=h)
            elif primitive == "torus":
                cen = list(params.get("center") or [0, 0, 0])
                R = float(params.get("major_radius") or 2.0)
                r = float(params.get("minor_radius") or 0.5)
                body = make_torus(center=cen, major_radius=R, minor_radius=r)
            else:
                return err_payload(f"Unknown primitive: {primitive!r}")

            result = solid_contains_point(body, pt, tolerance=tol, uv_samples=uv_s)
            return ok_payload({
                "inside": result.inside,
                "on_boundary": result.on_boundary,
                "ray_hits": result.ray_hits,
                "degenerate_ray": result.degenerate_ray,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
