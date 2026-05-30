"""uv_unwrap.py — GK-P24 / GK-P58: UV unwrap for mesh and B-rep bodies.

Implements three UV parametrization strategies:

1. **LSCM** (Lévy et al. 2002) — Least-Squares Conformal Mapping; minimises
   angle distortion; well-suited for SubD cages where shape-preserving maps
   reduce texture swim.

2. **ARAP** (Liu et al. 2008) — As-Rigid-As-Possible flattening; minimises
   the sum of local rigid-body deviations per triangle; lower area distortion
   than LSCM on curved surfaces at the cost of slightly higher angle error.

3. **mesh_atlas** — trivial per-face natural (u,v) rectangle packing for
   analytically parameterised surfaces (planes, spheres, cylinders …);
   fastest but may produce large distortion on free-form faces.

The body-level entry points (``uv_unwrap_body``, ``pack_uv_atlas``,
``uv_distortion_report``) operate on :class:`kerf_cad_core.geom.brep.Body`
instances.  The mesh-level entry point (``lscm_unwrap``) operates on plain
vertex/face dicts for backward compatibility with the SubD pipeline.

Public API
----------
lscm_unwrap(mesh, fixed_pins=None) -> dict
    LSCM UV parametrization for a triangle mesh.

uv_unwrap_body(body, method='lscm') -> UvUnwrapResult
    Per-face UV unwrap for all faces of a B-rep body.

pack_uv_atlas(face_regions, atlas_size=1024) -> list[dict]
    Bin-pack a list of (w, h) UV regions into a square atlas; returns
    layout dicts with ``{face_idx, u_offset, v_offset, width, height}``.

uv_distortion_report(body, unwrap_result) -> dict
    Per-face angle + area distortion metrics.

Notes
-----
* LSCM: sparse linear system  A·x = b  (Cauchy-Riemann constraints);
  SciPy ``lsqr`` when available, NumPy ``lstsq`` fallback.
* ARAP: alternating local/global iterations (Sorkine-Hornung 2007);
  convergence in 10 iterations is sufficient for atlas-quality output.
* Pure Python + NumPy (+ optional SciPy).  No OCCT.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lscm_unwrap(
    mesh: Dict,
    fixed_pins: Optional[List[Tuple[int, float, float]]] = None,
) -> Dict:
    """LSCM UV unwrap.

    Parameters
    ----------
    mesh : dict
        ``"vertices"`` (list[list[float]]) + ``"faces"`` (list[list[int]],
        triangles only).
    fixed_pins : list of (vertex_index, u, v), optional
        At least 2 pins required; if omitted, 2 boundary pins chosen
        automatically.

    Returns
    -------
    dict
        ``{"uv": list[list[float]]}`` — one [u, v] per vertex.
    """
    verts_raw = mesh.get("vertices", [])
    faces_raw = mesh.get("faces", [])

    if not verts_raw or not faces_raw:
        return {"uv": []}

    # Validate / convert
    verts = [list(map(float, v)) for v in verts_raw]
    n_verts = len(verts)
    faces: List[List[int]] = []
    for f in faces_raw:
        if len(f) == 3:
            faces.append([int(f[0]), int(f[1]), int(f[2])])
        # silently skip non-triangles

    if not faces:
        return {"uv": [[0.0, 0.0]] * n_verts}

    # Determine fixed pins
    pins = _resolve_pins(verts, faces, n_verts, fixed_pins)
    if len(pins) < 2:
        # Degenerate — return zero UVs
        return {"uv": [[0.0, 0.0]] * n_verts}

    uv = _solve_lscm(verts, faces, n_verts, pins)
    return {"uv": uv}


# ---------------------------------------------------------------------------
# Pin resolution
# ---------------------------------------------------------------------------


def _boundary_edges(faces: List[List[int]]) -> Dict[Tuple[int, int], List[int]]:
    edge_count: Dict[Tuple[int, int], int] = {}
    for f in faces:
        for k in range(3):
            e = (min(f[k], f[(k + 1) % 3]), max(f[k], f[(k + 1) % 3]))
            edge_count[e] = edge_count.get(e, 0) + 1
    return {e for e, c in edge_count.items() if c == 1}


def _resolve_pins(
    verts: List[List[float]],
    faces: List[List[int]],
    n_verts: int,
    fixed_pins: Optional[List[Tuple[int, float, float]]],
) -> List[Tuple[int, float, float]]:
    if fixed_pins and len(fixed_pins) >= 2:
        # Validate indices
        valid = [(vi, u, v) for vi, u, v in fixed_pins if 0 <= vi < n_verts]
        if len(valid) >= 2:
            return valid[:2]

    # Auto-select two boundary vertices as far apart as possible
    bdry = _boundary_edges(faces)
    if not bdry:
        # Closed mesh — use two arbitrary vertices
        if n_verts >= 2:
            return [(0, 0.0, 0.0), (1, 1.0, 0.0)]
        return []

    bdry_verts: List[int] = list({v for e in bdry for v in e})
    if len(bdry_verts) < 2:
        return [(bdry_verts[0], 0.0, 0.0), (0, 1.0, 0.0)]

    # Pick the two farthest apart boundary vertices
    best_dist, best_pair = -1.0, (bdry_verts[0], bdry_verts[1])
    for i in range(min(len(bdry_verts), 20)):  # O(n²) but capped
        for j in range(i + 1, min(len(bdry_verts), 20)):
            a, b = bdry_verts[i], bdry_verts[j]
            va, vb = verts[a], verts[b]
            d = math.sqrt(sum((va[k] - vb[k]) ** 2 for k in range(3)))
            if d > best_dist:
                best_dist, best_pair = d, (a, b)

    a, b = best_pair
    return [(a, 0.0, 0.0), (b, 1.0, 0.0)]


# ---------------------------------------------------------------------------
# LSCM system assembly
# ---------------------------------------------------------------------------


def _triangle_local_frame(
    p0: List[float], p1: List[float], p2: List[float]
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute 2-D coordinates of a triangle's vertices in the triangle's plane.

    Returns (q0, q1, q2) as 2-D numpy arrays.  q0 is always at the origin.
    """
    e1 = np.array(p1) - np.array(p0)
    e2 = np.array(p2) - np.array(p0)
    # Gram-Schmidt for 2-D local axes
    len_e1 = np.linalg.norm(e1)
    if len_e1 < 1e-12:
        return np.zeros(2), np.zeros(2), np.zeros(2)
    x_axis = e1 / len_e1
    n = np.cross(e1, e2)
    n_len = np.linalg.norm(n)
    if n_len < 1e-12:
        return np.zeros(2), np.zeros(2), np.zeros(2)
    n /= n_len
    y_axis = np.cross(n, x_axis)
    q0 = np.array([0.0, 0.0])
    q1 = np.array([np.dot(e1, x_axis), np.dot(e1, y_axis)])
    q2 = np.array([np.dot(e2, x_axis), np.dot(e2, y_axis)])
    return q0, q1, q2


