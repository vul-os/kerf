"""
tools/bcf.py — LLM tools for BCF 3.0 issue management.

Registered LLM tools
--------------------
bim_create_bcf_topic       — create a new clash/issue topic in a BcfProject
bim_add_bcf_comment        — add a comment to an existing topic
bim_export_bcf_zip         — serialise a BcfProject to a BCF 3.0 .bcf zip
bim_import_bcf_zip         — parse a BCF .bcf zip into a BcfProject dict
bim_summarize_bcf_project  — return counts by status/priority

All functions operate on plain JSON-serialisable dicts so the LLM never
sees Python objects directly — the project dict is round-tripped through
the BcfProject dataclass on each call.
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx  # noqa: F401  (for type hints)
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore

from kerf_bim.bcf import (
    BcfComment,
    BcfProject,
    BcfTopic,
    BcfViewpoint,
    VALID_PRIORITIES,
    VALID_STATUSES,
    VALID_TOPIC_TYPES,
    add_comment,
    add_viewpoint,
    create_topic,
    export_bcf_zip,
    import_bcf_zip,
    summarize_project,
    update_topic_status,
    _new_guid,
)


# ── serialisation helpers ─────────────────────────────────────────────────────

def _project_to_dict(p: BcfProject) -> dict:
    return {
        "project_id": p.project_id,
        "name":       p.name,
        "topics": [
            {k: v for k, v in t.__dict__.items()}
            for t in p.topics
        ],
        "comments": [
            {k: v for k, v in c.__dict__.items()}
            for c in p.comments
        ],
        "viewpoints": [
            {
                **{k: v for k, v in vp.__dict__.items() if k not in ("camera_position_xyz", "camera_target_xyz")},
                "camera_position_xyz": list(vp.camera_position_xyz),
                "camera_target_xyz":   list(vp.camera_target_xyz),
            }
            for vp in p.viewpoints
        ],
    }


def _project_from_dict(d: dict) -> BcfProject:
    topics = [BcfTopic(**t) for t in d.get("topics", [])]
    comments = [BcfComment(**c) for c in d.get("comments", [])]
    viewpoints = [
        BcfViewpoint(
            **{k: v for k, v in vp.items() if k not in ("camera_position_xyz", "camera_target_xyz")},
            camera_position_xyz=tuple(vp["camera_position_xyz"]),
            camera_target_xyz=tuple(vp["camera_target_xyz"]),
        )
        for vp in d.get("viewpoints", [])
    ]
    return BcfProject(
        project_id = d["project_id"],
        name       = d["name"],
        topics     = topics,
        comments   = comments,
        viewpoints = viewpoints,
    )


# ── bim_create_bcf_topic ──────────────────────────────────────────────────────

_create_topic_spec = ToolSpec(
    name="bim_create_bcf_topic",
    description=(
        "Create a new BCF 3.0 topic (clash, issue, RFI, etc.) in a BcfProject "
        "and return the updated project dict together with the new topic GUID.\n\n"
        "Pass the project dict returned by a previous bim_* call (or an empty "
        "project skeleton: {\"project_id\": \"<uuid>\", \"name\": \"My Project\", "
        "\"topics\": [], \"comments\": [], \"viewpoints\": []}).\n\n"
        "topic_type: Clash | Issue | Request | Fault | Inquiry\n"
        "priority:   Critical | Normal | Minor\n"
        "status:     Open | In Progress | Resolved | Closed"
    ),
    input_schema={
        "type": "object",
        "required": ["project", "title"],
        "properties": {
            "project":        {"type": "object", "description": "BcfProject dict"},
            "title":          {"type": "string"},
            "description":    {"type": "string", "default": ""},
            "topic_type":     {"type": "string", "default": "Issue",
                               "enum": sorted(VALID_TOPIC_TYPES)},
            "priority":       {"type": "string", "default": "Normal",
                               "enum": sorted(VALID_PRIORITIES)},
            "status":         {"type": "string", "default": "Open",
                               "enum": sorted(VALID_STATUSES)},
            "assigned_to":    {"type": "string", "default": ""},
            "creation_author":{"type": "string", "default": ""},
            "due_date_iso":   {"type": "string", "default": ""},
        },
    },
)


async def _handle_create_bcf_topic(args: dict, _ctx) -> dict:
    try:
        project = _project_from_dict(args["project"])
        topic = create_topic(
            project,
            title          = args["title"],
            description    = args.get("description", ""),
            topic_type     = args.get("topic_type", "Issue"),
            priority       = args.get("priority", "Normal"),
            status         = args.get("status", "Open"),
            assigned_to    = args.get("assigned_to", ""),
            creation_author= args.get("creation_author", ""),
            due_date_iso   = args.get("due_date_iso", ""),
        )
        return ok_payload({
            "project":    _project_to_dict(project),
            "topic_guid": topic.guid,
            "topic_title": topic.title,
        })
    except Exception as exc:
        return err_payload(str(exc))


# ── bim_add_bcf_comment ───────────────────────────────────────────────────────

_add_comment_spec = ToolSpec(
    name="bim_add_bcf_comment",
    description=(
        "Add a comment to an existing BCF 3.0 topic. "
        "Provide the project dict and the target topic_guid."
    ),
    input_schema={
        "type": "object",
        "required": ["project", "topic_guid", "comment"],
        "properties": {
            "project":    {"type": "object", "description": "BcfProject dict"},
            "topic_guid": {"type": "string"},
            "comment":    {"type": "string"},
            "author":     {"type": "string", "default": ""},
        },
    },
)


async def _handle_add_bcf_comment(args: dict, _ctx) -> dict:
    try:
        project = _project_from_dict(args["project"])
        c = add_comment(
            project,
            topic_guid = args["topic_guid"],
            comment    = args["comment"],
            author     = args.get("author", ""),
        )
        return ok_payload({
            "project":      _project_to_dict(project),
            "comment_guid": c.guid,
        })
    except Exception as exc:
        return err_payload(str(exc))


# ── bim_export_bcf_zip ────────────────────────────────────────────────────────

_export_zip_spec = ToolSpec(
    name="bim_export_bcf_zip",
    description=(
        "Serialise a BcfProject to a BCF 3.0 compliant .bcf ZIP file. "
        "Provide the project dict and an output_path (e.g. /tmp/project.bcf). "
        "Returns the file path and topic/comment/viewpoint counts."
    ),
    input_schema={
        "type": "object",
        "required": ["project", "output_path"],
        "properties": {
            "project":     {"type": "object", "description": "BcfProject dict"},
            "output_path": {"type": "string",
                            "description": "Absolute path to write the .bcf zip"},
        },
    },
)


async def _handle_export_bcf_zip(args: dict, _ctx) -> dict:
    try:
        project = _project_from_dict(args["project"])
        result  = export_bcf_zip(project, args["output_path"])
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc))


# ── bim_import_bcf_zip ────────────────────────────────────────────────────────

_import_zip_spec = ToolSpec(
    name="bim_import_bcf_zip",
    description=(
        "Parse a BCF 3.0 (or BCF 2.x) .bcf ZIP file and return a BcfProject dict "
        "that can be passed to other bim_* tools. "
        "Provide the absolute path to the .bcf file."
    ),
    input_schema={
        "type": "object",
        "required": ["zip_path"],
        "properties": {
            "zip_path": {"type": "string",
                         "description": "Absolute path to the .bcf zip to import"},
        },
    },
)


async def _handle_import_bcf_zip(args: dict, _ctx) -> dict:
    try:
        project = import_bcf_zip(args["zip_path"])
        return ok_payload({
            "project":  _project_to_dict(project),
            "summary":  summarize_project(project),
        })
    except Exception as exc:
        return err_payload(str(exc))


# ── bim_summarize_bcf_project ─────────────────────────────────────────────────

_summarize_spec = ToolSpec(
    name="bim_summarize_bcf_project",
    description=(
        "Return a summary dict with topic counts broken down by status and "
        "priority, plus total comment and viewpoint counts."
    ),
    input_schema={
        "type": "object",
        "required": ["project"],
        "properties": {
            "project": {"type": "object", "description": "BcfProject dict"},
        },
    },
)


async def _handle_summarize_bcf_project(args: dict, _ctx) -> dict:
    try:
        project = _project_from_dict(args["project"])
        return ok_payload(summarize_project(project))
    except Exception as exc:
        return err_payload(str(exc))


# ── TOOLS list (consumed by plugin.py) ────────────────────────────────────────

TOOLS = [
    ("bim_create_bcf_topic",      _create_topic_spec,  _handle_create_bcf_topic),
    ("bim_add_bcf_comment",       _add_comment_spec,   _handle_add_bcf_comment),
    ("bim_export_bcf_zip",        _export_zip_spec,    _handle_export_bcf_zip),
    ("bim_import_bcf_zip",        _import_zip_spec,    _handle_import_bcf_zip),
    ("bim_summarize_bcf_project", _summarize_spec,     _handle_summarize_bcf_project),
]
