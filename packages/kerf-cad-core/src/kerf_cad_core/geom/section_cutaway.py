"""
section_cutaway.py
==================
B-rep body section cutaway — ISO 128-30 compliant.

Cuts a body with a plane, extracts the cross-section as a 2D planar region
(list of 2D loops), and generates ISO 128-30 hatch patterns on the section.

Public API
----------
cut_body_with_plane(body, plane, side='positive') -> SectionResult
    Cut a B-rep body with a plane.  Returns:
        SectionResult.visible_body_half  : dict  — mesh of the kept half
        SectionResult.cross_section_2d   : list[list[[u,v]]]  — 2D loops
        SectionResult.hatched_2d         : list[dict]  — hatch line segments

hatch_cross_section(cross_section_2d, plane, hatch_pattern='ISO128-30_iron',
                    spacing=2.0) -> list[dict]
    Generate ISO 128-30 hatch lines for a 2D cross-section.
    Patterns:
        'ISO128-30_iron'  — 45° parallel lines (ANSI31 / ISO iron convention)
        'concrete'        — 45° lines + scatter dots (ISO 128-30 concrete)
        'plastic'         — horizontal lines (ISO 128-30 plastic/elastomer)

section_view_for_drawing(body, plane, drawing_scale=1.0) -> SectionView
    Wrap cut_body_with_plane + ISO 128-30 hatching + cutting-plane marker +
    arrow indicators per Bertoline §11.

References
----------
ISO 128-30:2001  §6 Section views — hatch conventions
Bertoline, "Fundamentals of Technical Drawing" §11 — sectioning

Never raises.  All public functions return structured dicts on failure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Plane helper
# ---------------------------------------------------------------------------

def _parse_plane(plane: Any) -> Tuple[np.ndarray, float]:
    """Parse plane spec to (unit_normal, d) where n·x = d.

    Accepts:
      {"normal": [nx, ny, nz], "d": d}
      {"normal": [nx, ny, nz], "point": [px, py, pz]}
      (normal_array_like, d_scalar)
      (normal_array_like, point_array_like)
    """
    if isinstance(plane, dict):
        n = np.asarray(plane["normal"], dtype=float).ravel()
        nrm = float(np.linalg.norm(n))
        if nrm < 1e-15:
            raise ValueError("plane normal is a zero vector")
        n = n / nrm
        if "d" in plane:
            d = float(plane["d"])
        elif "point" in plane:
            d = float(np.dot(n, np.asarray(plane["point"], dtype=float).ravel()))
        else:
            raise ValueError("plane dict must have 'd' or 'point' key")
        return n, d

    if isinstance(plane, (list, tuple)) and len(plane) == 2:
        n = np.asarray(plane[0], dtype=float).ravel()
        nrm = float(np.linalg.norm(n))
        if nrm < 1e-15:
            raise ValueError("plane normal is a zero vector")
        n = n / nrm
        second = np.asarray(plane[1], dtype=float).ravel()
        if second.size == 1:
            d = float(second[0])
        else:
            d = float(np.dot(n, second[:3]))
        return n, d

    raise ValueError(f"unrecognised plane specification: {plane!r}")


def _signed_dist_pt(pt: np.ndarray, n: np.ndarray, d: float) -> float:
    return float(np.dot(n, pt)) - d


# ---------------------------------------------------------------------------
# Body → mesh tessellation helpers
# ---------------------------------------------------------------------------

def _body_to_mesh(body: Any) -> Tuple[List[List[float]], List[List[int]]]:
    """Extract (verts, faces) from a brep Body or a pre-meshed dict.

    For analytic body types we build a uniform tessellation directly
    from the body's shells/faces.  We also accept a plain dict with
    'verts'/'faces' keys for easy testing.
    """
    # Plain mesh dict
    if isinstance(body, dict):
        verts = [list(v) for v in body.get("verts", body.get("vertices", []))]
        faces = [list(f) for f in body.get("faces", body.get("triangles", []))]
        return verts, faces

    # Try brep Body
    try:
        from kerf_cad_core.geom.brep import Body
        if isinstance(body, Body):
            return _tessellate_body(body)
    except ImportError:
        pass

    raise TypeError(f"Cannot extract mesh from {type(body).__name__}")


def _tessellate_body(body: Any) -> Tuple[List[List[float]], List[List[int]]]:
    """Tessellate a brep Body into triangles.

    We iterate over every Face in every Shell and triangulate each face's
    parametric domain.  For analytic surfaces (Plane, CylinderSurface,
    SphereSurface) we sample a fine grid and fan/quad-strip it.
    """
    from kerf_cad_core.geom.brep import Body, Plane, CylinderSurface, SphereSurface

    all_verts: List[np.ndarray] = []
    all_faces: List[List[int]] = []

    def _add_quad_grid(pts: np.ndarray, nu: int, nv: int) -> None:
        """Add a (nu x nv) point grid as triangles to all_verts/all_faces."""
        base = len(all_verts)
        for i in range(nu):
            for j in range(nv):
                all_verts.append(pts[i * nv + j])
        for i in range(nu - 1):
            for j in range(nv - 1):
                a = base + i * nv + j
                b = base + i * nv + (j + 1)
                c = base + (i + 1) * nv + j
                d = base + (i + 1) * nv + (j + 1)
                all_faces.append([a, b, c])
                all_faces.append([b, d, c])

    for solid in body.solids:
        for shell in solid.shells:
            for face in shell.faces:
                srf = face.surface
                # ---- Plane ----
                if isinstance(srf, Plane):
                    _tessellate_plane_face(face, srf, all_verts, all_faces)
                # ---- CylinderSurface ----
                elif isinstance(srf, CylinderSurface):
                    nu, nv = 32, 16
                    pts = np.array([
                        srf.evaluate(
                            float(u_val),
                            float(v_val),
                        )
                        for u_val in np.linspace(0.0, 2.0 * math.pi, nu)
                        for v_val in np.linspace(0.0, 1.0, nv)
                    ])
                    _add_quad_grid(pts, nu, nv)
                # ---- SphereSurface ----
                elif isinstance(srf, SphereSurface):
                    nu, nv = 32, 16
                    pts = np.array([
                        srf.evaluate(
                            float(u_val),
                            float(v_val),
                        )
                        for u_val in np.linspace(0.0, 2.0 * math.pi, nu)
                        for v_val in np.linspace(-math.pi / 2, math.pi / 2, nv)
                    ])
                    _add_quad_grid(pts, nu, nv)
                # ---- generic NurbsSurface or other ----
                else:
                    try:
                        _tessellate_generic_face(face, srf, all_verts, all_faces)
                    except Exception:
                        pass

    verts = [v.tolist() for v in all_verts]
    faces = all_faces
    return verts, faces


def _tessellate_plane_face(
    face: Any,
    srf: Any,
    all_verts: List[np.ndarray],
    all_faces: List[List[int]],
) -> None:
    """Tessellate a planar face by collecting corner vertices from its loops."""
    try:
        pts: List[np.ndarray] = []
        for lp in face.loops:
            if not lp.is_outer:
                continue
            for ce in lp.coedges:
                p = np.asarray(ce.start_point(), dtype=float)
                if not pts or float(np.linalg.norm(p - pts[-1])) > 1e-12:
                    pts.append(p)
        if len(pts) < 3:
            return
        base = len(all_verts)
        for p in pts:
            all_verts.append(p)
        # Fan triangulation
        for i in range(1, len(pts) - 1):
            all_faces.append([base, base + i, base + i + 1])
    except Exception:
        pass


def _tessellate_generic_face(
    face: Any,
    srf: Any,
    all_verts: List[np.ndarray],
    all_faces: List[List[int]],
) -> None:
    """UV-grid tessellation for NURBS/generic surfaces."""
    nu, nv = 16, 16
    # Get UV range
    if hasattr(srf, "knots_u") and hasattr(srf, "knots_v"):
        du, dv = srf.degree_u, srf.degree_v
        u0 = float(srf.knots_u[du])
        u1 = float(srf.knots_u[-(du + 1)])
        v0 = float(srf.knots_v[dv])
        v1 = float(srf.knots_v[-(dv + 1)])
    else:
        u0, u1, v0, v1 = 0.0, 1.0, 0.0, 1.0

    base = len(all_verts)
    pts = []
    for i, u in enumerate(np.linspace(u0, u1, nu)):
        for j, v in enumerate(np.linspace(v0, v1, nv)):
            p = np.asarray(srf.evaluate(float(u), float(v)), dtype=float)
            pts.append(p)
            all_verts.append(p)

    for i in range(nu - 1):
        for j in range(nv - 1):
            a = base + i * nv + j
            b = base + i * nv + (j + 1)
            c = base + (i + 1) * nv + j
            d = base + (i + 1) * nv + (j + 1)
            all_faces.append([a, b, c])
            all_faces.append([b, d, c])


# ---------------------------------------------------------------------------
# Mesh slicing — marching-triangles
# ---------------------------------------------------------------------------

def _lerp3(
    a: List[float], b: List[float], t: float
) -> List[float]:
    return [
        a[0] + t * (b[0] - a[0]),
        a[1] + t * (b[1] - a[1]),
        a[2] + t * (b[2] - a[2]),
    ]


def _section_mesh_by_plane(
    verts: List[List[float]],
    faces: List[List[int]],
    n: np.ndarray,
    d: float,
) -> List[List[List[float]]]:
    """Marching-Triangles: return list of polyline loops (3-D points)."""
    if not verts or not faces:
        return []
    sd = [_signed_dist_pt(np.asarray(v, dtype=float), n, d) for v in verts]

    segments: List[Tuple[List[float], List[float]]] = []
    for face in faces:
        if len(face) < 3:
            continue
        i, j, k = int(face[0]), int(face[1]), int(face[2])
        if i >= len(verts) or j >= len(verts) or k >= len(verts):
            continue
        s = [sd[i], sd[j], sd[k]]
        pts = [list(verts[i]), list(verts[j]), list(verts[k])]
        cross: List[List[float]] = []
        for ea, eb in [(0, 1), (1, 2), (2, 0)]:
            sa, sb = s[ea], s[eb]
            if (sa >= 0.0) != (sb >= 0.0):
                denom = sb - sa
                t = -sa / denom if abs(denom) > 1e-15 else 0.5
                cross.append(_lerp3(pts[ea], pts[eb], max(0.0, min(1.0, t))))
        if len(cross) == 2:
            segments.append((cross[0], cross[1]))

    return _chain_segments(segments)


def _pt_key(p: List[float], tol: float = 1e-9) -> Tuple[int, int, int]:
    s = 1.0 / max(tol, 1e-12)
    return (round(p[0] * s), round(p[1] * s), round(p[2] * s))


def _chain_segments(
    segments: List[Tuple[List[float], List[float]]],
    tol: float = 1e-9,
) -> List[List[List[float]]]:
    """Chain disconnected 3-D line segments into polylines."""
    if not segments:
        return []
    from collections import defaultdict
    key_to_pt: Dict[Tuple, List[float]] = {}
    adj: Dict[Tuple, List[Tuple]] = defaultdict(list)
    for idx, (a, b) in enumerate(segments):
        ka = _pt_key(a, tol)
        kb = _pt_key(b, tol)
        key_to_pt[ka] = a
        key_to_pt[kb] = b
        adj[ka].append((kb, idx))
        adj[kb].append((ka, idx))

    used: set = set()
    chains: List[List[List[float]]] = []
    for start_key in list(adj.keys()):
        if all(idx in used for (_, idx) in adj[start_key]):
            continue
        chain: List[List[float]] = [key_to_pt[start_key]]
        cur = start_key
        while True:
            moved = False
            for (nxt, idx) in adj[cur]:
                if idx not in used:
                    used.add(idx)
                    chain.append(key_to_pt[nxt])
                    cur = nxt
                    moved = True
                    break
            if not moved:
                break
        if len(chain) >= 2:
            chains.append(chain)
    return chains


# ---------------------------------------------------------------------------
# Half-body extraction (keep one side of the cut plane)
# ---------------------------------------------------------------------------

def _clip_mesh_to_halfspace(
    verts: List[List[float]],
    faces: List[List[int]],
    n: np.ndarray,
    d: float,
    side: str,
) -> Tuple[List[List[float]], List[List[int]]]:
    """Keep only the triangles on the selected side of the plane.

    Triangles that straddle the plane are split using linear interpolation.
    side == 'positive'  → keep where n·x >= d
    side == 'negative'  → keep where n·x <= d
    """
    sign = +1.0 if side == "positive" else -1.0
    sd = [sign * (_signed_dist_pt(np.asarray(v, dtype=float), n, d)) for v in verts]

    new_verts: List[List[float]] = list(verts)
    new_faces: List[List[int]] = []

    def _add_vert(p: List[float]) -> int:
        idx = len(new_verts)
        new_verts.append(p)
        return idx

    def _interp(ia: int, ib: int) -> int:
        sa, sb = sd[ia], sd[ib]
        denom = sb - sa
        t = max(0.0, min(1.0, -sa / denom if abs(denom) > 1e-15 else 0.5))
        p = _lerp3(new_verts[ia], new_verts[ib], t)
        return _add_vert(p)

    for face in faces:
        if len(face) < 3:
            continue
        i, j, k = int(face[0]), int(face[1]), int(face[2])
        if i >= len(verts) or j >= len(verts) or k >= len(verts):
            continue
        si, sj, sk = sd[i], sd[j], sd[k]
        inside = [(si >= -1e-12), (sj >= -1e-12), (sk >= -1e-12)]
        n_inside = sum(inside)
        if n_inside == 3:
            new_faces.append([i, j, k])
        elif n_inside == 0:
            pass  # entirely outside
        elif n_inside == 2:
            # One vertex outside; clip off the outside vertex
            out_idx = [m for m, ins in enumerate([i, j, k]) if not inside[m]][0]
            verts_tri = [i, j, k]
            v_out = verts_tri[out_idx]
            v_in1 = verts_tri[(out_idx + 1) % 3]
            v_in2 = verts_tri[(out_idx + 2) % 3]
            p1 = _interp(v_out, v_in1)
            p2 = _interp(v_out, v_in2)
            new_faces.append([v_in1, p1, v_in2])
            new_faces.append([p1, p2, v_in2])
        else:  # n_inside == 1
            in_idx = [m for m, ins in enumerate([i, j, k]) if inside[m]][0]
            verts_tri = [i, j, k]
            v_in = verts_tri[in_idx]
            v_out1 = verts_tri[(in_idx + 1) % 3]
            v_out2 = verts_tri[(in_idx + 2) % 3]
            p1 = _interp(v_in, v_out1)
            p2 = _interp(v_in, v_out2)
            new_faces.append([v_in, p1, p2])

    return new_verts, new_faces


# ---------------------------------------------------------------------------
# 3-D loops → 2-D projected loops
# ---------------------------------------------------------------------------

def _build_plane_frame(n: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Build (u_axis, v_axis) orthonormal frame in the cutting plane."""
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(ref, n))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    u_axis = ref - float(np.dot(ref, n)) * n
    nrm = float(np.linalg.norm(u_axis))
    if nrm < 1e-14:
        u_axis = np.array([0.0, 1.0, 0.0])
    else:
        u_axis = u_axis / nrm
    v_axis = np.cross(n, u_axis)
    v_nrm = float(np.linalg.norm(v_axis))
    if v_nrm > 1e-14:
        v_axis = v_axis / v_nrm
    return u_axis, v_axis