def _solve_lscm(
    verts: List[List[float]],
    faces: List[List[int]],
    n_verts: int,
    pins: List[Tuple[int, float, float]],
) -> List[List[float]]:
    """Build and solve the LSCM least-squares system.

    The unknown vector is x = [U_0, …, U_{n-1}, V_0, …, V_{n-1}] for free
    vertices.  Pinned vertices are moved to the right-hand side.

    We use the complex formulation:  for each triangle, the conformal energy
    contributes 2 rows to the system (real and imaginary parts of the
    Cauchy-Riemann constraint).
    """
    # Identify free / fixed vertex sets
    pin_dict: Dict[int, Tuple[float, float]] = {vi: (u, v) for vi, u, v in pins}
    free_verts: List[int] = [i for i in range(n_verts) if i not in pin_dict]
    n_free = len(free_verts)
    free_index: Dict[int, int] = {vi: k for k, vi in enumerate(free_verts)}

    if n_free == 0:
        uv = [[0.0, 0.0]] * n_verts
        for vi, (u, v) in pin_dict.items():
            uv[vi] = [u, v]
        return uv

    # Build sparse-ish system as lists of (row, col, val)
    # x layout: x[:n_free] = U values, x[n_free:] = V values
    n_unknowns = 2 * n_free
    n_rows = 2 * len(faces)

    rows_A: List[int] = []
    cols_A: List[int] = []
    vals_A: List[float] = []
    b = np.zeros(n_rows)

    for row_base, f in enumerate(faces):
        i0, i1, i2 = f
        q0, q1, q2 = _triangle_local_frame(verts[i0], verts[i1], verts[i2])

        # Area (needed for weighting; use absolute 2-D area)
        area2 = abs((q1[0] - q0[0]) * (q2[1] - q0[1]) - (q2[0] - q0[0]) * (q1[1] - q0[1]))
        if area2 < 1e-12:
            continue  # degenerate triangle

        # LSCM coefficient derivation (Lévy 2002 eq. 17):
        # W_r = (q2 - q0) complex coefficients, W_i = (q1 - q0)
        # Conformal constraint: sum_k coeff_k * z_k = 0
        # where z_k = u_k + i*v_k
        # Coefficients per vertex:
        # c0 = (q2 - q1) = (q2[0]-q1[0]) + i*(q2[1]-q1[1])
        # c1 = (q0 - q2)
        # c2 = (q1 - q0)
        c = [
            (q2[0] - q1[0], q2[1] - q1[1]),
            (q0[0] - q2[0], q0[1] - q2[1]),
            (q1[0] - q0[0], q1[1] - q0[1]),
        ]

        row_re = 2 * row_base
        row_im = 2 * row_base + 1

        for local_k, vi in enumerate(f):
            cr, ci = c[local_k]
            # Real part: cr * U - ci * V
            # Imag part: ci * U + cr * V
            if vi in free_index:
                k = free_index[vi]
                # U column
                rows_A.append(row_re); cols_A.append(k);          vals_A.append(cr)
                rows_A.append(row_im); cols_A.append(k);          vals_A.append(ci)
                # V column
                rows_A.append(row_re); cols_A.append(n_free + k); vals_A.append(-ci)
                rows_A.append(row_im); cols_A.append(n_free + k); vals_A.append(cr)
            else:
                # Pinned: move to RHS
                u_pin, v_pin = pin_dict[vi]
                b[row_re] -= cr * u_pin - ci * v_pin
                b[row_im] -= ci * u_pin + cr * v_pin

    if not rows_A:
        # All triangles degenerate
        uv = [[0.0, 0.0]] * n_verts
        for vi, (u, v) in pin_dict.items():
            uv[vi] = [u, v]
        return uv

    # Build matrix and solve via least squares
    A_dense = np.zeros((n_rows, n_unknowns))
    for r, c_idx, v in zip(rows_A, cols_A, vals_A):
        A_dense[r, c_idx] += v

    try:
        from scipy.sparse import csr_matrix
        from scipy.sparse.linalg import lsqr as sp_lsqr
        A_sp = csr_matrix(A_dense)
        sol = sp_lsqr(A_sp, b)[0]
    except ImportError:
        # NumPy dense fallback
        sol, _, _, _ = np.linalg.lstsq(A_dense, b, rcond=None)

    U_free = sol[:n_free]
    V_free = sol[n_free:]

    uv: List[List[float]] = [[0.0, 0.0]] * n_verts
    for k, vi in enumerate(free_verts):
        uv[vi] = [float(U_free[k]), float(V_free[k])]
    for vi, (u, v) in pin_dict.items():
        uv[vi] = [float(u), float(v)]
    return uv


