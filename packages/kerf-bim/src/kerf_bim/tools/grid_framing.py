"""
grid_framing.py — LLM tools for structural grid and framing layout.

Tools
-----
bim_make_grid     — create a named structural grid from column/row axes
bim_make_framing  — create a structural frame (columns + beams) on a grid
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# bim_make_grid
# ---------------------------------------------------------------------------

_make_grid_spec = ToolSpec(
    name="bim_make_grid",
    description=(
        "Create a named structural grid from column axes (letters) and row axes "
        "(numbers).  Supports regular (equal-bay) or irregular (custom spacing) grids.\n"
        "\n"
        "Mode 'regular': provide bay_widths_m and bay_depths_m plus counts to get "
        "a uniform grid.  Mode 'custom': provide column_coords and row_coords "
        "arrays directly.\n"
        "\n"
        "Returns IFC-ready dict plus intersection coordinates."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["regular", "custom"],
                "description": "Grid mode. 'regular' = equal bays, 'custom' = explicit coords.",
                "default": "regular",
            },
            "n_cols": {
                "type": "integer",
                "description": "Number of column-line bays + 1 for 'regular' mode.",
            },
            "n_rows": {
                "type": "integer",
                "description": "Number of row-line bays + 1 for 'regular' mode.",
            },
            "bay_width_m": {
                "type": "number",
                "description": "Bay width in metres for 'regular' mode (default 6.0).",
                "default": 6.0,
            },
            "bay_depth_m": {
                "type": "number",
                "description": "Bay depth in metres for 'regular' mode (default 6.0).",
                "default": 6.0,
            },
            "column_coords": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Custom column-axis x-coordinates (metres) for 'custom' mode.",
            },
            "row_coords": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Custom row-axis y-coordinates (metres) for 'custom' mode.",
            },
            "origin_x": {"type": "number", "description": "Grid origin x (metres, default 0).", "default": 0.0},
            "origin_y": {"type": "number", "description": "Grid origin y (metres, default 0).", "default": 0.0},
        },
        "required": [],
    },
)


async def run_bim_make_grid(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.grid import make_regular_grid, make_grid, grid_to_ifc_dict, GridAxis

        mode = params.get("mode", "regular")
        ox = float(params.get("origin_x", 0.0))
        oy = float(params.get("origin_y", 0.0))

        if mode == "regular":
            n_bays_x = int(params.get("n_cols", 3))   # number of bays
            n_bays_y = int(params.get("n_rows", 2))
            bw_mm = float(params.get("bay_width_m", 6.0)) * 1000.0  # m→mm
            bd_mm = float(params.get("bay_depth_m", 6.0)) * 1000.0
            grid = make_regular_grid(
                bays_x=n_bays_x,
                bays_y=n_bays_y,
                bay_width=bw_mm,
                bay_depth=bd_mm,
                origin=[ox * 1000.0, oy * 1000.0],
            )
        elif mode == "custom":
            col_coords = params.get("column_coords")
            row_coords = params.get("row_coords")
            if not col_coords or not row_coords:
                return err_payload("column_coords and row_coords required for custom mode", "BAD_ARGS")
            col_positions = [(_col_label(i), (ox + float(c)) * 1000.0) for i, c in enumerate(col_coords)]
            row_positions = [(str(i + 1), (oy + float(c)) * 1000.0) for i, c in enumerate(row_coords)]
            grid = make_grid(name="Custom Grid", column_positions=col_positions, row_positions=row_positions)
        else:
            return err_payload(f"unknown mode {mode!r}", "BAD_ARGS")

        ifc_dict = grid_to_ifc_dict(grid)
        intersections = [
            {"col": c, "row": r, "x_m": round(x / 1000.0, 4), "y_m": round(y / 1000.0, 4)}
            for c, r, x, y in grid.intersections()
        ]
        return ok_payload({
            "ok": True,
            "n_col_lines": len(grid.column_axes),
            "n_row_lines": len(grid.row_axes),
            "n_intersections": len(intersections),
            "bay_widths_m": [round(v / 1000.0, 4) for v in grid.bay_widths],
            "bay_depths_m": [round(v / 1000.0, 4) for v in grid.bay_depths],
            "intersections": intersections,
            "ifc_dict": ifc_dict,
        })
    except Exception as exc:
        return err_payload(str(exc), "BIM_GRID_ERROR")


def _col_label(idx: int) -> str:
    """A, B, C, … Z, AA, AB, …"""
    label = ""
    while True:
        label = chr(ord("A") + idx % 26) + label
        idx = idx // 26 - 1
        if idx < 0:
            break
    return label


# ---------------------------------------------------------------------------
# bim_make_framing
# ---------------------------------------------------------------------------

_make_framing_spec = ToolSpec(
    name="bim_make_framing",
    description=(
        "Create a structural framing layout (columns + beams) on a regular grid.\n"
        "\n"
        "Generates columns at every grid intersection from base level to each storey "
        "and beams along each grid line at every storey.\n"
        "\n"
        "Returns IFC-ready dict with member counts and a summary of the layout."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n_cols": {
                "type": "integer",
                "description": "Number of column-axis grid lines (default 3).",
                "default": 3,
            },
            "n_rows": {
                "type": "integer",
                "description": "Number of row-axis grid lines (default 3).",
                "default": 3,
            },
            "bay_width_m": {"type": "number", "default": 6.0},
            "bay_depth_m": {"type": "number", "default": 6.0},
            "storey_heights_m": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of storey heights in metres (default [4.0]).",
            },
            "column_section": {
                "type": "string",
                "description": "Column section designation, e.g. 'UC203x203x46' (default 'UC203x203x46').",
                "default": "UC203x203x46",
            },
            "beam_section": {
                "type": "string",
                "description": "Beam section designation, e.g. 'UB305x165x46' (default 'UB305x165x46').",
                "default": "UB305x165x46",
            },
        },
        "required": [],
    },
)


async def run_bim_make_framing(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.grid import make_regular_grid
        from kerf_bim.framing import make_frame_on_grid, framing_to_ifc_dict

        n_bays_x = int(params.get("n_cols", 3))
        n_bays_y = int(params.get("n_rows", 2))
        bw_mm = float(params.get("bay_width_m", 6.0)) * 1000.0
        bd_mm = float(params.get("bay_depth_m", 6.0)) * 1000.0
        storey_heights_mm = [float(h) * 1000.0 for h in params.get("storey_heights_m", [4.0])]
        col_sec = str(params.get("column_section", "W250x73"))
        beam_sec = str(params.get("beam_section", "W360x51"))

        grid = make_regular_grid(
            bays_x=n_bays_x,
            bays_y=n_bays_y,
            bay_width=bw_mm,
            bay_depth=bd_mm,
        )

        layout = make_frame_on_grid(
            grid=grid,
            storey_heights=storey_heights_mm,
            column_section=col_sec,
            beam_section=beam_sec,
        )

        ifc_dict = framing_to_ifc_dict(layout)

        n_columns = len(layout.columns)
        n_beams = len(layout.beams)

        return ok_payload({
            "ok": True,
            "n_columns": n_columns,
            "n_beams": n_beams,
            "n_storeys": len(storey_heights_mm),
            "total_members": n_columns + n_beams,
            "ifc_dict": ifc_dict,
        })
    except Exception as exc:
        return err_payload(str(exc), "BIM_FRAMING_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_make_grid",    _make_grid_spec,    run_bim_make_grid),
    ("bim_make_framing", _make_framing_spec, run_bim_make_framing),
]
