"""
kerf_mold.parting_cavity_tools — LLM tool wrappers for parting-line detection
and cavity/core split.

Tools registered:
  mold_detect_parting_line
    Walk B-rep edges; classify as silhouette / undercut / draft-deficient.
    (Hayrettin et al. 2003; Chen-Rosen 1999)

  mold_split_cavity_core
    Generate parting surface from parting-line report; split body into
    cavity (concave) + core (convex) halves.
    (Sanford 2017 Ch. 7; Chougule-Ravi 2006)

  mold_estimate_mold_complexity
    Return complexity score [1–10] + recommended tooling class.
    (Chougule-Ravi 2006 §3)

HONEST: All three tools operate on synthetic dict-based B-rep inputs.
Production use requires a real B-rep body from kerf_occt.

Wave 10C: parting-line detection + cavity-core split (Cimatron parity)
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.parting_line import (
    PartingLineDirection,
    detect_parting_line,
)
from kerf_mold.cavity_core_split import (
    split_cavity_core,
    estimate_mold_complexity,
)


# ---------------------------------------------------------------------------
# Tool 1: mold_detect_parting_line
# ---------------------------------------------------------------------------

mold_detect_parting_line_spec = ToolSpec(
    name="mold_detect_parting_line",
    description=(
        "Detect the parting line of a B-rep body for a given pull (demold) direction.\n\n"
        "Algorithm (Hayrettin et al. 2003 §3; Chen-Rosen 1999 §2–§3):\n"
        "  For each edge with adjacent faces F1, F2:\n"
        "    d1 = dot(N1, pull_dir), d2 = dot(N2, pull_dir)\n"
        "    sign(d1) != sign(d2) → silhouette edge (parting-line candidate)\n"
        "    d1 < 0 AND d2 < 0   → undercut boundary (side-action required)\n\n"
        "Accepts a synthetic dict B-rep:\n"
        "  body = {\n"
        "    'faces': [{'id': 'F0', 'normal': [0,0,1], 'vertices': [0,1,2,3]}, ...],\n"
        "    'edges': [{'id': 'E0', 'face_ids': ['F0','F1'],\n"
        "               'p_start': [x,y,z], 'p_end': [x,y,z]}, ...],\n"
        "    'vertices': [[x,y,z], ...]\n"
        "  }\n\n"
        "Returns: {ok, segments (list), total_length_mm, closed_loops, has_undercuts,\n"
        "  undercut_face_ids, draft_deficient_face_ids, honest_caveat}.\n\n"
        "HONEST: Planar pull direction only. Does not auto-design side actions.\n"
        "Refs: Hayrettin et al. CAD 35 (2003); Chen & Rosen JMSE 121 (1999)."
    ),
    input_schema={
        "type": "object",
        "required": ["body", "pull_direction"],
        "properties": {
            "body": {
                "type": "object",
                "description": (
                    "Synthetic B-rep body dict with keys 'faces', 'edges', 'vertices'. "
                    "Each face: {id, normal [nx,ny,nz], vertices [idx...]}. "
                    "Each edge: {id, face_ids [fid1,fid2], p_start [x,y,z], p_end [x,y,z]}."
                ),
            },
            "pull_direction": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Pull (demold) direction as [x, y, z]. Will be normalized. Default [0,0,1].",
                "default": [0, 0, 1],
            },
            "draft_angle_min_deg": {
                "type": "number",
                "description": (
                    "Minimum draft angle (degrees). Faces with less than this angle "
                    "relative to the parting plane are flagged as draft-deficient. "
                    "Default 1.0°."
                ),
                "default": 1.0,
                "minimum": 0,
            },
        },
    },
)


async def run_mold_detect_parting_line(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute parting-line detection and return a JSON string."""
    try:
        body = args.get("body")
        if body is None:
            return err_payload("'body' is required", "BAD_ARGS")

        pull_raw = args.get("pull_direction", [0, 0, 1])
        try:
            pull = np.asarray(pull_raw, dtype=float)
            if pull.shape != (3,):
                return err_payload("pull_direction must be a 3-element array", "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"pull_direction parse error: {exc}", "BAD_ARGS")

        draft_deg = float(args.get("draft_angle_min_deg", 1.0))

        direction = PartingLineDirection(
            pull_direction=pull,
            draft_angle_min_deg=draft_deg,
        )

        report = detect_parting_line(body, direction)

        segs_out = [
            {
                "edge_id": s.edge_id,
                "p_start": s.p_start.tolist(),
                "p_end":   s.p_end.tolist(),
                "length_mm": round(
                    float(np.linalg.norm(s.p_end - s.p_start)), 6
                ),
                "classification": s.classification,
            }
            for s in report.segments
        ]

        return ok_payload({
            "ok": True,
            "segments": segs_out,
            "total_length_mm": report.total_length_mm,
            "closed_loops": report.closed_loops,
            "has_undercuts": report.has_undercuts,
            "undercut_face_ids": report.undercut_face_ids,
            "draft_deficient_face_ids": report.draft_deficient_face_ids,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Hayrettin, A. et al. (2003). Automatic parting line extraction. "
                "Computer-Aided Design 35(12). "
                "Chen, L.L., Rosen, D.W. (1999). Parting Direction Selection. "
                "J. Manufacturing Science & Engineering 121(1)."
            ),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "PARTING_LINE_ERROR")


# ---------------------------------------------------------------------------
# Tool 2: mold_split_cavity_core
# ---------------------------------------------------------------------------

mold_split_cavity_core_spec = ToolSpec(
    name="mold_split_cavity_core",
    description=(
        "Split a B-rep body into cavity (concave, pull-side) and core "
        "(convex, ejection-side) halves.\n\n"
        "Algorithm (Sanford 2017 Ch. 7; Hayrettin 2003 §5):\n"
        "  1. Mean pull-axis coordinate of silhouette midpoints → split plane.\n"
        "  2. Extend parting sheet by sheet_extension_mm beyond body bbox.\n"
        "  3. Classify body faces: above split → cavity; below → core.\n"
        "  4. Detect undercut side-action requirements (sliders / lifters).\n\n"
        "Requires the parting-line report from mold_detect_parting_line.\n\n"
        "Returns: {ok, parting_surface, cavity_body, core_body, insert_count,\n"
        "  parting_surface_complexity, has_sliders_needed, has_lifters_needed,\n"
        "  honest_caveat}.\n\n"
        "HONEST: Cavity/core are bbox descriptors, not full Boolean B-rep solids. "
        "Free-form parting surfaces are flagged but not generated.\n"
        "Refs: Sanford 2017 Ch. 7; Chougule-Ravi 2006 §3."
    ),
    input_schema={
        "type": "object",
        "required": ["body", "parting_line_report", "pull_direction"],
        "properties": {
            "body": {
                "type": "object",
                "description": "Same synthetic B-rep dict used in mold_detect_parting_line.",
            },
            "parting_line_report": {
                "type": "object",
                "description": (
                    "Output of mold_detect_parting_line — must contain keys: "
                    "'segments', 'has_undercuts', 'undercut_face_ids', "
                    "'draft_deficient_face_ids'."
                ),
            },
            "pull_direction": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Pull direction [x, y, z]. Default [0,0,1].",
                "default": [0, 0, 1],
            },
            "sheet_extension_mm": {
                "type": "number",
                "description": (
                    "How far the parting sheet extends beyond the body bbox "
                    "perpendicular to pull_direction (mm). Default 50.0 mm."
                ),
                "default": 50.0,
                "minimum": 0,
            },
        },
    },
)


