"""
PCB panelization — KiKit-style board arraying for fab.

Implements:
  panelize_board  — build a panel descriptor (N×M array + separation + frame)
  panel_info      — query panel dimensions and feature counts

The output ``PanelDescriptor`` is a plain dict that the existing Gerber /
Excellon writers can consume via ``export_panel_gerber`` / ``export_panel_excellon``
(thin wrappers exported from this module).

Separation methods
------------------
mousebites
    Row of drilled holes along each board–board gap. The LLM/user controls
    hole diameter and pitch; the module places the holes centred on the gap.

vscore
    A pair of V-groove lines are recorded on the edge_cuts layer. No copper
    can run under these lines. A line element per gap is added to the panel
    descriptor; the GKO writer draws them.

tab_route
    Thin tabs are left connecting the boards. Break-away holes are placed at
    tab ends. Tab width, count per edge, and hole diameter are parametric.

Frame / rail
------------
An optional rectangular border rail is added outside the board array. The
rail carries tooling holes (corner + mid-edge) and fiducial marks. The
rail's own edge_cuts outline becomes the panel outline.

Gerber/Excellon consumption
---------------------------
``export_panel_gerber`` / ``export_panel_excellon`` iterate over the per-instance
transforms in ``PanelDescriptor["instances"]`` and call the single-board writers
after transforming each element's coordinates. They also inject the panel-level
edge_cuts outline (frame or tight bounding rect) and the separation feature
elements (mousebite drill hits, vscore lines, tab_route holes).

All coordinates are in millimetres.  No rotation beyond 0° and 180° is
supported for alternating_rotate (KiKit flip-rotate style).
"""

from __future__ import annotations

import json
import math
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register


# ─── geometry helpers ─────────────────────────────────────────────────────────

