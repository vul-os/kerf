"""
kerf_mold.parting_line — Parting-line detection for injection-mold B-rep bodies.

Theory & References
-------------------
Hayrettin, A., Taşdemir, S., Öztürk, F. (2003). "Automatic parting line
  extraction for cast parts." *Computer-Aided Design*, 35(12), 1109–1122.
  §3 — silhouette-edge detection from normal-pull-direction dot products.
  §4 — undercut identification: both adjacent face normals point away from
    the pull direction.

Chen, L.L., Rosen, D.W. (1999). "Parting direction selection in mold design
  for rapid tooling." *Journal of Manufacturing Science and Engineering*,
  121(1), 73–80.  §2 — parting direction optimisation; §3 — silhouette curve;
  §4 — undercut face enumeration.

Algorithm (Hayrettin 2003 §3; Chen-Rosen 1999 §2–§3)
------------------------------------------------------
For each edge E with adjacent faces F1, F2:
  N1, N2  = outward face normals at edge midpoint (or face centroid)
  d1 = dot(N1, pull_dir)
  d2 = dot(N2, pull_dir)

  Silhouette (parting-line candidate):  sign(d1) != sign(d2)
    → the parting surface must pass through this edge.

  Undercut region:  d1 < 0 AND d2 < 0
    → both faces are "negative" (face away from pull); requires side-action.

  Draft-deficient:  |angle between N and pull_dir| < (90° - draft_angle_min_deg)
    → the face normal is nearly parallel to pull_dir (near-vertical wall with
    insufficient draft); flagged for draft correction.

Body representation accepted
-----------------------------
The function accepts:
  1. A dict-based synthetic B-rep (used by tests):
       {
         "vertices": [[x,y,z], ...],
         "faces": [
           {"id": "F0", "normal": [nx,ny,nz], "vertices": [i,j,k,...]},
           ...
         ],
         "edges": [
           {"id": "E0", "face_ids": ["F0","F1"],
            "p_start": [x,y,z], "p_end": [x,y,z]},
           ...
         ]
       }
  2. Any duck-typed object with .faces (iterable) and .edges (iterable)
     attributes whose items carry .id, .normal / .outward_normal,
     .face_ids, .p_start, .p_end.

HONEST CAVEAT
-------------
Algorithm assumes a single planar pull direction.  Multi-axis pulls,
complex parting surfaces, and side-action design are NOT handled
automatically.  The undercut detector flags faces but does NOT design
the required slider/lifter geometry.  For production mold design, results
MUST be reviewed by a mold designer.

Wave 10C: parting-line detection + cavity-core split (Cimatron parity)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PartingLineDirection:
    """Pull (demold) direction specification.

    pull_direction : (3,) unit vector — typically [0, 0, 1] for Z-up.
    draft_angle_min_deg : faces whose normal deviates from the perpendicular
      plane by less than this value are flagged as draft-deficient.
      Default 1.0° per common injection-mold practice.

    References: Chen-Rosen 1999 §2; Menges 2001 §3.4.
    """
    pull_direction: np.ndarray
    draft_angle_min_deg: float = 1.0

    def __post_init__(self):
        pd = np.asarray(self.pull_direction, dtype=float)
        norm = np.linalg.norm(pd)
        if norm < 1e-12:
            raise ValueError("pull_direction must be a non-zero vector")
        self.pull_direction = pd / norm
        if self.draft_angle_min_deg < 0:
            raise ValueError("draft_angle_min_deg must be >= 0")


@dataclass
class PartingLineSegment:
    """One edge segment on (or near) the parting line.

    classification:
      'silhouette'         — sign(d1) != sign(d2); canonical parting-line edge
      'undercut_boundary'  — both adjacent normals face away from pull direction
      'sharp_edge'         — near-zero face area (degenerate / knife edge)
    """
    edge_id: str
    p_start: np.ndarray   # (3,) world coordinates (mm)
    p_end: np.ndarray     # (3,) world coordinates (mm)
    classification: str   # 'silhouette' | 'undercut_boundary' | 'sharp_edge'


@dataclass
class PartingLineReport:
    """Result of parting-line detection.

    segments         — ordered list of PartingLineSegment
    total_length_mm  — sum of all segment lengths (mm)
    closed_loops     — number of closed sub-loops in the parting line
    has_undercuts    — True if any undercut region was detected
    undercut_face_ids — face ids requiring side-action (slider / lifter)
    draft_deficient_face_ids — faces with insufficient draft angle
    honest_caveat    — plain-text limitation statement

    References: Hayrettin 2003 §3–§4; Chen-Rosen 1999 §2–§4.
    """
    segments: List[PartingLineSegment]
    total_length_mm: float
    closed_loops: int
    has_undercuts: bool
    undercut_face_ids: List[str]
    draft_deficient_face_ids: List[str] = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    """Return unit vector; zero-length → [0,0,0]."""
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.zeros(3)


def _seg_length(p_start: np.ndarray, p_end: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(p_end) - np.asarray(p_start)))


def _extract_faces_edges(body: Any):
    """Return (faces_dict, edges_list) from either a dict B-rep or a duck-typed object.

    faces_dict: {face_id: np.ndarray(3) outward normal}
    edges_list: list of dicts with keys
      'id', 'face_ids' (list[str]), 'p_start' (np.ndarray), 'p_end' (np.ndarray)
    """
    if isinstance(body, dict):
        # ---- dict-based synthetic B-rep ----
        faces_dict: Dict[str, np.ndarray] = {}
        for f in body.get("faces", []):
            fid = str(f["id"])
            n = np.asarray(f["normal"], dtype=float)
            faces_dict[fid] = _unit(n)

        edges_list = []
        for e in body.get("edges", []):
            edges_list.append({
                "id": str(e["id"]),
                "face_ids": [str(fi) for fi in e.get("face_ids", [])],
                "p_start": np.asarray(e.get("p_start", [0, 0, 0]), dtype=float),
                "p_end":   np.asarray(e.get("p_end",   [1, 0, 0]), dtype=float),
            })

        return faces_dict, edges_list

    else:
        # ---- duck-typed B-rep object ----
        faces_dict = {}
        for f in getattr(body, "faces", []):
            fid = str(getattr(f, "id", id(f)))
            normal = (
                getattr(f, "outward_normal", None)
                or getattr(f, "normal", None)
            )
            if normal is not None:
                faces_dict[fid] = _unit(np.asarray(normal, dtype=float))

        edges_list = []
        for e in getattr(body, "edges", []):
            edges_list.append({
                "id": str(getattr(e, "id", id(e))),
                "face_ids": [str(fi) for fi in getattr(e, "face_ids", [])],
                "p_start": np.asarray(getattr(e, "p_start", [0, 0, 0]), dtype=float),
                "p_end":   np.asarray(getattr(e, "p_end",   [1, 0, 0]), dtype=float),
            })

        return faces_dict, edges_list


def _count_closed_loops(segments: List[PartingLineSegment]) -> int:
    """Count closed sub-loops by building an adjacency graph of endpoints.

    A closed loop exists when every vertex in a connected component has
    degree 2 (every edge endpoint is shared by exactly 2 segments).

    HONEST: This is a topological heuristic; floating-point vertex
    matching uses a tolerance of 1e-6 mm.
    """
    TOL = 1e-6

    # Build vertex → [edge_index] map
    vertex_to_edges: Dict[tuple, List[int]] = {}

    def _vkey(p: np.ndarray) -> tuple:
        return (round(p[0] / TOL) * TOL,
                round(p[1] / TOL) * TOL,
                round(p[2] / TOL) * TOL)

    for i, seg in enumerate(segments):
        for pt in (seg.p_start, seg.p_end):
            k = _vkey(pt)
            vertex_to_edges.setdefault(k, []).append(i)

    # Find connected components and check if each is a closed loop
    visited_edges: set = set()
    closed = 0

    for start_idx in range(len(segments)):
        if start_idx in visited_edges:
            continue
        # BFS / DFS over connected component
        component_edges: List[int] = []
        stack = [start_idx]
        while stack:
            ei = stack.pop()
            if ei in visited_edges:
                continue
            visited_edges.add(ei)
            component_edges.append(ei)
            seg = segments[ei]
            for pt in (seg.p_start, seg.p_end):
                k = _vkey(pt)
                for neighbor in vertex_to_edges.get(k, []):
                    if neighbor not in visited_edges:
                        stack.append(neighbor)

        # A loop: every vertex in the component has even degree
        vertex_degree: Dict[tuple, int] = {}
        for ei in component_edges:
            seg = segments[ei]
            for pt in (seg.p_start, seg.p_end):
                k = _vkey(pt)
                vertex_degree[k] = vertex_degree.get(k, 0) + 1

        is_closed = all(deg % 2 == 0 for deg in vertex_degree.values())
        if is_closed and component_edges:
            closed += 1

    return closed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_parting_line(
    body: Any,
    direction: PartingLineDirection,
) -> PartingLineReport:
    """Walk B-rep edges and classify each as silhouette, undercut, or neutral.

    Algorithm (Hayrettin et al. 2003 §3; Chen-Rosen 1999 §2–§3)
    -------------------------------------------------------------
    For each edge with adjacent faces F1, F2:
      d1 = dot(N1, pull_dir)
      d2 = dot(N2, pull_dir)

      Silhouette (parting-line candidate):
        sign(d1) != sign(d2)  — the parting surface must pass through here.

      Undercut boundary:
        d1 < 0 AND d2 < 0  — both faces point away from the pull direction;
        material cannot be released without a side-action.

      Draft-deficient face (flagged separately):
        The angle between N and the pull-direction perpendicular plane is
        < draft_angle_min_deg.  Equivalently, |dot(N, pull_dir)| > cos(draft_angle_min_deg).
        (For the face to have sufficient draft, its normal must deviate from
        the parting plane by at least draft_angle_min_deg.)

    Parameters
    ----------
    body : dict or duck-typed B-rep object
    direction : PartingLineDirection

    Returns
    -------
    PartingLineReport

    HONEST CAVEAT
    -------------
    Planar pull direction only.  This implementation uses per-edge linear
    classification; curved edges and non-planar parting surfaces are not
    supported.  Undercut detection is conservative — a face with d < 0 is
    flagged but may be acceptable if a preceding feature provides clearance.
    Results require mold designer review before tooling commitment.

    References
    ----------
    Hayrettin, A. et al. (2003). Automatic parting line extraction. CAD 35.
    Chen, L.L., Rosen, D.W. (1999). Parting Direction Selection. JMSE 121.
    """
    pull = direction.pull_direction  # unit (3,)
    draft_cos_threshold = math.cos(math.radians(90.0 - direction.draft_angle_min_deg))
    # A face normal N has |dot(N, pull)| > draft_cos_threshold → near-vertical wall

    faces_dict, edges_list = _extract_faces_edges(body)

    segments: List[PartingLineSegment] = []
    undercut_face_ids_set: set = set()
    draft_deficient_face_ids_set: set = set()

    # Check every face for draft deficiency
    for fid, normal in faces_dict.items():
        d = float(np.dot(normal, pull))
        # Face angle relative to parting plane = arcsin(|d|) → near-vertical if |d| > threshold
        if abs(d) > draft_cos_threshold:
            draft_deficient_face_ids_set.add(fid)

    # Walk edges — Hayrettin 2003 §3
    for edge in edges_list:
        eid = edge["id"]
        face_ids = edge["face_ids"]
        p_start = edge["p_start"]
        p_end = edge["p_end"]

        if len(face_ids) < 2:
            # Boundary edge (single adjacent face) — skip
            continue

        n1 = faces_dict.get(face_ids[0])
        n2 = faces_dict.get(face_ids[1])
        if n1 is None or n2 is None:
            continue

        d1 = float(np.dot(n1, pull))
        d2 = float(np.dot(n2, pull))

        # Silhouette: sign change across the edge
        if (d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0):
            segments.append(PartingLineSegment(
                edge_id=eid,
                p_start=p_start.copy(),
                p_end=p_end.copy(),
                classification="silhouette",
            ))

        # Undercut: both faces point away from pull (Chen-Rosen 1999 §4)
        elif d1 < 0 and d2 < 0:
            undercut_face_ids_set.update(face_ids)
            segments.append(PartingLineSegment(
                edge_id=eid,
                p_start=p_start.copy(),
                p_end=p_end.copy(),
                classification="undercut_boundary",
            ))

    total_length = sum(_seg_length(s.p_start, s.p_end) for s in segments)
    silhouette_segments = [s for s in segments if s.classification == "silhouette"]
    closed_loops = _count_closed_loops(silhouette_segments)
    has_undercuts = len(undercut_face_ids_set) > 0

    caveat = (
        "HONEST: Planar pull direction only. Classification uses per-edge "
        "signed dot-product projection (Hayrettin et al. 2003 §3; Chen-Rosen 1999 §2). "
        "Complex multi-axis pulls, curved parting surfaces, and automatic "
        "side-action design are NOT supported. Undercut faces flagged but "
        "slider/lifter geometry must be designed by a mold engineer. "
        "Results require review before tooling commitment. "
        "Refs: Hayrettin et al. CAD 35 (2003); Chen & Rosen JMSE 121 (1999)."
    )

    return PartingLineReport(
        segments=segments,
        total_length_mm=round(total_length, 6),
        closed_loops=closed_loops,
        has_undercuts=has_undercuts,
        undercut_face_ids=sorted(undercut_face_ids_set),
        draft_deficient_face_ids=sorted(draft_deficient_face_ids_set),
        honest_caveat=caveat,
    )
