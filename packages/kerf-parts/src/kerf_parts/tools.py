"""LLM-callable tools for kerf-parts.

Exposes ``substitute_component`` — the seam that resolves a library component_id
(a Library Part file-id already in the project) to a materialized geometry
descriptor (STEP bytes reference or JSCAD source).

Cache contract:
  - Results are cached in ``_SUBST_CACHE`` keyed by ``component_id`` so that
    100 identical M6 bolts in an assembly only fetch and parse geometry once per
    process lifetime.
  - The cache is intentionally process-scoped (not request-scoped) because the
    library parts corpus changes infrequently. Call ``clear_substitute_cache()``
    in tests or if part content is updated.

Registration pattern:
  TOOLS list follows the same ``(name, spec, handler)`` triple convention used
  by ``kerf-woodworking`` so ``plugin.py``'s ``_register_tools`` loop just
  iterates it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# ToolSpec compat shim — mirrors kerf-woodworking._compat
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload  # type: ignore
except Exception:
    # Hermetic fallback when kerf_chat is not on sys.path (contributor / test envs).
    from dataclasses import dataclass as _dc

    @_dc
    class ToolSpec:  # type: ignore[no-redef]
        name: str
        description: str
        input_schema: dict

    def ok_payload(v: Any) -> str:  # type: ignore[misc]
        return json.dumps(v)

    def err_payload(msg: str, code: str) -> str:  # type: ignore[misc]
        return json.dumps({"error": msg, "code": code})


# ---------------------------------------------------------------------------
# In-memory geometry cache (process-scoped, keyed by component_id)
# ---------------------------------------------------------------------------

_SUBST_CACHE: dict[str, dict] = {}


def clear_substitute_cache() -> None:
    """Clear the process-level geometry cache (call between tests or after part updates)."""
    _SUBST_CACHE.clear()


def _resolve_geometry(part_doc: dict) -> dict | None:
    """Extract the geometry descriptor from a Library Part document.

    A Library Part document (``kind='part'``) may carry one or more geometry
    hints:

    1. ``model_3d`` — a JSCAD source string (the primary desktop-geometry path).
    2. ``model_3d_paths`` — a list of relative STEP/WRL paths (set by
       ``kerf-imports``' KiCad adapter).  We pick the first ``.step`` or
       ``.stp`` entry and return it for the STEP substitution path.

    Returns a descriptor dict with exactly one of:
        ``{"kind": "jscad",  "source": "<js source string>"}``
        ``{"kind": "step",   "path":   "<relative path>"}``

    Returns ``None`` when neither hint is present (the caller shows the
    indicator chip).
    """
    if not isinstance(part_doc, dict):
        return None

    # Prefer JSCAD — richer, client-side eval, no extra round-trip.
    src = part_doc.get("model_3d")
    if isinstance(src, str) and src.strip():
        return {"kind": "jscad", "source": src}

    # Fall back to the first STEP/STP path in model_3d_paths.
    paths = part_doc.get("model_3d_paths")
    if isinstance(paths, list):
        for p in paths:
            if isinstance(p, str) and p.lower().endswith((".step", ".stp")):
                return {"kind": "step", "path": p}

    return None


# ---------------------------------------------------------------------------
# substitute_component tool
# ---------------------------------------------------------------------------

_substitute_component_spec = ToolSpec(
    name="substitute_component",
    description=(
        "Resolve a Library Part component_id to its materialized geometry "
        "descriptor. Returns a {kind, source|path} object for the caller to "
        "splice into the 3D viewport. Result is cached per component_id so "
        "100 identical M6 bolts in an assembly load geometry only once."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": (
                    "The Library Part file-id (UUID string from the `files` table "
                    "with kind='part') to resolve to geometry."
                ),
            },
            "part_content": {
                "type": "string",
                "description": (
                    "The raw JSON content of the Library Part file (the caller "
                    "fetches this and passes it in to keep the tool stateless). "
                    "Must parse to a {version, name, model_3d?, model_3d_paths?, ...} "
                    "document."
                ),
            },
            "bust_cache": {
                "type": "boolean",
                "description": (
                    "When true, ignore any cached result for this component_id and "
                    "re-resolve from part_content. Useful after a Part is edited. "
                    "Defaults to false."
                ),
            },
        },
        "required": ["component_id", "part_content"],
    },
)


async def _run_substitute_component(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    component_id = a.get("component_id", "")
    part_content_raw = a.get("part_content", "")
    bust_cache = bool(a.get("bust_cache", False))

    if not isinstance(component_id, str) or not component_id.strip():
        return err_payload("component_id must be a non-empty string", "BAD_ARGS")
    if not isinstance(part_content_raw, str) or not part_content_raw.strip():
        return err_payload("part_content must be a non-empty string", "BAD_ARGS")

    # Cache hit (unless cache-bust requested).
    if not bust_cache and component_id in _SUBST_CACHE:
        cached = _SUBST_CACHE[component_id]
        return ok_payload({"component_id": component_id, "cached": True, **cached})

    # Parse the part document.
    try:
        part_doc = json.loads(part_content_raw)
    except json.JSONDecodeError as exc:
        return err_payload(f"part_content is not valid JSON: {exc}", "BAD_ARGS")

    if not isinstance(part_doc, dict):
        return err_payload("part_content must be a JSON object", "BAD_ARGS")

    descriptor = _resolve_geometry(part_doc)
    if descriptor is None:
        # No geometry hint — return a clear "no geometry" result so the
        # caller knows to keep the indicator chip rather than blow up.
        return ok_payload({
            "component_id": component_id,
            "cached": False,
            "kind": "none",
            "name": part_doc.get("name", ""),
        })

    result = {"component_id": component_id, "cached": False, **descriptor}
    # Cache the descriptor (not the full part doc — keeps memory bounded).
    _SUBST_CACHE[component_id] = descriptor
    return ok_payload(result)


# ---------------------------------------------------------------------------
# TOOLS registration list — iterated by plugin.py
# ---------------------------------------------------------------------------

TOOLS: list[tuple[str, ToolSpec, Any]] = [
    ("substitute_component", _substitute_component_spec, _run_substitute_component),
]
