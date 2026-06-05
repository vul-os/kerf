"""
construction_sequencing.py — LLM tools for 4D construction sequencing (Revit parity).

Registered tools
----------------
bim_4d_build_timeline    — link schedule tasks to elements, compute time-phased states
bim_4d_critical_path     — identify tasks on the critical path (CPM)
bim_4d_validate_schedule — consistency-check a ConstructionSchedule
bim_4d_summarise_date    — quick element-state summary at a given date

References
----------
IFC4 ADD2 TC1 — IfcTask, IfcRelAssignsToProcess, IfcWorkSchedule.
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_task(raw: dict) -> "Task":
    from kerf_bim.construction_sequencing import Task
    return Task(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        start=str(raw.get("start", "")),
        finish=str(raw.get("finish", "")),
        element_ids=list(raw.get("element_ids", [])),
        predecessors=list(raw.get("predecessors", [])),
        ifc_task_type=str(raw.get("ifc_task_type", "CONSTRUCTION")),
        trade=str(raw.get("trade", "")),
    )


def _parse_schedule(raw: dict) -> "ConstructionSchedule":
    from kerf_bim.construction_sequencing import ConstructionSchedule
    tasks = [_parse_task(t) for t in raw.get("tasks", [])]
    return ConstructionSchedule(
        tasks=tasks,
        project_start=str(raw.get("project_start", "")),
        project_finish=str(raw.get("project_finish", "")),
        name=str(raw.get("name", "Schedule")),
    )


# ---------------------------------------------------------------------------
# bim_4d_build_timeline
# ---------------------------------------------------------------------------

_build_timeline_spec = ToolSpec(
    name="bim_4d_build_timeline",
    description=(
        "4D Construction Sequencing: link a task schedule to BIM elements and "
        "compute the element-appearance timeline at a given date.\n"
        "\n"
        "Each task has: id, name, start (YYYY-MM-DD), finish (YYYY-MM-DD), "
        "element_ids (list), predecessors (list), ifc_task_type "
        "(CONSTRUCTION|DEMOLITION|INSTALLATION|…), trade.\n"
        "\n"
        "Returns per-element states: not_started | active | complete, "
        "with linear progress_pct and a summary count.\n"
        "\n"
        "IFC alignment: tasks ≈ IfcTask; element_ids ≈ IfcRelAssignsToProcess."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "schedule": {
                "type": "object",
                "description": "ConstructionSchedule dict: {tasks, project_start?, project_finish?, name?}",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":           {"type": "string"},
                                "name":         {"type": "string"},
                                "start":        {"type": "string"},
                                "finish":       {"type": "string"},
                                "element_ids":  {"type": "array", "items": {"type": "string"}},
                                "predecessors": {"type": "array", "items": {"type": "string"}},
                                "ifc_task_type":{"type": "string"},
                                "trade":        {"type": "string"},
                            },
                            "required": ["id", "name", "start", "finish"],
                        },
                    },
                    "project_start":  {"type": "string"},
                    "project_finish": {"type": "string"},
                    "name":           {"type": "string"},
                },
                "required": ["tasks"],
            },
            "date": {
                "type": "string",
                "description": "ISO 8601 date to query (YYYY-MM-DD).",
            },
        },
        "required": ["schedule", "date"],
    },
)


async def run_bim_4d_build_timeline(params: dict, ctx) -> str:
    try:
        from kerf_bim.construction_sequencing import build_timeline, summarise_timeline

        raw_schedule = params.get("schedule", {})
        query_date = str(params.get("date", ""))
        if not query_date:
            return err_payload("date is required", "BAD_ARGS")

        try:
            schedule = _parse_schedule(raw_schedule)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        entries = build_timeline(schedule, query_date)
        summary = summarise_timeline(entries)

        return ok_payload({
            "ok": True,
            "date": query_date,
            "schedule_name": schedule.name,
            "task_count": len(schedule.tasks),
            "entry_count": len(entries),
            "summary": summary,
            "timeline": [
                {
                    "element_id":    e.element_id,
                    "task_id":       e.task_id,
                    "task_name":     e.task_name,
                    "state":         e.state,
                    "start":         e.start,
                    "finish":        e.finish,
                    "progress_pct":  e.progress_pct,
                    "ifc_task_type": e.ifc_task_type,
                    "trade":         e.trade,
                }
                for e in entries
            ],
        })
    except Exception as exc:
        return err_payload(str(exc), "4D_TIMELINE_ERROR")


# ---------------------------------------------------------------------------
# bim_4d_critical_path
# ---------------------------------------------------------------------------

_critical_path_spec = ToolSpec(
    name="bim_4d_critical_path",
    description=(
        "Compute the critical path (CPM, Finish-to-Start) of a construction "
        "schedule. Returns IDs of tasks with zero total float. Predecessor "
        "links are Finish-to-Start. Linear day-duration model."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "schedule": {
                "type": "object",
                "description": "ConstructionSchedule dict (same format as bim_4d_build_timeline).",
            },
        },
        "required": ["schedule"],
    },
)


async def run_bim_4d_critical_path(params: dict, ctx) -> str:
    try:
        from kerf_bim.construction_sequencing import critical_path

        try:
            schedule = _parse_schedule(params.get("schedule", {}))
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        cp = critical_path(schedule)
        return ok_payload({
            "ok": True,
            "critical_task_ids": cp,
            "critical_count": len(cp),
            "total_tasks": len(schedule.tasks),
        })
    except Exception as exc:
        return err_payload(str(exc), "CPM_ERROR")


# ---------------------------------------------------------------------------
# bim_4d_validate_schedule
# ---------------------------------------------------------------------------

_validate_schedule_spec = ToolSpec(
    name="bim_4d_validate_schedule",
    description=(
        "Validate a 4D construction schedule: check date ordering, predecessor "
        "references, circular dependencies, and project date range. "
        "Returns a (possibly empty) list of error/warning strings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "schedule": {
                "type": "object",
                "description": "ConstructionSchedule dict.",
            },
        },
        "required": ["schedule"],
    },
)


async def run_bim_4d_validate_schedule(params: dict, ctx) -> str:
    try:
        from kerf_bim.construction_sequencing import validate_schedule

        try:
            schedule = _parse_schedule(params.get("schedule", {}))
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        errors = validate_schedule(schedule)
        return ok_payload({
            "ok": True,
            "valid": len(errors) == 0,
            "errors": errors,
            "task_count": len(schedule.tasks),
        })
    except Exception as exc:
        return err_payload(str(exc), "VALIDATE_SCHEDULE_ERROR")


# ---------------------------------------------------------------------------
# bim_4d_summarise_date
# ---------------------------------------------------------------------------

_summarise_date_spec = ToolSpec(
    name="bim_4d_summarise_date",
    description=(
        "Return element state counts (not_started / active / complete) at a "
        "given date without returning the full per-element timeline. Useful "
        "for building a progress bar or date-slider animation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "schedule": {"type": "object"},
            "date":     {"type": "string", "description": "ISO 8601 query date."},
        },
        "required": ["schedule", "date"],
    },
)


async def run_bim_4d_summarise_date(params: dict, ctx) -> str:
    try:
        from kerf_bim.construction_sequencing import build_timeline, summarise_timeline

        try:
            schedule = _parse_schedule(params.get("schedule", {}))
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        query_date = str(params.get("date", ""))
        if not query_date:
            return err_payload("date is required", "BAD_ARGS")

        entries = build_timeline(schedule, query_date)
        summary = summarise_timeline(entries)
        return ok_payload({"ok": True, "date": query_date, **summary})
    except Exception as exc:
        return err_payload(str(exc), "SUMMARISE_DATE_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_4d_build_timeline",    _build_timeline_spec,    run_bim_4d_build_timeline),
    ("bim_4d_critical_path",     _critical_path_spec,     run_bim_4d_critical_path),
    ("bim_4d_validate_schedule", _validate_schedule_spec, run_bim_4d_validate_schedule),
    ("bim_4d_summarise_date",    _summarise_date_spec,    run_bim_4d_summarise_date),
]