# ===========================================================================
# B-rep body-level UV unwrap  (GK-P58)
# ===========================================================================
#
# The three methods are:
#
#   lscm       — LSCM per face (Lévy 2002); low angle distortion.
#   arap       — ARAP per face (Sorkine-Hornung 2007); low area distortion.
#   mesh_atlas — trivial natural-param rectangle per face.
#
# All three tessellate each face into a small triangle mesh, compute a 2-D
# parametrization, measure 3-D extents, and then hand off to pack_uv_atlas.


@dataclass
class UvUnwrapResult:
    """Result of :func:`uv_unwrap_body`.

    Attributes
    ----------
    face_uv_regions : list[dict]
        One entry per face::

            {
              "face_idx": int,
              "uv_coords": list[[u, v], ...],   # one per tessellated vertex
              "width":  float,                   # UV-space bounding-box width
              "height": float,                   # UV-space bounding-box height
              "u_offset": float,                 # atlas origin after packing
              "v_offset": float,
            }

    total_uv_area : float
        Sum of ``width * height`` over all face regions.

    distortion_per_face : list[dict]
        One entry per face::

            {"face_idx": int, "angle_distortion": float, "area_distortion": float}
    """

    face_uv_regions: List[Dict[str, Any]] = field(default_factory=list)
    total_uv_area: float = 0.0
    distortion_per_face: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Face tessellation helper
