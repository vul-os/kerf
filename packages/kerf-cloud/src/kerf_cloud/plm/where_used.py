"""
kerf_cloud.plm.where_used
=========================

Assembly-graph "where-used" inverse lookup.

Given a part_id, walks the assembly graph upward and returns every parent
assembly that references the part (directly or transitively), together with
the effectivity window that governs each usage.

Public API
----------
where_used(part_id, project_files)
    Returns a dict::

        {
            "part_id": "...",
            "usages": [
                {
                    "assembly_id": "...",
                    "assembly_name": "...",
                    "quantity": N,
                    "effectivity": {"valid_from": ..., "valid_until": ..., "config_id": ...},
                    "path": ["Top Asm", "Sub Asm", ...]   # breadcrumb from root
                },
                ...
            ]
        }

    project_files is the same list-of-dicts shape used by bom_150_percent.
"""
from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_components(content: str) -> list[dict]:
    if not content or not content.strip():
        return []
    try:
        doc = json.loads(content)
    except Exception:
        return []
    if doc.get("components"):
        return doc["components"]
    if doc.get("children"):
        return doc["children"]
    return []


def _build_parent_map(
    project_files: list[dict],
) -> dict[str, list[dict]]:
    """Map child_id → list of {asm_id, quantity, effectivity, config_id}."""
    parent_map: dict[str, list[dict]] = {}
    for f in project_files:
        if f["kind"] != "assembly":
            continue
        for comp in _parse_components(f["content"]):
            child_id = comp.get("file_id", "")
            if not child_id:
                continue
            qty = int(comp.get("quantity", 1)) or 1
            eff_raw = comp.get("effectivity") or {}
            window = eff_raw if isinstance(eff_raw, dict) else {}
            if "config_id" not in window and comp.get("config_id"):
                window = dict(window, config_id=comp["config_id"])
            entry = {
                "asm_id": f["id"],
                "asm_name": f["name"],
                "quantity": qty,
                "effectivity": {
                    "valid_from": window.get("valid_from"),
                    "valid_until": window.get("valid_until"),
                    "config_id": window.get("config_id"),
                },
            }
            parent_map.setdefault(child_id, []).append(entry)
    return parent_map


def _build_assembly_parents(
    parent_map: dict[str, list[dict]],
) -> dict[str, list[str]]:
    """Map asm_id → list of asm_ids that contain it (upward links)."""
    asm_parents: dict[str, list[str]] = {}
    for child_id, parents in parent_map.items():
        for p in parents:
            asm_parents.setdefault(child_id, []).extend(
                [q["asm_id"] for q in parents]
            )
    return asm_parents


def _path_to_root(
    asm_id: str,
    by_id: dict[str, dict],
    parent_map: dict[str, list[dict]],
    visited: frozenset[str] = frozenset(),
) -> list[list[str]]:
    """Return all root-to-asm name paths (list of name lists)."""
    if asm_id in visited:
        return [[by_id[asm_id]["name"]]] if asm_id in by_id else [[asm_id]]
    parents = parent_map.get(asm_id, [])
    if not parents:
        name = by_id[asm_id]["name"] if asm_id in by_id else asm_id
        return [[name]]
    paths = []
    for p in parents:
        for ancestor_path in _path_to_root(
            p["asm_id"], by_id, parent_map, visited | {asm_id}
        ):
            name = by_id[asm_id]["name"] if asm_id in by_id else asm_id
            paths.append(ancestor_path + [name])
    return paths


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def where_used(
    part_id: str,
    project_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return all assemblies that use the given part, with effectivity.

    Parameters
    ----------
    part_id:
        The file id of the part to look up.
    project_files:
        All project files as list of dicts (id, name, kind, content, ...).

    Returns
    -------
    dict with keys:
        part_id   — echoed back
        usages    — list of usage records
    """
    by_id: dict[str, dict] = {f["id"]: f for f in project_files}
    parent_map = _build_parent_map(project_files)

    # BFS / DFS upward from part_id, collecting direct + indirect assemblies
    usages: list[dict] = []
    seen_asm: set[tuple[str, str]] = set()  # (asm_id, child_id)

    def _collect(child_id: str, depth: int) -> None:
        if depth > 64:
            return
        direct_parents = parent_map.get(child_id, [])
        for entry in direct_parents:
            asm_id = entry["asm_id"]
            key = (asm_id, child_id)
            if key in seen_asm:
                continue
            seen_asm.add(key)
            # Build breadcrumb path
            all_paths = _path_to_root(asm_id, by_id, parent_map)
            path = all_paths[0] if all_paths else [asm_id]
            usages.append({
                "assembly_id": asm_id,
                "assembly_name": entry["asm_name"],
                "quantity": entry["quantity"],
                "effectivity": entry["effectivity"],
                "path": path,
            })
            # Walk further up
            _collect(asm_id, depth + 1)

    _collect(part_id, 0)

    # Deduplicate (may see same asm via multiple paths)
    deduped: list[dict] = []
    seen_ids: set[str] = set()
    for u in usages:
        if u["assembly_id"] not in seen_ids:
            seen_ids.add(u["assembly_id"])
            deduped.append(u)

    deduped.sort(key=lambda u: u["assembly_name"])

    return {
        "part_id": part_id,
        "usages": deduped,
    }
