"""LLM tool: step_import_brep — import a STEP file into a Kerf project with
optional auto-heal.

Registered tool name: ``step_import_brep``

This tool wraps :func:`~kerf_cad_core.io.step_reader.read_step` and
exposes the ``auto_heal`` pipeline to the chat agent.  It reads a STEP
file stored as a project file (text/STEP kind), parses it into B-rep
bodies, optionally runs the heal pass, and returns a structured result
with body statistics and per-body heal stats.

Auto-heal pipeline (when ``auto_heal=true``):
  1. Vertex welding — merge near-duplicate vertices within ``heal_tol``.
  2. Short-edge removal — drop edges shorter than ``heal_tol``.
  3. Sliver-gap closure — snap coedge endpoint gaps within 10 × ``heal_tol``.

See :class:`~kerf_cad_core.io.step_reader.StepReadResult` and
:class:`~kerf_cad_core.io.step_reader.HealStats` for the full result schema.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

logger = logging.getLogger(__name__)

__all__ = ["run_step_import_brep"]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _read_step_text(ctx: ProjectCtx, file_id: uuid.UUID) -> tuple[Optional[str], Optional[str]]:
    """Read raw STEP text from project files table."""
    row = ctx.pool.fetchone(
        "select content, kind from files "
        "where id = $1 and project_id = $2 and deleted_at is null",
        file_id, ctx.project_id,
    )
    if not row:
        return None, "file not found"
    content, kind = row
    if kind not in ("step", "text"):
        return None, f"file is kind={kind!r}; expected 'step' or 'text'"
    if isinstance(content, (bytes, bytearray)):
        content = content.decode("utf-8", errors="replace")
    return str(content), None


def _parse_file_id(a: dict) -> tuple[Optional[uuid.UUID], Optional[str]]:
    raw = a.get("file_id", "").strip()
    if not raw:
        return None, "file_id is required"
    try:
        return uuid.UUID(raw), None
    except Exception:
        return None, "file_id must be a valid UUID"


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

step_import_spec = ToolSpec(
    name="step_import_brep",
    description=(
        "Import a STEP Part 21 (AP203/AP214) file stored in the project into "
        "Kerf B-rep bodies.  Optionally runs the industrial B-rep heal pipeline "
        "(vertex weld, short-edge removal, sliver-gap snap) on each imported "
        "body.  Returns body counts, face/edge/vertex topology, and per-body "
        "heal statistics so the agent can report what was repaired.\n\n"
        "Parameters\n"
        "----------\n"
        "file_id   : UUID of a project file with kind='step' or kind='text'.\n"
        "auto_heal : Run B-rep heal after import (default true).\n"
        "heal_tol  : Merge/snap tolerance in model units (default 1e-6).\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the STEP file to import.",
            },
            "auto_heal": {
                "type": "boolean",
                "description": (
                    "Run B-rep heal pipeline after import.  "
                    "Default: true.  Set to false to skip healing."
                ),
            },
            "heal_tol": {
                "type": "number",
                "description": (
                    "Heal tolerance in model units (mm).  "
                    "Vertices within this distance are merged.  Default: 1e-6."
                ),
            },
        },
        "required": ["file_id"],
    },
)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

@register(step_import_spec, write=False)
async def run_step_import_brep(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool handler: parse STEP, optionally heal, return stats."""
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    fid, err = _parse_file_id(a)
    if err:
        return err_payload(err, "BAD_ARGS")

    auto_heal: bool = bool(a.get("auto_heal", True))
    heal_tol: float = float(a.get("heal_tol", 1e-6))
    if heal_tol <= 0:
        return err_payload("heal_tol must be positive", "BAD_ARGS")

    step_text, err = _read_step_text(ctx, fid)
    if err:
        return err_payload(err, "NOT_FOUND")

    # Import
    try:
        from kerf_cad_core.io.step_reader import read_step, StepReadResult
        result = read_step(
            step_text,
            validate=False,       # caller controls; heal may fix validation issues
            auto_heal=auto_heal,
            heal_options={"tol": heal_tol},
        )
    except Exception as exc:
        return err_payload(f"STEP parse failed: {exc}", "PARSE_ERROR")

    # Normalise to StepReadResult regardless of auto_heal
    if isinstance(result, StepReadResult):
        sr = result
    else:
        # auto_heal=False returns a plain Body — wrap for uniform output
        from kerf_cad_core.io.step_reader import StepReadResult, HealStats
        sr = StepReadResult(bodies=[result], heal_stats={}, heal_warnings=[])

    # Build response payload
    body_summaries = []
    for idx, body in enumerate(sr.bodies):
        hs = sr.heal_stats.get(idx)
        body_summaries.append({
            "body_index": idx,
            "face_count": len(body.all_faces()),
            "edge_count": len(body.all_edges()),
            "vertex_count": len(body.all_vertices()),
            "heal_stats": {
                "vertices_merged": hs.vertices_merged if hs else None,
                "edges_stitched": hs.edges_stitched if hs else None,
                "faces_orientation_fixed": hs.faces_orientation_fixed if hs else None,
            } if auto_heal else None,
            "heal_warning": idx in sr.heal_warnings,
        })

    return ok_payload({
        "file_id": str(fid),
        "auto_heal": auto_heal,
        "heal_tol": heal_tol,
        "body_count": len(sr.bodies),
        "heal_warnings": sr.heal_warnings,
        "bodies": body_summaries,
    })
