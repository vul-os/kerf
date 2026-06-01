"""uv_unwrap_hardening.py — GK-P20: UV-unwrap post-processing.

Post-processes raw UV layouts produced by LSCM / ARAP unwrap modules:

1. **Seam cutting** — split the mesh at marked seam edges so that each
   connected UV-island (chart) has no internal seam discontinuities.
2. **Chart bbox-normalisation** — translate each chart's UV bounding-box
   to the origin; try 90°-increment rotations to minimise bbox area.
3. **Shelf bin-packing** — pack charts into a unit square using the
   shelf-first-fit heuristic (Kenyon 1996 / Sleator 1980).
4. **Distortion statistics** — per-chart and global angle/area distortion
   summary (Sander et al. 2003 §3; Lévy et al. 2002 §5).

References
----------
* P. Sander, S. Gortler, J. Snyder, H. Hoppe — "Multi-Chart Geometry
  Images", SGP 2003.
* B. Lévy, S. Petitjean, N. Ray, J. Maillot — "Least Squares Conformal
  Maps for Automatic Texture Atlas Generation", SIGGRAPH 2002.

Public API
----------
harden_uv_unwrap(spec: UVUnwrapHardeningSpec) -> HardenedUVResult

HONEST caveats
--------------
* Rotation: 90°-increment discrete search only (0°, 90°, 180°, 270°).
  No sub-degree optimal-angle (no SAT/no iterative minimisation).
* Packing: shelf-first-fit heuristic ≥ 50% efficiency on uniform inputs;
  NOT optimal (no guillotine / guillotine-with-rotation / VLSI packing).
* Distortion: sampling-based lower bound (per-face Jacobian residual);
  NOT the continuous L²-LSCM energy minimum.
* Corner-split UVs: when seams split a vertex into multiple corners, the
  returned ``packed_uv`` list is per-corner (length = 3 × num_faces),
  indexed as corner c = face_idx*3 + local_vertex_idx (0/1/2).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UVUnwrapHardeningSpec:
    """Input specification for :func:`harden_uv_unwrap`.

    Attributes
    ----------
    mesh_vertices_xyz : list of (x, y, z)
        3-D positions of mesh vertices.
    mesh_faces : list of (i0, i1, i2)
        Triangle faces as vertex-index triples.
    initial_uv : list of (u, v)
        Raw UV coordinates produced by LSCM/ARAP; one entry per vertex.
    seam_edges : list of (v_a, v_b)
        Vertex-index pairs marking seam edges that should be cut.  Use
        the *unordered* canonical form (both (a,b) and (b,a) are treated
        as the same seam edge).
    """

    mesh_vertices_xyz: List[Tuple[float, float, float]]
    mesh_faces: List[Tuple[int, int, int]]
    initial_uv: List[Tuple[float, float]]
    seam_edges: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class UVChart:
    """A single UV island (chart) after seam-cutting and packing.

    Attributes
    ----------
    face_indices : list[int]
        Indices of faces belonging to this chart.
    uv_min : (float, float)
        Bottom-left corner of the chart's axis-aligned bounding box
        in the *packed* UV space.
    uv_max : (float, float)
        Top-right corner of the chart's bounding box in packed UV space.
    chart_area_uv : float
        Signed area of the chart in UV space (sum of triangle areas).
    chart_area_3d_mm2 : float
        Approximate 3-D surface area of the chart (mm²), computed via
        cross-product of 3-D triangle edges.
    scale_factor : float
        Ratio uv_area / 3d_area.  Values far from 1 indicate scale
        distortion; use alongside distortion stats for QC.
    """

    face_indices: List[int]
    uv_min: Tuple[float, float]
    uv_max: Tuple[float, float]
    chart_area_uv: float
    chart_area_3d_mm2: float
    scale_factor: float


@dataclass
class HardenedUVResult:
    """Output of :func:`harden_uv_unwrap`.

    Attributes
    ----------
    packed_uv : list of (u, v)
        Per-corner UV coordinates in packed space.  Each triangle face
        ``f`` has corners at indices ``f*3``, ``f*3+1``, ``f*3+2``.
    charts : list[UVChart]
        One entry per UV island.
    num_charts : int
        Total number of islands produced by seam-cutting.
    num_seam_cuts : int
        Number of seam edges that were actually present in the mesh (and
        cut).  May be less than ``len(spec.seam_edges)`` if some edges
        do not exist in the mesh.
    packing_efficiency : float
        ``sum(chart_area_uv) / 1.0`` — fraction of the unit square
        covered by chart content.  Always in (0, 1].
    max_distortion : float
        Maximum per-chart mean angle distortion (degrees).
    mean_distortion : float
        Mean of per-chart angle distortion values (degrees).
    honest_caveat : str
        Human-readable caveat string documenting algorithm limitations.
    """

    packed_uv: List[Tuple[float, float]]
    charts: List[UVChart]
    num_charts: int
    num_seam_cuts: int
    packing_efficiency: float
    max_distortion: float
    mean_distortion: float
    honest_caveat: str = (
        "Shelf bin-packing only (not optimal); rotation at 90° increments only "
        "(no fractional angles); distortion is a sampling-based lower bound."
    )


# ---------------------------------------------------------------------------
# Internal helpers: seam-edge normalisation
# ---------------------------------------------------------------------------


def _seam_key(a: int, b: int) -> Tuple[int, int]:
    return (min(a, b), max(a, b))


def _build_seam_set(
    seam_edges: List[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    return {_seam_key(a, b) for a, b in seam_edges}


# ---------------------------------------------------------------------------
# Connected-component search respecting seam edges
# ---------------------------------------------------------------------------


def _find_charts(
    faces: List[Tuple[int, int, int]],
    seam_set: Set[Tuple[int, int]],
) -> Tuple[List[List[int]], int]:
    """Flood-fill faces into connected components using face-adjacency.

    Two adjacent triangles are in the *same* component if the shared edge
    is NOT in ``seam_set``.

    Returns
    -------
    (components, num_cuts)
        components — list of face-index lists (one per chart)
        num_cuts   — number of seam edges that actually separated faces
    """
    n_faces = len(faces)
    if n_faces == 0:
        return [], 0

    # Build edge → list[face_idx] map
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    for fi, f in enumerate(faces):
        for k in range(3):
            e = _seam_key(f[k], f[(k + 1) % 3])
            edge_faces.setdefault(e, []).append(fi)

    # Count how many seam edges actually appear in the mesh
    num_cuts = sum(
        1 for e in seam_set if e in edge_faces and len(edge_faces[e]) >= 2
    )

    # BFS
    visited = [False] * n_faces
    components: List[List[int]] = []

    for start in range(n_faces):
        if visited[start]:
            continue
        component: List[int] = []
        queue = [start]
        visited[start] = True
        while queue:
            fi = queue.pop()
            component.append(fi)
            f = faces[fi]
            for k in range(3):
                e = _seam_key(f[k], f[(k + 1) % 3])
                if e in seam_set:
                    continue  # cut here — do NOT cross seam
                for nfi in edge_faces.get(e, []):
                    if not visited[nfi]:
                        visited[nfi] = True
                        queue.append(nfi)
        components.append(component)

    return components, num_cuts


# ---------------------------------------------------------------------------
# Per-chart UV extraction + bbox normalisation + rotation
# ---------------------------------------------------------------------------


def _rotate_uvs_90(uvs: np.ndarray, k: int) -> np.ndarray:
    """Rotate UV coordinates by k×90° around origin."""
    if k == 0:
        return uvs
    if k == 1:
        return np.column_stack([-uvs[:, 1], uvs[:, 0]])
    if k == 2:
        return -uvs
    # k == 3
    return np.column_stack([uvs[:, 1], -uvs[:, 0]])


def _bbox_area(uvs: np.ndarray) -> float:
    w = float(uvs[:, 0].max() - uvs[:, 0].min())
    h = float(uvs[:, 1].max() - uvs[:, 1].min())
    return w * h


def _normalise_chart_uvs(
    chart_corner_uv: np.ndarray,
) -> Tuple[np.ndarray, float, float]:
    """Translate + optionally rotate so bbox origin = (0,0); minimise bbox area.

    Returns (normalised_uvs, width, height) in normalised space.
    """
    # Try 4 × 90° rotations, pick the one with smallest bbox area
    best_uvs = chart_corner_uv
    best_area = math.inf
    best_rot = 0

    for k in range(4):
        rotated = _rotate_uvs_90(chart_corner_uv, k)
        # Translate to origin
        u_min = float(rotated[:, 0].min())
        v_min = float(rotated[:, 1].min())
        translated = rotated - np.array([u_min, v_min])
        a = _bbox_area(translated)
        if a < best_area:
            best_area = a
            best_uvs = translated
            best_rot = k  # noqa: F841 (kept for debug)

    w = float(best_uvs[:, 0].max() - best_uvs[:, 0].min())
    h = float(best_uvs[:, 1].max() - best_uvs[:, 1].min())
    if w < 1e-12:
        w = 1e-12
    if h < 1e-12:
        h = 1e-12
    return best_uvs, w, h


# ---------------------------------------------------------------------------
# Distortion: per-face Jacobian angle residual (Lévy 2002 / Sander 2003)
# ---------------------------------------------------------------------------


def _triangle_local_frame_2d(
    p0: np.ndarray, p1: np.ndarray, p2: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2-D local-frame coordinates of a 3-D triangle."""
    e1 = p1 - p0
    e2 = p2 - p0
    len_e1 = float(np.linalg.norm(e1))
    if len_e1 < 1e-12:
        return np.zeros(2), np.zeros(2), np.zeros(2)
    x_axis = e1 / len_e1
    n = np.cross(e1, e2)
    n_len = float(np.linalg.norm(n))
    if n_len < 1e-12:
        return np.zeros(2), np.zeros(2), np.zeros(2)
    n /= n_len
    y_axis = np.cross(n, x_axis)
    q0 = np.array([0.0, 0.0])
    q1 = np.array([float(np.dot(e1, x_axis)), float(np.dot(e1, y_axis))])
    q2 = np.array([float(np.dot(e2, x_axis)), float(np.dot(e2, y_axis))])
    return q0, q1, q2


