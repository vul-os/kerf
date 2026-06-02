"""
tools/element_lock.py — LLM tools for BIMcloud-lite element-level locking.

Tools
-----
bim_request_lock         — claim an exclusive edit lock on a BIM element
bim_release_lock         — give up a lock
bim_extend_lock          — push the expiry of an active lock forward
bim_list_locks           — list locks (per user, or all active)
bim_cleanup_expired_locks — remove expired locks from the manifest
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# bim_request_lock
# ---------------------------------------------------------------------------

_request_lock_spec = ToolSpec(
    name="bim_request_lock",
    description=(
        "Claim an exclusive edit lock on a BIM element for a user.\n"
        "\n"
        "If the element is unlocked (or its lock has expired), the lock is granted\n"
        "immediately.  If another user holds an active lock, the request fails and\n"
        "conflict_user identifies the holder.\n"
        "\n"
        "A user re-requesting their own active lock silently refreshes the expiry.\n"
        "\n"
        "Returns: {ok, lock: {element_id, locked_by_email, locked_at_iso,\n"
        "         expires_at_iso, lock_comment}, conflict_user, reason}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {
                "type": "string",
                "description": "Current LockManifest as a JSON string (pass '{}' or '{\"locks\":[]}' for an empty manifest).",
            },
            "element_id": {
                "type": "string",
                "description": "Unique identifier of the BIM element to lock.",
            },
            "user_email": {
                "type": "string",
                "description": "Email address of the requesting user.",
            },
            "lock_duration_hours": {
                "type": "number",
                "description": "How long the lock should be valid (default 8.0 hours).",
                "default": 8.0,
            },
            "comment": {
                "type": "string",
                "description": "Optional note explaining why the element is locked.",
                "default": "",
            },
        },
        "required": ["manifest_json", "element_id", "user_email"],
    },
)


async def run_bim_request_lock(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.element_lock import (
            LockManifest, LockRequest, request_lock,
        )

        raw = params.get("manifest_json", "{}")
        if not raw:
            raw = "{}"
        try:
            manifest = LockManifest.from_json(raw)
        except Exception:
            manifest = LockManifest()

        element_id = params.get("element_id", "").strip()
        user_email = params.get("user_email", "").strip()
        if not element_id or not user_email:
            return err_payload("element_id and user_email are required", "BAD_ARGS")

        request = LockRequest(
            element_id=element_id,
            user_email=user_email,
            lock_duration_hours=float(params.get("lock_duration_hours", 8.0)),
            comment=str(params.get("comment", "")),
        )

        result = request_lock(manifest, request)

        return ok_payload({
            "ok": result.success,
            "lock": result.lock.to_dict() if result.lock else None,
            "conflict_user": result.conflict_user,
            "reason": result.reason,
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "BIM_LOCK_ERROR")


# ---------------------------------------------------------------------------
# bim_release_lock
# ---------------------------------------------------------------------------

_release_lock_spec = ToolSpec(
    name="bim_release_lock",
    description=(
        "Release a BIM element lock held by *user_email*.\n"
        "\n"
        "Only the user who acquired the lock can release it.  Returns ok=True on\n"
        "success, ok=False if the lock was not found or the caller doesn't own it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {
                "type": "string",
                "description": "Current LockManifest as JSON.",
            },
            "element_id": {
                "type": "string",
                "description": "Element whose lock should be released.",
            },
            "user_email": {
                "type": "string",
                "description": "Email of the user releasing the lock (must be the owner).",
            },
        },
        "required": ["manifest_json", "element_id", "user_email"],
    },
)


async def run_bim_release_lock(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.element_lock import LockManifest, release_lock

        raw = params.get("manifest_json", "{}")
        manifest = LockManifest.from_json(raw) if raw else LockManifest()
        element_id = params.get("element_id", "").strip()
        user_email = params.get("user_email", "").strip()

        if not element_id or not user_email:
            return err_payload("element_id and user_email are required", "BAD_ARGS")

        released = release_lock(manifest, element_id, user_email)
        return ok_payload({
            "ok": released,
            "reason": "" if released else "Lock not found or not owned by this user.",
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "BIM_LOCK_ERROR")


# ---------------------------------------------------------------------------
# bim_extend_lock
# ---------------------------------------------------------------------------

_extend_lock_spec = ToolSpec(
    name="bim_extend_lock",
    description=(
        "Extend the expiry of an active BIM element lock by *additional_hours*.\n"
        "\n"
        "Only the lock owner can extend.  Returns ok=False if the lock is missing,\n"
        "already expired, or the caller is not the owner."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {
                "type": "string",
                "description": "Current LockManifest as JSON.",
            },
            "element_id": {
                "type": "string",
                "description": "Element whose lock should be extended.",
            },
            "user_email": {
                "type": "string",
                "description": "Email of the lock owner.",
            },
            "additional_hours": {
                "type": "number",
                "description": "Hours to add to the current expiry (e.g. 4.0 = 4 more hours).",
            },
        },
        "required": ["manifest_json", "element_id", "user_email", "additional_hours"],
    },
)


async def run_bim_extend_lock(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.element_lock import LockManifest, extend_lock

        raw = params.get("manifest_json", "{}")
        manifest = LockManifest.from_json(raw) if raw else LockManifest()
        element_id = params.get("element_id", "").strip()
        user_email = params.get("user_email", "").strip()
        additional_hours = float(params.get("additional_hours", 0.0))

        if not element_id or not user_email:
            return err_payload("element_id and user_email are required", "BAD_ARGS")
        if additional_hours <= 0:
            return err_payload("additional_hours must be positive", "BAD_ARGS")

        extended = extend_lock(manifest, element_id, user_email, additional_hours)
        return ok_payload({
            "ok": extended,
            "reason": "" if extended else "Lock not found, expired, or not owned by this user.",
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "BIM_LOCK_ERROR")


# ---------------------------------------------------------------------------
# bim_list_locks
# ---------------------------------------------------------------------------

_list_locks_spec = ToolSpec(
    name="bim_list_locks",
    description=(
        "List active BIM element locks.\n"
        "\n"
        "• If *user_email* is provided: returns only locks held by that user.\n"
        "• Otherwise: returns all currently active locks in the manifest.\n"
        "\n"
        "Returns: {ok, locks: [...], count}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {
                "type": "string",
                "description": "Current LockManifest as JSON.",
            },
            "user_email": {
                "type": "string",
                "description": "If provided, filter to locks owned by this user.",
                "default": "",
            },
        },
        "required": ["manifest_json"],
    },
)


async def run_bim_list_locks(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.element_lock import LockManifest, list_user_locks, list_all_active_locks

        raw = params.get("manifest_json", "{}")
        manifest = LockManifest.from_json(raw) if raw else LockManifest()
        user_email = params.get("user_email", "").strip()

        if user_email:
            locks = list_user_locks(manifest, user_email)
        else:
            locks = list_all_active_locks(manifest)

        return ok_payload({
            "ok": True,
            "locks": [lock.to_dict() for lock in locks],
            "count": len(locks),
        })
    except Exception as exc:
        return err_payload(str(exc), "BIM_LOCK_ERROR")


# ---------------------------------------------------------------------------
# bim_cleanup_expired_locks
# ---------------------------------------------------------------------------

_cleanup_spec = ToolSpec(
    name="bim_cleanup_expired_locks",
    description=(
        "Remove all expired locks from a LockManifest.\n"
        "\n"
        "Returns: {ok, removed_count, manifest_json}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manifest_json": {
                "type": "string",
                "description": "Current LockManifest as JSON.",
            },
        },
        "required": ["manifest_json"],
    },
)


async def run_bim_cleanup_expired_locks(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.element_lock import LockManifest, cleanup_expired_locks

        raw = params.get("manifest_json", "{}")
        manifest = LockManifest.from_json(raw) if raw else LockManifest()

        removed = cleanup_expired_locks(manifest)
        return ok_payload({
            "ok": True,
            "removed_count": removed,
            "manifest_json": manifest.to_json(),
        })
    except Exception as exc:
        return err_payload(str(exc), "BIM_LOCK_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_request_lock",          _request_lock_spec,  run_bim_request_lock),
    ("bim_release_lock",          _release_lock_spec,  run_bim_release_lock),
    ("bim_extend_lock",           _extend_lock_spec,   run_bim_extend_lock),
    ("bim_list_locks",            _list_locks_spec,    run_bim_list_locks),
    ("bim_cleanup_expired_locks", _cleanup_spec,       run_bim_cleanup_expired_locks),
]