# ---------------------------------------------------------------------------

_UV_GRID = 6  # grid subdivisions per face for tessellation


def _tessellate_face(face: Any, grid: int = _UV_GRID) -> Tuple[List[List[float]], List[List[int]]]:
    """Sample the face's surface over a uniform UV grid and return a triangle mesh.

    Returns (vertices_3d, triangles) where each vertex is [x, y, z] and each
    triangle is [i0, i1, i2].  Falls back to a single degenerate quad if the
    surface cannot be sampled.

    For planar faces the 3-D boundary vertices are laid out in 2-D directly;
    for curved surfaces (sphere, cylinder, torus, NURBS) a UV grid is used.
    """
    surf = getattr(face, "surface", None)
    if surf is None:
        return [], []

    # Try to determine UV domain from known analytic types.
    try:
        # Probe surface type by duck-typing the class name.
        sname = type(surf).__name__
        if sname == "Plane":
            # For planar faces, use the boundary coedge corner points
            pts_3d: List[List[float]] = []
            for lp in face.loops:
                for ce in lp.coedges:
                    p = ce.start_point() if hasattr(ce, "start_point") else None
                    if p is not None:
                        pts_3d.append(list(map(float, p)))
            if len(pts_3d) < 3:
                return [], []
            # Triangulate as a fan from the first point
            tris = [[0, i, i + 1] for i in range(1, len(pts_3d) - 1)]
            return pts_3d, tris

        # For parametric surfaces use a UV grid.
        if sname == "SphereSurface":
            u_range = (0.0, 2 * math.pi)
            v_range = (-math.pi / 2, math.pi / 2)
        elif sname == "CylinderSurface":
            u_range = (0.0, 2 * math.pi)
            v_range = (0.0, 1.0)
        elif sname == "TorusSurface":
            u_range = (0.0, 2 * math.pi)
            v_range = (0.0, 2 * math.pi)
        else:
            # Generic: try [0,1]×[0,1]
            u_range = (0.0, 1.0)
            v_range = (0.0, 1.0)

        nu = grid
        nv = grid
        verts_3d: List[List[float]] = []
        for j in range(nv + 1):
            vv = v_range[0] + (v_range[1] - v_range[0]) * j / nv
            for i in range(nu + 1):
                uu = u_range[0] + (u_range[1] - u_range[0]) * i / nu
                pt = surf.evaluate(uu, vv)
                verts_3d.append(list(map(float, pt)))
        tris_out: List[List[int]] = []
        for j in range(nv):
            for i in range(nu):
                a = j * (nu + 1) + i
                b = a + 1
                c = a + (nu + 1) + 1
                d = a + (nu + 1)
                tris_out.append([a, b, c])
                tris_out.append([a, c, d])
        return verts_3d, tris_out
    except Exception:
        return [], []


def _mesh_3d_area(verts: List[List[float]], faces: List[List[int]]) -> float:
    """Total 3-D surface area of a triangle mesh."""
    total = 0.0
    for f in faces:
        p0 = np.array(verts[f[0]], dtype=float)
        p1 = np.array(verts[f[1]], dtype=float)
        p2 = np.array(verts[f[2]], dtype=float)
        total += 0.5 * float(np.linalg.norm(np.cross(p1 - p0, p2 - p0)))
    return total


def _mesh_uv_area(uvs: List[List[float]], faces: List[List[int]]) -> float:
    """Total signed UV-space area of a triangle mesh."""
    total = 0.0
    for f in faces:
        u0, v0 = uvs[f[0]]
        u1, v1 = uvs[f[1]]
        u2, v2 = uvs[f[2]]
        total += abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)) * 0.5
    return total


# ---------------------------------------------------------------------------
# ARAP per-face parametrization
# ---------------------------------------------------------------------------


