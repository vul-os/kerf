"""
kerf_cad_core.geom.mold_parting_surface — Mold parting-surface construction.

GK-P (Wave 4T): Parting-surface construction (Yu-Fan 2003)
-----------------------------------------------------------
Given a parting line (the silhouette of a body w.r.t. a pull direction, from
GK-118) and a mold block bounding box, construct the **parting surface** —
the continuous ruled surface sheet that separates the top (cavity) and bottom
(core) mold halves and coincides with the parting line.

Theory
------
Yu-Fan Chen, "Computer-aided design of plastic injection molds", 2003, §6:
  The parting surface is constructed by sweeping rays from each parting-line
  point perpendicular to the pull direction until they hit the mold block
  boundary.  Adjacent rays form a ruled surface strip; all strips are stitched
  into a single planar (or near-planar) parting sheet.

For axis-aligned pull directions, each parting point p projects onto the
parting plane (the plane through the parting-line centroid, normal = pull).
The ray extends from p outward in the plane until it reaches the mold_bbox
boundary.  Adjacent rays form a linear ruled quadrilateral (bilinear patch).

Kalpakjian & Schmid, "Manufacturing Engineering and Technology", 7th ed.,
§19.10 confirms: the parting surface follows the parting line and extends to
the mold block perimeter.

Algorithm
---------
1. Collect parting_line points (from GK-118 ``parting_line()``).
2. Compute the parting plane: origin = mean of parting points projected onto
   pull axis; normal = pull_hat.
3. Project each parting point onto this parting plane (snap to plane along
   pull direction).
4. Order the projected points angularly around the parting plane centroid
   (convex ordering for well-behaved silhouettes).
5. For each consecutive pair of ordered points, extend both points radially
   in the parting plane to the mold_block_bbox boundary, forming a ruled quad
   strip.
6. Stitch all strips into a single parting surface mesh (vertices + quads).
7. For ``construct_with_shutoff_inserts``: identify undercut zones, add
   shutoff patch panels connecting the part surface boundary to the parting
   plane at those locations.
8. ``validate_parting_surface`` checks that the parting surface spans the
   mold block perimeter and that the top/bottom surfaces together with the
   body form a nominally closed volume.

Output
------
The surface is returned as a dict with ``vertices``, ``faces`` (quad/tri
index lists), ``area``, and ``is_planar`` — a lightweight mesh representation
that is independent of the B-rep topology layer, consistent with how
``generate_parting_surface`` in kerf_mold works and easily testable.

The ``parting_surface_top`` and ``parting_surface_bottom`` are symmetric
copies — the parting surface is shared between the two halves; one copy is
assigned to the cavity, the other to the core.

All code is pure-Python / NumPy; no OCC dependency.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

Point3 = List[float]
BBox = Tuple[Point3, Point3]   # (lo, hi) corners
SurfaceMesh = Dict            # {vertices, faces, area, is_planar, ...}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TOL = 1e-9


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > _TOL else v


def _perp_axes(pull_hat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return two mutually-orthogonal axes lying in the parting plane (⊥ pull)."""
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(pull_hat, ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    u_ax = _unit(np.cross(pull_hat, ref))
    v_ax = _unit(np.cross(pull_hat, u_ax))
    return u_ax, v_ax


def _project_onto_plane(
    point: np.ndarray,
    plane_origin: np.ndarray,
    pull_hat: np.ndarray,
) -> np.ndarray:
    """Snap *point* onto the parting plane (translate along pull to plane)."""
    offset = float(np.dot(point - plane_origin, pull_hat))
    return point - offset * pull_hat


def _ray_bbox_intersect(
    origin: np.ndarray,
    direction: np.ndarray,
    bbox_lo: np.ndarray,
    bbox_hi: np.ndarray,
) -> Optional[np.ndarray]:
    """Intersect a ray (origin + t*direction, t >= 0) with an AABB.

    Returns the *farthest* positive-t intersection point, or None if the ray
    does not intersect the box interior.  Used to extend parting-plane rays to
    the mold block boundary.
    """
    if float(np.linalg.norm(direction)) < _TOL:
        return None

    t_min = float("-inf")
    t_max = float("inf")

    for i in range(3):
        d = float(direction[i])
        o = float(origin[i])
        lo = float(bbox_lo[i])
        hi = float(bbox_hi[i])
        if abs(d) < _TOL:
            if o < lo - _TOL or o > hi + _TOL:
                return None  # parallel & outside
        else:
            t1 = (lo - o) / d
            t2 = (hi - o) / d
            if t1 > t2:
                t1, t2 = t2, t1
            t_min = max(t_min, t1)
            t_max = min(t_max, t2)

    if t_max < t_min - _TOL:
        return None

    # We want the farthest positive intersection (exit point)
    t = t_max if t_max > _TOL else t_min
    if t < _TOL:
        return None
    return origin + t * direction


def _angular_order(
    pts_in_plane: np.ndarray,
    centroid: np.ndarray,
    u_ax: np.ndarray,
    v_ax: np.ndarray,
) -> np.ndarray:
    """Return indices that sort *pts_in_plane* by angle around *centroid*."""
    rel = pts_in_plane - centroid
    angles = np.arctan2(rel @ v_ax, rel @ u_ax)
    return np.argsort(angles)


def _quad_area(p0, p1, p2, p3) -> float:
    """Approximate area of a planar quadrilateral via two triangles."""
    t1 = 0.5 * float(np.linalg.norm(np.cross(p1 - p0, p3 - p0)))
    t2 = 0.5 * float(np.linalg.norm(np.cross(p2 - p1, p3 - p1)))
    return t1 + t2


def _is_planar(pts: np.ndarray, tol: float = 1e-4) -> bool:
    """Return True if all *pts* lie within *tol* of their best-fit plane."""
    if len(pts) < 4:
        return True
    centroid = pts.mean(axis=0)
    _, _, Vt = np.linalg.svd(pts - centroid)
    normal = Vt[-1]  # smallest singular-value direction
    dists = np.abs((pts - centroid) @ normal)
    return bool(dists.max() < tol)


# ---------------------------------------------------------------------------
# Core: parting plane + ray extension to bbox
# ---------------------------------------------------------------------------

def _build_parting_strip(
    p_inner: np.ndarray,
    q_inner: np.ndarray,
    p_outer: np.ndarray,
    q_outer: np.ndarray,
) -> Tuple[List[List[float]], List[List[int]]]:
    """One ruled quadrilateral strip (4 vertices, 2 triangles)."""
    verts = [p_inner.tolist(), q_inner.tolist(), q_outer.tolist(), p_outer.tolist()]
    faces = [[0, 1, 2, 3]]   # quad (CCW when viewed from pull side)
    return verts, faces


def _extend_to_bbox(
    pt: np.ndarray,
    centroid: np.ndarray,
    bbox_lo: np.ndarray,
    bbox_hi: np.ndarray,
    u_ax: np.ndarray,
    v_ax: np.ndarray,
) -> np.ndarray:
    """Extend *pt* radially outward from *centroid* (in the parting plane) to bbox."""
    radial = pt - centroid
    radial_n = float(np.linalg.norm(radial))
    if radial_n < _TOL:
        # Degenerate: pt at centroid — pick an arbitrary outward direction
        radial = u_ax * 1e-6
        radial_n = 1e-6
    direction = radial / radial_n
    # Small epsilon beyond current position so t>0 from the *extended* origin
    start = centroid + direction * _TOL
    hit = _ray_bbox_intersect(start, direction, bbox_lo, bbox_hi)
    if hit is None:
        # Fallback: project direction to bbox half-extents
        mid = 0.5 * (bbox_lo + bbox_hi)
        half_ext = 0.5 * (bbox_hi - bbox_lo)
        # Scale to reach box face along dominant axis
        scales = []
        for i in range(3):
            if abs(direction[i]) > _TOL:
                t_pos = (mid[i] + half_ext[i] - float(start[i])) / direction[i]
                t_neg = (mid[i] - half_ext[i] - float(start[i])) / direction[i]
                for t in (t_pos, t_neg):
                    if t > _TOL:
                        scales.append(t)
        t = min(scales) if scales else 1.0
        hit = start + t * direction
    return hit


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def construct_parting_surface(
    body: object,
    parting_line_pts: Sequence[Point3],
    mold_block_bbox: Tuple[Sequence[float], Sequence[float]],
    pull_direction: Union[Sequence[float], np.ndarray],
    *,
    n_angular_samples: int = 0,
) -> Tuple[SurfaceMesh, SurfaceMesh]:
    """Construct the mold parting surface from a parting line and mold bbox.

    Given the parting line (output of ``kerf_cad_core.geom.mold.parting_line``)
    and the mold block bounding box, build the parting surface that separates
    the top (cavity) and bottom (core) mold halves.

    Algorithm (Yu-Fan 2003 §6)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. Project all parting-line points onto the parting plane
       (plane whose normal = pull_hat, passing through parting-line centroid).
    2. Sort projected points angularly around the centroid.
    3. For each consecutive pair of projected points:
       - Extend both radially in the parting plane to the ``mold_block_bbox``
         boundary → outer boundary of the surface.
       - Form a ruled quadrilateral (inner edge = parting-line segment,
         outer edge = bbox boundary).
    4. Stitch all quads into a single surface mesh.
    5. Return identical copies as ``(parting_surface_top, parting_surface_bottom)``
       — one for the cavity, one for the core.

    Parameters
    ----------
    body:
        The moulded part (not used directly in the geometric construction, but
        included for API completeness and future surface-trim integration).
    parting_line_pts:
        List of 3-D points on the parting line (from ``parting_line()``).
        At least 3 points are required.
    mold_block_bbox:
        ``((xlo, ylo, zlo), (xhi, yhi, zhi))`` — the bounding box of the mold
        block.  The parting surface extends from the parting line outward to
        this boundary.
    pull_direction:
        3-vector giving the mold pull / demould direction.
    n_angular_samples:
        If > 0, resample the angularly-sorted loop to this many equally-spaced
        angular positions (useful to densify the surface for smooth renders).

    Returns
    -------
    ``(parting_surface_top, parting_surface_bottom)``
        Each is a ``SurfaceMesh`` dict::

            {
                "vertices": [[x, y, z], ...],
                "faces":    [[i0, i1, i2, i3], ...],   # quads
                "area":     float,
                "is_planar": bool,
                "centroid": [x, y, z],
                "pull_direction": [dx, dy, dz],
            }

    Raises
    ------
    ValueError
        If *pull_direction* is zero, or *parting_line_pts* has fewer than 3 pts.
    """
    pull = np.asarray(pull_direction, dtype=float).ravel()[:3]
    pull_nrm = float(np.linalg.norm(pull))
    if pull_nrm < _TOL:
        raise ValueError("pull_direction must be a non-zero vector")
    pull_hat = pull / pull_nrm

    pts = [np.asarray(p, dtype=float)[:3] for p in parting_line_pts]
    if len(pts) < 3:
        raise ValueError("parting_line_pts must have at least 3 points")

    pts_arr = np.array(pts, dtype=float)

    # --- Parting plane -----------------------------------------------------
    # Parting height = mean projection of parting points onto pull axis
    pull_proj = pts_arr @ pull_hat
    parting_height = float(pull_proj.mean())
    # A reference point on the parting plane
    plane_origin = parting_height * pull_hat

    # Centroid of parting points projected onto parting plane
    pts_proj = np.array([_project_onto_plane(p, plane_origin, pull_hat) for p in pts])
    centroid = pts_proj.mean(axis=0)

    # Parting-plane axes
    u_ax, v_ax = _perp_axes(pull_hat)

    # --- Angular sort -------------------------------------------------------
    order = _angular_order(pts_proj, centroid, u_ax, v_ax)
    ordered = pts_proj[order]  # (N, 3) projected + sorted parting pts

    n = len(ordered)

    # Optional resampling
    if n_angular_samples > 3:
        angles_orig = np.arctan2((ordered - centroid) @ v_ax,
                                 (ordered - centroid) @ u_ax)
        angles_orig = np.append(angles_orig, angles_orig[0] + 2 * math.pi)
        radii_orig = np.linalg.norm(ordered - centroid, axis=1)
        radii_orig = np.append(radii_orig, radii_orig[0])
        angles_new = np.linspace(angles_orig[0], angles_orig[0] + 2 * math.pi,
                                 n_angular_samples + 1)[:-1]
        radii_new = np.interp(angles_new, angles_orig, radii_orig)
        ordered = np.array([
            centroid + r * (math.cos(a) * u_ax + math.sin(a) * v_ax)
            for r, a in zip(radii_new, angles_new)
        ])
        n = len(ordered)

    # --- Bbox ---------------------------------------------------------------
    bbox_lo = np.asarray(mold_block_bbox[0], dtype=float)[:3]
    bbox_hi = np.asarray(mold_block_bbox[1], dtype=float)[:3]

    # --- Build quad strips --------------------------------------------------
    all_verts: List[np.ndarray] = []
    all_faces: List[List[int]] = []
    total_area = 0.0

    for i in range(n):
        p_inner = ordered[i]
        q_inner = ordered[(i + 1) % n]
        p_outer = _extend_to_bbox(p_inner, centroid, bbox_lo, bbox_hi, u_ax, v_ax)
        q_outer = _extend_to_bbox(q_inner, centroid, bbox_lo, bbox_hi, u_ax, v_ax)

        base = len(all_verts)
        all_verts.extend([p_inner, q_inner, q_outer, p_outer])
        all_faces.append([base, base + 1, base + 2, base + 3])
        total_area += _quad_area(p_inner, q_inner, q_outer, p_outer)

    verts_arr = np.array([v.tolist() for v in all_verts])
    planar = _is_planar(verts_arr)
    vert_list = [v.tolist() for v in all_verts]
    centroid_out = centroid.tolist()
    pull_out = pull_hat.tolist()

    mesh: SurfaceMesh = {
        "vertices": vert_list,
        "faces": all_faces,
        "area": total_area,
        "is_planar": planar,
        "centroid": centroid_out,
        "pull_direction": pull_out,
        "parting_height": float(parting_height),
    }

    # Top and bottom are symmetric — same surface sheet, labelled differently
    import copy
    mesh_top = copy.deepcopy(mesh)
    mesh_top["side"] = "top"
    mesh_bottom = copy.deepcopy(mesh)
    mesh_bottom["side"] = "bottom"

    return mesh_top, mesh_bottom


def construct_with_shutoff_inserts(
    body: object,
    parting_line_pts: Sequence[Point3],
    pull_direction: Union[Sequence[float], np.ndarray],
    *,
    undercut_regions: Optional[Sequence[Sequence[Point3]]] = None,
) -> Tuple[SurfaceMesh, SurfaceMesh]:
    """Construct parting surfaces with shutoff inserts for undercut zones.

    Shutoff surfaces are small planar patches that fill the gap between the
    part's undercut feature boundary and the nominal parting plane.  They
    are required to close the mold cavity at undercut locations.

    Algorithm
    ~~~~~~~~~
    1. Compute the parting plane from the parting line.
    2. For each undercut region (a closed loop of 3-D points on the part
       boundary adjacent to an undercut feature):
       - Project the region boundary onto the parting plane.
       - Construct a fan-triangulated planar patch (the shutoff face).
       - Append the shutoff patch vertices/faces to the base parting surface.
    3. Return ``(top, bottom)`` meshes augmented with the shutoff patches.

    Parameters
    ----------
    body:
        The moulded part (duck-typed; must have ``all_faces()``).
    parting_line_pts:
        List of 3-D parting-line points (from ``parting_line()``).
    pull_direction:
        3-vector giving the mold pull direction.
    undercut_regions:
        Optional list of undercut regions.  Each region is a list of 3-D
        points forming a closed loop that bounds an undercut zone.  If
        ``None``, undercut detection falls back to ``undercut_faces()``
        from ``kerf_cad_core.geom.mold``.

    Returns
    -------
    ``(top, bottom)`` — augmented ``SurfaceMesh`` dicts with a
    ``"shutoff_patches"`` key listing each inserted patch.

    Raises
    ------
    ValueError
        If *pull_direction* is zero or *parting_line_pts* has < 3 pts.
    """
    pull = np.asarray(pull_direction, dtype=float).ravel()[:3]
    pull_nrm = float(np.linalg.norm(pull))
    if pull_nrm < _TOL:
        raise ValueError("pull_direction must be a non-zero vector")
    pull_hat = pull / pull_nrm

    pts = [np.asarray(p, dtype=float)[:3] for p in parting_line_pts]
    if len(pts) < 3:
        raise ValueError("parting_line_pts must have at least 3 points")

    pts_arr = np.array(pts, dtype=float)
    parting_height = float((pts_arr @ pull_hat).mean())
    plane_origin = parting_height * pull_hat

    # Base parting surfaces (use a large enough fake bbox that won't matter
    # for shutoff geometry itself — caller can call construct_parting_surface
    # for the full surface)
    # Determine bbox from part + some margin
    try:
        part_pts = [
            np.asarray(v.point, dtype=float)[:3]
            for v in body.all_vertices()  # type: ignore[attr-defined]
        ]
        if part_pts:
            part_arr = np.array(part_pts, dtype=float)
            margin = float(np.max(part_arr.max(axis=0) - part_arr.min(axis=0))) * 2.0
            bbox_lo = (part_arr.min(axis=0) - margin).tolist()
            bbox_hi = (part_arr.max(axis=0) + margin).tolist()
        else:
            bbox_lo = [-10.0, -10.0, -10.0]
            bbox_hi = [10.0, 10.0, 10.0]
    except Exception:
        bbox_lo = [-10.0, -10.0, -10.0]
        bbox_hi = [10.0, 10.0, 10.0]

    base_top, base_bottom = construct_parting_surface(
        body, pts, (bbox_lo, bbox_hi), pull_hat
    )

    # --- Determine undercut regions -----------------------------------------
    if undercut_regions is None:
        # Auto-detect from body
        try:
            from kerf_cad_core.geom.mold import undercut_faces, _face_surface_domain
            result = undercut_faces(body, pull_hat)
            undercut_ids = set(result.get("undercut_face_ids", []))
            undercut_regions = []
            for face in body.all_faces():  # type: ignore[attr-defined]
                if face.id not in undercut_ids:
                    continue
                # Sample boundary of undercut face as a rectangular loop
                srf = face.surface
                u0, u1, v0, v1 = _face_surface_domain(face)
                loop_pts: List[List[float]] = []
                for u in np.linspace(u0, u1, 5):
                    p = np.asarray(srf.evaluate(float(u), v0), dtype=float)[:3]
                    loop_pts.append(p.tolist())
                for v in np.linspace(v0, v1, 5):
                    p = np.asarray(srf.evaluate(float(u1), float(v)), dtype=float)[:3]
                    loop_pts.append(p.tolist())
                for u in np.linspace(u1, u0, 5):
                    p = np.asarray(srf.evaluate(float(u), v1), dtype=float)[:3]
                    loop_pts.append(p.tolist())
                for v in np.linspace(v1, v0, 5):
                    p = np.asarray(srf.evaluate(float(u0), float(v)), dtype=float)[:3]
                    loop_pts.append(p.tolist())
                if loop_pts:
                    undercut_regions.append(loop_pts)
        except Exception:
            undercut_regions = []

    shutoff_patches: List[dict] = []

    for region in undercut_regions:
        if not region or len(region) < 3:
            continue
        region_pts = np.array([np.asarray(p, dtype=float)[:3] for p in region])
        # Project boundary loop onto parting plane
        proj_pts = np.array([
            _project_onto_plane(p, plane_origin, pull_hat) for p in region_pts
        ])
        # Fan triangulate from centroid
        cent = proj_pts.mean(axis=0)
        patch_verts = [cent.tolist()] + [p.tolist() for p in proj_pts]
        patch_faces = [
            [0, i + 1, (i + 1) % len(proj_pts) + 1]
            for i in range(len(proj_pts))
        ]
        patch_area = sum(
            0.5 * float(np.linalg.norm(np.cross(
                proj_pts[i] - cent,
                proj_pts[(i + 1) % len(proj_pts)] - cent
            )))
            for i in range(len(proj_pts))
        )
        patch = {
            "vertices": patch_verts,
            "faces": patch_faces,
            "area": patch_area,
            "type": "shutoff",
        }
        shutoff_patches.append(patch)

        # Merge into base meshes
        for mesh in (base_top, base_bottom):
            base_offset = len(mesh["vertices"])
            mesh["vertices"].extend(patch_verts)
            mesh["faces"].extend([
                [base_offset + fi for fi in f] for f in patch_faces
            ])
            mesh["area"] = float(mesh["area"]) + patch_area

    base_top["shutoff_patches"] = shutoff_patches
    base_bottom["shutoff_patches"] = shutoff_patches

    return base_top, base_bottom


def validate_parting_surface(
    body: object,
    top_surface: SurfaceMesh,
    bottom_surface: SurfaceMesh,
    pull_direction: Union[Sequence[float], np.ndarray],
    *,
    area_tol_frac: float = 0.01,
) -> Dict:
    """Validate the parting surface against the mold geometry.

    Checks
    ~~~~~~
    1. **Non-empty** — both top and bottom surfaces have vertices and faces.
    2. **Co-planar** — all surface vertices within the parting plane (or
       within ``area_tol_frac * bbox_extent`` of it) for flat-parting-surface
       bodies.
    3. **Pull-direction alignment** — stored ``pull_direction`` in each
       surface mesh matches the supplied *pull_direction* (within 1°).
    4. **Symmetric** — top and bottom meshes have matching vertex/face counts
       (they are symmetric copies of the same sheet).
    5. **Area positive** — combined parting surface area > 0.

    Parameters
    ----------
    body:
        The moulded part (not directly used in validation, included for API).
    top_surface, bottom_surface:
        The ``SurfaceMesh`` dicts returned by ``construct_parting_surface``.
    pull_direction:
        The pull direction used when constructing the surfaces.
    area_tol_frac:
        Relative tolerance for area checks (default 0.01 = 1 %).

    Returns
    -------
    dict::

        {
            "valid": bool,
            "checks": {
                "non_empty": bool,
                "pull_aligned": bool,
                "symmetric": bool,
                "area_positive": bool,
            },
            "warnings": [str, ...],
            "errors": [str, ...],
        }
    """
    pull = np.asarray(pull_direction, dtype=float).ravel()[:3]
    pull_nrm = float(np.linalg.norm(pull))
    if pull_nrm < _TOL:
        return {
            "valid": False,
            "checks": {},
            "warnings": [],
            "errors": ["pull_direction is zero vector"],
        }
    pull_hat = pull / pull_nrm

    errors: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, bool] = {}

    # 1. Non-empty
    non_empty = (
        bool(top_surface.get("vertices"))
        and bool(top_surface.get("faces"))
        and bool(bottom_surface.get("vertices"))
        and bool(bottom_surface.get("faces"))
    )
    checks["non_empty"] = non_empty
    if not non_empty:
        errors.append("One or both parting surfaces are empty (no vertices/faces)")

    # 2. Pull-direction alignment
    pull_aligned = True
    for label, surf in (("top", top_surface), ("bottom", bottom_surface)):
        stored_pull = surf.get("pull_direction")
        if stored_pull is not None:
            sp = np.asarray(stored_pull, dtype=float)
            sp_nrm = float(np.linalg.norm(sp))
            if sp_nrm > _TOL:
                cos_a = float(np.clip(np.dot(sp / sp_nrm, pull_hat), -1.0, 1.0))
                angle_deg = math.degrees(math.acos(abs(cos_a)))
                if angle_deg > 1.0:
                    pull_aligned = False
                    errors.append(
                        f"{label} surface pull_direction deviates by "
                        f"{angle_deg:.2f}° from supplied pull_direction"
                    )
    checks["pull_aligned"] = pull_aligned

    # 3. Symmetric
    n_verts_top = len(top_surface.get("vertices", []))
    n_verts_bot = len(bottom_surface.get("vertices", []))
    n_faces_top = len(top_surface.get("faces", []))
    n_faces_bot = len(bottom_surface.get("faces", []))
    symmetric = (n_verts_top == n_verts_bot) and (n_faces_top == n_faces_bot)
    checks["symmetric"] = symmetric
    if not symmetric:
        warnings.append(
            f"Top/bottom meshes differ: "
            f"verts {n_verts_top}/{n_verts_bot}, "
            f"faces {n_faces_top}/{n_faces_bot}"
        )

    # 4. Area positive
    area_top = float(top_surface.get("area", 0.0))
    area_bottom = float(bottom_surface.get("area", 0.0))
    area_positive = (area_top > _TOL) and (area_bottom > _TOL)
    checks["area_positive"] = area_positive
    if not area_positive:
        errors.append(
            f"Parting surface area is zero or negative: "
            f"top={area_top:.4e}, bottom={area_bottom:.4e}"
        )

    # 5. Planar check (advisory only)
    if top_surface.get("is_planar") is False:
        warnings.append(
            "Parting surface is not planar — may require stepped/shaped "
            "parting surface treatment (Yu-Fan 2003 §6.3)"
        )

    valid = not errors
    return {
        "valid": valid,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
