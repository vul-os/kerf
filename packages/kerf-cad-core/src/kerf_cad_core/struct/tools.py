"""
kerf_cad_core.struct.tools — LLM tool wrappers for structural grid + framing.

Registers five tools with the Kerf tool registry:

  struct_grid              — define a structural grid (X bay spacings + Y bay spacings)
  struct_level             — define a floor/storey level (name + elevation)
  struct_column            — place a column at a grid intersection spanning two levels
  struct_beam              — add a beam between two grid intersections at a level
  struct_framing_summary   — BOM-style summary: member count + total steel tonnage by section

All tools are pure-Python; no OCC dependency.  Session state (grid, levels,
columns, beams) is passed in and out as plain dicts — no DB writes for these
tools.  The caller accumulates state across calls.

Validation contract: invalid inputs return {ok: false, errors: [...]}; never raise.

Units: mm (lengths, elevations), kg (mass), t (tonnes in summary).
"""
from __future__ import annotations

import json
import math
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.struct.grid import StructGrid, Level
from kerf_cad_core.struct.framing import (
    Column,
    Beam,
    SECTION_CATALOG,
    get_section,
)


# ---------------------------------------------------------------------------
# Internal helpers (importable by tests)
# ---------------------------------------------------------------------------

def _build_grid(spacing_x: list, spacing_y: list, name: str = "") -> tuple[bool, Any, list[str]]:
    """Build a StructGrid; return (ok, grid_or_none, errors)."""
    errors: list[str] = []
    try:
        sx = [float(v) for v in spacing_x]
    except (TypeError, ValueError) as exc:
        errors.append(f"spacing_x must be a list of numbers: {exc}")
        return False, None, errors
    try:
        sy = [float(v) for v in spacing_y]
    except (TypeError, ValueError) as exc:
        errors.append(f"spacing_y must be a list of numbers: {exc}")
        return False, None, errors
    try:
        grid = StructGrid(spacing_x=sx, spacing_y=sy, name=str(name))
    except ValueError as exc:
        errors.append(str(exc))
        return False, None, errors
    return True, grid, []


def _build_level(name: str, elevation_mm: float) -> tuple[bool, Any, list[str]]:
    """Build a Level; return (ok, level_or_none, errors)."""
    errors: list[str] = []
    if not name or not str(name).strip():
        errors.append("level name must be a non-empty string")
        return False, None, errors
    try:
        elev = float(elevation_mm)
    except (TypeError, ValueError) as exc:
        errors.append(f"elevation_mm must be a number: {exc}")
        return False, None, errors
    try:
        lev = Level(name=str(name).strip(), elevation_mm=elev)
    except ValueError as exc:
        errors.append(str(exc))
        return False, None, errors
    return True, lev, []


def _resolve_column(
    member_id: str,
    grid_dict: dict,
    levels_dict: dict,
    grid_label: str,
    section_name: str,
    base_level_name: str,
    top_level_name: str,
) -> tuple[bool, Any, list[str]]:
    """Validate inputs and build a Column dataclass. Returns (ok, col, errors)."""
    errors: list[str] = []

    # Reconstruct StructGrid
    ok, grid, gerrs = _build_grid(
        grid_dict.get("spacing_x", []),
        grid_dict.get("spacing_y", []),
        grid_dict.get("name", ""),
    )
    if not ok:
        errors.extend(gerrs)
        return False, None, errors

    # Resolve grid label
    ok2, pt, grr = grid.resolve(grid_label)
    if not ok2:
        errors.append(grr or f"Could not resolve grid label '{grid_label}'")
        return False, None, errors

    # Resolve section
    sec = get_section(section_name)
    if sec is None:
        valid = sorted(SECTION_CATALOG.keys())
        errors.append(
            f"Unknown section '{section_name}'. "
            f"Valid sections: {valid}"
        )
        return False, None, errors

    # Resolve levels
    base_data = levels_dict.get(base_level_name)
    if base_data is None:
        errors.append(f"Base level '{base_level_name}' not found in levels dict")
        return False, None, errors
    top_data = levels_dict.get(top_level_name)
    if top_data is None:
        errors.append(f"Top level '{top_level_name}' not found in levels dict")
        return False, None, errors

    ok_b, base_lev, berrs = _build_level(
        base_data.get("name", base_level_name),
        base_data.get("elevation_mm", 0),
    )
    if not ok_b:
        errors.extend(berrs)
        return False, None, errors

    ok_t, top_lev, terrs = _build_level(
        top_data.get("name", top_level_name),
        top_data.get("elevation_mm", 0),
    )
    if not ok_t:
        errors.extend(terrs)
        return False, None, errors

    if base_lev.elevation_mm == top_lev.elevation_mm:
        errors.append(
            f"base_level '{base_level_name}' and top_level '{top_level_name}' "
            "have the same elevation — column would have zero length"
        )
        return False, None, errors

    col = Column(
        id=str(member_id),
        grid_label=pt.label,
        grid_point=pt,
        section=sec,
        base_level=base_lev,
        top_level=top_lev,
    )
    return True, col, []


