"""
xref.py — LLM tools for Federated XRef / Hotlinks.

Registers five tools:
  bim_add_xref           — add an external IFC file as a live reference
  bim_check_xref_status  — check whether a reference is stale / missing
  bim_refresh_xref       — re-import a reference and update its hash
  bim_compose_federated  — build the full federated model (all disciplines)
  bim_list_xrefs         — list all references in a manifest

All handlers are hermetically importable without kerf_chat / kerf_core so the
module can be unit-tested without the full server stack.
"""
from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Gated registry import — same pattern as export_ifc.py
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore
    from kerf_core.utils.context import ProjectCtx  # type: ignore
    _HAVE_REGISTRY = True
except ImportError:
    _HAVE_REGISTRY = False
    ToolSpec = dict          # type: ignore
    ProjectCtx = object      # type: ignore

    def register(spec, **kwargs):   # type: ignore
        def _dec(fn):
            return fn
        return _dec

    def err_payload(msg: str, code: str = "") -> str:  # type: ignore
        return json.dumps({"ok": False, "error": msg, "code": code})

    def ok_payload(data: Any) -> str:  # type: ignore
        return json.dumps({"ok": True, **data})


# ---------------------------------------------------------------------------
# Import xref module (always importable — no heavy deps)
# ---------------------------------------------------------------------------
from kerf_bim.xref import (
    XRefSpec,
    XRefManifest,
    add_xref,
    check_xref_status,
    refresh_xref,
    remove_xref,
    compose_federated_model,
    VALID_DISCIPLINES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manifest_from_arg(raw: Any) -> XRefManifest:
    """Parse manifest from an arg value (dict or JSON string)."""
    if isinstance(raw, str):
        return XRefManifest.from_json(raw)
    if isinstance(raw, dict):
        return XRefManifest.from_dict(raw)
    return XRefManifest()


def _spec_from_arg(a: dict[str, Any]) -> XRefSpec:
    origin_raw = a.get("reference_origin_xyz_mm") or [0, 0, 0]
    return XRefSpec(
        source_path=a.get("source_path", "").strip(),
        discipline=a.get("discipline", "").strip(),
        reference_origin_xyz_mm=tuple(float(v) for v in origin_raw[:3]),  # type: ignore[arg-type]
        reference_rotation_deg=float(a.get("reference_rotation_deg", 0.0)),
        last_loaded_hash=a.get("last_loaded_hash", ""),
    )


# ---------------------------------------------------------------------------
# Tool: bim_add_xref
# ---------------------------------------------------------------------------

if _HAVE_REGISTRY:
    _add_xref_spec = ToolSpec(
        name="bim_add_xref",
        description=(
            "Add an external IFC file as a live federated reference (XRef) to the project. "
            "Specify the path to the .ifc file, its discipline (structural/mep/architecture/civil), "
            "an optional placement origin in mm, and an optional Z-axis rotation. "
            "Returns an updated XRefManifest JSON containing all references."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "manifest": {
                    "description": "Existing XRefManifest JSON string or dict. Pass {} or omit for a new manifest.",
                },
                "source_path": {
                    "type": "string",
                    "description": "Absolute or project-relative path to the .ifc file.",
                },
                "discipline": {
                    "type": "string",
                    "enum": sorted(VALID_DISCIPLINES),
                    "description": "Discipline classification of the linked model.",
                },
                "reference_origin_xyz_mm": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "[x, y, z] offset in mm for composing into the federated model.",
                },
                "reference_rotation_deg": {
                    "type": "number",
                    "description": "Z-axis rotation in degrees (default 0).",
                },
            },
            "required": ["source_path", "discipline"],
        },
    )

    @register(_add_xref_spec, write=True)
    async def bim_add_xref(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            manifest = _manifest_from_arg(a.get("manifest") or {})
            spec = _spec_from_arg(a)
            spec.validate()
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        new_manifest = add_xref(manifest, spec)
        return ok_payload({
            "manifest": new_manifest.to_dict(),
            "ref_count": len(new_manifest.refs),
            "added": spec.to_dict(),
        })


# ---------------------------------------------------------------------------
# Tool: bim_check_xref_status
# ---------------------------------------------------------------------------

if _HAVE_REGISTRY:
    _check_status_spec = ToolSpec(
        name="bim_check_xref_status",
        description=(
            "Check whether a federated IFC reference is current, stale, or missing. "
            "Compares the stored SHA-256 hash against the current file on disk. "
            "No IFC parsing is performed — fast disk-hash only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Path to the .ifc file (same value used in bim_add_xref).",
                },
                "discipline": {
                    "type": "string",
                    "enum": sorted(VALID_DISCIPLINES),
                },
                "last_loaded_hash": {
                    "type": "string",
                    "description": "Hash stored in XRefSpec. Pass '' if never loaded.",
                },
            },
            "required": ["source_path", "discipline"],
        },
    )

    @register(_check_status_spec, write=False)
    async def bim_check_xref_status(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            spec = _spec_from_arg(a)
            spec.validate()
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        status = check_xref_status(spec)
        return ok_payload({"status": status.to_dict(), "source_path": spec.source_path})


# ---------------------------------------------------------------------------
# Tool: bim_refresh_xref
# ---------------------------------------------------------------------------

if _HAVE_REGISTRY:
    _refresh_spec = ToolSpec(
        name="bim_refresh_xref",
        description=(
            "Re-import a federated IFC reference from disk, update its SHA-256 hash, "
            "and return geometry statistics. "
            "Use after bim_check_xref_status reports is_stale=true. "
            "Returns {status, element_count, updated_spec}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Path to the .ifc file.",
                },
                "discipline": {
                    "type": "string",
                    "enum": sorted(VALID_DISCIPLINES),
                },
                "reference_origin_xyz_mm": {
                    "type": "array",
                    "items": {"type": "number"},
                },
                "reference_rotation_deg": {"type": "number"},
                "last_loaded_hash": {"type": "string"},
            },
            "required": ["source_path", "discipline"],
        },
    )

    @register(_refresh_spec, write=True)
    async def bim_refresh_xref(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            spec = _spec_from_arg(a)
            spec.validate()
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        try:
            _body, status = refresh_xref(spec)
        except FileNotFoundError as exc:
            return err_payload(str(exc), "NOT_FOUND")
        except RuntimeError as exc:
            return err_payload(str(exc), "PARSE_ERROR")

        return ok_payload({
            "status": status.to_dict(),
            "element_count": status.num_elements,
            "updated_spec": spec.to_dict(),
        })


# ---------------------------------------------------------------------------
# Tool: bim_compose_federated
# ---------------------------------------------------------------------------

if _HAVE_REGISTRY:
    _compose_spec = ToolSpec(
        name="bim_compose_federated",
        description=(
            "Build the complete federated model by refreshing all XRefs in the manifest "
            "and grouping loaded geometry by discipline. "
            "Returns {per_discipline_counts, total_elements, disciplines_loaded}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "manifest": {
                    "description": "XRefManifest JSON string or dict.",
                },
            },
            "required": ["manifest"],
        },
    )

    @register(_compose_spec, write=True)
    async def bim_compose_federated(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            manifest = _manifest_from_arg(a.get("manifest") or {})
        except Exception as exc:
            return err_payload(f"invalid manifest: {exc}", "BAD_ARGS")

        federated = compose_federated_model(manifest)

        per_discipline_counts: dict[str, int] = {}
        total = 0
        for discipline, bodies in federated.items():
            elem_count = sum(
                len(getattr(b, "elements", [])) for b in bodies
            )
            per_discipline_counts[discipline] = elem_count
            total += elem_count

        return ok_payload({
            "per_discipline_counts": per_discipline_counts,
            "total_elements": total,
            "disciplines_loaded": sorted(federated.keys()),
            "ref_count": len(manifest.refs),
        })


# ---------------------------------------------------------------------------
# Tool: bim_list_xrefs
# ---------------------------------------------------------------------------

if _HAVE_REGISTRY:
    _list_spec = ToolSpec(
        name="bim_list_xrefs",
        description=(
            "List all federated XRef entries in the manifest, including their discipline, "
            "path, and last-loaded hash. Cheap read-only operation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "manifest": {
                    "description": "XRefManifest JSON string or dict.",
                },
            },
            "required": ["manifest"],
        },
    )

    @register(_list_spec, write=False)
    async def bim_list_xrefs(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            manifest = _manifest_from_arg(a.get("manifest") or {})
        except Exception as exc:
            return err_payload(f"invalid manifest: {exc}", "BAD_ARGS")

        return ok_payload({
            "refs": [r.to_dict() for r in manifest.refs],
            "ref_count": len(manifest.refs),
        })


# ---------------------------------------------------------------------------
# TOOLS registration list (consumed by plugin.py)
# ---------------------------------------------------------------------------

if _HAVE_REGISTRY:
    TOOLS = [
        ("bim_add_xref",          _add_xref_spec,   bim_add_xref),
        ("bim_check_xref_status", _check_status_spec, bim_check_xref_status),
        ("bim_refresh_xref",      _refresh_spec,    bim_refresh_xref),
        ("bim_compose_federated", _compose_spec,    bim_compose_federated),
        ("bim_list_xrefs",        _list_spec,       bim_list_xrefs),
    ]
else:
    TOOLS = []
