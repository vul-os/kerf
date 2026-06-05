"""shop_drawings.py — Shop drawing and technical documentation generator.

Produces structured shop-drawing data for woodworking cabinet and furniture
parts. The output is a JSON-serialisable dict suitable for:

  - Rendering a 2D orthographic drawing on the frontend.
  - CNC machine import (DXF-like coordinate data).
  - Printed shop packets (human-readable part lists + annotations).

Cabinet drawing conventions follow AWI (Architectural Woodwork Institute)
Quality Standards 9th edition §11 and KCMA (2021) Cabinet Standards.

The module does NOT generate binary file formats (PDF/DXF) directly — it
produces coordinate/annotation data that the frontend SVG renderer or a
downstream DXF writer can consume.

References:
    AWI (2014). Architectural Woodwork Quality Standards, 9th ed., §11.
    KCMA (2021). Cabinet Standards §5: Shop drawings.
    Stanley, J. (2010). Furniture Design & Construction. Ch. 15: Drawings.

All dimensions in millimetres unless noted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

@dataclass
class Line:
    """A single line segment."""
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "visible"   # 'visible' | 'hidden' | 'centre' | 'dimension'
    label: str = ""


@dataclass
class Arc:
    """A circular arc."""
    cx: float          # centre x
    cy: float          # centre y
    radius: float
    start_deg: float   # start angle (degrees from +x axis)
    end_deg: float     # end angle
    layer: str = "visible"
    label: str = ""


@dataclass
class Dimension:
    """A linear dimension annotation."""
    x1: float
    y1: float
    x2: float
    y2: float
    value_mm: float
    text: str = ""
    direction: str = "horizontal"   # 'horizontal' | 'vertical' | 'aligned'


@dataclass
class HoleAnnotation:
    """A bore hole annotation circle."""
    cx: float
    cy: float
    diameter_mm: float
    depth_mm: float
    label: str = ""
    kind: str = "drill"   # 'drill' | 'counterbore' | 'countersink' | 'cup'


@dataclass
class View:
    """One orthographic view of a panel (front, side, top, section)."""
    name: str                          # 'front' | 'back' | 'left' | 'right' | 'top' | 'bottom' | 'section'
    origin_x: float = 0.0             # view origin in drawing space
    origin_y: float = 0.0
    scale: float = 1.0                # drawing scale (1.0 = full size, 0.1 = 1:10)
    lines: List[Line] = field(default_factory=list)
    arcs: List[Arc] = field(default_factory=list)
    dimensions: List[Dimension] = field(default_factory=list)
    holes: List[HoleAnnotation] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ShopDrawing:
    """Complete shop drawing for one part or assembly.

    Attributes
    ----------
    part_id : str
        Part identifier.
    part_description : str
        Human-readable description (e.g. 'Base cabinet B1 — left side panel').
    views : list[View]
        Orthographic views.
    bill_of_materials : list[dict]
        BOM entries [{part_id, description, material, qty, length_mm, width_mm, thickness_mm}].
    notes : list[str]
        General drawing notes and tolerances.
    revision : str
        Drawing revision identifier.
    """
    part_id: str
    part_description: str
    views: List[View] = field(default_factory=list)
    bill_of_materials: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    revision: str = "A"


# ---------------------------------------------------------------------------
# Panel drawing generator
# ---------------------------------------------------------------------------

def panel_shop_drawing(
    part_id: str,
    length_mm: float,
    width_mm: float,
    thickness_mm: float = 19.0,
    *,
    description: str = "",
    holes: Optional[List[Dict[str, Any]]] = None,
    edge_banding: Optional[Dict[str, str]] = None,
    grain_direction: str = "length",
    include_section: bool = False,
) -> ShopDrawing:
    """Generate a shop drawing for a flat panel.

    Produces:
    - Front view: panel outline with dimensions.
    - Side view: thickness profile.
    - Section view (optional): cross-section showing edge and thickness.
    - Hole annotations from bore-pattern data.

    Args:
        part_id:         Part identifier.
        length_mm:       Panel long dimension.
        width_mm:        Panel short dimension.
        thickness_mm:    Panel thickness (default 19 mm = 3/4").
        description:     Human-readable label.
        holes:           List of hole dicts:
                         [{x, y, diameter_mm, depth_mm, kind, label}]
                         as returned by bore_pattern_to_dict().
        edge_banding:    Which edges are banded:
                         {'top': 'pvc_white', 'bottom': 'none', ...}
                         Keys: 'top', 'bottom', 'left', 'right'.
        grain_direction: 'length' | 'width' | 'none' (shown as arrow).
        include_section: Whether to include a cross-section view.

    Returns:
        :class:`ShopDrawing`.

    References:
        AWI (2014) §11; KCMA (2021) §5.
    """
    if length_mm <= 0 or width_mm <= 0 or thickness_mm <= 0:
        raise ValueError("Panel dimensions must be positive")

    desc = description or f"Panel {part_id} — {length_mm:.0f}×{width_mm:.0f}×{thickness_mm:.0f} mm"
    drawing = ShopDrawing(
        part_id=part_id,
        part_description=desc,
        notes=[
            f"Material: {thickness_mm:.1f} mm panel",
            f"Grain direction: {grain_direction}",
            "All dimensions in mm. Tolerances: ±0.5 mm unless noted.",
            "Ref: AWI Quality Standards 9th ed. §11.",
        ],
    )

    # ----------------------------------------------------------------
    # Front view: full panel face
    # ----------------------------------------------------------------
    front = View(name="front", origin_x=0.0, origin_y=0.0)

    # Outline rectangle
    front.lines.extend([
        Line(0, 0, length_mm, 0, layer="visible"),
        Line(length_mm, 0, length_mm, width_mm, layer="visible"),
        Line(length_mm, width_mm, 0, width_mm, layer="visible"),
        Line(0, width_mm, 0, 0, layer="visible"),
    ])

    # Grain direction arrow (along length or width)
    arrow_x = length_mm / 2.0
    arrow_y = width_mm / 2.0
    if grain_direction == "length":
        front.lines.extend([
            Line(arrow_x - 50, arrow_y, arrow_x + 50, arrow_y, layer="centre", label="grain"),
            # Arrow heads
            Line(arrow_x + 50, arrow_y, arrow_x + 40, arrow_y + 8, layer="centre"),
            Line(arrow_x + 50, arrow_y, arrow_x + 40, arrow_y - 8, layer="centre"),
        ])
    elif grain_direction == "width":
        front.lines.extend([
            Line(arrow_x, arrow_y - 50, arrow_x, arrow_y + 50, layer="centre", label="grain"),
            Line(arrow_x, arrow_y + 50, arrow_x - 8, arrow_y + 40, layer="centre"),
            Line(arrow_x, arrow_y + 50, arrow_x + 8, arrow_y + 40, layer="centre"),
        ])

    # Dimensions: length along bottom, width on right
    front.dimensions.extend([
        Dimension(
            x1=0, y1=-20.0, x2=length_mm, y2=-20.0,
            value_mm=length_mm,
            text=f"{length_mm:.0f}",
            direction="horizontal",
        ),
        Dimension(
            x1=length_mm + 20, y1=0, x2=length_mm + 20, y2=width_mm,
            value_mm=width_mm,
            text=f"{width_mm:.0f}",
            direction="vertical",
        ),
    ])

    # Edge banding indicators: bold line on each banded edge
    eb = edge_banding or {}
    if eb.get("bottom", "none") not in ("none", ""):
        front.lines.append(
            Line(0, -5, length_mm, -5, layer="visible", label=f"EB: {eb['bottom']}")
        )
    if eb.get("top", "none") not in ("none", ""):
        front.lines.append(
            Line(0, width_mm + 5, length_mm, width_mm + 5, layer="visible", label=f"EB: {eb['top']}")
        )
    if eb.get("left", "none") not in ("none", ""):
        front.lines.append(
            Line(-5, 0, -5, width_mm, layer="visible", label=f"EB: {eb['left']}")
        )
    if eb.get("right", "none") not in ("none", ""):
        front.lines.append(
            Line(length_mm + 5, 0, length_mm + 5, width_mm, layer="visible", label=f"EB: {eb['right']}")
        )

    # Bore holes
    for hole_data in (holes or []):
        front.holes.append(HoleAnnotation(
            cx=float(hole_data.get("x", 0.0)),
            cy=float(hole_data.get("y", 0.0)),
            diameter_mm=float(hole_data.get("diameter_mm", 5.0)),
            depth_mm=float(hole_data.get("depth_mm", 11.0)),
            label=str(hole_data.get("label", "")),
            kind=str(hole_data.get("kind", "drill")),
        ))

    drawing.views.append(front)

    # ----------------------------------------------------------------
    # Side view: thickness cross-section
    # ----------------------------------------------------------------
    side_offset_x = length_mm + 80  # offset to right of front view
    side = View(name="side", origin_x=side_offset_x, origin_y=0.0)
    side.lines.extend([
        Line(0, 0, thickness_mm, 0, layer="visible"),
        Line(thickness_mm, 0, thickness_mm, width_mm, layer="visible"),
        Line(thickness_mm, width_mm, 0, width_mm, layer="visible"),
        Line(0, width_mm, 0, 0, layer="visible"),
    ])
    side.dimensions.append(Dimension(
        x1=0, y1=-20.0, x2=thickness_mm, y2=-20.0,
        value_mm=thickness_mm,
        text=f"{thickness_mm:.1f}",
        direction="horizontal",
    ))
    drawing.views.append(side)

    # ----------------------------------------------------------------
    # Section view (optional): face of the edge, showing thickness
    # ----------------------------------------------------------------
    if include_section:
        sec_offset_y = width_mm + 60
        section = View(name="section", origin_x=0.0, origin_y=sec_offset_y)
        # Show one layer (simplified — no internal layup)
        section.lines.extend([
            Line(0, 0, length_mm, 0, layer="visible"),
            Line(length_mm, 0, length_mm, thickness_mm, layer="visible"),
            Line(length_mm, thickness_mm, 0, thickness_mm, layer="visible"),
            Line(0, thickness_mm, 0, 0, layer="visible"),
        ])
        section.dimensions.append(Dimension(
            x1=length_mm + 20, y1=0, x2=length_mm + 20, y2=thickness_mm,
            value_mm=thickness_mm,
            text=f"t={thickness_mm:.1f}",
            direction="vertical",
        ))
        section.notes.append("Cross-section A-A: edge profile")
        drawing.views.append(section)

    # BOM entry
    drawing.bill_of_materials.append({
        "part_id": part_id,
        "description": desc,
        "length_mm": length_mm,
        "width_mm": width_mm,
        "thickness_mm": thickness_mm,
        "grain_direction": grain_direction,
        "qty": 1,
        "edge_banding": edge_banding or {},
    })

    return drawing


def cabinet_shop_drawing(
    cabinet_id: str,
    cabinet_type: str,
    width_mm: float,
    height_mm: float,
    depth_mm: float,
    *,
    material: str = 'birch_ply_3/4"',
    door_count: int = 1,
    shelf_count: int = 1,
    description: str = "",
) -> ShopDrawing:
    """Generate a shop drawing for a complete cabinet assembly.

    Produces:
    - Front elevation: cabinet face with door and drawer outlines.
    - Side elevation: depth profile.
    - Plan view: top-down layout.
    - BOM: all panel parts.

    Args:
        cabinet_id:   Cabinet identifier (e.g. 'B1').
        cabinet_type: 'base' | 'wall' | 'tall'.
        width_mm:     Overall cabinet width.
        height_mm:    Overall cabinet height.
        depth_mm:     Overall cabinet depth.
        material:     Sheet material key.
        door_count:   Number of doors.
        shelf_count:  Number of adjustable shelves.
        description:  Human-readable label.

    Returns:
        :class:`ShopDrawing`.

    References:
        AWI (2014) §11; KCMA (2021) §5.
    """
    if width_mm <= 0 or height_mm <= 0 or depth_mm <= 0:
        raise ValueError("Cabinet dimensions must be positive")
    if cabinet_type not in ("base", "wall", "tall"):
        raise ValueError(
            f"cabinet_type must be 'base', 'wall', or 'tall', got '{cabinet_type}'"
        )

    t = 19.05   # 3/4" panel thickness
    desc = description or (
        f"{cabinet_type.title()} cabinet {cabinet_id} — "
        f"{width_mm:.0f}W × {height_mm:.0f}H × {depth_mm:.0f}D mm"
    )

    drawing = ShopDrawing(
        part_id=cabinet_id,
        part_description=desc,
        notes=[
            f"Cabinet type: {cabinet_type}",
            f"Material: {material}",
            f"Panel thickness: {t:.2f} mm (3/4\")",
            "32 mm system hardware. All dimensions in mm.",
            "Tolerances: ±0.5 mm. Ref: AWI §11; KCMA 2021.",
        ],
    )

    # ----------------------------------------------------------------
    # Front elevation
    # ----------------------------------------------------------------
    front = View(name="front_elevation")

    # Cabinet outline
    front.lines.extend([
        Line(0, 0, width_mm, 0),
        Line(width_mm, 0, width_mm, height_mm),
        Line(width_mm, height_mm, 0, height_mm),
        Line(0, height_mm, 0, 0),
    ])

    # Toe kick for base cabinets
    if cabinet_type == "base":
        front.lines.extend([
            Line(t, 0, t, 96.0, layer="hidden"),       # left toe kick
            Line(width_mm - t, 0, width_mm - t, 96.0, layer="hidden"),  # right toe kick
        ])

    # Door outlines (evenly spaced)
    door_w = (width_mm - 2.0 * t) / max(door_count, 1)
    door_clearance = 3.0    # gap between doors
    for d in range(door_count):
        dx_left  = t + d * door_w + door_clearance / 2.0
        dx_right = t + (d + 1) * door_w - door_clearance / 2.0
        dy_bottom = (96.0 if cabinet_type == "base" else t)
        dy_top = height_mm - t
        front.lines.extend([
            Line(dx_left, dy_bottom, dx_right, dy_bottom, layer="visible"),
            Line(dx_right, dy_bottom, dx_right, dy_top, layer="visible"),
            Line(dx_right, dy_top, dx_left, dy_top, layer="visible"),
            Line(dx_left, dy_top, dx_left, dy_bottom, layer="visible"),
        ])
        # Door handle stub
        mid_y = (dy_top + dy_bottom) / 2.0
        front.lines.append(
            Line(dx_right - 50.0, mid_y, dx_right - 25.0, mid_y, layer="visible", label="handle")
        )

    # Shelf line indicators (hidden lines at equal spacing)
    if shelf_count > 0:
        dy_bottom_inner = (96.0 if cabinet_type == "base" else t)
        inner_h = height_mm - t - dy_bottom_inner
        for s in range(1, shelf_count + 1):
            shelf_y = dy_bottom_inner + inner_h * s / (shelf_count + 1)
            front.lines.append(
                Line(t, shelf_y, width_mm - t, shelf_y, layer="hidden", label=f"shelf {s}")
            )

    # Dimensions
    front.dimensions.extend([
        Dimension(0, -25, width_mm, -25, width_mm, text=f"{width_mm:.0f}", direction="horizontal"),
        Dimension(width_mm + 25, 0, width_mm + 25, height_mm, height_mm, text=f"{height_mm:.0f}", direction="vertical"),
    ])
    drawing.views.append(front)

    # ----------------------------------------------------------------
    # Side elevation
    # ----------------------------------------------------------------
    side_offset = width_mm + 60
    side = View(name="side_elevation", origin_x=side_offset)
    side.lines.extend([
        Line(0, 0, depth_mm, 0),
        Line(depth_mm, 0, depth_mm, height_mm),
        Line(depth_mm, height_mm, 0, height_mm),
        Line(0, height_mm, 0, 0),
    ])
    side.dimensions.extend([
        Dimension(0, -25, depth_mm, -25, depth_mm, text=f"{depth_mm:.0f}", direction="horizontal"),
    ])
    drawing.views.append(side)

    # ----------------------------------------------------------------
    # Plan view (top looking down)
    # ----------------------------------------------------------------
    plan_offset_y = height_mm + 60
    plan = View(name="plan_view", origin_y=plan_offset_y)
    plan.lines.extend([
        Line(0, 0, width_mm, 0),
        Line(width_mm, 0, width_mm, depth_mm),
        Line(width_mm, depth_mm, 0, depth_mm),
        Line(0, depth_mm, 0, 0),
        # Side panels (shown in plan)
        Line(t, t, t, depth_mm - t, layer="visible"),
        Line(width_mm - t, t, width_mm - t, depth_mm - t, layer="visible"),
        # Back panel
        Line(t, depth_mm - t, width_mm - t, depth_mm - t, layer="visible"),
    ])
    drawing.views.append(plan)

    # ----------------------------------------------------------------
    # BOM
    # ----------------------------------------------------------------
    inner_w = width_mm - 2.0 * t
    bom_parts = [
        {"part_id": f"{cabinet_id}_side",   "description": "Side panel",   "qty": 2,
         "length_mm": height_mm,  "width_mm": depth_mm,  "thickness_mm": t},
        {"part_id": f"{cabinet_id}_top",    "description": "Top panel",    "qty": 1,
         "length_mm": inner_w,    "width_mm": depth_mm,  "thickness_mm": t},
        {"part_id": f"{cabinet_id}_bottom", "description": "Bottom panel", "qty": 1,
         "length_mm": inner_w,    "width_mm": depth_mm,  "thickness_mm": t},
        {"part_id": f"{cabinet_id}_back",   "description": "Back panel",   "qty": 1,
         "length_mm": inner_w,    "width_mm": height_mm - 2.0 * t, "thickness_mm": 6.35},
    ]
    if shelf_count > 0:
        bom_parts.append({
            "part_id": f"{cabinet_id}_shelf",
            "description": "Adjustable shelf",
            "qty": shelf_count,
            "length_mm": inner_w,
            "width_mm": depth_mm - 25.0,
            "thickness_mm": t,
        })
    if door_count > 0:
        bom_parts.append({
            "part_id": f"{cabinet_id}_door",
            "description": "Door panel",
            "qty": door_count,
            "length_mm": height_mm,
            "width_mm": width_mm / door_count,
            "thickness_mm": t,
        })

    for bp in bom_parts:
        bp["material"] = material
        drawing.bill_of_materials.append(bp)

    return drawing


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def shop_drawing_to_dict(drawing: ShopDrawing) -> Dict[str, Any]:
    """Serialise a :class:`ShopDrawing` to a JSON-safe dict."""
    return {
        "part_id": drawing.part_id,
        "part_description": drawing.part_description,
        "revision": drawing.revision,
        "notes": drawing.notes,
        "bill_of_materials": drawing.bill_of_materials,
        "views": [
            {
                "name": v.name,
                "origin": {"x": v.origin_x, "y": v.origin_y},
                "scale": v.scale,
                "notes": v.notes,
                "lines": [
                    {
                        "x1": round(l.x1, 3), "y1": round(l.y1, 3),
                        "x2": round(l.x2, 3), "y2": round(l.y2, 3),
                        "layer": l.layer, "label": l.label,
                    }
                    for l in v.lines
                ],
                "arcs": [
                    {
                        "cx": round(a.cx, 3), "cy": round(a.cy, 3),
                        "radius": round(a.radius, 3),
                        "start_deg": a.start_deg, "end_deg": a.end_deg,
                        "layer": a.layer, "label": a.label,
                    }
                    for a in v.arcs
                ],
                "dimensions": [
                    {
                        "x1": round(d.x1, 3), "y1": round(d.y1, 3),
                        "x2": round(d.x2, 3), "y2": round(d.y2, 3),
                        "value_mm": d.value_mm,
                        "text": d.text,
                        "direction": d.direction,
                    }
                    for d in v.dimensions
                ],
                "holes": [
                    {
                        "cx": round(h.cx, 3), "cy": round(h.cy, 3),
                        "diameter_mm": h.diameter_mm,
                        "depth_mm": h.depth_mm,
                        "kind": h.kind,
                        "label": h.label,
                    }
                    for h in v.holes
                ],
            }
            for v in drawing.views
        ],
    }
