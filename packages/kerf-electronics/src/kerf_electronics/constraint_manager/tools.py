"""
Constraint Manager spreadsheet UI — tabular get/set API.

Surfaces the existing net-class / constraint engine as row/column table data
suitable for a spreadsheet editing UI (rows = nets or net-classes,
columns = constraint properties).

Tools:
  constraint_table_get  — return the current constraint table (all net-classes
                          + per-net overrides) in a flat row-based format
  constraint_table_set  — write one or more cell edits back into the board
                          net_classes / net_rules, with validation

Column schema (mirrors Allegro Constraint Manager):
  name              — net/class name (read-only row key)
  kind              — "net_class" | "net"
  trace_width_mm    — min trace width
  clearance_mm      — min copper clearance
  via_diameter_mm   — via annular ring outer diameter
  via_drill_mm      — via drill hole diameter
  target_impedance_ohms  — target characteristic impedance (optional)
  length_match_group — length-match group label (optional string)
  via_type          — preferred via type: "through" | "blind" | "buried" | "micro" (optional)

Read/write delegation:
  - Net-class rows delegate to the net_classes list on the board.
  - Per-net override rows delegate to board.net_rules[net_id].
  - Built-in classes (Default/Power/Signal/HighSpeed/Differential) can be
    overridden but not deleted.

Validation ranges (conservative ECAD-grade defaults):
  trace_width_mm     : 0.01 – 25.0
  clearance_mm       : 0.01 – 25.0
  via_diameter_mm    : 0.1  – 10.0
  via_drill_mm       : 0.05 – 8.0
  target_impedance_ohms : 10 – 200
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.tools.net_classes import (
    _BUILTIN_CLASSES,
    _get_board,
    _ensure_board_keys,
    _resolve_class,
)

# ── column metadata ────────────────────────────────────────────────────────────

COLUMNS = [
    "name",
    "kind",
    "trace_width_mm",
    "clearance_mm",
    "via_diameter_mm",
    "via_drill_mm",
    "target_impedance_ohms",
    "length_match_group",
    "via_type",
]

_READONLY_COLS = {"name", "kind"}

_NUMERIC_COLS = {
    "trace_width_mm":         (0.01,  25.0),
    "clearance_mm":           (0.01,  25.0),
    "via_diameter_mm":        (0.1,   10.0),
    "via_drill_mm":           (0.05,   8.0),
    "target_impedance_ohms":  (10.0, 200.0),
}

_VIA_TYPES = {"through", "blind", "buried", "micro"}


def _validate_cell(col: str, value: Any) -> str | None:
    """Return an error message string if invalid, else None."""
    if col in _READONLY_COLS:
        return f"column '{col}' is read-only"
    if col in _NUMERIC_COLS:
        lo, hi = _NUMERIC_COLS[col]
        if not isinstance(value, (int, float)):
            return f"column '{col}' must be a number"
        if not (lo <= value <= hi):
            return f"column '{col}' value {value} out of range [{lo}, {hi}]"
    if col == "via_type" and value is not None:
        if value not in _VIA_TYPES:
            return f"via_type must be one of {sorted(_VIA_TYPES)}; got '{value}'"
    if col == "length_match_group" and value is not None:
        if not isinstance(value, str):
            return "length_match_group must be a string"
    return None


def _class_to_row(cls: dict, kind: str = "net_class") -> dict:
    """Convert a net-class dict to a flat constraint table row."""
    return {
        "name":                   cls.get("name", ""),
        "kind":                   kind,
        "trace_width_mm":         cls.get("trace_width_mm"),
        "clearance_mm":           cls.get("clearance_mm"),
        "via_diameter_mm":        cls.get("via_diameter_mm"),
        "via_drill_mm":           cls.get("via_drill_mm"),
        "target_impedance_ohms":  cls.get("target_impedance_ohms"),
        "length_match_group":     cls.get("length_match_group"),
        "via_type":               cls.get("via_type"),
    }


def _net_override_to_row(net_id: str, overrides: dict) -> dict:
    """Convert a per-net override dict to a flat row."""
    return {
        "name":                   net_id,
        "kind":                   "net",
        "trace_width_mm":         overrides.get("trace_width_mm"),
        "clearance_mm":           overrides.get("clearance_mm"),
        "via_diameter_mm":        overrides.get("via_diameter_mm"),
        "via_drill_mm":           overrides.get("via_drill_mm"),
        "target_impedance_ohms":  overrides.get("target_impedance_ohms"),
        "length_match_group":     overrides.get("length_match_group"),
        "via_type":               overrides.get("via_type"),
    }


def _build_table(board: dict | None) -> list[dict]:
    """Build the full constraint table from a board object."""
    rows: list[dict] = []

    # ── net-class rows ─────────────────────────────────────────────────────────
    user_classes = (board.get("net_classes") or []) if board else []
    user_by_name = {c["name"]: c for c in user_classes if "name" in c}

    seen: set[str] = set()
    for name, cls in _BUILTIN_CLASSES.items():
        effective = user_by_name.get(name, cls)
        rows.append(_class_to_row(effective))
        seen.add(name)

    for name, cls in user_by_name.items():
        if name not in seen:
            rows.append(_class_to_row(cls))
            seen.add(name)

    # ── per-net override rows ─────────────────────────────────────────────────
    net_rules = (board.get("net_rules") or {}) if board else {}
    for net_id, overrides in net_rules.items():
        if overrides:
            rows.append(_net_override_to_row(net_id, overrides))

    return rows


# ── constraint_table_get ──────────────────────────────────────────────────────

constraint_table_get_spec = ToolSpec(
    name="constraint_table_get",
    description=(
        "Return the current constraint table for a CircuitJSON board as a flat "
        "list of rows (net-classes + per-net overrides). Each row has columns: "
        "name, kind, trace_width_mm, clearance_mm, via_diameter_mm, via_drill_mm, "
        "target_impedance_ohms, length_match_group, via_type. "
        "This is the data-source for the Constraint Manager spreadsheet UI."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "object",
                "description": "The CircuitJSON board object.",
            },
        },
        "required": ["circuit_json"],
    },
)


@register(constraint_table_get_spec, write=False)
async def constraint_table_get(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not circuit_json:
        return err_payload("circuit_json is required", "BAD_ARGS")

    board = _get_board(circuit_json)
    rows = _build_table(board)

    return ok_payload({
        "columns": COLUMNS,
        "rows": rows,
    })


# ── constraint_table_set ──────────────────────────────────────────────────────

constraint_table_set_spec = ToolSpec(
    name="constraint_table_set",
    description=(
        "Write one or more constraint table cell edits into a CircuitJSON board. "
        "Each edit is {row_name, col, value} where row_name is a net-class name "
        "or net id and col is one of the editable columns: "
        "trace_width_mm, clearance_mm, via_diameter_mm, via_drill_mm, "
        "target_impedance_ohms, length_match_group, via_type. "
        "Net-class edits modify/create the class; net edits create/update "
        "per-net override rules. Validates ranges before writing. "
        "Returns the updated circuit_json and the new full constraint table."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "object",
                "description": "The CircuitJSON board object to modify.",
            },
            "edits": {
                "type": "array",
                "description": "List of cell edits to apply.",
                "items": {
                    "type": "object",
                    "properties": {
                        "row_name": {
                            "type": "string",
                            "description": "Net-class name (e.g. 'Power') or net id (e.g. 'GND').",
                        },
                        "col": {
                            "type": "string",
                            "description": "Column to edit.",
                            "enum": [
                                "trace_width_mm",
                                "clearance_mm",
                                "via_diameter_mm",
                                "via_drill_mm",
                                "target_impedance_ohms",
                                "length_match_group",
                                "via_type",
                            ],
                        },
                        "value": {
                            "description": "New value (number for numeric columns, string for string columns, null to clear optional fields).",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["net_class", "net"],
                            "description": "Row kind — defaults to 'net_class' for known class names, 'net' for others.",
                        },
                    },
                    "required": ["row_name", "col", "value"],
                },
                "minItems": 1,
            },
        },
        "required": ["circuit_json", "edits"],
    },
)


def _infer_kind(row_name: str, board: dict | None) -> str:
    """Infer whether a row_name is a net-class or net override."""
    if row_name in _BUILTIN_CLASSES:
        return "net_class"
    user_classes = (board.get("net_classes") or []) if board else []
    if any(c.get("name") == row_name for c in user_classes):
        return "net_class"
    return "net"


@register(constraint_table_set_spec, write=True)
async def constraint_table_set(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not circuit_json:
        return err_payload("circuit_json is required", "BAD_ARGS")

    edits = a.get("edits")
    if not edits or not isinstance(edits, list):
        return err_payload("edits must be a non-empty array", "BAD_ARGS")

    cloned = deepcopy(circuit_json)
    board = _get_board(cloned)
    if board is None:
        return err_payload("No pcb_board element found in circuit_json", "BAD_ARGS")

    _ensure_board_keys(board)
    if not isinstance(board.get("net_rules"), dict):
        board["net_rules"] = {}

    applied: list[dict] = []
    rejected: list[dict] = []

    for edit in edits:
        row_name = (edit.get("row_name") or "").strip()
        col      = (edit.get("col") or "").strip()
        value    = edit.get("value")
        kind     = (edit.get("kind") or "").strip() or _infer_kind(row_name, board)

        if not row_name:
            rejected.append({"edit": edit, "reason": "row_name is required"})
            continue

        if col not in COLUMNS or col in _READONLY_COLS:
            rejected.append({"edit": edit, "reason": f"col '{col}' is not writable"})
            continue

        # Validate value
        if value is not None:
            err_msg = _validate_cell(col, value)
            if err_msg:
                rejected.append({"edit": edit, "reason": err_msg})
                continue

        if kind == "net_class":
            # Find or create the user-defined class entry
            existing = next(
                (c for c in board["net_classes"] if c.get("name") == row_name), None
            )
            if existing is None:
                # Seed from builtin or blank
                base = deepcopy(_BUILTIN_CLASSES.get(row_name, {"name": row_name}))
                board["net_classes"].append(base)
                existing = board["net_classes"][-1]
            # Apply edit
            if value is None:
                existing.pop(col, None)
            else:
                existing[col] = value

        else:
            # per-net override
            if row_name not in board["net_rules"]:
                board["net_rules"][row_name] = {}
            if value is None:
                board["net_rules"][row_name].pop(col, None)
                # Clean up empty override dicts
                if not board["net_rules"][row_name]:
                    del board["net_rules"][row_name]
            else:
                board["net_rules"][row_name][col] = value

        applied.append({"row_name": row_name, "col": col, "value": value})

    if rejected and not applied:
        reasons = "; ".join(r["reason"] for r in rejected)
        return err_payload(f"All edits rejected: {reasons}", "BAD_ARGS")

    # Rebuild table view
    rows = _build_table(board)

    return ok_payload({
        "circuit_json": cloned,
        "applied": applied,
        "rejected": rejected,
        "table": {
            "columns": COLUMNS,
            "rows": rows,
        },
    })


# ── TOOLS export ──────────────────────────────────────────────────────────────

TOOLS = [
    ("constraint_table_get", constraint_table_get_spec, constraint_table_get),
    ("constraint_table_set", constraint_table_set_spec, constraint_table_set),
]
