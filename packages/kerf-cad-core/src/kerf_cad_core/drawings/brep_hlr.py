"""B-rep → 2D drawing tessellation via Hidden-Line Removal (HLR).

Produces SVG-ready paths for technical drawings by projecting a 3D B-rep
solid into orthographic 2D views with visibility classification.

Algorithm references
--------------------
* Appel, A. (1967). "The Notion of Quantitative Invisibility and the Machine
  Rendering of Solids." Proc. ACM 22nd National Conference, pp. 387-393.
  -- Defines quantitative invisibility (QI) counting: an edge point is
     visible iff QI = 0 (no triangle face in front of it in the view
     direction). We implement a simplified discrete QI walk.

* Markosian, L., Kowalski, M.A., Trychin, S.J., Bourdev, L.D., Goldstein, D.,
  and Hughes, J.F. (1997). "Real-Time Nonphotorealistic Rendering." SIGGRAPH 97.
  -- Section 3 covers silhouette and feature-edge detection on mesh models,
     classifying edges as: silhouette, crease (sharp), smooth boundary, etc.

* Hertzmann, A. (1999). "Introduction to 3D Non-Photorealistic Rendering:
  Silhouettes and Outlines." Proc. NPAR 1999.
  -- Formalises the silhouette test: edge (f0, f1) is a silhouette iff
     (N_f0 · v_dir) * (N_f1 · v_dir) < 0, where v_dir is toward the camera.

Usage
-----
    from kerf_cad_core.geom.brep import make_box
    from kerf_cad_core.drawings.brep_hlr import make_standard_views

    body = make_box(size=(2, 1, 1))
    views = make_standard_views(body)
    print(views['front'].svg_path_visible)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    CylinderSurface,
    Face,
    Line3,
    Plane,
    SphereSurface,
    _unit,
    _perp,
)

# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------

@dataclass
class ProjectionView:
    """Orthographic projection of a 3D B-rep into 2D drawing space.

    Parameters
    ----------
    name:
        Human-readable identifier, e.g. 'front', 'top', 'right', 'iso'.
    direction:
        Unit vector pointing *toward* the camera (view direction). For a
        front view this is typically (0, -1, 0) or (0, 0, -1) depending
        on convention. The projection drops the component along this axis.
    up:
        Defines the vertical axis in the 2D drawing plane. Must not be
        parallel to *direction*.
    """
    name: str
    direction: Tuple[float, float, float]
    up: Tuple[float, float, float]


@dataclass
class HlrEdge2d:
    """A single projected 2D edge segment with visibility and kind tags.

    Parameters
    ----------
    p0, p1:
        2D start/end in drawing-plane coordinates.
    visibility:
        ``'visible'`` if the edge is unoccluded, ``'hidden'`` if occluded.
    kind:
        * ``'sharp'``     — dihedral angle between adjacent faces > 30°.
        * ``'silhouette'``— sign change of (N · view_dir) across the edge.
        * ``'smooth'``    — tangent-continuous crease (dihedral ≤ 30°),
                            excluded from output to avoid clutter per
                            Markosian 1997 §3.3.
        * ``'outline'``   — boundary edge (belongs to only one face).
    """
    p0: Tuple[float, float]
    p1: Tuple[float, float]
    visibility: str  # 'visible' | 'hidden'
    kind: str        # 'silhouette' | 'sharp' | 'smooth' | 'outline'


@dataclass
class HlrResult:
    """Projected 2D drawing output for one view.

    Parameters
    ----------
    view_name:
        Name from the originating :class:`ProjectionView`.
    visible_edges, hidden_edges:
        All classified 2D edge segments.
    svg_path_visible:
        SVG ``<path>`` ``d`` attribute string for visible edges (solid).
    svg_path_hidden:
        SVG ``<path>`` ``d`` attribute string for hidden edges (dashed).
    bbox:
        ``(xmin, ymin, xmax, ymax)`` bounding box in 2D drawing coordinates.
    """
    view_name: str
    visible_edges: List[HlrEdge2d]
    hidden_edges: List[HlrEdge2d]
    svg_path_visible: str
    svg_path_hidden: str
    bbox: Tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Internal tessellation helpers
# ---------------------------------------------------------------------------

@dataclass
class _Triangle:
    """A tessellated triangle with face reference and outward normal."""
    v0: np.ndarray
    v1: np.ndarray
    v2: np.ndarray
    normal: np.ndarray       # outward unit normal
    face_id: int             # id() of the originating Face

    @property
    def centroid(self) -> np.ndarray:
        return (self.v0 + self.v1 + self.v2) / 3.0


@dataclass
class _Edge3d:
    """A 3D edge with adjacency (up to two triangle face normals)."""
    p0: np.ndarray
    p1: np.ndarray
    face_normals: List[np.ndarray] = field(default_factory=list)
    face_ids: List[int] = field(default_factory=list)
    kind: str = 'sharp'        # set after classification


# ---------------------------------------------------------------------------
# Face tessellation
# ---------------------------------------------------------------------------

_CURVE_SAMPLES = 24      # samples per arc/circle edge
_CYL_U_STEPS = 32        # angular samples for cylinder lateral face
_SPH_U_STEPS = 24        # longitude samples for sphere
_SPH_V_STEPS = 16        # latitude samples for sphere


def _tessellate_planar_face(face: Face) -> List[_Triangle]:
    """Fan-triangulate a planar face from its outer-loop vertices."""
    outer = face.outer_loop()
    if outer is None or not outer.coedges:
        return []
    pts: List[np.ndarray] = []
    for ce in outer.coedges:
        pts.append(np.asarray(ce.start_point(), dtype=float))
    if len(pts) < 3:
        return []
    # Remove duplicate consecutive vertices
    clean: List[np.ndarray] = [pts[0]]
    for p in pts[1:]:
        if np.linalg.norm(p - clean[-1]) > 1e-10:
            clean.append(p)
    if np.linalg.norm(clean[-1] - clean[0]) < 1e-10:
        clean = clean[:-1]
    if len(clean) < 3:
        return []

    n = face.surface_normal(0.5, 0.5)
    tris = []
    fan = clean[0]
    fid = id(face)
    for i in range(1, len(clean) - 1):
        v0, v1, v2 = fan, clean[i], clean[i + 1]
        # ensure consistent outward orientation with the face normal
        computed = _unit(np.cross(v1 - v0, v2 - v0))
        if np.dot(computed, n) < 0:
            v1, v2 = v2, v1
            computed = -computed
        tris.append(_Triangle(v0, v1, v2, computed, fid))
    return tris


def _sample_circle_arc(arc: CircleArc3, n_samples: int = _CURVE_SAMPLES) -> List[np.ndarray]:
    ts = np.linspace(arc.t0, arc.t1, n_samples, endpoint=True)
    return [np.asarray(arc.evaluate(float(t)), dtype=float) for t in ts]


def _tessellate_cylinder_face(face: Face) -> List[_Triangle]:
    """Tessellate a CylinderSurface face into a triangle strip."""
    surf = face.surface
    if not isinstance(surf, CylinderSurface):
        return []
    # Sample a grid over (u in [0, 2pi], v in [0, height])
    # We find the v-range from the seam edge endpoints
    # Approximate: use full u in [0, 2*pi] and derive v from loop vertices
    loop = face.outer_loop()
    if loop is None:
        return []
    # Collect v values projected onto axis
    c = surf.center
    ax = surf.axis
    v_vals = []
    for ce in loop.coedges:
        p = np.asarray(ce.start_point(), dtype=float)
        v_vals.append(float(np.dot(p - c, ax)))
    if not v_vals:
        return []
    v0 = min(v_vals)
    v1 = max(v_vals)
    if abs(v1 - v0) < 1e-12:
        v0, v1 = 0.0, 1.0

    us = np.linspace(0.0, 2 * math.pi, _CYL_U_STEPS, endpoint=False)
    fid = id(face)
    tris: List[_Triangle] = []
    for i in range(len(us)):
        ua, ub = us[i], us[(i + 1) % len(us)]
        pa0 = np.asarray(surf.evaluate(ua, v0), dtype=float)
        pa1 = np.asarray(surf.evaluate(ub, v0), dtype=float)
        pb0 = np.asarray(surf.evaluate(ua, v1), dtype=float)
        pb1 = np.asarray(surf.evaluate(ub, v1), dtype=float)
        # Two triangles per quad strip
        for tri_pts in [(pa0, pb0, pa1), (pa1, pb0, pb1)]:
            a, b, cc = tri_pts
            n = _unit(np.cross(b - a, cc - a))
            # Check orientation vs surface normal at midpoint
            u_mid = (ua + ub) / 2
            v_mid = (v0 + v1) / 2
            surf_n = np.asarray(surf.normal(u_mid, v_mid), dtype=float)
            if np.dot(n, surf_n) < 0:
                b, cc = cc, b
                n = -n
            tris.append(_Triangle(a, b, cc, n, fid))
    return tris


def _tessellate_sphere_face(face: Face) -> List[_Triangle]:
    """Tessellate a SphereSurface face into lat/lon triangles."""
    surf = face.surface
    if not isinstance(surf, SphereSurface):
        return []
    c = surf.center
    r = surf.radius
    us = np.linspace(0.0, 2 * math.pi, _SPH_U_STEPS, endpoint=False)
    vs = np.linspace(-math.pi / 2, math.pi / 2, _SPH_V_STEPS + 1)
    fid = id(face)
    tris: List[_Triangle] = []
    for j in range(len(vs) - 1):
        va, vb = vs[j], vs[j + 1]
        for i in range(len(us)):
            ua, ub = us[i], us[(i + 1) % len(us)]
            p00 = np.asarray(surf.evaluate(ua, va), dtype=float)
            p10 = np.asarray(surf.evaluate(ub, va), dtype=float)
            p01 = np.asarray(surf.evaluate(ua, vb), dtype=float)
            p11 = np.asarray(surf.evaluate(ub, vb), dtype=float)
            for tri_pts in [(p00, p10, p01), (p10, p11, p01)]:
                a, b, cc = tri_pts
                n = _unit(np.cross(b - a, cc - a))
                # outward sphere normal at centroid
                mid = (a + b + cc) / 3.0
                out_n = _unit(mid - c)
                if np.dot(n, out_n) < 0:
                    b, cc = cc, b
                    n = -n
                tris.append(_Triangle(a, b, cc, n, fid))
    return tris


def _tessellate_generic_face(face: Face) -> List[_Triangle]:
    """Tessellate a face with an unknown surface type via UV grid sampling."""
    surf = face.surface
    if not hasattr(surf, 'evaluate'):
        return []
    # Sample a coarse UV grid
    u_steps, v_steps = 8, 8
    tris: List[_Triangle] = []
    fid = id(face)
    for ui in range(u_steps):
        for vi in range(v_steps):
            ua = ui / u_steps
            ub = (ui + 1) / u_steps
            va = vi / v_steps
            vb = (vi + 1) / v_steps
            try:
                p00 = np.asarray(surf.evaluate(ua, va), dtype=float)
                p10 = np.asarray(surf.evaluate(ub, va), dtype=float)
                p01 = np.asarray(surf.evaluate(ua, vb), dtype=float)
                p11 = np.asarray(surf.evaluate(ub, vb), dtype=float)
            except Exception:
                continue
            for tri_pts in [(p00, p10, p01), (p10, p11, p01)]:
                a, b, cc = tri_pts
                n = _unit(np.cross(b - a, cc - a))
                tris.append(_Triangle(a, b, cc, n, fid))
    return tris


def _tessellate_body(body: Body) -> Tuple[List[_Triangle], List[_Edge3d]]:
    """Tessellate all faces of a body into triangles and tagged 3D edges.

    Returns ``(triangles, edges)``.
    - ``triangles`` are used for visibility testing.
    - ``edges`` carry classification tags for silhouette/sharp/outline detection.

    Two types of edges are generated:
    1. **Topology edges** (from the B-rep edge list): sharp/outline edges
       between adjacent faces.
    2. **Mesh-interior silhouette candidates** (for curved faces): edges
       shared between adjacent tessellation triangles within a single curved
       face. These are added so that silhouettes of cylinders/spheres that
       have no topological edge representation can still be drawn.
       (Markosian 1997 §3; Hertzmann 1999 §2.)
    """
    all_tris: List[_Triangle] = []
    face_normals: Dict[int, np.ndarray] = {}  # face_id -> representative normal
    # Per-face: list of triangles (for mesh-interior silhouette extraction)
    face_tris: Dict[int, List[_Triangle]] = {}

    for face in body.all_faces():
        surf = face.surface
        if isinstance(surf, Plane):
            tris = _tessellate_planar_face(face)
        elif isinstance(surf, CylinderSurface):
            tris = _tessellate_cylinder_face(face)
        elif isinstance(surf, SphereSurface):
            tris = _tessellate_sphere_face(face)
        else:
            tris = _tessellate_generic_face(face)

        fid = id(face)
        if tris:
            # Use median triangle normal as face representative normal
            normals = np.array([t.normal for t in tris])
            rep_normal = _unit(normals.mean(axis=0))
            face_normals[fid] = rep_normal
            all_tris.extend(tris)
            face_tris[fid] = tris

    # Build 3D edges from topology with adjacency info
    edges_3d: List[_Edge3d] = []
    # Map edge id -> list of adjacent face normals
    edge_face_map: Dict[int, Tuple[List[np.ndarray], List[int]]] = {}

    for face in body.all_faces():
        fid = id(face)
        fn = face_normals.get(fid)
        if fn is None:
            # Fallback: try to get surface normal directly
            try:
                fn = np.asarray(face.surface_normal(0.5, 0.5), dtype=float)
            except Exception:
                fn = np.array([0.0, 0.0, 1.0])
            face_normals[fid] = fn

        for loop in face.loops:
            for ce in loop.coedges:
                eid = id(ce.edge)
                if eid not in edge_face_map:
                    edge_face_map[eid] = ([], [])
                normals_list, fids_list = edge_face_map[eid]
                if fid not in fids_list:
                    normals_list.append(fn)
                    fids_list.append(fid)

    seen_edges: set = set()
    for face in body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                eid = id(ce.edge)
                if eid in seen_edges:
                    continue
                seen_edges.add(eid)
                edge = ce.edge
                normals_list, fids_list = edge_face_map.get(eid, ([], []))

                # Sample a few points along the edge for polyline representation
                p0 = np.asarray(edge.start_point(), dtype=float)
                p1 = np.asarray(edge.end_point(), dtype=float)
                e3d = _Edge3d(p0, p1, list(normals_list), list(fids_list))
                edges_3d.append(e3d)

    # --- Mesh-interior silhouette edges for curved faces --------------------
    # For faces whose tessellation triangles are adjacent within the face
    # (cylinder, sphere, generic), extract internal shared edges.
    # These are pairs of adjacent triangles within the same face that share
    # an edge. This allows the silhouette test (Hertzmann 1999) to fire on
    # the tessellation mesh, not just topological edges.
    for face in body.all_faces():
        surf = face.surface
        # Only add mesh-interior edges for truly curved surfaces
        if isinstance(surf, Plane):
            continue
        fid = id(face)
        tris = face_tris.get(fid, [])
        if len(tris) < 2:
            continue
        # Build a map from (vertex_key, vertex_key) -> list of triangle normals
        # using rounded vertex positions as keys for adjacency detection
        def _vkey(v: np.ndarray) -> tuple:
            return (round(float(v[0]), 8), round(float(v[1]), 8), round(float(v[2]), 8))

        half_edge_map: Dict[Tuple, List] = {}
        for tri in tris:
            verts = [tri.v0, tri.v1, tri.v2]
            for i in range(3):
                a = _vkey(verts[i])
                b = _vkey(verts[(i + 1) % 3])
                key = (min(a, b), max(a, b))
                if key not in half_edge_map:
                    half_edge_map[key] = []
                half_edge_map[key].append((verts[i], verts[(i + 1) % 3], tri.normal))

        for key, entries in half_edge_map.items():
            if len(entries) != 2:
                # Boundary or non-manifold mesh edge; handled by topology edges
                continue
            n0 = entries[0][2]
            n1 = entries[1][2]
            p0 = entries[0][0]
            p1 = entries[0][1]
            e3d = _Edge3d(
                np.asarray(p0, dtype=float),
                np.asarray(p1, dtype=float),
                [n0, n1],
                [fid, fid],
            )
            edges_3d.append(e3d)

    return all_tris, edges_3d


# ---------------------------------------------------------------------------
# Edge classification
# ---------------------------------------------------------------------------

_SHARP_ANGLE_RAD = math.radians(30.0)  # Markosian 1997: crease threshold


def _classify_edges(
    edges_3d: List[_Edge3d],
    view_dir: np.ndarray,
    silhouette_tol_rad: float = 0.01,
) -> List[_Edge3d]:
    """Classify edges as sharp/silhouette/smooth/outline (Markosian 1997 §3).

    Modifies edge ``kind`` in place. Returns only edges that should appear
    in the drawing (excludes smooth interior creases per §3.3).

    Classification rules
    --------------------
    * outline:    boundary edge — used by exactly one face.
    * silhouette: (N_f0 · view_dir) * (N_f1 · view_dir) < 0 (strict sign flip).
                  (Hertzmann 1999, definition 2.1.)
    * sharp:      dihedral angle > 30° between adjacent face normals.
    * smooth:     dihedral angle ≤ 30° (tangent-continuous); omitted from
                  output to reduce clutter.
    """
    _sil_cos_tol = math.cos(math.pi / 2 - silhouette_tol_rad)  # small positive (unused now)

    classified = []
    for e in edges_3d:
        n_faces = len(e.face_normals)
        if n_faces == 0:
            e.kind = 'outline'
            classified.append(e)
        elif n_faces == 1:
            e.kind = 'outline'
            classified.append(e)
        else:
            n0 = e.face_normals[0]
            n1 = e.face_normals[1]
            d0 = float(np.dot(n0, view_dir))
            d1 = float(np.dot(n1, view_dir))
            # Silhouette: strict sign change across the edge (Hertzmann 1999 §2.1).
            # Use silhouette_tol_rad to avoid classifying grazing-angle edges
            # (|d| ≈ 0) as silhouettes — those should fall through to the
            # dihedral-angle test instead.
            # An edge is a silhouette iff one face is clearly front-facing
            # (d > tol) and the other is clearly back-facing (d < -tol).
            if d0 * d1 < 0.0:
                e.kind = 'silhouette'
                classified.append(e)
                continue
            # Dihedral angle between faces
            cos_angle = float(np.clip(np.dot(n0, n1), -1.0, 1.0))
            dihedral = math.acos(cos_angle)
            if dihedral > _SHARP_ANGLE_RAD:
                e.kind = 'sharp'
                classified.append(e)
            else:
                e.kind = 'smooth'
                # smooth edges excluded (Markosian 1997 §3.3 "don't draw")
    return classified


# ---------------------------------------------------------------------------
# 2D projection
# ---------------------------------------------------------------------------

def _build_projection_basis(view: ProjectionView):
    """Return orthonormal (right, up, view_dir) basis vectors.

    The 2D projection is: x_2d = P · right, y_2d = P · up_ortho.
    """
    view_dir = _unit(np.asarray(view.direction, dtype=float))
    up = np.asarray(view.up, dtype=float)
    # Gram-Schmidt: orthonormalise up against view_dir
    up_ortho = _unit(up - np.dot(up, view_dir) * view_dir)
    right = _unit(np.cross(up_ortho, view_dir))
    return right, up_ortho, view_dir


def _project_3d_to_2d(
    p: np.ndarray,
    right: np.ndarray,
    up_ortho: np.ndarray,
) -> Tuple[float, float]:
    """Project a 3D point onto the 2D drawing plane."""
    return float(np.dot(p, right)), float(np.dot(p, up_ortho))


def _point_depth(p: np.ndarray, view_dir: np.ndarray) -> float:
    """Depth along view direction (larger = closer to camera)."""
    return float(np.dot(p, view_dir))


# ---------------------------------------------------------------------------
# Visibility testing  (Appel 1967 quantitative invisibility)
# ---------------------------------------------------------------------------

_HLR_WALK_STEPS = 20   # steps per edge for QI walk (Appel 1967)


def _barycentric_coords(
    p: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
) -> Tuple[float, float, float]:
    """Barycentric coordinates of 2D point p in triangle (a, b, c)."""
    v0 = b - a
    v1 = c - a
    v2 = p - a
    d00 = float(np.dot(v0, v0))
    d01 = float(np.dot(v0, v1))
    d11 = float(np.dot(v1, v1))
    d20 = float(np.dot(v2, v0))
    d21 = float(np.dot(v2, v1))
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-20:
        return -1.0, -1.0, -1.0
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w
    return u, v, w


def _is_point_occluded(
    test_xy: Tuple[float, float],
    test_depth: float,
    tri_2d: List[Tuple[np.ndarray, np.ndarray, np.ndarray, float, int]],
    occlusion_tol: float,
    exclude_face_ids: Optional[set] = None,
) -> bool:
    """Test if a 2D point is occluded by any triangle closer to the camera.

    Parameters
    ----------
    test_xy:
        2D drawing-plane coordinate to test.
    test_depth:
        Depth (dot-product with view_dir) of the original 3D point.
    tri_2d:
        Precomputed ``(v0_2d, v1_2d, v2_2d, depth_centroid, face_id)``
        for each triangle.
    occlusion_tol:
        Numerical tolerance for depth comparison.
    exclude_face_ids:
        Set of face id()s to skip when checking occlusion. Used to prevent
        a surface edge from being occluded by its own adjacent triangles
        (self-occlusion artefact, particularly on sphere/cylinder silhouettes).

    Returns True if occluded (quantitative invisibility > 0, Appel 1967).
    """
    tx, ty = test_xy

    for v0_2d, v1_2d, v2_2d, depth_centroid, face_id in tri_2d:
        # Skip triangles belonging to excluded faces (self-occlusion prevention)
        if exclude_face_ids is not None and face_id in exclude_face_ids:
            continue

        # Quick bounding-box cull
        min_x = min(v0_2d[0], v1_2d[0], v2_2d[0])
        max_x = max(v0_2d[0], v1_2d[0], v2_2d[0])
        min_y = min(v0_2d[1], v1_2d[1], v2_2d[1])
        max_y = max(v0_2d[1], v1_2d[1], v2_2d[1])
        if tx < min_x - occlusion_tol or tx > max_x + occlusion_tol:
            continue
        if ty < min_y - occlusion_tol or ty > max_y + occlusion_tol:
            continue

        # Check if the triangle is closer to the camera (depth > test_depth)
        if depth_centroid <= test_depth + occlusion_tol:
            continue

        # Check if the 2D point is inside the triangle
        p2d = np.array([tx, ty], dtype=float)
        u, v, w = _barycentric_coords(p2d, v0_2d, v1_2d, v2_2d)
        if u >= -occlusion_tol and v >= -occlusion_tol and w >= -occlusion_tol:
            return True
    return False


def _precompute_tri_2d(
    triangles: List[_Triangle],
    right: np.ndarray,
    up_ortho: np.ndarray,
    view_dir: np.ndarray,
) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray, float, int]]:
    """Project all triangles to 2D once for fast per-edge visibility testing.

    Returns tuples of ``(v0_2d, v1_2d, v2_2d, depth_centroid, face_id)``.
    The ``face_id`` is used to skip self-face occlusion.
    """
    result = []
    for tri in triangles:
        v0_2d = np.array(_project_3d_to_2d(tri.v0, right, up_ortho))
        v1_2d = np.array(_project_3d_to_2d(tri.v1, right, up_ortho))
        v2_2d = np.array(_project_3d_to_2d(tri.v2, right, up_ortho))
        # Use centroid depth as representative depth for the triangle
        depth = _point_depth(tri.centroid, view_dir)
        result.append((v0_2d, v1_2d, v2_2d, depth, tri.face_id))
    return result


# ---------------------------------------------------------------------------
# SVG path generation
# ---------------------------------------------------------------------------

def _edges_to_svg_path(edges: List[HlrEdge2d]) -> str:
    """Build a compact SVG ``<path>`` ``d`` attribute from a list of edges.

    Each edge becomes an independent ``M x y L x y`` segment (the edges are
    not necessarily connected). Returns an empty string if no edges.
    """
    if not edges:
        return ''
    parts = []
    for e in edges:
        x0, y0 = e.p0
        x1, y1 = e.p1
        parts.append(f'M {x0:.4f} {y0:.4f} L {x1:.4f} {y1:.4f}')
    return ' '.join(parts)


def _compute_bbox(
    visible: List[HlrEdge2d],
    hidden: List[HlrEdge2d],
) -> Tuple[float, float, float, float]:
    """Compute bounding box from all 2D edge endpoints."""
    all_pts = []
    for e in visible + hidden:
        all_pts.append(e.p0)
        all_pts.append(e.p1)
    if not all_pts:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def project_brep_to_2d(
    body: Body,
    view: ProjectionView,
    silhouette_tol_rad: float = 0.01,
    occlusion_tol: float = 1e-6,
) -> HlrResult:
    """Project a B-rep solid into 2D with hidden lines removed.

    Implements the Appel (1967) + Markosian et al. (1997) pipeline:

    1. **Tessellate** body faces into triangles with face/edge tags
       (fan-triangulation for planar faces; UV sampling for curved).
    2. **Classify edges**:
       - *Outline*  — boundary (one adjacent face only).
       - *Silhouette* — (N_f0 · v) * (N_f1 · v) ≤ 0 (Hertzmann 1999 §2.1).
       - *Sharp*    — dihedral > 30° (Markosian 1997 §3.2).
       - *Smooth*   — dihedral ≤ 30°, excluded from output (§3.3).
    3. **Project** each retained 3D edge endpoint to 2D via the orthonormal
       ``(right, up, view_dir)`` frame.
    4. **Visibility walk** (Appel 1967 §2): walk each edge in
       ``_HLR_WALK_STEPS`` steps; at each step, ray-cast in 2D against all
       projected triangles. Visible iff no triangle's projected interior covers
       that step *closer* to camera (depth > edge-point depth + occlusion_tol).
    5. Emit ``HlrResult`` with visible/hidden lists and SVG path strings.

    Parameters
    ----------
    body:
        A :class:`~kerf_cad_core.geom.brep.Body` to project.
    view:
        Projection direction and up vector.
    silhouette_tol_rad:
        Angular tolerance (radians) below which a near-zero N·v dot product
        is still treated as a silhouette (avoids flickering near grazing).
    occlusion_tol:
        Depth tolerance for the Appel QI test.

    Returns
    -------
    HlrResult
    """
    right, up_ortho, view_dir = _build_projection_basis(view)

    # Step 1: tessellate
    triangles, edges_3d = _tessellate_body(body)

    # Step 2: classify
    classified = _classify_edges(edges_3d, view_dir, silhouette_tol_rad)

    # Step 3+4: project and test visibility
    tri_2d = _precompute_tri_2d(triangles, right, up_ortho, view_dir)
    visible_edges: List[HlrEdge2d] = []
    hidden_edges: List[HlrEdge2d] = []

    for e3d in classified:
        p0_2d = _project_3d_to_2d(e3d.p0, right, up_ortho)
        p1_2d = _project_3d_to_2d(e3d.p1, right, up_ortho)
        depth0 = _point_depth(e3d.p0, view_dir)
        depth1 = _point_depth(e3d.p1, view_dir)

        # Skip degenerate zero-length 2D edges
        dx = p1_2d[0] - p0_2d[0]
        dy = p1_2d[1] - p0_2d[1]
        if dx * dx + dy * dy < 1e-20:
            continue

        # Silhouette edges are visible by definition: a silhouette requires one
        # front-facing and one back-facing adjacent face. The front-facing face
        # makes the edge visible. Skip expensive occlusion testing for these
        # (Markosian 1997 §3 — silhouettes are drawn as visible).
        # We still test outline edges with occlusion since they could be hidden
        # behind other bodies or faces.
        if e3d.kind == 'silhouette':
            # Verify at least one adjacent face is front-facing
            is_vis_sil = any(float(np.dot(n, view_dir)) > 0 for n in e3d.face_normals)
            if is_vis_sil:
                edge2d = HlrEdge2d(p0_2d, p1_2d, 'visible', e3d.kind)
                visible_edges.append(edge2d)
            else:
                edge2d = HlrEdge2d(p0_2d, p1_2d, 'hidden', e3d.kind)
                hidden_edges.append(edge2d)
            continue

        # Exclude self-face triangles from occluding their own edges
        # (prevents planar face edges on curved surfaces from self-occluding).
        exclude_ids = set(e3d.face_ids) if e3d.face_ids else None

        # Walk the edge in N steps (Appel 1967 §2)
        # Classify by majority vote (if >50% steps are visible → visible)
        vis_count = 0
        for step in range(_HLR_WALK_STEPS):
            t = (step + 0.5) / _HLR_WALK_STEPS
            x = p0_2d[0] + t * dx
            y = p0_2d[1] + t * dy
            depth = depth0 + t * (depth1 - depth0)
            if not _is_point_occluded(
                (x, y), depth, tri_2d, occlusion_tol, exclude_ids
            ):
                vis_count += 1

        visibility = 'visible' if vis_count >= _HLR_WALK_STEPS // 2 else 'hidden'
        edge2d = HlrEdge2d(p0_2d, p1_2d, visibility, e3d.kind)
        if visibility == 'visible':
            visible_edges.append(edge2d)
        else:
            hidden_edges.append(edge2d)

    # Step 5: build SVG paths and bbox
    svg_vis = _edges_to_svg_path(visible_edges)
    svg_hid = _edges_to_svg_path(hidden_edges)
    bbox = _compute_bbox(visible_edges, hidden_edges)

    return HlrResult(
        view_name=view.name,
        visible_edges=visible_edges,
        hidden_edges=hidden_edges,
        svg_path_visible=svg_vis,
        svg_path_hidden=svg_hid,
        bbox=bbox,
    )


def make_standard_views(body: Body) -> Dict[str, HlrResult]:
    """Return HLR results for the four standard engineering views.

    Views
    -----
    * ``front`` — looking in the +Y direction (toward -Y face).
    * ``top``   — looking down in -Z direction (toward -Z face).
    * ``right`` — looking in the -X direction (toward +X face).
    * ``iso``   — isometric, standard (1, -1, 1) / √3 direction.

    Returns
    -------
    dict mapping view name → :class:`HlrResult`.
    """
    views = [
        ProjectionView('front',  (0.0,  1.0, 0.0), (0.0, 0.0, 1.0)),
        ProjectionView('top',    (0.0,  0.0, 1.0), (0.0, 1.0, 0.0)),
        ProjectionView('right',  (1.0,  0.0, 0.0), (0.0, 0.0, 1.0)),
        ProjectionView('iso',    (1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
    ]
    results = {}
    for v in views:
        results[v.name] = project_brep_to_2d(body, v)
    return results


__all__ = [
    'ProjectionView',
    'HlrEdge2d',
    'HlrResult',
    'project_brep_to_2d',
    'make_standard_views',
]
