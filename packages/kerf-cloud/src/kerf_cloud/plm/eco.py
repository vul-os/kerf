"""
kerf_cloud.plm.eco
==================

Engineering Change Order / Engineering Change Request (ECR/ECO) file kind.

An .eco file stores a structured change request as JSON content inside a
kerf file of kind='eco'.  This module provides:

  * ECO schema (from-state / to-state / impact list)
  * create_eco()  — build a new ECO dict ready to embed in file content
  * validate_eco() — validate an ECO dict, returning ok/errors
  * compute_impact() — roll up where-used to build the impact list
  * apply_eco() — apply from→to state and return diff record

ECO JSON schema
---------------
{
  "eco_id": "eco-<timestamp>-<rand>",
  "title": str,
  "description": str,
  "status": "draft" | "in_review" | "approved" | "rejected" | "implemented",
  "requestor": str,
  "created_at": ISO datetime,
  "updated_at": ISO datetime,
  "affected_parts": [
    {
      "part_id": str,          // file id
      "from_state": {          // snapshot of part content before change
        "name": str,
        "content": str
      },
      "to_state": {            // intended new state
        "name": str,
        "content": str
      },
      "change_type": "add" | "remove" | "modify" | "replace"
    },
    ...
  ],
  "impact_list": [             // populated by compute_impact()
    {
      "assembly_id": str,
      "assembly_name": str,
      "effectivity": { ... }
    },
    ...
  ],
  "verification_tests": [str], // test IDs that verify this change
  "linked_requirements": [str] // requirement IDs from SysML docs
}
"""
from __future__ import annotations

import json
import random
import string
from datetime import datetime, timezone
from typing import Any

from kerf_cloud.plm.where_used import where_used


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rand_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


