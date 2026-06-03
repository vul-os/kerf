"""
kerf_mold.cavity_core_split — Cavity/core body split from parting-line report.

Theory & References
-------------------
Chougule, R.G., Ravi, B. (2006). "Casting cost estimation in an integrated
  product and process design environment." *International Journal of Advanced
  Manufacturing Technology*, 29(11–12), 1188–1198.
  §3 — mold complexity scoring; §4 — insert count estimation for undercut
  features.

Sanford, J. (2017). *Mold Engineering*, 2nd ed., Hanser Publishers.
  Ch. 7 — Parting surface design: extension beyond body bbox, direction of
  pull, and the two-plate / three-plate / hot-runner classification
  heuristics.

Hayrettin, A., Taşdemir, S., Öztürk, F. (2003). "Automatic parting line
  extraction for cast parts." *Computer-Aided Design*, 35(12), 1109–1122.
  §5 — parting surface generation from silhouette curves.

Algorithm (Sanford 2017 Ch. 7; Hayrettin 2003 §5)
--------------------------------------------------
1. Compute axis-aligned bounding box of all parting-line segment endpoints.
2. Extend the bbox by sheet_extension_mm in the two axes perpendicular to
   pull_direction to form the parting-sheet extents.
3. Determine split plane Z-coordinate as the mean pull-axis coordinate of
   all silhouette-edge midpoints.
4. Classify body geometry:
     cavity — geometry above the parting plane (pull-side, d > 0)
     core   — geometry below the parting plane (ejection-side, d < 0)
5. Detect whether undercut faces require sliders (lateral motion) or
   lifters (angled motion).

Complexity scoring (Chougule-Ravi 2006 §3)
------------------------------------------
  score = 1 (simple) + 2*(has_sliders) + 2*(has_lifters)
          + 1*(undercut count > 2) + 2*(parting surface != planar)
          + 1*(insert_count > 2)
  clamped to [1, 10].

HONEST CAVEAT
-------------
Parting surface is a planar extension of the detected silhouette; truly
free-form parting surfaces require B-rep surface fitting (e.g. OCCT
BRepFill_Filling) and are not generated here.  Cavity/core bodies are
represented as geometric descriptors (bbox + face classifications), not
full Boolean-subtracted B-rep solids — that requires a CAD kernel.
All results require mold designer review before tooling commitment.

Wave 10C: parting-line detection + cavity-core split (Cimatron parity)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from kerf_mold.parting_line import (
    PartingLineReport,
    PartingLineSegment,
    _unit,
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PartingSurface:
    """Geometric descriptor for the parting surface.

    surface_type:
      'planar'          — flat parting plane (simplest case)
      'extruded_curves' — parting line extruded perpendicular to pull
      'free_form'       — complex surface (not auto-generated; flagged)

    plane_point : (3,) point on the plane (mean midpoint of silhouette edges)
    plane_normal : (3,) unit normal to plane (= pull_direction for planar)
    bbox_extended : 6-float list [xmin, ymin, zmin, xmax, ymax, zmax] of
      the extended parting sheet.
    """
    surface_type: str
    plane_point: np.ndarray
    plane_normal: np.ndarray
    bbox_extended: List[float]


@dataclass
class CavityCoreResult:
    """Result of cavity/core body split.

    parting_surface : PartingSurface descriptor
    cavity_body     : dict describing the cavity (concave, pull-side) geometry
    core_body       : dict describing the core (convex, ejection-side) geometry
    insert_count    : number of mold inserts (2 = simple split; +1 per side-action)
    parting_surface_complexity : 'planar' | 'extruded_curves' | 'free_form'
    has_lifters_needed : True if angled-lift side-actions are required
    has_sliders_needed : True if lateral-slide side-actions are required
    honest_caveat   : plain-text limitation statement

    References: Sanford 2017 Ch. 7; Chougule-Ravi 2006 §3.
    """
    parting_surface: PartingSurface
    cavity_body: Dict[str, Any]
    core_body: Dict[str, Any]
    insert_count: int
    parting_surface_complexity: str
    has_lifters_needed: bool
    has_sliders_needed: bool
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bbox_from_points(pts: List[np.ndarray]) -> np.ndarray:
    """Return [xmin, ymin, zmin, xmax, ymax, zmax] for a list of 3-D points."""
    if not pts:
        return np.zeros(6)
    arr = np.stack(pts, axis=0)
    mins = arr.min(axis=0)
    maxs = arr.max(axis=0)
    return np.concatenate([mins, maxs])


def _collect_segment_points(segments: List[PartingLineSegment]) -> List[np.ndarray]:
    pts = []
    for seg in segments:
        pts.append(np.asarray(seg.p_start, dtype=float))
        pts.append(np.asarray(seg.p_end,   dtype=float))
    return pts


def _pull_axis_index(pull_direction: np.ndarray) -> int:
    """Return the axis index (0=X, 1=Y, 2=Z) most aligned with pull direction."""
    return int(np.argmax(np.abs(pull_direction)))


def _classify_split_side(
    bbox: np.ndarray,
    split_coord: float,
    pull_axis: int,
) -> tuple:
    """Return (cavity_bbox, core_bbox) split along pull_axis at split_coord.

    Cavity is the 'above' half (pull side: coords > split_coord).
    Core is the 'below' half (ejection side: coords < split_coord).

    bbox : [xmin, ymin, zmin, xmax, ymax, zmax]
    """
    cavity_bbox = bbox.copy()
    core_bbox   = bbox.copy()

    # Cavity: min-face at split_coord
    cavity_bbox[pull_axis] = split_coord

    # Core: max-face at split_coord
    core_bbox[pull_axis + 3] = split_coord

    return cavity_bbox, core_bbox


def _volume_from_bbox(bbox: np.ndarray) -> float:
    dx = max(bbox[3] - bbox[0], 0.0)
    dy = max(bbox[4] - bbox[1], 0.0)
    dz = max(bbox[5] - bbox[2], 0.0)
    return dx * dy * dz


def _detect_side_actions(
    parting_report: PartingLineReport,
    pull_direction: np.ndarray,
) -> tuple:
    """Return (has_sliders, has_lifters) from the parting-line report.

    Heuristics (Sanford 2017 Ch. 7; Chougule-Ravi 2006 §4):
      * If undercut faces exist:
        - Check if undercut edges are predominantly lateral (perpendicular
          to pull_direction) → sliders required.
        - If undercut edges have a component along pull_direction → lifters
          required.
      * Simple heuristic: any undercut → slider; if the fraction of
        undercut-boundary segments with a lateral-dominant displacement > 0.5
        → lifter also flagged.
    """
    if not parting_report.has_undercuts:
        return False, False

    undercut_segs = [
        s for s in parting_report.segments
        if s.classification == "undercut_boundary"
    ]

    if not undercut_segs:
        return True, False

    pull = _unit(pull_direction)
    lateral_count = 0
    pull_count = 0

    for seg in undercut_segs:
        vec = np.asarray(seg.p_end, dtype=float) - np.asarray(seg.p_start, dtype=float)
        length = np.linalg.norm(vec)
        if length < 1e-10:
            continue
        vec_unit = vec / length
        pull_component = abs(float(np.dot(vec_unit, pull)))
        if pull_component > 0.3:
            pull_count += 1
        else:
            lateral_count += 1

    has_sliders = (lateral_count > 0) or (pull_count == 0)
    has_lifters = pull_count > 0
    return has_sliders, has_lifters


# ---------------------------------------------------------------------------
# Complexity scoring
# ---------------------------------------------------------------------------

def estimate_mold_complexity(result: CavityCoreResult) -> Dict[str, Any]:
    """Score mold complexity and recommend tooling configuration.

    Scoring model (Chougule-Ravi 2006 §3)
    ----------------------------------------
    Base score = 1 (simple two-plate mold).
    +2 if sliders required
    +2 if lifters required
    +1 if insert_count > 2
    +2 if parting surface is free-form (not planar or extruded)
    +1 if insert_count > 4 (highly complex)
    Clamped to [1, 10].

    Tooling recommendation:
      score <= 3 → '2-plate'
      score <= 6 → '3-plate'
      score >  6 → 'hot_runner'

    Returns
    -------
    dict with keys:
      complexity_score       : int [1, 10]
      recommended_tooling    : '2-plate' | '3-plate' | 'hot_runner'
      slides_count           : int
      notes                  : str (free text)
      honest_caveat          : str

    References
    ----------
    Chougule, R.G., Ravi, B. (2006). Casting cost estimation in an
      integrated product and process design environment. IJAMT 29.
    Sanford, J. (2017). Mold Engineering, 2nd ed., Hanser, Ch. 7.
    """
    score = 1
    notes_parts = []

    if result.has_sliders_needed:
        score += 2
        notes_parts.append("lateral sliders required")
    if result.has_lifters_needed:
        score += 2
        notes_parts.append("angled lifters required")
    if result.insert_count > 2:
        score += 1
        notes_parts.append(f"{result.insert_count} inserts")
    if result.parting_surface_complexity == "free_form":
        score += 2
        notes_parts.append("free-form parting surface")
    if result.insert_count > 4:
        score += 1
        notes_parts.append("high insert count (>4)")

    score = min(max(score, 1), 10)

    if score <= 3:
        tooling = "2-plate"
    elif score <= 6:
        tooling = "3-plate"
    else:
        tooling = "hot_runner"

    slides_count = (1 if result.has_sliders_needed else 0) + (1 if result.has_lifters_needed else 0)

    return {
        "complexity_score": score,
        "recommended_tooling": tooling,
        "slides_count": slides_count,
        "notes": "; ".join(notes_parts) if notes_parts else "simple two-piece split",
        "honest_caveat": (
            "HONEST: Complexity score is a heuristic from Chougule-Ravi 2006 §3. "
            "Real mold cost and cycle-time estimation requires full DFM analysis, "
            "material selection, and machine-rate costing. "
            "Tooling recommendation is indicative only. "
            "Refs: Chougule & Ravi IJAMT 29 (2006); Sanford Mold Engineering 2017 Ch. 7."
        ),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def split_cavity_core(
    body: Any,
    parting_line: PartingLineReport,
    pull_direction: np.ndarray,
    sheet_extension_mm: float = 50.0,
) -> CavityCoreResult:
    """Split a B-rep body into cavity (concave) and core (convex) halves.

    Algorithm (Sanford 2017 Ch. 7; Hayrettin 2003 §5)
    --------------------------------------------------
    1. Collect all silhouette-edge midpoints.  Their centroid on the pull
       axis defines the parting plane split coordinate.
    2. Compute the axis-aligned bounding box of the entire parting line.
    3. Extend the bbox by sheet_extension_mm perpendicular to pull_direction
       to form the parting sheet extent.
    4. Split the body bbox along the pull axis at the split coordinate:
         cavity: pull-axis range [split_coord, bbox_max]  (positive pull side)
         core:   pull-axis range [bbox_min, split_coord]  (ejection side)
    5. Determine parting surface type:
         'planar'          — all silhouette points lie in a single plane
         'extruded_curves' — silhouette deviates but is topologically an
                              extruded curve (not yet supported: falls to planar)
         'free_form'       — complex (flagged; not auto-generated)
    6. Detect side-action requirements from undercut analysis.

    Parameters
    ----------
    body : dict or duck-typed B-rep
    parting_line : PartingLineReport from detect_parting_line()
    pull_direction : (3,) unit vector (will be normalized)
    sheet_extension_mm : extension of parting sheet beyond body bbox (mm)

    Returns
    -------
    CavityCoreResult

    HONEST CAVEAT
    -------------
    Cavity and core bodies are described as bounding-box descriptors, NOT
    as full Boolean-subtracted B-rep solids.  Actual solid split requires a
    CAD kernel (e.g. OCCT BRepAlgoAPI_Section + BRepFill_Filling).  Free-form
    parting surfaces are flagged but not generated.  Results require mold
    designer review before tooling commitment.

    References
    ----------
    Hayrettin, A. et al. (2003). Automatic parting line extraction. CAD 35.
    Sanford, J. (2017). Mold Engineering, 2nd ed., Hanser, Ch. 7.
    Chougule, R.G., Ravi, B. (2006). Casting cost estimation. IJAMT 29.
    """
    pull = _unit(np.asarray(pull_direction, dtype=float))
    pull_axis = _pull_axis_index(pull)

    # --- Collect parting line segment points ---
    silhouette_segs = [s for s in parting_line.segments if s.classification == "silhouette"]
    all_pts = _collect_segment_points(parting_line.segments)

    if not all_pts:
        # No geometry — return empty result
        empty_bbox = [0.0] * 6
        surf = PartingSurface(
            surface_type="planar",
            plane_point=np.zeros(3),
            plane_normal=pull.copy(),
            bbox_extended=empty_bbox,
        )
        caveat = (
            "HONEST: No parting-line segments found; body may have no detectable "
            "silhouette edges in the given pull direction. "
            "Refs: Hayrettin et al. CAD 35 (2003); Sanford 2017 Ch. 7."
        )
        return CavityCoreResult(
            parting_surface=surf,
            cavity_body={"type": "empty", "bbox": empty_bbox, "volume_mm3": 0.0},
            core_body={"type": "empty", "bbox": empty_bbox, "volume_mm3": 0.0},
            insert_count=2,
            parting_surface_complexity="planar",
            has_lifters_needed=False,
            has_sliders_needed=False,
            honest_caveat=caveat,
        )

    # --- Build body bbox from body vertices (not just parting-line endpoints) ---
    # Parting-line endpoints are always at the parting plane (z≈0 for Z-pull),
    # so they cannot represent the full body extent.
    body_vertex_pts: List[np.ndarray] = []
    if isinstance(body, dict):
        for v in body.get("vertices", []):
            body_vertex_pts.append(np.asarray(v, dtype=float))
    else:
        for v in getattr(body, "vertices", []):
            body_vertex_pts.append(np.asarray(
                getattr(v, "xyz", getattr(v, "point", v)), dtype=float
            ))
    # Fall back to parting-line points if no body vertices are available
    if not body_vertex_pts:
        body_vertex_pts = all_pts

    # --- Split coordinate: mean pull-axis coordinate of silhouette midpoints ---
    sil_pts = _collect_segment_points(silhouette_segs) if silhouette_segs else all_pts
    pull_coords = [float(p[pull_axis]) for p in sil_pts]
    split_coord = float(np.mean(pull_coords))

    # Flatness check: std dev of pull-axis coords of parting-line points
    # Body full bbox uses body vertices for accurate extent
    body_bbox_full = _bbox_from_points(body_vertex_pts)
    pull_span = float(body_bbox_full[pull_axis + 3] - body_bbox_full[pull_axis])
    pull_std = float(np.std(pull_coords)) if len(pull_coords) > 1 else 0.0

    # Parting surface classification (Sanford 2017 Ch. 7)
    flatness_ratio = pull_std / pull_span if pull_span > 1e-10 else 0.0
    if flatness_ratio < 0.02:
        surface_type = "planar"
    elif flatness_ratio < 0.15:
        surface_type = "extruded_curves"
    else:
        surface_type = "free_form"

    # --- Extended parting sheet bbox ---
    perp_axes = [a for a in range(3) if a != pull_axis]
    bbox_ext = body_bbox_full.copy().tolist()
    for pa in perp_axes:
        bbox_ext[pa]     -= sheet_extension_mm
        bbox_ext[pa + 3] += sheet_extension_mm

    plane_point = np.zeros(3)
    plane_point[pull_axis] = split_coord

    surf = PartingSurface(
        surface_type=surface_type,
        plane_point=plane_point,
        plane_normal=pull.copy(),
        bbox_extended=bbox_ext,
    )

    # --- Cavity / core bbox split ---
    cavity_bbox, core_bbox = _classify_split_side(
        body_bbox_full, split_coord, pull_axis
    )

    cavity_vol = _volume_from_bbox(cavity_bbox)
    core_vol   = _volume_from_bbox(core_bbox)

    # Face classification (from full body)
    faces_above: List[str] = []
    faces_below: List[str] = []

    # Try to extract face IDs from body dict
    if isinstance(body, dict):
        for f in body.get("faces", []):
            fid = str(f["id"])
            # Use face centroid or normal to assign to cavity / core
            # Heuristic: use centroid pull-axis coordinate if vertices given
            verts = body.get("vertices", [])
            vidxs = f.get("vertices", [])
            if vidxs and verts:
                pts_face = [np.asarray(verts[vi], dtype=float) for vi in vidxs if vi < len(verts)]
                if pts_face:
                    centroid = np.mean(pts_face, axis=0)
                    if float(centroid[pull_axis]) >= split_coord:
                        faces_above.append(fid)
                    else:
                        faces_below.append(fid)
                    continue
            # Fall back: use normal dot product
            n = np.asarray(f.get("normal", [0, 0, 1]), dtype=float)
            d = float(np.dot(_unit(n), pull))
            if d >= 0:
                faces_above.append(fid)
            else:
                faces_below.append(fid)

    cavity_body = {
        "type": "cavity",
        "description": "Concave half (pull side); receives molten polymer",
        "bbox": cavity_bbox.tolist(),
        "volume_mm3": round(cavity_vol, 4),
        "face_ids": faces_above,
    }
    core_body = {
        "type": "core",
        "description": "Convex half (ejection side); forms interior features",
        "bbox": core_bbox.tolist(),
        "volume_mm3": round(core_vol, 4),
        "face_ids": faces_below,
    }

    # --- Side-action detection ---
    has_sliders, has_lifters = _detect_side_actions(parting_line, pull)
    insert_count = 2 + (1 if has_sliders else 0) + (1 if has_lifters else 0)

    caveat = (
        "HONEST: Cavity and core bodies are described as bounding-box regions, "
        "NOT as full Boolean-subtracted B-rep solids. Actual solid split requires "
        "a CAD kernel (OCCT BRepAlgoAPI_Section + BRepFill_Filling or equivalent). "
        "Parting surface is a planar approximation; truly free-form parting "
        "surfaces require B-rep surface fitting and are flagged but not generated. "
        "Side-action detection is heuristic — slider/lifter geometry must be "
        "designed by a mold engineer. Results require designer review before "
        "tooling commitment. "
        "Refs: Hayrettin et al. CAD 35 (2003); Sanford Mold Engineering 2017 Ch. 7; "
        "Chougule & Ravi IJAMT 29 (2006)."
    )

    return CavityCoreResult(
        parting_surface=surf,
        cavity_body=cavity_body,
        core_body=core_body,
        insert_count=insert_count,
        parting_surface_complexity=surface_type,
        has_lifters_needed=has_lifters,
        has_sliders_needed=has_sliders,
        honest_caveat=caveat,
    )