def _board_bbox(circuit_json: list[dict]) -> tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) from pcb_board or smtpad extents."""
    for el in circuit_json:
        if el.get("type") in ("pcb_board", "board"):
            w = float(el.get("width", 0))
            h = float(el.get("height", 0))
            cx = float(el.get("center_x", el.get("x", w / 2)))
            cy = float(el.get("center_y", el.get("y", h / 2)))
            if w > 0 and h > 0:
                return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    # Fallback: union of all element coordinates
    xs = [float(e.get("x", 0)) for e in circuit_json if "x" in e]
    ys = [float(e.get("y", 0)) for e in circuit_json if "y" in e]
    if not xs:
        return 0.0, 0.0, 100.0, 80.0
    return min(xs), min(ys), max(xs), max(ys)


def _translate_element(el: dict, dx: float, dy: float) -> dict:
    """Return a shallow copy of *el* with (x,y) offset applied."""
    out = dict(el)
    if "x" in out:
        out["x"] = float(out["x"]) + dx
    if "y" in out:
        out["y"] = float(out["y"]) + dy
    if "center_x" in out:
        out["center_x"] = float(out["center_x"]) + dx
    if "center_y" in out:
        out["center_y"] = float(out["center_y"]) + dy
    # Translate route points
    if "route" in out and isinstance(out["route"], list):
        out["route"] = [
            {**pt, "x": float(pt.get("x", 0)) + dx, "y": float(pt.get("y", 0)) + dy}
            for pt in out["route"]
        ]
    if "polygon" in out and isinstance(out["polygon"], list):
        out["polygon"] = [
            {"x": float(p.get("x", 0)) + dx, "y": float(p.get("y", 0)) + dy}
            for p in out["polygon"]
        ]
    return out


def _rotate180_element(el: dict, pivot_x: float, pivot_y: float) -> dict:
    """Rotate element 180° around pivot. Used for alternating_rotate."""
    out = dict(el)

    def rot_xy(x: float, y: float) -> tuple[float, float]:
        return 2 * pivot_x - x, 2 * pivot_y - y

    if "x" in out and "y" in out:
        out["x"], out["y"] = rot_xy(float(out["x"]), float(out["y"]))
    if "center_x" in out and "center_y" in out:
        out["center_x"], out["center_y"] = rot_xy(float(out["center_x"]), float(out["center_y"]))
    if "rotation" in out:
        out["rotation"] = (float(out.get("rotation", 0)) + 180.0) % 360.0
    if "route" in out and isinstance(out["route"], list):
        out["route"] = [
            {**pt, "x": 2 * pivot_x - float(pt.get("x", 0)),
             "y": 2 * pivot_y - float(pt.get("y", 0))}
            for pt in out["route"]
        ]
    if "polygon" in out and isinstance(out["polygon"], list):
        out["polygon"] = [
            {"x": 2 * pivot_x - float(p.get("x", 0)),
             "y": 2 * pivot_y - float(p.get("y", 0))}
            for p in out["polygon"]
        ]
    return out


def _rect_outline(x0: float, y0: float, x1: float, y1: float) -> list[dict]:
    """Return four corner dicts for a rectangular outline."""
    return [
        {"x": x0, "y": y0},
        {"x": x1, "y": y0},
        {"x": x1, "y": y1},
        {"x": x0, "y": y1},
    ]


# ─── separation feature generators ───────────────────────────────────────────

def _mousebite_holes(
    x0: float, y0: float, x1: float, y1: float,
    hole_diameter: float = 0.8,
    hole_pitch: float = 1.2,
) -> list[dict]:
    """Generate mousebite drill hit dicts along a line segment (x0,y0)-(x1,y1)."""
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < hole_pitch:
        # Place a single hole at the midpoint
        return [{"type": "_mousebite_hole", "x": (x0 + x1) / 2, "y": (y0 + y1) / 2,
                 "diameter": hole_diameter}]
    n = max(1, int(length / hole_pitch))
    holes: list[dict] = []
    for i in range(n + 1):
        t = i / n
        holes.append({
            "type": "_mousebite_hole",
            "x": x0 + t * dx,
            "y": y0 + t * dy,
            "diameter": hole_diameter,
        })
    return holes


def _vscore_line(x0: float, y0: float, x1: float, y1: float) -> dict:
    """Return a V-score line element for the edge_cuts layer."""
    return {
        "type": "_vscore_line",
        "x0": x0, "y0": y0,
        "x1": x1, "y1": y1,
    }


def _tab_route_holes(
    x0: float, y0: float, x1: float, y1: float,
    tab_width_mm: float = 3.0,
    tab_count: int = 2,
    hole_diameter: float = 0.8,
) -> list[dict]:
    """Generate tab breakaway holes and tab segments along an edge segment."""
    features: list[dict] = []
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-6 or tab_count < 1:
        return features
    # Space tabs evenly
    step = length / (tab_count + 1)
    ux, uy = dx / length, dy / length
    for i in range(1, tab_count + 1):
        tc = i * step  # centre of tab along segment
        cx = x0 + tc * ux
        cy = y0 + tc * uy
        hw = tab_width_mm / 2
        # Start and end of tab
        tx0 = cx - hw * ux
        ty0 = cy - hw * uy
        tx1 = cx + hw * ux
        ty1 = cy + hw * uy
        features.append({
            "type": "_tab_segment",
            "x0": tx0, "y0": ty0,
            "x1": tx1, "y1": ty1,
            "width": tab_width_mm,
        })
        # Breakaway holes at tab ends
        for bx, by in [(tx0, ty0), (tx1, ty1)]:
            features.append({
                "type": "_mousebite_hole",
                "x": bx, "y": by,
                "diameter": hole_diameter,
            })
    return features


# ─── frame / rail generator ───────────────────────────────────────────────────

def _make_frame(
    array_x0: float, array_y0: float,
    array_x1: float, array_y1: float,
    rail_width: float = 5.0,
    tooling_hole_diameter: float = 2.0,
    fiducial_diameter: float = 1.0,
) -> dict:
    """Build panel frame element lists around the board array."""
    fx0 = array_x0 - rail_width
    fy0 = array_y0 - rail_width
    fx1 = array_x1 + rail_width
    fy1 = array_y1 + rail_width

    # Tooling holes — corner pockets + mid-edge (kept inside the rail)
    th_inset = rail_width / 2
    tooling_holes: list[dict] = []
    for (hx, hy) in [
        (fx0 + th_inset, fy0 + th_inset),
        (fx1 - th_inset, fy0 + th_inset),
        (fx0 + th_inset, fy1 - th_inset),
        (fx1 - th_inset, fy1 - th_inset),
        # mid-edge pairs
        ((fx0 + fx1) / 2, fy0 + th_inset),
        ((fx0 + fx1) / 2, fy1 - th_inset),
    ]:
        tooling_holes.append({
            "type": "_tooling_hole",
            "x": hx, "y": hy,
            "diameter": tooling_hole_diameter,
        })

    # Fiducials — 3-point triangle pattern on the top rail
    fid_y = fy0 + th_inset
    fiducials: list[dict] = []
    for fid_x in [fx0 + 2 * th_inset, (fx0 + fx1) / 2, fx1 - 2 * th_inset]:
        fiducials.append({
            "type": "_fiducial",
            "x": fid_x, "y": fid_y,
            "diameter": fiducial_diameter,
        })

    return {
        "outline": _rect_outline(fx0, fy0, fx1, fy1),
        "panel_x0": fx0, "panel_y0": fy0,
        "panel_x1": fx1, "panel_y1": fy1,
        "tooling_holes": tooling_holes,
        "fiducials": fiducials,
    }


# ─── core panelisation logic ──────────────────────────────────────────────────

def panelize(
    circuit_json: list[dict],
    cols: int = 2,
    rows: int = 2,
    gap_x_mm: float = 2.0,
    gap_y_mm: float = 2.0,
    separation: str = "mousebites",
    alternating_rotate: bool = False,
    # mousebites params
    mousebite_hole_diameter: float = 0.8,
    mousebite_hole_pitch: float = 1.2,
    # vscore params (reserved — future line-spec pass-through)
    vscore_line_width: float = 0.1,
    # tab_route params
    tab_width_mm: float = 3.0,
    tab_count: int = 2,
    tab_hole_diameter: float = 0.8,
    # frame params
    add_frame: bool = True,
    rail_width_mm: float = 5.0,
    tooling_hole_diameter: float = 2.0,
    fiducial_diameter: float = 1.0,
) -> dict:
    """Compute a panel descriptor for N×M board arrays.

    Parameters
    ----------
    circuit_json:
        Single-board CircuitJSON array.
    cols, rows:
        Number of columns / rows in the array.
    gap_x_mm, gap_y_mm:
        Gap between adjacent boards (horizontal / vertical), in mm.
    separation:
        One of ``"mousebites"``, ``"vscore"``, ``"tab_route"``.
    alternating_rotate:
        If True every other instance (chequerboard order) is rotated 180°.
    add_frame:
        If True, add a border rail with tooling holes and fiducials.
    rail_width_mm:
        Rail width in mm (applies to all four sides).

    Returns
    -------
    dict — the ``PanelDescriptor`` (see schema below).

    PanelDescriptor schema
    ----------------------
    {
      "board_w": float,         # source board width (mm)
      "board_h": float,         # source board height (mm)
      "cols": int,
      "rows": int,
      "gap_x": float,
      "gap_y": float,
      "separation": str,
      "alternating_rotate": bool,
      "instances": [            # one per board copy
        {
          "col": int,
          "row": int,
          "origin_x": float,    # lower-left of this board instance
          "origin_y": float,
          "rotated180": bool,
          "circuit_json": [...] # transformed copy of the input board elements
        },
        ...
      ],
      "separation_features": [  # mousebite/vscore/tab elements
        { "type": "_mousebite_hole"|"_vscore_line"|"_tab_segment", ... }
      ],
      "frame": { ... } | null,  # frame descriptor or null
      "panel_outline": [...],   # panel edge_cuts polygon vertices
      "array_x0": float, "array_y0": float,
      "array_x1": float, "array_y1": float,
      "panel_x0": float, "panel_y0": float,
      "panel_x1": float, "panel_y1": float,
    }
    """
    if cols < 1 or rows < 1:
        raise ValueError("cols and rows must be >= 1")
    valid_sep = {"mousebites", "vscore", "tab_route"}
    if separation not in valid_sep:
        raise ValueError(f"separation must be one of {valid_sep}")

    x0, y0, x1, y1 = _board_bbox(circuit_json)
    board_w = x1 - x0
    board_h = y1 - y0

    # pitch = board size + gap
    pitch_x = board_w + gap_x_mm
    pitch_y = board_h + gap_y_mm

    instances: list[dict] = []
    separation_features: list[dict] = []

    for row in range(rows):
        for col in range(cols):
            # origin of this board instance (lower-left corner)
            ox = col * pitch_x
            oy = row * pitch_y
            # board centre in panel coords
            cx = ox + board_w / 2
            cy = oy + board_h / 2

            rotated = alternating_rotate and ((col + row) % 2 == 1)

            # Transform every element into panel space
            translated: list[dict] = []
            for el in circuit_json:
                # Translate so board origin aligns with panel slot
                tex = _translate_element(el, ox - x0, oy - y0)
                if rotated:
                    tex = _rotate180_element(tex, cx, cy)
                translated.append(tex)

            instances.append({
                "col": col,
                "row": row,
                "origin_x": ox,
                "origin_y": oy,
                "rotated180": rotated,
                "circuit_json": translated,
            })

    # ── separation features ────────────────────────────────────────────────
    array_x0 = 0.0
    array_y0 = 0.0
    array_x1 = cols * pitch_x - gap_x_mm
    array_y1 = rows * pitch_y - gap_y_mm

    # Vertical gap lines (between cols)
    for c in range(1, cols):
        gx = c * pitch_x - gap_x_mm / 2  # centre of gap
        line_x0, line_y0 = gx, array_y0
        line_x1, line_y1 = gx, array_y1

        if separation == "mousebites":
            separation_features.extend(
                _mousebite_holes(line_x0, line_y0, line_x1, line_y1,
                                 hole_diameter=mousebite_hole_diameter,
                                 hole_pitch=mousebite_hole_pitch)
            )
        elif separation == "vscore":
            separation_features.append(
                _vscore_line(line_x0, line_y0, line_x1, line_y1)
            )
        elif separation == "tab_route":
            separation_features.extend(
                _tab_route_holes(line_x0, line_y0, line_x1, line_y1,
                                 tab_width_mm=tab_width_mm,
                                 tab_count=tab_count,
                                 hole_diameter=tab_hole_diameter)
            )

    # Horizontal gap lines (between rows)
    for r in range(1, rows):
        gy = r * pitch_y - gap_y_mm / 2
        line_x0, line_y0 = array_x0, gy
        line_x1, line_y1 = array_x1, gy

        if separation == "mousebites":
            separation_features.extend(
                _mousebite_holes(line_x0, line_y0, line_x1, line_y1,
                                 hole_diameter=mousebite_hole_diameter,
                                 hole_pitch=mousebite_hole_pitch)
            )
        elif separation == "vscore":
            separation_features.append(
                _vscore_line(line_x0, line_y0, line_x1, line_y1)
            )
        elif separation == "tab_route":
            separation_features.extend(
                _tab_route_holes(line_x0, line_y0, line_x1, line_y1,
                                 tab_width_mm=tab_width_mm,
                                 tab_count=tab_count,
                                 hole_diameter=tab_hole_diameter)
            )

    # ── frame ──────────────────────────────────────────────────────────────
    frame = None
    if add_frame:
        frame = _make_frame(
            array_x0, array_y0, array_x1, array_y1,
            rail_width=rail_width_mm,
            tooling_hole_diameter=tooling_hole_diameter,
            fiducial_diameter=fiducial_diameter,
        )
        panel_x0 = frame["panel_x0"]
        panel_y0 = frame["panel_y0"]
        panel_x1 = frame["panel_x1"]
        panel_y1 = frame["panel_y1"]
        panel_outline = frame["outline"]
    else:
        panel_x0, panel_y0 = array_x0, array_y0
        panel_x1, panel_y1 = array_x1, array_y1
        panel_outline = _rect_outline(array_x0, array_y0, array_x1, array_y1)

    return {
        "board_w": board_w,
        "board_h": board_h,
        "cols": cols,
        "rows": rows,
        "gap_x": gap_x_mm,
        "gap_y": gap_y_mm,
        "separation": separation,
        "alternating_rotate": alternating_rotate,
        "instances": instances,
        "separation_features": separation_features,
        "frame": frame,
        "panel_outline": panel_outline,
        "array_x0": array_x0, "array_y0": array_y0,
        "array_x1": array_x1, "array_y1": array_y1,
        "panel_x0": panel_x0, "panel_y0": panel_y0,
        "panel_x1": panel_x1, "panel_y1": panel_y1,
    }


# ─── Gerber / Excellon panel export ──────────────────────────────────────────

def export_panel_gerber(panel: dict, stem: str = "panel") -> dict[str, str]:
    """Produce Gerber files for a panel descriptor.

    Iterates over all board instances, collects their transformed circuit_json,
    merges them into a single virtual board, injects the panel edge_cuts outline
    and separation feature elements, then calls the single-board Gerber writer.

    Returns the same ``{filename: gerber_text}`` dict as ``export_gerber``.
    """
    from kerf_electronics.fab.gerber import export_gerber as _export_gerber

    merged: list[dict] = []

    # Merge all instance circuit_json elements (already in panel coords)
    for inst in panel["instances"]:
        for el in inst["circuit_json"]:
            # Skip per-instance board outline elements — we supply a single
            # panel outline below
            if el.get("type") in ("pcb_board", "board"):
                continue
            merged.append(el)

    # Panel-level pcb_board element (drives IPC-2581 board dims)
    px0 = panel["panel_x0"]
    py0 = panel["panel_y0"]
    px1 = panel["panel_x1"]
    py1 = panel["panel_y1"]
    pw = px1 - px0
    ph = py1 - py0
    merged.append({
        "type": "pcb_board",
        "width": pw,
        "height": ph,
        "center_x": (px0 + px1) / 2,
        "center_y": (py0 + py1) / 2,
    })

    # Inject panel outline as explicit pcb_outline_path
    merged.append({
        "type": "pcb_outline_path",
        "route": [{"x": p["x"], "y": p["y"]} for p in panel["panel_outline"]],
    })

    # Inject separation feature elements that affect Gerber layers:
    # - vscore lines → drawn on edge_cuts layer as pcb_silkscreen_line
    #   (fab houses read V-score from the edge_cuts or a dedicated mechanical layer)
    # - tab_route tabs → routed slots on edge_cuts (represented as lines)
    for feat in panel.get("separation_features", []):
        ft = feat.get("type")
        if ft == "_vscore_line":
            merged.append({
                "type": "pcb_silkscreen_line",
                "layer": "edge_cuts",
                "route": [
                    {"x": feat["x0"], "y": feat["y0"]},
                    {"x": feat["x1"], "y": feat["y1"]},
                ],
                "stroke_width": 0.1,
            })
        elif ft == "_tab_segment":
            merged.append({
                "type": "pcb_silkscreen_line",
                "layer": "edge_cuts",
                "route": [
                    {"x": feat["x0"], "y": feat["y0"]},
                    {"x": feat["x1"], "y": feat["y1"]},
                ],
                "stroke_width": feat.get("width", 3.0),
            })

    # Frame fiducials → silkscreen marks (top_silk)
    if panel.get("frame"):
        for fid in panel["frame"].get("fiducials", []):
            merged.append({
                "type": "pcb_silkscreen_text",
                "layer": "top_silk",
                "x": fid["x"],
                "y": fid["y"],
                "text": "+",
            })

    return _export_gerber(merged, stem=stem)


def export_panel_excellon(panel: dict, stem: str = "panel") -> dict[str, str]:
    """Produce Excellon drill files for a panel descriptor.

    Merges all board-instance drill hits (vias, PTH pads), then appends:
    - mousebite holes from ``separation_features``
    - tooling holes from ``frame``
    - tab-route breakaway holes

    Returns the same ``{filename: excellon_text}`` dict as ``export_excellon``.
    """
    from kerf_electronics.fab.excellon import export_excellon as _export_excellon

    merged: list[dict] = []

    for inst in panel["instances"]:
        for el in inst["circuit_json"]:
            t = el.get("type", "")
            if t in ("pcb_via", "pcb_plated_pad", "pcb_pad", "pcb_hole", "pcb_mounting_hole"):
                merged.append(el)

    # Mousebite + tab-route breakaway holes → pcb_hole (non-plated)
    for feat in panel.get("separation_features", []):
        if feat.get("type") == "_mousebite_hole":
            merged.append({
                "type": "pcb_hole",
                "x": feat["x"],
                "y": feat["y"],
                "hole_diameter": feat.get("diameter", 0.8),
                "plated": False,
            })

    # Tooling holes → non-plated holes
    if panel.get("frame"):
        for th in panel["frame"].get("tooling_holes", []):
            merged.append({
                "type": "pcb_hole",
                "x": th["x"],
                "y": th["y"],
                "hole_diameter": th.get("diameter", 2.0),
                "plated": False,
            })

    return _export_excellon(merged, stem=stem)


# ─── LLM tool: panelize_board ─────────────────────────────────────────────────

panelize_board_spec = ToolSpec(
    name="panelize_board",
    description=(
        "Panelize a CircuitJSON board into an N×M production panel. "
        "Arrays the board into a grid with configurable gap, separation method "
        "(mousebites / vscore / tab_route), optional border rail with tooling holes "
        "and fiducials, and optional alternating 180° rotation. "
        "Returns a panel_descriptor (JSON) plus Gerber and Excellon files for the panel "
        "so the result can be sent directly to a fab house. "
        "Use this when the user wants to array their board for batch PCB production."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": "Parsed CircuitJSON array from the board file.",
                "items": {"type": "object"},
            },
            "cols": {
                "type": "integer",
                "description": "Number of columns in the array (default: 2).",
                "minimum": 1,
            },
            "rows": {
                "type": "integer",
                "description": "Number of rows in the array (default: 2).",
                "minimum": 1,
            },
            "gap_x_mm": {
                "type": "number",
                "description": "Horizontal gap between boards in mm (default: 2.0).",
            },
            "gap_y_mm": {
                "type": "number",
                "description": "Vertical gap between boards in mm (default: 2.0).",
            },
            "separation": {
                "type": "string",
                "enum": ["mousebites", "vscore", "tab_route"],
                "description": (
                    "Board separation method. "
                    "'mousebites' = perforated hole rows (default). "
                    "'vscore' = V-groove score lines. "
                    "'tab_route' = routed tabs with breakaway holes."
                ),
            },
            "alternating_rotate": {
                "type": "boolean",
                "description": (
                    "If true, rotate every other board 180° (chequerboard). "
                    "Reduces material waste for asymmetric boards."
                ),
            },
            "mousebite_hole_diameter": {
                "type": "number",
                "description": "Mousebite hole diameter in mm (default: 0.8).",
            },
            "mousebite_hole_pitch": {
                "type": "number",
                "description": "Spacing between mousebite holes in mm (default: 1.2).",
            },
            "tab_width_mm": {
                "type": "number",
                "description": "Width of each tab in mm for tab_route (default: 3.0).",
            },
            "tab_count": {
                "type": "integer",
                "description": "Number of tabs per board edge for tab_route (default: 2).",
                "minimum": 1,
            },
            "tab_hole_diameter": {
                "type": "number",
                "description": "Breakaway hole diameter for tab_route in mm (default: 0.8).",
            },
            "add_frame": {
                "type": "boolean",
                "description": "Add a border rail with tooling holes + fiducials (default: true).",
            },
            "rail_width_mm": {
                "type": "number",
                "description": "Border rail width in mm (default: 5.0).",
            },
            "tooling_hole_diameter": {
                "type": "number",
                "description": "Tooling hole diameter in mm (default: 2.0).",
            },
            "stem": {
                "type": "string",
                "description": "Base filename stem for output files (default: 'panel').",
            },
        },
        "required": ["circuit_json"],
    },
)


@register(panelize_board_spec)
async def run_panelize_board(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not isinstance(circuit_json, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    cols = int(a.get("cols", 2))
    rows = int(a.get("rows", 2))
    if cols < 1 or rows < 1:
        return err_payload("cols and rows must be >= 1", "BAD_ARGS")

    gap_x = float(a.get("gap_x_mm", 2.0))
    gap_y = float(a.get("gap_y_mm", 2.0))
    separation = a.get("separation", "mousebites")
    if separation not in ("mousebites", "vscore", "tab_route"):
        return err_payload("separation must be one of mousebites, vscore, tab_route", "BAD_ARGS")

    stem = a.get("stem", "panel") or "panel"

    try:
        panel = panelize(
            circuit_json,
            cols=cols,
            rows=rows,
            gap_x_mm=gap_x,
            gap_y_mm=gap_y,
            separation=separation,
            alternating_rotate=bool(a.get("alternating_rotate", False)),
            mousebite_hole_diameter=float(a.get("mousebite_hole_diameter", 0.8)),
            mousebite_hole_pitch=float(a.get("mousebite_hole_pitch", 1.2)),
            tab_width_mm=float(a.get("tab_width_mm", 3.0)),
            tab_count=int(a.get("tab_count", 2)),
            tab_hole_diameter=float(a.get("tab_hole_diameter", 0.8)),
            add_frame=bool(a.get("add_frame", True)),
            rail_width_mm=float(a.get("rail_width_mm", 5.0)),
            tooling_hole_diameter=float(a.get("tooling_hole_diameter", 2.0)),
        )
    except Exception as e:
        return err_payload(f"panelize failed: {e}", "PANELIZE_ERROR")

    try:
        gerber_files = export_panel_gerber(panel, stem=stem)
        drill_files = export_panel_excellon(panel, stem=stem)
    except Exception as e:
        return err_payload(f"panel fab export failed: {e}", "EXPORT_ERROR")

    import base64, io, zipfile

    all_files: dict[str, str] = {}
    all_files.update(gerber_files)
    all_files.update(drill_files)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, content in sorted(all_files.items()):
            zf.writestr(fname, content.encode("utf-8"))
    zip_bytes = buf.getvalue()

    instance_count = len(panel["instances"])
    sep_count = len(panel["separation_features"])
    frame_info = None
    if panel.get("frame"):
        frame_info = {
            "tooling_holes": len(panel["frame"].get("tooling_holes", [])),
            "fiducials": len(panel["frame"].get("fiducials", [])),
        }

    return ok_payload({
        "panel_w_mm": round(panel["panel_x1"] - panel["panel_x0"], 3),
        "panel_h_mm": round(panel["panel_y1"] - panel["panel_y0"], 3),
        "board_w_mm": round(panel["board_w"], 3),
        "board_h_mm": round(panel["board_h"], 3),
        "cols": cols,
        "rows": rows,
        "instance_count": instance_count,
        "separation": separation,
        "separation_feature_count": sep_count,
        "frame": frame_info,
        "gerber_layers": sorted(gerber_files.keys()),
        "drill_files": sorted(drill_files.keys()),
        "panel_descriptor": panel,
        "zip_b64": base64.b64encode(zip_bytes).decode(),
        "zip_filename": f"{stem}-fab.zip",
        "zip_size_bytes": len(zip_bytes),
        "message": (
            f"Panel ready: {cols}×{rows} = {instance_count} boards, "
            f"separation={separation}, "
            f"{sep_count} separation feature(s). "
            f"Panel size: {round(panel['panel_x1'] - panel['panel_x0'], 1)} × "
            f"{round(panel['panel_y1'] - panel['panel_y0'], 1)} mm. "
            f"Decode zip_b64 to get the fab package."
        ),
    })


# ─── LLM tool: panel_info ────────────────────────────────────────────────────

panel_info_spec = ToolSpec(
    name="panel_info",
    description=(
        "Inspect an existing panel descriptor produced by panelize_board. "
        "Returns a human-readable summary: board/panel dimensions, instance list "
        "with per-instance origin and rotation, separation feature count by type, "
        "and frame tooling/fiducial positions. "
        "Use this when the user wants to understand or verify a panel without "
        "re-generating the fab files."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panel_descriptor": {
                "type": "object",
                "description": "The panel_descriptor object returned by panelize_board.",
            },
        },
        "required": ["panel_descriptor"],
    },
)


@register(panel_info_spec)
async def run_panel_info(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    panel = a.get("panel_descriptor")
    if not isinstance(panel, dict):
        return err_payload("panel_descriptor must be an object", "BAD_ARGS")

    required_keys = {"cols", "rows", "instances", "separation_features"}
    missing = required_keys - panel.keys()
    if missing:
        return err_payload(f"panel_descriptor missing keys: {sorted(missing)}", "BAD_ARGS")

    cols = panel.get("cols", 0)
    rows = panel.get("rows", 0)
    board_w = panel.get("board_w", 0)
    board_h = panel.get("board_h", 0)
    panel_w = panel.get("panel_x1", 0) - panel.get("panel_x0", 0)
    panel_h = panel.get("panel_y1", 0) - panel.get("panel_y0", 0)

    instances = panel.get("instances", [])
    instance_summary = [
        {
            "col": i["col"],
            "row": i["row"],
            "origin_x": round(i["origin_x"], 3),
            "origin_y": round(i["origin_y"], 3),
            "rotated180": i.get("rotated180", False),
        }
        for i in instances
    ]

    sep_features = panel.get("separation_features", [])
    sep_by_type: dict[str, int] = {}
    for f in sep_features:
        k = f.get("type", "unknown")
        sep_by_type[k] = sep_by_type.get(k, 0) + 1

    frame_summary = None
    if panel.get("frame"):
        frame_summary = {
            "tooling_holes": len(panel["frame"].get("tooling_holes", [])),
            "fiducials": len(panel["frame"].get("fiducials", [])),
            "rail_x0": round(panel["panel_x0"], 3),
            "rail_y0": round(panel["panel_y0"], 3),
            "rail_x1": round(panel["panel_x1"], 3),
            "rail_y1": round(panel["panel_y1"], 3),
        }

    return ok_payload({
        "cols": cols,
        "rows": rows,
        "instance_count": len(instances),
        "board_w_mm": round(board_w, 3),
        "board_h_mm": round(board_h, 3),
        "panel_w_mm": round(panel_w, 3),
        "panel_h_mm": round(panel_h, 3),
        "gap_x_mm": panel.get("gap_x", 0),
        "gap_y_mm": panel.get("gap_y", 0),
        "separation": panel.get("separation", ""),
        "alternating_rotate": panel.get("alternating_rotate", False),
        "instances": instance_summary,
        "separation_features_by_type": sep_by_type,
        "total_separation_features": len(sep_features),
        "frame": frame_summary,
    })