def _reconstruct_parting_report(raw: dict):
    """Re-build a PartingLineReport from a serialised dict (from LLM tool output)."""
    from kerf_mold.parting_line import PartingLineReport, PartingLineSegment
    segs = []
    for s in raw.get("segments", []):
        segs.append(PartingLineSegment(
            edge_id=str(s.get("edge_id", "")),
            p_start=np.asarray(s.get("p_start", [0, 0, 0]), dtype=float),
            p_end=np.asarray(s.get("p_end", [0, 0, 0]), dtype=float),
            classification=str(s.get("classification", "silhouette")),
        ))
    return PartingLineReport(
        segments=segs,
        total_length_mm=float(raw.get("total_length_mm", 0.0)),
        closed_loops=int(raw.get("closed_loops", 0)),
        has_undercuts=bool(raw.get("has_undercuts", False)),
        undercut_face_ids=list(raw.get("undercut_face_ids", [])),
        draft_deficient_face_ids=list(raw.get("draft_deficient_face_ids", [])),
        honest_caveat=str(raw.get("honest_caveat", "")),
    )


async def run_mold_split_cavity_core(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute cavity/core split and return a JSON string."""
    try:
        body = args.get("body")
        if body is None:
            return err_payload("'body' is required", "BAD_ARGS")

        pl_raw = args.get("parting_line_report")
        if pl_raw is None:
            return err_payload("'parting_line_report' is required", "BAD_ARGS")

        pull_raw = args.get("pull_direction", [0, 0, 1])
        try:
            pull = np.asarray(pull_raw, dtype=float)
        except Exception as exc:
            return err_payload(f"pull_direction parse error: {exc}", "BAD_ARGS")

        sheet_ext = float(args.get("sheet_extension_mm", 50.0))

        parting_report = _reconstruct_parting_report(pl_raw)

        result = split_cavity_core(
            body=body,
            parting_line=parting_report,
            pull_direction=pull,
            sheet_extension_mm=sheet_ext,
        )

        return ok_payload({
            "ok": True,
            "parting_surface": {
                "surface_type": result.parting_surface.surface_type,
                "plane_point": result.parting_surface.plane_point.tolist(),
                "plane_normal": result.parting_surface.plane_normal.tolist(),
                "bbox_extended": result.parting_surface.bbox_extended,
            },
            "cavity_body": result.cavity_body,
            "core_body": result.core_body,
            "insert_count": result.insert_count,
            "parting_surface_complexity": result.parting_surface_complexity,
            "has_sliders_needed": result.has_sliders_needed,
            "has_lifters_needed": result.has_lifters_needed,
            "honest_caveat": result.honest_caveat,
            "reference": (
                "Hayrettin, A. et al. (2003). Automatic parting line extraction. "
                "Computer-Aided Design 35(12). "
                "Sanford, J. (2017). Mold Engineering, 2nd ed., Hanser, Ch. 7. "
                "Chougule, R.G., Ravi, B. (2006). Casting cost estimation. IJAMT 29."
            ),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "CAVITY_CORE_SPLIT_ERROR")


# ---------------------------------------------------------------------------
# Tool 3: mold_estimate_mold_complexity
# ---------------------------------------------------------------------------

mold_estimate_mold_complexity_spec = ToolSpec(
    name="mold_estimate_mold_complexity",
    description=(
        "Estimate mold complexity and recommend tooling class from a cavity/core split result.\n\n"
        "Scoring model (Chougule-Ravi 2006 §3):\n"
        "  Base = 1; +2 sliders; +2 lifters; +1 insert_count > 2;\n"
        "  +2 free-form parting; +1 insert_count > 4. Clamped [1, 10].\n\n"
        "Tooling recommendation:\n"
        "  score ≤ 3 → '2-plate'\n"
        "  score ≤ 6 → '3-plate'\n"
        "  score >  6 → 'hot_runner'\n\n"
        "Returns: {ok, complexity_score, recommended_tooling, slides_count, notes, honest_caveat}.\n\n"
        "HONEST: Heuristic model only. Real mold cost requires full DFM + machine-rate costing.\n"
        "Refs: Chougule-Ravi IJAMT 29 (2006); Sanford 2017 Ch. 7."
    ),
    input_schema={
        "type": "object",
        "required": ["split_result"],
        "properties": {
            "split_result": {
                "type": "object",
                "description": (
                    "Output of mold_split_cavity_core — must contain keys: "
                    "'has_sliders_needed', 'has_lifters_needed', 'insert_count', "
                    "'parting_surface_complexity'."
                ),
            },
        },
    },
)


async def run_mold_estimate_mold_complexity(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Compute complexity score from a split result dict."""
    try:
        sr = args.get("split_result")
        if sr is None:
            return err_payload("'split_result' is required", "BAD_ARGS")

        # Re-build a minimal CavityCoreResult from the serialised dict
        from kerf_mold.cavity_core_split import CavityCoreResult, PartingSurface

        ps = PartingSurface(
            surface_type=str(sr.get("parting_surface_complexity", "planar")),
            plane_point=np.zeros(3),
            plane_normal=np.array([0.0, 0.0, 1.0]),
            bbox_extended=[0.0] * 6,
        )
        result = CavityCoreResult(
            parting_surface=ps,
            cavity_body=sr.get("cavity_body", {}),
            core_body=sr.get("core_body", {}),
            insert_count=int(sr.get("insert_count", 2)),
            parting_surface_complexity=str(sr.get("parting_surface_complexity", "planar")),
            has_lifters_needed=bool(sr.get("has_lifters_needed", False)),
            has_sliders_needed=bool(sr.get("has_sliders_needed", False)),
            honest_caveat=str(sr.get("honest_caveat", "")),
        )

        complexity = estimate_mold_complexity(result)
        complexity["ok"] = True
        return ok_payload(complexity)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "COMPLEXITY_ESTIMATE_ERROR")