def _project_loops_to_2d(
    loops_3d: List[List[List[float]]],
    n: np.ndarray,
    d: float,
) -> List[List[List[float]]]:
    """Project 3-D section loops onto the cutting plane → list of 2-D loops.

    Each point becomes [u, v] (2-D coordinates in the plane frame).
    """
    u_ax, v_ax = _build_plane_frame(n)
    # Origin: the projection of the world origin onto the plane
    origin = d * n  # point on plane closest to world origin

    loops_2d: List[List[List[float]]] = []
    for loop in loops_3d:
        loop_2d: List[List[float]] = []
        for pt in loop:
            p = np.asarray(pt, dtype=float) - origin
            u = float(np.dot(p, u_ax))
            v = float(np.dot(p, v_ax))
            loop_2d.append([u, v])
        loops_2d.append(loop_2d)
    return loops_2d


# ---------------------------------------------------------------------------
# ISO 128-30 hatch generation
# ---------------------------------------------------------------------------

# ISO 128-30 material hatch conventions:
#   iron / steel / aluminium  — 45° equally-spaced parallel lines (ANSI 31)
#   concrete                  — 45° lines + scattered dots
#   plastic / elastomer       — horizontal lines (0°)

_HATCH_PATTERNS: Dict[str, Dict[str, Any]] = {
    "ISO128-30_iron": {
        "angle_deg": 45.0,
        "extra": "none",
        "description": "Iron, steel, aluminium — 45° parallel lines",
    },
    "concrete": {
        "angle_deg": 45.0,
        "extra": "dots",
        "description": "Concrete — 45° lines + scatter dots",
    },
    "plastic": {
        "angle_deg": 0.0,
        "extra": "none",
        "description": "Plastic / elastomer — horizontal lines",
    },
}

