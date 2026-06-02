"""
phase_filter.py — LLM tools for renovation phase management.

Tools
-----
bim_apply_phase_filter  — apply a named or custom phase filter to element list
bim_set_element_phase   — tag a single element with its renovation phase
bim_compute_phase_stats — count elements per phase tag
bim_get_phase_filters   — return the default ArchiCAD-style filter presets
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:  # pragma: no cover — offline / test environment
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# bim_apply_phase_filter
# ---------------------------------------------------------------------------

_apply_filter_spec = ToolSpec(
    name="bim_apply_phase_filter",
    description=(
        "Apply a renovation phase filter to a list of BIM elements and return "
        "visible, hidden, and demolished-ghost element IDs.\n"
        "\n"
        "Pass filter_name to use a built-in preset ('Existing Plan', "
        "'Demolition Plan', 'New Construction Plan', 'Composite (All Phases)'), "
        "or set visible_phases (array of phase tag strings) together with "
        "demolished_visible / future_visible for a custom filter.\n"
        "\n"
        "element_phases is a list of objects with fields:\n"
        "  element_id      {string}\n"
        "  primary_phase   {string}  — one of the PhaseTag values\n"
        "  demolish_phase  {string|null}\n"
        "  notes           {string}\n"
        "\n"
        "Phase tags: existing | new_construction | demolish | future | "
        "alternate_a | alternate_b"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "element_phases": {
                "type": "array",
                "description": "List of element phase records.",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_id":     {"type": "string"},
                        "primary_phase":  {"type": "string"},
                        "demolish_phase": {"type": ["string", "null"]},
                        "notes":          {"type": "string"},
                    },
                    "required": ["element_id", "primary_phase"],
                },
            },
            "filter_name": {
                "type": "string",
                "description": (
                    "Built-in preset name. One of: 'Existing Plan', "
                    "'Demolition Plan', 'New Construction Plan', "
                    "'Composite (All Phases)'."
                ),
            },
            "visible_phases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Custom filter: list of phase tag strings to show.",
            },
            "demolished_visible": {
                "type": "boolean",
                "description": "Custom filter: show demolished elements as ghosts.",
                "default": False,
            },
            "future_visible": {
                "type": "boolean",
                "description": "Custom filter: show future elements.",
                "default": False,
            },
        },
        "required": ["element_phases"],
    },
)


async def run_bim_apply_phase_filter(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.phase_filter import (
            ElementPhase, PhaseFilter, PhaseTag,
            apply_phase_filter, get_default_filters,
        )

        raw_eps = params.get("element_phases", [])

        # Parse element phases
        element_phases = []
        for raw in raw_eps:
            eid = str(raw.get("element_id", ""))
            if not eid:
                return err_payload("element_id is required for each element", "BAD_ARGS")
            try:
                primary = PhaseTag(raw["primary_phase"])
            except (KeyError, ValueError):
                return err_payload(
                    f"unknown primary_phase '{raw.get('primary_phase')}' for element '{eid}'",
                    "BAD_ARGS",
                )
            dp_raw = raw.get("demolish_phase")
            demolish_phase = None
            if dp_raw:
                try:
                    demolish_phase = PhaseTag(dp_raw)
                except ValueError:
                    return err_payload(
                        f"unknown demolish_phase '{dp_raw}' for element '{eid}'",
                        "BAD_ARGS",
                    )
            element_phases.append(ElementPhase(
                element_id=eid,
                primary_phase=primary,
                demolish_phase=demolish_phase,
                notes=str(raw.get("notes", "")),
            ))

        # Resolve filter
        filter_name = params.get("filter_name")
        if filter_name:
            defaults = {f.name: f for f in get_default_filters()}
            if filter_name not in defaults:
                return err_payload(
                    f"unknown filter_name '{filter_name}'. "
                    f"Available: {list(defaults.keys())}",
                    "BAD_ARGS",
                )
            phase_filter = defaults[filter_name]
        else:
            raw_vp = params.get("visible_phases", [])
            try:
                visible_phases = [PhaseTag(p) for p in raw_vp]
            except ValueError as e:
                return err_payload(f"invalid phase in visible_phases: {e}", "BAD_ARGS")
            phase_filter = PhaseFilter(
                name="custom",
                visible_phases=visible_phases,
                demolished_visible=bool(params.get("demolished_visible", False)),
                future_visible=bool(params.get("future_visible", False)),
            )

        result = apply_phase_filter(element_phases, phase_filter)

        return ok_payload({
            "ok": True,
            "filter_name": phase_filter.name,
            "total_elements": len(element_phases),
            "visible_count": len(result.visible_element_ids),
            "hidden_count": len(result.hidden_element_ids),
            "demolished_ghost_count": len(result.demolished_ghost_ids),
            "visible_element_ids": result.visible_element_ids,
            "hidden_element_ids": result.hidden_element_ids,
            "demolished_ghost_ids": result.demolished_ghost_ids,
        })
    except Exception as exc:
        return err_payload(str(exc), "PHASE_FILTER_ERROR")


# ---------------------------------------------------------------------------
# bim_set_element_phase
# ---------------------------------------------------------------------------

_set_phase_spec = ToolSpec(
    name="bim_set_element_phase",
    description=(
        "Tag a BIM element with its renovation phase and optionally a demolition "
        "phase.  The element_phases list inside the provided manifest is updated "
        "in-place and the updated manifest is returned.\n"
        "\n"
        "Phase tags: existing | new_construction | demolish | future | "
        "alternate_a | alternate_b"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "element_id":     {"type": "string", "description": "Element to tag."},
            "phase":          {"type": "string", "description": "Primary phase tag."},
            "demolish_phase": {"type": "string", "description": "Optional demolition phase tag."},
            "notes":          {"type": "string", "description": "Free-text design note.", "default": ""},
            "manifest": {
                "type": "object",
                "description": (
                    "BIM manifest dict.  The 'element_phases' list within it "
                    "will be created or updated."
                ),
                "default": {},
            },
        },
        "required": ["element_id", "phase"],
    },
)


async def run_bim_set_element_phase(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.phase_filter import PhaseTag, set_element_phase

        element_id = str(params.get("element_id", ""))
        if not element_id:
            return err_payload("element_id is required", "BAD_ARGS")

        try:
            phase = PhaseTag(params["phase"])
        except (KeyError, ValueError):
            return err_payload(f"unknown phase '{params.get('phase')}'", "BAD_ARGS")

        dp_raw = params.get("demolish_phase")
        demolish_phase = None
        if dp_raw:
            try:
                demolish_phase = PhaseTag(dp_raw)
            except ValueError:
                return err_payload(f"unknown demolish_phase '{dp_raw}'", "BAD_ARGS")

        manifest = dict(params.get("manifest") or {})
        ep = set_element_phase(
            element_id=element_id,
            phase=phase,
            manifest=manifest,
            demolish_phase=demolish_phase,
            notes=str(params.get("notes", "")),
        )

        return ok_payload({
            "ok": True,
            "element_id": ep.element_id,
            "primary_phase": ep.primary_phase.value,
            "demolish_phase": ep.demolish_phase.value if ep.demolish_phase else None,
            "notes": ep.notes,
            "manifest_phase_count": len(manifest.get("element_phases", [])),
            "manifest": manifest,
        })
    except Exception as exc:
        return err_payload(str(exc), "SET_PHASE_ERROR")


# ---------------------------------------------------------------------------
# bim_compute_phase_stats
# ---------------------------------------------------------------------------

_compute_stats_spec = ToolSpec(
    name="bim_compute_phase_stats",
    description=(
        "Count BIM elements by primary phase tag.  Returns a dict mapping each "
        "phase label to the number of elements with that primary_phase.  All six "
        "phase tags are always present (zero-padded)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "element_phases": {
                "type": "array",
                "description": "List of element phase records (same format as bim_apply_phase_filter).",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_id":    {"type": "string"},
                        "primary_phase": {"type": "string"},
                    },
                    "required": ["element_id", "primary_phase"],
                },
            },
        },
        "required": ["element_phases"],
    },
)


async def run_bim_compute_phase_stats(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.phase_filter import ElementPhase, PhaseTag, compute_phase_statistics

        raw_eps = params.get("element_phases", [])
        element_phases = []
        for raw in raw_eps:
            try:
                primary = PhaseTag(raw["primary_phase"])
            except (KeyError, ValueError):
                return err_payload(
                    f"unknown primary_phase '{raw.get('primary_phase')}'",
                    "BAD_ARGS",
                )
            element_phases.append(ElementPhase(
                element_id=str(raw.get("element_id", "")),
                primary_phase=primary,
            ))

        counts = compute_phase_statistics(element_phases)
        return ok_payload({
            "ok": True,
            "total": len(element_phases),
            "counts": {tag.value: count for tag, count in counts.items()},
        })
    except Exception as exc:
        return err_payload(str(exc), "STATS_ERROR")


# ---------------------------------------------------------------------------
# bim_get_phase_filters
# ---------------------------------------------------------------------------

_get_filters_spec = ToolSpec(
    name="bim_get_phase_filters",
    description=(
        "Return the four ArchiCAD-style default renovation phase filters: "
        "'Existing Plan', 'Demolition Plan', 'New Construction Plan', and "
        "'Composite (All Phases)'.  Use these as a starting point for custom "
        "filter configuration."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
)


async def run_bim_get_phase_filters(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.phase_filter import get_default_filters

        filters = get_default_filters()
        return ok_payload({
            "ok": True,
            "filters": [
                {
                    "name": f.name,
                    "visible_phases": [p.value for p in f.visible_phases],
                    "demolished_visible": f.demolished_visible,
                    "future_visible": f.future_visible,
                }
                for f in filters
            ],
        })
    except Exception as exc:
        return err_payload(str(exc), "GET_FILTERS_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_apply_phase_filter",  _apply_filter_spec,  run_bim_apply_phase_filter),
    ("bim_set_element_phase",   _set_phase_spec,      run_bim_set_element_phase),
    ("bim_compute_phase_stats", _compute_stats_spec,  run_bim_compute_phase_stats),
    ("bim_get_phase_filters",   _get_filters_spec,    run_bim_get_phase_filters),
]
