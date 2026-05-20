"""
LLM tool: lca_report

Walks the project BOM (assembly + part files), resolves mass + material per
part, and returns an embodied-carbon report using ICE v3 reference factors.

The tool accepts an optional list of parts override so it can also be called
with an explicit BOM (useful for scripting / testing without a live DB).

Input schema
------------
project_id   — (string, optional) Kerf project UUID.  When omitted the tool
               uses ctx.project_id.
parts        — (array, optional) explicit BOM override. Each item:
                 { "name": str, "material": str, "mass_kg": float, "quantity": int }
               If omitted the tool reads the project files from the DB.

Output
------
JSON with: total_carbon_kg_co2, circularity_score, by_material, parts, warnings.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_lca._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_lca.report import lca_report as _lca_report

lca_report_spec = ToolSpec(
    name="lca_report",
    description=(
        "Generate a Life Cycle Assessment (LCA) / embodied-carbon report for the "
        "current project. Walks the Bill of Materials (BOM), multiplies each part's "
        "mass by its ICE v3 embodied-carbon factor, and returns: "
        "(1) total embodied carbon in kg CO₂-eq, "
        "(2) per-material breakdown, "
        "(3) circularity score (0–100, based on recycled content and end-of-life "
        "recyclability). "
        "Optionally supply an explicit 'parts' list to override the project BOM."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Project UUID (defaults to current project).",
            },
            "parts": {
                "type": "array",
                "description": (
                    "Explicit BOM override. Each item: "
                    "{ name, material, mass_kg, quantity }. "
                    "When omitted the project's BOM is read from the database."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "material": {"type": "string"},
                        "mass_kg": {"type": "number"},
                        "quantity": {"type": "integer"},
                    },
                    "required": ["name"],
                },
            },
        },
    },
)


def _parse_part_content(content: str) -> dict:
    if not content or not content.strip():
        return {}
    try:
        return json.loads(content)
    except Exception:
        return {}


def _parse_assembly_components(content: str) -> list:
    if not content or not content.strip():
        return []
    try:
        d = json.loads(content)
    except Exception:
        return []
    return d.get("components") or d.get("children") or []


async def _bom_from_db(ctx: ProjectCtx) -> list[dict]:
    """
    Read project files from the DB and build a flat BOM list.

    Each returned dict has: name, material, mass_kg (may be None), quantity.
    """
    if ctx.pool is None:
        return []

    rows = await ctx.pool.fetch(
        "SELECT id, parent_id, name, kind, content "
        "FROM files "
        "WHERE project_id = $1 AND deleted_at IS NULL "
        "AND kind IN ('assembly', 'part', 'folder')",
        ctx.project_id,
    )

    by_id: dict[Any, dict] = {}
    for row in rows:
        by_id[row["id"]] = {
            "id": row["id"],
            "parent_id": row["parent_id"],
            "name": row["name"],
            "kind": row["kind"],
            "content": row["content"] or "",
        }

    aggregates: dict[str, dict] = {}  # file_id_str -> {count, file}

    import uuid as _uuid

    def _add_part(file_dict: dict, qty: int):
        fid = str(file_dict["id"])
        if fid not in aggregates:
            aggregates[fid] = {"count": 0, "file": file_dict}
        aggregates[fid]["count"] += qty

    def _walk(fid: Any, multiplier: int, visited: set):
        f = by_id.get(fid)
        if f is None:
            return
        if f["kind"] == "part":
            _add_part(f, multiplier)
            return
        if f["kind"] != "assembly":
            return
        if fid in visited:
            return
        visited.add(fid)
        for comp in _parse_assembly_components(f["content"]):
            cid_str = comp.get("file_id", "")
            if not cid_str:
                continue
            try:
                cid = _uuid.UUID(cid_str)
            except Exception:
                continue
            q = max(int(comp.get("quantity") or 1), 1)
            _walk(cid, multiplier * q, visited)

    for f in by_id.values():
        if f["kind"] == "assembly":
            _walk(f["id"], 1, set())

    bom: list[dict] = []
    for fid_str, agg in aggregates.items():
        f = agg["file"]
        doc = _parse_part_content(f["content"])
        material = (
            doc.get("material")
            or doc.get("material_path")
            or doc.get("material_name")
            or ""
        )
        mass_kg = doc.get("mass_kg") or doc.get("mass")
        bom.append({
            "name": f["name"],
            "material": material,
            "mass_kg": float(mass_kg) if mass_kg else None,
            "quantity": agg["count"],
        })
    return bom


@register(lca_report_spec)
async def run_lca_report(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    # explicit parts override
    parts_override: list[dict] | None = a.get("parts")

    if parts_override is not None:
        if not isinstance(parts_override, list):
            return err_payload("'parts' must be an array", "BAD_ARGS")
        parts = parts_override
    else:
        # read from DB
        try:
            parts = await _bom_from_db(ctx)
        except Exception as e:
            return err_payload(f"failed to read BOM from database: {e}", "DB_ERROR")
        if not parts:
            return err_payload(
                "No parts found in project BOM. "
                "Supply an explicit 'parts' list or add assembly/part files to the project.",
                "EMPTY_BOM",
            )

    result = _lca_report(parts)
    return ok_payload(result.to_dict())
