"""
kerf_cloud.plm.sysml_trace
==========================

SysML-light trace for the .sysml file kind.

A .sysml file stores a top-level system-engineering requirement with trace
links to implementation files (CAD, circuit, firmware …) and verification
test IDs.  The module provides:

  * SysML document schema
  * create_sysml_doc()  — build a new SysML doc
  * add_trace_link()    — attach file_id → requirement trace
  * add_verification()  — attach test_id → requirement
  * trace()             — resolve the full requirement→implementation→verification chain
  * sysml_from_content() — parse SysML JSON content string

SysML-light JSON schema (stored in file.content)
-------------------------------------------------
{
  "sysml_id": "sysml-<ts>-<rand>",
  "title": str,
  "requirements": [
    {
      "req_id": str,           // unique within the document, e.g. "REQ-001"
      "text": str,             // requirement statement
      "rationale": str,
      "priority": "shall" | "should" | "may",
      "trace_links": [         // implementation links
        {
          "file_id": str,      // kerf file id that satisfies this req
          "file_name": str,
          "link_type": "satisfies" | "refines" | "derives"
        },
        ...
      ],
      "verification": [        // test IDs that verify this req
        {
          "test_id": str,
          "method": "test" | "analysis" | "inspection" | "demonstration",
          "status": "pending" | "pass" | "fail"
        },
        ...
      ]
    },
    ...
  ],
  "created_at": ISO datetime,
  "updated_at": ISO datetime
}
"""
from __future__ import annotations

