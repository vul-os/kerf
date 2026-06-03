"""sculpt/brush.py — Mesh sculpt brush engine.

Five brush operations on triangle meshes with radius-falloff and delta-based undo:
    GRAB, SMOOTH, INFLATE, CREASE, PINCH

References
----------
- Sederberg, T.W. & Parry, S.R. (1986) "Free-form deformation of solid geometric
  models", SIGGRAPH Proc. pp. 151-160. (Soft-selection / falloff concept adapted for
  direct vertex sculpting; here we use radial influence instead of FFD lattices.)
- Pixar / Mudbox sculpt-brush conventions: falloff weight, strength, per-vertex normal
  accumulation, and delta-based undo follow the established DCC tool idioms described
  in Autodesk Mudbox Technical Reference (2013) and the Blender sculpt-mode source.
- Botsch, M. & Sorkine, O. (2008) "On linear variational surface deformation methods",
  IEEE TVCG 14(1):213-230. (Laplacian smoothing context.)
- Meyer, M., Desbrun, M., Schröder, P. & Barr, A.H. (2003) "Discrete
  Differential-Geometry Operators for Triangulated 2-Manifolds", VisMath.
  (Area-weighted vertex normal accumulation, §3.1.)

Design notes
------------
- Pure Python + NumPy; no OCC dependency.
- All operations are single-stroke and stateless; undo is handled externally via
  MeshDelta (caller stacks MeshDelta objects and calls revert_delta to pop them).
- SculptMesh.positions is mutated in-place by apply_brush for performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Public enums and dataclasses
# ---------------------------------------------------------------------------


class BrushKind(str, Enum):
    """Sculpt brush operation kind."""

    GRAB = "grab"      # translate verts in brush radius along input direction
    SMOOTH = "smooth"  # Laplacian smoothing — move toward neighbours' centroid
    INFLATE = "inflate"  # push verts along per-vertex normal
    CREASE = "crease"  # pinch toward stroke axis (sharpen edge)
    PINCH = "pinch"    # pull verts toward brush center


@dataclass
class BrushStroke:
    """Parameters for a single sculpt-brush stroke.

    Parameters
    ----------
    kind:
        Which operation to apply (GRAB, SMOOTH, INFLATE, CREASE, PINCH).
    center:
        World-space position of the brush center, shape (3,).
    direction:
        Unit direction for GRAB (stroke direction) and CREASE (stroke axis).
        Must be provided for GRAB; optional for CREASE (falls back to no-op if
        None).  Ignored for SMOOTH, INFLATE, PINCH.
    radius:
        Influence radius in world units (> 0).  Vertices farther than this from
        *center* receive zero weight.
    strength:
        Scalar in [0, 1] controlling the magnitude of the displacement.  0
        produces no change; 1 applies the full formula displacement.
    falloff:
        Falloff shape: "smooth" (cubic Hermite), "linear", or "constant".
        See falloff_weight() for exact formulas.
    """

    kind: BrushKind
    center: np.ndarray              # (3,) world position
    direction: Optional[np.ndarray]  # (3,) direction (for GRAB/CREASE) or None
    radius: float                   # influence radius in world units
    strength: float                 # 0..1
    falloff: str = "smooth"         # "smooth" (cubic), "linear", "constant"


@dataclass
class MeshDelta:
    """Per-vertex displacement record for undo / redo.

    Attributes
    ----------
    vertex_indices:
        Indices of the affected vertices, shape (K,).
    deltas:
        Displacement vectors applied to each affected vertex, shape (K, 3).
        Subtracting these from positions reverts the stroke.
    """

    vertex_indices: np.ndarray   # (K,) int
    deltas: np.ndarray           # (K, 3) float


@dataclass
class SculptMesh:
    """Triangle mesh with mutable vertex positions.

    Attributes
    ----------
    positions:
        Vertex positions, shape (V, 3).  Mutated in-place by apply_brush.
    triangles:
        Triangle face index array, shape (F, 3), dtype int.
    """

    positions: np.ndarray   # (V, 3)
    triangles: np.ndarray   # (F, 3) vertex indices

    # ------------------------------------------------------------------
    # Cached derived data (invalidated by _invalidate_cache)
    # ------------------------------------------------------------------
    _normals_cache: Optional[np.ndarray] = field(default=None, repr=False)
    _ring_cache: Optional[list] = field(default=None, repr=False)

    def _invalidate_cache(self) -> None:
        """Invalidate cached vertex normals and ring neighbours."""
        self._normals_cache = None
        # Ring topology doesn't change when positions change, so we keep it.

    def vertex_normals(self) -> np.ndarray:
        """Per-vertex normals via area-weighted face-normal accumulation.

        Each triangle contributes its area-weighted face normal to all three
        corner vertices (Meyer et al. 2003 §3.1).  The result is normalised
        per vertex; degenerate vertices (zero accumulated normal) receive
        [0, 0, 1].

        Returns
        -------
        normals : np.ndarray, shape (V, 3)
        """
        # Recompute every call (positions may have changed since last call).
        V = self.positions.shape[0]
        normals = np.zeros((V, 3), dtype=np.float64)

        # Extract triangle vertex positions
        p0 = self.positions[self.triangles[:, 0]]   # (F, 3)
        p1 = self.positions[self.triangles[:, 1]]
        p2 = self.positions[self.triangles[:, 2]]

        # Area-weighted face normals (cross product, not normalised)
        e1 = p1 - p0   # (F, 3)
        e2 = p2 - p0
        fn = np.cross(e1, e2)   # (F, 3) — magnitude = 2 * triangle area

        # Accumulate into vertex normals (each corner gets the same face normal)
        np.add.at(normals, self.triangles[:, 0], fn)
        np.add.at(normals, self.triangles[:, 1], fn)
        np.add.at(normals, self.triangles[:, 2], fn)

        # Normalise; fall back to Z for degenerate vertices
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)  # (V, 1)
        degenerate = (lengths[:, 0] < 1e-12)
        lengths = np.where(lengths < 1e-12, 1.0, lengths)
        normals = normals / lengths
        normals[degenerate] = [0.0, 0.0, 1.0]

        return normals

    def one_ring_neighbours(self) -> list[set[int]]:
        """For each vertex, the set of edge-adjacent vertices.

        Computes from triangles by collecting both directed edges of each
        undirected edge per triangle.  Each unique (i, j) pair with i != j
        contributes j to ring[i] and i to ring[j].

        Returns
        -------
        rings : list of sets, length V
        """
        if self._ring_cache is not None:
            return self._ring_cache

        V = self.positions.shape[0]
        rings: list[set[int]] = [set() for _ in range(V)]

        for tri in self.triangles:
            a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
            rings[a].add(b); rings[a].add(c)
            rings[b].add(a); rings[b].add(c)
            rings[c].add(a); rings[c].add(b)

        self._ring_cache = rings
        return rings


# ---------------------------------------------------------------------------
# Falloff
# ---------------------------------------------------------------------------


def falloff_weight(distance: float, radius: float, kind: str = "smooth") -> float:
    """Brush influence weight at *distance* from brush center.

    Weight is 1.0 at the center (distance = 0) and 0.0 at the boundary
    (distance >= radius).

    Parameters
    ----------
    distance:
        Distance from brush center in world units.
    radius:
        Brush influence radius in world units (> 0).
    kind:
        One of:
        * ``"smooth"``   — cubic Hermite: w = 1 - 3t² + 2t³  (smooth at both
                           ends; matches Pixar/Mudbox "smooth" brush falloff).
                           Note: this is the "smoothstep" complement:
                           if S(t) = 3t²-2t³ then w = 1 - S(t).
                           Sederberg-Parry (1986) use similar smooth kernels for
                           their FFD soft-selection regions.
        * ``"linear"``   — w = 1 - t  (linear ramp).
        * ``"constant"`` — w = 1 for t < 1 (top-hat / uniform brush).

    Returns
    -------
    float in [0, 1].
    """
    if radius <= 0.0:
        raise ValueError(f"radius must be > 0, got {radius}")
    t = float(distance) / float(radius)
    if t >= 1.0:
        return 0.0
    if t < 0.0:
        t = 0.0

    if kind == "smooth":
        # Cubic Hermite / smoothstep complement: 1 - (3t² - 2t³)
        return 1.0 - (3.0 * t * t - 2.0 * t * t * t)
    elif kind == "linear":
        return 1.0 - t
    elif kind == "constant":
        return 1.0
    else:
        raise ValueError(f"unknown falloff kind {kind!r}; use 'smooth', 'linear', or 'constant'")


# ---------------------------------------------------------------------------
# Core brush application
# ---------------------------------------------------------------------------


def apply_brush(mesh: SculptMesh, stroke: BrushStroke) -> MeshDelta:
    """Apply one brush stroke, mutate mesh.positions in-place, return delta.

    The delta can be passed to revert_delta() to undo the stroke.

    Algorithms
    ----------
    GRAB
        v += direction * w * strength
        (Sederberg-Parry 1986 soft-selection concept: vertices within radius
        are translated by a falloff-weighted fraction of the displacement.)

    SMOOTH
        Unweighted Laplacian step: target = mean(neighbour positions);
        v += (target - v) * w * strength.

    INFLATE
        v += vertex_normal * w * strength
        (Mudbox inflate brush convention; normals are area-weighted one-ring.)

    CREASE
        Axis = stroke.direction (stroke axis).  For each vertex in radius,
        compute the offset from the brush center, project out the axis component
        (perpendicular component), then pull the perpendicular toward zero by
        w * strength.  This pinches vertices toward the stroke axis, sharpening
        a ridge or crease.

    PINCH
        v += (center - v) * w * strength
        (Attract toward brush center; shrinks geometry at the brush site.)

    Parameters
    ----------
    mesh:
        Triangle mesh (positions mutated in-place).
    stroke:
        Brush stroke parameters.

    Returns
    -------
    MeshDelta
        Record of per-vertex displacements for undo.
    """
    if stroke.radius <= 0.0:
        raise ValueError(f"stroke.radius must be > 0, got {stroke.radius}")

    positions = mesh.positions        # (V, 3) — we will modify in-place
    center = np.asarray(stroke.center, dtype=np.float64)   # (3,)

    # Compute per-vertex distances to brush center
    offsets = positions - center       # (V, 3)
    distances = np.linalg.norm(offsets, axis=1)   # (V,)

    # Vertices within the brush radius
    in_radius = np.where(distances < stroke.radius)[0]  # (K,)

    if in_radius.size == 0 or stroke.strength == 0.0:
        return MeshDelta(
            vertex_indices=np.array([], dtype=np.intp),
            deltas=np.zeros((0, 3), dtype=np.float64),
        )

    # Compute falloff weights for affected vertices
    d_in = distances[in_radius]                              # (K,)
    weights = np.array(
        [falloff_weight(float(d), stroke.radius, stroke.falloff) for d in d_in],
        dtype=np.float64,
    )   # (K,)

    # Compute per-vertex displacement based on brush kind
    kind = stroke.kind
    s = float(stroke.strength)

    if kind == BrushKind.GRAB:
        # Translate along direction vector, scaled by weight * strength.
        # Sederberg-Parry (1986): each point in the region is shifted by the
        # same displacement, weighted by a smooth falloff function.
        if stroke.direction is None:
            raise ValueError("BrushKind.GRAB requires stroke.direction")
        direction = np.asarray(stroke.direction, dtype=np.float64)
        norm = np.linalg.norm(direction)
        if norm > 1e-12:
            direction = direction / norm
        # disp[i] = direction * weights[i] * strength
        disp = direction[np.newaxis, :] * (weights * s)[:, np.newaxis]   # (K, 3)

    elif kind == BrushKind.SMOOTH:
        # Laplacian smoothing: move toward the centroid of one-ring neighbours.
        rings = mesh.one_ring_neighbours()
        disp = np.zeros((in_radius.size, 3), dtype=np.float64)
        for idx, vi in enumerate(in_radius):
            nb = rings[int(vi)]
            if not nb:
                continue
            nb_arr = np.array(list(nb), dtype=np.intp)
            centroid = positions[nb_arr].mean(axis=0)   # (3,)
            disp[idx] = (centroid - positions[vi]) * weights[idx] * s

    elif kind == BrushKind.INFLATE:
        # Push along per-vertex normal.
        # Mudbox/ZBrush inflate: normal-direction displacement with falloff.
        normals = mesh.vertex_normals()                       # (V, 3)
        vn = normals[in_radius]                              # (K, 3)
        disp = vn * (weights * s)[:, np.newaxis]             # (K, 3)

    elif kind == BrushKind.CREASE:
        # Pinch vertices toward the stroke axis (sharpens edge along axis).
        # For each vertex: compute offset from center, project out the axis
        # component, leaving the perpendicular component; scale the
        # perpendicular component toward zero by w * strength.
        if stroke.direction is None:
            # No axis → no-op
            return MeshDelta(
                vertex_indices=np.array([], dtype=np.intp),
                deltas=np.zeros((0, 3), dtype=np.float64),
            )
        axis = np.asarray(stroke.direction, dtype=np.float64)
        anorm = np.linalg.norm(axis)
        if anorm < 1e-12:
            return MeshDelta(
                vertex_indices=np.array([], dtype=np.intp),
                deltas=np.zeros((0, 3), dtype=np.float64),
            )
        axis = axis / anorm

        off_in = offsets[in_radius]                          # (K, 3)
        # Axis component: (off · axis) * axis
        proj_len = off_in.dot(axis)                          # (K,)
        along = proj_len[:, np.newaxis] * axis[np.newaxis, :]  # (K, 3)
        perp = off_in - along                                # (K, 3) perpendicular part

        # Displacement: move vertex so that its perpendicular offset shrinks by
        # weight * strength (i.e., delta = -perp * w * s)
        disp = -perp * (weights * s)[:, np.newaxis]          # (K, 3)

    elif kind == BrushKind.PINCH:
        # Pull vertex toward brush center.
        # delta = (center - v) * w * strength  = -offset * w * s
        off_in = offsets[in_radius]                          # (K, 3)
        disp = -off_in * (weights * s)[:, np.newaxis]        # (K, 3)

    else:
        raise ValueError(f"Unknown BrushKind: {kind!r}")

    # Apply displacement in-place and record delta
    mesh.positions[in_radius] += disp
    mesh._invalidate_cache()

    return MeshDelta(vertex_indices=in_radius.copy(), deltas=disp.copy())


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def revert_delta(mesh: SculptMesh, delta: MeshDelta) -> None:
    """Undo a previous apply_brush by subtracting the recorded delta.

    Parameters
    ----------
    mesh:
        The mesh that was modified by the corresponding apply_brush call.
        positions is mutated in-place.
    delta:
        The MeshDelta returned by apply_brush.
    """
    if delta.vertex_indices.size == 0:
        return
    mesh.positions[delta.vertex_indices] -= delta.deltas
    mesh._invalidate_cache()
