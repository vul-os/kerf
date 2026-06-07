"""
tools/worksharing.py — LLM tools for BIM worksharing (central model + worksets +
element borrow/release + sync-to-central).

Worksharing model (honest):
  This implements the *checkout / borrow / sync* worksharing model — the same model
  used by Revit Worksharing.  It is NOT live real-time co-editing (no OT/CRDT);
  rather, each user borrows elements exclusively, edits locally, then
  synchronises back to the central model.  Conflicts are detected when two users
  edited the same element and flagged for manual resolution.

Tools
-----
bim_worksharing_create_workset  — add a named workset to the central manifest
bim_worksharing_assign_element  — assign an element to a workset
bim_worksharing_borrow          — borrow (check out) an element for exclusive editing
bim_worksharing_release         — release a borrow without committing edits
bim_worksharing_update_local    — store local edit payload for a borrowed element
bim_worksharing_sync            — sync-to-central: push edits + pull others' changes
bim_worksharing_status          — summary of current borrow/workset state
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manifest_from_arg(raw: Any):
    """Parse WorksharingManifest from a JSON string or dict arg."""
    from kerf_bim.worksharing import WorksharingManifest
    if isinstance(raw, str):
        return WorksharingManifest.from_json(raw) if raw.strip() else WorksharingManifest()
    if isinstance(raw, dict):
        return WorksharingManifest.from_dict(raw)
    return WorksharingManifest()


# ---------------------------------------------------------------------------
# bim_worksharing_create_workset
# ---------------------------------------------------------------------------

_create_workset_spec = ToolSpec(
    name="bim_worksharing_create_workset",
    description=(
        "Add a named workset to the BIM central model's worksharing manifest.\n"
        "\n"
        "Worksets are named element groups (e.g. 'Architecture', 'Structure', 'MEP'). "
        "Each workset has an optional owner who has blanket borrow rights over all its "
        "elements.  Other users can still borrow individual elements from any workset.\n"
        "\n"
        "Returns: {ok, workset, manifest_json}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {
                "type": "string",
                "description": "Current WorksharingManifest as JSON (pass '{}' for new).",
            },
            "workset_id": {
                "type": "string",
                "description": "Unique workset identifier (e.g. 'ws-arch').",
            },
            "name": {
                "type": "string",
                "description": "Human-readable workset name (e.g. 'Architecture').",
            },
            "owner_email": {
                "type": "string",
                "description": "Email of the user who owns this workset (optional).",
                "default": "",
            },
            "kind": {
                "type": "string",
                "enum": ["user", "standard", "view", "family"],
                "description": "Workset kind (default: 'user').",
                "default": "user",
            },
        },
        "required": ["manifest_json", "workset_id", "name"],
    },
)


async def run_bim_worksharing_create_workset(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.worksharing import workset_create
        manifest = _manifest_from_arg(params.get("manifest_json", "{}"))
        workset_id = params.get("workset_id", "").strip()
        name = params.get("name", "").strip()
        owner_email = str(params.get("owner_email", ""))
        kind = str(params.get("kind", "user"))

        if not workset_id or not name:
            return err_payload("workset_id and name are required", "BAD_ARGS")

        ws = workset_create(manifest, workset_id, name, owner_email, kind)
        return ok_payload({
            "ok": True,
            "workset": ws.to_dict(),
            "manifest_json": manifest.to_json(),
        })
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "WORKSHARING_ERROR")


# ---------------------------------------------------------------------------
# bim_worksharing_assign_element
# ---------------------------------------------------------------------------

_assign_element_spec = ToolSpec(
    name="bim_worksharing_assign_element",
    description=(
        "Assign a BIM element to a workset (moves it out of any previous workset).\n"
        "\n"
        "Returns: {ok, manifest_json}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {"type": "string"},
            "element_id": {"type": "string", "description": "Element to assign."},
            "workset_id": {"type": "string", "description": "Target workset ID."},
        },
        "required": ["manifest_json", "element_id", "workset_id"],
    },
)


async def run_bim_worksharing_assign_element(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.worksharing import workset_assign_element
        manifest = _manifest_from_arg(params.get("manifest_json", "{}"))
        element_id = params.get("element_id", "").strip()
        workset_id = params.get("workset_id", "").strip()
        if not element_id or not workset_id:
            return err_payload("element_id and workset_id are required", "BAD_ARGS")
        ok = workset_assign_element(manifest, element_id, workset_id)
        return ok_payload({
            "ok": ok,
            "reason": "" if ok else f"Workset '{workset_id}' not found.",
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "WORKSHARING_ERROR")


# ---------------------------------------------------------------------------
# bim_worksharing_borrow
# ---------------------------------------------------------------------------

_borrow_spec = ToolSpec(
    name="bim_worksharing_borrow",
    description=(
        "Borrow (check out) a BIM element for exclusive editing by user_email.\n"
        "\n"
        "This is the worksharing equivalent of Revit's 'borrow element': the element "
        "is locked for the user for duration_hours (default 8).  A second user trying "
        "to borrow the same element will be blocked until it is released or expires.\n"
        "\n"
        "A user re-borrowing their own element refreshes the expiry (safe/idempotent).\n"
        "\n"
        "Returns: {ok, borrow, conflict_holder, reason, manifest_json}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {"type": "string"},
            "element_id": {"type": "string"},
            "user_email": {"type": "string"},
            "duration_hours": {"type": "number", "default": 8.0},
        },
        "required": ["manifest_json", "element_id", "user_email"],
    },
)


async def run_bim_worksharing_borrow(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.worksharing import borrow_element
        manifest = _manifest_from_arg(params.get("manifest_json", "{}"))
        element_id = params.get("element_id", "").strip()
        user_email = params.get("user_email", "").strip()
        duration = float(params.get("duration_hours", 8.0))
        if not element_id or not user_email:
            return err_payload("element_id and user_email are required", "BAD_ARGS")
        ok, reason = borrow_element(manifest, element_id, user_email, duration)
        borrow_entry = manifest._find_borrow(element_id)
        return ok_payload({
            "ok": ok,
            "borrow": borrow_entry.to_dict() if ok and borrow_entry else None,
            "conflict_holder": None if ok else (
                manifest._find_borrow(element_id).borrowed_by_email
                if manifest._find_borrow(element_id) else None
            ),
            "reason": reason,
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "WORKSHARING_ERROR")


# ---------------------------------------------------------------------------
# bim_worksharing_release
# ---------------------------------------------------------------------------

_release_spec = ToolSpec(
    name="bim_worksharing_release",
    description=(
        "Release a borrowed element WITHOUT committing any edits (discard local changes).\n"
        "\n"
        "Only the user who borrowed the element can release it.\n"
        "\n"
        "Returns: {ok, reason, manifest_json}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {"type": "string"},
            "element_id": {"type": "string"},
            "user_email": {"type": "string"},
        },
        "required": ["manifest_json", "element_id", "user_email"],
    },
)


async def run_bim_worksharing_release(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.worksharing import release_element
        manifest = _manifest_from_arg(params.get("manifest_json", "{}"))
        element_id = params.get("element_id", "").strip()
        user_email = params.get("user_email", "").strip()
        if not element_id or not user_email:
            return err_payload("element_id and user_email are required", "BAD_ARGS")
        ok = release_element(manifest, element_id, user_email)
        return ok_payload({
            "ok": ok,
            "reason": "" if ok else "Borrow not found or not owned by this user.",
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "WORKSHARING_ERROR")


# ---------------------------------------------------------------------------
# bim_worksharing_update_local
# ---------------------------------------------------------------------------

_update_local_spec = ToolSpec(
    name="bim_worksharing_update_local",
    description=(
        "Store the user's local edit payload for a borrowed element.\n"
        "\n"
        "Call this after borrowing an element and making changes locally.  The payload "
        "is persisted in the manifest and will be pushed to central on the next "
        "bim_worksharing_sync call.\n"
        "\n"
        "Returns: {ok, reason, manifest_json}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {"type": "string"},
            "element_id": {"type": "string"},
            "user_email": {"type": "string"},
            "element_data": {
                "type": "object",
                "description": "Arbitrary JSON dict of the element's updated properties.",
            },
        },
        "required": ["manifest_json", "element_id", "user_email", "element_data"],
    },
)


async def run_bim_worksharing_update_local(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.worksharing import update_local_data
        manifest = _manifest_from_arg(params.get("manifest_json", "{}"))
        element_id = params.get("element_id", "").strip()
        user_email = params.get("user_email", "").strip()
        element_data = params.get("element_data", {})
        if not element_id or not user_email:
            return err_payload("element_id and user_email are required", "BAD_ARGS")
        ok = update_local_data(manifest, element_id, user_email, element_data)
        return ok_payload({
            "ok": ok,
            "reason": "" if ok else "Element not borrowed by this user or borrow expired.",
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "WORKSHARING_ERROR")


# ---------------------------------------------------------------------------
# bim_worksharing_sync
# ---------------------------------------------------------------------------

_sync_spec = ToolSpec(
    name="bim_worksharing_sync",
    description=(
        "Sync the user's borrowed-element edits to the central model (sync-to-central).\n"
        "\n"
        "This implements Revit's 'Synchronize with Central' workflow:\n"
        "  1. For each borrowed element with local edits: push to central (release borrow).\n"
        "  2. Pull all other users' committed changes from central.\n"
        "  3. Detect conflicts: same element edited by two users → conflict list.\n"
        "\n"
        "This is NOT live real-time co-editing; it is the standard checkout/sync "
        "worksharing model identical to Revit Worksharing.\n"
        "\n"
        "Returns: {ok, synced_elements, pulled_elements, conflicts, released_borrows, "
        "          manifest_json, message}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {"type": "string"},
            "user_email": {"type": "string"},
        },
        "required": ["manifest_json", "user_email"],
    },
)


async def run_bim_worksharing_sync(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.worksharing import sync_to_central
        manifest = _manifest_from_arg(params.get("manifest_json", "{}"))
        user_email = params.get("user_email", "").strip()
        if not user_email:
            return err_payload("user_email is required", "BAD_ARGS")
        result = sync_to_central(manifest, user_email)
        return ok_payload({
            **result.to_dict(),
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "WORKSHARING_ERROR")


# ---------------------------------------------------------------------------
# bim_worksharing_status
# ---------------------------------------------------------------------------

_status_spec = ToolSpec(
    name="bim_worksharing_status",
    description=(
        "Return a summary of the current worksharing state: worksets, active borrows "
        "by user, and central element count.\n"
        "\n"
        "Returns: {project_id, workset_count, active_borrow_count, central_element_count, "
        "          borrows_by_user, worksets, last_sync_iso}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {"type": "string"},
        },
        "required": ["manifest_json"],
    },
)


async def run_bim_worksharing_status(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.worksharing import worksharing_status
        manifest = _manifest_from_arg(params.get("manifest_json", "{}"))
        status = worksharing_status(manifest)
        return ok_payload({"ok": True, **status})
    except Exception as exc:
        return err_payload(str(exc), "WORKSHARING_ERROR")


# ---------------------------------------------------------------------------
# TOOLS registration list
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_worksharing_create_workset", _create_workset_spec, run_bim_worksharing_create_workset),
    ("bim_worksharing_assign_element", _assign_element_spec, run_bim_worksharing_assign_element),
    ("bim_worksharing_borrow",         _borrow_spec,         run_bim_worksharing_borrow),
    ("bim_worksharing_release",        _release_spec,        run_bim_worksharing_release),
    ("bim_worksharing_update_local",   _update_local_spec,   run_bim_worksharing_update_local),
    ("bim_worksharing_sync",           _sync_spec,           run_bim_worksharing_sync),
    ("bim_worksharing_status",         _status_spec,         run_bim_worksharing_status),
]