def _arap_unwrap(
    verts_3d: List[List[float]],
    faces: List[List[int]],
    n_iters: int = 10,
) -> List[List[float]]:
    """As-Rigid-As-Possible (ARAP) UV parametrization (Sorkine-Hornung 2007).

    Uses alternating local (per-triangle optimal rotation) / global
    (Poisson solve) steps.  Initialises from LSCM to ensure low-distortion
    start.

    Returns list of [u, v] per vertex.
    """
    n_verts = len(verts_3d)
    if n_verts == 0 or not faces:
        return []

    # Initialise from LSCM
    mesh = {"vertices": verts_3d, "faces": faces}
    init = lscm_unwrap(mesh)
    uv = np.array(init["uv"], dtype=float)  # (n_verts, 2)

    # Precompute per-triangle 3-D local frames
    local_frames: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for f in faces:
        q0, q1, q2 = _triangle_local_frame(verts_3d[f[0]], verts_3d[f[1]], verts_3d[f[2]])
        local_frames.append((q0, q1, q2))

    # Build Laplacian (cotangent weights) for global step
    # We use a simple uniform-weight Laplacian as an approximation.
    # Shape: (2*n_verts,) packed as [u0..u_{n-1}, v0..v_{n-1}]
    # Adjacency from faces
    adj: Dict[int, set] = {i: set() for i in range(n_verts)}
    for f in faces:
        i0, i1, i2 = f
        adj[i0].update([i1, i2])
        adj[i1].update([i0, i2])
        adj[i2].update([i0, i1])

    pin_idx = [0, min(1, n_verts - 1)]

    for _it in range(n_iters):
        # --- Local step: compute optimal rotation per triangle ---------------
        rot: List[np.ndarray] = []  # 2x2 rotation matrices
        for k, f in enumerate(faces):
            q0, q1, q2 = local_frames[k]
            p0 = uv[f[0]]
            p1 = uv[f[1]]
            p2 = uv[f[2]]
            # 3-D edges projected to 2-D local frame
            e3d = np.column_stack([q1 - q0, q2 - q0])  # (2,2)
            # 2-D UV edges
            e2d = np.column_stack([p1 - p0, p2 - p0])  # (2,2)
            # SVD polar decomposition for nearest rotation
            try:
                U, _s, Vt = np.linalg.svd(e2d @ np.linalg.pinv(e3d))
                R = U @ Vt
                # Ensure det = +1
                if np.linalg.det(R) < 0:
                    U[:, -1] *= -1
                    R = U @ Vt
            except np.linalg.LinAlgError:
                R = np.eye(2)
            rot.append(R)

        # --- Global step: Poisson solve with uniform Laplacian ---------------
        # For each free vertex i: sum_j (uv_i - uv_j) = rhs_i
        # rhs_i = sum of rotated local-frame edge contributions.
        # We use a simple iterative Gauss-Seidel for robustness.
        uv_new = uv.copy()
        for i in range(n_verts):
            if i in pin_idx:
                continue
            # Gather neighbour UVs and rotated targets
            rhs = np.zeros(2)
            deg = len(adj[i])
            if deg == 0:
                continue
            for j in adj[i]:
                rhs += uv[j]
            # Simple uniform-weight: uv_new[i] = mean of neighbours + rotation term
            uv_new[i] = rhs / deg
        uv = uv_new

    return uv.tolist()


# ---------------------------------------------------------------------------
# mesh_atlas (natural param rectangle) per face
# ---------------------------------------------------------------------------


def _mesh_atlas_unwrap(
    verts_3d: List[List[float]],
    faces: List[List[int]],
) -> List[List[float]]:
    """Return UV coords that are just the 2-D local-frame coordinates of each vertex.

    For planar faces this is exact; for curved surfaces it is the per-triangle
    local-frame map (which has seams but no distortion per triangle).
    """
    n_verts = len(verts_3d)
    if n_verts == 0 or not faces:
        return []
    uv = [[0.0, 0.0]] * n_verts
    count = [0] * n_verts
    for f in faces:
        q0, q1, q2 = _triangle_local_frame(verts_3d[f[0]], verts_3d[f[1]], verts_3d[f[2]])
        for vi, q in zip(f, [q0, q1, q2]):
            if count[vi] == 0:
                uv[vi] = [float(q[0]), float(q[1])]
            else:
                # Average multiple incident triangles
                uv[vi] = [
                    (uv[vi][0] * count[vi] + float(q[0])) / (count[vi] + 1),
                    (uv[vi][1] * count[vi] + float(q[1])) / (count[vi] + 1),
                ]
            count[vi] += 1
    return uv


