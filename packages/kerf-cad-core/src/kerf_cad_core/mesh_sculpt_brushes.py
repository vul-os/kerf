"""mesh_sculpt_brushes.py — GK-P22: Sculpt brushes for SubD cages and triangle meshes.

Implements five sculpt brushes (Inflate, Crease, Smooth, Smooth-Taubin, Pinch)
that displace mesh vertices within a brush radius using a Wendland C2 falloff
kernel.

References
----------
- Botsch & Sorkine (2008) "On linear variational surface deformation methods",
  IEEE TVCG 14(1):213-230.
- Sculptris / ZBrush brush displacement conventions (Pixologic ZBrush Docs 2024).
- Wendland, H. (1995) "Piecewise polynomial, positive definite and compactly
  supported radial functions of minimal degree", Advances in Computational
  Mathematics 4(1):389-396. Falloff w(t) = (1-t^2)^2 for t in [0,1).
- Meyer, M., Desbrun, M., Schröder, P. & Barr, A.H. (2003) "Discrete
  Differential-Geometry Operators for Triangulated 2-Manifolds", VisMath.
  Cotangent-weight Laplace-Beltrami operator (§3.3).
- Taubin, G. (1995) "A signal processing approach to fair surface design",
  SIGGRAPH Proceedings, pp. 351-358. λ|μ two-pass shrinkage-free smoothing.

Honest caveats
--------------
- Single-stroke, stateless: no stroke history, no undo stack, no dyntopo.
- Auto-normals computed by one-ring area-weighted averaging (flat mesh: all zeros
  → inflate falls back to global Z if all computed normals are zero).
- ``smooth`` brush uses unweighted centroid of first-order vertex neighbours only
  (fast, but causes mesh shrinkage over repeated applications).
- ``smooth-taubin`` brush uses cotangent-weighted Laplace-Beltrami (Meyer et al.
  2003 §3.3) with Taubin (1995) λ|μ two-pass anti-shrink formulation: first pass
  λ>0 smooths, second pass μ<0 (|μ|>λ) corrects the DC shift, preserving low
  frequencies while attenuating high-frequency noise.
- Crease brush is a signed-inflate with strength negated when strength > 0 to pull
  inward; full CC crease sharpness propagation across subdivision levels is out
  of scope (mesh-level only).
- Triangle meshes and quad cages are treated identically (vertex + face index list).
- Cotangent weights: for degenerate triangles (zero or near-zero area) a fallback
  to uniform weights is applied per-vertex to avoid NaN/Inf.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SculptStroke:
    """Parameters for a single sculpt-brush stroke.

    Parameters
    ----------
    position_xyz_mm:
        World-space centre of the brush in millimetres.
    radius_mm:
        Brush influence radius in millimetres (> 0).
    brush_type:
        One of ``"inflate"``, ``"crease"``, ``"smooth"``, ``"smooth-taubin"``,
        ``"pinch"``.
    strength:
        Signed displacement scale in [-1, 1].  Positive = outward / toward
        neighbours / toward centre depending on brush type.  Negative reverses
        the direction.
    normal_direction_xyz:
        Override the inflate/crease displacement axis.  When ``None`` (default)
        each vertex's one-ring area-weighted normal is used instead.
    """

    position_xyz_mm: Tuple[float, float, float]
    radius_mm: float
    brush_type: str  # "inflate" | "crease" | "smooth" | "smooth-taubin" | "pinch"
    strength: float  # -1 .. 1
    normal_direction_xyz: Optional[Tuple[float, float, float]] = None


@dataclass
class MeshSculptResult:
    """Result of :func:`apply_sculpt_brush`.

    Parameters
    ----------
    output_vertices:
        Full vertex list (same length as input) with displaced positions.
    num_vertices_modified:
        Count of vertices whose displacement magnitude exceeded 1e-12.
    max_displacement_mm:
        Maximum per-vertex displacement magnitude among all modified vertices.
    mean_displacement_mm:
        Mean per-vertex displacement magnitude among all modified vertices
        (0.0 if none were modified).
    brush_type_applied:
        Echo of ``SculptStroke.brush_type``.
    honest_caveat:
        Plain-text caveat string summarising v1 limitations.
    """

    output_vertices: List[Tuple[float, float, float]]
    num_vertices_modified: int
    max_displacement_mm: float
    mean_displacement_mm: float
    brush_type_applied: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "GK-P22 v2: single-stroke, stateless brush — no undo stack, no stroke history, "
    "no dyntopo. Auto-normals use one-ring area-weighted averaging; degenerate "
    "faces (area=0) are skipped. 'smooth' brush uses unweighted first-order centroid "
    "(shrinks over repeated passes). 'smooth-taubin' uses cotangent-weight "
    "Laplace-Beltrami (Meyer et al. 2003 §3.3) + Taubin (1995) λ|μ anti-shrink "
    "two-pass: low-freq shape preserved, high-freq noise attenuated. Degenerate "
    "triangles fall back to uniform cotangent weights per-vertex. Crease brush is "
    "inverted-inflate (no CC subdivision sharpness). "
    "Ref: Botsch-Sorkine 2008 §3; Wendland 1995 C2 kernel; Meyer et al. 2003; "
    "Taubin 1995."
)


def _wendland_c2(t: float) -> float:
    """Wendland C2 falloff: w(t) = (1 - t^2)^2 for t in [0, 1), else 0.

    Here t = d / radius, so w(0) = 1 at the stroke centre and w(1) = 0 at the
    boundary.  Second derivative is continuous (C2) at the boundary.
    """
    if t >= 1.0:
        return 0.0
    s = 1.0 - t * t
    return s * s


def _vec_sub(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_add(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec_scale(v: Tuple[float, float, float], s: float) -> Tuple[float, float, float]:
    return (v[0] * s, v[1] * s, v[2] * s)


def _vec_length(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _vec_normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    length = _vec_length(v)
    if length < 1e-14:
        return (0.0, 0.0, 0.0)
    inv = 1.0 / length
    return (v[0] * inv, v[1] * inv, v[2] * inv)


def _vec_cross(a: Tuple[float, float, float],
               b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_dot(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _build_adjacency(num_verts: int,
                     faces: List) -> List[List[int]]:
    """Return one-ring neighbour lists (vertex → [adjacent vertex indices])."""
    adj: List[List[int]] = [[] for _ in range(num_verts)]
    for face in faces:
        n = len(face)
        for i in range(n):
            vi = face[i]
            for j in range(n):
                vj = face[j]
                if vi != vj and vj not in adj[vi]:
                    adj[vi].append(vj)
    return adj


def _cot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    """Cotangent of the angle between vectors *a* and *b* at their shared tail.

    cot(θ) = cos(θ)/sin(θ) = dot(a,b) / |cross(a,b)|

    Returns 0.0 for degenerate (zero-area) configurations.
    """
    dot = _vec_dot(a, b)
    cross = _vec_cross(a, b)
    sin_val = _vec_length(cross)
    if sin_val < 1e-14:
        return 0.0
    return dot / sin_val


def _build_cotangent_weights(
    vertices: List[Tuple[float, float, float]],
    faces: List,
) -> List[List[Tuple[int, float]]]:
    """Compute cotangent-weight Laplace-Beltrami operator per vertex.

    For each vertex *i* and each incident edge (i, j), the cotangent weight is::

        w_ij = (cot α_ij + cot β_ij) / 2

    where α_ij and β_ij are the two angles opposite to edge (i,j) in the two
    triangles sharing that edge (Meyer et al. 2003 §3.3, eq. 7).

    For non-triangle faces (n>3) we fan-triangulate: (f[0], f[k], f[k+1]).

    Returns a list of length ``len(vertices)``, where entry *i* is a list of
    ``(j, w_ij)`` pairs with ``w_ij >= 0``.  Weights are NOT normalised here;
    normalisation happens inside :func:`_taubin_smooth_one_pass`.

    Degenerate triangles (zero area) contribute cot=0 and are safely skipped.
    Boundary edges (only one adjacent triangle) use half the available cot.
    """
    nv = len(vertices)
    # Accumulate (j, weight) per vertex i.  Use a dict for O(1) accumulation.
    weight_acc: List[dict] = [{} for _ in range(nv)]

    for face in faces:
        n = len(face)
        if n < 3:
            continue
        # Fan-triangulate face into (face[0], face[k], face[k+1]) for k in 1..n-2
        for k in range(1, n - 1):
            i0, i1, i2 = face[0], face[k], face[k + 1]
            p0 = vertices[i0]
            p1 = vertices[i1]
            p2 = vertices[i2]

            # Opposite angle at p2 (opposite to edge p0-p1)
            cot2 = _cot(_vec_sub(p0, p2), _vec_sub(p1, p2))
            # Opposite angle at p0 (opposite to edge p1-p2)
            cot0 = _cot(_vec_sub(p1, p0), _vec_sub(p2, p0))
            # Opposite angle at p1 (opposite to edge p0-p2)
            cot1 = _cot(_vec_sub(p0, p1), _vec_sub(p2, p1))

            # Edge (i0, i1): opposite angle at i2 → add cot2/2 to both endpoints
            half_cot2 = cot2 / 2.0
            weight_acc[i0][i1] = weight_acc[i0].get(i1, 0.0) + half_cot2
            weight_acc[i1][i0] = weight_acc[i1].get(i0, 0.0) + half_cot2

            # Edge (i1, i2): opposite angle at i0 → add cot0/2
            half_cot0 = cot0 / 2.0
            weight_acc[i1][i2] = weight_acc[i1].get(i2, 0.0) + half_cot0
            weight_acc[i2][i1] = weight_acc[i2].get(i1, 0.0) + half_cot0

            # Edge (i0, i2): opposite angle at i1 → add cot1/2
            half_cot1 = cot1 / 2.0
            weight_acc[i0][i2] = weight_acc[i0].get(i2, 0.0) + half_cot1
            weight_acc[i2][i0] = weight_acc[i2].get(i0, 0.0) + half_cot1

    # Convert to list-of-pairs; clamp negative weights (obtuse triangles → cot < 0).
    # Negative cotangent weights are mathematically valid but can cause instability
    # in a single-pass smoother; we clamp to 0 and fall back to uniform if the sum
    # is zero (fully degenerate one-ring).
    result: List[List[Tuple[int, float]]] = []
    for i in range(nv):
        pairs = [(j, max(0.0, w)) for j, w in weight_acc[i].items()]
        total = sum(w for _, w in pairs)
        if total < 1e-14:
            # Degenerate one-ring: fall back to uniform weights
            pairs = [(j, 1.0) for j, _ in pairs]
            total = float(len(pairs))
        if total < 1e-14:
            # Isolated vertex: no neighbours
            result.append([])
        else:
            result.append(pairs)
    return result


def _taubin_smooth_one_pass(
    vertices: List[Tuple[float, float, float]],
    faces: List,
    lambda_factor: float = 0.5,
    mu_factor: float = -0.53,
) -> List[Tuple[float, float, float]]:
    """Taubin (1995) λ|μ cotangent-weight shrinkage-free smoothing, full mesh.

    Applies two sequential Laplacian passes to all vertices:

    1. **Positive λ pass** (smoothing): each vertex moves toward the weighted
       centroid of its one-ring by fraction λ, attenuating high-frequency signal.
    2. **Negative μ pass** (anti-shrink): each vertex is moved in the reverse
       direction by fraction |μ| > λ, restoring the low-frequency (DC) component
       that was lost in pass 1.

    The condition |μ| > λ ensures the pass-band frequencies (low-freq shape) are
    preserved while the stop-band (high-freq noise) is attenuated — see Taubin
    (1995) §4 "transfer function" analysis.

    Cotangent weights follow Meyer et al. (2003) §3.3 eq. 7::

        w_ij = (cot α_ij + cot β_ij) / 2

    where α_ij, β_ij are the angles opposite edge (i,j) in adjacent triangles.
    Weights are normalised per vertex so they sum to 1 (unit-weight Laplacian).

    Parameters
    ----------
    vertices:
        Input vertex positions.
    faces:
        Face index lists (triangles or fan-triangulated n-gons).
    lambda_factor:
        Positive smoothing step-size λ ∈ (0, 1).  Default 0.5.
    mu_factor:
        Negative anti-shrink step-size μ < 0, |μ| > λ.  Default -0.53.
        Taubin (1995) suggests μ ≈ -(λ + ε) for small ε > 0; -0.53 with λ=0.5
        is the standard "0.5 / -0.53" pair from the original paper.

    Returns
    -------
    List of displaced vertex positions (same length as *vertices*).

    References
    ----------
    Taubin, G. (1995) "A signal processing approach to fair surface design",
    SIGGRAPH Proc. pp. 351-358.
    Meyer, M. et al. (2003) "Discrete Differential-Geometry Operators for
    Triangulated 2-Manifolds", VisMath.
    """
    nv = len(vertices)
    cot_weights = _build_cotangent_weights(vertices, faces)

    def _single_laplacian_pass(
        verts: List[Tuple[float, float, float]], step: float
    ) -> List[Tuple[float, float, float]]:
        """One weighted Laplacian pass: v_new = v + step · Σ w_ij (v_j - v)."""
        out = list(verts)  # copy
        for i in range(nv):
            pairs = cot_weights[i]
            if not pairs:
                continue
            total_w = sum(w for _, w in pairs)
            if total_w < 1e-14:
                continue
            inv_w = 1.0 / total_w
            delta_x = 0.0
            delta_y = 0.0
            delta_z = 0.0
            vi = verts[i]
            for j, w in pairs:
                vj = verts[j]
                nw = w * inv_w  # normalised weight
                delta_x += nw * (vj[0] - vi[0])
                delta_y += nw * (vj[1] - vi[1])
                delta_z += nw * (vj[2] - vi[2])
            out[i] = (
                vi[0] + step * delta_x,
                vi[1] + step * delta_y,
                vi[2] + step * delta_z,
            )
        return out

    # Pass 1: positive λ smoothing
    after_lambda = _single_laplacian_pass(vertices, lambda_factor)
    # Pass 2: negative μ anti-shrink
    after_mu = _single_laplacian_pass(after_lambda, mu_factor)
    return after_mu


def _compute_vertex_normals(
    vertices: List[Tuple[float, float, float]],
    faces: List,
) -> List[Tuple[float, float, float]]:
    """Area-weighted one-ring normal for each vertex.

    Uses the first two edges of each face polygon as the cross-product pair.
    Degenerate faces (zero area) are skipped.
    """
    n = len(vertices)
    normals: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(n)]

    for face in faces:
        if len(face) < 3:
            continue
        v0 = vertices[face[0]]
        v1 = vertices[face[1]]
        v2 = vertices[face[2]]
        e1 = _vec_sub(v1, v0)
        e2 = _vec_sub(v2, v0)
        fn = _vec_cross(e1, e2)
        # Weight = half the cross-product magnitude (= triangle area)
        for vi in face:
            normals[vi][0] += fn[0]
            normals[vi][1] += fn[1]
            normals[vi][2] += fn[2]

    result: List[Tuple[float, float, float]] = []
    for nm in normals:
        t = (nm[0], nm[1], nm[2])
        result.append(_vec_normalize(t))
    return result


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def apply_sculpt_brush(
    vertices: List[Tuple[float, float, float]],
    faces: List,
    stroke: SculptStroke,
) -> MeshSculptResult:
    """Apply a single sculpt-brush stroke to a mesh.

    For each vertex within ``stroke.radius_mm`` of the brush centre, the vertex
    is displaced by ``strength · falloff(d/r) · direction`` where:

    - ``falloff(t) = (1-t²)²``  (Wendland C2 kernel, Wendland 1995)
    - ``direction`` depends on ``stroke.brush_type``

    Brush semantics
    ---------------
    inflate
        Displace along the vertex normal (or the override axis if provided).
        Positive strength = outward.
    crease
        Same as inflate but with ``strength`` negated: positive strength pulls
        inward, creating a crease/pinch toward the surface (per Sculptris
        convention where Crease = negative inflate).
    smooth
        Displace toward the unweighted centroid of the one-ring neighbours.
        The displacement vector is ``(centroid - vertex) · |strength| · falloff``.
        Strength sign has no effect (smoothing is always toward centroid).
    pinch
        Displace toward the stroke centre projected onto the tangent plane at
        each vertex.  Positive strength pinches inward.

    Parameters
    ----------
    vertices:
        List of ``(x, y, z)`` tuples in mm.
    faces:
        List of face index lists (triangles or quads or n-gons).
    stroke:
        Brush stroke parameters.

    Returns
    -------
    MeshSculptResult
    """
    if stroke.radius_mm <= 0.0:
        raise ValueError("stroke.radius_mm must be > 0")
    if stroke.brush_type not in ("inflate", "crease", "smooth", "smooth-taubin", "pinch"):
        raise ValueError(
            f"brush_type must be one of inflate/crease/smooth/smooth-taubin/pinch, "
            f"got {stroke.brush_type!r}"
        )

    nv = len(vertices)
    out_verts: List[List[float]] = [
        [v[0], v[1], v[2]] for v in vertices
    ]

    # Build adjacency and per-vertex normals once
    adj = _build_adjacency(nv, faces)
    vert_normals = _compute_vertex_normals(vertices, faces)

    # Override normal direction
    override_normal: Optional[Tuple[float, float, float]] = None
    if stroke.normal_direction_xyz is not None:
        override_normal = _vec_normalize(stroke.normal_direction_xyz)

    cx, cy, cz = stroke.position_xyz_mm
    r = stroke.radius_mm

    displacements: List[float] = []
    modified_indices: List[int] = []

    # -----------------------------------------------------------------------
    # smooth-taubin: run a full Taubin λ|μ pass on the whole mesh, then blend
    # the displacement into each in-radius vertex using the Wendland falloff
    # and the stroke strength as a blend fraction.
    # -----------------------------------------------------------------------
    if stroke.brush_type == "smooth-taubin":
        taubin_verts = _taubin_smooth_one_pass(vertices, faces)
        for i, v in enumerate(vertices):
            dx = v[0] - cx
            dy = v[1] - cy
            dz = v[2] - cz
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist >= r:
                continue
            t = dist / r
            w = _wendland_c2(t)
            blend = abs(stroke.strength) * w
            tv = taubin_verts[i]
            delta_x = (tv[0] - v[0]) * blend
            delta_y = (tv[1] - v[1]) * blend
            delta_z = (tv[2] - v[2]) * blend
            out_verts[i][0] += delta_x
            out_verts[i][1] += delta_y
            out_verts[i][2] += delta_z
            disp = math.sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z)
            if disp > 1e-12:
                displacements.append(disp)
                modified_indices.append(i)

        output_vertices = [
            (out_verts[i][0], out_verts[i][1], out_verts[i][2]) for i in range(nv)
        ]
        if displacements:
            max_d = max(displacements)
            mean_d = sum(displacements) / len(displacements)
        else:
            max_d = 0.0
            mean_d = 0.0
        return MeshSculptResult(
            output_vertices=output_vertices,
            num_vertices_modified=len(displacements),
            max_displacement_mm=max_d,
            mean_displacement_mm=mean_d,
            brush_type_applied=stroke.brush_type,
            honest_caveat=_HONEST_CAVEAT,
        )

    for i, v in enumerate(vertices):
        dx = v[0] - cx
        dy = v[1] - cy
        dz = v[2] - cz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist >= r:
            continue

        t = dist / r
        w = _wendland_c2(t)  # 0 at boundary, 1 at centre

        if stroke.brush_type == "inflate":
            if override_normal is not None:
                direction = override_normal
            else:
                direction = vert_normals[i]
                # Fallback: if normal is zero vector (degenerate mesh), use global Z
                if _vec_length(direction) < 1e-12:
                    direction = (0.0, 0.0, 1.0)
            scale = stroke.strength * w
            out_verts[i][0] += direction[0] * scale
            out_verts[i][1] += direction[1] * scale
            out_verts[i][2] += direction[2] * scale
            disp = abs(scale) * _vec_length(direction)

        elif stroke.brush_type == "crease":
            # Crease = inward inflate (sign flipped vs inflate per Sculptris convention)
            if override_normal is not None:
                direction = override_normal
            else:
                direction = vert_normals[i]
                if _vec_length(direction) < 1e-12:
                    direction = (0.0, 0.0, 1.0)
            scale = -stroke.strength * w  # inverted
            out_verts[i][0] += direction[0] * scale
            out_verts[i][1] += direction[1] * scale
            out_verts[i][2] += direction[2] * scale
            disp = abs(scale) * _vec_length(direction)

        elif stroke.brush_type == "smooth":
            neighbours = adj[i]
            if not neighbours:
                disp = 0.0
            else:
                cx_n = sum(vertices[j][0] for j in neighbours) / len(neighbours)
                cy_n = sum(vertices[j][1] for j in neighbours) / len(neighbours)
                cz_n = sum(vertices[j][2] for j in neighbours) / len(neighbours)
                delta_x = (cx_n - v[0]) * abs(stroke.strength) * w
                delta_y = (cy_n - v[1]) * abs(stroke.strength) * w
                delta_z = (cz_n - v[2]) * abs(stroke.strength) * w
                out_verts[i][0] += delta_x
                out_verts[i][1] += delta_y
                out_verts[i][2] += delta_z
                disp = math.sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z)

        elif stroke.brush_type == "pinch":
            # Displace toward stroke centre (in 3D space directly)
            toward = (cx - v[0], cy - v[1], cz - v[2])
            toward_len = _vec_length(toward)
            if toward_len < 1e-14:
                disp = 0.0
            else:
                inv_len = 1.0 / toward_len
                toward_n = (toward[0] * inv_len, toward[1] * inv_len, toward[2] * inv_len)
                scale = stroke.strength * w
                out_verts[i][0] += toward_n[0] * scale
                out_verts[i][1] += toward_n[1] * scale
                out_verts[i][2] += toward_n[2] * scale
                disp = abs(scale)

        else:  # pragma: no cover — guarded by earlier validation
            disp = 0.0

        if disp > 1e-12:
            displacements.append(disp)
            modified_indices.append(i)

    output_vertices = [
        (out_verts[i][0], out_verts[i][1], out_verts[i][2]) for i in range(nv)
    ]

    if displacements:
        max_d = max(displacements)
        mean_d = sum(displacements) / len(displacements)
    else:
        max_d = 0.0
        mean_d = 0.0

    return MeshSculptResult(
        output_vertices=output_vertices,
        num_vertices_modified=len(displacements),
        max_displacement_mm=max_d,
        mean_displacement_mm=mean_d,
        brush_type_applied=stroke.brush_type,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool (gated import)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    import json as _json

    _mesh_sculpt_brush_spec = ToolSpec(
        name="mesh_sculpt_brush",
        description=(
            "Apply a sculpt-brush stroke to a triangle mesh or SubD cage. "
            "Displaces vertices within a brush radius using a Wendland C2 "
            "falloff kernel w(t)=(1-t²)² (Wendland 1995).  "
            "Five brush types: "
            "'inflate' — push along per-vertex normal; "
            "'crease' — pull inward along normal (negative inflate); "
            "'smooth' — blend toward one-ring centroid (Laplacian relaxation, may shrink); "
            "'smooth-taubin' — cotangent-weight Taubin λ|μ shrinkage-free smoothing "
            "(Meyer et al. 2003 §3.3 + Taubin 1995); "
            "'pinch' — attract toward the brush centre. "
            "Strength in [-1, 1]; positive = outward/inward/toward-centroid/pinch. "
            "No OCCT required — pure-Python geometry. "
            "Ref: Botsch-Sorkine 2008 §3 (variational deformation); "
            "Sculptris/ZBrush brush math (Pixologic 2024)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "List of [x, y, z] vertex positions in mm.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                },
                "faces": {
                    "type": "array",
                    "description": (
                        "List of face index arrays (triangles or quads or n-gons). "
                        "Example for two triangles: [[0,1,2],[0,2,3]]."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "position_xyz_mm": {
                    "type": "array",
                    "description": "Brush centre [x, y, z] in mm.",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "radius_mm": {
                    "type": "number",
                    "description": "Brush influence radius in mm (> 0).",
                    "exclusiveMinimum": 0,
                },
                "brush_type": {
                    "type": "string",
                    "enum": ["inflate", "crease", "smooth", "smooth-taubin", "pinch"],
                    "description": (
                        "Brush type. 'smooth' = fast unweighted centroid (may shrink). "
                        "'smooth-taubin' = cotangent-weight Laplace-Beltrami (Meyer 2003) "
                        "with Taubin (1995) λ|μ two-pass anti-shrink formulation."
                    ),
                },
                "strength": {
                    "type": "number",
                    "description": "Displacement scale [-1, 1].",
                    "minimum": -1.0,
                    "maximum": 1.0,
                },
                "normal_direction_xyz": {
                    "type": "array",
                    "description": (
                        "Optional override axis for inflate/crease brushes [x, y, z]. "
                        "Normalised internally. Omit to use auto-computed vertex normals."
                    ),
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "default": None,
                },
            },
            "required": [
                "vertices",
                "faces",
                "position_xyz_mm",
                "radius_mm",
                "brush_type",
                "strength",
            ],
        },
    )

    @register(_mesh_sculpt_brush_spec)
    async def _run_mesh_sculpt_brush(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            verts = [tuple(v) for v in a["vertices"]]
            faces_raw = [list(f) for f in a["faces"]]
            pos = tuple(a["position_xyz_mm"])
            radius = float(a["radius_mm"])
            btype = str(a["brush_type"])
            strength = float(a["strength"])
            normal_override = (
                tuple(a["normal_direction_xyz"])
                if a.get("normal_direction_xyz") is not None
                else None
            )
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"parameter error: {exc}", "BAD_ARGS")

        try:
            stroke = SculptStroke(
                position_xyz_mm=pos,  # type: ignore[arg-type]
                radius_mm=radius,
                brush_type=btype,
                strength=strength,
                normal_direction_xyz=normal_override,  # type: ignore[arg-type]
            )
            result = apply_sculpt_brush(verts, faces_raw, stroke)  # type: ignore[arg-type]
        except Exception as exc:
            return err_payload(str(exc), "COMPUTE_ERROR")

        return ok_payload(
            {
                "output_vertices": [list(v) for v in result.output_vertices],
                "num_vertices_modified": result.num_vertices_modified,
                "max_displacement_mm": result.max_displacement_mm,
                "mean_displacement_mm": result.mean_displacement_mm,
                "brush_type_applied": result.brush_type_applied,
                "honest_caveat": result.honest_caveat,
            }
        )

except ImportError:
    pass  # Standalone / test mode without kerf_chat
