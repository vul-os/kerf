"""sculpt/character_rigging.py — Bone hierarchy, weight painting, and Linear Blend Skinning.

Background
----------
Character rigging for VFX and animation requires:
1. A **skeleton** — a hierarchy of bones, each with a world-space rest pose.
2. A **weight map** — per-vertex bone influence weights summing to 1 (at most
   *max_bones_per_vertex* non-zero weights for GPU efficiency).
3. **Linear Blend Skinning (LBS)** — the standard real-time deformation formula
   that blends the pose-space transformation of each contributing bone:

       p_new = Σ_i  w_i · M_i^pose · (M_i^rest)⁻¹ · p_rest

   where M_i^rest is the bone's rest-pose world matrix and M_i^pose is its
   current pose matrix (Lewis et al. 2000).
4. **Automatic weight computation** — Baran & Popović (2007) showed that
   heat-diffusion weights from bone segments produce natural deformation for
   most character meshes.  The heat weight for a vertex v toward bone b is
   proportional to the heat that would flow from b to v in a virtual thermal
   diffusion on the mesh surface.  We approximate this with a distance-based
   heuristic followed by one pass of Laplacian smoothing (§6 of the paper).

References
----------
- Baran, I., & Popović, J. (2007). "Automatic Rigging and Animation of 3D
  Characters." ACM SIGGRAPH 2007, TOG 26(3), Article 72.
- Lewis, J.P., Cordner, M., & Fong, N. (2000). "Pose Space Deformation: A
  Unified Approach to Shape Interpolation and Skeleton-Driven Deformation."
  SIGGRAPH 2000, pp. 165-172.  (Linear Blend Skinning foundations.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Bone:
    """A single bone in a character skeleton.

    Attributes
    ----------
    name : str
        Unique bone identifier.
    parent : str or None
        Name of the parent bone, or None for root bones.
    head : np.ndarray, shape (3,)
        World-space position of the bone's proximal (root) end.
    tail : np.ndarray, shape (3,)
        World-space position of the bone's distal (tip) end.
    rest_matrix : np.ndarray, shape (4, 4)
        Homogeneous world-space rest-pose matrix.  The rotation columns are
        the bone's local X, Y (along-bone), Z axes at rest; the translation
        column is *head*.
    """

    name: str
    parent: Optional[str]
    head: np.ndarray        # (3,)
    tail: np.ndarray        # (3,)
    rest_matrix: np.ndarray  # (4, 4) world-space rest pose


@dataclass
class Skeleton:
    """A collection of bones forming an articulated character skeleton.

    Provides :meth:`by_name` lookup and :meth:`topological_order` traversal.
    """

    bones: list[Bone]

    def by_name(self, name: str) -> Bone:
        """Return the bone with the given *name*.

        Raises
        ------
        KeyError
            If no bone with that name exists.
        """
        for bone in self.bones:
            if bone.name == name:
                return bone
        raise KeyError(f"No bone named '{name}' in skeleton")

    def topological_order(self) -> list[str]:
        """Return bone names in topological (parent-before-child) order.

        Root bones (parent=None) come first.  Within each generation, bones
        appear in the order they were added to :attr:`bones`.

        Returns
        -------
        list[str]
            Ordered list of bone names.
        """
        name_set = {b.name for b in self.bones}
        # Build adjacency: parent → [children]
        children: dict[Optional[str], list[str]] = {}
        for bone in self.bones:
            children.setdefault(bone.parent, []).append(bone.name)
        # BFS from root(s) — None parent means root
        ordered: list[str] = []
        queue: list[str] = list(children.get(None, []))
        while queue:
            current = queue.pop(0)
            ordered.append(current)
            queue.extend(children.get(current, []))
        # Append any orphaned bones that didn't appear
        for bone in self.bones:
            if bone.name not in ordered:
                ordered.append(bone.name)
        return ordered


@dataclass
class WeightMap:
    """Per-vertex bone weights (sparse, ≤ max_bones slots per vertex).

    Attributes
    ----------
    vertex_count : int
        Number of vertices.
    bone_indices : np.ndarray, shape (V, 4), int32
        Bone slot indices (into :attr:`Skeleton.bones`).  Unused slots = -1.
    bone_weights : np.ndarray, shape (V, 4), float32
        Corresponding weights.  Rows sum to 1.0 for active vertices.
    """

    vertex_count: int
    bone_indices: np.ndarray    # (V, 4) int32, -1 for unused slots
    bone_weights: np.ndarray    # (V, 4) float32, sum=1 per row


# ---------------------------------------------------------------------------
# Linear Blend Skinning
# ---------------------------------------------------------------------------


def linear_blend_skinning(
    positions: np.ndarray,
    weights: WeightMap,
    skeleton: Skeleton,
    pose_matrices: list[np.ndarray],
) -> np.ndarray:
    """Apply Linear Blend Skinning to transform *positions* by the given pose.

    Implements the standard LBS formula (Lewis et al. 2000):

        p_new = Σ_i  w_i · M_i^pose · (M_i^rest)^{-1} · p_rest

    where the sum runs over the ≤ 4 bone slots per vertex.

    Parameters
    ----------
    positions : np.ndarray, shape (V, 3)
        Rest-pose vertex positions.
    weights : WeightMap
        Bone influence weights (at most 4 per vertex).
    skeleton : Skeleton
        Rest-pose skeleton.  Bone order must match *pose_matrices* indexing.
    pose_matrices : list of np.ndarray, each (4, 4)
        World-space pose matrices, one per bone in *skeleton.bones* order.

    Returns
    -------
    np.ndarray, shape (V, 3)
        Deformed vertex positions.

    References
    ----------
    Lewis, J.P., Cordner, M., & Fong, N. (2000). "Pose Space Deformation."
    SIGGRAPH 2000, pp. 165-172.
    """
    V = len(positions)
    pos4 = np.ones((V, 4), dtype=np.float64)
    pos4[:, :3] = positions.astype(np.float64)

    # Pre-compute skinning matrices: M_pose * M_rest^{-1} for each bone
    n_bones = len(skeleton.bones)
    skin_mats = np.zeros((n_bones, 4, 4), dtype=np.float64)
    for b_idx, bone in enumerate(skeleton.bones):
        M_rest_inv = np.linalg.inv(bone.rest_matrix.astype(np.float64))
        M_pose = np.asarray(pose_matrices[b_idx], dtype=np.float64)
        skin_mats[b_idx] = M_pose @ M_rest_inv

    result = np.zeros((V, 3), dtype=np.float64)

    for slot in range(weights.bone_indices.shape[1]):
        b_idx_arr = weights.bone_indices[:, slot]   # (V,)
        w_arr     = weights.bone_weights[:, slot].astype(np.float64)  # (V,)

        active = b_idx_arr >= 0
        if not np.any(active):
            continue

        for b_idx in np.unique(b_idx_arr[active]):
            vert_mask = active & (b_idx_arr == b_idx)
            if not np.any(vert_mask):
                continue
            M = skin_mats[b_idx]  # (4, 4)
            p4 = pos4[vert_mask]  # (K, 4)
            w  = w_arr[vert_mask, None]  # (K, 1)
            transformed = (M @ p4.T).T[:, :3]  # (K, 3)
            result[vert_mask] += w * transformed

    return result


# ---------------------------------------------------------------------------
# Automatic weight computation (Baran–Popović 2007 §6 heuristic)
# ---------------------------------------------------------------------------


def _point_to_segment_distance(
    points: np.ndarray,  # (N, 3)
    a: np.ndarray,       # (3,)
    b: np.ndarray,       # (3,)
) -> np.ndarray:
    """Minimum distance from each point to the line segment a–b.

    Returns (N,) distances.
    """
    ab = b - a
    ab_len2 = np.dot(ab, ab)
    if ab_len2 < 1e-20:
        return np.linalg.norm(points - a, axis=1)

    t = np.clip(np.einsum("ni,i->n", points - a, ab) / ab_len2, 0.0, 1.0)
    closest = a[None, :] + t[:, None] * ab[None, :]
    return np.linalg.norm(points - closest, axis=1)


def _one_ring_neighbours(triangles: np.ndarray, V: int) -> list[list[int]]:
    """Build per-vertex one-ring neighbour lists from *triangles*."""
    rings: list[set[int]] = [set() for _ in range(V)]
    for tri in triangles:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        rings[i0].update([i1, i2])
        rings[i1].update([i0, i2])
        rings[i2].update([i0, i1])
    return [list(r) for r in rings]


def auto_weight_from_proximity(
    positions: np.ndarray,
    skeleton: Skeleton,
    max_bones_per_vert: int = 4,
    triangles: np.ndarray | None = None,
    smooth_iters: int = 3,
) -> WeightMap:
    """Compute bone influence weights by bone-distance heuristic + Laplacian smoothing.

    Implements the Baran & Popović (2007) §6 approach:
    1. For each vertex compute the distance to every bone segment (head→tail).
    2. Convert distances to initial weights using an inverse-distance²
       softmax (heat kernel approximation).
    3. Apply *smooth_iters* rounds of uniform-weight Laplacian smoothing on the
       mesh surface (requires *triangles* to be provided; skipped otherwise).
    4. Keep the top *max_bones_per_vert* weights per vertex and re-normalise.

    Parameters
    ----------
    positions : np.ndarray, shape (V, 3)
        Mesh vertex positions.
    skeleton : Skeleton
        Skeleton whose bones define the influence regions.
    max_bones_per_vert : int
        Maximum number of active bone slots (≤ 4 for GPU constraints).
    triangles : np.ndarray, shape (F, 3) or None
        Triangle connectivity used for Laplacian smoothing.  If None,
        smoothing is skipped.
    smooth_iters : int
        Number of Laplacian smoothing iterations.

    Returns
    -------
    WeightMap
        Bone weights for all vertices, normalised to sum = 1.

    References
    ----------
    Baran, I., & Popović, J. (2007). "Automatic Rigging and Animation of 3D
    Characters." SIGGRAPH 2007, TOG 26(3), Article 72.
    """
    positions = np.asarray(positions, dtype=np.float64)
    V = len(positions)
    n_bones = len(skeleton.bones)

    if max_bones_per_vert > 4:
        max_bones_per_vert = 4  # hardware limit for GPU skinning

    # --- Step 1: distance to each bone segment ---
    dist = np.zeros((V, n_bones), dtype=np.float64)
    for b_idx, bone in enumerate(skeleton.bones):
        dist[:, b_idx] = _point_to_segment_distance(positions, bone.head, bone.tail)

    # --- Step 2: heat-kernel weights (inverse-distance² softmax) ---
    # Avoid division by zero for vertices on a bone
    eps = 1e-8
    inv_dist2 = 1.0 / (dist ** 2 + eps)
    raw_weights = inv_dist2 / inv_dist2.sum(axis=1, keepdims=True)  # (V, n_bones)

    # --- Step 3: Laplacian smoothing ---
    if triangles is not None and smooth_iters > 0:
        triangles_arr = np.asarray(triangles, dtype=np.int32)
        rings = _one_ring_neighbours(triangles_arr, V)
        for _ in range(smooth_iters):
            new_w = raw_weights.copy()
            for v_idx, nbrs in enumerate(rings):
                if not nbrs:
                    continue
                nbr_w = raw_weights[nbrs]  # (K, n_bones)
                new_w[v_idx] = 0.5 * raw_weights[v_idx] + 0.5 * nbr_w.mean(axis=0)
            # Re-normalise after smoothing
            row_sums = new_w.sum(axis=1, keepdims=True)
            row_sums = np.where(row_sums < 1e-15, 1.0, row_sums)
            raw_weights = new_w / row_sums

    # --- Step 4: keep top max_bones_per_vert, normalise ---
    slots = min(max_bones_per_vert, n_bones)
    bone_indices = np.full((V, 4), -1, dtype=np.int32)
    bone_weights = np.zeros((V, 4), dtype=np.float32)

    for v_idx in range(V):
        row = raw_weights[v_idx]
        top_idx = np.argsort(row)[::-1][:slots]
        top_w   = row[top_idx]
        total   = top_w.sum()
        if total < 1e-15:
            total = 1.0
        top_w = (top_w / total).astype(np.float32)

        bone_indices[v_idx, :slots] = top_idx.astype(np.int32)
        bone_weights[v_idx, :slots] = top_w

    return WeightMap(
        vertex_count=V,
        bone_indices=bone_indices,
        bone_weights=bone_weights,
    )


# ---------------------------------------------------------------------------
# Skeleton builder helpers
# ---------------------------------------------------------------------------


def make_bone(
    name: str,
    head: np.ndarray,
    tail: np.ndarray,
    parent: Optional[str] = None,
) -> Bone:
    """Create a :class:`Bone` with an auto-computed rest matrix.

    The rest matrix places the Y-axis along the bone direction
    (head→tail), Z-axis perpendicular in the XZ plane (or the YZ plane if
    the bone is vertical), and X-axis completing the right-hand basis.

    Parameters
    ----------
    name : str
        Unique bone name.
    head : array-like (3,)
        Proximal end in world space.
    tail : array-like (3,)
        Distal end in world space.
    parent : str, optional
        Parent bone name.
    """
    head = np.asarray(head, dtype=np.float64)
    tail = np.asarray(tail, dtype=np.float64)

    y_axis = tail - head
    length = np.linalg.norm(y_axis)
    if length < 1e-12:
        y_axis = np.array([0.0, 1.0, 0.0])
    else:
        y_axis /= length

    # Choose a perpendicular reference vector
    ref = np.array([0.0, 0.0, 1.0]) if abs(y_axis[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    x_axis = np.cross(ref, y_axis)
    x_norm = np.linalg.norm(x_axis)
    x_axis = x_axis / x_norm if x_norm > 1e-12 else np.array([1.0, 0.0, 0.0])
    z_axis = np.cross(x_axis, y_axis)

    M = np.eye(4, dtype=np.float64)
    M[:3, 0] = x_axis
    M[:3, 1] = y_axis
    M[:3, 2] = z_axis
    M[:3, 3] = head

    return Bone(name=name, parent=parent, head=head, tail=tail, rest_matrix=M)