def _resolve_beam(
    member_id: str,
    grid_dict: dict,
    levels_dict: dict,
    start_label: str,
    end_label: str,
    section_name: str,
    level_name: str,
) -> tuple[bool, Any, list[str]]:
    """Validate inputs and build a Beam dataclass. Returns (ok, beam, errors)."""
    errors: list[str] = []

    ok, grid, gerrs = _build_grid(
        grid_dict.get("spacing_x", []),
        grid_dict.get("spacing_y", []),
        grid_dict.get("name", ""),
    )
    if not ok:
        errors.extend(gerrs)
        return False, None, errors

    ok_s, pt_s, serr = grid.resolve(start_label)
    if not ok_s:
        errors.append(serr or f"Could not resolve start label '{start_label}'")
        return False, None, errors

    ok_e, pt_e, eerr = grid.resolve(end_label)
    if not ok_e:
        errors.append(eerr or f"Could not resolve end label '{end_label}'")
        return False, None, errors

    if pt_s.x_mm == pt_e.x_mm and pt_s.y_mm == pt_e.y_mm:
        errors.append(
            f"start and end grid labels resolve to the same point "
            f"({start_label} == {end_label}) — beam would have zero length"
        )
        return False, None, errors

    sec = get_section(section_name)
    if sec is None:
        valid = sorted(SECTION_CATALOG.keys())
        errors.append(
            f"Unknown section '{section_name}'. "
            f"Valid sections: {valid}"
        )
        return False, None, errors

    lev_data = levels_dict.get(level_name)
    if lev_data is None:
        errors.append(f"Level '{level_name}' not found in levels dict")
        return False, None, errors

    ok_l, lev, lerrs = _build_level(
        lev_data.get("name", level_name),
        lev_data.get("elevation_mm", 0),
    )
    if not ok_l:
        errors.extend(lerrs)
        return False, None, errors

    beam = Beam(
        id=str(member_id),
        start_label=pt_s.label,
        end_label=pt_e.label,
        start_point=pt_s,
        end_point=pt_e,
        section=sec,
        level=lev,
    )
    return True, beam, []