# Alias for the default iron pattern
_HATCH_PATTERNS["ansi31"] = _HATCH_PATTERNS["ISO128-30_iron"]


def _point_in_poly_2d(
    pt: np.ndarray, poly: List[np.ndarray]
) -> bool:
    """Ray-casting point-in-polygon test (2-D)."""
    x, y = float(pt[0]), float(pt[1])
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(poly[i][0]), float(poly[i][1])
        xj, yj = float(poly[j][0]), float(poly[j][1])
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _clip_line_to_poly_2d(
    origin: np.ndarray,
    direction: np.ndarray,
    poly: List[np.ndarray],
) -> List[Tuple[float, float]]:
    """Clip an infinite line to the interior of a 2-D polygon.

    Returns sorted list of (t_enter, t_exit) pairs.
    """
    params: List[float] = []
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        edge = b - a
        d = direction
        denom = d[0] * edge[1] - d[1] * edge[0]
        if abs(denom) < 1e-14:
            continue
        dx = a[0] - origin[0]
        dy = a[1] - origin[1]
        t = (dx * edge[1] - dy * edge[0]) / denom
        s = (dx * d[1] - dy * d[0]) / denom
        if -1e-9 <= s <= 1.0 + 1e-9:
            params.append(t)
    params.sort()
    segments = []
    for k in range(0, len(params) - 1, 2):
        t0, t1 = params[k], params[k + 1]
        mid = origin + 0.5 * (t0 + t1) * direction
        if _point_in_poly_2d(mid, poly):
            segments.append((t0, t1))
    return segments