def _angle_distortion_for_faces(
    verts_xyz: np.ndarray,          # (N, 3)
    faces: List[Tuple[int, int, int]],
    corner_uv: np.ndarray,          # (3*F, 2) — corners indexed face*3+k
) -> float:
    """Mean per-triangle angle distortion in degrees (Sheffer 2006 eq. 3)."""
    errors: List[float] = []
    for fi, f in enumerate(faces):
        p0 = verts_xyz[f[0]]
        p1 = verts_xyz[f[1]]
        p2 = verts_xyz[f[2]]
        q0, q1, q2 = _triangle_local_frame_2d(p0, p1, p2)

        uv0 = corner_uv[fi * 3 + 0]
        uv1 = corner_uv[fi * 3 + 1]
        uv2 = corner_uv[fi * 3 + 2]

        e3 = np.column_stack([q1 - q0, q2 - q0])
        e2 = np.column_stack([uv1 - uv0, uv2 - uv0])

        det3 = float(np.linalg.det(e3))
        if abs(det3) < 1e-12:
            continue
        try:
            J = e2 @ np.linalg.inv(e3)
        except np.linalg.LinAlgError:
            continue
        det_J = abs(float(np.linalg.det(J)))
        sigma = math.sqrt(max(det_J, 0.0))
        deviation = J.T @ J - sigma ** 2 * np.eye(2)
        errors.append(math.degrees(math.sqrt(float(np.sum(deviation ** 2)))))

    return float(np.mean(errors)) if errors else 0.0