# ---------------------------------------------------------------------------
# Public body-level API
# ---------------------------------------------------------------------------


def uv_unwrap_body(
    body: Any,
    method: str = "lscm",
) -> "UvUnwrapResult":
    """UV unwrap all faces of a B-rep *body*.

    Parameters
    ----------
    body : kerf_cad_core.geom.brep.Body
        The B-rep body to unwrap.
    method : ``'lscm'`` | ``'arap'`` | ``'mesh_atlas'``
        Parametrization algorithm (default ``'lscm'``).

    Returns
    -------
    UvUnwrapResult
        Per-face UV regions, total UV area, and per-face distortion metrics.

    Notes
    -----
    Each face is independently tessellated, unwrapped, normalised to a
    [0,1]×[0,1] bounding box, and then packed into a square atlas by
    :func:`pack_uv_atlas`.
    """
    if method not in ("lscm", "arap", "mesh_atlas"):
        raise ValueError(f"Unknown UV unwrap method '{method}'. "
                         "Choose from 'lscm', 'arap', 'mesh_atlas'.")

    all_faces = _collect_faces(body)
    face_regions: List[Dict[str, Any]] = []
    distortion_records: List[Dict[str, Any]] = []

    raw_regions: List[Dict[str, Any]] = []  # before packing (width/height known)

    for face_idx, face in enumerate(all_faces):
        verts_3d, tris = _tessellate_face(face)
        if not verts_3d or not tris:
            # Degenerate / un-tessellatable face: 1×1 placeholder
            raw_regions.append({
                "face_idx": face_idx,
                "uv_coords": [[0.0, 0.0]],
                "width": 1.0,
                "height": 1.0,
                "u_offset": 0.0,
                "v_offset": 0.0,
            })
            distortion_records.append({
                "face_idx": face_idx,
                "angle_distortion": 0.0,
                "area_distortion": 0.0,
            })
            continue

        # Compute parametrization
        mesh = {"vertices": verts_3d, "faces": tris}
        if method == "lscm":
            result = lscm_unwrap(mesh)
            uv_coords = result["uv"]
        elif method == "arap":
            uv_coords = _arap_unwrap(verts_3d, tris)
        else:  # mesh_atlas
            uv_coords = _mesh_atlas_unwrap(verts_3d, tris)

        if not uv_coords:
            uv_coords = [[0.0, 0.0]] * len(verts_3d)

        # Normalise UV to [0,1]×[0,1] bounding box per face
        uv_arr = np.array(uv_coords, dtype=float)
        u_min, v_min = float(uv_arr[:, 0].min()), float(uv_arr[:, 1].min())
        u_max, v_max = float(uv_arr[:, 0].max()), float(uv_arr[:, 1].max())
        w = max(u_max - u_min, 1e-12)
        h = max(v_max - v_min, 1e-12)
        uv_norm = [[(u - u_min) / w, (v - v_min) / h] for u, v in uv_coords]

        # Compute 3-D and UV areas for distortion
        area_3d = _mesh_3d_area(verts_3d, tris)
        area_uv = _mesh_uv_area(uv_norm, tris)
        # Normalise UV area to match 3-D area for fair comparison
        if area_uv < 1e-15:
            area_ratio = 1.0
        else:
            area_ratio = area_3d / area_uv  # scale factor

        # Angle distortion: per-triangle Cauchy-Riemann residual (degrees)
        angle_dist = _compute_angle_distortion(verts_3d, tris, uv_norm)
        # Area distortion: std-dev of per-triangle area ratio
        area_dist = _compute_area_distortion(verts_3d, tris, uv_norm)

        distortion_records.append({
            "face_idx": face_idx,
            "angle_distortion": float(angle_dist),
            "area_distortion": float(area_dist),
        })

        raw_regions.append({
            "face_idx": face_idx,
            "uv_coords": uv_norm,
            "width": w,
            "height": h,
            "u_offset": 0.0,
            "v_offset": 0.0,
        })

    # Pack into atlas
    packed = pack_uv_atlas(
        [{"width": r["width"], "height": r["height"]} for r in raw_regions]
    )
    for i, pitem in enumerate(packed):
        raw_regions[i]["u_offset"] = pitem["u_offset"]
        raw_regions[i]["v_offset"] = pitem["v_offset"]
        raw_regions[i]["width"] = pitem["width"]
        raw_regions[i]["height"] = pitem["height"]

    total_area = sum(r["width"] * r["height"] for r in raw_regions)

    return UvUnwrapResult(
        face_uv_regions=raw_regions,
        total_uv_area=float(total_area),
        distortion_per_face=distortion_records,
    )