def _hatch_loop_2d(
    loop_2d: List[List[float]],
    angle_deg: float,
    spacing: float,
) -> List[Dict[str, List[float]]]:
    """Generate ISO hatch lines for a single 2-D polygon loop.

    Returns list of {"start": [u0, v0], "end": [u1, v1]} dicts.
    """
    if len(loop_2d) < 3:
        return []

    poly = [np.array(pt[:2], dtype=float) for pt in loop_2d]
    poly_arr = np.array([p for p in poly])

    x_min, y_min = poly_arr[:, 0].min(), poly_arr[:, 1].min()
    x_max, y_max = poly_arr[:, 0].max(), poly_arr[:, 1].max()
    diag = float(np.hypot(x_max - x_min, y_max - y_min))

    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    direction = np.array([cos_a, sin_a])
    perp = np.array([-sin_a, cos_a])

    cx = 0.5 * (x_min + x_max)
    cy = 0.5 * (y_min + y_max)

    proj_vals = [float(np.dot(p, perp)) for p in poly_arr]
    proj_min, proj_max = min(proj_vals), max(proj_vals)

    n_lines = int(math.ceil((proj_max - proj_min) / spacing)) + 2
    proj_start = proj_min - spacing

    lines: List[Dict[str, List[float]]] = []
    for k in range(n_lines + 1):
        proj = proj_start + k * spacing
        # Line origin: point satisfying perp·origin = proj
        centre = np.array([cx, cy])
        origin = centre + (proj - float(np.dot(centre, perp))) * perp

        segs = _clip_line_to_poly_2d(origin, direction, poly)
        for (t0, t1) in segs:
            if t1 - t0 < 1e-10:
                continue
            p0 = origin + t0 * direction
            p1 = origin + t1 * direction
            lines.append({
                "start": [float(p0[0]), float(p0[1])],
                "end": [float(p1[0]), float(p1[1])],
            })

    return lines