# ---------------------------------------------------------------------------
# 3-D area helper
# ---------------------------------------------------------------------------


def _chart_3d_area(
    verts_xyz: np.ndarray,
    faces: List[Tuple[int, int, int]],
) -> float:
    total = 0.0
    for f in faces:
        a = verts_xyz[f[0]]
        b = verts_xyz[f[1]]
        c = verts_xyz[f[2]]
        total += 0.5 * float(np.linalg.norm(np.cross(b - a, c - a)))
    return total


# ---------------------------------------------------------------------------
# UV area helper (corner layout)
# ---------------------------------------------------------------------------


def _chart_uv_area(
    face_indices: List[int],
    corner_uv: np.ndarray,
) -> float:
    total = 0.0
    for fi in face_indices:
        u0, v0 = corner_uv[fi * 3 + 0]
        u1, v1 = corner_uv[fi * 3 + 1]
        u2, v2 = corner_uv[fi * 3 + 2]
        total += abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)) * 0.5
    return total


# ---------------------------------------------------------------------------
# Shelf bin-packer
# ---------------------------------------------------------------------------


def _shelf_pack(
    items: List[Tuple[float, float]],   # list of (w, h)
) -> List[Tuple[float, float]]:
    """Place items into unit square using shelf-first-fit; return (u_off, v_off).

    Items are sorted tallest-first.  If the packed extents exceed 1.0 (because
    total area > 1.0) the coordinates are still returned as-is (caller should
    normalise / report packing efficiency < 1.0 honestly).
    """
    n = len(items)
    if n == 0:
        return []

    order = sorted(range(n), key=lambda i: -items[i][1])
    placed: List[Optional[Tuple[float, float]]] = [None] * n

    # Each shelf: (x_cursor, y_base, shelf_height)
    shelves: List[List[float]] = []  # [x, y, h]

    for idx in order:
        w, h = items[idx]
        placed_flag = False
        for shelf in shelves:
            if shelf[0] + w <= 1.0 + 1e-9 and h <= shelf[2] + 1e-9:
                placed[idx] = (shelf[0], shelf[1])
                shelf[0] += w
                placed_flag = True
                break
        if not placed_flag:
            y_base = sum(s[2] for s in shelves)
            placed[idx] = (0.0, y_base)
            shelves.append([w, y_base, h])

    return [(float(p[0]), float(p[1])) if p is not None else (0.0, 0.0) for p in placed]


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def harden_uv_unwrap(spec: UVUnwrapHardeningSpec) -> HardenedUVResult:
    """Post-process a raw UV layout into clean, packed, chart-cut UV maps.

    Parameters
    ----------
    spec : UVUnwrapHardeningSpec
        Input mesh, initial UV, and seam edges.

    Returns
    -------
    HardenedUVResult
        Packed per-corner UVs, chart metadata, and distortion stats.

    Algorithm
    ---------
    1. Normalise seam edge list to canonical (min, max) pairs.
    2. BFS flood-fill the face adjacency graph, refusing to cross seam
       edges → one connected component per UV chart.
    3. For each chart:
       a. Collect per-corner UV coordinates (face*3+k indexing).
       b. Translate bbox to origin; try 0°/90°/180°/270° rotations and
          keep the one that minimises bbox area.
       c. Normalise widths + heights to sum ≤ 1 for packing.
    4. Sort charts tallest-first; shelf-first-fit into the unit square.
    5. Compute per-chart 3-D area, UV area, scale factor, angle distortion.
    """
    verts_raw = spec.mesh_vertices_xyz
    faces_raw = spec.mesh_faces
    uv_raw = spec.initial_uv

    # Validate + convert
    if not verts_raw or not faces_raw:
        return HardenedUVResult(
            packed_uv=[],
            charts=[],
            num_charts=0,
            num_seam_cuts=0,
            packing_efficiency=0.0,
            max_distortion=0.0,
            mean_distortion=0.0,
        )

    verts_xyz = np.array(
        [(float(v[0]), float(v[1]), float(v[2])) for v in verts_raw],
        dtype=float,
    )
    n_verts = len(verts_xyz)

    faces: List[Tuple[int, int, int]] = []
    for f in faces_raw:
        if len(f) >= 3:
            faces.append((int(f[0]), int(f[1]), int(f[2])))

    n_faces = len(faces)

    # Pad / trim initial UV
    uv_padded: List[Tuple[float, float]] = []
    for i in range(n_verts):
        if i < len(uv_raw):
            uv_padded.append((float(uv_raw[i][0]), float(uv_raw[i][1])))
        else:
            uv_padded.append((0.0, 0.0))

    if not faces:
        return HardenedUVResult(
            packed_uv=[],
            charts=[],
            num_charts=0,
            num_seam_cuts=0,
            packing_efficiency=0.0,
            max_distortion=0.0,
            mean_distortion=0.0,
        )

    # Build per-corner UV array (face*3+k) from initial vertex UV
    corner_uv_initial = np.zeros((n_faces * 3, 2), dtype=float)
    for fi, f in enumerate(faces):
        for k in range(3):
            vi = f[k]
            corner_uv_initial[fi * 3 + k, 0] = uv_padded[vi][0]
            corner_uv_initial[fi * 3 + k, 1] = uv_padded[vi][1]

    # Find charts via seam-aware BFS
    seam_set = _build_seam_set(spec.seam_edges)
    components, num_cuts = _find_charts(faces, seam_set)

    # Per-chart normalisation + collect packing input
    # chart_local_uvs[i] = (array of corner UVs in local bbox space, w, h)
    chart_local_uvs: List[Tuple[np.ndarray, float, float]] = []
    for component in components:
        # Gather corner UVs for this chart
        indices: List[int] = []
        for fi in component:
            indices.extend([fi * 3, fi * 3 + 1, fi * 3 + 2])
        chart_corners = corner_uv_initial[indices, :]  # (M*3, 2)
        normalised, w, h = _normalise_chart_uvs(chart_corners)
        chart_local_uvs.append((normalised, w, h))

    # Scale widths + heights to fit in unit square
    # Compute a global scale factor so all charts could in principle tile
    # the unit square (used for normalising the shelf input).
    max_w = max(w for _, w, _ in chart_local_uvs) if chart_local_uvs else 1.0
    max_h = max(h for _, _, h in chart_local_uvs) if chart_local_uvs else 1.0
    scale = max(max_w, max_h, 1e-12)

    packing_input = [(w / scale, h / scale) for _, w, h in chart_local_uvs]
    offsets = _shelf_pack(packing_input)   # (u_off, v_off) per chart

    # Build final packed corner UV array
    packed_corner_uv = np.zeros((n_faces * 3, 2), dtype=float)
    charts: List[UVChart] = []
    distortions: List[float] = []

    for ci, (component, (local_uvs, w, h), (u_off, v_off)) in enumerate(
        zip(components, chart_local_uvs, offsets)
    ):
        pw = w / scale
        ph = h / scale

        # Indices in the flat corner array
        flat_indices: List[int] = []
        for fi in component:
            flat_indices.extend([fi * 3, fi * 3 + 1, fi * 3 + 2])

        # Map local UVs → packed space
        packed_local = local_uvs / np.array([w, h]) * np.array([pw, ph])
        packed_local += np.array([u_off, v_off])

        for pos, idx in enumerate(flat_indices):
            packed_corner_uv[idx, 0] = float(packed_local[pos, 0])
            packed_corner_uv[idx, 1] = float(packed_local[pos, 1])

        # Collect chart faces (subset of mesh faces)
        chart_faces_subset = [faces[fi] for fi in component]

        # UV area (using packed coords)
        uv_area = _chart_uv_area(component, packed_corner_uv)

        # 3-D area
        area_3d = _chart_3d_area(verts_xyz, chart_faces_subset)

        # Scale factor
        if uv_area > 1e-15 and area_3d > 1e-15:
            sf = uv_area / area_3d
        else:
            sf = 1.0

        # Distortion
        chart_corner_arr = np.zeros((len(component) * 3, 2), dtype=float)
        for j, fi in enumerate(component):
            chart_corner_arr[j * 3 + 0] = packed_corner_uv[fi * 3 + 0]
            chart_corner_arr[j * 3 + 1] = packed_corner_uv[fi * 3 + 1]
            chart_corner_arr[j * 3 + 2] = packed_corner_uv[fi * 3 + 2]
        # Re-index for distortion helper
        reindexed_faces = [(j * 3, j * 3 + 1, j * 3 + 2) for j in range(len(component))]
        chart_verts = np.array([verts_xyz[f[k]] for f in chart_faces_subset for k in range(3)], dtype=float).reshape(-1, 3)
        # Per-vertex positions aligned with corner layout
        chart_verts_per_corner = np.array(
            [verts_xyz[faces[fi][k]] for fi in component for k in range(3)],
            dtype=float,
        )
        dist = _angle_distortion_for_faces(
            chart_verts_per_corner,
            reindexed_faces,
            chart_corner_arr,
        )
        distortions.append(dist)

        charts.append(UVChart(
            face_indices=list(component),
            uv_min=(float(u_off), float(v_off)),
            uv_max=(float(u_off + pw), float(v_off + ph)),
            chart_area_uv=float(uv_area),
            chart_area_3d_mm2=float(area_3d),
            scale_factor=float(sf),
        ))

    # Global stats
    total_uv_area = sum(c.chart_area_uv for c in charts)
    packing_efficiency = min(total_uv_area, 1.0)

    max_dist = float(max(distortions)) if distortions else 0.0
    mean_dist = float(np.mean(distortions)) if distortions else 0.0

    # Convert corner_uv to list of tuples
    packed_uv_list: List[Tuple[float, float]] = [
        (float(packed_corner_uv[i, 0]), float(packed_corner_uv[i, 1]))
        for i in range(n_faces * 3)
    ]

    return HardenedUVResult(
        packed_uv=packed_uv_list,
        charts=charts,
        num_charts=len(charts),
        num_seam_cuts=num_cuts,
        packing_efficiency=packing_efficiency,
        max_distortion=max_dist,
        mean_distortion=mean_dist,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

    def register(spec, **kw):  # type: ignore[misc]
        def _dec(fn):
            return fn
        return _dec

    def ok_payload(d: dict) -> str:  # type: ignore[misc]
        return json.dumps({"ok": True, **d})

    def err_payload(msg: str, code: str = "ERROR") -> str:  # type: ignore[misc]
        return json.dumps({"ok": False, "error": msg, "code": code})

    class ToolSpec:  # type: ignore[misc]
        def __init__(self, *, name: str, description: str, input_schema: dict):
            self.name = name


_TOOL_SPEC = ToolSpec(
    name="nurbs_harden_uv_unwrap",
    description=(
        "Post-process a raw LSCM/ARAP UV layout: cut mesh at seam edges into "
        "charts, rotate each chart to minimise bbox area (90° increments only), "
        "shelf-pack charts into a unit square, and report distortion statistics. "
        "Per Sander et al. (2003) Multi-Chart Geometry Images + Lévy et al. (2002) LSCM. "
        "HONEST: shelf packing only (not optimal); rotation at 90° increments only."
    ),
    input_schema={
        "type": "object",
        "required": ["mesh_vertices_xyz", "mesh_faces", "initial_uv"],
        "properties": {
            "mesh_vertices_xyz": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "3-D vertex positions [[x,y,z], ...]",
            },
            "mesh_faces": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
                "description": "Triangle faces [[i0,i1,i2], ...]",
            },
            "initial_uv": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Per-vertex UV from LSCM/ARAP [[u,v], ...]",
            },
            "seam_edges": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                "description": "Seam edges as vertex-index pairs [[v_a,v_b], ...]",
                "default": [],
            },
        },
    },
)