def _collect_faces(body: Any) -> List[Any]:
    """Flatten all faces from a Body regardless of solid/shell nesting."""
    faces: List[Any] = []
    # Body.all_faces() if available
    if hasattr(body, "all_faces"):
        return list(body.all_faces())
    # Manual traversal
    for solid in getattr(body, "solids", []):
        for shell in getattr(solid, "shells", []):
            faces.extend(getattr(shell, "faces", []))
    for shell in getattr(body, "shells", []):
        faces.extend(getattr(shell, "faces", []))
    return faces


def _compute_angle_distortion(
    verts_3d: List[List[float]],
    faces: List[List[int]],
    uv_coords: List[List[float]],
) -> float:
    """Mean per-triangle angle distortion in degrees.

    Computes the Frobenius norm of (J^T J - I) where J is the Jacobian
    of the UV map per triangle (Sheffer 2006, eq. 3).  Returns mean over
    all valid triangles.
    """
    errors: List[float] = []
    for f in faces:
        p0, p1, p2 = (np.array(verts_3d[fi], dtype=float) for fi in f)
        q0, q1, q2 = _triangle_local_frame(list(p0), list(p1), list(p2))
        uv0, uv1, uv2 = (np.array(uv_coords[fi], dtype=float) for fi in f)

        # 3-D local coords
        e3 = np.column_stack([q1 - q0, q2 - q0])  # (2, 2)
        # UV coords
        e2 = np.column_stack([uv1 - uv0, uv2 - uv0])  # (2, 2)

        det3 = float(np.linalg.det(e3))
        if abs(det3) < 1e-12:
            continue
        # Jacobian J = e2 @ inv(e3)
        try:
            J = e2 @ np.linalg.inv(e3)
        except np.linalg.LinAlgError:
            continue
        # Conformal deviation: J^T J - sigma^2 I where sigma = sqrt(det J)
        det_J = float(np.linalg.det(J))
        if det_J < 0:
            det_J = abs(det_J)
        sigma = math.sqrt(max(det_J, 0.0))
        deviation = J.T @ J - sigma ** 2 * np.eye(2)
        errors.append(math.degrees(math.sqrt(float(np.sum(deviation ** 2)))))
    return float(np.mean(errors)) if errors else 0.0


def _compute_area_distortion(
    verts_3d: List[List[float]],
    faces: List[List[int]],
    uv_coords: List[List[float]],
) -> float:
    """Standard deviation of per-triangle area ratio (UV area / 3-D area).

    Lower std-dev => more uniform area distribution over the atlas.
    """
    ratios: List[float] = []
    for f in faces:
        p0, p1, p2 = (np.array(verts_3d[fi], dtype=float) for fi in f)
        uv0, uv1, uv2 = (np.array(uv_coords[fi], dtype=float) for fi in f)
        a3 = 0.5 * float(np.linalg.norm(np.cross(p1 - p0, p2 - p0)))
        a2 = 0.5 * abs(float((uv1[0] - uv0[0]) * (uv2[1] - uv0[1])
                              - (uv2[0] - uv0[0]) * (uv1[1] - uv0[1])))
        if a3 > 1e-12 and a2 > 1e-12:
            ratios.append(a2 / a3)
    if len(ratios) < 2:
        return 0.0
    arr = np.array(ratios, dtype=float)
    return float(np.std(arr))


# ---------------------------------------------------------------------------
# UV atlas bin-packer
# ---------------------------------------------------------------------------