def _dot_scatter(
    loop_2d: List[List[float]],
    spacing: float,
) -> List[Dict[str, Any]]:
    """Scatter dots inside a 2-D polygon for 'concrete' pattern.

    Returns list of {"center": [u, v], "radius": r} dicts.
    Dots are placed on a staggered grid with spacing * 0.75.
    """
    if len(loop_2d) < 3:
        return []

    poly = [np.array(pt[:2], dtype=float) for pt in loop_2d]
    poly_arr = np.array([p for p in poly])

    x_min, y_min = poly_arr[:, 0].min(), poly_arr[:, 1].min()
    x_max, y_max = poly_arr[:, 0].max(), poly_arr[:, 1].max()

    dot_spacing = spacing * 0.75
    dot_radius = spacing * 0.08  # small filled dot
    dots: List[Dict[str, Any]] = []

    row = 0
    y = y_min + dot_spacing * 0.5
    while y <= y_max + dot_spacing * 0.5:
        x_offset = (row % 2) * dot_spacing * 0.5  # stagger
        x = x_min + dot_spacing * 0.5 + x_offset
        while x <= x_max + dot_spacing * 0.5:
            pt = np.array([x, y])
            if _point_in_poly_2d(pt, poly):
                dots.append({"center": [float(x), float(y)], "radius": float(dot_radius)})
            x += dot_spacing
        y += dot_spacing
        row += 1

    return dots


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SectionResult:
    """Result of cutting a body with a plane.

    Attributes
    ----------
    visible_body_half : dict
        Tessellated mesh of the kept half:
        {"verts": [[x,y,z],...], "faces": [[i,j,k],...], "side": str}
    cross_section_2d : list of list of [u, v]
        One 2-D loop per closed contour in the cutting plane.
    hatched_2d : list of dict
        ISO 128-30 hatch segments per loop:
        [{"loop_index": int, "lines": [{"start":[u,v], "end":[u,v]}, ...],
          "pattern": str, "angle_deg": float, "dots": [...]}]
    plane_normal : [nx, ny, nz]
    plane_d : float
    ok : bool
    reason : str  (empty on success)
    """
    visible_body_half: Dict[str, Any] = field(default_factory=dict)
    cross_section_2d: List[List[List[float]]] = field(default_factory=list)
    hatched_2d: List[Dict[str, Any]] = field(default_factory=list)
    plane_normal: List[float] = field(default_factory=list)
    plane_d: float = 0.0
    ok: bool = True
    reason: str = ""


