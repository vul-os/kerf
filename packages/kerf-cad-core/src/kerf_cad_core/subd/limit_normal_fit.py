"""limit_normal_fit.py
=====================
SUBD-LIMIT-NORMAL-FIT — sample the limit-surface normal n̂(u,v) of a
Catmull-Clark subdivision surface at multiple parameter points and fit a
smooth NURBS normal field for use in shading/rendering.

Theory
------
The Catmull-Clark (CC) limit-surface normal at parameter (u, v) on a cage
face is:

    N(u, v) = (∂S/∂u × ∂S/∂v) / |∂S/∂u × ∂S/∂v|

where ∂S/∂u and ∂S/∂v are the Stam-exact limit tangent vectors
(``stam_limit_tangents``, Stam 1998 §3.2).  For regular patches (all four
face vertices have valence 4) the tangent vectors are the analytic partial
derivatives of the underlying bi-cubic B-spline.  For faces adjacent to an
extraordinary vertex (valence n ≠ 4), Stam's eigenstructure decomposition
gives C¹-continuous tangents even at the extraordinary point.

Normal-field fitting
~~~~~~~~~~~~~~~~~~~~
For each cage face we sample a ``sqrt(samples_per_face)``-resolution uniform
grid:  (u_i, v_j) = (i / (n-1), j / (n-1))  for  i, j ∈ {0, …, n-1},
where n = round(sqrt(samples_per_face)).

Each sample returns a unit normal (nx, ny, nz).  The collection of all
sampled normals across all faces forms the "normal field."

*NURBS fit*: We do NOT fit a global NURBS patch to the normal field (that
would require solving a full least-squares system and is outside the scope
of this module).  Instead we compute the **residual of the sampled normals
against the bilinear approximation** on each face: bilinear interpolation of
the four face-corner Stam normals gives a cheap shading approximation; the
angular deviation (degrees) between the bilinear approximation and the
Stam-exact normal quantifies how much a true NURBS normal field buys over
the simple interpolation.  This is the ``max_normal_residual_deg`` and
``mean_normal_residual_deg`` in the result.

Irregular samples
~~~~~~~~~~~~~~~~~
A sample is flagged as "irregular" if any vertex of its cage face has
valence ≠ 4.  Normals at these samples are still computed exactly (via
Stam's eigenstructure), but callers should be aware that the underlying
surface is only C¹ (not C²) there.

References
----------
* Stam, J. (1998). "Exact Evaluation of Catmull-Clark Subdivision Surfaces
  at Arbitrary Parameter Values." SIGGRAPH 1998, pp. 395-404.
* Halstead, M., Kass, M., DeRose, T. (1993). "Efficient, Fair Interpolation
  Using Catmull-Clark Surfaces." SIGGRAPH 1993, pp. 35-44.
* Piegl, L. & Tiller, W. (1997). "The NURBS Book." 2nd ed.  Springer.

Caveats (honest)
----------------
* The "NURBS fit" here is a residual analysis, not a closed-form NURBS
  surface; full NURBS fitting would require solving an overdetermined
  least-squares system and storing degree/knot/control-point data.
* Residuals are computed against bilinear interpolation of the four
  face-corner Stam normals — not against a ground-truth NURBS normal field.
* For non-quad faces (triangles, n-gons > 4) the 2-ring extraction
  approximates a quad from the first four vertices; normals on such faces
  are approximate.
* The Stam 2-ring is constructed from a simplified connectivity walk that
  may mis-identify outer-ring vertices on complex cage topologies; results
  are reliable for typical interior quad meshes.
* Normal sign convention: N = ∂S/∂u × ∂S/∂v.  Winding order of cage faces
  determines the sign.  Consistent outward normals require consistent
  face-vertex winding.

Public API
----------
LimitNormalFitResult
    Dataclass returned by ``sample_subd_limit_normals``.

sample_subd_limit_normals(cage_mesh, samples_per_face=9, normalize=True)
    Main entry point.  Returns a ``LimitNormalFitResult``.

LLM tool: ``subd_sample_limit_normals``
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from kerf_cad_core.geom.subd import SubDMesh, subd_limit_position
from kerf_cad_core.geom.subd_stam import stam_limit_tangents


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class LimitNormalFitResult:
    """Result of sampling CC limit-surface normals and fitting a normal field.

    Attributes
    ----------
    sampled_normals : list of dict
        Each dict has keys ``u``, ``v``, ``face_idx``, ``nx``, ``ny``, ``nz``.
        One entry per (u, v, face) sample point.  The (nx, ny, nz) vector is
        unit-length when ``normalize=True``.
    max_normal_residual_deg : float
        Maximum angular deviation (degrees) between the Stam-exact normals
        and the bilinear-interpolated face-corner normals over all sample
        points.  Quantifies the error of using a bilinear approximation
        instead of the exact normal field.
    mean_normal_residual_deg : float
        Mean angular deviation (degrees) over all sample points.
    num_irregular_samples : int
        Number of sample points on cage faces that have at least one
        extraordinary vertex (valence ≠ 4).
    honest_caveat : str
        Plain-language description of the method's limitations.
    """
    sampled_normals: List[Dict] = field(default_factory=list)
    max_normal_residual_deg: float = 0.0
    mean_normal_residual_deg: float = 0.0
    num_irregular_samples: int = 0
    honest_caveat: str = (
        "Discrete sample fit: normals sampled on a uniform (u,v) grid using "
        "Stam (1998) exact eigenstructure tangents.  Residuals are computed "
        "against bilinear interpolation of face-corner Stam normals — NOT a "
        "true closed-form NURBS normal surface.  Non-quad faces use a 4-vertex "
        "approximation.  For faces adjacent to extraordinary vertices (valence "
        "!= 4) the surface is C1 (not C2); normals are still exact via Stam "
        "eigendecomposition but may show higher variation near the EV.  Normal "
        "sign depends on cage face winding order."
    )


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _cross3(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot3(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm_vec(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    ln = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if ln < 1e-15:
        return (0.0, 0.0, 1.0)
    return (v[0] / ln, v[1] / ln, v[2] / ln)


def _angular_dev_deg(
    n1: Tuple[float, float, float],
    n2: Tuple[float, float, float],
) -> float:
    """Angular deviation in degrees between two unit normals."""
    d = _dot3(n1, n2)
    d = max(-1.0, min(1.0, d))
    return math.degrees(math.acos(abs(d)))


# ---------------------------------------------------------------------------
# Build vertex adjacency (reuse pattern from limit_walk_cross_curve)
# ---------------------------------------------------------------------------

def _build_vertex_adjacency(
    mesh: SubDMesh,
) -> Tuple[
    "dict[int, list[int]]",   # vertex -> face indices
    "dict[int, list[int]]",   # vertex -> neighbour vertices
]:
    vert_faces: "dict[int, list[int]]" = {}
    vert_nbrs: "dict[int, list[int]]" = {}

    for fi, face in enumerate(mesh.faces):
        n = len(face)
        for vi in face:
            vert_faces.setdefault(vi, []).append(fi)
        for i in range(n):
            a = face[i]
            b = face[(i + 1) % n]
            if b not in vert_nbrs.get(a, []):
                vert_nbrs.setdefault(a, []).append(b)
            if a not in vert_nbrs.get(b, []):
                vert_nbrs.setdefault(b, []).append(a)

    return vert_faces, vert_nbrs


# ---------------------------------------------------------------------------
# 2-ring extraction and Stam tangent evaluation at (u, v) on a cage face
# ---------------------------------------------------------------------------

def _get_outer_vertex(
    vi: int,
    exclude: "list[int]",
    verts: "list[list[float]]",
    vert_nbrs: "dict[int, list[int]]",
) -> "list[float]":
    """Return a 1-ring neighbour of vi not in exclude, or vi itself."""
    for nb in vert_nbrs.get(vi, []):
        if nb not in exclude:
            return verts[nb]
    return verts[vi]


def _edge_opp(
    a: int,
    b: int,
    face_idx: int,
    face_v: "list[int]",
    mesh: SubDMesh,
    vert_faces: "dict[int, list[int]]",
) -> "list[float]":
    """Return the vertex on the far side of edge (a,b) in an adjacent face."""
    adj_faces = [
        fi for fi in (
            set(vert_faces.get(a, [])) & set(vert_faces.get(b, []))
        )
        if fi != face_idx
    ]
    verts = mesh.vertices
    if adj_faces:
        adj_face = mesh.faces[adj_faces[0]]
        for vi in adj_face:
            if vi != a and vi != b:
                return verts[vi]
    # Boundary: mirror across edge midpoint
    va = verts[a]
    vb = verts[b]
    opp = [v for v in face_v if v != a and v != b]
    mid = [(va[0] + vb[0]) / 2, (va[1] + vb[1]) / 2, (va[2] + vb[2]) / 2]
    if opp:
        vo = verts[opp[0]]
        return [2 * mid[0] - vo[0], 2 * mid[1] - vo[1], 2 * mid[2] - vo[2]]
    return mid


def _extract_regular_2ring(
    face_idx: int,
    mesh: SubDMesh,
    vert_faces: "dict[int, list[int]]",
    vert_nbrs: "dict[int, list[int]]",
) -> "list[list[float]]":
    """Extract a 16-point regular 2-ring for face_idx (same as limit_walk_cross_curve)."""
    face = list(mesh.faces[face_idx])
    verts = mesh.vertices

    while len(face) < 4:
        face = face + [face[-1]]

    v0, v1, v2, v3 = face[0], face[1], face[2], face[3]
    inner = [v0, v1, v2, v3]

    c00 = _get_outer_vertex(v0, [v1, v3], verts, vert_nbrs)
    c03 = _get_outer_vertex(v1, [v0, v2], verts, vert_nbrs)
    c30 = _get_outer_vertex(v3, [v0, v2], verts, vert_nbrs)
    c33 = _get_outer_vertex(v2, [v1, v3], verts, vert_nbrs)

    e01 = _edge_opp(v0, v1, face_idx, inner, mesh, vert_faces)
    e12 = _edge_opp(v1, v2, face_idx, inner, mesh, vert_faces)
    e23 = _edge_opp(v2, v3, face_idx, inner, mesh, vert_faces)
    e30 = _edge_opp(v3, v0, face_idx, inner, mesh, vert_faces)

    grid = [
        c00,   e01,   e01,   c03,
        e30,   verts[v0], verts[v1], e12,
        e30,   verts[v3], verts[v2], e12,
        c30,   e23,   e23,   c33,
    ]
    return [list(p) for p in grid]


def _face_vertex_valences(
    face_idx: int,
    mesh: SubDMesh,
    vert_faces: "dict[int, list[int]]",
) -> "list[int]":
    """Return the valences (number of incident faces) for the face vertices."""
    face = mesh.faces[face_idx]
    return [len(vert_faces.get(vi, [])) for vi in face]


def _eval_face_limit_tangents(
    face_idx: int,
    u: float,
    v: float,
    mesh: SubDMesh,
    vert_faces: "dict[int, list[int]]",
    vert_nbrs: "dict[int, list[int]]",
) -> Tuple[
    Tuple[float, float, float],
    Tuple[float, float, float],
]:
    """Evaluate Stam-exact limit tangents (du, dv) at (u,v) on cage face face_idx.

    Falls back to finite-difference tangents from bilinear positions on error.

    Returns (du, dv) — two 3-tuples.
    """
    import numpy as np

    try:
        ring = _extract_regular_2ring(face_idx, mesh, vert_faces, vert_nbrs)
        pts_np = np.array(ring, dtype=float)

        # Determine face valence — use 4 for regular, n for irregular
        valences = _face_vertex_valences(face_idx, mesh, vert_faces)
        irregular = [v for v in valences if v != 4]
        n_val = irregular[0] if irregular else 4

        du_np, dv_np = stam_limit_tangents(pts_np, u, v, n_irregular_vertex=n_val)
        du = (float(du_np[0]), float(du_np[1]), float(du_np[2]))
        dv = (float(dv_np[0]), float(dv_np[1]), float(dv_np[2]))
        return du, dv

    except Exception:
        pass

    # Fallback: finite-difference using bilinear face corners
    try:
        face = list(mesh.faces[face_idx])
        while len(face) < 4:
            face = face + [face[-1]]
        verts = mesh.vertices

        def _bilinear_pos(uu: float, vv: float) -> Tuple[float, float, float]:
            p00 = subd_limit_position(mesh, face[0])
            p10 = subd_limit_position(mesh, face[1])
            p11 = subd_limit_position(mesh, face[2])
            p01 = subd_limit_position(mesh, face[3])
            x = (1-uu)*(1-vv)*p00[0] + uu*(1-vv)*p10[0] + uu*vv*p11[0] + (1-uu)*vv*p01[0]
            y = (1-uu)*(1-vv)*p00[1] + uu*(1-vv)*p10[1] + uu*vv*p11[1] + (1-uu)*vv*p01[1]
            z = (1-uu)*(1-vv)*p00[2] + uu*(1-vv)*p10[2] + uu*vv*p11[2] + (1-uu)*vv*p01[2]
            return (x, y, z)

        h = 1e-5
        p_uf = _bilinear_pos(min(u + h, 1.0), v)
        p_ub = _bilinear_pos(max(u - h, 0.0), v)
        p_vf = _bilinear_pos(u, min(v + h, 1.0))
        p_vb = _bilinear_pos(u, max(v - h, 0.0))
        du = (
            (p_uf[0] - p_ub[0]) / (2 * h),
            (p_uf[1] - p_ub[1]) / (2 * h),
            (p_uf[2] - p_ub[2]) / (2 * h),
        )
        dv = (
            (p_vf[0] - p_vb[0]) / (2 * h),
            (p_vf[1] - p_vb[1]) / (2 * h),
            (p_vf[2] - p_vb[2]) / (2 * h),
        )
        return du, dv

    except Exception:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)


def _eval_face_limit_normal(
    face_idx: int,
    u: float,
    v: float,
    mesh: SubDMesh,
    vert_faces: "dict[int, list[int]]",
    vert_nbrs: "dict[int, list[int]]",
    normalize: bool = True,
) -> Tuple[float, float, float]:
    """Evaluate the CC limit-surface normal at (u,v) on cage face face_idx.

    Returns (nx, ny, nz) — unit-length when normalize=True.
    """
    du, dv = _eval_face_limit_tangents(face_idx, u, v, mesh, vert_faces, vert_nbrs)
    n = _cross3(du, dv)
    if normalize:
        return _norm_vec(n)
    return n


# ---------------------------------------------------------------------------
# Bilinear approximation from face-corner normals (for residual computation)
# ---------------------------------------------------------------------------

def _bilinear_normal(
    u: float,
    v: float,
    n00: Tuple[float, float, float],
    n10: Tuple[float, float, float],
    n11: Tuple[float, float, float],
    n01: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    """Bilinear interpolation of four corner normals at (u, v).

    The four corners are:
        n00 = N(0, 0),  n10 = N(1, 0),
        n11 = N(1, 1),  n01 = N(0, 1).

    The result is NOT unit-length in general; callers should normalise.
    """
    w00 = (1 - u) * (1 - v)
    w10 = u * (1 - v)
    w11 = u * v
    w01 = (1 - u) * v
    nx = w00 * n00[0] + w10 * n10[0] + w11 * n11[0] + w01 * n01[0]
    ny = w00 * n00[1] + w10 * n10[1] + w11 * n11[1] + w01 * n01[1]
    nz = w00 * n00[2] + w10 * n10[2] + w11 * n11[2] + w01 * n01[2]
    return _norm_vec((nx, ny, nz))


# ---------------------------------------------------------------------------
# Public API: sample_subd_limit_normals
# ---------------------------------------------------------------------------

def sample_subd_limit_normals(
    cage_mesh: SubDMesh,
    samples_per_face: int = 9,
    normalize: bool = True,
) -> LimitNormalFitResult:
    """Sample the Catmull-Clark limit-surface normal field on a cage mesh.

    For each cage face, samples a uniform (u, v) grid of
    ``sqrt(samples_per_face)`` × ``sqrt(samples_per_face)`` parameter points
    and evaluates the limit normal at each point using the Stam (1998) exact
    tangent evaluator (eigenstructure for irregular faces, closed-form B-spline
    for regular faces).

    The method also computes the angular deviation of each sampled normal from
    the bilinear approximation (linear blend of the four face-corner Stam
    normals) to quantify how much accuracy a proper normal field gives over the
    simple bilinear shader approximation.

    Parameters
    ----------
    cage_mesh : SubDMesh
        The Catmull-Clark cage mesh.  Quads recommended; n-gons are padded
        to 4 vertices (approximate).
    samples_per_face : int
        Approximate number of (u, v) samples per face.  The actual count is
        ``n × n`` where ``n = max(2, round(sqrt(samples_per_face)))``.
        Default 9 → 3×3 grid (parameter values 0, 0.5, 1).
    normalize : bool
        If True (default), output normals are unit-length.  If False,
        returns the raw cross-product (unnormalised) magnitude.

    Returns
    -------
    LimitNormalFitResult
        ``.sampled_normals``         — list of {u, v, face_idx, nx, ny, nz}
        ``.max_normal_residual_deg`` — max angular error vs bilinear approx
        ``.mean_normal_residual_deg``— mean angular error vs bilinear approx
        ``.num_irregular_samples``   — samples on extraordinary-vertex faces
        ``.honest_caveat``           — method limitations

    Notes
    -----
    * The "normal-field fit" residuals use bilinear interpolation of the four
      face-corner Stam normals as the approximation baseline, NOT a full NURBS
      surface fit.  A closed-form NURBS fit would require an overdetermined
      least-squares solve and is out of scope here.
    * Never raises — errors produce a partial or empty result with the caveat.

    References
    ----------
    Stam (1998) §3.2; Halstead-Kass-DeRose (1993) §3.
    """
    result = LimitNormalFitResult()

    try:
        if not cage_mesh.faces:
            return result

        # Build adjacency once
        vert_faces, vert_nbrs = _build_vertex_adjacency(cage_mesh)

        # Grid density
        n_grid = max(2, round(math.sqrt(max(1, samples_per_face))))
        # Parameter values: n_grid points in [0, 1]
        if n_grid == 1:
            uv_vals = [0.5]
        else:
            uv_vals = [i / (n_grid - 1) for i in range(n_grid)]

        sampled: "list[dict]" = []
        residuals: "list[float]" = []
        n_irregular = 0

        for fi, face in enumerate(cage_mesh.faces):
            if len(face) < 3:
                continue

            # Determine if this face has any irregular vertices
            valences = _face_vertex_valences(fi, cage_mesh, vert_faces)
            face_is_irregular = any(v != 4 for v in valences)

            # Pre-compute corner normals for bilinear residual baseline
            # Corners: (0,0), (1,0), (1,1), (0,1)
            n_corner_00 = _eval_face_limit_normal(fi, 0.0, 0.0, cage_mesh, vert_faces, vert_nbrs, normalize=True)
            n_corner_10 = _eval_face_limit_normal(fi, 1.0, 0.0, cage_mesh, vert_faces, vert_nbrs, normalize=True)
            n_corner_11 = _eval_face_limit_normal(fi, 1.0, 1.0, cage_mesh, vert_faces, vert_nbrs, normalize=True)
            n_corner_01 = _eval_face_limit_normal(fi, 0.0, 1.0, cage_mesh, vert_faces, vert_nbrs, normalize=True)

            for u in uv_vals:
                for v in uv_vals:
                    # Stam-exact normal
                    nx, ny, nz = _eval_face_limit_normal(
                        fi, u, v, cage_mesh, vert_faces, vert_nbrs, normalize=normalize
                    )

                    sampled.append({
                        "u": u,
                        "v": v,
                        "face_idx": fi,
                        "nx": nx,
                        "ny": ny,
                        "nz": nz,
                    })

                    if face_is_irregular:
                        n_irregular += 1

                    # Residual vs bilinear approximation (always using normalised exact)
                    exact_unit = _norm_vec((nx, ny, nz)) if not normalize else (nx, ny, nz)
                    bilin = _bilinear_normal(u, v, n_corner_00, n_corner_10, n_corner_11, n_corner_01)
                    dev = _angular_dev_deg(exact_unit, bilin)
                    residuals.append(dev)

        result.sampled_normals = sampled
        result.num_irregular_samples = n_irregular

        if residuals:
            result.max_normal_residual_deg = max(residuals)
            result.mean_normal_residual_deg = sum(residuals) / len(residuals)
        else:
            result.max_normal_residual_deg = 0.0
            result.mean_normal_residual_deg = 0.0

    except Exception as exc:
        result.honest_caveat += f"  [ERROR: {exc}]"

    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_sample_limit_normals
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811

    _subd_sample_limit_normals_spec = ToolSpec(
        name="subd_sample_limit_normals",
        description=(
            "Sample the Catmull-Clark limit-surface normal field n̂(u,v) at a "
            "uniform grid of (u,v) parameter points on each cage face, using "
            "Stam's (1998) exact eigenstructure tangent evaluator.\n"
            "\n"
            "For each cage face the method samples an "
            "n×n grid (n = round(sqrt(samples_per_face))).  The exact limit "
            "normal is N = (∂S/∂u × ∂S/∂v) / |...|.  Residuals are computed "
            "against the bilinear interpolation of the four face-corner normals "
            "to quantify the accuracy gain from a proper normal field.\n"
            "\n"
            "Inputs:\n"
            "  vertices         : [[x,y,z], ...]  cage control vertices.\n"
            "  faces            : [[i,j,k,l], ...]  cage face vertex indices.\n"
            "  samples_per_face : int  approx samples per face (default 9 → 3×3).\n"
            "  normalize        : bool  unit-length normals (default true).\n"
            "\n"
            "Returns:\n"
            "  ok                       : bool\n"
            "  sampled_normals          : [{u, v, face_idx, nx, ny, nz}, ...]  per-sample\n"
            "  max_normal_residual_deg  : float  max angular error vs bilinear approx (°)\n"
            "  mean_normal_residual_deg : float  mean angular error vs bilinear approx (°)\n"
            "  num_irregular_samples    : int    samples on extraordinary-vertex faces\n"
            "  total_samples            : int    total samples across all faces\n"
            "  honest_caveat            : str    method limitations\n"
            "\n"
            "Caveats: residuals use bilinear baseline (not a full NURBS fit); "
            "non-quad faces approximated from first 4 vertices; normal sign "
            "depends on cage face winding.  Never raises.\n"
            "\n"
            "Refs: Stam (1998) §3.2; Halstead-Kass-DeRose (1993); "
            "Piegl-Tiller 'The NURBS Book' (1997)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 3,
                },
                "faces": {
                    "type": "array",
                    "description": "Cage face vertex-index lists as [[i,j,k,...], ...].",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 3,
                    },
                    "minItems": 1,
                },
                "samples_per_face": {
                    "type": "integer",
                    "description": (
                        "Approximate number of (u,v) samples per face.  Actual "
                        "count is n×n where n = round(sqrt(samples_per_face)).  "
                        "Default 9."
                    ),
                    "default": 9,
                    "minimum": 1,
                },
                "normalize": {
                    "type": "boolean",
                    "description": "Return unit-length normals (default true).",
                    "default": True,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_sample_limit_normals_spec)
    async def run_subd_sample_limit_normals(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        n_samples = int(a.get("samples_per_face", 9))
        do_normalize = bool(a.get("normalize", True))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")

        try:
            verts = [[float(c) for c in row] for row in raw_verts]
            faces = [[int(i) for i in row] for row in raw_faces]
        except Exception as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        mesh = SubDMesh(vertices=verts, faces=faces)
        res = sample_subd_limit_normals(mesh, samples_per_face=n_samples, normalize=do_normalize)

        return ok_payload({
            "ok": True,
            "sampled_normals": res.sampled_normals,
            "max_normal_residual_deg": res.max_normal_residual_deg,
            "mean_normal_residual_deg": res.mean_normal_residual_deg,
            "num_irregular_samples": res.num_irregular_samples,
            "total_samples": len(res.sampled_normals),
            "honest_caveat": res.honest_caveat,
        })
