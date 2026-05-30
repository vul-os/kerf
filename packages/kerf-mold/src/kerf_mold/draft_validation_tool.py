"""
kerf_mold.draft_validation_tool — LLM tool wrapper for mold draft-angle validation.

Tool: mold_validate_draft
  Verify that every face of a B-rep model has the minimum draft angle required
  for injection-mold ejection without sticking.

  Per-face result includes computed draft angle, required minimum, pass/fail,
  and a human-readable note.

References
----------
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001 — §3.4 Draft angles and surface finish requirements.
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007
  — §4 Part geometry, draft, and moldability.
SPI Surface Finish Standard (PLASTICS Industry Association) — Ra grades
  A1–D3 and corresponding minimum draft angles.
"""
from __future__ import annotations

import json
import math

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.draft_validation import FaceInput, validate_draft


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_VALIDATE_DRAFT_SPEC = ToolSpec(
    name="mold_validate_draft",
    description=(
        "Verify that every face of a B-rep model intended for injection molding "
        "has the minimum draft angle required for ejection without sticking "
        "(Menges 2001 §3.4; Beaumont 2007 §4; SPI Surface Finish Standard).\n\n"
        "Draft angle is measured from the parting plane (perpendicular to pull): "
        "0° = perfectly vertical wall (needs the most draft), "
        "90° = top/bottom face (no draft needed).\n\n"
        "Minimum requirements:\n"
        "  • Smooth outer walls:   ≥ 0.5°\n"
        "  • Smooth inner walls:   ≥ 1.0°\n"
        "  • SPI A3 (diamond):     ≥ 1.0°\n"
        "  • SPI B1 (600-grit):    ≥ 1.5°\n"
        "  • SPI C1–C3 (stone):    ≥ 2.0°–3.0°\n"
        "  • SPI D1–D3 (blast):    ≥ 3.0°–4.0°\n"
        "  • Ribs (per side):      ≥ 1.0°\n"
        "  • Bosses:               ≥ 0.5°\n\n"
        "v1 limitation: only draft angle is checked.  Undercut detection "
        "(faces trapped under geometry in the pull direction) is a separate, "
        "harder problem and is NOT performed here.\n\n"
        "Returns: {ok, faces_passing, faces_failing, faces_degenerate, "
        "per_face_results:[{face_id, angle_deg, required_min_deg, passes, "
        "region, is_degenerate, note}], pull_direction, surface_finish, summary}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "faces": {
                "type": "array",
                "description": (
                    "B-rep faces to check.  Each face: "
                    "{normal:[nx,ny,nz], face_id?:str, region?:str}.  "
                    "normal is the outward face normal (need not be unit length).  "
                    "region: 'outer' (default) | 'inner' | 'rib' | 'boss'."
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "pull_direction": {
                "type": "array",
                "description": (
                    "Mold pull direction vector [x, y, z].  "
                    "Default [0, 0, 1] (+Z, typical for vertically-opening molds)."
                ),
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "surface_finish": {
                "type": "string",
                "description": (
                    "Surface finish code controlling the minimum draft requirement.  "
                    "'smooth' (default, 0.5° outer / 1° inner) or SPI grade: "
                    "A1, A2, A3, B1, B2, B3, C1, C2, C3, D1, D2, D3.  "
                    "See _SPI_MIN_DRAFT_OUTER table (Menges 2001 §3.4)."
                ),
            },
        },
        "required": ["faces"],
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_validate_draft(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_faces = a.get("faces", [])
    if not isinstance(raw_faces, list) or not raw_faces:
        return err_payload("faces must be a non-empty list", "BAD_ARGS")

    # Parse faces
    face_inputs: list[FaceInput] = []
    for i, rf in enumerate(raw_faces):
        try:
            raw_n = rf.get("normal")
            if raw_n is None or len(raw_n) != 3:
                return err_payload(
                    f"faces[{i}].normal must be [nx, ny, nz]", "BAD_ARGS"
                )
            face_inputs.append(FaceInput(
                normal=(float(raw_n[0]), float(raw_n[1]), float(raw_n[2])),
                face_id=str(rf.get("face_id", f"face{i}")),
                region=str(rf.get("region", "outer")),
            ))
        except Exception as exc:
            return err_payload(f"faces[{i}]: {exc}", "BAD_ARGS")

    # Parse pull direction
    raw_pull = a.get("pull_direction", [0.0, 0.0, 1.0])
    try:
        if len(raw_pull) != 3:
            return err_payload("pull_direction must have 3 components", "BAD_ARGS")
        pull = (float(raw_pull[0]), float(raw_pull[1]), float(raw_pull[2]))
    except Exception as exc:
        return err_payload(f"pull_direction: {exc}", "BAD_ARGS")

    surface_finish = str(a.get("surface_finish", "smooth"))

    try:
        report = validate_draft(
            faces=face_inputs,
            pull_direction=pull,
            surface_finish=surface_finish,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    per_face = []
    for fr in report.per_face_results:
        # NaN is not valid JSON — serialise as None
        angle: object
        if isinstance(fr.angle_deg, float) and math.isnan(fr.angle_deg):
            angle = None
        else:
            angle = fr.angle_deg
        per_face.append({
            "face_id": fr.face_id,
            "angle_deg": angle,
            "required_min_deg": fr.required_min_deg,
            "passes": fr.passes,
            "region": fr.region,
            "is_degenerate": fr.is_degenerate,
            "note": fr.note,
        })

    return ok_payload({
        "ok": True,
        "faces_passing": report.faces_passing,
        "faces_failing": report.faces_failing,
        "faces_degenerate": report.faces_degenerate,
        "per_face_results": per_face,
        "pull_direction": list(report.pull_direction),
        "surface_finish": report.surface_finish,
        "summary": report.summary,
    })