@dataclass
class SectionView:
    """Output of section_view_for_drawing — wraps SectionResult with ISO 128-30
    drawing annotations.

    Attributes
    ----------
    section_result : SectionResult
    cutting_plane_marker : dict
        {"line_start": [x,y,z], "line_end": [x,y,z], "style": "chain_line"}
    arrow_indicators : list of dict
        [{"origin": [x,y,z], "direction": [dx,dy,dz], "label": str}]
    drawing_scale : float
    section_id : str
    ok : bool
    reason : str
    """
    section_result: SectionResult = field(default_factory=SectionResult)
    cutting_plane_marker: Dict[str, Any] = field(default_factory=dict)
    arrow_indicators: List[Dict[str, Any]] = field(default_factory=list)
    drawing_scale: float = 1.0
    section_id: str = "A-A"
    ok: bool = True
    reason: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cut_body_with_plane(
    body: Any,
    plane: Any,
    side: str = "positive",
) -> SectionResult:
    """Cut a B-rep body (or mesh dict) with a plane.

    Parameters
    ----------
    body : Body | dict
        A brep Body or a plain dict with 'verts' and 'faces' keys (triangles).
    plane : dict | tuple
        Plane specification; see module docstring.  E.g.::
            {"normal": [0,0,1], "point": [0,0,5]}
    side : str
        'positive' — keep where n·x >= d  (default).
        'negative' — keep where n·x <= d.

    Returns
    -------
    SectionResult
        .ok          : bool
        .visible_body_half : {"verts":..., "faces":..., "side": side}
        .cross_section_2d  : list of 2-D loops [[u,v], ...]
        .hatched_2d        : ISO 128-30 hatch lines (iron / 45° default)
        .plane_normal, .plane_d
    """
    try:
        return _cut_body_with_plane_impl(body, plane, side)
    except Exception as exc:
        return SectionResult(ok=False, reason=f"cut_body_with_plane failed: {exc}")


def _cut_body_with_plane_impl(
    body: Any,
    plane: Any,
    side: str,
) -> SectionResult:
    if side not in ("positive", "negative"):
        raise ValueError(f"side must be 'positive' or 'negative'; got {side!r}")

    n, d = _parse_plane(plane)

    # 1. Tessellate body
    verts, faces = _body_to_mesh(body)

    # 2. Extract cross-section (3-D loops at the cut plane)
    loops_3d = _section_mesh_by_plane(verts, faces, n, d)

    # 3. Project to 2-D
    loops_2d = _project_loops_to_2d(loops_3d, n, d)

    # 4. Default hatch (ISO 128-30 iron = 45°)
    hatched = hatch_cross_section(loops_2d, plane, hatch_pattern="ISO128-30_iron")

    # 5. Clip mesh to the half-space
    half_verts, half_faces = _clip_mesh_to_halfspace(verts, faces, n, d, side)

    return SectionResult(
        visible_body_half={
            "verts": half_verts,
            "faces": half_faces,
            "side": side,
        },
        cross_section_2d=loops_2d,
        hatched_2d=hatched,
        plane_normal=n.tolist(),
        plane_d=float(d),
        ok=True,
        reason="",
    )


def hatch_cross_section(
    cross_section_2d: List[List[List[float]]],
    plane: Any,
    hatch_pattern: str = "ISO128-30_iron",
    spacing: float = 2.0,
) -> List[Dict[str, Any]]:
    """Generate ISO 128-30 hatch lines for a 2-D cross-section.

    Parameters
    ----------
    cross_section_2d : list of list of [u, v]
        2-D loop polygons (output of cut_body_with_plane or project_loops).
    plane : dict | tuple
        Plane specification (used for documentation / metadata only here;
        the actual geometry is already in 2-D).
    hatch_pattern : str
        One of:
            'ISO128-30_iron'  — 45° parallel lines (default)
            'concrete'        — 45° lines + scatter dots
            'plastic'         — 0° horizontal lines
    spacing : float
        Distance between hatch lines in the 2-D coordinate system.

    Returns
    -------
    list of dict, one per loop:
        {
          "loop_index"  : int,
          "lines"       : [{"start": [u0,v0], "end": [u1,v1]}, ...],
          "pattern"     : str,
          "angle_deg"   : float,
          "dots"        : [...],   # only for 'concrete' pattern
        }
    """
    try:
        return _hatch_cross_section_impl(
            cross_section_2d, hatch_pattern, spacing
        )
    except Exception as exc:
        return [{"ok": False, "reason": f"hatch_cross_section failed: {exc}"}]


