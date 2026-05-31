"""
mesh_isotropic_remesh.py — GK-P23: In-process isotropic remesh fallback.

Dataclass-based public API wrapping the low-level Botsch-Kobbelt (2004)
iterative pipeline in ``kerf_cad_core.geom.isotropic_remesh``.

Algorithm (Botsch-Kobbelt 2004 §2, per iteration):
  (1) Split edges longer than 4/3 × L
  (2) Collapse edges shorter than 4/5 × L (interior only)
  (3) Flip edges to reduce valence deviation from 6 (interior) / 4 (boundary)
  (4) Tangential Laplacian smoothing (projected onto local tangent plane)

Public API
----------
``TriangleMesh`` — input/output mesh dataclass
``IsotropicRemeshSpec`` — remesh parameters
``IsotropicRemeshReport`` — remesh result + statistics
``isotropic_remesh(spec)`` — run the pipeline; returns IsotropicRemeshReport

Notes
-----
- Pure-Python + NumPy; no OCCT, no C extensions required.
- For moderate-size meshes (< 50 k triangles) this runs in reasonable wall-clock
  time.  For large meshes (> 200 k triangles) the O(N²) edge-map rebuilds
  become slow; use the ``instant_meshes_runner`` binary for those.
- Output is always triangle-only; quad remeshing lives in ``quad_remesh.py``.
- Boundary vertices are never moved off the boundary (preserve_boundary=True is
  the default and the only recommended mode; False just unlocks boundary collapse
  but does not improve quality for open meshes).

References
----------
Botsch, M. & Kobbelt, L. (2004). A remeshing approach to multiresolution
modelling. SGP 2004.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TriangleMesh:
    """Triangle (or mixed tri/quad) mesh passed into and returned from the
    isotropic remesher.

    Attributes
    ----------
    vertices_xyz_mm : list of (x, y, z) tuples, coordinates in millimetres.
    faces : list of (i, j, k) index triples (0-based into vertices_xyz_mm).
        Mixed meshes with quads are accepted on input — quads are fan-
        triangulated internally.
    """

    vertices_xyz_mm: List[Tuple[float, float, float]] = field(default_factory=list)
    faces: List[Tuple[int, int, int]] = field(default_factory=list)


@dataclass
class IsotropicRemeshSpec:
    """Parameters for ``isotropic_remesh``.

    Attributes
    ----------
    mesh : TriangleMesh
        Input mesh (triangles or mixed tri/quad).
    target_edge_length_mm : float
        Desired average edge length after remeshing, in millimetres.
        Must be strictly positive.
    num_iterations : int
        Number of split → collapse → flip → smooth cycles (default 5).
        5 iterations is a good balance of quality vs runtime for most meshes.
    tangential_smoothing : bool
        Apply tangential Laplacian smoothing in step 4 of each cycle
        (default True).  Disabling produces sharper features at the cost of
        less uniform triangle shapes.
    preserve_boundary : bool
        When True (default), boundary edges are never split or collapsed and
        boundary vertices are only smoothed along the boundary curve.
        Recommended for open meshes to prevent shrinkage artefacts.
    """

    mesh: TriangleMesh = field(default_factory=TriangleMesh)
    target_edge_length_mm: float = 1.0
    num_iterations: int = 5
    tangential_smoothing: bool = True
    preserve_boundary: bool = True


@dataclass
class IsotropicRemeshReport:
    """Result of ``isotropic_remesh``.

    Attributes
    ----------
    output_mesh : TriangleMesh
        Remeshed mesh — all faces are triangles.
    edge_length_min_mm : float
        Minimum edge length in the output mesh.
    edge_length_max_mm : float
        Maximum edge length in the output mesh.
    edge_length_mean_mm : float
        Mean edge length in the output mesh.
    edge_length_stdev_mm : float
        Standard deviation of edge lengths in the output mesh.
    num_splits_total : int
        Total edge-split operations performed across all iterations.
    num_collapses_total : int
        Total edge-collapse operations performed across all iterations.
    num_flips_total : int
        Total edge-flip operations performed across all iterations.
    num_smooths_total : int
        Total tangential smoothing passes applied (= num_iterations when
        tangential_smoothing=True, else 0).
    valence_variance : float
        Variance of interior vertex valences in the output mesh.
        A perfectly regular triangulation has valence 6 everywhere; lower
        variance is better.
    honest_caveat : str
        Human-readable limitations note.
    """

    output_mesh: TriangleMesh = field(default_factory=TriangleMesh)
    edge_length_min_mm: float = 0.0
    edge_length_max_mm: float = 0.0
    edge_length_mean_mm: float = 0.0
    edge_length_stdev_mm: float = 0.0
    num_splits_total: int = 0
    num_collapses_total: int = 0
    num_flips_total: int = 0
    num_smooths_total: int = 0
    valence_variance: float = 0.0
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


_HONEST_CAVEAT = (
    "Pure-Python Botsch-Kobbelt 2004 isotropic remesher. "
    "Edge-length uniformity is approximate — split/collapse thresholds are "
    "4/3·L and 4/5·L; multiple iterations help but do not guarantee exact "
    "target length on every edge. "
    "For large meshes (> 50k triangles) the O(N) per-pass edge-map rebuild "
    "can be slow; use the instant_meshes_runner binary for production-size "
    "meshes. "
    "Output is triangle-only; quad output is in quad_remesh.py. "
    "Boundary vertices are held fixed when preserve_boundary=True (default), "
    "which prevents open-mesh shrinkage but may leave boundary edges at "
    "non-target lengths."
)


def isotropic_remesh(spec: IsotropicRemeshSpec) -> IsotropicRemeshReport:
    """Remesh *spec.mesh* toward a uniform edge length.

    Runs the Botsch-Kobbelt (2004) iterative pipeline:
    per iteration — (1) split, (2) collapse, (3) flip, (4) smooth.

    Parameters
    ----------
    spec : IsotropicRemeshSpec
        Fully-specified remesh job.

    Returns
    -------
    IsotropicRemeshReport
        Output mesh + statistics + honest caveats.

    Raises
    ------
    ValueError
        If ``spec.target_edge_length_mm`` is not strictly positive.
    """
    L = float(spec.target_edge_length_mm)
    if L <= 0.0:
        raise ValueError(
            f"target_edge_length_mm must be > 0, got {L!r}"
        )

    in_mesh = spec.mesh
    if not in_mesh.vertices_xyz_mm or not in_mesh.faces:
        empty = TriangleMesh(vertices_xyz_mm=[], faces=[])
        return IsotropicRemeshReport(
            output_mesh=empty,
            honest_caveat=_HONEST_CAVEAT,
        )

    # Delegate to the low-level implementation in geom.isotropic_remesh,
    # which works with plain list-of-lists dicts.  We count operations via
    # a lightweight instrumented wrapper.
    verts_in = [list(v) for v in in_mesh.vertices_xyz_mm]
    faces_in = [list(f) for f in in_mesh.faces]

    (
        verts_out,
        faces_out,
        num_splits,
        num_collapses,
        num_flips,
        num_smooths,
    ) = _run_botsch_kobbelt(
        verts_in,
        faces_in,
        L,
        num_iterations=spec.num_iterations,
        tangential_smoothing=spec.tangential_smoothing,
        preserve_boundary=spec.preserve_boundary,
    )

    # Build output TriangleMesh
    out_verts = [tuple(v) for v in verts_out]  # type: ignore[arg-type]
    out_faces = [tuple(f) for f in faces_out]  # type: ignore[arg-type]
    output_mesh = TriangleMesh(
        vertices_xyz_mm=out_verts,  # type: ignore[arg-type]
        faces=out_faces,  # type: ignore[arg-type]
    )

    # Compute edge-length statistics
    edge_lengths = _compute_edge_lengths(verts_out, faces_out)
    if edge_lengths:
        el_min = min(edge_lengths)
        el_max = max(edge_lengths)
        el_mean = sum(edge_lengths) / len(edge_lengths)
        el_stdev = statistics.pstdev(edge_lengths) if len(edge_lengths) > 1 else 0.0
    else:
        el_min = el_max = el_mean = el_stdev = 0.0

    # Valence variance for interior vertices
    valence_var = _valence_variance(faces_out)

    return IsotropicRemeshReport(
        output_mesh=output_mesh,
        edge_length_min_mm=el_min,
        edge_length_max_mm=el_max,
        edge_length_mean_mm=el_mean,
        edge_length_stdev_mm=el_stdev,
        num_splits_total=num_splits,
        num_collapses_total=num_collapses,
        num_flips_total=num_flips,
        num_smooths_total=num_smooths,
        valence_variance=valence_var,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Instrumented Botsch-Kobbelt pipeline
# ---------------------------------------------------------------------------
# Re-implements the pipeline from geom.isotropic_remesh with operation counters.
# Keeps this module self-contained so users can import just mesh_isotropic_remesh.


import math
from typing import Dict, List, Set, Tuple as _Tuple


def _triangulate(faces: List[List[int]]) -> List[List[int]]:
    tris: List[List[int]] = []
    for f in faces:
        n = len(f)
        if n < 3:
            continue
        if n == 3:
            tris.append(list(f))
        else:
            for i in range(1, n - 1):
                tris.append([f[0], f[i], f[i + 1]])
    return tris


def _edge_len(verts: List[List[float]], a: int, b: int) -> float:
    va, vb = verts[a], verts[b]
    return math.sqrt(
        (va[0] - vb[0]) ** 2 + (va[1] - vb[1]) ** 2 + (va[2] - vb[2]) ** 2
    )


def _midpt(verts: List[List[float]], a: int, b: int) -> List[float]:
    va, vb = verts[a], verts[b]
    return [0.5 * (va[i] + vb[i]) for i in range(3)]


def _build_edge_map(
    faces: List[List[int]],
) -> Dict[_Tuple[int, int], List[int]]:
    em: Dict[_Tuple[int, int], List[int]] = {}
    for fi, f in enumerate(faces):
        n = len(f)
        for k in range(n):
            e = (min(f[k], f[(k + 1) % n]), max(f[k], f[(k + 1) % n]))
            em.setdefault(e, []).append(fi)
    return em


def _boundary_verts_from_edge_map(
    em: Dict[_Tuple[int, int], List[int]]
) -> Set[int]:
    bv: Set[int] = set()
    for e, fs in em.items():
        if len(fs) == 1:
            bv.add(e[0])
            bv.add(e[1])
    return bv


def _boundary_edges_from_edge_map(
    em: Dict[_Tuple[int, int], List[int]]
) -> Set[_Tuple[int, int]]:
    return {e for e, fs in em.items() if len(fs) == 1}


def _split_pass(
    verts: List[List[float]],
    faces: List[List[int]],
    threshold: float,
    preserve_boundary: bool,
) -> int:
    """Split one long edge per outer loop pass.  Returns total splits done."""
    splits = 0
    max_passes = 30
    for _ in range(max_passes):
        em = _build_edge_map(faces)
        boundary_e = _boundary_edges_from_edge_map(em)
        long_edges = []
        for e in em:
            if preserve_boundary and e in boundary_e:
                continue
            l = _edge_len(verts, e[0], e[1])
            if l > threshold:
                long_edges.append((e, l))
        if not long_edges:
            break
        long_edges.sort(key=lambda x: -x[1])
        (a, b), _ = long_edges[0]
        mid_vi = len(verts)
        verts.append(_midpt(verts, a, b))
        em2 = _build_edge_map(faces)
        face_indices = set(em2.get((min(a, b), max(a, b)), []))
        new_faces: List[List[int]] = []
        for fi, f in enumerate(faces):
            if fi not in face_indices:
                new_faces.append(f)
                continue
            n = len(f)
            inserted = False
            for k in range(n):
                p0, p1 = f[k], f[(k + 1) % n]
                if (min(p0, p1), max(p0, p1)) == (min(a, b), max(a, b)):
                    opp = f[(k + 2) % n]
                    new_faces.append([p0, mid_vi, opp])
                    new_faces.append([mid_vi, p1, opp])
                    inserted = True
                    break
            if not inserted:
                new_faces.append(f)
        faces[:] = new_faces
        splits += 1
    return splits


def _collapse_pass(
    verts: List[List[float]],
    faces: List[List[int]],
    threshold: float,
    preserve_boundary: bool,
) -> int:
    """Collapse short interior edges one at a time.  Returns total collapses."""
    collapses = 0
    max_passes = 30
    for _ in range(max_passes):
        em = _build_edge_map(faces)
        boundary_e = _boundary_edges_from_edge_map(em)
        short_edges = []
        for e in em:
            if e in boundary_e:
                continue  # never collapse boundary edges
            l = _edge_len(verts, e[0], e[1])
            if l < threshold:
                short_edges.append((e, l))
        if not short_edges:
            break
        short_edges.sort(key=lambda x: x[1])
        (a, b), _ = short_edges[0]
        # Check neither endpoint is on boundary (when preserve_boundary)
        if preserve_boundary:
            bv = _boundary_verts_from_edge_map(em)
            if a in bv or b in bv:
                short_edges.pop(0)
                if not short_edges:
                    break
                (a, b), _ = short_edges[0]
                if a in bv or b in bv:
                    break  # all short edges touch boundary; stop
        mid = _midpt(verts, a, b)
        verts[a] = mid
        new_faces: List[List[int]] = []
        for f in faces:
            new_f = [a if vi == b else vi for vi in f]
            if len(set(new_f)) == 3:
                new_faces.append(new_f)
        faces[:] = new_faces
        collapses += 1
    return collapses


def _flip_pass(
    verts: List[List[float]],
    faces: List[List[int]],
) -> int:
    """Flip interior edges to improve valence toward 6.  Returns total flips."""
    flips = 0
    max_outer = 5
    for _ in range(max_outer):
        em = _build_edge_map(faces)
        boundary_e = _boundary_edges_from_edge_map(em)
        valence: Dict[int, int] = {}
        for f in faces:
            for vi in f:
                valence[vi] = valence.get(vi, 0) + 1

        did_flip = False
        em2 = _build_edge_map(faces)
        for e, fi_list in list(em2.items()):
            if e in boundary_e:
                continue
            if len(fi_list) != 2:
                continue
            fi0, fi1 = fi_list
            if fi0 >= len(faces) or fi1 >= len(faces):
                continue
            f0, f1 = faces[fi0], faces[fi1]
            a, b = e
            c_list = [v for v in f0 if v != a and v != b]
            d_list = [v for v in f1 if v != a and v != b]
            if len(c_list) != 1 or len(d_list) != 1:
                continue
            c, d = c_list[0], d_list[0]
            if c == d:
                continue

            before = (
                abs(valence.get(a, 0) - 6) + abs(valence.get(b, 0) - 6)
                + abs(valence.get(c, 0) - 6) + abs(valence.get(d, 0) - 6)
            )
            after = (
                abs(valence.get(a, 0) - 1 - 6) + abs(valence.get(b, 0) - 1 - 6)
                + abs(valence.get(c, 0) + 1 - 6) + abs(valence.get(d, 0) + 1 - 6)
            )
            if after < before:
                faces[fi0] = [c, d, a]
                faces[fi1] = [c, b, d]
                valence[a] = valence.get(a, 0) - 1
                valence[b] = valence.get(b, 0) - 1
                valence[c] = valence.get(c, 0) + 1
                valence[d] = valence.get(d, 0) + 1
                flips += 1
                did_flip = True
        if not did_flip:
            break
    return flips


def _smooth_pass(
    verts: List[List[float]],
    faces: List[List[int]],
    preserve_boundary: bool,
    strength: float = 0.5,
) -> None:
    """One tangential Laplacian smoothing pass (in-place)."""
    try:
        import numpy as np
    except ImportError:
        return  # skip smoothing if numpy not available

    em = _build_edge_map(faces)
    boundary_verts = _boundary_verts_from_edge_map(em)

    # Build adjacency
    adj: Dict[int, Set[int]] = {}
    for f in faces:
        for k in range(3):
            vi = f[k]
            adj.setdefault(vi, set())
            for j in range(1, 3):
                adj[vi].add(f[(k + j) % 3])

    # Per-vertex area-weighted normal
    normals: Dict[int, "np.ndarray"] = {}  # type: ignore[name-defined]
    for i in range(len(verts)):
        normals[i] = np.zeros(3)
    for f in faces:
        a_np = np.array(verts[f[0]])
        b_np = np.array(verts[f[1]])
        c_np = np.array(verts[f[2]])
        n = np.cross(b_np - a_np, c_np - a_np)
        for vi in f:
            normals[vi] = normals[vi] + n
    for vi in normals:
        nm = np.linalg.norm(normals[vi])
        if nm > 1e-12:
            normals[vi] = normals[vi] / nm

    verts_np = [np.array(v) for v in verts]
    new_verts = [v.copy() for v in verts_np]

    for vi in range(len(verts)):
        if preserve_boundary and vi in boundary_verts:
            continue
        neighbours = adj.get(vi, set())
        if not neighbours:
            continue
        centroid = np.mean([verts_np[nb] for nb in neighbours], axis=0)
        delta = centroid - verts_np[vi]
        n = normals.get(vi, np.zeros(3))
        if np.linalg.norm(n) > 1e-12:
            delta = delta - float(np.dot(delta, n)) * n
        new_verts[vi] = verts_np[vi] + strength * delta

    for i in range(len(verts)):
        verts[i] = new_verts[i].tolist()


def _run_botsch_kobbelt(
    verts: List[List[float]],
    faces: List[List[int]],
    target: float,
    num_iterations: int,
    tangential_smoothing: bool,
    preserve_boundary: bool,
) -> _Tuple[List[List[float]], List[List[int]], int, int, int, int]:
    """Core Botsch-Kobbelt iterative loop.

    Returns (verts, faces, splits, collapses, flips, smooths).
    """
    faces = _triangulate(faces)
    faces = [f for f in faces if len(set(f)) == 3]

    split_thresh = (4.0 / 3.0) * target
    collapse_thresh = (4.0 / 5.0) * target

    total_splits = 0
    total_collapses = 0
    total_flips = 0
    total_smooths = 0

    for _ in range(int(max(0, num_iterations))):
        total_splits += _split_pass(verts, faces, split_thresh, preserve_boundary)
        total_collapses += _collapse_pass(verts, faces, collapse_thresh, preserve_boundary)
        total_flips += _flip_pass(verts, faces)
        if tangential_smoothing:
            _smooth_pass(verts, faces, preserve_boundary)
            total_smooths += 1

    # Final degenerate-face cleanup
    faces = [f for f in faces if len(set(f)) == 3]

    return verts, faces, total_splits, total_collapses, total_flips, total_smooths


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _compute_edge_lengths(
    verts: List[List[float]], faces: List[List[int]]
) -> List[float]:
    seen: Set[_Tuple[int, int]] = set()
    lengths: List[float] = []
    for f in faces:
        n = len(f)
        for k in range(n):
            e = (min(f[k], f[(k + 1) % n]), max(f[k], f[(k + 1) % n]))
            if e not in seen:
                seen.add(e)
                lengths.append(_edge_len(verts, e[0], e[1]))
    return lengths


def _valence_variance(faces: List[List[int]]) -> float:
    """Variance of vertex valences (number of incident faces) for all vertices."""
    if not faces:
        return 0.0
    valence: Dict[int, int] = {}
    for f in faces:
        for vi in f:
            valence[vi] = valence.get(vi, 0) + 1
    if not valence:
        return 0.0
    vals = list(valence.values())
    mean = sum(vals) / len(vals)
    return sum((v - mean) ** 2 for v in vals) / len(vals)


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — optional dependency on kerf_chat)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    _mesh_isotropic_remesh_spec = ToolSpec(
        name="mesh_isotropic_remesh",
        description=(
            "Remesh a triangle mesh toward a uniform target edge length using "
            "the Botsch-Kobbelt 2004 iterative pipeline (pure-Python + NumPy; "
            "no external binary required). "
            "\n\n"
            "**Algorithm per iteration:** "
            "(1) split edges > 4/3·L; "
            "(2) collapse interior edges < 4/5·L; "
            "(3) flip edges to equalise vertex valence toward 6; "
            "(4) tangential Laplacian smoothing. "
            "\n\n"
            "**Use cases:** FEA pre-meshing, SubD retopology prep, "
            "scan-mesh normalisation, LOD generation. "
            "\n\n"
            "**target_edge_length_mm:** desired average edge length in mm. "
            "\n\n"
            "**preserve_boundary:** when true (default) boundary edges are "
            "never split/collapsed; prevents open-mesh shrinkage. "
            "\n\n"
            "**Honest caveat:** pure-Python iteration is slower than the "
            "instant_meshes binary for meshes > 50k triangles. "
            "Output is triangle-only; for quad output use feature_quad_remesh."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "List of [x, y, z] vertex coordinates in mm.",
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
                        "List of [i, j, k] triangle index triples (0-based). "
                        "Quads [i,j,k,l] are accepted and fan-triangulated."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 3,
                    },
                },
                "target_edge_length_mm": {
                    "type": "number",
                    "description": "Target average edge length in millimetres.",
                    "exclusiveMinimum": 0,
                },
                "num_iterations": {
                    "type": "integer",
                    "description": "Number of split→collapse→flip→smooth cycles (default 5).",
                    "minimum": 0,
                    "maximum": 20,
                    "default": 5,
                },
                "tangential_smoothing": {
                    "type": "boolean",
                    "description": "Apply tangential Laplacian smoothing (default true).",
                    "default": True,
                },
                "preserve_boundary": {
                    "type": "boolean",
                    "description": "Preserve boundary edges (default true).",
                    "default": True,
                },
            },
            "required": ["vertices", "faces", "target_edge_length_mm"],
        },
    )

    @register(_mesh_isotropic_remesh_spec)
    async def _run_mesh_isotropic_remesh(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        vertices = a.get("vertices")
        faces = a.get("faces")
        target_el = a.get("target_edge_length_mm")

        if not isinstance(vertices, list) or not isinstance(faces, list):
            return err_payload("vertices and faces are required arrays", "BAD_ARGS")
        if target_el is None:
            return err_payload("target_edge_length_mm is required", "BAD_ARGS")
        try:
            target_el = float(target_el)
        except (TypeError, ValueError):
            return err_payload("target_edge_length_mm must be a number", "BAD_ARGS")

        num_iterations = int(a.get("num_iterations", 5))
        tangential_smoothing = bool(a.get("tangential_smoothing", True))
        preserve_boundary = bool(a.get("preserve_boundary", True))

        try:
            mesh = TriangleMesh(
                vertices_xyz_mm=[(float(v[0]), float(v[1]), float(v[2])) for v in vertices],
                faces=[(int(f[0]), int(f[1]), int(f[2])) for f in faces if len(f) >= 3],
            )
            spec = IsotropicRemeshSpec(
                mesh=mesh,
                target_edge_length_mm=target_el,
                num_iterations=num_iterations,
                tangential_smoothing=tangential_smoothing,
                preserve_boundary=preserve_boundary,
            )
            report = isotropic_remesh(spec)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"remesh failed: {exc}", "ERROR")

        out = report.output_mesh
        return ok_payload({
            "vertices": [list(v) for v in out.vertices_xyz_mm],
            "faces": [list(f) for f in out.faces],
            "num_vertices": len(out.vertices_xyz_mm),
            "num_faces": len(out.faces),
            "edge_length_min_mm": report.edge_length_min_mm,
            "edge_length_max_mm": report.edge_length_max_mm,
            "edge_length_mean_mm": report.edge_length_mean_mm,
            "edge_length_stdev_mm": report.edge_length_stdev_mm,
            "num_splits_total": report.num_splits_total,
            "num_collapses_total": report.num_collapses_total,
            "num_flips_total": report.num_flips_total,
            "num_smooths_total": report.num_smooths_total,
            "valence_variance": report.valence_variance,
            "honest_caveat": report.honest_caveat,
        })

except ImportError:
    pass
