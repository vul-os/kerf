"""
kerf_cloud.plm.llm_tools
========================

LLM-callable tool definitions for PLM operations.

Each tool follows the standard kerf pattern:
  - Plain Python function, JSON-serialisable return value
  - Never raises (errors returned as {"ok": False, "error": ..., "code": ...})
  - Registered in TOOL_DEFS as an Anthropic-style function-call descriptor

Tools exposed
-------------
plm_bom_150_percent      — full universe of parts + effectivity windows
plm_where_used           — assembly-graph upward walk
plm_create_eco           — create an ECO/ECR document
plm_validate_eco         — validate an ECO dict
plm_compute_eco_impact   — refresh ECO impact list via where-used
plm_create_sysml_doc     — create a SysML-light requirements document
plm_add_trace_link       — attach file → requirement trace link
plm_add_verification     — attach test → requirement verification
plm_trace                — resolve requirement→implementation→verification chain
"""
from __future__ import annotations

import json
from typing import Any

from kerf_cloud.plm.bom150 import bom_150_percent
from kerf_cloud.plm.eco import (
    approve_eco,
    compute_impact,
    create_eco,
    eco_from_content,
    validate_eco,
)
from kerf_cloud.plm.sysml_trace import (
    add_trace_link,
    add_verification,
    create_sysml_doc,
    sysml_from_content,
    trace,
)
from kerf_cloud.plm.where_used import where_used


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def plm_bom_150_percent(
    project_files_json: str,
    effectivity_date: str | None = None,
) -> dict[str, Any]:
    """150% BOM: full universe of parts ever used in the project.

    Parameters
    ----------
    project_files_json:
        JSON array of file objects (id, name, kind, content, parent_id).
    effectivity_date:
        ISO date string (YYYY-MM-DD) to mark which parts are currently
        effective.  Pass null/empty for the full superset.
    """
    try:
        files = json.loads(project_files_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid project_files_json: {exc}", "code": "PARSE_ERROR"}
    if not isinstance(files, list):
        return {"ok": False, "error": "project_files_json must be a JSON array", "code": "BAD_ARGS"}
    return bom_150_percent(files, effectivity_date or None)


def plm_where_used(
    part_id: str,
    project_files_json: str,
) -> dict[str, Any]:
    """Where-used: all assemblies (direct + indirect) that reference a part.

    Parameters
    ----------
    part_id:
        File id of the part to look up.
    project_files_json:
        JSON array of file objects (id, name, kind, content, parent_id).
    """
    try:
        files = json.loads(project_files_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid project_files_json: {exc}", "code": "PARSE_ERROR"}
    if not part_id:
        return {"ok": False, "error": "part_id is required", "code": "BAD_ARGS"}
    return where_used(part_id, files)


def plm_create_eco(
    title: str,
    description: str,
    requestor: str,
    affected_parts_json: str,
    project_files_json: str | None = None,
    verification_tests_json: str | None = None,
    linked_requirements_json: str | None = None,
) -> dict[str, Any]:
    """Create a new Engineering Change Order (ECO/ECR).

    Parameters
    ----------
    title:
        Short title for the change.
    description:
        Detailed rationale for the change.
    requestor:
        Name or user ID of requester.
    affected_parts_json:
        JSON array of part-change records, each with:
        part_id, from_state, to_state, change_type.
    project_files_json:
        Optional JSON array of project files for impact roll-up.
    verification_tests_json:
        Optional JSON array of test ID strings.
    linked_requirements_json:
        Optional JSON array of requirement ID strings.
    """
    try:
        affected = json.loads(affected_parts_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid affected_parts_json: {exc}", "code": "PARSE_ERROR"}

    files: list[dict] | None = None
    if project_files_json:
        try:
            files = json.loads(project_files_json)
        except Exception as exc:
            return {"ok": False, "error": f"invalid project_files_json: {exc}", "code": "PARSE_ERROR"}

    vtests: list[str] | None = None
    if verification_tests_json:
        try:
            vtests = json.loads(verification_tests_json)
        except Exception as exc:
            return {"ok": False, "error": f"invalid verification_tests_json: {exc}", "code": "PARSE_ERROR"}

    lreqs: list[str] | None = None
    if linked_requirements_json:
        try:
            lreqs = json.loads(linked_requirements_json)
        except Exception as exc:
            return {"ok": False, "error": f"invalid linked_requirements_json: {exc}", "code": "PARSE_ERROR"}

    return create_eco(
        title=title,
        description=description,
        requestor=requestor,
        affected_parts=affected,
        project_files=files,
        verification_tests=vtests,
        linked_requirements=lreqs,
    )


def plm_validate_eco(eco_json: str) -> dict[str, Any]:
    """Validate an ECO JSON document.

    Parameters
    ----------
    eco_json:
        JSON string of the ECO object.
    """
    try:
        eco = json.loads(eco_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid eco_json: {exc}", "code": "PARSE_ERROR"}
    return validate_eco(eco)


def plm_compute_eco_impact(
    eco_json: str,
    project_files_json: str,
) -> dict[str, Any]:
    """Recompute impact list for an ECO using current project files.

    Parameters
    ----------
    eco_json:
        JSON string of the ECO object.
    project_files_json:
        JSON array of all project files.
    """
    try:
        eco = json.loads(eco_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid eco_json: {exc}", "code": "PARSE_ERROR"}
    try:
        files = json.loads(project_files_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid project_files_json: {exc}", "code": "PARSE_ERROR"}
    return compute_impact(eco, files)


def plm_create_sysml_doc(
    title: str,
    requirements_json: str | None = None,
) -> dict[str, Any]:
    """Create a new SysML-light requirements document.

    Parameters
    ----------
    title:
        System / document title.
    requirements_json:
        Optional JSON array of requirement objects (req_id, text, priority).
    """
    reqs: list[dict] | None = None
    if requirements_json:
        try:
            reqs = json.loads(requirements_json)
        except Exception as exc:
            return {"ok": False, "error": f"invalid requirements_json: {exc}", "code": "PARSE_ERROR"}
    return create_sysml_doc(title=title, requirements=reqs)


def plm_add_trace_link(
    doc_json: str,
    req_id: str,
    file_id: str,
    file_name: str,
    link_type: str = "satisfies",
) -> dict[str, Any]:
    """Add an implementation trace link to a requirement in a SysML doc.

    Parameters
    ----------
    doc_json:
        JSON string of the SysML document.
    req_id:
        Requirement ID to attach the link to.
    file_id:
        Kerf file id that satisfies/refines/derives the requirement.
    file_name:
        Human-readable name of the file.
    link_type:
        One of satisfies, refines, derives.
    """
    try:
        doc = json.loads(doc_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid doc_json: {exc}", "code": "PARSE_ERROR"}
    return add_trace_link(doc, req_id, file_id, file_name, link_type)


def plm_add_verification(
    doc_json: str,
    req_id: str,
    test_id: str,
    method: str = "test",
    status: str = "pending",
) -> dict[str, Any]:
    """Add a verification test link to a requirement in a SysML doc.

    Parameters
    ----------
    doc_json:
        JSON string of the SysML document.
    req_id:
        Requirement ID.
    test_id:
        Test identifier (pytest node id, JIRA ticket, etc.).
    method:
        One of test, analysis, inspection, demonstration.
    status:
        One of pending, pass, fail.
    """
    try:
        doc = json.loads(doc_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid doc_json: {exc}", "code": "PARSE_ERROR"}
    return add_verification(doc, req_id, test_id, method, status)


def plm_trace(
    doc_json: str,
    req_id: str | None = None,
) -> dict[str, Any]:
    """Resolve requirement → implementation → verification chain.

    Parameters
    ----------
    doc_json:
        JSON string of the SysML document.
    req_id:
        Optional.  If given, return chain for this req only.
        If omitted, return chains for all requirements.
    """
    try:
        doc = json.loads(doc_json)
    except Exception as exc:
        return {"ok": False, "error": f"invalid doc_json: {exc}", "code": "PARSE_ERROR"}
    return trace(doc, req_id or None)


# ---------------------------------------------------------------------------
# Anthropic-style tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "plm_bom_150_percent",
        "description": (
            "Generate a 150% (superset) BOM for a project — all parts ever used, "
            "with per-part effectivity windows.  Pass an effectivity_date to mark "
            "which parts are currently effective."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_files_json": {
                    "type": "string",
                    "description": "JSON array of project file objects (id, name, kind, content, parent_id).",
                },
                "effectivity_date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD) to filter effective parts.  Omit for full superset.",
                },
            },
            "required": ["project_files_json"],
        },
    },
    {
        "name": "plm_where_used",
        "description": (
            "Walk the assembly graph upward from a part and return every parent "
            "assembly (direct + transitive) with effectivity info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "part_id": {
                    "type": "string",
                    "description": "File id of the part to look up.",
                },
                "project_files_json": {
                    "type": "string",
                    "description": "JSON array of project file objects.",
                },
            },
            "required": ["part_id", "project_files_json"],
        },
    },
    {
        "name": "plm_create_eco",
        "description": (
            "Create a new Engineering Change Order (ECO/ECR) with from-state / "
            "to-state and an auto-computed impact list via where-used roll-up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "requestor": {"type": "string"},
                "affected_parts_json": {
                    "type": "string",
                    "description": (
                        "JSON array of part-change records.  Each has: "
                        "part_id, from_state {name, content}, "
                        "to_state {name, content}, change_type (add|remove|modify|replace)."
                    ),
                },
                "project_files_json": {
                    "type": "string",
                    "description": "Optional JSON array of project files for impact roll-up.",
                },
                "verification_tests_json": {
                    "type": "string",
                    "description": "Optional JSON array of test ID strings.",
                },
                "linked_requirements_json": {
                    "type": "string",
                    "description": "Optional JSON array of SysML req IDs.",
                },
            },
            "required": ["title", "description", "requestor", "affected_parts_json"],
        },
    },
    {
        "name": "plm_validate_eco",
        "description": "Validate an ECO JSON document and return any schema errors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "eco_json": {"type": "string", "description": "JSON string of the ECO object."},
            },
            "required": ["eco_json"],
        },
    },
    {
        "name": "plm_compute_eco_impact",
        "description": "Recompute the impact list for an ECO using current project files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "eco_json": {"type": "string"},
                "project_files_json": {"type": "string"},
            },
            "required": ["eco_json", "project_files_json"],
        },
    },
    {
        "name": "plm_create_sysml_doc",
        "description": (
            "Create a new SysML-light requirements document with top-level "
            "requirements and optional trace links / verification entries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "requirements_json": {
                    "type": "string",
                    "description": "Optional JSON array of {req_id, text, priority} objects.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "plm_add_trace_link",
        "description": "Attach an implementation file to a SysML requirement (satisfies/refines/derives).",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_json": {"type": "string"},
                "req_id": {"type": "string"},
                "file_id": {"type": "string"},
                "file_name": {"type": "string"},
                "link_type": {
                    "type": "string",
                    "enum": ["satisfies", "refines", "derives"],
                    "default": "satisfies",
                },
            },
            "required": ["doc_json", "req_id", "file_id", "file_name"],
        },
    },
    {
        "name": "plm_add_verification",
        "description": "Add a verification test to a SysML requirement.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_json": {"type": "string"},
                "req_id": {"type": "string"},
                "test_id": {"type": "string"},
                "method": {
                    "type": "string",
                    "enum": ["test", "analysis", "inspection", "demonstration"],
                    "default": "test",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "pass", "fail"],
                    "default": "pending",
                },
            },
            "required": ["doc_json", "req_id", "test_id"],
        },
    },
    {
        "name": "plm_trace",
        "description": (
            "Resolve the full requirement → implementation → verification chain "
            "for all (or a specific) requirement in a SysML document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_json": {"type": "string"},
                "req_id": {
                    "type": "string",
                    "description": "Optional.  Restrict to one requirement.",
                },
            },
            "required": ["doc_json"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher (for kerf-chat or agent use)
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Any] = {
    "plm_bom_150_percent": plm_bom_150_percent,
    "plm_where_used": plm_where_used,
    "plm_create_eco": plm_create_eco,
    "plm_validate_eco": plm_validate_eco,
    "plm_compute_eco_impact": plm_compute_eco_impact,
    "plm_create_sysml_doc": plm_create_sysml_doc,
    "plm_add_trace_link": plm_add_trace_link,
    "plm_add_verification": plm_add_verification,
    "plm_trace": plm_trace,
}


def dispatch(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Call a PLM tool by name with the given input dict."""
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        return {"ok": False, "error": f"unknown PLM tool: {tool_name!r}", "code": "NOT_FOUND"}
    try:
        return fn(**tool_input)
    except TypeError as exc:
        return {"ok": False, "error": f"tool argument error: {exc}", "code": "BAD_ARGS"}
