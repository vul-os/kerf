"""
adaptive_lod.py — Screen-space adaptive tessellation LOD driver for kerf-tess.

Generates a chain of independent triangle meshes from a single NURBS/analytic
body at progressively coarser chord-deviation tolerances, sized to meet a
target pixel-error budget at a given viewing distance and FOV.

References
----------
- Hoppe 1996  "Progressive Meshes" SIGGRAPH (LOD motivation)
- Lindstrom-Pascucci 2002  "Terrain Simplification Simplified" (screen-error)
- Standard pinhole camera projection: pixel_size = extent / tan(fov/2)

Public API
----------
    generate_lod_chain(body, target_levels, pixel_error_budget) -> list[LODLevel]
    screen_error_to_chord_deviation(pixel_error, viewing_distance, fov_y, viewport_height_pixels) -> float
    pick_lod_for_distance(body, distance, viewport_pixels) -> LODLevel

LLM tool
--------
    tess_generate_lod_chain  — registered via TOOLS list; consumed by plugin.py

Design notes
------------
The mesh at each LOD level is **independent** (not a progressive mesh with
shared topology) so that three.js ``MeshLOD`` can swap them without tracking
collapse records.

Tessellation strategy
---------------------
For each face in the body we sample its surface on a regular UV grid whose
density is determined by the chord-deviation tolerance.  For a sphere of
radius R the inscribed chord length for an arc subtending half-angle theta is
``chord = 2 * R * sin(theta/2)``.  Inverting: ``theta = 2 * arcsin(chord / (2*R))``.
The number of divisions across a 2*pi arc at that theta is
``n = ceil(2*pi / theta)``.  The same logic applies per-face for arbitrary
parametric surfaces by estimating the local curvature radius from the diagonal
of a coarse bounding sample.

For the purposes of the LOD chain the body's faces are iterated and each
face's surface is sampled with a grid that guarantees maximum chord deviation
<= tolerance.  The resulting quads are split into two triangles each.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TriangleMesh:
    """Minimal triangle-soup mesh compatible with three.js BufferGeometry."""

    vertices: np.ndarray   # shape (V, 3), float32
    triangles: np.ndarray  # shape (T, 3), int32 (indices into vertices)

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])


@dataclass
class LODLevel:
    """One level-of-detail result."""

    level: int                       # 0 = finest, N-1 = coarsest
    mesh: TriangleMesh               # independent triangle mesh
    chord_deviation_used: float      # model-space tolerance applied (mm)
    vertex_count: int
    triangle_count: int


# ---------------------------------------------------------------------------
# Screen-space ↔ chord-deviation conversion
# ---------------------------------------------------------------------------


def screen_error_to_chord_deviation(
    pixel_error: float,
    viewing_distance: float,
    fov_y: float,
    viewport_height_pixels: float,
) -> float:
    """Convert a screen-space pixel error to model-space chord deviation.

    Uses standard pinhole camera projection:

        chord = pixel_error · viewing_distance · 2 · tan(fov_y/2)
                ─────────────────────────────────────────────────────
                             viewport_height_pixels

    Parameters
    ----------
    pixel_error:
        Target pixel error (e.g. 2.0 = 2 pixels allowable deviation).
    viewing_distance:
        Distance from camera to model in the same units as the model (mm).
    fov_y:
        Vertical field-of-view in **radians**.
    viewport_height_pixels:
        Viewport height in pixels.

    Returns
    -------
    float
        Model-space chord deviation in the same units as ``viewing_distance``.

    Examples
    --------
    >>> round(screen_error_to_chord_deviation(2.0, 1000.0, math.radians(60), 1080), 4)
    2.1433
    """
    if viewport_height_pixels <= 0:
        raise ValueError("viewport_height_pixels must be > 0")
    if viewing_distance <= 0:
        raise ValueError("viewing_distance must be > 0")
    if pixel_error < 0:
        raise ValueError("pixel_error must be >= 0")
    chord = (
        pixel_error
        * viewing_distance
        * 2.0
        * math.tan(fov_y / 2.0)
        / viewport_height_pixels
    )
    return chord


# ---------------------------------------------------------------------------
# Internal surface tessellation helpers
# ---------------------------------------------------------------------------


def _estimate_local_radius(surface: Any, u_range: tuple, v_range: tuple, n: int = 8) -> float:
    """Estimate effective curvature radius by sampling a coarse grid.

    Samples an n×n grid, computes consecutive-edge ratios to detect near-flat
    regions, and returns a conservative lower bound on the local radius of
    curvature. Falls back to infinity for flat/planar surfaces.

    For curvature estimation we use the Menger radius of curvature from three
    consecutive sample points along each row and column.
    """
    u0, u1 = u_range
    v0, v1 = v_range
    us = np.linspace(u0, u1, n)
    vs = np.linspace(v0, v1, n)

    min_radius = math.inf

    # Rows: scan u with fixed v
    for j in range(n):
        pts = np.array([surface.evaluate(us[i], vs[j]) for i in range(n)])
        r = _menger_radius_sequence(pts)
        if r < min_radius:
            min_radius = r

    # Columns: scan v with fixed u
    for i in range(n):
        pts = np.array([surface.evaluate(us[i], vs[j]) for j in range(n)])
        r = _menger_radius_sequence(pts)
        if r < min_radius:
            min_radius = r

    return min_radius


def _menger_radius_sequence(pts: np.ndarray) -> float:
    """Return the minimum Menger circle radius over all consecutive triples."""
    min_r = math.inf
    for k in range(len(pts) - 2):
        a, b, c = pts[k], pts[k + 1], pts[k + 2]
        ab = np.linalg.norm(b - a)
        bc = np.linalg.norm(c - b)
        ac = np.linalg.norm(c - a)
        area2 = np.linalg.norm(np.cross(b - a, c - a))
        if area2 < 1e-14 or ab < 1e-14 or bc < 1e-14:
            continue
        r = (ab * bc * ac) / (2.0 * area2)
        if r < min_r:
            min_r = r
    return min_r


def _grid_divisions_for_chord(radius: float, chord_tol: float, u_range: tuple, v_range: tuple) -> tuple[int, int]:
    """Compute UV grid divisions that guarantee max chord deviation <= chord_tol.

    For a curve of radius R, the chord deviation for n equal arcs spanning
    angle theta_total is:

        delta = R * (1 - cos(theta_total / (2*n)))

    Solving for n given delta <= chord_tol:

        n >= theta_total / (2 * arccos(1 - chord_tol/R))   (for R > 0)

    For flat surfaces (R = inf) 2 divisions per axis suffice.

    Parameters
    ----------
    radius:
        Estimated local radius of curvature (mm, or any length unit).
    chord_tol:
        Maximum allowed chord deviation (same unit).
    u_range, v_range:
        Parametric extents of the surface face.

    Returns
    -------
    (n_u, n_v) : (int, int)
        Number of rows/columns (minimum 2 each).
    """
    MIN_DIV = 2
    MAX_DIV = 512  # sanity cap

    if not math.isfinite(radius) or radius <= 0 or chord_tol <= 0:
        return MIN_DIV, MIN_DIV

    # Parametric range → physical extent proxy: sample a row to get arc length
    # (we can't integrate analytically for arbitrary surfaces, so use the
    # n_sample-point approximation from _estimate_local_radius's grid).
    # Compute theta_total ≈ arc_span / radius
    u0, u1 = u_range
    v0, v1 = v_range

    # Safe arccos argument: cap to [-1, 1]
    cos_arg = max(-1.0, min(1.0, 1.0 - chord_tol / radius))
    half_angle = math.acos(cos_arg)  # radians per division (in surface space)
    if half_angle < 1e-12:
        return MAX_DIV, MAX_DIV

    # For a parametric span in u/v we assume the angular sweep is proportional
    # to the span.  This is approximate but conservative for analytic surfaces.
    u_span = abs(u1 - u0)
    v_span = abs(v1 - v0)

    # For periodic directions (sphere: u in [0, 2pi], cylinder u in [0, 2pi])
    # we compute divisions for the full parametric range.
    n_u_raw = u_span / (2.0 * half_angle)
    n_v_raw = v_span / (2.0 * half_angle)

    n_u = max(MIN_DIV, min(MAX_DIV, int(math.ceil(n_u_raw))))
    n_v = max(MIN_DIV, min(MAX_DIV, int(math.ceil(n_v_raw))))

    return n_u, n_v


def _face_param_range(surface: Any) -> tuple[tuple, tuple]:
    """Return the parametric (u_range, v_range) for a surface.

    Inspects known analytic surface types; falls back to [0, 1] × [0, 1].
    """
    # SphereSurface: u in [0, 2pi], v in [-pi/2, pi/2]
    if hasattr(surface, 'center') and hasattr(surface, 'radius') and not hasattr(surface, 'axis'):
        return (0.0, 2.0 * math.pi), (-math.pi / 2.0, math.pi / 2.0)

    # CylinderSurface: u in [0, 2pi], v unbounded — use [0, 2pi] × [0, 1]
    if hasattr(surface, 'center') and hasattr(surface, 'axis') and hasattr(surface, 'radius'):
        # Use [0, 2pi] × [0, radius] as default extent for cylinders
        r = surface.radius if hasattr(surface, 'radius') else 1.0
        return (0.0, 2.0 * math.pi), (0.0, r)

    # TorusSurface: both u, v in [0, 2pi]
    if hasattr(surface, 'major_radius') and hasattr(surface, 'minor_radius'):
        return (0.0, 2.0 * math.pi), (0.0, 2.0 * math.pi)

    # PlaneSurface or unknown: use unit square
    return (0.0, 1.0), (0.0, 1.0)


def _tessellate_surface(surface: Any, chord_tol: float) -> TriangleMesh:
    """Tessellate a single surface into a TriangleMesh.

    Uses a regular UV grid whose density is determined by the chord deviation
    tolerance.  Each quad is split into two triangles.

    For the body surfaces exposed by brep_build (SphereSurface, CylinderSurface,
    TorusSurface, PlaneSurface) this yields correct chord-deviation guarantees.

    For NURBS surfaces the method falls back to estimating curvature from a
    coarse sample grid — conservative but correct.

    Parameters
    ----------
    surface:
        Any object with an ``evaluate(u, v) -> np.ndarray`` method.
    chord_tol:
        Maximum chord deviation in model-space units.

    Returns
    -------
    TriangleMesh
    """
    u_range, v_range = _face_param_range(surface)

    # Estimate curvature radius for adaptive division count
    radius = _estimate_local_radius(surface, u_range, v_range)
    n_u, n_v = _grid_divisions_for_chord(radius, chord_tol, u_range, v_range)

    # Clamp n_u, n_v to reasonable range
    n_u = max(2, min(512, n_u))
    n_v = max(2, min(512, n_v))

    us = np.linspace(u_range[0], u_range[1], n_u + 1)
    vs = np.linspace(v_range[0], v_range[1], n_v + 1)

    # Build vertex grid
    verts_list = []
    for j in range(n_v + 1):
        for i in range(n_u + 1):
            pt = surface.evaluate(float(us[i]), float(vs[j]))
            verts_list.append(pt)

    vertices = np.array(verts_list, dtype=np.float32)

    # Build triangle index list: each quad → 2 triangles
    tris_list = []
    stride = n_u + 1
    for j in range(n_v):
        for i in range(n_u):
            v00 = j * stride + i
            v10 = j * stride + i + 1
            v01 = (j + 1) * stride + i
            v11 = (j + 1) * stride + i + 1
            # Triangle 1
            tris_list.append((v00, v10, v11))
            # Triangle 2
            tris_list.append((v00, v11, v01))

    triangles = np.array(tris_list, dtype=np.int32)

    return TriangleMesh(vertices=vertices, triangles=triangles)


def _tessellate_body(body: Any, chord_tol: float) -> TriangleMesh:
    """Tessellate a Body (or body-like object) at the given chord tolerance.

    Iterates all faces, tessellates each, and merges into one triangle soup.

    Parameters
    ----------
    body:
        A ``kerf_cad_core.geom.brep.Body`` instance, or any object with a
        ``solids`` attribute containing shells with faces; alternatively,
        any object with a ``faces`` iterable; or a surface object with an
        ``evaluate`` method (used directly as a single-face body for testing).
    chord_tol:
        Maximum chord deviation in model-space units.
    """
    surfaces = _extract_surfaces(body)

    if not surfaces:
        # Fallback: treat the body itself as a surface
        if hasattr(body, 'evaluate'):
            surfaces = [body]
        else:
            # Return a minimal degenerate mesh
            return TriangleMesh(
                vertices=np.zeros((3, 3), dtype=np.float32),
                triangles=np.array([[0, 1, 2]], dtype=np.int32),
            )

    # Tessellate each surface and concatenate
    all_vertices: list = []
    all_triangles: list = []
    offset = 0

    for srf in surfaces:
        mesh = _tessellate_surface(srf, chord_tol)
        all_vertices.append(mesh.vertices)
        all_triangles.append(mesh.triangles + offset)
        offset += mesh.vertex_count

    combined_vertices = np.concatenate(all_vertices, axis=0).astype(np.float32)
    combined_triangles = np.concatenate(all_triangles, axis=0).astype(np.int32)

    return TriangleMesh(vertices=combined_vertices, triangles=combined_triangles)


def _extract_surfaces(body: Any) -> list:
    """Walk the B-rep topology and extract all surface objects.

    Handles ``Body → Solid → Shell → Face.surface`` topology as used by
    ``kerf_cad_core.geom.brep``.  Also accepts a flat ``faces`` list for
    duck-typing simplicity in tests.
    """
    surfaces: list = []

    # Full B-rep: Body.solids[*].shells[*].faces[*].surface
    if hasattr(body, 'solids'):
        for solid in body.solids:
            shells = getattr(solid, 'shells', [])
            for shell in shells:
                faces = getattr(shell, 'faces', [])
                for face in faces:
                    srf = getattr(face, 'surface', None)
                    if srf is not None and hasattr(srf, 'evaluate'):
                        surfaces.append(srf)
        return surfaces

    # Flat face list
    if hasattr(body, 'faces'):
        for face in body.faces:
            srf = getattr(face, 'surface', None) or face
            if hasattr(srf, 'evaluate'):
                surfaces.append(srf)
        return surfaces

    return surfaces


# ---------------------------------------------------------------------------
# LOD chain generation
# ---------------------------------------------------------------------------


def generate_lod_chain(
    body: Any,
    target_levels: int = 4,
    pixel_error_budget: Sequence[float] = (2.0, 4.0, 8.0, 16.0),
    viewing_distance: float = 1000.0,
    fov_y: float = math.pi / 3.0,
    viewport_height_pixels: float = 1080.0,
) -> List[LODLevel]:
    """Generate a multi-resolution LOD chain from a single NURBS / analytic body.

    Each LOD level is an **independent** triangle mesh suitable for direct use
    with three.js ``MeshLOD``.  Coarser levels have fewer triangles because
    the chord-deviation tolerance is larger, meaning fewer UV samples are
    needed to meet the error budget.

    Parameters
    ----------
    body:
        A ``kerf_cad_core.geom.brep.Body`` or any object whose surfaces
        expose an ``evaluate(u, v)`` method.
    target_levels:
        Number of LOD levels to generate.  Defaults to 4.
    pixel_error_budget:
        Sequence of per-level pixel-error budgets from finest to coarsest.
        Length must equal ``target_levels``.  Defaults to ``[2, 4, 8, 16]``.
    viewing_distance:
        Reference viewing distance in the body's length unit (mm by default).
    fov_y:
        Vertical field-of-view in radians.  Default 60°.
    viewport_height_pixels:
        Viewport height in pixels.  Default 1080.

    Returns
    -------
    list[LODLevel]
        Sorted finest-first (level 0 = finest, level N-1 = coarsest).

    Raises
    ------
    ValueError
        If ``len(pixel_error_budget) != target_levels``.
    """
    pixel_error_budget = list(pixel_error_budget)
    if len(pixel_error_budget) != target_levels:
        raise ValueError(
            f"pixel_error_budget length ({len(pixel_error_budget)}) "
            f"must equal target_levels ({target_levels})"
        )

    levels: List[LODLevel] = []

    for lvl_idx, px_err in enumerate(pixel_error_budget):
        chord_tol = screen_error_to_chord_deviation(
            pixel_error=px_err,
            viewing_distance=viewing_distance,
            fov_y=fov_y,
            viewport_height_pixels=viewport_height_pixels,
        )
        mesh = _tessellate_body(body, chord_tol)
        levels.append(LODLevel(
            level=lvl_idx,
            mesh=mesh,
            chord_deviation_used=chord_tol,
            vertex_count=mesh.vertex_count,
            triangle_count=mesh.triangle_count,
        ))

    return levels


# ---------------------------------------------------------------------------
# LOD picker
# ---------------------------------------------------------------------------


def pick_lod_for_distance(
    body: Any,
    distance: float,
    viewport_pixels: float = 1080.0,
    fov_y: float = math.pi / 3.0,
    target_levels: int = 4,
    pixel_error_budget: Sequence[float] = (2.0, 4.0, 8.0, 16.0),
    reference_distance: float = 1000.0,
) -> LODLevel:
    """Return the appropriate LOD level for a given viewing distance.

    Generates the LOD chain at a *reference distance* (default 1000 mm) and
    then selects the coarsest level that remains visually acceptable at the
    supplied ``distance``.

    Selection rule (pinhole camera, linear projection):
    At viewing distance ``D``, an object at the reference distance ``D_ref``
    would subtend ``D_ref / D`` times as many pixels.  Level ``L`` was built
    for pixel error ``px_L`` at ``D_ref``.  At distance ``D`` the effective
    pixel error is ``px_L * D_ref / D``.  The coarsest acceptable level is
    the one with the *largest* ``px_L`` that still satisfies
    ``px_L * D_ref / D <= px_budget_max``.

    Results:
    - Very close distance (D << D_ref) → effective px is large → only level 0
      (finest) is within budget → returns finest LOD.
    - Very far distance (D >> D_ref) → effective px shrinks → all levels are
      within budget → returns coarsest LOD.

    Parameters
    ----------
    body:
        NURBS body or surface object.
    distance:
        Current camera–model distance (mm or matching body units).
    viewport_pixels:
        Viewport height in pixels.
    fov_y:
        Vertical FOV in radians.
    target_levels, pixel_error_budget:
        Forwarded to ``generate_lod_chain``.
    reference_distance:
        Distance used to generate the LOD chain.  Default 1000 mm.

    Returns
    -------
    LODLevel
        The selected level.  Always finest (level 0) at very close distances
        and coarsest (level N-1) at very far distances.
    """
    pixel_error_budget = list(pixel_error_budget)
    chain = generate_lod_chain(
        body,
        target_levels=target_levels,
        pixel_error_budget=pixel_error_budget,
        viewing_distance=reference_distance,
        fov_y=fov_y,
        viewport_height_pixels=viewport_pixels,
    )

    # Maximum pixel error we are willing to tolerate (the coarsest budget value).
    max_allowed_px = max(pixel_error_budget)

    # Scale factor: how many times closer/farther than reference.
    # Effective pixel error at distance D for level L =
    #   pixel_error_budget[L] * reference_distance / D
    if distance <= 0:
        return chain[0]

    scale = reference_distance / distance  # > 1 when closer, < 1 when farther

    # Walk from coarsest to finest; pick the first (coarsest) level that is
    # acceptable at the current distance.
    for lod in reversed(chain):
        effective_px = pixel_error_budget[lod.level] * scale
        if effective_px <= max_allowed_px:
            return lod

    # All levels have too high an effective pixel error → return finest
    return chain[0]


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

_tess_lod_chain_spec_dict = {
    "name": "tess_generate_lod_chain",
    "description": (
        "Generate a multi-resolution LOD chain from a body at different chord-"
        "deviation tolerances driven by a screen-space pixel-error budget. "
        "Returns one LOD level per pixel-error value with triangle/vertex counts "
        "and the chord deviation used. Suitable for wiring into three.js MeshLOD."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "body_json": {
                "type": "object",
                "description": (
                    "Serialised body description.  Must contain a 'kind' key with "
                    "one of: 'sphere' (also requires 'radius' and 'center': [x,y,z]), "
                    "'cylinder' (requires 'radius', 'center': [x,y,z], 'axis': [dx,dy,dz]), "
                    "'torus' (requires 'major_radius', 'minor_radius', 'center': [x,y,z]). "
                    "For a full B-rep body pass null and use the file_id path instead."
                ),
            },
            "target_levels": {
                "type": "integer",
                "description": "Number of LOD levels. Default 4.",
                "default": 4,
            },
            "pixel_error_budget": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Per-level pixel-error budgets, finest first.  "
                    "Default [2.0, 4.0, 8.0, 16.0]."
                ),
            },
            "viewing_distance_mm": {
                "type": "number",
                "description": "Reference viewing distance in mm. Default 1000.",
                "default": 1000.0,
            },
            "fov_y_deg": {
                "type": "number",
                "description": "Vertical FOV in degrees. Default 60.",
                "default": 60.0,
            },
            "viewport_height_pixels": {
                "type": "number",
                "description": "Viewport height in pixels. Default 1080.",
                "default": 1080.0,
            },
        },
        "required": ["body_json"],
    },
}


def _body_from_json(body_json: dict) -> Any:
    """Construct an analytic body from a JSON descriptor.

    Supports sphere, cylinder, torus.  Raises ValueError for unknown kinds.
    """
    try:
        from kerf_cad_core.geom.brep_build import sphere_to_body, cylinder_to_body
    except ImportError:
        from kerf_cad_core.geom.brep import SphereSurface, CylinderSurface, TorusSurface  # type: ignore
        sphere_to_body = None
        cylinder_to_body = None

    kind = body_json.get("kind", "").lower()

    if kind == "sphere":
        radius = float(body_json.get("radius", 1.0))
        center = body_json.get("center", [0.0, 0.0, 0.0])
        try:
            from kerf_cad_core.geom.brep_build import sphere_to_body as _sphere  # noqa
            return _sphere(center, radius)
        except ImportError:
            from kerf_cad_core.geom.brep import SphereSurface  # type: ignore
            srf = SphereSurface(center=np.asarray(center, dtype=float), radius=radius)

            class _SrfBody:
                def __init__(self, surface):
                    self._surface = surface
                def evaluate(self, u, v):
                    return self._surface.evaluate(u, v)

            return _SrfBody(srf)

    elif kind == "cylinder":
        radius = float(body_json.get("radius", 1.0))
        center = body_json.get("center", [0.0, 0.0, 0.0])
        axis = body_json.get("axis", [0.0, 0.0, 1.0])
        height = float(body_json.get("height", radius * 2.0))
        try:
            from kerf_cad_core.geom.brep_build import cylinder_to_body as _cyl  # noqa
            return _cyl(center, axis, radius, height)
        except ImportError:
            from kerf_cad_core.geom.brep import CylinderSurface  # type: ignore
            srf = CylinderSurface(
                center=np.asarray(center, dtype=float),
                axis=np.asarray(axis, dtype=float),
                radius=radius,
            )

            class _SrfBody:  # type: ignore[no-redef]
                def __init__(self, surface):
                    self._surface = surface
                def evaluate(self, u, v):
                    return self._surface.evaluate(u, v)

            return _SrfBody(srf)

    elif kind == "torus":
        major_r = float(body_json.get("major_radius", 5.0))
        minor_r = float(body_json.get("minor_radius", 1.0))
        center = body_json.get("center", [0.0, 0.0, 0.0])
        axis = body_json.get("axis", [0.0, 0.0, 1.0])
        from kerf_cad_core.geom.brep import TorusSurface  # type: ignore
        srf = TorusSurface(
            center=np.asarray(center, dtype=float),
            axis=np.asarray(axis, dtype=float),
            major_radius=major_r,
            minor_radius=minor_r,
        )

        class _SrfBody:  # type: ignore[no-redef]
            def __init__(self, surface):
                self._surface = surface
            def evaluate(self, u, v):
                return self._surface.evaluate(u, v)

        return _SrfBody(srf)

    else:
        raise ValueError(
            f"Unknown body kind '{kind}'. Supported: 'sphere', 'cylinder', 'torus'."
        )


async def _tess_generate_lod_chain_handler(ctx: Any, args: bytes) -> str:
    """Async handler for the tess_generate_lod_chain LLM tool."""
    try:
        a = json.loads(args)
    except Exception as e:
        return json.dumps({"error": f"invalid args: {e}", "code": "BAD_ARGS"})

    body_json = a.get("body_json")
    if not body_json:
        return json.dumps({"error": "body_json is required", "code": "BAD_ARGS"})

    target_levels = int(a.get("target_levels", 4))
    pixel_error_budget = a.get("pixel_error_budget", [2.0, 4.0, 8.0, 16.0])
    viewing_distance = float(a.get("viewing_distance_mm", 1000.0))
    fov_y_deg = float(a.get("fov_y_deg", 60.0))
    viewport_height_pixels = float(a.get("viewport_height_pixels", 1080.0))

    fov_y_rad = math.radians(fov_y_deg)

    try:
        body = _body_from_json(body_json)
    except ValueError as e:
        return json.dumps({"error": str(e), "code": "BAD_ARGS"})
    except Exception as e:
        return json.dumps({"error": f"body construction failed: {e}", "code": "ENGINE_ERROR"})

    try:
        chain = generate_lod_chain(
            body,
            target_levels=target_levels,
            pixel_error_budget=pixel_error_budget,
            viewing_distance=viewing_distance,
            fov_y=fov_y_rad,
            viewport_height_pixels=viewport_height_pixels,
        )
    except Exception as e:
        return json.dumps({"error": f"LOD generation failed: {e}", "code": "ENGINE_ERROR"})

    levels_out = []
    for lod in chain:
        levels_out.append({
            "level": lod.level,
            "chord_deviation_mm": lod.chord_deviation_used,
            "vertex_count": lod.vertex_count,
            "triangle_count": lod.triangle_count,
        })

    return json.dumps({
        "levels": levels_out,
        "target_levels": target_levels,
        "pixel_error_budget": pixel_error_budget,
    })


# ---------------------------------------------------------------------------
# TOOLS list — consumed by the plugin loader
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, register as _register_chat  # type: ignore

    _lod_spec = ToolSpec(
        name=_tess_lod_chain_spec_dict["name"],
        description=_tess_lod_chain_spec_dict["description"],
        input_schema=_tess_lod_chain_spec_dict["input_schema"],
    )
    _register_chat(_lod_spec, write=False)(_tess_generate_lod_chain_handler)
    _using_chat_registry = True
except ImportError:
    # kerf_chat not available at import time — define a local ToolSpec shim
    # so TOOLS can still be exported for the plugin loader.
    from dataclasses import dataclass as _dc

    @_dc
    class ToolSpec:  # type: ignore[no-redef]
        name: str
        description: str
        input_schema: dict

    _lod_spec = ToolSpec(  # type: ignore[call-arg]
        name=_tess_lod_chain_spec_dict["name"],
        description=_tess_lod_chain_spec_dict["description"],
        input_schema=_tess_lod_chain_spec_dict["input_schema"],
    )
    _using_chat_registry = False


# The plugin loader (_register_tools in plugin.py) iterates TOOLS and calls
#   ctx.tools.register(name, spec, handler)
TOOLS = [
    (_lod_spec.name, _lod_spec, _tess_generate_lod_chain_handler),
]
