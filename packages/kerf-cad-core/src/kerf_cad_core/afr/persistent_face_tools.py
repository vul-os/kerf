"""
kerf_cad_core.afr.persistent_face_tools — LLM tool wrapper for persistent face naming.

Registers two tools:
  brep_assign_persistent_face_ids  — assign/match stable UUIDs to all body faces
                                     (survives parametric edits as long as geometry
                                     matches — Kripac 1997; Han et al. 1999)
  brep_detect_face_id_breaks       — compare two assignments and report broken IDs

Both tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
Kripac, J. (1997). "A mechanism for persistently naming topological entities in
  history-based parametric solid models." Proc. 4th ACM SMA, pp. 21-30.
Han, J., Shi, F. & Kim, Y.S. (1999). "Persistent naming in parametric CAD
  systems using feature-based face signatures." ASME DETC99/CIE-9022.

Author: imranparuk
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register

try:
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
except ImportError:
    from kerf_cad_core._compat import ProjectCtx  # type: ignore[assignment]

from kerf_cad_core.afr.persistent_face_id import (
    FacePersistentId,
    assign_persistent_ids,
)


# ---------------------------------------------------------------------------
# Tool: brep_assign_persistent_face_ids
# ---------------------------------------------------------------------------

_assign_spec = ToolSpec(
    name="brep_assign_persistent_face_ids",
    description=(
        "Assign stable persistent UUIDs to every face in a B-rep body.\n"
        "UUIDs survive parametric edits as long as the face's geometry\n"
        "(surface type, normal, area, centroid) remains recognisably the same.\n\n"
        "Algorithm: geometric-signature matching (Kripac 1997 / Han et al. 1999).\n"
        "If prior_assignments is supplied, UUIDs are re-matched by canonical\n"
        "signature; unmatched faces receive fresh UUIDs.\n\n"
        "Inputs:\n"
        "  body (dict): AFR body dict with 'faces' list. Each face must have:\n"
        "    id, type ('planar'|'cylindrical'|'conical'|'spherical'|'toroidal'|'other'),\n"
        "    normal ([nx,ny,nz]), area (float).\n"
        "    Optional: centroid ([x,y,z]), radius (float), convexity, creating_feature_id.\n"
        "  prior_assignments (list of {face_index, face_uuid, creating_feature_id,\n"
        "    feature_role, canonical_signature} | null):\n"
        "    Previous assignment list from an earlier call, for re-matching.\n\n"
        "Outputs:\n"
        "  assignments: list of {face_index, face_uuid, creating_feature_id,\n"
        "    feature_role, canonical_signature}\n"
        "  n_faces: total face count\n"
        "  n_reused: count of UUIDs reused from prior_assignments (0 if none supplied)\n\n"
        "HONEST: Simplified geometric-signature approach. Production kernels use full\n"
        "topological graph matching. Works well for common ops (extrude/pocket/fillet);\n"
        "may produce spurious breaks on split/merge operations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "body": {
                "type": "object",
                "description": "AFR body dict with 'faces' list.",
                "properties": {
                    "faces": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":       {"type": ["string", "integer"]},
                                "type":     {"type": "string"},
                                "normal":   {"type": "array", "items": {"type": "number"}},
                                "area":     {"type": "number"},
                                "centroid": {"type": "array", "items": {"type": "number"}},
                                "radius":   {"type": "number"},
                                "convexity": {"type": "string"},
                                "creating_feature_id": {"type": "string"},
                            },
                            "required": ["id", "type", "normal", "area"],
                        },
                    },
                },
                "required": ["faces"],
            },
            "prior_assignments": {
                "type": ["array", "null"],
                "default": None,
                "description": "Previous assignment list for UUID re-matching (or null).",
                "items": {
                    "type": "object",
                    "properties": {
                        "face_index":           {"type": "integer"},
                        "face_uuid":            {"type": "string"},
                        "creating_feature_id":  {"type": "string"},
                        "feature_role":         {"type": "string"},
                        "canonical_signature":  {"type": "string"},
                    },
                },
            },
        },
        "required": ["body"],
    },
)


@register(_assign_spec, write=False)
async def run_brep_assign_persistent_face_ids(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        body = payload["body"]
        prior_raw = payload.get("prior_assignments", None)

        # Reconstruct prior_assignments dict if provided
        prior: dict[int, FacePersistentId] | None = None
        if prior_raw:
            prior = {}
            for item in prior_raw:
                idx = int(item["face_index"])
                prior[idx] = FacePersistentId(
                    face_uuid=item["face_uuid"],
                    creating_feature_id=item["creating_feature_id"],
                    feature_role=item["feature_role"],
                    canonical_signature=item["canonical_signature"],
                )

        assignments = assign_persistent_ids(body, prior_assignments=prior)

        # Count reused UUIDs
        n_reused = 0
        if prior:
            prior_uuids = {fp.face_uuid for fp in prior.values()}
            n_reused = sum(1 for fp in assignments.values() if fp.face_uuid in prior_uuids)

        out_list = [
            {
                "face_index": idx,
                "face_uuid": fp.face_uuid,
                "creating_feature_id": fp.creating_feature_id,
                "feature_role": fp.feature_role,
                "canonical_signature": fp.canonical_signature,
            }
            for idx, fp in sorted(assignments.items())
        ]

    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"assign_persistent_ids failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({
        "assignments": out_list,
        "n_faces": len(out_list),
        "n_reused": n_reused,
    })


# ---------------------------------------------------------------------------
# Tool: brep_detect_face_id_breaks
# ---------------------------------------------------------------------------

_detect_breaks_spec = ToolSpec(
    name="brep_detect_face_id_breaks",
    description=(
        "Detect persistent face ID breaks between two B-rep body assignments.\n"
        "A 'break' is a UUID from prior_assignments that has no match in new_assignments.\n"
        "Use after parametric edits to find which references are now stale.\n\n"
        "Inputs:\n"
        "  prior_assignments: list of {face_index, face_uuid, ...} from an earlier call\n"
        "  new_assignments:   list of {face_index, face_uuid, ...} from the edited body\n\n"
        "Outputs:\n"
        "  broken_uuids: list of UUIDs that are no longer present\n"
        "  n_stable: count of UUIDs that survived the edit\n"
        "  n_broken: count of broken UUIDs\n"
        "  n_new: count of brand-new UUIDs in new_assignments"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prior_assignments": {
                "type": "array",
                "description": "Assignment list from before the edit.",
                "items": {
                    "type": "object",
                    "properties": {
                        "face_index":          {"type": "integer"},
                        "face_uuid":           {"type": "string"},
                        "creating_feature_id": {"type": "string"},
                        "feature_role":        {"type": "string"},
                        "canonical_signature": {"type": "string"},
                    },
                    "required": ["face_index", "face_uuid", "canonical_signature"],
                },
            },
            "new_assignments": {
                "type": "array",
                "description": "Assignment list from after the edit.",
                "items": {
                    "type": "object",
                    "properties": {
                        "face_index":          {"type": "integer"},
                        "face_uuid":           {"type": "string"},
                        "creating_feature_id": {"type": "string"},
                        "feature_role":        {"type": "string"},
                        "canonical_signature": {"type": "string"},
                    },
                    "required": ["face_index", "face_uuid", "canonical_signature"],
                },
            },
        },
        "required": ["prior_assignments", "new_assignments"],
    },
)


@register(_detect_breaks_spec, write=False)
async def run_brep_detect_face_id_breaks(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        def _list_to_dict(lst: list) -> dict[int, FacePersistentId]:
            d: dict[int, FacePersistentId] = {}
            for item in lst:
                idx = int(item["face_index"])
                d[idx] = FacePersistentId(
                    face_uuid=item["face_uuid"],
                    creating_feature_id=item.get("creating_feature_id", "unknown"),
                    feature_role=item.get("feature_role", "imported"),
                    canonical_signature=item["canonical_signature"],
                )
            return d

        prior = _list_to_dict(payload["prior_assignments"])
        new   = _list_to_dict(payload["new_assignments"])

        prior_uuids = {fp.face_uuid for fp in prior.values()}
        new_uuids   = {fp.face_uuid for fp in new.values()}

        broken_uuids = list(prior_uuids - new_uuids)
        n_stable = len(prior_uuids & new_uuids)
        n_new    = len(new_uuids - prior_uuids)

    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"detect_id_breaks failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({
        "broken_uuids": broken_uuids,
        "n_stable": n_stable,
        "n_broken": len(broken_uuids),
        "n_new": n_new,
    })


__all__ = [
    "run_brep_assign_persistent_face_ids",
    "run_brep_detect_face_id_breaks",
]