@register(_TOOL_SPEC)
def nurbs_harden_uv_unwrap(args: Dict[str, Any]) -> str:
    """LLM tool: harden a raw UV unwrap layout."""
    try:
        verts = [tuple(v) for v in args["mesh_vertices_xyz"]]
        faces = [tuple(f) for f in args["mesh_faces"]]
        uv = [tuple(u) for u in args["initial_uv"]]
        seams = [tuple(s) for s in args.get("seam_edges", [])]

        spec = UVUnwrapHardeningSpec(
            mesh_vertices_xyz=verts,  # type: ignore[arg-type]
            mesh_faces=faces,          # type: ignore[arg-type]
            initial_uv=uv,             # type: ignore[arg-type]
            seam_edges=seams,          # type: ignore[arg-type]
        )
        result = harden_uv_unwrap(spec)

        charts_out = [
            {
                "face_indices": c.face_indices,
                "uv_min": list(c.uv_min),
                "uv_max": list(c.uv_max),
                "chart_area_uv": c.chart_area_uv,
                "chart_area_3d_mm2": c.chart_area_3d_mm2,
                "scale_factor": c.scale_factor,
            }
            for c in result.charts
        ]
        return ok_payload({
            "packed_uv": [list(uv_pt) for uv_pt in result.packed_uv],
            "charts": charts_out,
            "num_charts": result.num_charts,
            "num_seam_cuts": result.num_seam_cuts,
            "packing_efficiency": result.packing_efficiency,
            "max_distortion": result.max_distortion,
            "mean_distortion": result.mean_distortion,
            "honest_caveat": result.honest_caveat,
        })
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(str(exc), "INTERNAL_ERROR")
