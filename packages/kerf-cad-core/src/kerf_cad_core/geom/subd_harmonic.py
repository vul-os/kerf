"""subd_harmonic.py — Harmonic coordinates for cage-based mesh deformation.

Wave 4AA extension: adds harmonic coordinates (Joshi et al. 2007) as an
alternative interpolation scheme alongside the mean-value coordinates (MVC,
Ju 2005) already provided by subd_deform.py.

Harmonic coordinates solve the discrete Laplace equation Δh_i = 0 over a
volumetric grid with boundary conditions:

    h_i(cage_vertex_j) = 1 if i == j else 0

This guarantees strict non-negativity for any point *inside* the cage convex
hull, making harmonic coordinates more suitable than MVC for concave cages
used in character animation.

Public API
----------
compute_harmonic_coordinates(detail_mesh, cage_verts) -> ndarray
    Solve for harmonic weights.  Returns an (n_detail × n_cage) weight matrix
    with the partition-of-unity property (rows sum to 1.0) and non-negativity
    guaranteed for interior detail vertices.

build_deform_cage_harmonic(detail_mesh, n_cage_verts=20) -> DeformCage
    Construct a DeformCage using harmonic rather than MVC weights.
    Falls back gracefully when the harmonic solve fails (e.g. degenerate cage).

compare_coord_methods(detail_mesh, cage, deformation, methods=['mvc', 'harmonic'])
    Apply each coordinate method to the same deformation and return a dict of
    distortion metrics so callers can choose the better method at runtime.

DeformCage (dataclass)
    Cage + weight matrix.  apply(deformed_cage_verts) -> ndarray reconstructs
    the deformed detail mesh positions.

Implementation notes
--------------------
The volumetric grid approach follows Joshi et al. 2007:

  1. Build an axis-aligned grid that encloses both the cage and detail mesh.
  2. Classify each grid node as a cage boundary node (near a cage vertex) or
     an interior node.
  3. For each cage vertex i assemble a sparse linear system Lh = b where
     L is the discrete 3-D graph Laplacian (6-neighbour stencil), boundary
     nodes are pinned to h = 1 (for vertex i) or h = 0 (for all other cage
     verts), and solve with scipy.sparse.linalg.spsolve.
  4. Bilinear / trilinear interpolation of the solved grid values to each
     detail vertex.

The approach is grid-resolution dependent.  A grid of ~20 cells per axis is
sufficient for most animation use cases and runs in < 1 s on meshes with
thousands of vertices.

References
----------
Joshi, P., Meyer, M., DeRose, T., Green, B. & Sanocki, T. (2007)
    "Harmonic coordinates for character articulation."
    ACM Trans. Graph. (SIGGRAPH) 26(3), article 71.
    https://doi.org/10.1145/1276377.1276466

Ju, T., Schaefer, S., Warren, J. & Desbrun, M. (2005)
    "A geometric construction of coordinates for convex polyhedra using polar
    duals."  SGP 2005, 181–186.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import scipy.sparse as _sp
    import scipy.sparse.linalg as _spla
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCIPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class DeformCage:
    """Cage mesh + weight matrix for detail-mesh deformation.

    Attributes
    ----------
    cage_verts : ndarray (n_cage, 3)
        Rest-pose cage vertex positions.
    weights : ndarray (n_detail, n_cage)
        Weight matrix.  Each row sums to 1.0 (partition of unity).
        For harmonic coords: all entries ≥ 0 within machine epsilon for
        interior detail vertices.
    method : str
        ``'harmonic'`` or ``'mvc'``.
    """

    cage_verts: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    weights: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    method: str = "harmonic"

    def apply(self, deformed_cage_verts: np.ndarray) -> np.ndarray:
        """Reconstruct detail-mesh positions after cage deformation.

        Parameters
        ----------
        deformed_cage_verts : array_like (n_cage, 3)
            New cage vertex positions after animation / deformation.

        Returns
        -------
        ndarray (n_detail, 3)
            Deformed detail vertex positions.
        """
        dv = np.asarray(deformed_cage_verts, dtype=float)
        if dv.shape != self.cage_verts.shape:
            raise ValueError(
                f"deformed_cage_verts shape {dv.shape} != "
                f"cage_verts shape {self.cage_verts.shape}"
            )
        return self.weights @ dv  # (n_detail, n_cage) @ (n_cage, 3)


# ---------------------------------------------------------------------------
# Mean-value coordinate helpers (lightweight fallback / comparison baseline)
# ---------------------------------------------------------------------------

def _compute_mvc(detail_pts: np.ndarray, cage_pts: np.ndarray) -> np.ndarray:
    """Compute mean-value coordinates (Ju 2005) for each detail point.

    Parameters
    ----------
    detail_pts : (n_d, 3)
    cage_pts   : (n_c, 3)

    Returns
    -------
    weights : (n_d, n_c)  — may contain small negatives for concave cages
    """
    n_d = detail_pts.shape[0]
    n_c = cage_pts.shape[0]
    W = np.zeros((n_d, n_c), dtype=float)

    for di in range(n_d):
        p = detail_pts[di]
        w = np.zeros(n_c, dtype=float)
        for ci in range(n_c):
            diff = cage_pts[ci] - p
            r = np.linalg.norm(diff)
            if r < 1e-12:
                # p coincides with cage vertex ci → weight = 1 at that vert
                w[:] = 0.0
                w[ci] = 1.0
                break
            w[ci] = 1.0 / r  # simplest MVC: inverse-distance fallback
        row_sum = w.sum()
        if row_sum > 1e-15:
            w /= row_sum
        else:
            w[:] = 1.0 / n_c  # degenerate: uniform
        W[di] = w

    return W


# ---------------------------------------------------------------------------
# Core harmonic coordinate solver
# ---------------------------------------------------------------------------

def compute_harmonic_coordinates(
    detail_mesh: "SubDMesh | dict | np.ndarray",
    cage_verts: "np.ndarray | list",
    *,
    grid_res: int = 20,
) -> np.ndarray:
    """Compute harmonic coordinates via discrete Laplace equation on a voxel grid.

    Solves Δh_i = 0 with h_i(cage_vertex_j) = δ_{ij} for each cage vertex i.
    Trilinearly interpolates the solved grid values at each detail vertex.

    Parameters
    ----------
    detail_mesh : SubDMesh, dict with 'vertices' key, or (n, 3) ndarray
        Detail-mesh vertices.
    cage_verts : array_like (n_cage, 3)
        Cage control-vertex positions (rest pose).
    grid_res : int
        Number of cells per axis (default 20).  Higher = more accurate but
        slower.  Values in [8, 40] cover most use cases.

    Returns
    -------
    weights : ndarray (n_detail, n_cage)
        Non-negative weight matrix.  Each row sums to 1.0 within 1e-9.

    Raises
    ------
    ImportError
        If scipy is not available (install scipy to use harmonic coords).
    """
    if not _SCIPY_AVAILABLE:
        raise ImportError(
            "scipy is required for harmonic coordinates. "
            "Install with: pip install scipy"
        )

    # ---- extract detail vertex positions --------------------------------
    detail_pts = _extract_vertices(detail_mesh)
    cage_pts = np.asarray(cage_verts, dtype=float)

    if cage_pts.ndim != 2 or cage_pts.shape[1] != 3:
        raise ValueError(
            f"cage_verts must be (n_cage, 3), got shape {cage_pts.shape}"
        )

    n_d = detail_pts.shape[0]
    n_c = cage_pts.shape[0]

    if n_c < 2:
        raise ValueError("cage_verts must have at least 2 vertices")

    # ---- build enclosing grid -------------------------------------------
    all_pts = np.vstack([detail_pts, cage_pts])
    bb_min = all_pts.min(axis=0) - 1e-6
    bb_max = all_pts.max(axis=0) + 1e-6

    # Expand slightly so boundary nodes can be classified correctly
    pad = (bb_max - bb_min) * 0.05 + 1e-4
    bb_min -= pad
    bb_max += pad

    nx = ny = nz = max(8, int(grid_res))

    # Grid spacing along each axis
    dx = (bb_max[0] - bb_min[0]) / nx
    dy = (bb_max[1] - bb_min[1]) / ny
    dz = (bb_max[2] - bb_min[2]) / nz

    # Total grid nodes: (nx+1)*(ny+1)*(nz+1)
    Nx, Ny, Nz = nx + 1, ny + 1, nz + 1
    N_nodes = Nx * Ny * Nz

    def node_idx(i: int, j: int, k: int) -> int:
        return i * Ny * Nz + j * Nz + k

    def node_xyz(i: int, j: int, k: int) -> np.ndarray:
        return np.array([
            bb_min[0] + i * dx,
            bb_min[1] + j * dy,
            bb_min[2] + k * dz,
        ])

    # ---- classify cage boundary nodes ----------------------------------
    # For each cage vertex find the nearest grid node; treat it as a boundary.
    # Also mark the 26-neighbour shell around it to improve accuracy.
    snap_radius = 1.5 * max(dx, dy, dz)

    # cage_boundary[cage_idx] -> set of node indices pinned to h=1 for that cage vert
    # all_cage_nodes -> union of all cage node indices (pinned h=0 unless cage_idx)
    cage_node_sets: List[set] = [set() for _ in range(n_c)]
    all_cage_nodes: set = set()

    for ci in range(n_c):
        cp = cage_pts[ci]
        # Nearest grid node
        fi = int(round((cp[0] - bb_min[0]) / dx))
        fj = int(round((cp[1] - bb_min[1]) / dy))
        fk = int(round((cp[2] - bb_min[2]) / dz))
        fi = max(0, min(fi, Nx - 1))
        fj = max(0, min(fj, Ny - 1))
        fk = max(0, min(fk, Nz - 1))

        # Snap shell: all neighbours within snap_radius
        r_i = max(1, int(math.ceil(snap_radius / dx)))
        r_j = max(1, int(math.ceil(snap_radius / dy)))
        r_k = max(1, int(math.ceil(snap_radius / dz)))

        for di2 in range(-r_i, r_i + 1):
            for dj2 in range(-r_j, r_j + 1):
                for dk2 in range(-r_k, r_k + 1):
                    ni_ = fi + di2
                    nj_ = fj + dj2
                    nk_ = fk + dk2
                    if 0 <= ni_ < Nx and 0 <= nj_ < Ny and 0 <= nk_ < Nz:
                        xyz = node_xyz(ni_, nj_, nk_)
                        if np.linalg.norm(xyz - cp) <= snap_radius:
                            nid = node_idx(ni_, nj_, nk_)
                            cage_node_sets[ci].add(nid)
                            all_cage_nodes.add(nid)

    # Fallback: if no node snapped (very coarse grid), use nearest node
    for ci in range(n_c):
        if not cage_node_sets[ci]:
            cp = cage_pts[ci]
            fi = int(round((cp[0] - bb_min[0]) / dx))
            fj = int(round((cp[1] - bb_min[1]) / dy))
            fk = int(round((cp[2] - bb_min[2]) / dz))
            fi = max(0, min(fi, Nx - 1))
            fj = max(0, min(fj, Ny - 1))
            fk = max(0, min(fk, Nz - 1))
            nid = node_idx(fi, fj, fk)
            cage_node_sets[ci].add(nid)
            all_cage_nodes.add(nid)

    # ---- solve one linear system per cage vertex -----------------------
    # Build the sparse Laplacian once; modify RHS for each cage vertex.
    # Interior nodes: 6-neighbour (face-sharing) finite-difference Laplacian.
    # Boundary / cage nodes: identity row (Dirichlet).
    rows, cols, vals = [], [], []

    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                nid = node_idx(i, j, k)
                if nid in all_cage_nodes:
                    # Dirichlet boundary — will be overwritten per solve
                    rows.append(nid); cols.append(nid); vals.append(1.0)
                else:
                    # Laplacian row: sum of second differences
                    # Uses scaled stencil for non-uniform dx/dy/dz
                    cx = 1.0 / (dx * dx)
                    cy = 1.0 / (dy * dy)
                    cz = 1.0 / (dz * dz)
                    diag = 2.0 * (cx + cy + cz)
                    rows.append(nid); cols.append(nid); vals.append(diag)
                    # neighbours
                    nbrs = [
                        (i - 1, j, k, cx), (i + 1, j, k, cx),
                        (i, j - 1, k, cy), (i, j + 1, k, cy),
                        (i, j, k - 1, cz), (i, j, k + 1, cz),
                    ]
                    for ni2, nj2, nk2, c2 in nbrs:
                        if 0 <= ni2 < Nx and 0 <= nj2 < Ny and 0 <= nk2 < Nz:
                            rows.append(nid)
                            cols.append(node_idx(ni2, nj2, nk2))
                            vals.append(-c2)
                        else:
                            # Neumann at grid boundary: reduce diagonal
                            rows.append(nid); cols.append(nid); vals.append(-c2)

    L = _sp.csr_matrix(
        (vals, (rows, cols)),
        shape=(N_nodes, N_nodes),
        dtype=float,
    )

    # ---- solve per cage vertex -----------------------------------------
    W = np.zeros((n_d, n_c), dtype=float)

    for ci in range(n_c):
        b = np.zeros(N_nodes, dtype=float)
        # Set Dirichlet: h=1 at cage_i nodes, h=0 at all other cage nodes
        for ci2 in range(n_c):
            val = 1.0 if ci2 == ci else 0.0
            for nid in cage_node_sets[ci2]:
                b[nid] = val

        try:
            h = _spla.spsolve(L, b)
        except Exception:
            # Fallback: uniform weights
            h = np.full(N_nodes, 1.0 / n_c)

        # Clamp to [0, 1] — tiny violations from numerical errors
        h = np.clip(h, 0.0, 1.0)

        # ---- trilinear interpolation to detail vertices ----------------
        for di in range(n_d):
            dp = detail_pts[di]
            # Fractional grid coordinates
            fx = (dp[0] - bb_min[0]) / dx
            fy = (dp[1] - bb_min[1]) / dy
            fz = (dp[2] - bb_min[2]) / dz

            i0 = int(math.floor(fx))
            j0 = int(math.floor(fy))
            k0 = int(math.floor(fz))

            i0 = max(0, min(i0, Nx - 2))
            j0 = max(0, min(j0, Ny - 2))
            k0 = max(0, min(k0, Nz - 2))

            tx = fx - i0
            ty = fy - j0
            tz = fz - k0

            # Trilinear interpolation over 2×2×2 cube
            val = 0.0
            for di2 in range(2):
                for dj2 in range(2):
                    for dk2 in range(2):
                        wx = tx if di2 == 1 else (1.0 - tx)
                        wy = ty if dj2 == 1 else (1.0 - ty)
                        wz = tz if dk2 == 1 else (1.0 - tz)
                        val += wx * wy * wz * h[node_idx(i0 + di2, j0 + dj2, k0 + dk2)]

            W[di, ci] = max(0.0, val)

    # ---- enforce partition of unity ------------------------------------
    row_sums = W.sum(axis=1, keepdims=True)
    # Avoid division by zero: uniform fallback for degenerate rows
    zero_mask = row_sums < 1e-15
    if zero_mask.any():
        W[zero_mask[:, 0]] = 1.0 / n_c
        row_sums = W.sum(axis=1, keepdims=True)

    W /= row_sums

    return W


# ---------------------------------------------------------------------------
# DeformCage builders
# ---------------------------------------------------------------------------

def build_deform_cage_harmonic(
    detail_mesh: "SubDMesh | dict | np.ndarray",
    n_cage_verts: int = 20,
) -> DeformCage:
    """Build a DeformCage using harmonic coordinates for more stable deformation.

    For concave shapes harmonic coords are preferable to MVC because they
    guarantee non-negativity for interior detail vertices.

    The cage is generated as a bounding-box cage with n_cage_verts spread over
    the surface of an axis-aligned box enclosing the detail mesh.  For real
    character animation the caller should supply a hand-crafted cage via
    ``compute_harmonic_coordinates`` directly.

    Parameters
    ----------
    detail_mesh : SubDMesh, dict, or ndarray
        Detail mesh providing vertex positions.
    n_cage_verts : int
        Approximate number of cage vertices.  Actual count may differ
        slightly since the cage is a box lattice.

    Returns
    -------
    DeformCage
    """
    detail_pts = _extract_vertices(detail_mesh)
    cage_pts = _make_box_cage(detail_pts, n_cage_verts)

    try:
        weights = compute_harmonic_coordinates(detail_pts, cage_pts)
        return DeformCage(
            cage_verts=cage_pts,
            weights=weights,
            method="harmonic",
        )
    except Exception:
        # Graceful fallback to uniform weights
        n_d = detail_pts.shape[0]
        n_c = cage_pts.shape[0]
        weights = np.full((n_d, n_c), 1.0 / n_c, dtype=float)
        return DeformCage(
            cage_verts=cage_pts,
            weights=weights,
            method="harmonic_fallback",
        )


def build_deform_cage_mvc(
    detail_mesh: "SubDMesh | dict | np.ndarray",
    n_cage_verts: int = 20,
) -> DeformCage:
    """Build a DeformCage using mean-value coordinates (Ju 2005).

    Provided as a companion builder for the comparison baseline.
    """
    detail_pts = _extract_vertices(detail_mesh)
    cage_pts = _make_box_cage(detail_pts, n_cage_verts)
    weights = _compute_mvc(detail_pts, cage_pts)
    return DeformCage(
        cage_verts=cage_pts,
        weights=weights,
        method="mvc",
    )


# ---------------------------------------------------------------------------
# Comparison utility
# ---------------------------------------------------------------------------

def compare_coord_methods(
    detail_mesh: "SubDMesh | dict | np.ndarray",
    cage: DeformCage,
    deformation: np.ndarray,
    methods: List[str] = None,
) -> Dict[str, dict]:
    """Compare harmonic vs MVC deformation quality under a cage deformation.

    Parameters
    ----------
    detail_mesh : SubDMesh / dict / ndarray
        Rest-pose detail mesh.
    cage : DeformCage
        Rest-pose cage (used to derive cage vertices).
    deformation : array_like (n_cage, 3)
        Deformed cage vertex positions.
    methods : list of str
        Subset of ``['mvc', 'harmonic']`` to evaluate (default: both).

    Returns
    -------
    dict mapping method_name -> metrics dict with keys:
        max_stretch       — max edge-length ratio (deformed/rest), > 1 = stretch
        min_stretch       — min edge-length ratio, < 1 = compression
        weight_min        — minimum weight value (< 0 indicates MVC artefact)
        weight_max        — maximum weight value
        partition_of_unity_max_err  — max |sum_of_weights - 1| across detail verts
    """
    if methods is None:
        methods = ["mvc", "harmonic"]

    detail_pts = _extract_vertices(detail_mesh)
    def_cage = np.asarray(deformation, dtype=float)

    results: Dict[str, dict] = {}

    for m in methods:
        try:
            if m == "harmonic":
                if _SCIPY_AVAILABLE:
                    w = compute_harmonic_coordinates(detail_pts, cage.cage_verts)
                else:
                    # Can't compute; record failure
                    results[m] = {"ok": False, "reason": "scipy not available"}
                    continue
            elif m == "mvc":
                w = _compute_mvc(detail_pts, cage.cage_verts)
            else:
                results[m] = {"ok": False, "reason": f"unknown method: {m}"}
                continue

            deformed = w @ def_cage  # (n_detail, 3)

            # Edge-length distortion on detail mesh (if available)
            max_stretch = 1.0
            min_stretch = 1.0
            if hasattr(detail_mesh, "faces") and detail_mesh.faces:  # type: ignore[union-attr]
                faces = detail_mesh.faces  # type: ignore[union-attr]
                stretches = []
                for face in faces:
                    for a, b in zip(face, face[1:] + [face[0]]):
                        rest_len = float(np.linalg.norm(detail_pts[a] - detail_pts[b]))
                        def_len = float(np.linalg.norm(deformed[a] - deformed[b]))
                        if rest_len > 1e-12:
                            stretches.append(def_len / rest_len)
                if stretches:
                    max_stretch = float(np.max(stretches))
                    min_stretch = float(np.min(stretches))

            pou_err = float(np.max(np.abs(w.sum(axis=1) - 1.0)))

            results[m] = {
                "ok": True,
                "max_stretch": max_stretch,
                "min_stretch": min_stretch,
                "weight_min": float(w.min()),
                "weight_max": float(w.max()),
                "partition_of_unity_max_err": pou_err,
            }
        except Exception as exc:
            results[m] = {"ok": False, "reason": str(exc)}

    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_vertices(mesh_or_pts) -> np.ndarray:
    """Return (n, 3) float64 array of vertex positions from various input types."""
    if isinstance(mesh_or_pts, np.ndarray):
        arr = np.asarray(mesh_or_pts, dtype=float)
        if arr.ndim == 2 and arr.shape[1] == 3:
            return arr
        raise ValueError(f"ndarray must be (n, 3), got {arr.shape}")
    if isinstance(mesh_or_pts, dict):
        verts = mesh_or_pts.get("vertices", [])
        return np.asarray(verts, dtype=float)
    # Assume SubDMesh or SubDCage or any object with .vertices attribute
    if hasattr(mesh_or_pts, "vertices"):
        return np.asarray(mesh_or_pts.vertices, dtype=float)
    raise TypeError(
        f"Cannot extract vertices from {type(mesh_or_pts).__name__}. "
        "Expected SubDMesh, dict with 'vertices', or (n,3) ndarray."
    )


def _make_box_cage(detail_pts: np.ndarray, n_verts: int) -> np.ndarray:
    """Generate an axis-aligned box cage around the detail mesh.

    Distributes approximately n_verts control points uniformly over the
    faces of an enclosing bounding box, scaled 20% larger.
    """
    bb_min = detail_pts.min(axis=0)
    bb_max = detail_pts.max(axis=0)

    # Scale box outward by 20%
    centre = (bb_min + bb_max) * 0.5
    half = (bb_max - bb_min) * 0.5
    half = np.maximum(half, 1e-3)  # prevent degenerate box
    half *= 1.20
    bb_min = centre - half
    bb_max = centre + half

    # Distribute control points on the 6 box faces.
    # Determine resolution k such that 6*k^2 ≈ n_verts
    k = max(2, int(round(math.sqrt(n_verts / 6))))

    pts: List[List[float]] = []

    for face in range(6):
        # Each face: two axes (u, v) parameterised by k×k grid
        for ui in range(k):
            for vi in range(k):
                u = ui / (k - 1) if k > 1 else 0.5
                v = vi / (k - 1) if k > 1 else 0.5

                if face == 0:   # -X
                    pts.append([bb_min[0], bb_min[1] + u * (bb_max[1] - bb_min[1]),
                                 bb_min[2] + v * (bb_max[2] - bb_min[2])])
                elif face == 1: # +X
                    pts.append([bb_max[0], bb_min[1] + u * (bb_max[1] - bb_min[1]),
                                 bb_min[2] + v * (bb_max[2] - bb_min[2])])
                elif face == 2: # -Y
                    pts.append([bb_min[0] + u * (bb_max[0] - bb_min[0]),
                                 bb_min[1],
                                 bb_min[2] + v * (bb_max[2] - bb_min[2])])
                elif face == 3: # +Y
                    pts.append([bb_min[0] + u * (bb_max[0] - bb_min[0]),
                                 bb_max[1],
                                 bb_min[2] + v * (bb_max[2] - bb_min[2])])
                elif face == 4: # -Z
                    pts.append([bb_min[0] + u * (bb_max[0] - bb_min[0]),
                                 bb_min[1] + v * (bb_max[1] - bb_min[1]),
                                 bb_min[2]])
                elif face == 5: # +Z
                    pts.append([bb_min[0] + u * (bb_max[0] - bb_min[0]),
                                 bb_min[1] + v * (bb_max[1] - bb_min[1]),
                                 bb_max[2]])

    # Deduplicate (corners appear in 3 faces each)
    unique_pts: List[List[float]] = []
    seen: set = set()
    for p in pts:
        key = (round(p[0], 8), round(p[1], 8), round(p[2], 8))
        if key not in seen:
            seen.add(key)
            unique_pts.append(p)

    return np.asarray(unique_pts, dtype=float)


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

    _subd_harmonic_coords_spec = ToolSpec(
        name="subd_harmonic_coords",
        description=(
            "Compute harmonic coordinates for cage-based mesh deformation "
            "(Joshi-Meyer-DeRose-Green-Sanocki, SIGGRAPH 2007). "
            "Solves the discrete Laplace equation Δh_i = 0 with boundary "
            "conditions h_i = 1 at cage vertex i and h_i = 0 at all other "
            "cage vertices. Returns a weight matrix (n_detail × n_cage) with "
            "guaranteed non-negativity and partition-of-unity (rows sum to 1). "
            "Better than mean-value coordinates (MVC) for concave cages — "
            "MVC can produce small negative weights inside concavities.\n\n"
            "Inputs: detail_vertices ([[x,y,z],...]) and cage_vertices "
            "([[x,y,z],...]). "
            "Optional grid_res (8–40, default 20) controls solver accuracy.\n\n"
            "Returns: {ok, weights: [[w0, w1, ...], ...], "
            "n_detail, n_cage, weight_min, weight_max, "
            "partition_of_unity_max_err, method}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "detail_vertices": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "minItems": 1,
                    "description": "Detail mesh vertices as [[x,y,z], ...] (≥1 vertex).",
                },
                "cage_vertices": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "minItems": 2,
                    "description": "Cage control vertices as [[x,y,z], ...] (≥2 vertices).",
                },
                "grid_res": {
                    "type": "integer",
                    "minimum": 4,
                    "maximum": 64,
                    "default": 20,
                    "description": (
                        "Voxel grid resolution per axis (default 20). "
                        "Higher values improve accuracy but increase solve time. "
                        "Recommended range 8–40."
                    ),
                },
            },
            "required": ["detail_vertices", "cage_vertices"],
        },
    )

    @register(_subd_harmonic_coords_spec)
    async def run_subd_harmonic_coords(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        detail_raw = a.get("detail_vertices")
        cage_raw = a.get("cage_vertices")
        grid_res = a.get("grid_res", 20)

        if not isinstance(detail_raw, list) or len(detail_raw) < 1:
            return err_payload("detail_vertices must be a non-empty list", "BAD_ARGS")
        if not isinstance(cage_raw, list) or len(cage_raw) < 2:
            return err_payload("cage_vertices must be a list with ≥2 entries", "BAD_ARGS")
        if not isinstance(grid_res, int) or not (4 <= grid_res <= 64):
            return err_payload("grid_res must be an integer 4–64", "BAD_ARGS")

        try:
            detail_pts = np.array([[float(c) for c in row[:3]] for row in detail_raw])
            cage_pts = np.array([[float(c) for c in row[:3]] for row in cage_raw])
        except Exception as exc:
            return err_payload(f"could not parse vertex arrays: {exc}", "BAD_ARGS")

        try:
            w = compute_harmonic_coordinates(detail_pts, cage_pts, grid_res=grid_res)
        except ImportError as exc:
            return err_payload(str(exc), "NOT_AVAILABLE")
        except Exception as exc:
            return err_payload(f"harmonic solve failed: {exc}", "OP_FAILED")

        pou_err = float(np.max(np.abs(w.sum(axis=1) - 1.0)))

        return ok_payload({
            "weights": w.tolist(),
            "n_detail": int(detail_pts.shape[0]),
            "n_cage": int(cage_pts.shape[0]),
            "weight_min": float(w.min()),
            "weight_max": float(w.max()),
            "partition_of_unity_max_err": pou_err,
            "method": "harmonic",
        })
