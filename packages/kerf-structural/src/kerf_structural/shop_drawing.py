"""
Shop drawing and general-arrangement (GA) drawing generation for structural members.

Generates fabrication-ready drawing data (JSON) that can be rendered to SVG/DXF:
- Member marks, dimensioned section + elevation views
- Bar/section marks with leaders
- Bar-bending schedule table embedded in drawing sheet
- Assembly marks, sheet title block
- Multi-sheet GA layout reusing the existing HLR/drawing engine concepts

Scope: data-model output only (pure Python, no raster output).
Rendering to SVG is delegated to the frontend panel or DXF exporter.

References
----------
BS EN ISO 3766:2003  Drawing practice for RC — simplified representation
BS 8888:2017         Technical product documentation
AISC 927-18          Standard for detailing structural steel (US reference)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Title block
# ---------------------------------------------------------------------------

@dataclass
class TitleBlock:
    """Title block metadata for a drawing sheet."""
    project_name: str = "Project"
    drawing_title: str = "Structural Drawing"
    drawing_number: str = "S-001"
    revision: str = "P1"
    scale: str = "1:50"
    date: str = ""
    drawn_by: str = ""
    checked_by: str = ""
    client: str = ""

    def as_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "drawing_title": self.drawing_title,
            "drawing_number": self.drawing_number,
            "revision": self.revision,
            "scale": self.scale,
            "date": self.date,
            "drawn_by": self.drawn_by,
            "checked_by": self.checked_by,
            "client": self.client,
        }


# ---------------------------------------------------------------------------
# Drawing primitives (SVG-friendly dict representation)
# ---------------------------------------------------------------------------

def _line(x1: float, y1: float, x2: float, y2: float,
          style: str = "solid", layer: str = "outline") -> dict:
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "style": style, "layer": layer}


def _rect(x: float, y: float, w: float, h: float,
          style: str = "solid", layer: str = "outline") -> dict:
    return {"type": "rect", "x": x, "y": y, "w": w, "h": h,
            "style": style, "layer": layer}


def _circle(cx: float, cy: float, r: float, layer: str = "rebar") -> dict:
    return {"type": "circle", "cx": cx, "cy": cy, "r": r, "layer": layer}


def _text(x: float, y: float, text: str, size: float = 3.5,
          anchor: str = "start", layer: str = "annotation") -> dict:
    return {"type": "text", "x": x, "y": y, "text": text,
            "size": size, "anchor": anchor, "layer": layer}


def _dim_line(x1: float, y1: float, x2: float, y2: float,
              value: str, offset: float = 8.0) -> dict:
    """Dimension line between two points with value annotation."""
    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0
    return {
        "type": "dimension",
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "mid_x": mid_x, "mid_y": mid_y,
        "value": value,
        "offset": offset,
        "layer": "dimension",
    }


def _leader(x_tip: float, y_tip: float, x_text: float, y_text: float,
            text: str) -> dict:
    return {
        "type": "leader",
        "x_tip": x_tip, "y_tip": y_tip,
        "x_text": x_text, "y_text": y_text,
        "text": text,
        "layer": "annotation",
    }


# ---------------------------------------------------------------------------
# Section view generator
# ---------------------------------------------------------------------------

def _beam_section_view(
    origin_x: float,
    origin_y: float,
    width_mm: float,
    depth_mm: float,
    cover_mm: float,
    long_bar_d_mm: float,
    stirrup_d_mm: float,
    n_bars_bottom: int,
    n_bars_top: int,
    scale: float = 0.5,   # mm per SVG unit
) -> list[dict]:
    """
    Generate drawing entities for a beam cross-section view.

    Returns a list of drawing primitive dicts.
    All coordinates in SVG-space (origin_x/y offset, scaled by `scale`).
    """
    entities: list[dict] = []

    W = width_mm * scale
    H = depth_mm * scale
    cv = cover_mm * scale
    d_l = long_bar_d_mm * scale
    d_s = stirrup_d_mm * scale
    r_l = d_l / 2.0
    r_s = d_s / 2.0

    # Outer concrete outline
    entities.append(_rect(origin_x, origin_y, W, H))

    # Stirrup rectangle
    sx = origin_x + cv
    sy = origin_y + cv
    sw = W - 2 * cv
    sh = H - 2 * cv
    entities.append(_rect(sx, sy, sw, sh, style="solid", layer="rebar"))

    # Longitudinal bars — bottom
    offset_to_cl = cv + d_s + r_l
    y_bot = origin_y + H - offset_to_cl
    y_top = origin_y + offset_to_cl

    for layer_bars, y_pos in [(n_bars_bottom, y_bot), (n_bars_top, y_top)]:
        if layer_bars <= 0:
            continue
        if layer_bars == 1:
            xs = [origin_x + W / 2.0]
        else:
            inner_w = W - 2 * (cv + d_s + r_l)
            sp = inner_w / (layer_bars - 1)
            xs = [origin_x + (cv + d_s + r_l) + i * sp for i in range(layer_bars)]
        for x_pos in xs:
            entities.append(_circle(x_pos, y_pos, r_l))

    # Bar leaders (mark annotation)
    bar_label = f"T{int(long_bar_d_mm)}"
    if n_bars_bottom > 0:
        xs_b = origin_x + cv + d_s + r_l
        entities.append(_leader(xs_b, y_bot, origin_x - 15, y_bot, f"{n_bars_bottom}-{bar_label}"))
    if n_bars_top > 0:
        xs_t = origin_x + cv + d_s + r_l
        entities.append(_leader(xs_t, y_top, origin_x - 15, y_top, f"{n_bars_top}-{bar_label}"))

    # Stirrup leader
    entities.append(_leader(
        sx, sy + sh / 2.0, origin_x + W + 5, origin_y + H / 2.0,
        f"T{int(stirrup_d_mm)} links"
    ))

    # Dimension lines
    entities.append(_dim_line(origin_x, origin_y + H + 8, origin_x + W, origin_y + H + 8,
                               f"{width_mm:.0f}"))
    entities.append(_dim_line(origin_x - 8, origin_y, origin_x - 8, origin_y + H,
                               f"{depth_mm:.0f}"))

    # View label
    entities.append(_text(origin_x + W / 2.0, origin_y - 5, "SECTION", anchor="middle"))

    return entities


def _beam_elevation_view(
    origin_x: float,
    origin_y: float,
    length_mm: float,
    depth_mm: float,
    cover_mm: float,
    stirrup_d_mm: float,
    stirrup_spacing_mm: float,
    n_bars_bottom: int,
    n_bars_top: int,
    long_bar_d_mm: float,
    scale: float = 0.05,
) -> list[dict]:
    """
    Generate drawing entities for a beam elevation view.
    """
    entities: list[dict] = []

    L = length_mm * scale
    H = depth_mm * scale
    cv = cover_mm * scale
    d_l = long_bar_d_mm * scale
    d_s = stirrup_d_mm * scale

    # Concrete outline
    entities.append(_rect(origin_x, origin_y, L, H))

    # Bottom longitudinal bar centreline
    y_bot_cl = origin_y + H - cv - d_s - d_l / 2.0
    y_top_cl = origin_y + cv + d_s + d_l / 2.0

    if n_bars_bottom > 0:
        entities.append(_line(origin_x + cv, y_bot_cl, origin_x + L - cv, y_bot_cl,
                               style="dashed", layer="rebar"))
    if n_bars_top > 0:
        entities.append(_line(origin_x + cv, y_top_cl, origin_x + L - cv, y_top_cl,
                               style="dashed", layer="rebar"))

    # Stirrups (vertical lines at spacing)
    n_stir = max(1, int((length_mm - 2 * cover_mm) / stirrup_spacing_mm) + 1)
    stir_start_x = origin_x + cv
    stir_spacing_scaled = stirrup_spacing_mm * scale
    for i in range(min(n_stir, 60)):  # cap SVG entities for large members
        sx = stir_start_x + i * stir_spacing_scaled
        if sx > origin_x + L - cv:
            break
        entities.append(_line(sx, origin_y + cv, sx, origin_y + H - cv,
                               layer="rebar"))

    # Dimension: member length
    entities.append(_dim_line(origin_x, origin_y + H + 8, origin_x + L, origin_y + H + 8,
                               f"{length_mm:.0f}"))
    # Dimension: depth
    entities.append(_dim_line(origin_x - 8, origin_y, origin_x - 8, origin_y + H,
                               f"{depth_mm:.0f}"))

    # Stirrup spacing annotation
    mid_x = origin_x + L / 2.0
    entities.append(_text(mid_x, origin_y - 5, f"T{int(stirrup_d_mm)}-{stirrup_spacing_mm:.0f}c/c",
                           anchor="middle"))

    # View label
    entities.append(_text(origin_x + L / 2.0, origin_y + H + 18, "ELEVATION", anchor="middle"))

    return entities


# ---------------------------------------------------------------------------
# Bar-bending schedule table (drawing entity)
# ---------------------------------------------------------------------------

def _bending_schedule_table(
    origin_x: float,
    origin_y: float,
    rows: list[dict],
    col_widths: list[float] | None = None,
) -> list[dict]:
    """
    Generate drawing entities for a bar-bending schedule table.

    Columns: Member | Mark | Type | Dia | Shape | A | Length | No. | Total L | Mass
    """
    if col_widths is None:
        col_widths = [20, 12, 8, 8, 10, 14, 18, 10, 18, 14]

    headers = ["Member", "Mark", "Type", "Dia", "Shape", "A (mm)", "L (mm)", "No.", "Total L (m)", "Mass (kg)"]
    row_h = 7.0
    header_h = 9.0

    entities: list[dict] = []
    total_w = sum(col_widths)

    # Header background rect
    entities.append(_rect(origin_x, origin_y, total_w, header_h, layer="annotation"))
    entities.append(_text(origin_x + total_w / 2.0, origin_y + 6,
                           "BAR BENDING SCHEDULE", size=4.5, anchor="middle"))

    y_cur = origin_y + header_h
    # Column headers
    x_cur = origin_x
    for hdr, cw in zip(headers, col_widths):
        entities.append(_text(x_cur + 1.5, y_cur + 5, hdr, size=3.0))
        x_cur += cw
    entities.append(_line(origin_x, y_cur, origin_x + total_w, y_cur, layer="annotation"))

    y_cur += row_h

    # Data rows
    for row in rows:
        x_cur = origin_x
        A_val = row.get("dims", {}).get("A", "")
        cells = [
            row.get("member_ref", ""),
            row.get("bar_mark", ""),
            row.get("bar_type", "H"),
            str(row.get("diameter_mm", "")),
            row.get("shape_code", ""),
            f"{A_val:.0f}" if isinstance(A_val, (int, float)) else str(A_val),
            f"{row.get('cut_length_mm', 0):.0f}",
            str(row.get("number_of_bars", "")),
            f"{row.get('total_length_m', 0):.2f}",
            f"{row.get('mass_kg', 0):.2f}",
        ]
        for cell, cw in zip(cells, col_widths):
            entities.append(_text(x_cur + 1.5, y_cur + 4.5, cell, size=2.8))
            x_cur += cw
        entities.append(_line(origin_x, y_cur, origin_x + total_w, y_cur,
                               style="thin", layer="annotation"))
        y_cur += row_h

    # Outer border
    table_h = y_cur - origin_y
    entities.append(_rect(origin_x, origin_y, total_w, table_h, layer="annotation"))

    # Vertical column separators
    x_cur = origin_x
    for cw in col_widths[:-1]:
        x_cur += cw
        entities.append(_line(x_cur, origin_y, x_cur, origin_y + table_h, layer="annotation"))

    return entities


# ---------------------------------------------------------------------------
# Title block entities
# ---------------------------------------------------------------------------

def _title_block_entities(
    sheet_w: float,
    sheet_h: float,
    tb: TitleBlock,
    margin: float = 10.0,
) -> list[dict]:
    """Generate title block drawing entities at bottom-right of sheet."""
    tb_w = 180.0
    tb_h = 40.0
    x = sheet_w - margin - tb_w
    y = sheet_h - margin - tb_h

    entities: list[dict] = []
    entities.append(_rect(x, y, tb_w, tb_h, layer="annotation"))

    # Fields
    fields = [
        (x + 2, y + 6,   f"PROJECT: {tb.project_name}"),
        (x + 2, y + 13,  f"TITLE: {tb.drawing_title}"),
        (x + 2, y + 20,  f"DWG No: {tb.drawing_number}  REV: {tb.revision}"),
        (x + 2, y + 27,  f"SCALE: {tb.scale}  DATE: {tb.date}"),
        (x + 2, y + 34,  f"DRAWN: {tb.drawn_by}  CHK: {tb.checked_by}"),
    ]
    for fx, fy, text in fields:
        entities.append(_text(fx, fy, text, size=3.0))

    return entities


# ---------------------------------------------------------------------------
# Main shop drawing generator
# ---------------------------------------------------------------------------

def generate_shop_drawing(
    member_ref: str,
    member_type: str,
    length_mm: float,
    width_mm: float,
    depth_mm: float,
    cover_mm: float,
    long_bar_diameter_mm: int,
    n_bars_bottom: int,
    n_bars_top: int,
    stirrup_diameter_mm: int,
    stirrup_spacing_mm: float,
    bending_schedule_rows: list[dict],
    title_block: dict | None = None,
    sheet: str = "A1",
) -> dict:
    """
    Generate a complete shop drawing data structure for a single RC member.

    The output is a sheet-level drawing dict with:
      - `sheets`: list of sheet dicts, each with `entities` (drawing primitives)
      - `title_block`: title-block metadata
      - `member_mark`: member reference
      - `summary`: bar count / mass summary

    Two sheets are generated:
      Sheet 1: Section view (cross-section) + elevation view + assembly mark
      Sheet 2: Bar-bending schedule table

    Parameters
    ----------
    member_ref : str
        Member mark (e.g. 'B1').
    member_type : str
        'beam', 'column', or 'slab'.
    length_mm, width_mm, depth_mm, cover_mm : float
        Member geometry (mm).
    long_bar_diameter_mm : int
        Longitudinal bar nominal diameter (mm).
    n_bars_bottom, n_bars_top : int
        Number of longitudinal bars per layer.
    stirrup_diameter_mm : int
        Transverse bar diameter (mm).
    stirrup_spacing_mm : float
        Stirrup / link spacing (mm).
    bending_schedule_rows : list[dict]
        Rows from generate_bending_schedule() output.
    title_block : dict or None
        Title-block parameters (project_name, drawing_title, etc.).
    sheet : str
        Sheet size code ('A1', 'A2', 'A3').

    Returns
    -------
    dict
        {
          "ok": True,
          "member_ref": ...,
          "sheets": [sheet1_dict, sheet2_dict],
          "title_block": {...},
          "summary": {"total_bars": ..., "total_mass_kg": ...}
        }
    """
    # Sheet dimensions (mm at 1:1, then we scale in SVG)
    _sheet_sizes = {
        "A1": (841, 594),
        "A2": (594, 420),
        "A3": (420, 297),
    }
    sw, sh = _sheet_sizes.get(sheet, _sheet_sizes["A1"])

    tb_data = title_block or {}
    tb = TitleBlock(
        project_name=tb_data.get("project_name", "Project"),
        drawing_title=tb_data.get("drawing_title", f"{member_type.title()} {member_ref} Reinforcement Drawing"),
        drawing_number=tb_data.get("drawing_number", "S-001"),
        revision=tb_data.get("revision", "P1"),
        scale=tb_data.get("scale", "1:50"),
        date=tb_data.get("date", ""),
        drawn_by=tb_data.get("drawn_by", ""),
        checked_by=tb_data.get("checked_by", ""),
        client=tb_data.get("client", ""),
    )

    # --- Sheet 1: Views ---
    margin = 15.0
    sheet1_entities: list[dict] = []

    # Section view (scale: 1 unit = 2 mm → 1:2)
    sec_scale = 0.5
    sec_origin_x = margin + 30
    sec_origin_y = margin + 20

    sheet1_entities += _beam_section_view(
        sec_origin_x, sec_origin_y,
        width_mm=width_mm,
        depth_mm=depth_mm,
        cover_mm=cover_mm,
        long_bar_d_mm=float(long_bar_diameter_mm),
        stirrup_d_mm=float(stirrup_diameter_mm),
        n_bars_bottom=n_bars_bottom,
        n_bars_top=n_bars_top,
        scale=sec_scale,
    )

    # Elevation view (scale: 1 unit = 20 mm → 1:20)
    elev_scale = 0.05
    elev_origin_x = sec_origin_x + width_mm * sec_scale + 40
    elev_origin_y = sec_origin_y

    sheet1_entities += _beam_elevation_view(
        elev_origin_x, elev_origin_y,
        length_mm=length_mm,
        depth_mm=depth_mm,
        cover_mm=cover_mm,
        stirrup_d_mm=float(stirrup_diameter_mm),
        stirrup_spacing_mm=stirrup_spacing_mm,
        n_bars_bottom=n_bars_bottom,
        n_bars_top=n_bars_top,
        long_bar_d_mm=float(long_bar_diameter_mm),
        scale=elev_scale,
    )

    # Assembly mark at top-left
    sheet1_entities.append(_text(margin, margin, f"MEMBER: {member_ref}", size=5, layer="annotation"))
    sheet1_entities.append(_text(margin, margin + 8, f"TYPE: {member_type.upper()}", size=4, layer="annotation"))

    # Title block
    sheet1_entities += _title_block_entities(sw, sh, tb)

    # --- Sheet 2: Bending schedule ---
    sheet2_entities: list[dict] = []
    sheet2_entities.append(_text(margin, margin, "BAR BENDING SCHEDULE", size=5, layer="annotation"))
    sheet2_entities += _bending_schedule_table(
        margin, margin + 10, bending_schedule_rows
    )

    # Title block on sheet 2 too
    tb2 = TitleBlock(**{**tb.as_dict(),
                        "drawing_title": f"{member_type.title()} {member_ref} — Bending Schedule",
                        "drawing_number": tb_data.get("drawing_number", "S-001") + "/2"})
    sheet2_entities += _title_block_entities(sw, sh, tb2)

    # Summary
    total_bars = sum(r.get("number_of_bars", 0) for r in bending_schedule_rows)
    total_mass = round(sum(r.get("mass_kg", 0.0) for r in bending_schedule_rows), 3)

    return {
        "ok": True,
        "member_ref": member_ref,
        "sheets": [
            {
                "sheet_number": 1,
                "sheet_size": sheet,
                "title": f"{member_ref} Reinforcement",
                "entities": sheet1_entities,
                "entity_count": len(sheet1_entities),
            },
            {
                "sheet_number": 2,
                "sheet_size": sheet,
                "title": f"{member_ref} Bending Schedule",
                "entities": sheet2_entities,
                "entity_count": len(sheet2_entities),
            },
        ],
        "title_block": tb.as_dict(),
        "summary": {
            "total_bars": total_bars,
            "total_mass_kg": total_mass,
            "sheets": 2,
            "schedule_rows": len(bending_schedule_rows),
        },
    }


def generate_ga_drawing(
    members: list[dict],
    title_block: dict | None = None,
    sheet: str = "A1",
) -> dict:
    """
    Generate a multi-sheet GA (general arrangement) drawing for a structure.

    Sheet 1: Member location plan (simplified 2D grid with member marks).
    Sheet 2+: Individual member reinforcement drawings (one per member).
    Final sheet: Combined bar-bending schedule.

    Parameters
    ----------
    members : list[dict]
        Each dict: {
          "member_ref": str,
          "member_type": str,
          "x_mm": float,   # plan position X
          "y_mm": float,   # plan position Y
          "all_bars": list[dict],  # from detail_member
          ... (geometry keys)
        }
    title_block : dict or None
    sheet : str

    Returns
    -------
    dict
        { "ok", "sheets", "title_block", "summary" }
    """
    _sheet_sizes = {"A1": (841, 594), "A2": (594, 420), "A3": (420, 297)}
    sw, sh = _sheet_sizes.get(sheet, _sheet_sizes["A1"])
    margin = 15.0

    tb_data = title_block or {}
    tb = TitleBlock(
        project_name=tb_data.get("project_name", "Project"),
        drawing_title=tb_data.get("drawing_title", "General Arrangement"),
        drawing_number=tb_data.get("drawing_number", "GA-001"),
        revision=tb_data.get("revision", "P1"),
        scale=tb_data.get("scale", "1:100"),
        date=tb_data.get("date", ""),
        drawn_by=tb_data.get("drawn_by", ""),
        checked_by=tb_data.get("checked_by", ""),
        client=tb_data.get("client", ""),
    )

    sheets: list[dict] = []

    # --- GA Sheet 1: Plan layout ---
    ga_entities: list[dict] = []
    ga_entities.append(_text(margin, margin, "GENERAL ARRANGEMENT PLAN", size=6, layer="annotation"))

    plan_scale = 0.01   # 1 unit = 100 mm (1:100)
    for m in members:
        mx = margin + 20 + m.get("x_mm", 0.0) * plan_scale
        my = margin + 20 + m.get("y_mm", 0.0) * plan_scale
        mw = m.get("width_mm", 300.0) * plan_scale
        mh = m.get("length_mm", 5000.0) * plan_scale * 0.02  # simplified plan footprint

        ga_entities.append(_rect(mx, my, max(mw, 4), max(mh, 4)))
        ga_entities.append(_text(mx + 1, my + 3,
                                  m.get("member_ref", "?"), size=2.5))

    ga_entities += _title_block_entities(sw, sh, tb)
    sheets.append({
        "sheet_number": 1,
        "sheet_size": sheet,
        "title": "GA Plan",
        "entities": ga_entities,
        "entity_count": len(ga_entities),
    })

    # --- Assembly marks legend ---
    asm_entities: list[dict] = []
    asm_entities.append(_text(margin, margin, "ASSEMBLY MARKS / MEMBER SCHEDULE", size=5))
    y_leg = margin + 10
    for m in members:
        asm_entities.append(_text(margin, y_leg,
                                   f"{m.get('member_ref','?')} — {m.get('member_type','').upper()} "
                                   f"{m.get('width_mm',0):.0f}×{m.get('depth_mm',0):.0f}×{m.get('length_mm',0):.0f} mm",
                                   size=3.0))
        y_leg += 6

    asm_entities += _title_block_entities(sw, sh,
                                           TitleBlock(**{**tb.as_dict(),
                                                         "drawing_title": "Assembly Marks",
                                                         "drawing_number": tb_data.get("drawing_number", "GA-001") + "/ASM"}))
    sheets.append({
        "sheet_number": 2,
        "sheet_size": sheet,
        "title": "Assembly Marks",
        "entities": asm_entities,
        "entity_count": len(asm_entities),
    })

    # --- Combined bending schedule ---
    all_rows: list[dict] = []
    for m in members:
        ref = m.get("member_ref", "?")
        for bar in m.get("all_bars", []):
            d = int(bar.get("diameter_mm", 0))
            count = int(bar.get("count", 0))
            cut_len = float(bar.get("cut_length_mm", 0))
            try:
                from kerf_structural.rebar_3d import bs_bar_properties
                props = bs_bar_properties(d)
                mass = round(props.mass_kg_per_m * (cut_len / 1000.0) * count, 3)
            except Exception:
                mass = 0.0
            all_rows.append({
                "member_ref": ref,
                "bar_mark": bar.get("mark", ""),
                "bar_type": "H",
                "diameter_mm": d,
                "shape_code": bar.get("shape_code", "00"),
                "dims": bar.get("dims", {}),
                "cut_length_mm": cut_len,
                "number_of_bars": count,
                "total_length_m": round(cut_len / 1000.0 * count, 3),
                "mass_kg": mass,
            })

    sched_entities: list[dict] = []
    sched_entities.append(_text(margin, margin, "COMBINED BAR BENDING SCHEDULE", size=5))
    sched_entities += _bending_schedule_table(margin, margin + 10, all_rows)
    sched_entities += _title_block_entities(sw, sh,
                                             TitleBlock(**{**tb.as_dict(),
                                                           "drawing_title": "Bar Bending Schedule",
                                                           "drawing_number": tb_data.get("drawing_number", "GA-001") + "/BBS"}))
    sheets.append({
        "sheet_number": 3,
        "sheet_size": sheet,
        "title": "Bending Schedule",
        "entities": sched_entities,
        "entity_count": len(sched_entities),
    })

    total_mass = round(sum(r.get("mass_kg", 0.0) for r in all_rows), 3)
    total_bars = sum(r.get("number_of_bars", 0) for r in all_rows)

    return {
        "ok": True,
        "sheets": sheets,
        "title_block": tb.as_dict(),
        "summary": {
            "total_sheets": len(sheets),
            "member_count": len(members),
            "total_bars": total_bars,
            "total_mass_kg": total_mass,
        },
    }