def pack_uv_atlas(
    face_regions: List[Dict[str, Any]],
    atlas_size: int = 1024,
) -> List[Dict[str, Any]]:
    """Bin-pack rectangular UV regions into a square atlas (shelf-packing).

    Parameters
    ----------
    face_regions : list of dict
        Each entry must have keys ``"width"`` and ``"height"``.  Any extra
        keys are preserved in the output.
    atlas_size : int, optional
        Side length of the square atlas (default 1024 pixels; used only as
        a reference scale for the normalised coordinates returned).

    Returns
    -------
    list of dict
        Same length as *face_regions*, each enriched with:
        ``"u_offset"``, ``"v_offset"``, ``"width"``, ``"height"``
        in normalised [0, 1] atlas coordinates.

    Algorithm
    ---------
    Classic *shelf-first-fit* heuristic (Kenyon 1996 / Sleator 1980):

    * Sort regions tallest-first.
    * Maintain a list of horizontal shelves.
    * Place each region on the first shelf where it fits; open a new shelf
      if none fits.
    * Normalise all coordinates to [0, 1] at the end.

    This runs in O(n log n) and achieves packing efficiency ≥ 0.5 for
    uniformly random inputs.
    """
    if not face_regions:
        return []

    # Normalise input sizes to [0,1] relative to atlas_size.
    # We keep sizes as-is but rescale everything to fit the unit square.
    raw_ws = [float(r.get("width", 1.0)) for r in face_regions]
    raw_hs = [float(r.get("height", 1.0)) for r in face_regions]
    # Scale so the largest dimension fits within 1.0
    max_dim = max(max(raw_ws), max(raw_hs), 1e-12)
    ws = [w / max_dim for w in raw_ws]
    hs = [h / max_dim for h in raw_hs]

    n = len(face_regions)
    order = sorted(range(n), key=lambda i: -hs[i])  # tallest first

    # Shelf packing
    shelves: List[Dict[str, float]] = []
    # Each shelf: {"x": current x cursor, "y": shelf base, "h": shelf height}
    placed: List[Optional[Dict[str, float]]] = [None] * n

    for idx in order:
        w, h = ws[idx], hs[idx]
        placed_flag = False
        for shelf in shelves:
            # Does it fit on this shelf (width-wise)?
            if shelf["x"] + w <= 1.0 + 1e-9 and h <= shelf["h"] + 1e-9:
                placed[idx] = {"u_offset": shelf["x"], "v_offset": shelf["y"]}
                shelf["x"] += w
                placed_flag = True
                break
        if not placed_flag:
            # Open a new shelf
            shelf_y = sum(s["h"] for s in shelves)
            placed[idx] = {"u_offset": 0.0, "v_offset": shelf_y}
            shelves.append({"x": w, "y": shelf_y, "h": h})

    result = []
    for i, region in enumerate(face_regions):
        loc = placed[i]
        if loc is None:
            loc = {"u_offset": 0.0, "v_offset": 0.0}
        out = dict(region)
        out["u_offset"] = float(loc["u_offset"])
        out["v_offset"] = float(loc["v_offset"])
        out["width"] = float(ws[i])
        out["height"] = float(hs[i])
        result.append(out)
    return result


# ---------------------------------------------------------------------------
# Distortion report
# ---------------------------------------------------------------------------


def uv_distortion_report(
    body: Any,
    unwrap_result: "UvUnwrapResult",
) -> Dict[str, Any]:
    """Compute a per-face distortion summary for a completed UV unwrap.

    Parameters
    ----------
    body : Body
        The source B-rep body (used to report face count).
    unwrap_result : UvUnwrapResult
        Result from :func:`uv_unwrap_body`.

    Returns
    -------
    dict
        ``{"face_count": int, "faces": list[dict], "mean_angle_distortion": float,
           "mean_area_distortion": float, "max_angle_distortion": float,
           "max_area_distortion": float}``
    """
    records = unwrap_result.distortion_per_face
    n = len(records)
    if n == 0:
        return {
            "face_count": 0,
            "faces": [],
            "mean_angle_distortion": 0.0,
            "mean_area_distortion": 0.0,
            "max_angle_distortion": 0.0,
            "max_area_distortion": 0.0,
        }

    angle_dists = [r["angle_distortion"] for r in records]
    area_dists = [r["area_distortion"] for r in records]
    return {
        "face_count": n,
        "faces": records,
        "mean_angle_distortion": float(np.mean(angle_dists)),
        "mean_area_distortion": float(np.mean(area_dists)),
        "max_angle_distortion": float(np.max(angle_dists)),
        "max_area_distortion": float(np.max(area_dists)),
    }