def framing_summary(members: list[dict]) -> dict:
    """
    Compute a BOM-style framing summary from a list of member dicts.

    Each member dict must have:
        type       — "column" or "beam"
        section    — section name (must be in SECTION_CATALOG)
        length_mm  — member length in mm
        mass_kg    — member mass in kg

    Returns
    -------
    dict with:
        total_members     — total count
        total_mass_kg     — grand total mass (kg)
        total_mass_t      — grand total mass (tonnes, 3 d.p.)
        by_section        — list of {section, family, count, total_length_mm, total_mass_kg}
        by_type           — {columns: {count, mass_kg}, beams: {count, mass_kg}}
        errors            — list of parse errors (non-fatal)
    """
    by_section: dict[str, dict] = {}
    total_mass_kg = 0.0
    col_count = 0
    col_mass = 0.0
    beam_count = 0
    beam_mass = 0.0
    parse_errors: list[str] = []

    for i, m in enumerate(members):
        if not isinstance(m, dict):
            parse_errors.append(f"members[{i}]: expected a dict")
            continue

        sec_name = m.get("section", "")
        try:
            length_mm = float(m.get("length_mm", 0))
            mass_kg = float(m.get("mass_kg", 0))
        except (TypeError, ValueError) as exc:
            parse_errors.append(f"members[{i}]: numeric field error: {exc}")
            continue

        mem_type = m.get("type", "unknown")
        sec = get_section(sec_name) if sec_name else None
        family = sec.family if sec else "UNKNOWN"

        if sec_name not in by_section:
            by_section[sec_name] = {
                "section": sec_name,
                "family": family,
                "count": 0,
                "total_length_mm": 0.0,
                "total_mass_kg": 0.0,
            }
        by_section[sec_name]["count"] += 1
        by_section[sec_name]["total_length_mm"] += length_mm
        by_section[sec_name]["total_mass_kg"] += mass_kg

        total_mass_kg += mass_kg

        if mem_type == "column":
            col_count += 1
            col_mass += mass_kg
        elif mem_type == "beam":
            beam_count += 1
            beam_mass += mass_kg

    # Round for display
    for row in by_section.values():
        row["total_length_mm"] = round(row["total_length_mm"], 3)
        row["total_mass_kg"] = round(row["total_mass_kg"], 4)

    return {
        "total_members": col_count + beam_count,
        "total_mass_kg": round(total_mass_kg, 4),
        "total_mass_t": round(total_mass_kg / 1000.0, 6),
        "by_section": sorted(by_section.values(), key=lambda r: r["section"]),
        "by_type": {
            "columns": {
                "count": col_count,
                "mass_kg": round(col_mass, 4),
            },
            "beams": {
                "count": beam_count,
                "mass_kg": round(beam_mass, 4),
            },
        },
        "errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Tool: struct_grid
# ---------------------------------------------------------------------------

_grid_spec = ToolSpec(
    name="struct_grid",
    description=(
        "Define a structural grid for a building layout. "
        "X-direction axes are labelled A, B, C, … (left to right); "
        "Y-direction axes are numbered 1, 2, 3, … (front to back). "
        "spacing_x is the list of bay widths between consecutive X-axes (mm). "
        "spacing_y is the list of bay depths between consecutive Y-axes (mm). "
        "Grid intersections are addressed as 'X/Y', e.g. 'B/3'. "
        "Returns the full grid dict (axis labels + cumulative coordinates) "
        "which is passed as `grid` to struct_column, struct_beam, etc. "
        "All spacings must be > 0. Maximum 26 X-axes (A–Z)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "spacing_x": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Bay widths in X direction (mm), left to right. "
                    "len(spacing_x) bays → len(spacing_x)+1 axes (A, B, C, …). "
                    "Example: [6000, 8000, 6000] → axes A, B, C, D."
                ),
            },
            "spacing_y": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Bay depths in Y direction (mm), front to back. "
                    "len(spacing_y) bays → len(spacing_y)+1 axes (1, 2, 3, …). "
                    "Example: [5000, 5000] → axes 1, 2, 3."
                ),
            },
            "name": {
                "type": "string",
                "description": "Optional name/identifier for this grid (e.g. 'GridA').",
            },
        },
        "required": ["spacing_x", "spacing_y"],
    },
)


@register(_grid_spec, write=False)
async def run_struct_grid(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    spacing_x = a.get("spacing_x")
    spacing_y = a.get("spacing_y")
    name = a.get("name", "")

    if spacing_x is None or not isinstance(spacing_x, list):
        return _err_result(["spacing_x must be a non-empty array"])
    if spacing_y is None or not isinstance(spacing_y, list):
        return _err_result(["spacing_y must be a non-empty array"])

    ok, grid, errors = _build_grid(spacing_x, spacing_y, name)
    if not ok:
        return _err_result(errors)

    return ok_payload({
        "ok": True,
        "grid": grid.to_dict(),
        "intersections": len(grid.x_axis_labels) * len(grid.y_axis_labels),
        "message": (
            f"Grid '{name or 'unnamed'}' defined: "
            f"{len(grid.x_axis_labels)} X-axes ({', '.join(grid.x_axis_labels)}) × "
            f"{len(grid.y_axis_labels)} Y-axes ({', '.join(grid.y_axis_labels)})."
        ),
    })


# ---------------------------------------------------------------------------
# Tool: struct_level
# ---------------------------------------------------------------------------

_level_spec = ToolSpec(
    name="struct_level",
    description=(
        "Define a floor/storey level at a given elevation above the project datum. "
        "Returns a level dict that is accumulated into a levels dict keyed by name. "
        "Elevations are in mm from Z=0 (project datum). "
        "Negative elevations are valid (basement levels). "
        "The levels dict is passed to struct_column and struct_beam."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Level name, e.g. 'Ground', 'L1', 'L2', 'Mezzanine', 'Roof'. "
                    "Must be unique within the project level set."
                ),
            },
            "elevation_mm": {
                "type": "number",
                "description": (
                    "Elevation of this level above the project datum (mm). "
                    "Use 0 for ground floor. Negative for basements."
                ),
            },
        },
        "required": ["name", "elevation_mm"],
    },
)