import copy
import json
import random
import string
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRIORITIES = frozenset({"shall", "should", "may"})
LINK_TYPES = frozenset({"satisfies", "refines", "derives"})
VERIFICATION_METHODS = frozenset({"test", "analysis", "inspection", "demonstration"})
VERIFICATION_STATUSES = frozenset({"pending", "pass", "fail"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rand_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_sysml_doc(
    title: str,
    requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new SysML-light document.

    Parameters
    ----------
    title:
        Document / system title.
    requirements:
        Optional list of requirement dicts.  Each must have at least
        'req_id' and 'text'.  'priority' defaults to 'shall'.

    Returns
    -------
    {"ok": True, "doc": {...}} or {"ok": False, "error": ..., "code": ...}
    """
    if not title or not title.strip():
        return {"ok": False, "error": "title is required", "code": "BAD_ARGS"}

    validated_reqs: list[dict] = []
    for i, req in enumerate(requirements or []):
        v = _validate_req(req, i)
        if not v["ok"]:
            return v
        validated_reqs.append(_normalise_req(req))

    ts = _now_iso()
    doc: dict[str, Any] = {
        "sysml_id": f"sysml-{int(datetime.now(timezone.utc).timestamp())}-{_rand_suffix()}",
        "title": title.strip(),
        "requirements": validated_reqs,
        "created_at": ts,
        "updated_at": ts,
    }
    return {"ok": True, "doc": doc}


def add_trace_link(
    doc: dict[str, Any],
    req_id: str,
    file_id: str,
    file_name: str,
    link_type: str = "satisfies",
) -> dict[str, Any]:
    """Add an implementation trace link to a requirement.

    Returns updated doc copy or error.
    """
    if link_type not in LINK_TYPES:
        return {
            "ok": False,
            "error": f"link_type must be one of {sorted(LINK_TYPES)}",
            "code": "BAD_ARGS",
        }
    updated = copy.deepcopy(doc)
    req = _find_req(updated, req_id)
    if req is None:
        return {"ok": False, "error": f"req_id {req_id!r} not found", "code": "NOT_FOUND"}
    link = {"file_id": file_id, "file_name": file_name, "link_type": link_type}
    # Deduplicate by file_id + link_type
    existing = req.setdefault("trace_links", [])
    for ex in existing:
        if ex.get("file_id") == file_id and ex.get("link_type") == link_type:
            return {"ok": True, "doc": updated}  # already present
    existing.append(link)
    updated["updated_at"] = _now_iso()
    return {"ok": True, "doc": updated}


def add_verification(
    doc: dict[str, Any],
    req_id: str,
    test_id: str,
    method: str = "test",
    status: str = "pending",
) -> dict[str, Any]:
    """Add a verification test link to a requirement."""
    if method not in VERIFICATION_METHODS:
        return {
            "ok": False,
            "error": f"method must be one of {sorted(VERIFICATION_METHODS)}",
            "code": "BAD_ARGS",
        }
    if status not in VERIFICATION_STATUSES:
        return {
            "ok": False,
            "error": f"status must be one of {sorted(VERIFICATION_STATUSES)}",
            "code": "BAD_ARGS",
        }
    updated = copy.deepcopy(doc)
    req = _find_req(updated, req_id)
    if req is None:
        return {"ok": False, "error": f"req_id {req_id!r} not found", "code": "NOT_FOUND"}
    verif = {"test_id": test_id, "method": method, "status": status}
    existing = req.setdefault("verification", [])
    for ex in existing:
        if ex.get("test_id") == test_id:
            return {"ok": True, "doc": updated}  # already present
    existing.append(verif)
    updated["updated_at"] = _now_iso()
    return {"ok": True, "doc": updated}


def trace(
    doc: dict[str, Any],
    req_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the requirement → implementation → verification chain.

    Parameters
    ----------
    doc:
        SysML document dict.
    req_id:
        If given, return the chain for only this requirement.
        If None, return chains for all requirements.

    Returns
    -------
    {"ok": True, "chains": [ {req_id, text, implementations, verifications}, ... ]}
    """
    reqs = doc.get("requirements", [])
    if req_id is not None:
        reqs = [r for r in reqs if r.get("req_id") == req_id]
        if not reqs:
            return {"ok": False, "error": f"req_id {req_id!r} not found", "code": "NOT_FOUND"}

    chains = []
    for req in reqs:
        chains.append({
            "req_id": req.get("req_id"),
            "text": req.get("text", ""),
            "priority": req.get("priority", "shall"),
            "implementations": list(req.get("trace_links", [])),
            "verifications": list(req.get("verification", [])),
            "implementation_count": len(req.get("trace_links", [])),
            "verification_count": len(req.get("verification", [])),
            "coverage_status": _coverage_status(req),
        })
    return {"ok": True, "chains": chains}


def sysml_from_content(content: str) -> dict[str, Any]:
    """Parse SysML JSON content string.  Returns the doc dict or error."""
    if not content or not content.strip():
        return {"ok": False, "error": "empty content", "code": "BAD_ARGS"}
    try:
        doc = json.loads(content)
    except Exception as exc:
        return {"ok": False, "error": f"JSON parse error: {exc}", "code": "PARSE_ERROR"}
    if not isinstance(doc, dict):
        return {"ok": False, "error": "SysML content must be a JSON object", "code": "BAD_ARGS"}
    return {"ok": True, "doc": doc}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_req(doc: dict, req_id: str) -> dict | None:
    for req in doc.get("requirements", []):
        if req.get("req_id") == req_id:
            return req
    return None


def _validate_req(req: dict, idx: int) -> dict[str, Any]:
    if not req.get("req_id"):
        return {"ok": False, "error": f"requirements[{idx}].req_id missing", "code": "BAD_ARGS"}
    if not req.get("text"):
        return {"ok": False, "error": f"requirements[{idx}].text missing", "code": "BAD_ARGS"}
    priority = req.get("priority", "shall")
    if priority not in PRIORITIES:
        return {
            "ok": False,
            "error": f"requirements[{idx}].priority must be one of {sorted(PRIORITIES)}",
            "code": "BAD_ARGS",
        }
    return {"ok": True}


def _normalise_req(req: dict) -> dict:
    return {
        "req_id": req["req_id"],
        "text": req["text"],
        "rationale": req.get("rationale", ""),
        "priority": req.get("priority", "shall"),
        "trace_links": list(req.get("trace_links", [])),
        "verification": list(req.get("verification", [])),
    }


def _coverage_status(req: dict) -> str:
    """Return "uncovered", "implemented", "verified", or "fully_verified"."""
    has_impl = bool(req.get("trace_links"))
    verifs = req.get("verification", [])
    has_verif = bool(verifs)
    all_pass = has_verif and all(v.get("status") == "pass" for v in verifs)
    if not has_impl:
        return "uncovered"
    if has_impl and not has_verif:
        return "implemented"
    if has_verif and all_pass:
        return "fully_verified"
    return "verified"
