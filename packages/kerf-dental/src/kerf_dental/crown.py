"""
kerf_dental.crown — Parametric dental crown design.

Public API
----------
ToothAnatomy
    Dataclass describing a single tooth (crown, root, arch position).

CrownDesignInput
    Design parameters: margin line polygon, opposing tooth profile, material.

design_crown(inp) -> CrownResult
    **Deprecated placeholder** – still honours the original signature and
    returns a validate_body-clean B-rep, but uses a circumscribed-circle
    cylinder.  Kept for backward-compatibility.

design_crown_anatomic(inp, *, n_cusps, cusp_depth_fraction) -> CrownResult
    **Recommended** – sweeps the actual margin-line polygon upward and caps
    it with a contoured occlusal surface (2–4 cusp ridges).  Returns a
    validate_body-clean triangle-mesh B-rep suitable for STL milling.

Algorithm (Option A)
--------------------
1. Project margin-line polygon to its best-fit plane via PCA; preserve the
   exact polygon vertices (no circumscribed-circle approximation).
2. Build three rings in the local frame:
   - MARGIN ring  : the original margin vertices, offset by the centroid (z=0).
   - OCCLUSAL ring: same polygon, scaled in by `occlusal_inset` (default 85 %),
     raised to `h_body = crown_height - cusp_depth`.
   - APEX point   : centroid of occlusal ring, raised by `cusp_depth` to give
     a single apex for the cusp fan (creating a smooth dome with n_cusps bumps
     when n_cusps >= 2; for n_cusps == 1 the apex is centred).
3. Triangulate three zones:
   - Side wall  : each quad (margin[i], margin[i+1], occlusal[i+1], occlusal[i])
     split into 2 triangles → 2·N lateral triangles.
   - Occlusal   : fan from occlusal ring toward apex (one triangle per ring
     segment) → N occlusal triangles.
   - Margin base: fan from margin ring toward margin centroid → N base triangles.
4. Assemble as a planar-triangle-faced B-rep (every triangle is a `Face`
   with a `Plane` surface).  Shared edges are detected by matching their
   ordered-vertex-pair signature and their physical midpoint, then merged to
   a single `Edge` so every closed edge is used by exactly two coedges of
   opposite orientation.  The result is a closed, manifold, validate_body-
   clean `Body`.

The existing `design_crown` signature is unchanged.  The new function adds
`n_cusps` and `cusp_depth_fraction` keyword arguments.

Notes
-----
Crown coordinate frame:
  - Origin = centroid of the margin line (projected to best-fit plane).
  - Z-axis = occlusal (superior) direction (outward from the PCA plane).
  - X / Y axes span the margin plane.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ToothAnatomy:
    """Anatomical description of a single tooth."""

    tooth_id: str
    """FDI notation, e.g. '16' (upper-right first molar)."""

    arch: str
    """'upper' or 'lower'."""

    crown_height_mm: float
    """Anatomical crown height in millimetres (typical 7–10 mm)."""

    root_length_mm: float
    """Root length in millimetres (typical 12–17 mm)."""

    mesio_distal_width_mm: float
    """Mesio-distal (x-axis) crown width in millimetres."""

    bucco_lingual_width_mm: float
    """Bucco-lingual (y-axis) crown width in millimetres."""

    cusp_heights_mm: list[float] = field(default_factory=lambda: [1.5])
    """Cusp heights above the margin line (mm).  One per cusp."""


@dataclass
class CrownDesignInput:
    """Inputs required to design a parametric crown."""

    margin_line: Sequence[tuple[float, float, float]]
    """3-D polygon (closed implied) defining the tooth preparation margin.
    Points are in mm, expressed in a common jaw coordinate frame."""

    opposing_cusp_heights_mm: Sequence[float]
    """Heights (mm) of functional cusps on the opposing tooth.
    Used to derive occlusal clearance and morphology. At least one value."""

    material: str = "zirconia"
    """Restorative material — informational only (zirconia, PMMA, e.max, etc.)."""

    occlusal_clearance_mm: float = 0.3
    """Minimum clearance between crown occlusal surface and opposing cusps (mm)."""

    def __post_init__(self):
        pts = list(self.margin_line)
        if len(pts) < 3:
            raise ValueError(
                f"margin_line must have at least 3 points, got {len(pts)}"
            )
        heights = list(self.opposing_cusp_heights_mm)
        if not heights:
            raise ValueError("opposing_cusp_heights_mm must not be empty")
        if self.occlusal_clearance_mm < 0:
            raise ValueError("occlusal_clearance_mm must be >= 0")


@dataclass
class CrownResult:
    """Output of design_crown() / design_crown_anatomic()."""

    body: object
    """kerf_cad_core.geom.brep.Body — a closed, validate_body-clean B-rep."""

    margin_centroid_mm: tuple[float, float, float]
    """Centroid of the fitted margin line (mm)."""

    crown_radius_mm: float
    """Fitted circumradius of the crown footprint (mm)."""

    crown_height_mm: float
    """Total crown height (margin plane to occlusal surface) (mm)."""

    tooth_anatomy: "ToothAnatomy | None" = None
    """Populated anatomy dataclass when tooth_id is supplied."""


# ---------------------------------------------------------------------------
# Internal triangle-mesh B-rep builder
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-14 else v


def _triangle_mesh_to_body(
    vertices: np.ndarray,       # (V, 3) float
    faces: np.ndarray,          # (F, 3) int  — CCW from outside
    tol: float = 1e-7,
) -> object:
    """Convert a closed triangle mesh into a validate_body-clean B-rep Body.

    Each triangle becomes a planar Face with a Plane surface.  Shared edges
    are discovered by their ordered-pair signature (or reversed) and merged
    into a single Edge with two opposite-orientation Coedges (one per
    adjacent face).

    The mesh MUST be:
    - Closed (every edge shared by exactly two triangles, opposite orientations).
    - Manifold (no T-junctions).
    - Triangles oriented CCW when viewed from outside.
    """
    from kerf_cad_core.geom.brep import (
        Body, Coedge, Edge, Face, Line3, Loop, Plane, Shell, Solid, Vertex,
        validate_body,
    )

    verts = np.asarray(vertices, dtype=float)
    tris = np.asarray(faces, dtype=int)

    # Build shared Vertex objects (one per mesh vertex)
    V = [Vertex(verts[i], tol) for i in range(len(verts))]

    # Bump vertex tol so it is >= edge tol (tolerance monotonicity)
    etol = max(tol, 1e-7)
    for v in V:
        if v.tol < etol:
            v.tol = etol

    # Build edges: keyed by (min_idx, max_idx) -> Edge
    # We track canonical direction too.
    edge_map: Dict[Tuple[int, int], Edge] = {}

    def _get_or_make_edge(a: int, b: int) -> Edge:
        key = (min(a, b), max(a, b))
        if key not in edge_map:
            e = Edge(
                Line3(verts[a], verts[b]),
                0.0, 1.0,
                V[a], V[b],
                etol,
            )
            edge_map[key] = e
        return edge_map[key]

    # Build one Face per triangle
    brep_faces: List[Face] = []
    for tri in tris:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        p0, p1, p2 = verts[i0], verts[i1], verts[i2]

        # Plane surface: outward normal = cross(p1-p0, p2-p0)
        n = _unit(np.cross(p1 - p0, p2 - p0))
        plane = Plane(origin=p0, x_axis=p1 - p0, y_axis=p2 - p0)

        # Three edges, oriented to match i0->i1->i2->i0 (CCW from outside)
        # Coedge orientation = True if edge stored as (a->b) and we walk a->b
        pairs = [(i0, i1), (i1, i2), (i2, i0)]
        coedges = []
        for (a, b) in pairs:
            e = _get_or_make_edge(a, b)
            # Edge is stored with v_start = min(a,b), v_end = max(a,b) ... but
            # we stored it as V[a] -> V[b] above — canonical = (a, b) as given
            # to _get_or_make_edge.  The key is (min,max) so we need to check.
            key = (min(a, b), max(a, b))
            actual_edge = edge_map[key]
            # The edge was created with v_start=V[a_orig], v_end=V[b_orig]
            # where a_orig, b_orig are the first a,b that created it.
            # orientation=True if we walk v_start->v_end (same direction as creation)
            orient = (actual_edge.v_start is V[a])
            coedges.append(Coedge(actual_edge, orient))

        loop = Loop(coedges, is_outer=True)
        face = Face(plane, [loop], orientation=True, tol=tol)
        brep_faces.append(face)

    shell = Shell(brep_faces, is_closed=True)
    body = Body(solids=[Solid([shell])])

    vr = validate_body(body)
    if not vr["ok"]:
        raise RuntimeError(
            f"_triangle_mesh_to_body produced invalid body: {vr['errors']}"
        )
    return body


# ---------------------------------------------------------------------------
# Anatomic crown mesh builder
# ---------------------------------------------------------------------------

def _build_anatomic_crown_mesh(
    margin_pts_3d: np.ndarray,   # (N, 3) original margin in world space
    crown_height: float,
    n_cusps: int,
    cusp_depth_fraction: float,
    occlusal_inset: float = 0.85,
) -> Tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """Build triangle mesh for anatomic crown (Option A).

    Strategy
    --------
    Four-vertex-ring topology (always topologically a sphere genus-0):

      - MARGIN ring     : N vertices at z=0 in local frame (actual margin polygon).
      - OCCLUSAL ring   : N vertices at z=h_body, scaled inward by occlusal_inset.
                          Each occlusal vertex is given a cusp-shaped vertical
                          displacement: vertices angularly close to a cusp axis
                          get lifted by cusp_depth; vertices between cusps stay
                          near h_body. This embeds cusp morphology in the ring
                          without any topology seam.
      - APEX            : 1 vertex at the occlusal centroid height
                          (average of displaced occlusal ring heights).
      - BASE centroid   : 1 vertex at z=0 (margin centroid for base cap).

    Triangle zones:
      - Side walls : N quads (margin[i], margin[i+1], occ[i+1], occ[i]) → 2N tris.
      - Occlusal   : N tris fanning from occlusal ring → apex.
      - Base cap   : N tris fanning from margin ring → base centroid.
    Total faces = 4·N, total vertices = 2·N + 2.

    The cusp profile uses a raised-cosine shape:
      z_occ[i] = h_body + cusp_depth · max_k( (1 + cos(angle_to_cusp_k)) / 2 )

    This gives smooth cusp ridges with no topology seam.

    Returns
    -------
    vertices : (V, 3) float  — in world space
    faces    : (F, 3) int    — raw winding (corrected by caller)
    crown_radius : float
    centroid : (3,) float
    """
    pts = margin_pts_3d
    N = len(pts)

    # 1. Centroid and PCA normal
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[2]
    if np.linalg.norm(normal) < 1e-12:
        raise ValueError("Margin line points are degenerate (zero spread)")
    normal = normal / np.linalg.norm(normal)
    if normal[2] < 0:
        normal = -normal

    # Build local frame: x, y in margin plane
    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(ref, normal)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    x_ax = _unit(np.cross(normal, ref))
    y_ax = _unit(np.cross(normal, x_ax))

    # 2. Project margin to local 2-D
    margin_2d = np.column_stack([
        centered.dot(x_ax),
        centered.dot(y_ax),
    ])
    crown_radius = float(np.linalg.norm(margin_2d, axis=1).max())

    # 3. Cusp geometry
    cusp_depth = crown_height * cusp_depth_fraction   # height of cusp bumps
    h_body = crown_height - cusp_depth                # base of occlusal zone

    # Cusp axes equally spaced in angle
    cusp_angles = [2.0 * math.pi * k / n_cusps for k in range(n_cusps)]

    def _cusp_lift(angle: float) -> float:
        """Raised-cosine cusp lift for a ring vertex at the given angle.

        Returns a value in [0, cusp_depth]: maximum at cusp axes, zero midway.
        """
        best = 0.0
        for ca in cusp_angles:
            delta = angle - ca
            # wrap to [-pi, pi]
            delta = math.atan2(math.sin(delta), math.cos(delta))
            # raised cosine: (1 + cos(n_cusps * delta)) / 2, clamped to cusp sector
            # Use half-wave: max when delta=0, zero when |delta| >= pi/n_cusps
            half_width = math.pi / n_cusps
            if abs(delta) < half_width:
                v = (1.0 + math.cos(math.pi * delta / half_width)) / 2.0
                if v > best:
                    best = v
        return best * cusp_depth

    # 4. Build vertex arrays (world space)
    def _local_to_world(xy2d: np.ndarray, z_local: float) -> np.ndarray:
        return centroid + xy2d[0] * x_ax + xy2d[1] * y_ax + z_local * normal

    # Margin ring (z = 0 local)
    margin_verts = np.array([
        _local_to_world(margin_2d[i], 0.0) for i in range(N)
    ])

    # Occlusal ring: inset + cusp-lifted z
    occ_pts_2d = margin_2d * occlusal_inset
    occ_angles = [math.atan2(float(occ_pts_2d[i, 1]), float(occ_pts_2d[i, 0]))
                  for i in range(N)]
    occ_z = [h_body + _cusp_lift(a) for a in occ_angles]
    occlusal_verts = np.array([
        _local_to_world(occ_pts_2d[i], occ_z[i]) for i in range(N)
    ])

    # Apex: occlusal centroid lifted a bit more (average cusp lift * 0.5 extra)
    # Use the average occlusal ring position + a small extra lift for the "dome"
    avg_occ_z = float(np.mean(occ_z))
    apex_2d = np.zeros(2)  # centroid in occlusal plane
    apex_z = avg_occ_z + cusp_depth * 0.3  # slight extra central elevation
    apex_pt = _local_to_world(apex_2d, apex_z)

    # Base centroid (1 vertex at z = 0, world centroid)
    base_pt = centroid

    # Vertex index layout:
    #   0..N-1   : margin ring
    #   N..2N-1  : occlusal ring
    #   2N       : apex
    #   2N+1     : base center
    all_verts = np.vstack([
        margin_verts,        # [0..N-1]
        occlusal_verts,      # [N..2N-1]
        apex_pt[None, :],    # [2N]
        base_pt[None, :],    # [2N+1]
    ])

    IDX_APEX = 2 * N
    IDX_BASE = 2 * N + 1

    def idx_m(i: int) -> int: return i % N
    def idx_o(i: int) -> int: return N + (i % N)

    tri_list: List[Tuple[int, int, int]] = []

    # 5a. Side wall: quad (mi, mi1, oi1, oi) → 2 triangles
    # Outward-facing: split along mi--oi1 diagonal
    for i in range(N):
        mi  = idx_m(i)
        mi1 = idx_m(i + 1)
        oi  = idx_o(i)
        oi1 = idx_o(i + 1)
        tri_list.append((mi, mi1, oi1))
        tri_list.append((mi, oi1, oi))

    # 5b. Occlusal: fan from ring → apex
    # From above (outward = +normal): CCW = apex, oi, oi1
    for i in range(N):
        oi  = idx_o(i)
        oi1 = idx_o(i + 1)
        tri_list.append((IDX_APEX, oi, oi1))

    # 5c. Base cap: fan from margin ring → base centroid
    # From below (outward = -normal): CCW from below = base, mi1, mi
    for i in range(N):
        mi  = idx_m(i)
        mi1 = idx_m(i + 1)
        tri_list.append((IDX_BASE, mi1, mi))

    faces_arr = np.array(tri_list, dtype=int)
    return all_verts, faces_arr, crown_radius, centroid


def _ensure_outward_normals(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> np.ndarray:
    """Flip any triangle whose normal points inward (toward mesh centroid).

    Returns a new faces array with corrected winding.
    """
    mesh_centroid = vertices.mean(axis=0)
    corrected = []
    for tri in faces:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        p0, p1, p2 = vertices[i0], vertices[i1], vertices[i2]
        n = np.cross(p1 - p0, p2 - p0)
        face_c = (p0 + p1 + p2) / 3.0
        if np.dot(n, face_c - mesh_centroid) < 0:
            corrected.append((i0, i2, i1))  # flip winding
        else:
            corrected.append((i0, i1, i2))
    return np.array(corrected, dtype=int)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def design_crown_anatomic(
    inp: CrownDesignInput,
    *,
    n_cusps: int = 2,
    cusp_depth_fraction: float = 0.20,
    occlusal_inset: float = 0.85,
) -> CrownResult:
    """
    Build an anatomic parametric crown from a margin line + opposing tooth profile.

    Implements Option A: sweep the actual margin-line polygon (not a
    circumscribed circle) upward to an inset occlusal ring, then cap with a
    cusp-ridged occlusal surface.  The result is a triangle-mesh B-rep
    suitable for STL milling.

    Parameters
    ----------
    inp : CrownDesignInput
    n_cusps : int
        Number of occlusal cusps (2 for premolars, 4 for molars). Default 2.
    cusp_depth_fraction : float
        Fraction of crown height occupied by the cusp bumps above the
        occlusal ring (0.10–0.30 is typical). Default 0.20.
    occlusal_inset : float
        Scale factor applied to the margin polygon to derive the occlusal
        ring (0 < inset < 1). Default 0.85.

    Returns
    -------
    CrownResult
        body: closed, validate_body-clean triangle-mesh B-rep.
        crown_radius_mm: circumradius of the margin footprint.
        crown_height_mm: total height (margin to highest cusp apex).
        margin_centroid_mm: centroid of margin line.

    Raises
    ------
    ValueError if the margin line is degenerate.
    RuntimeError if the assembled mesh fails validation.
    """
    pts = np.array(inp.margin_line, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(
            f"margin_line must be an (N, 3) array-like, got shape {pts.shape}"
        )

    n_cusps = max(1, int(n_cusps))
    cusp_depth_fraction = float(np.clip(cusp_depth_fraction, 0.05, 0.50))
    occlusal_inset = float(np.clip(occlusal_inset, 0.50, 0.99))

    crown_height = float(max(inp.opposing_cusp_heights_mm)) + inp.occlusal_clearance_mm
    if crown_height < 0.1:
        crown_height = 0.1

    verts, faces, crown_radius, centroid = _build_anatomic_crown_mesh(
        pts,
        crown_height=crown_height,
        n_cusps=n_cusps,
        cusp_depth_fraction=cusp_depth_fraction,
        occlusal_inset=occlusal_inset,
    )

    # Ensure all triangle normals point outward before assembling B-rep
    faces = _ensure_outward_normals(verts, faces)

    body = _triangle_mesh_to_body(verts, faces)

    return CrownResult(
        body=body,
        margin_centroid_mm=(float(centroid[0]), float(centroid[1]), float(centroid[2])),
        crown_radius_mm=crown_radius,
        crown_height_mm=crown_height,
    )


def design_crown(inp: CrownDesignInput) -> CrownResult:
    """
    Build a parametric crown B-rep from a margin line + opposing tooth profile.

    .. deprecated::
        Use :func:`design_crown_anatomic` for a proper anatomic crown that
        honours the margin-line polygon.  This function remains for backward
        compatibility and uses a circumscribed-circle cylinder approximation.

    The algorithm:
    1. Fit the margin-line polygon:
       - Project to best-fit plane via PCA.
       - Compute the circumscribed radius (max distance from centroid).
    2. Determine crown height:
       - Max opposing cusp height + occlusal_clearance_mm.
    3. Build the crown Body:
       - make_cylinder(radius=circumradius, height=crown_height) oriented
         along the local Z axis of the margin plane.
    4. Return CrownResult; the Body is guaranteed validate_body-clean
       because make_cylinder produces a topologically sound manifold solid.

    Parameters
    ----------
    inp : CrownDesignInput

    Returns
    -------
    CrownResult with a closed, validate_body-clean Body.

    Raises
    ------
    ImportError  if kerf_cad_core is not importable.
    ValueError   if the margin line is degenerate (all points collinear).
    """
    from kerf_cad_core.geom.brep import make_cylinder, validate_body

    pts = np.array(inp.margin_line, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(
            f"margin_line must be an (N, 3) array-like, got shape {pts.shape}"
        )

    centroid = pts.mean(axis=0)

    # PCA to find best-fit plane normal (smallest eigenvalue eigenvector)
    centered = pts - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[2]  # smallest-variance direction = plane normal
    if np.linalg.norm(normal) < 1e-12:
        raise ValueError("Margin line points are degenerate (zero spread)")
    normal = normal / np.linalg.norm(normal)

    # Ensure normal points in the "occlusal" (positive z) sense
    if normal[2] < 0:
        normal = -normal

    # Circumscribed radius = max distance from centroid projected to margin plane
    proj = centered - np.outer(centered.dot(normal), normal)
    radii = np.linalg.norm(proj, axis=1)
    crown_radius = float(radii.max())
    if crown_radius < 1e-6:
        raise ValueError("Margin line degenerates to a single point")

    # Crown height: tallest opposing cusp + clearance
    crown_height = float(max(inp.opposing_cusp_heights_mm)) + inp.occlusal_clearance_mm
    if crown_height < 0.1:
        crown_height = 0.1  # minimum 0.1 mm structural thickness

    # Build the crown body as a cylinder along the margin-plane normal
    body = make_cylinder(
        center=tuple(centroid),
        axis=tuple(normal),
        radius=crown_radius,
        height=crown_height,
    )

    # Sanity check — should always pass for make_cylinder output
    vr = validate_body(body)
    if not vr["ok"]:
        raise RuntimeError(
            f"design_crown produced an invalid body: {vr['errors']}"
        )

    return CrownResult(
        body=body,
        margin_centroid_mm=(float(centroid[0]), float(centroid[1]), float(centroid[2])),
        crown_radius_mm=crown_radius,
        crown_height_mm=crown_height,
    )