@register(_level_spec, write=False)
async def run_struct_level(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    name = a.get("name", "")
    elevation_mm = a.get("elevation_mm")

    if elevation_mm is None:
        return _err_result(["elevation_mm is required"])

    ok, lev, errors = _build_level(name, elevation_mm)
    if not ok:
        return _err_result(errors)

    return ok_payload({
        "ok": True,
        "level": lev.to_dict(),
        "message": f"Level '{lev.name}' defined at elevation {lev.elevation_mm:.0f} mm.",
    })


# ---------------------------------------------------------------------------
# Tool: struct_column
# ---------------------------------------------------------------------------

_column_spec = ToolSpec(
    name="struct_column",
    description=(
        "Place a structural column at a grid intersection, spanning from a base level "
        "to a top level. "
        "grid_label is the grid intersection address, e.g. 'B/3'. "
        "section is the steel section name from the built-in catalog "
        "(IPE160, IPE200, IPE270, IPE360, HEA200, HEA300, HEA400, "
        "UB203x133x25, UB356x171x51, W8x31, W12x50, W14x68). "
        "Pass the `grid` dict from struct_grid and the `levels` dict "
        "(keys = level names, values = level dicts from struct_level). "
        "Returns the column dict including length_mm and mass_kg."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Unique column identifier, e.g. 'C-B3-G-L1'.",
            },
            "grid_label": {
                "type": "string",
                "description": "Grid intersection in 'X/Y' format, e.g. 'B/3'.",
            },
            "section": {
                "type": "string",
                "description": (
                    "Steel section name from catalog: IPE160, IPE200, IPE270, IPE360, "
                    "HEA200, HEA300, HEA400, UB203x133x25, UB356x171x51, "
                    "W8x31, W12x50, W14x68."
                ),
            },
            "base_level": {
                "type": "string",
                "description": "Name of the base level (key in levels dict).",
            },
            "top_level": {
                "type": "string",
                "description": "Name of the top level (key in levels dict).",
            },
            "grid": {
                "type": "object",
                "description": "Grid dict from struct_grid output.",
            },
            "levels": {
                "type": "object",
                "description": (
                    "Dict of level dicts keyed by level name "
                    "(accumulated from struct_level outputs)."
                ),
            },
        },
        "required": ["id", "grid_label", "section", "base_level", "top_level", "grid", "levels"],
    },
)


@register(_column_spec, write=False)
async def run_struct_column(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    member_id = str(a.get("id", "")).strip()
    grid_label = str(a.get("grid_label", "")).strip()
    section_name = str(a.get("section", "")).strip()
    base_level_name = str(a.get("base_level", "")).strip()
    top_level_name = str(a.get("top_level", "")).strip()
    grid_dict = a.get("grid") or {}
    levels_dict = a.get("levels") or {}

    errors: list[str] = []
    if not member_id:
        errors.append("id is required")
    if not grid_label:
        errors.append("grid_label is required")
    if not section_name:
        errors.append("section is required")
    if not base_level_name:
        errors.append("base_level is required")
    if not top_level_name:
        errors.append("top_level is required")
    if not isinstance(grid_dict, dict) or not grid_dict:
        errors.append("grid must be the dict returned by struct_grid")
    if not isinstance(levels_dict, dict) or not levels_dict:
        errors.append("levels must be a dict of level dicts keyed by level name")
    if errors:
        return _err_result(errors)

    ok, col, col_errors = _resolve_column(
        member_id, grid_dict, levels_dict,
        grid_label, section_name, base_level_name, top_level_name,
    )
    if not ok:
        return _err_result(col_errors)

    return ok_payload({
        "ok": True,
        "column": col.to_dict(),
        "message": (
            f"Column '{col.id}' at {col.grid_label}: "
            f"{col.section.name}, "
            f"{col.base_level.name}→{col.top_level.name}, "
            f"L={col.length_mm:.0f} mm, "
            f"mass={col.mass_kg:.2f} kg."
        ),
    })


# ---------------------------------------------------------------------------
# Tool: struct_beam
# ---------------------------------------------------------------------------

_beam_spec = ToolSpec(
    name="struct_beam",
    description=(
        "Add a structural beam spanning between two grid intersections at a given level. "
        "start and end are grid labels, e.g. 'A/2' and 'C/2'. "
        "They must resolve to different points (zero-length beam is rejected). "
        "section is the steel section name from the built-in catalog. "
        "Pass the `grid` dict from struct_grid and the `levels` dict. "
        "Returns the beam dict including length_mm and mass_kg."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Unique beam identifier, e.g. 'B-A2-C2-L1'.",
            },
            "start": {
                "type": "string",
                "description": "Start grid intersection in 'X/Y' format, e.g. 'A/2'.",
            },
            "end": {
                "type": "string",
                "description": "End grid intersection in 'X/Y' format, e.g. 'C/2'.",
            },
            "section": {
                "type": "string",
                "description": "Steel section name from catalog.",
            },
            "level": {
                "type": "string",
                "description": "Name of the level at which the beam sits.",
            },
            "grid": {
                "type": "object",
                "description": "Grid dict from struct_grid output.",
            },
            "levels": {
                "type": "object",
                "description": "Dict of level dicts keyed by level name.",
            },
        },
        "required": ["id", "start", "end", "section", "level", "grid", "levels"],
    },
)