def _hatch_cross_section_impl(
    cross_section_2d: List[List[List[float]]],
    hatch_pattern: str,
    spacing: float,
) -> List[Dict[str, Any]]:
    pattern_key = hatch_pattern.lower()
    # normalise aliases
    _aliases = {
        "iso128-30_iron": "ISO128-30_iron",
        "ansi31": "ISO128-30_iron",
        "iron": "ISO128-30_iron",
        "steel": "ISO128-30_iron",
        "concrete": "concrete",
        "plastic": "plastic",
    }
    canonical = _aliases.get(pattern_key, "ISO128-30_iron")

    pdef = _HATCH_PATTERNS[canonical]
    angle_deg = float(pdef["angle_deg"])
    extra = str(pdef.get("extra", "none"))

    result = []
    for li, loop in enumerate(cross_section_2d):
        lines = _hatch_loop_2d(loop, angle_deg, spacing)
        dots: List[Dict[str, Any]] = []
        if extra == "dots":
            dots = _dot_scatter(loop, spacing)
        result.append({
            "loop_index": li,
            "lines": lines,
            "pattern": canonical,
            "angle_deg": angle_deg,
            "dots": dots,
        })

    return result


def section_view_for_drawing(
    body: Any,
    plane: Any,
    drawing_scale: float = 1.0,
    section_id: str = "A-A",
    hatch_pattern: str = "ISO128-30_iron",
    hatch_spacing: float = 2.0,
) -> SectionView:
    """Build a complete ISO 128-30 section view for a 2D drawing.

    Wraps cut_body_with_plane + ISO 128-30 hatching + cutting-plane line marker
    + arrow indicators per Bertoline §11.

    Parameters
    ----------
    body : Body | dict
        B-rep body or mesh dict.
    plane : dict | tuple
        Cutting plane specification.
    drawing_scale : float
        Drawing scale (1.0 = full scale).
    section_id : str
        Section label, e.g. 'A-A', 'B-B'.
    hatch_pattern : str
        ISO 128-30 material pattern name.
    hatch_spacing : float
        Hatch line spacing in model units.

    Returns
    -------
    SectionView
        .section_result       : full SectionResult
        .cutting_plane_marker : dict with line start/end + style
        .arrow_indicators     : list of dicts with origin, direction, label
        .drawing_scale        : float
        .section_id           : str
        .ok                   : bool
    """
    try:
        return _section_view_for_drawing_impl(
            body, plane, drawing_scale, section_id, hatch_pattern, hatch_spacing
        )
    except Exception as exc:
        return SectionView(
            ok=False,
            reason=f"section_view_for_drawing failed: {exc}",
        )


