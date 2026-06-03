"""
ALE dynamic mesh deformation and Fluid-Structure Interaction utilities.

Overview
--------
Implements the Arbitrary Lagrangian-Eulerian (ALE) framework for moving-mesh
CFD simulations:

1. **Laplacian mesh smoothing** (Lohner-Yang 1996):
   Interior mesh vertices are displaced by solving a discrete Laplace equation
   to propagate boundary motion smoothly into the interior while preserving
   mesh quality.  The update is:

       x_i^{n+1} = x_i^n + (1/|N_i|) Σ_{j ∈ N_i} (x_j^n - x_i^n)

   iterated ``smoothing_iterations`` times with boundary vertices held fixed
   after their prescribed displacement.

2. **Geometric Conservation Law (GCL)** (Thomas-Lombard 1979):
   On a moving mesh the discrete GCL ensures that a uniform flow remains
   exactly preserved.  The GCL correction computes the swept volume
   δV for each cell face from the mesh velocity:

       δV_face ≈ dot(w_face, n_face) · A_face · dt

   For a stationary mesh all corrections are zero.

3. **One-way FSI coupling**:
   Fluid pressure at the wetted boundary drives structural deformation via a
   compliance matrix:

       u_boundary = C @ p_boundary

   where C is the (Nb × Nb) structural compliance matrix [m/Pa].  This is
   appropriate for linear-elastic structures with small deformations.

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM or experimental benchmarks.  Do not use for safety-critical design.

References
----------
Lohner, R., Yang, C. (1996). "Improved ALE mesh velocities for moving
bodies." Comm. Num. Meth. Eng. 12(10), 599–608.

Thomas, P.D., Lombard, C.K. (1979). "Geometric conservation law and its
application to flow computations on moving grids." AIAA J. 17(10), 1030–1037.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class DynamicMeshState:
    """State of a moving ALE mesh.

    Attributes
    ----------
    vertices:
        Vertex coordinates, shape (Nv, 3) [m].
    cell_connectivity:
        Cell-to-vertex connectivity, shape (Nc, nv_per_cell).
        nv_per_cell = 4 for tetrahedra, 8 for hexahedra.
    vertex_velocity:
        ALE mesh (grid) velocity at each vertex, shape (Nv, 3) [m/s].
        Computed by :func:`displace_mesh_rigid` as Δx / dt.
    """
    vertices: np.ndarray
    cell_connectivity: np.ndarray
    vertex_velocity: np.ndarray

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=float)
        self.cell_connectivity = np.asarray(self.cell_connectivity, dtype=int)
        self.vertex_velocity = np.asarray(self.vertex_velocity, dtype=float)

    def copy(self) -> "DynamicMeshState":
        return DynamicMeshState(
            vertices=self.vertices.copy(),
            cell_connectivity=self.cell_connectivity.copy(),
            vertex_velocity=self.vertex_velocity.copy(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_vertex_neighbours(
    n_vertices: int,
    cell_connectivity: np.ndarray,
) -> list:
    """Build adjacency list: vertex → set of neighbouring vertex indices.

    Two vertices are neighbours if they share a cell edge (i.e. appear together
    in any row of cell_connectivity).
    """
    neighbours: list = [set() for _ in range(n_vertices)]
    for cell in cell_connectivity:
        for a in cell:
            for b in cell:
                if a != b:
                    neighbours[a].add(b)
    return neighbours


# ---------------------------------------------------------------------------
# Laplacian mesh smoothing (Lohner-Yang 1996)
# ---------------------------------------------------------------------------

def displace_mesh_rigid(
    state: DynamicMeshState,
    boundary_displacement: np.ndarray,
    boundary_node_ids: list,
    dt: float,
    smoothing_iterations: int = 5,
) -> DynamicMeshState:
    """Move boundary nodes and propagate motion to interior via Laplacian smoothing.

    Algorithm (Lohner-Yang 1996):
      1. Apply prescribed displacement to boundary vertices.
      2. For ``smoothing_iterations`` sweeps over all interior vertices,
         update each as the average of its neighbours' positions.
      3. Compute vertex_velocity = (x_new - x_old) / dt.

    The Laplacian smoothing step is:

        x_i^{k+1} = (1/|N_i|) Σ_{j ∈ N_i} x_j^k    (interior only)

    Boundary vertices are held fixed at their displaced positions throughout.

    Parameters
    ----------
    state:
        Current mesh state.
    boundary_displacement:
        Prescribed displacement for each boundary vertex, shape (Nb, 3) [m].
    boundary_node_ids:
        List of length Nb containing the global vertex indices of boundary nodes.
    dt:
        Time step [s].  Used to compute vertex_velocity.
    smoothing_iterations:
        Number of Laplacian smoothing sweeps (default 5).

    Returns
    -------
    DynamicMeshState
        Updated mesh with new vertex positions and mesh velocities.

    References
    ----------
    Lohner, R., Yang, C. (1996). Comm. Num. Meth. Eng. 12(10), 599–608.
    """
    boundary_displacement = np.asarray(boundary_displacement, dtype=float)
    boundary_node_ids = list(boundary_node_ids)
    n_verts = len(state.vertices)

    x_old = state.vertices.copy()
    x_new = state.vertices.copy()

    # Step 1: apply boundary displacement
    for local_idx, global_idx in enumerate(boundary_node_ids):
        x_new[global_idx] = x_old[global_idx] + boundary_displacement[local_idx]

    # Build neighbour list (once)
    neighbours = _build_vertex_neighbours(n_verts, state.cell_connectivity)
    boundary_set = set(boundary_node_ids)

    # Step 2: Laplacian smoothing sweeps
    for _ in range(smoothing_iterations):
        x_sweep = x_new.copy()
        for i in range(n_verts):
            if i in boundary_set:
                continue  # boundary held fixed
            nb = list(neighbours[i])
            if not nb:
                continue
            x_sweep[i] = np.mean(x_new[nb], axis=0)
        x_new = x_sweep

    # Step 3: mesh velocity = Δx / dt
    w = (x_new - x_old) / dt if dt > 0.0 else np.zeros_like(x_new)

    return DynamicMeshState(
        vertices=x_new,
        cell_connectivity=state.cell_connectivity.copy(),
        vertex_velocity=w,
    )


# ---------------------------------------------------------------------------
# Geometric Conservation Law correction (Thomas-Lombard 1979)
# ---------------------------------------------------------------------------

def compute_geometric_conservation_law_correction(
    state_old: DynamicMeshState,
    state_new: DynamicMeshState,
    cell_face_normals: np.ndarray,
    dt: float,
) -> np.ndarray:
    """Compute the GCL swept-volume correction for each cell.

    The Geometric Conservation Law (Thomas-Lombard 1979) requires that the
    numerical scheme on a moving mesh preserves a spatially uniform flow
    exactly.  This is achieved by computing the swept volume δV consistent
    with the discrete face-flux:

        δV_cell = Σ_f  dot(w_f, n_f) · A_f · dt

    where w_f is the face mesh velocity (average of its vertex velocities),
    n_f is the outward unit face normal, and A_f is the face area.

    Here we use a cell-centred approximation: the mesh velocity at each cell
    centre is estimated as the average of its vertex velocities, and the GCL
    volume is computed as:

        δV_cell ≈ dot(w_cell, Σ_f n_f · A_f) · dt

    For a stationary mesh (state_old == state_new) all corrections are zero.

    Parameters
    ----------
    state_old:
        Mesh state at time t^n.
    state_new:
        Mesh state at time t^{n+1}.
    cell_face_normals:
        Area-weighted outward face normals per cell, shape (Nc, 3) [m²].
        Each row is the vector sum of face normals × areas for that cell.
    dt:
        Time step [s].

    Returns
    -------
    np.ndarray, shape (Nc,)
        GCL swept-volume correction δV per cell [m³].  Zero for stationary mesh.

    References
    ----------
    Thomas, P.D., Lombard, C.K. (1979). AIAA J. 17(10), 1030–1037.
    """
    cell_face_normals = np.asarray(cell_face_normals, dtype=float)
    n_cells = len(state_old.cell_connectivity)

    # Average mesh velocity at each cell centre
    w_cell_old = np.zeros((n_cells, 3))
    w_cell_new = np.zeros((n_cells, 3))

    for ci, cell in enumerate(state_old.cell_connectivity):
        w_cell_old[ci] = np.mean(state_old.vertex_velocity[cell], axis=0)
        w_cell_new[ci] = np.mean(state_new.vertex_velocity[cell], axis=0)

    # Use mid-point (time-centred) mesh velocity for GCL
    w_mid = 0.5 * (w_cell_old + w_cell_new)

    # GCL swept volume: δV = dot(w_cell, Σ n_f A_f) · dt
    # cell_face_normals is the net vector [m²] for each cell
    delta_V = np.einsum("ci,ci->c", w_mid, cell_face_normals) * dt

    return delta_V


# ---------------------------------------------------------------------------
# One-way FSI coupling
# ---------------------------------------------------------------------------

def fsi_one_way_coupling(
    fluid_pressure_at_boundary: np.ndarray,
    structure_compliance: np.ndarray,
) -> np.ndarray:
    """Compute structural boundary displacement from fluid pressure (one-way FSI).

    In one-way FSI coupling the fluid drives the structure but the structure
    does not deform the fluid domain within the same time step.  Given the
    fluid pressure at Nb boundary nodes and a (Nb × Nb) linear-elastic
    compliance matrix C [m/Pa], the boundary displacement vector is:

        u_boundary = C @ p_boundary

    where u_boundary has shape (Nb,) (scalar normal displacement) or
    (Nb, ndof) for multi-DOF structures.

    Parameters
    ----------
    fluid_pressure_at_boundary:
        Fluid (gauge) pressure at each boundary node, shape (Nb,) [Pa].
    structure_compliance:
        Structural compliance matrix, shape (Nb, Nb) [m/Pa].
        Each entry C[i,j] is the displacement at node i due to a unit
        pressure at node j.

    Returns
    -------
    np.ndarray, shape (Nb,)
        Normal boundary displacement [m].

    References
    ----------
    Lohner, R., Yang, C. (1996). Comm. Num. Meth. Eng. 12(10), 599–608.
    """
    p = np.asarray(fluid_pressure_at_boundary, dtype=float)
    C = np.asarray(structure_compliance, dtype=float)
    return C @ p