@register(_beam_spec, write=False)
async def run_struct_beam(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    member_id = str(a.get("id", "")).strip()
    start_label = str(a.get("start", "")).strip()
    end_label = str(a.get("end", "")).strip()
    section_name = str(a.get("section", "")).strip()
    level_name = str(a.get("level", "")).strip()
    grid_dict = a.get("grid") or {}
    levels_dict = a.get("levels") or {}

    errors: list[str] = []
    if not member_id:
        errors.append("id is required")
    if not start_label:
        errors.append("start is required")
    if not end_label:
        errors.append("end is required")
    if not section_name:
        errors.append("section is required")
    if not level_name:
        errors.append("level is required")
    if not isinstance(grid_dict, dict) or not grid_dict:
        errors.append("grid must be the dict returned by struct_grid")
    if not isinstance(levels_dict, dict) or not levels_dict:
        errors.append("levels must be a dict of level dicts keyed by level name")
    if errors:
        return _err_result(errors)

    ok, beam, beam_errors = _resolve_beam(
        member_id, grid_dict, levels_dict,
        start_label, end_label, section_name, level_name,
    )
    if not ok:
        return _err_result(beam_errors)

    return ok_payload({
        "ok": True,
        "beam": beam.to_dict(),
        "message": (
            f"Beam '{beam.id}' at level '{beam.level.name}': "
            f"{beam.start_label}→{beam.end_label}, "
            f"{beam.section.name}, "
            f"L={beam.length_mm:.0f} mm, "
            f"mass={beam.mass_kg:.2f} kg."
        ),
    })


# ---------------------------------------------------------------------------
# Tool: struct_framing_summary
# ---------------------------------------------------------------------------

_summary_spec = ToolSpec(
    name="struct_framing_summary",
    description=(
        "Compute a BOM-style framing summary from a list of column and beam dicts. "
        "Pass the members array (column dicts + beam dicts from struct_column / "
        "struct_beam outputs). "
        "Returns: total member count, grand total steel mass in kg and tonnes, "
        "breakdown by section (count + total length + total mass), "
        "and breakdown by member type (columns vs beams). "
        "Total mass = sum of (member length in m × section mass in kg/m) over all members. "
        "Use this for steel tonnage estimates and quantity take-offs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "members": {
                "type": "array",
                "description": (
                    "List of member dicts from struct_column / struct_beam outputs "
                    "(the 'column' or 'beam' dict from each tool's output)."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["members"],
    },
)


@register(_summary_spec, write=False)
async def run_struct_framing_summary(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    members = a.get("members")
    if members is None:
        return _err_result(["members is required"])
    if not isinstance(members, list):
        return _err_result(["members must be an array"])

    summary = framing_summary(members)
    summary["ok"] = True
    return ok_payload(summary)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _err_result(errors: list[str]) -> str:
    return ok_payload({"ok": False, "errors": errors})
