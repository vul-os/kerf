"""
unroll_srf.py
=============
Pure-Python (math-only, no OCC) developable-surface unroll / flatten.
Rhino-parity: UnrollSrf command.

Distinct from ``sheet_metal`` (bend-allowance flat-pattern):
  - sheet_metal operates on bend features with material K-factor corrections.
  - unroll_srf operates on arbitrary analytical/mesh surfaces and produces
    exact or near-exact developed layouts preserving edge lengths.

Public API
----------
is_developable(surface_or_mesh, *, tol=1e-4) -> dict
    Gaussian curvature test.  Returns ok/reason/max_gaussian/is_developable.

unroll_developable(surface_desc) -> dict
    Exact unroll for cylinder, cone, tangent-developable strips.
    Returns ok/reason/flat_vertices/flat_edges/developed_width/developed_height.

unroll_strip(vertices, faces, *, tol=1e-3) -> dict
    Sequential triangle-strip hinge-unfold for near-developable meshes.
    Returns ok/reason/flat_vertices/distortion/max_length_distortion/
            max_area_distortion/total_developed_width/total_developed_height.

smash(vertices, faces, *, report_distortion=True) -> dict
    Force-flatten with distortion map (works on any mesh).
    Returns ok/reason/flat_vertices/distortion_map.

project_curves_to_unrolled(surface_desc, curves_3d) -> dict
    Map 3D curves/points onto the unrolled domain.
    Returns ok/reason/flat_curves.

All functions return {"ok": bool, "reason": str, ...} -- never raise.

@register LLM tools:
  unroll_surface        -- unroll a cylinder, cone, or strip mesh
  smash_surface         -- force-flatten with distortion map
  check_developability  -- Gaussian curvature diagnostic
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Vec3 = np.ndarray  # shape (3,)
Tri = Tuple[int, int, int]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm(v: np.ndarray) -> float:
    return float(np.linalg.norm(v))


def _unit(v: np.ndarray) -> np.ndarray:
    n = _norm(v)
    if n < 1e-15:
        return np.zeros(3)
    return v / n


def _triangle_area_3d(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return 0.5 * _norm(np.cross(b - a, c - a))


def _triangle_area_2d(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return 0.5 * abs(
        (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
    )


# ---------------------------------------------------------------------------
# Gaussian curvature on a triangle mesh (angle deficit method)
# ---------------------------------------------------------------------------


def _gaussian_curvature_mesh(
    vertices: np.ndarray,
    faces: List[Tri],
) -> np.ndarray:
    """Discrete Gaussian curvature (angle-deficit) per vertex.

    Boundary vertices are excluded (angle-sum at boundary is naturally < 2pi
    even for a flat mesh), so only interior vertices are meaningful.
    Returns K=0 for boundary vertices.
    """
    n = len(vertices)
    angle_sum = np.zeros(n)
    area_sum = np.zeros(n)
    valence = np.zeros(n, dtype=int)  # count of incident triangles

    # Identify boundary vertices: those on edges with only one incident face
    edge_count: Dict[Tuple[int, int], int] = {}
    for tri in faces:
        for a, b in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])]:
            e = (min(a, b), max(a, b))
            edge_count[e] = edge_count.get(e, 0) + 1

    boundary_verts: set = set()
    for (a, b), cnt in edge_count.items():
        if cnt == 1:
            boundary_verts.add(a)
            boundary_verts.add(b)

    for tri in faces:
        i, j, k = tri
        a, b, c = vertices[i], vertices[j], vertices[k]
        edges = [(a, b, c), (b, c, a), (c, a, b)]
        area = _triangle_area_3d(a, b, c)
        for idx, (p, q, r) in zip([i, j, k], edges):
            e1 = _unit(q - p)
            e2 = _unit(r - p)
            dot = float(np.clip(np.dot(e1, e2), -1.0, 1.0))
            angle_sum[idx] += math.acos(dot)
            area_sum[idx] += area / 3.0
            valence[idx] += 1

    K = np.zeros(n)
    for i in range(n):
        if i in boundary_verts:
            # boundary vertex: curvature not meaningful, set to 0
            K[i] = 0.0
        elif area_sum[i] > 1e-15:
            K[i] = (2.0 * math.pi - angle_sum[i]) / area_sum[i]
    return K


# ---------------------------------------------------------------------------
# is_developable
# ---------------------------------------------------------------------------


def is_developable(
    surface_or_mesh: Dict[str, Any],
    *,
    tol: float = 1e-4,
) -> dict:
    """Test whether a surface/mesh is developable (Gaussian curvature ~= 0).

    Parameters
    ----------
    surface_or_mesh : dict
        Either:
          {"type": "cylinder", "radius": R, "height": H, "sweep": theta}
          {"type": "cone",     "base_radius": R, "apex_height": H, "sweep": theta}
          {"type": "plane"}
          {"type": "mesh",     "vertices": [[x,y,z],...], "faces": [[i,j,k],...]}
    tol : float
        Gaussian curvature threshold below which the surface is considered
        developable (default 1e-4).

    Returns
    -------
    dict with:
        ok              : bool
        reason          : str
        max_gaussian    : float
        mean_gaussian   : float
        is_developable  : bool
    """
    try:
        stype = surface_or_mesh.get("type", "")

        if stype in ("cylinder", "cone", "plane"):
            return {
                "ok": True, "reason": "",
                "max_gaussian": 0.0, "mean_gaussian": 0.0,
                "is_developable": True,
            }

        if stype == "mesh":
            verts = np.array(surface_or_mesh["vertices"], dtype=float)
            faces = [tuple(f) for f in surface_or_mesh["faces"]]
            if len(verts) < 3 or len(faces) < 1:
                return {"ok": False, "reason": "mesh must have >=3 vertices and >=1 face",
                        "max_gaussian": 0.0, "mean_gaussian": 0.0, "is_developable": False}
            K = _gaussian_curvature_mesh(verts, faces)
            max_K = float(np.max(np.abs(K)))
            mean_K = float(np.mean(np.abs(K)))
            return {
                "ok": True, "reason": "",
                "max_gaussian": max_K,
                "mean_gaussian": mean_K,
                "is_developable": max_K <= tol,
            }

        return {"ok": False, "reason": f"unknown surface type: {stype!r}",
                "max_gaussian": 0.0, "mean_gaussian": 0.0, "is_developable": False}

    except Exception as exc:
        return {"ok": False, "reason": str(exc),
                "max_gaussian": 0.0, "mean_gaussian": 0.0, "is_developable": False}


# ---------------------------------------------------------------------------
# unroll_developable -- exact analytical unroll
# ---------------------------------------------------------------------------


def _cylinder_unroll(
    radius: float,
    height: float,
    sweep: float,
    num_u: int = 64,
    num_v: int = 2,
) -> dict:
    """Exact unroll of a cylinder: arc length = R*theta, height stays."""
    if radius <= 0:
        return {"ok": False, "reason": "cylinder radius must be > 0"}
    if height <= 0:
        return {"ok": False, "reason": "cylinder height must be > 0"}
    if not (0 < sweep <= 2 * math.pi + 1e-9):
        return {"ok": False, "reason": "sweep must be in (0, 2pi]"}

    flat_width = radius * sweep
    flat_height = height

    us = np.linspace(0.0, sweep, num_u)
    vs = np.linspace(0.0, height, num_v)

    pts_3d = []
    pts_2d = []
    for v in vs:
        for u in us:
            pts_3d.append([radius * math.cos(u), radius * math.sin(u), v])
            pts_2d.append([radius * u, v])

    return {
        "ok": True, "reason": "",
        "surface_type": "cylinder",
        "flat_vertices": pts_2d,
        "flat_vertices_3d": pts_3d,
        "developed_width": flat_width,
        "developed_height": flat_height,
        "flat_edges": [],
        "num_u": num_u, "num_v": num_v,
    }


def _cone_unroll(
    base_radius: float,
    apex_height: float,
    sweep: float,
    num_u: int = 64,
    num_v: int = 16,
) -> dict:
    """Exact unroll of a right circular cone to a flat sector."""
    if base_radius <= 0:
        return {"ok": False, "reason": "base_radius must be > 0"}
    if apex_height <= 0:
        return {"ok": False, "reason": "apex_height must be > 0"}
    if not (0 < sweep <= 2 * math.pi + 1e-9):
        return {"ok": False, "reason": "sweep must be in (0, 2pi]"}

    slant = math.sqrt(base_radius ** 2 + apex_height ** 2)
    sin_alpha = base_radius / slant
    sector_angle = sweep * sin_alpha

    us = np.linspace(0.0, sweep, num_u)
    vs = np.linspace(0.0, 1.0, num_v)

    pts_3d = []
    pts_2d = []
    for tv in vs:
        r3d = tv * base_radius
        z3d = (1.0 - tv) * apex_height
        for u in us:
            pts_3d.append([r3d * math.cos(u), r3d * math.sin(u), z3d])
            r_flat = tv * slant
            phi_flat = (u / sweep) * sector_angle if sweep > 0 else 0.0
            pts_2d.append([r_flat * math.cos(phi_flat), r_flat * math.sin(phi_flat)])

    return {
        "ok": True, "reason": "",
        "surface_type": "cone",
        "flat_vertices": pts_2d,
        "flat_vertices_3d": pts_3d,
        "developed_width": 2.0 * slant * math.sin(sector_angle / 2.0) if sector_angle < math.pi else 2.0 * slant,
        "developed_height": slant,
        "slant_length": slant,
        "sector_angle": sector_angle,
        "flat_edges": [],
        "num_u": num_u, "num_v": num_v,
    }


def _plane_unroll(
    width: float,
    height: float,
    num_u: int = 8,
    num_v: int = 8,
) -> dict:
    """A planar surface is already developed -- identity map."""
    if width <= 0 or height <= 0:
        return {"ok": False, "reason": "plane width and height must be > 0"}
    us = np.linspace(0.0, width, num_u)
    vs = np.linspace(0.0, height, num_v)
    pts_3d, pts_2d = [], []
    for v in vs:
        for u in us:
            pts_3d.append([u, v, 0.0])
            pts_2d.append([u, v])
    return {
        "ok": True, "reason": "",
        "surface_type": "plane",
        "flat_vertices": pts_2d,
        "flat_vertices_3d": pts_3d,
        "developed_width": width,
        "developed_height": height,
        "flat_edges": [],
        "num_u": num_u, "num_v": num_v,
    }


def unroll_developable(surface_desc: Dict[str, Any], **kwargs) -> dict:
    """Exact analytical unroll for cylinder, cone, and plane.

    Parameters
    ----------
    surface_desc : dict
        {"type": "cylinder", "radius": R, "height": H, "sweep": theta}
        {"type": "cone", "base_radius": R, "apex_height": H, "sweep": theta}
        {"type": "plane", "width": W, "height": H}

    Returns
    -------
    dict with:
        ok                  : bool
        reason              : str
        surface_type        : str
        flat_vertices       : list of [x, y]
        flat_vertices_3d    : list of [x, y, z]
        developed_width     : float
        developed_height    : float
        flat_edges          : list
    """
    try:
        stype = surface_desc.get("type", "")
        if stype == "cylinder":
            return _cylinder_unroll(
                radius=float(surface_desc["radius"]),
                height=float(surface_desc["height"]),
                sweep=float(surface_desc.get("sweep", 2 * math.pi)),
            )
        if stype == "cone":
            return _cone_unroll(
                base_radius=float(surface_desc["base_radius"]),
                apex_height=float(surface_desc["apex_height"]),
                sweep=float(surface_desc.get("sweep", 2 * math.pi)),
            )
        if stype == "plane":
            return _plane_unroll(
                width=float(surface_desc["width"]),
                height=float(surface_desc["height"]),
            )
        return {"ok": False, "reason": f"unroll_developable: unsupported type {stype!r}",
                "flat_vertices": [], "flat_vertices_3d": [],
                "developed_width": 0.0, "developed_height": 0.0, "flat_edges": []}
    except KeyError as exc:
        return {"ok": False, "reason": f"missing required field: {exc}",
                "flat_vertices": [], "flat_vertices_3d": [],
                "developed_width": 0.0, "developed_height": 0.0, "flat_edges": []}
    except Exception as exc:
        return {"ok": False, "reason": str(exc),
                "flat_vertices": [], "flat_vertices_3d": [],
                "developed_width": 0.0, "developed_height": 0.0, "flat_edges": []}


# ---------------------------------------------------------------------------
# unroll_strip -- sequential triangle hinge-unfold
# ---------------------------------------------------------------------------


def _build_adjacency(faces: List[Tri]) -> Dict[Tuple[int, int], List[int]]:
    """Map (edge as sorted pair) -> list of face indices."""
    adj: Dict[Tuple[int, int], List[int]] = {}
    for fi, tri in enumerate(faces):
        for a, b in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])]:
            e = (min(a, b), max(a, b))
            adj.setdefault(e, []).append(fi)
    return adj


def _unfold_triangle(
    p0_2d: np.ndarray, p1_2d: np.ndarray, p2_3d: np.ndarray,
    p0_3d: np.ndarray, p1_3d: np.ndarray,
    *,
    flip: bool = False,
) -> np.ndarray:
    """Place p2 in 2D by preserving distances |p2-p0| and |p2-p1|.

    flip : bool
        Place p2 on the negative-perp side of the (p0->p1) edge.
    """
    d0 = _norm(p2_3d - p0_3d)
    d1 = _norm(p2_3d - p1_3d)
    base = _norm(p1_2d - p0_2d)
    if base < 1e-15:
        return p0_2d + np.array([d0, 0.0])

    cos_a = (d0 ** 2 + base ** 2 - d1 ** 2) / (2.0 * d0 * base + 1e-15)
    cos_a = float(np.clip(cos_a, -1.0, 1.0))
    sin_a = math.sqrt(max(0.0, 1.0 - cos_a ** 2))

    e = (p1_2d - p0_2d) / (base + 1e-15)
    perp = np.array([-e[1], e[0]])
    sign = -1.0 if flip else 1.0

    return p0_2d + d0 * (cos_a * e + sign * sin_a * perp)


def unroll_strip(
    vertices: Sequence,
    faces: Sequence,
    *,
    tol: float = 1e-3,
) -> dict:
    """Sequential triangle-strip hinge-unfold for near-developable meshes.

    Each triangle is unfolded by rotating about the shared edge with its
    predecessor, preserving all three edge lengths exactly.  Distortion
    is measured by comparing 2D edge lengths against 3D edge lengths.

    Parameters
    ----------
    vertices : list of [x, y, z]
    faces : list of [i, j, k]
    tol : float
        Gaussian curvature tolerance for the near-developable check.

    Returns
    -------
    dict with:
        ok                     : bool
        reason                 : str
        flat_vertices          : list of [x, y] per vertex
        distortion             : list of per-face area distortion ratios
        max_length_distortion  : float
        max_area_distortion    : float
        total_developed_width  : float
        total_developed_height : float
    """
    try:
        verts = np.array(vertices, dtype=float)
        tris: List[Tri] = [tuple(f) for f in faces]  # type: ignore[misc]

        if len(verts) < 3:
            return {"ok": False, "reason": "need at least 3 vertices",
                    "flat_vertices": [], "distortion": [],
                    "max_length_distortion": 0.0, "max_area_distortion": 0.0,
                    "total_developed_width": 0.0, "total_developed_height": 0.0}
        if len(tris) < 1:
            return {"ok": False, "reason": "need at least 1 face",
                    "flat_vertices": [], "distortion": [],
                    "max_length_distortion": 0.0, "max_area_distortion": 0.0,
                    "total_developed_width": 0.0, "total_developed_height": 0.0}

        n_v = len(verts)
        flat = np.full((n_v, 2), np.nan)
        placed = np.zeros(n_v, dtype=bool)

        # Seed first triangle flat
        i0, i1, i2 = tris[0]
        flat[i0] = np.array([0.0, 0.0])
        flat[i1] = np.array([_norm(verts[i1] - verts[i0]), 0.0])
        # Seed triangle: place i2 on positive-perp side (flip=False)
        flat[i2] = _unfold_triangle(
            flat[i0], flat[i1], verts[i2], verts[i0], verts[i1], flip=False
        )
        placed[i0] = placed[i1] = placed[i2] = True

        adj = _build_adjacency(tris)

        # BFS over faces, unfolding by hinge
        from collections import deque
        visited_faces = {0}
        queue: deque = deque([0])

        while queue:
            fi = queue.popleft()
            tri = tris[fi]
            for ai, bi in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])]:
                e = (min(ai, bi), max(ai, bi))
                for nfi in adj.get(e, []):
                    if nfi in visited_faces:
                        continue
                    visited_faces.add(nfi)
                    queue.append(nfi)
                    ntri = tris[nfi]
                    # ci is the vertex of neighbor not on the shared edge
                    ci = next(v for v in ntri if v != ai and v != bi)
                    if not placed[ci] and placed[ai] and placed[bi]:
                        # In the parent triangle, ai->bi winding determines which
                        # side is "inside". The neighbor ci goes on the opposite
                        # side (flip=True) because ai->bi appears in reversed
                        # winding in a consistently-oriented mesh neighbor.
                        ntri_list = list(ntri)
                        try:
                            ai_pos = ntri_list.index(ai)
                            bi_pos = ntri_list.index(bi)
                            # If bi follows ai in CCW order in the neighbor,
                            # the edge is in the same direction as in the parent
                            # -> ci should go on the same side (flip=False).
                            # In a consistently wound mesh, neighbors share edges
                            # with opposite winding, so bi_pos != (ai_pos+1)%3.
                            edge_same_direction = (bi_pos == (ai_pos + 1) % 3)
                        except ValueError:
                            edge_same_direction = False
                        flat[ci] = _unfold_triangle(
                            flat[ai], flat[bi],
                            verts[ci], verts[ai], verts[bi],
                            flip=(not edge_same_direction),
                        )
                        placed[ci] = True

        # Compute per-face area distortion
        area_distortion = []
        max_len_dist = 0.0
        for fi, tri in enumerate(tris):
            i, j, k = tri
            if placed[i] and placed[j] and placed[k]:
                a3 = _triangle_area_3d(verts[i], verts[j], verts[k])
                a2 = _triangle_area_2d(flat[i], flat[j], flat[k])
                ratio = abs(a2 - a3) / max(a3, 1e-15)
                area_distortion.append(float(ratio))
                for ia, ib in [(i, j), (j, k), (k, i)]:
                    l3 = _norm(verts[ib] - verts[ia])
                    l2 = _norm(flat[ib] - flat[ia])
                    if l3 > 1e-15:
                        max_len_dist = max(max_len_dist, abs(l2 - l3) / l3)
            else:
                area_distortion.append(float("nan"))

        valid_flat = flat[~np.isnan(flat[:, 0])]
        if len(valid_flat) >= 2:
            mins = valid_flat.min(axis=0)
            maxs = valid_flat.max(axis=0)
            w = float(maxs[0] - mins[0])
            h = float(maxs[1] - mins[1])
        else:
            w = h = 0.0

        max_area_dist = float(np.nanmax(area_distortion)) if area_distortion else 0.0

        return {
            "ok": True, "reason": "",
            "flat_vertices": flat.tolist(),
            "distortion": area_distortion,
            "max_length_distortion": float(max_len_dist),
            "max_area_distortion": float(max_area_dist),
            "total_developed_width": w,
            "total_developed_height": h,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc),
                "flat_vertices": [], "distortion": [],
                "max_length_distortion": 0.0, "max_area_distortion": 0.0,
                "total_developed_width": 0.0, "total_developed_height": 0.0}


# ---------------------------------------------------------------------------
# smash -- force-flatten with distortion map
# ---------------------------------------------------------------------------


def smash(
    vertices: Sequence,
    faces: Sequence,
    *,
    report_distortion: bool = True,
) -> dict:
    """Force-flatten an arbitrary mesh to 2D using PCA projection.

    Projects all vertices onto the best-fit plane (via PCA), then rotates
    so the plane aligns with Z=0.  Returns a distortion map.

    Parameters
    ----------
    vertices : list of [x, y, z]
    faces : list of [i, j, k]
    report_distortion : bool

    Returns
    -------
    dict with:
        ok              : bool
        reason          : str
        flat_vertices   : list of [x, y]
        distortion_map  : list of per-face area distortion ratios
        max_length_distortion  : float
        max_area_distortion    : float
        total_developed_width  : float
        total_developed_height : float
    """
    try:
        verts = np.array(vertices, dtype=float)
        tris: List[Tri] = [tuple(f) for f in faces]  # type: ignore[misc]

        if len(verts) < 3:
            return {"ok": False, "reason": "need at least 3 vertices",
                    "flat_vertices": [], "distortion_map": [],
                    "max_length_distortion": 0.0, "max_area_distortion": 0.0,
                    "total_developed_width": 0.0, "total_developed_height": 0.0}

        centroid = verts.mean(axis=0)
        centered = verts - centroid
        try:
            _, _, Vt = np.linalg.svd(centered, full_matrices=False)
        except np.linalg.LinAlgError:
            Vt = np.eye(3)

        ax1 = Vt[0]
        ax2 = Vt[1]

        flat_2d = np.column_stack([centered @ ax1, centered @ ax2])

        distortion_map: List[float] = []
        max_len_dist = 0.0

        if report_distortion:
            for tri in tris:
                i, j, k = tri
                a3 = _triangle_area_3d(verts[i], verts[j], verts[k])
                a2 = _triangle_area_2d(flat_2d[i], flat_2d[j], flat_2d[k])
                ratio = abs(a2 - a3) / max(a3, 1e-15)
                distortion_map.append(float(ratio))
                for ia, ib in [(i, j), (j, k), (k, i)]:
                    l3 = _norm(verts[ib] - verts[ia])
                    l2 = _norm(flat_2d[ib] - flat_2d[ia])
                    if l3 > 1e-15:
                        max_len_dist = max(max_len_dist, abs(l2 - l3) / l3)

        mins = flat_2d.min(axis=0)
        maxs = flat_2d.max(axis=0)
        w = float(maxs[0] - mins[0])
        h = float(maxs[1] - mins[1])

        max_area_dist = float(max(distortion_map)) if distortion_map else 0.0

        return {
            "ok": True, "reason": "",
            "flat_vertices": flat_2d.tolist(),
            "distortion_map": distortion_map,
            "max_length_distortion": float(max_len_dist),
            "max_area_distortion": float(max_area_dist),
            "total_developed_width": w,
            "total_developed_height": h,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc),
                "flat_vertices": [], "distortion_map": [],
                "max_length_distortion": 0.0, "max_area_distortion": 0.0,
                "total_developed_width": 0.0, "total_developed_height": 0.0}


# ---------------------------------------------------------------------------
# project_curves_to_unrolled
# ---------------------------------------------------------------------------


def project_curves_to_unrolled(
    surface_desc: Dict[str, Any],
    curves_3d: List[List[List[float]]],
) -> dict:
    """Map 3D curves/points onto the unrolled (developed) domain.

    Parameters
    ----------
    surface_desc : dict
        Same format as unroll_developable.
    curves_3d : list of list of [x, y, z]

    Returns
    -------
    dict with:
        ok           : bool
        reason       : str
        flat_curves  : list of list of [x, y]
    """
    try:
        stype = surface_desc.get("type", "")

        flat_curves: List[List[List[float]]] = []

        for curve in curves_3d:
            pts = [np.asarray(p, dtype=float) for p in curve]
            flat_pts: List[List[float]] = []

            for p in pts:
                if len(p) < 3:
                    continue

                if stype == "cylinder":
                    R = float(surface_desc["radius"])
                    theta = math.atan2(float(p[1]), float(p[0]))
                    if theta < 0:
                        theta += 2 * math.pi
                    flat_pts.append([R * theta, float(p[2])])

                elif stype == "cone":
                    R = float(surface_desc["base_radius"])
                    H = float(surface_desc["apex_height"])
                    slant = math.sqrt(R ** 2 + H ** 2)
                    sin_alpha = R / slant
                    sweep = float(surface_desc.get("sweep", 2 * math.pi))
                    r_xy = math.sqrt(float(p[0]) ** 2 + float(p[1]) ** 2)
                    dz = H - float(p[2])
                    r_flat = math.sqrt(r_xy ** 2 + dz ** 2) if r_xy > 1e-15 else 0.0
                    theta = math.atan2(float(p[1]), float(p[0]))
                    if theta < 0:
                        theta += 2 * math.pi
                    sector_angle = sweep * sin_alpha
                    phi_flat = (theta / sweep) * sector_angle if sweep > 0 else 0.0
                    flat_pts.append([r_flat * math.cos(phi_flat), r_flat * math.sin(phi_flat)])

                elif stype == "plane":
                    flat_pts.append([float(p[0]), float(p[1])])

                else:
                    flat_pts.append([float(p[0]), float(p[1])])

            flat_curves.append(flat_pts)

        return {"ok": True, "reason": "", "flat_curves": flat_curves}

    except Exception as exc:
        return {"ok": False, "reason": str(exc), "flat_curves": []}


# ---------------------------------------------------------------------------
# diagnostics helper
# ---------------------------------------------------------------------------


def surface_diagnostics(surface_desc: Dict[str, Any]) -> dict:
    """Return developed dimensions and max distortion summary for a surface."""
    try:
        dev = is_developable(surface_desc)
        if not dev["ok"]:
            return {**dev, "developed_width": 0.0, "developed_height": 0.0, "surface_type": ""}

        unrolled = unroll_developable(surface_desc)
        if not unrolled["ok"]:
            return {
                "ok": True,
                "reason": f"is_developable ok but unroll failed: {unrolled['reason']}",
                "is_developable": dev["is_developable"],
                "max_gaussian": dev["max_gaussian"],
                "developed_width": 0.0,
                "developed_height": 0.0,
                "surface_type": surface_desc.get("type", ""),
            }

        return {
            "ok": True, "reason": "",
            "is_developable": dev["is_developable"],
            "max_gaussian": dev["max_gaussian"],
            "developed_width": unrolled["developed_width"],
            "developed_height": unrolled["developed_height"],
            "surface_type": surface_desc.get("type", ""),
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc),
                "is_developable": False, "max_gaussian": 0.0,
                "developed_width": 0.0, "developed_height": 0.0, "surface_type": ""}


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # check_developability
    # ------------------------------------------------------------------

    _check_dev_spec = ToolSpec(
        name="check_developability",
        description=(
            "Check whether a surface or mesh is developable (Gaussian curvature ~= 0). "
            "Returns max/mean Gaussian curvature and a boolean is_developable flag.\n\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  is_developable  : bool\n"
            "  max_gaussian    : float\n"
            "  mean_gaussian   : float\n\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "surface": {
                    "type": "object",
                    "description": (
                        "Surface description. One of:\n"
                        "  {\"type\":\"cylinder\", \"radius\":R, \"height\":H, \"sweep\":theta}\n"
                        "  {\"type\":\"cone\", \"base_radius\":R, \"apex_height\":H, \"sweep\":theta}\n"
                        "  {\"type\":\"plane\"}\n"
                        "  {\"type\":\"mesh\", \"vertices\":[[x,y,z],...], \"faces\":[[i,j,k],...]}"
                    ),
                },
                "tol": {"type": "number", "description": "Gaussian curvature threshold (default 1e-4)."},
            },
            "required": ["surface"],
        },
    )

    @register(_check_dev_spec)
    async def run_check_developability(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        surface = a.get("surface")
        if not surface:
            return err_payload("surface is required", "BAD_ARGS")
        tol = a.get("tol", 1e-4)
        result = is_developable(surface, tol=float(tol))
        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")
        return ok_payload(result)

    # ------------------------------------------------------------------
    # unroll_surface
    # ------------------------------------------------------------------

    _unroll_spec = ToolSpec(
        name="unroll_surface",
        description=(
            "Unroll a developable surface (cylinder, cone, or near-developable mesh) "
            "into a flat 2D layout with exact edge-length preservation.\n\n"
            "Returns:\n"
            "  ok                    : bool\n"
            "  flat_vertices         : list of [x, y]\n"
            "  developed_width       : float\n"
            "  developed_height      : float\n"
            "  max_length_distortion : float  (mesh mode)\n"
            "  max_area_distortion   : float  (mesh mode)\n\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "surface": {"type": "object"},
                "tol": {"type": "number"},
            },
            "required": ["surface"],
        },
    )

    @register(_unroll_spec)
    async def run_unroll_surface(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        surface = a.get("surface")
        if not surface:
            return err_payload("surface is required", "BAD_ARGS")
        tol = float(a.get("tol", 1e-3))
        stype = surface.get("type", "")
        if stype == "mesh":
            verts = surface.get("vertices")
            faces = surface.get("faces")
            if not verts or not faces:
                return err_payload("mesh requires vertices and faces", "BAD_ARGS")
            result = unroll_strip(verts, faces, tol=tol)
        else:
            result = unroll_developable(surface)
        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")
        payload = {
            "flat_vertices": result["flat_vertices"],
            "developed_width": result.get("developed_width", result.get("total_developed_width", 0.0)),
            "developed_height": result.get("developed_height", result.get("total_developed_height", 0.0)),
            "surface_type": result.get("surface_type", stype),
        }
        if "max_length_distortion" in result:
            payload["max_length_distortion"] = result["max_length_distortion"]
            payload["max_area_distortion"] = result["max_area_distortion"]
        return ok_payload(payload)

    # ------------------------------------------------------------------
    # smash_surface
    # ------------------------------------------------------------------

    _smash_spec = ToolSpec(
        name="smash_surface",
        description=(
            "Force-flatten an arbitrary mesh (including non-developable) to 2D "
            "using PCA projection.  Returns a distortion map.\n\n"
            "Returns:\n"
            "  ok                    : bool\n"
            "  flat_vertices         : list of [x, y]\n"
            "  distortion_map        : list of per-face area distortion ratios\n"
            "  max_length_distortion : float\n"
            "  max_area_distortion   : float\n\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "report_distortion": {"type": "boolean"},
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_smash_spec)
    async def run_smash_surface(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        verts = a.get("vertices")
        faces = a.get("faces")
        if not verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not faces:
            return err_payload("faces is required", "BAD_ARGS")
        report = a.get("report_distortion", True)
        result = smash(verts, faces, report_distortion=bool(report))
        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")
        return ok_payload(result)