ECO_STATUSES = frozenset({"draft", "in_review", "approved", "rejected", "implemented"})
CHANGE_TYPES = frozenset({"add", "remove", "modify", "replace"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_eco(
    title: str,
    description: str,
    requestor: str,
    affected_parts: list[dict[str, Any]],
    project_files: list[dict[str, Any]] | None = None,
    verification_tests: list[str] | None = None,
    linked_requirements: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new ECO dict.

    Parameters
    ----------
    title:
        Short title for the change request.
    description:
        Detailed description of why the change is needed.
    requestor:
        Name or user ID of the person requesting the change.
    affected_parts:
        List of part-change dicts.  Each must have:
          - part_id: str
          - from_state: dict with at least 'name'
          - to_state: dict with at least 'name'
          - change_type: one of add/remove/modify/replace
    project_files:
        If provided, used to compute the impact list via where_used().
    verification_tests:
        Optional list of test IDs that verify this change.
    linked_requirements:
        Optional list of requirement IDs.

    Returns
    -------
    dict  (never raises; errors returned as {"ok": False, "error": ..., "code": ...})
    """
    if not title or not title.strip():
        return {"ok": False, "error": "title is required", "code": "BAD_ARGS"}
    if not requestor or not requestor.strip():
        return {"ok": False, "error": "requestor is required", "code": "BAD_ARGS"}
    if not affected_parts:
        return {"ok": False, "error": "affected_parts must be non-empty", "code": "BAD_ARGS"}

    # Validate each affected part entry
    for i, ap in enumerate(affected_parts):
        if not ap.get("part_id"):
            return {"ok": False, "error": f"affected_parts[{i}].part_id missing", "code": "BAD_ARGS"}
        if ap.get("change_type") not in CHANGE_TYPES:
            return {
                "ok": False,
                "error": f"affected_parts[{i}].change_type must be one of {sorted(CHANGE_TYPES)}",
                "code": "BAD_ARGS",
            }
        if "from_state" not in ap:
            return {"ok": False, "error": f"affected_parts[{i}].from_state missing", "code": "BAD_ARGS"}
        if "to_state" not in ap:
            return {"ok": False, "error": f"affected_parts[{i}].to_state missing", "code": "BAD_ARGS"}

    # Build impact list from where-used roll-up
    impact_list: list[dict] = []
    if project_files:
        seen_asm_ids: set[str] = set()
        for ap in affected_parts:
            wu = where_used(ap["part_id"], project_files)
            for usage in wu.get("usages", []):
                aid = usage["assembly_id"]
                if aid not in seen_asm_ids:
                    seen_asm_ids.add(aid)
                    impact_list.append({
                        "assembly_id": aid,
                        "assembly_name": usage["assembly_name"],
                        "effectivity": usage["effectivity"],
                    })
    impact_list.sort(key=lambda x: x["assembly_name"])

    ts = _now_iso()
    eco: dict[str, Any] = {
        "eco_id": f"eco-{int(datetime.now(timezone.utc).timestamp())}-{_rand_suffix()}",
        "title": title.strip(),
        "description": description.strip() if description else "",
        "status": "draft",
        "requestor": requestor.strip(),
        "created_at": ts,
        "updated_at": ts,
        "affected_parts": affected_parts,
        "impact_list": impact_list,
        "verification_tests": list(verification_tests or []),
        "linked_requirements": list(linked_requirements or []),
    }
    return {"ok": True, "eco": eco}


def validate_eco(eco: dict[str, Any]) -> dict[str, Any]:
    """Validate an ECO dict.

    Returns {"ok": True} or {"ok": False, "errors": [str]}.
    """
    errors: list[str] = []
    if not eco.get("eco_id"):
        errors.append("eco_id missing")
    if not eco.get("title"):
        errors.append("title missing")
    if not eco.get("requestor"):
        errors.append("requestor missing")
    status = eco.get("status")
    if status not in ECO_STATUSES:
        errors.append(f"status must be one of {sorted(ECO_STATUSES)}, got {status!r}")
    parts = eco.get("affected_parts")
    if not parts:
        errors.append("affected_parts is empty")
    else:
        for i, ap in enumerate(parts):
            if not ap.get("part_id"):
                errors.append(f"affected_parts[{i}].part_id missing")
            if ap.get("change_type") not in CHANGE_TYPES:
                errors.append(f"affected_parts[{i}].change_type invalid")
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True}


def compute_impact(
    eco: dict[str, Any],
    project_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute the impact list for an ECO using current project files.

    Returns updated ECO dict (new copy) with refreshed impact_list.
    """
    import copy
    updated = copy.deepcopy(eco)
    seen_asm_ids: set[str] = set()
    impact_list: list[dict] = []
    for ap in eco.get("affected_parts", []):
        wu = where_used(ap["part_id"], project_files)
        for usage in wu.get("usages", []):
            aid = usage["assembly_id"]
            if aid not in seen_asm_ids:
                seen_asm_ids.add(aid)
                impact_list.append({
                    "assembly_id": aid,
                    "assembly_name": usage["assembly_name"],
                    "effectivity": usage["effectivity"],
                })
    impact_list.sort(key=lambda x: x["assembly_name"])
    updated["impact_list"] = impact_list
    updated["updated_at"] = _now_iso()
    return {"ok": True, "eco": updated}


def approve_eco(eco: dict[str, Any]) -> dict[str, Any]:
    """Transition ECO status draft/in_review → approved."""
    import copy
    if eco.get("status") not in {"draft", "in_review"}:
        return {
            "ok": False,
            "error": f"cannot approve ECO in status {eco.get('status')!r}",
            "code": "INVALID_STATE",
        }
    updated = copy.deepcopy(eco)
    updated["status"] = "approved"
    updated["updated_at"] = _now_iso()
    return {"ok": True, "eco": updated}


def eco_from_content(content: str) -> dict[str, Any]:
    """Parse ECO JSON content string.  Returns the eco dict or error."""
    if not content or not content.strip():
        return {"ok": False, "error": "empty content", "code": "BAD_ARGS"}
    try:
        doc = json.loads(content)
    except Exception as exc:
        return {"ok": False, "error": f"JSON parse error: {exc}", "code": "PARSE_ERROR"}
    if not isinstance(doc, dict):
        return {"ok": False, "error": "ECO content must be a JSON object", "code": "BAD_ARGS"}
    return {"ok": True, "eco": doc}