def _section_view_for_drawing_impl(
    body: Any,
    plane: Any,
    drawing_scale: float,
    section_id: str,
    hatch_pattern: str,
    hatch_spacing: float,
) -> SectionView:
    n, d = _parse_plane(plane)

    # Cut and hatch
    result = cut_body_with_plane(body, plane, side="positive")
    if not result.ok:
        return SectionView(ok=False, reason=result.reason)

    # Re-hatch with the requested material pattern and spacing
    hatched = hatch_cross_section(
        result.cross_section_2d,
        plane,
        hatch_pattern=hatch_pattern,
        spacing=hatch_spacing,
    )
    result.hatched_2d = hatched

    # Build cutting-plane marker (ISO 128-30 §6.2 — chain line with thick ends)
    u_ax, v_ax = _build_plane_frame(n)
    # Estimate a half-width from the cross-section bounding box
    all_2d_pts: List[np.ndarray] = []
    for loop in result.cross_section_2d:
        for pt in loop:
            all_2d_pts.append(np.asarray(pt[:2], dtype=float))

    if all_2d_pts:
        arr = np.stack(all_2d_pts)
        u_range = float(arr[:, 0].max() - arr[:, 0].min())
        half_w = max(u_range * 0.5, 1.0)
    else:
        half_w = 10.0

    origin_3d = d * n
    marker_start = (origin_3d - half_w * u_ax * drawing_scale).tolist()
    marker_end = (origin_3d + half_w * u_ax * drawing_scale).tolist()

    # Arrow indicators (Bertoline §11: arrows perpendicular to cutting line,
    # pointing in the viewing direction — away from the cut-off side)
    arrow_dir = n.tolist()  # viewing direction = toward the kept positive side
    arrows = [
        {
            "origin": marker_start,
            "direction": arrow_dir,
            "label": section_id,
        },
        {
            "origin": marker_end,
            "direction": arrow_dir,
            "label": section_id,
        },
    ]

    return SectionView(
        section_result=result,
        cutting_plane_marker={
            "line_start": marker_start,
            "line_end": marker_end,
            "style": "chain_line",
            "label": section_id,
        },
        arrow_indicators=arrows,
        drawing_scale=float(drawing_scale),
        section_id=str(section_id),
        ok=True,
        reason="",
    )


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

    _section_view_spec = ToolSpec(
        name="brep_section_view",
        description=(
            "Cut a B-rep body (or triangle mesh) with a plane, extract the "
            "cross-section as 2-D loops, and generate ISO 128-30 hatch lines "
            "on the section face.  Returns the tessellated visible half-body, "
            "2-D cross-section loops, and hatch segments ready for drawing.\n\n"
            "Plane conventions:\n"
            "  normal [0,0,1] + point [0,0,5]  → cut at z=5, keep z>5.\n"
            "  normal [0,1,0] + point [0,0,0]  → cut at y=0.\n\n"
            "ISO 128-30 hatch patterns:\n"
            "  'ISO128-30_iron' — iron/steel/aluminium (45° lines)\n"
            "  'concrete'       — concrete (45° lines + dots)\n"
            "  'plastic'        — plastic/elastomer (horizontal lines)\n\n"
            "Returns:\n"
            "  ok                 : bool\n"
            "  visible_body_half  : {verts, faces, side}\n"
            "  cross_section_2d   : list of [[u,v],...] 2-D loops\n"
            "  hatched_2d         : list of {loop_index, lines, pattern, angle_deg, dots}\n"
            "  cutting_plane_marker, arrow_indicators  (drawing annotations)\n"
            "  section_id, drawing_scale\n\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "verts": {
                    "type": "array",
                    "description": "Mesh vertices [[x,y,z], ...].  Supply either verts+faces or body_id.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Triangle faces [[i,j,k], ...] (0-based).",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "plane_normal": {
                    "type": "array",
                    "description": "Cutting plane normal [nx, ny, nz].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "plane_point": {
                    "type": "array",
                    "description": "A point on the cutting plane [x, y, z].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "side": {
                    "type": "string",
                    "enum": ["positive", "negative"],
                    "description": "Which half to keep. 'positive' keeps n·x >= d (default).",
                },
                "hatch_pattern": {
                    "type": "string",
                    "enum": ["ISO128-30_iron", "concrete", "plastic"],
                    "description": "ISO 128-30 material hatch pattern (default 'ISO128-30_iron').",
                },
                "hatch_spacing": {
                    "type": "number",
                    "description": "Distance between hatch lines in model units (default 2.0).",
                },
                "drawing_scale": {
                    "type": "number",
                    "description": "Drawing scale factor (default 1.0).",
                },
                "section_id": {
                    "type": "string",
                    "description": "Section label for the drawing annotation (default 'A-A').",
                },
            },
            "required": ["plane_normal", "plane_point"],
        },
    )

    @register(_section_view_spec)
    async def run_brep_section_view(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        plane_normal = a.get("plane_normal")
        plane_point = a.get("plane_point")

        if plane_normal is None or plane_point is None:
            return err_payload("plane_normal and plane_point are required", "BAD_ARGS")

        verts = a.get("verts")
        faces = a.get("faces")

        if verts is None or faces is None:
            return err_payload("verts and faces are required", "BAD_ARGS")

        body = {"verts": verts, "faces": faces}
        plane = {"normal": plane_normal, "point": plane_point}

        side = a.get("side", "positive")
        hatch_pattern = a.get("hatch_pattern", "ISO128-30_iron")
        hatch_spacing = float(a.get("hatch_spacing", 2.0))
        drawing_scale = float(a.get("drawing_scale", 1.0))
        section_id = str(a.get("section_id", "A-A"))

        view = section_view_for_drawing(
            body,
            plane,
            drawing_scale=drawing_scale,
            section_id=section_id,
            hatch_pattern=hatch_pattern,
            hatch_spacing=hatch_spacing,
        )

        if not view.ok:
            return err_payload(view.reason, "OP_FAILED")

        sr = view.section_result
        return ok_payload({
            "ok": True,
            "visible_body_half": sr.visible_body_half,
            "cross_section_2d": sr.cross_section_2d,
            "hatched_2d": sr.hatched_2d,
            "plane_normal": sr.plane_normal,
            "plane_d": sr.plane_d,
            "cutting_plane_marker": view.cutting_plane_marker,
            "arrow_indicators": view.arrow_indicators,
            "drawing_scale": view.drawing_scale,
            "section_id": view.section_id,
        })
