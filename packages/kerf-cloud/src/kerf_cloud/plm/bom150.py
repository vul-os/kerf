"""
kerf_cloud.plm.bom150
=====================

150% BOM (Superset / Universal BOM).

A "150% BOM" is the full universe of *all* parts that have ever been used
in a project, with per-part effectivity windows attached.  The caller can
then slice to an "effective BOM" for a specific date.

Data model
----------
PartUsage
    part_id       — str  (file id or mpn-based key)
    name          — str
    quantity      — int  (max quantity seen; usually 1 for structural refs)
    effectivity   — list[EffectivityWindow]

EffectivityWindow
    valid_from    — str (ISO date) | None  (None = "from the beginning")
    valid_until   — str (ISO date) | None  (None = "still current")
    config_id     — str | None
    source_asm    — str  (assembly file_id where this usage was declared)

Assembly graph is the same parent→children structure used by the live BOM
endpoint (kerf_api.routes.get_bom).  Components live in assembly.content
as JSON: {"components": [{"file_id": "...", "quantity": N, ...}]}.

Effectivity windows are stored as an optional "effectivity" key in each
component entry::

    {"file_id": "part-uuid", "quantity": 2,
     "effectivity": {"valid_from": "2024-01-01", "valid_until": null}}

If no effectivity key is present the part is assumed always-effective.

Public API
----------
bom_150_percent(project_files, effectivity_date=None)
    Returns a dict::

        {
            "effectivity_date": <ISO date str or null>,
            "parts": [
                {
                    "part_id": "...",
                    "name": "...",
                    "quantity": N,
                    "effective": True/False,
                    "effectivity": [{"valid_from": ..., "valid_until": ..., ...}]
                },
                ...
            ]
        }

    project_files is a list of dicts with keys: id, name, kind, content,
    parent_id.  Same shape as the rows from kerf-api's BOM query.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_content(content: str) -> dict:
    if not content or not content.strip():
        return {}
    try:
        return json.loads(content)
    except Exception:
        return {}


def _parse_components(content: str) -> list[dict]:
    doc = _parse_content(content)
    if doc.get("components"):
        return doc["components"]
    if doc.get("children"):
        return doc["children"]
    return []


def _iso_to_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def _window_active_on(window: dict, target: date | None) -> bool:
    """Return True if the effectivity window covers *target* date.

    If target is None (caller did not restrict by date) any window is active.
    """
    if target is None:
        return True
    valid_from = _iso_to_date(window.get("valid_from"))
    valid_until = _iso_to_date(window.get("valid_until"))
    if valid_from is not None and target < valid_from:
        return False
    if valid_until is not None and target > valid_until:
        return False
    return True


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def bom_150_percent(
    project_files: list[dict[str, Any]],
    effectivity_date: str | None = None,
) -> dict[str, Any]:
    """Build the 150% (superset) BOM for a project.

    Parameters
    ----------
    project_files:
        All files in the project as list of dicts with id/name/kind/content.
    effectivity_date:
        ISO date string (YYYY-MM-DD) to filter effective parts, or None for
        the full superset.

    Returns
    -------
    dict with keys:
        effectivity_date  — echoed back (str or None)
        parts             — list of part-usage records
    """
    target_date: date | None = None
    if effectivity_date:
        target_date = _iso_to_date(effectivity_date)

    by_id: dict[str, dict] = {f["id"]: f for f in project_files}

    # part_id -> {"name": ..., "quantity": int, "windows": list, "source_asms": set}
    universe: dict[str, dict] = {}

    def _record(part_file: dict, quantity: int, window: dict, asm_id: str) -> None:
        pid = part_file["id"]
        if pid not in universe:
            universe[pid] = {
                "part_id": pid,
                "name": part_file["name"],
                "quantity": 0,
                "windows": [],
                "_asm_ids": set(),
            }
        rec = universe[pid]
        rec["quantity"] = max(rec["quantity"], quantity)
        # Deduplicate effectivity windows by content
        w_key = (
            window.get("valid_from"),
            window.get("valid_until"),
            window.get("config_id"),
            asm_id,
        )
        existing_keys = [
            (
                w.get("valid_from"),
                w.get("valid_until"),
                w.get("config_id"),
                w.get("source_asm"),
            )
            for w in rec["windows"]
        ]
        if w_key not in existing_keys:
            rec["windows"].append({
                "valid_from": window.get("valid_from"),
                "valid_until": window.get("valid_until"),
                "config_id": window.get("config_id"),
                "source_asm": asm_id,
            })

    def _walk(fid: str, multiplier: int, visited: set[str]) -> None:
        f = by_id.get(fid)
        if f is None:
            return
        if f["kind"] == "part":
            _record(f, multiplier, {}, fid)
            return
        if f["kind"] != "assembly":
            return
        if fid in visited:
            return
        visited.add(fid)
        for comp in _parse_components(f["content"]):
            child_id = comp.get("file_id", "")
            if not child_id:
                continue
            qty = int(comp.get("quantity", 1)) or 1
            eff_raw = comp.get("effectivity") or {}
            window = eff_raw if isinstance(eff_raw, dict) else {}
            if "config_id" not in window and comp.get("config_id"):
                window = dict(window, config_id=comp["config_id"])
            child = by_id.get(child_id)
            if child and child["kind"] == "part":
                _record(child, multiplier * qty, window, fid)
            else:
                _walk(child_id, multiplier * qty, visited)

    # Walk from every top-level assembly
    assembly_ids = {
        f["id"]
        for f in project_files
        if f["kind"] == "assembly"
    }
    # Also walk from assemblies that have no parent assembly containing them
    referenced_ids: set[str] = set()
    for f in project_files:
        if f["kind"] == "assembly":
            for comp in _parse_components(f["content"]):
                cid = comp.get("file_id", "")
                if cid:
                    referenced_ids.add(cid)
    top_level = assembly_ids - referenced_ids
    if not top_level:
        top_level = assembly_ids  # fallback: walk all assemblies

    for asm_id in top_level:
        _walk(asm_id, 1, set())

    # Build result
    parts_out = []
    for rec in universe.values():
        windows = rec["windows"]
        if not windows:
            windows = [{"valid_from": None, "valid_until": None, "config_id": None, "source_asm": None}]
        effective = any(_window_active_on(w, target_date) for w in windows)
        parts_out.append({
            "part_id": rec["part_id"],
            "name": rec["name"],
            "quantity": rec["quantity"],
            "effective": effective,
            "effectivity": windows,
        })

    # Stable output order
    parts_out.sort(key=lambda p: p["name"])

    return {
        "effectivity_date": effectivity_date,
        "parts": parts_out,
    }
