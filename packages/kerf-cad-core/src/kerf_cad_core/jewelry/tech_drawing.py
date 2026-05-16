"""
kerf_cad_core.jewelry.tech_drawing
====================================

Setter's spec sheet — multi-view technical drawing of a jewelry piece.

Given a *piece description dict* and a list of requested view names, produces a
Drawing dict containing:

  • Per-view projection data (polylines via Make2D)
  • Jewelry-specific annotations:
      - Stone callouts: each gemstone → a leader entry labelled
        "<carat> ct <cut_abbr> Ø<diameter> mm" (e.g. "1.00 ct RBC Ø6.50 mm")
      - Seat-depth dimensions: recess depth from the setting face
      - Prong-height dimensions: prong-tip to bezel-top distance
      - Ring-size badge in the title-block corner
      - Hallmark / maker-mark position indicator
      - Total-carat label
      - Metal-weight estimate label
  • Sheet border / title-block layout (A4 landscape by default)
  • DXF and SVG export serialisation helpers

Public API
----------
jewelry_tech_drawing(piece, views, *, sheet, scale) -> Drawing
    Main entry point.  Pure Python + NumPy, no OCC required.  Never raises.

Drawing (dict)
    Top-level output.  Keys: ``views``, ``annotations``, ``sheet``, ``meta``.

dxf_export(drawing) -> str
    Serialise a Drawing to a minimal DXF R12 string.

svg_export(drawing) -> str
    Serialise a Drawing to an SVG 1.1 string.

LLM tools registered (kerf_chat gated)
---------------------------------------
  jewelry_tech_drawing_generate   — generate drawing dict (read)
  jewelry_tech_drawing_export_dxf — export drawing as DXF text (read)
  jewelry_tech_drawing_export_svg — export drawing as SVG text (read)

Never raises — all public functions catch exceptions internally.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Make2D import (soft-dep so tests run without full stack)
# ---------------------------------------------------------------------------
try:
    from kerf_cad_core.geom.make2d import (  # type: ignore[import]
        Make2DInput,
        ViewParams,
        make2d,
        standard_views,
    )
    _MAKE2D_AVAILABLE = True
except Exception:
    _MAKE2D_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default A4 landscape sheet, mm
_A4_WIDTH_MM: float = 297.0
_A4_HEIGHT_MM: float = 210.0
_MARGIN_MM: float = 10.0
_TITLE_BLOCK_HEIGHT_MM: float = 20.0

# Standard view names accepted
_VALID_VIEWS = {"top", "front", "side", "iso"}

# Abbreviation map for common gemstone cuts (for callout labels)
_CUT_ABBR: Dict[str, str] = {
    "round_brilliant": "RBC",
    "princess":        "PRC",
    "oval":            "OVL",
    "emerald":         "EMR",
    "marquise":        "MQS",
    "pear":            "PER",
    "cushion":         "CUS",
    "radiant":         "RAD",
    "asscher":         "ASS",
    "trillion":        "TRL",
    "heart":           "HRT",
    "baguette":        "BAG",
    "briolette":       "BRL",
    "rose_cut":        "RSC",
    "cabochon":        "CAB",
}

# Default dummy ring mesh (flat disc) used when no mesh provided
_DUMMY_VERTS = np.array([
    [0.0, 0.0, 0.0],
    [5.0, 0.0, 0.0],
    [5.0, 5.0, 0.0],
    [0.0, 5.0, 0.0],
], dtype=float)
_DUMMY_TRIS = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)

# ---------------------------------------------------------------------------
# Piece description schema (dict, not a strict dataclass — permissive input)
# ---------------------------------------------------------------------------
#
# piece = {
#   "metal":           str,              # e.g. "18k_yellow"
#   "ring_size":       float | None,     # US size (None for non-rings)
#   "ring_size_system": str | None,      # "US" | "UK" | "EU" | "JP"
#   "volume_mm3":      float | None,     # metal volume for weight estimate
#   "hallmark_position": [x, y] | None, # 2D hint position in sheet coords
#   "maker_mark":      str | None,       # e.g. "KF"
#   "gemstones": [
#     {
#       "cut":           str,            # "round_brilliant" etc.
#       "diameter_mm":   float,
#       "carat":         float,
#       "position":      [x, y, z],      # 3D centre in piece coords
#       "seat_depth_mm": float | None,   # recess from setting face
#       "prong_height_mm": float | None, # prong tip above bezel
#       "label":         str | None,     # override auto label
#     },
#     ...
#   ],
#   "mesh": {                            # optional tessellation
#     "vertices":  [[x,y,z], ...],
#     "triangles": [[i,j,k], ...],
#   },
# }

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _stone_callout_label(stone: Dict[str, Any]) -> str:
    """Build the callout label string for a single stone."""
    carat = float(stone.get("carat", 0.0))
    cut = stone.get("cut", "")
    abbr = _CUT_ABBR.get(cut, cut.upper()[:3]) if cut else "GEM"
    diam = float(stone.get("diameter_mm", 0.0))
    return f"{carat:.2f} ct {abbr} Ø{diam:.2f} mm"


def _total_carats(gemstones: List[Dict[str, Any]]) -> float:
    return sum(float(g.get("carat", 0.0)) for g in gemstones)


def _metal_weight_estimate(piece: Dict[str, Any]) -> Optional[float]:
    """Return estimated metal weight in grams, or None if data missing."""
    volume = piece.get("volume_mm3")
    metal = piece.get("metal", "")
    if volume is None or not metal:
        return None
    try:
        from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3  # type: ignore[import]
        density = METAL_DENSITY_G_CM3.get(metal)
        if density is None:
            return None
        return float(volume) * density / 1000.0  # mm³ → cm³ → g
    except Exception:
        return None


def _view_params_for_name(name: str) -> "ViewParams":
    """Return ViewParams for a named view."""
    views = standard_views() if _MAKE2D_AVAILABLE else {}
    mapping = {
        "top":   views.get("top"),
        "front": views.get("front"),
        "side":  views.get("right"),
        "iso":   views.get("iso"),
    }
    vp = mapping.get(name)
    if vp is None:
        # Fallback to simple defaults (if make2d not available)
        if name == "top":
            vp = _FallbackViewParams([0.0, 0.0, -1.0])
        elif name == "front":
            vp = _FallbackViewParams([0.0, -1.0, 0.0])
        elif name == "side":
            vp = _FallbackViewParams([1.0, 0.0, 0.0])
        else:
            vp = _FallbackViewParams([1.0, -1.0, -1.0])
    return vp


class _FallbackViewParams:
    """Minimal stub when make2d not available."""
    def __init__(self, direction: List[float]):
        self.direction = direction


def _project_stone_to_view(
    stone_pos: List[float],
    view_name: str,
) -> Tuple[float, float]:
    """Simple orthographic projection of a 3D stone position to 2D view coords."""
    x, y, z = float(stone_pos[0]), float(stone_pos[1]), float(stone_pos[2])
    if view_name == "top":
        return x, y
    elif view_name == "front":
        return x, z
    elif view_name == "side":
        return y, z
    else:  # iso — rough 2D projection
        return x - y * 0.5, z + y * 0.5


def _run_make2d_for_view(
    piece: Dict[str, Any],
    view_name: str,
) -> Tuple[List, List]:
    """Run Make2D for a view; return (visible_polylines, hidden_polylines)."""
    if not _MAKE2D_AVAILABLE:
        return [], []
    try:
        mesh_data = piece.get("mesh")
        if mesh_data:
            verts = np.array(mesh_data["vertices"], dtype=float)
            tris = np.array(mesh_data["triangles"], dtype=int)
        else:
            verts = _DUMMY_VERTS.copy()
            tris = _DUMMY_TRIS.copy()

        mesh_input = Make2DInput(vertices=verts, triangles=tris)
        ok, _ = mesh_input.is_valid()
        if not ok:
            return [], []

        vp = _view_params_for_name(view_name)
        result = make2d(mesh_input, vp)
        return result.visible, result.hidden
    except Exception:
        return [], []


def _sheet_layout(
    view_names: List[str],
    sheet_width: float,
    sheet_height: float,
    margin: float,
    title_height: float,
) -> Dict[str, Dict[str, float]]:
    """Compute per-view bounding boxes on the sheet.

    Divides the drawable area (minus margin and title block) into a grid.
    Returns a dict: view_name → {"x", "y", "w", "h"} in mm.
    """
    draw_x0 = margin
    draw_y0 = margin + title_height
    draw_w = sheet_width - 2 * margin
    draw_h = sheet_height - 2 * margin - title_height

    n = len(view_names) if view_names else 1
    # 4 views → 2×2; 3 views → 2×2 (last slot empty); 2 → 1×2; 1 → 1×1
    if n == 1:
        cols, rows = 1, 1
    elif n == 2:
        cols, rows = 2, 1
    else:
        cols, rows = 2, 2

    cell_w = draw_w / cols
    cell_h = draw_h / rows

    layout: Dict[str, Dict[str, float]] = {}
    for idx, name in enumerate(view_names[:4]):
        col = idx % cols
        row = idx // cols
        layout[name] = {
            "x": draw_x0 + col * cell_w,
            "y": draw_y0 + row * cell_h,
            "w": cell_w,
            "h": cell_h,
        }
    return layout


def _annotation_in_bounds(
    ax: float, ay: float,
    cell: Dict[str, float],
) -> bool:
    """Return True if annotation point (ax, ay) is within the cell bounds."""
    return (
        cell["x"] <= ax <= cell["x"] + cell["w"]
        and cell["y"] <= ay <= cell["y"] + cell["h"]
    )


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def jewelry_tech_drawing(
    piece: Dict[str, Any],
    views: Optional[Sequence[str]] = None,
    *,
    sheet_width_mm: float = _A4_WIDTH_MM,
    sheet_height_mm: float = _A4_HEIGHT_MM,
    margin_mm: float = _MARGIN_MM,
    title_block_height_mm: float = _TITLE_BLOCK_HEIGHT_MM,
    scale: float = 1.0,
) -> Dict[str, Any]:
    """Generate a multi-view setter's tech drawing for a jewelry piece.

    Parameters
    ----------
    piece : dict
        Piece description (see module docstring for schema).
    views : sequence of str, optional
        View names to generate.  Subset of ``{"top", "front", "side", "iso"}``.
        Defaults to all four.
    sheet_width_mm, sheet_height_mm : float
        Sheet dimensions in mm (default A4 landscape).
    margin_mm : float
        Sheet margin in mm (default 10).
    title_block_height_mm : float
        Height of the title block band at bottom of sheet (default 20).
    scale : float
        Drawing scale factor applied to geometry (default 1.0 = 1:1).

    Returns
    -------
    dict
        Drawing structure::

            {
              "ok": True,
              "views": {
                "<view_name>": {
                  "visible":  [polyline, ...],  # each polyline = [[x,y], ...]
                  "hidden":   [polyline, ...],
                  "bbox":     {"x", "y", "w", "h"},
                  "annotations": [...],          # view-local annotations
                },
                ...
              },
              "annotations": {                   # sheet-level annotations
                "stone_callouts": [...],
                "seat_depth_dims": [...],
                "prong_height_dims": [...],
                "ring_size_badge": {...} | None,
                "hallmark_indicator": {...} | None,
                "total_carat_label": {...},
                "metal_weight_label": {...} | None,
              },
              "sheet": {
                "width_mm": float,
                "height_mm": float,
                "margin_mm": float,
                "title_block_height_mm": float,
                "border": [[x,y], ...],           # sheet border polyline
                "title_block": [[x,y], ...],      # title-block border
              },
              "meta": {
                "drawing_id": str,
                "piece_metal": str | None,
                "scale": float,
                "view_names": [str, ...],
              },
            }

    Never raises.
    """
    try:
        return _build_drawing(
            piece,
            views,
            sheet_width_mm=sheet_width_mm,
            sheet_height_mm=sheet_height_mm,
            margin_mm=margin_mm,
            title_block_height_mm=title_block_height_mm,
            scale=scale,
        )
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _build_drawing(
    piece: Dict[str, Any],
    views: Optional[Sequence[str]],
    *,
    sheet_width_mm: float,
    sheet_height_mm: float,
    margin_mm: float,
    title_block_height_mm: float,
    scale: float,
) -> Dict[str, Any]:
    if not isinstance(piece, dict):
        raise ValueError("piece must be a dict")
    if scale <= 0:
        raise ValueError(f"scale must be positive; got {scale!r}")

    # Normalise view list
    if views is None:
        view_names: List[str] = ["top", "front", "side", "iso"]
    else:
        view_names = [v for v in views if v in _VALID_VIEWS]
        unknown = [v for v in views if v not in _VALID_VIEWS]
        if unknown:
            raise ValueError(
                f"Unknown view(s): {unknown}. "
                f"Valid choices: {sorted(_VALID_VIEWS)}"
            )
        if not view_names:
            raise ValueError("No valid views specified.")

    gemstones: List[Dict[str, Any]] = piece.get("gemstones") or []

    # Sheet border
    w, h, m, tb = sheet_width_mm, sheet_height_mm, margin_mm, title_block_height_mm
    sheet_border = [
        [m, m], [w - m, m], [w - m, h - m], [m, h - m], [m, m]
    ]
    title_block_border = [
        [m, m], [w - m, m], [w - m, m + tb], [m, m + tb], [m, m]
    ]

    # Sheet layout
    layout = _sheet_layout(view_names, w, h, m, tb)

    # Per-view data
    views_out: Dict[str, Any] = {}
    for vname in view_names:
        visible, hidden = _run_make2d_for_view(piece, vname)

        # Scale polylines and offset to cell origin
        cell = layout[vname]
        cx = cell["x"] + cell["w"] * 0.5
        cy = cell["y"] + cell["h"] * 0.5

        def _offset_poly(poly: List) -> List[List[float]]:
            return [[cx + pt[0] * scale, cy + pt[1] * scale] for pt in poly]

        vis_scaled = [_offset_poly(p) for p in visible]
        hid_scaled = [_offset_poly(p) for p in hidden]

        # Per-view annotations (stone callout leaders)
        view_annots: List[Dict[str, Any]] = []
        for idx, stone in enumerate(gemstones):
            pos = stone.get("position") or [0.0, 0.0, 0.0]
            sx, sy = _project_stone_to_view(pos, vname)
            leader_x = cx + sx * scale
            leader_y = cy + sy * scale
            label = stone.get("label") or _stone_callout_label(stone)
            # Leader endpoint (offset by a fixed amount for readability)
            leader_tip_x = leader_x + 8.0
            leader_tip_y = leader_y + 8.0
            view_annots.append({
                "type":          "stone_callout_leader",
                "stone_index":   idx,
                "origin":        [leader_x, leader_y],
                "tip":           [leader_tip_x, leader_tip_y],
                "label":         label,
            })

        views_out[vname] = {
            "visible":     vis_scaled,
            "hidden":      hid_scaled,
            "bbox":        cell,
            "annotations": view_annots,
        }

    # Sheet-level annotations
    # --- Stone callouts (consolidated list, using "front" view projection or first view)
    primary_view = "front" if "front" in view_names else view_names[0]
    primary_cell = layout[primary_view]
    pcx = primary_cell["x"] + primary_cell["w"] * 0.5
    pcy = primary_cell["y"] + primary_cell["h"] * 0.5

    stone_callouts: List[Dict[str, Any]] = []
    for idx, stone in enumerate(gemstones):
        pos = stone.get("position") or [0.0, 0.0, 0.0]
        sx, sy = _project_stone_to_view(pos, primary_view)
        lx = pcx + sx * scale
        ly = pcy + sy * scale
        tip_x = lx + 10.0 + idx * 2.0
        tip_y = ly + 10.0 + idx * 2.0
        label = stone.get("label") or _stone_callout_label(stone)
        stone_callouts.append({
            "type":        "stone_callout",
            "index":       idx,
            "label":       label,
            "origin_2d":   [lx, ly],
            "leader_tip":  [tip_x, tip_y],
            "view":        primary_view,
        })

    # --- Seat-depth dimensions
    seat_depth_dims: List[Dict[str, Any]] = []
    for idx, stone in enumerate(gemstones):
        depth = stone.get("seat_depth_mm")
        if depth is not None:
            pos = stone.get("position") or [0.0, 0.0, 0.0]
            sx, sy = _project_stone_to_view(pos, primary_view)
            seat_depth_dims.append({
                "type":          "seat_depth_dim",
                "stone_index":   idx,
                "seat_depth_mm": float(depth),
                "position_2d":   [pcx + sx * scale + 12.0, pcy + sy * scale],
                "view":          primary_view,
                "label":         f"seat: {float(depth):.2f} mm",
            })

    # --- Prong-height dimensions
    prong_height_dims: List[Dict[str, Any]] = []
    for idx, stone in enumerate(gemstones):
        ph = stone.get("prong_height_mm")
        if ph is not None:
            pos = stone.get("position") or [0.0, 0.0, 0.0]
            sx, sy = _project_stone_to_view(pos, primary_view)
            prong_height_dims.append({
                "type":           "prong_height_dim",
                "stone_index":    idx,
                "prong_height_mm": float(ph),
                "position_2d":    [pcx + sx * scale - 12.0, pcy + sy * scale],
                "view":           primary_view,
                "label":          f"prong: {float(ph):.2f} mm",
            })

    # --- Ring-size badge
    ring_size = piece.get("ring_size")
    ring_system = piece.get("ring_size_system", "US")
    ring_size_badge: Optional[Dict[str, Any]] = None
    if ring_size is not None:
        badge_x = w - m - 35.0
        badge_y = m + 5.0
        ring_size_badge = {
            "type":    "ring_size_badge",
            "size":    ring_size,
            "system":  ring_system or "US",
            "label":   f"Ring Size {ring_size} ({ring_system or 'US'})",
            "position_2d": [badge_x, badge_y],
        }

    # --- Hallmark / maker-mark indicator
    hallmark_pos = piece.get("hallmark_position")
    maker_mark = piece.get("maker_mark")
    hallmark_indicator: Optional[Dict[str, Any]] = None
    if hallmark_pos or maker_mark:
        hx = float(hallmark_pos[0]) if hallmark_pos else m + 10.0
        hy = float(hallmark_pos[1]) if hallmark_pos else m + 5.0
        hallmark_indicator = {
            "type":        "hallmark_indicator",
            "maker_mark":  maker_mark or "",
            "position_2d": [hx, hy],
            "label":       f"HM: {maker_mark or ''}",
        }

    # --- Total-carat label
    total_ct = _total_carats(gemstones)
    total_carat_label: Dict[str, Any] = {
        "type":    "total_carat_label",
        "value":   total_ct,
        "label":   f"Total: {total_ct:.2f} ct",
        "position_2d": [m + 5.0, m + 5.0],
    }

    # --- Metal-weight estimate label
    weight_g = _metal_weight_estimate(piece)
    metal_weight_label: Optional[Dict[str, Any]] = None
    if weight_g is not None:
        metal_weight_label = {
            "type":     "metal_weight_label",
            "weight_g": round(weight_g, 4),
            "label":    f"Metal: {weight_g:.2f} g",
            "position_2d": [m + 5.0, m + 10.0],
        }

    return {
        "ok": True,
        "views": views_out,
        "annotations": {
            "stone_callouts":      stone_callouts,
            "seat_depth_dims":     seat_depth_dims,
            "prong_height_dims":   prong_height_dims,
            "ring_size_badge":     ring_size_badge,
            "hallmark_indicator":  hallmark_indicator,
            "total_carat_label":   total_carat_label,
            "metal_weight_label":  metal_weight_label,
        },
        "sheet": {
            "width_mm":              sheet_width_mm,
            "height_mm":             sheet_height_mm,
            "margin_mm":             margin_mm,
            "title_block_height_mm": title_block_height_mm,
            "border":                sheet_border,
            "title_block":           title_block_border,
        },
        "meta": {
            "drawing_id": str(uuid.uuid4()),
            "piece_metal": piece.get("metal"),
            "scale":       scale,
            "view_names":  view_names,
        },
    }


# ---------------------------------------------------------------------------
# DXF export
# ---------------------------------------------------------------------------

_DXF_HEADER = """\
0
SECTION
2
HEADER
9
$ACADVER
1
AC1009
0
ENDSEC
0
SECTION
2
ENTITIES
"""
_DXF_FOOTER = """\
0
ENDSEC
0
EOF
"""


def _dxf_polyline(pts: List[List[float]], layer: str = "0") -> str:
    """Return DXF LINE entities for a sequence of points."""
    lines = []
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        lines.append(
            f"0\nLINE\n8\n{layer}\n"
            f"10\n{x0:.6f}\n20\n{y0:.6f}\n30\n0.0\n"
            f"11\n{x1:.6f}\n21\n{y1:.6f}\n31\n0.0\n"
        )
    return "".join(lines)


def _dxf_text(x: float, y: float, text: str, height: float = 2.5, layer: str = "ANNOT") -> str:
    return (
        f"0\nTEXT\n8\n{layer}\n"
        f"10\n{x:.6f}\n20\n{y:.6f}\n30\n0.0\n"
        f"40\n{height:.3f}\n"
        f"1\n{text}\n"
    )


def dxf_export(drawing: Dict[str, Any]) -> str:
    """Serialise a Drawing dict to a minimal DXF R12 string.

    Returns an empty string if drawing is invalid (never raises).
    """
    try:
        return _dxf_export_inner(drawing)
    except Exception:
        return ""


def _dxf_export_inner(drawing: Dict[str, Any]) -> str:
    if not drawing.get("ok"):
        return ""

    entities: List[str] = []

    # Sheet border
    sheet = drawing.get("sheet", {})
    border = sheet.get("border", [])
    if border:
        entities.append(_dxf_polyline(border, layer="BORDER"))

    title_block = sheet.get("title_block", [])
    if title_block:
        entities.append(_dxf_polyline(title_block, layer="BORDER"))

    # Views
    for view_name, view_data in drawing.get("views", {}).items():
        for poly in view_data.get("visible", []):
            entities.append(_dxf_polyline(poly, layer="VISIBLE"))
        for poly in view_data.get("hidden", []):
            entities.append(_dxf_polyline(poly, layer="HIDDEN"))
        # View label
        bbox = view_data.get("bbox", {})
        if bbox:
            vx = bbox.get("x", 0) + 2
            vy = bbox.get("y", 0) + 2
            entities.append(_dxf_text(vx, vy, view_name.upper(), height=3.0, layer="VIEWLABEL"))

    # Annotations
    annots = drawing.get("annotations", {})

    for callout in annots.get("stone_callouts", []):
        tip = callout.get("leader_tip", [0, 0])
        label = callout.get("label", "")
        entities.append(_dxf_text(tip[0], tip[1], label, layer="ANNOT"))
        origin = callout.get("origin_2d", [0, 0])
        entities.append(_dxf_polyline([origin, tip], layer="LEADER"))

    for dim in annots.get("seat_depth_dims", []):
        pos = dim.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], dim.get("label", ""), layer="DIM"))

    for dim in annots.get("prong_height_dims", []):
        pos = dim.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], dim.get("label", ""), layer="DIM"))

    badge = annots.get("ring_size_badge")
    if badge:
        pos = badge.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], badge.get("label", ""), layer="BADGE"))

    hm = annots.get("hallmark_indicator")
    if hm:
        pos = hm.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], hm.get("label", ""), layer="HALLMARK"))

    tcl = annots.get("total_carat_label", {})
    if tcl:
        pos = tcl.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], tcl.get("label", ""), layer="ANNOT"))

    mwl = annots.get("metal_weight_label")
    if mwl:
        pos = mwl.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], mwl.get("label", ""), layer="ANNOT"))

    return _DXF_HEADER + "".join(entities) + _DXF_FOOTER


# ---------------------------------------------------------------------------
# SVG export
# ---------------------------------------------------------------------------


def svg_export(drawing: Dict[str, Any]) -> str:
    """Serialise a Drawing dict to an SVG 1.1 string.

    Returns an empty string if drawing is invalid (never raises).
    """
    try:
        return _svg_export_inner(drawing)
    except Exception:
        return ""


def _svg_polyline_attr(pts: List[List[float]]) -> str:
    return " ".join(f"{p[0]:.3f},{p[1]:.3f}" for p in pts)


def _svg_export_inner(drawing: Dict[str, Any]) -> str:
    if not drawing.get("ok"):
        return ""

    sheet = drawing.get("sheet", {})
    sw = sheet.get("width_mm", _A4_WIDTH_MM)
    sh = sheet.get("height_mm", _A4_HEIGHT_MM)

    lines: List[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{sw}mm" height="{sh}mm" '
        f'viewBox="0 0 {sw} {sh}" '
        f'version="1.1">'
    )
    lines.append(
        '<defs><style>'
        '.visible{stroke:#000;stroke-width:0.3;fill:none}'
        '.hidden{stroke:#555;stroke-width:0.15;stroke-dasharray:2 1;fill:none}'
        '.border{stroke:#000;stroke-width:0.5;fill:none}'
        '.annot{font-family:sans-serif;font-size:2.5px;fill:#000}'
        '.dim{font-family:sans-serif;font-size:2px;fill:#333}'
        '.badge{font-family:sans-serif;font-size:2.8px;fill:#000;font-weight:bold}'
        '.leader{stroke:#000;stroke-width:0.2;fill:none}'
        '</style></defs>'
    )

    # Sheet border
    border = sheet.get("border", [])
    if border:
        pts_str = _svg_polyline_attr(border)
        lines.append(f'<polyline class="border" points="{pts_str}"/>')

    title_block = sheet.get("title_block", [])
    if title_block:
        pts_str = _svg_polyline_attr(title_block)
        lines.append(f'<polyline class="border" points="{pts_str}"/>')

    # Views
    for view_name, view_data in drawing.get("views", {}).items():
        bbox = view_data.get("bbox", {})
        bx = bbox.get("x", 0)
        by = bbox.get("y", 0)
        # View label
        lines.append(
            f'<text class="annot" x="{bx + 2:.1f}" y="{by + 5:.1f}">'
            f'{view_name.upper()}</text>'
        )

        for poly in view_data.get("visible", []):
            pts_str = _svg_polyline_attr(poly)
            if pts_str:
                lines.append(f'<polyline class="visible" points="{pts_str}"/>')
        for poly in view_data.get("hidden", []):
            pts_str = _svg_polyline_attr(poly)
            if pts_str:
                lines.append(f'<polyline class="hidden" points="{pts_str}"/>')

    # Annotations
    annots = drawing.get("annotations", {})

    for callout in annots.get("stone_callouts", []):
        origin = callout.get("origin_2d", [0, 0])
        tip = callout.get("leader_tip", [0, 0])
        label = callout.get("label", "")
        lines.append(
            f'<polyline class="leader" points="{origin[0]:.2f},{origin[1]:.2f} '
            f'{tip[0]:.2f},{tip[1]:.2f}"/>'
        )
        lines.append(
            f'<text class="annot" x="{tip[0]:.2f}" y="{tip[1] - 1:.2f}">'
            f'{_svg_escape(label)}</text>'
        )

    for dim in annots.get("seat_depth_dims", []):
        pos = dim.get("position_2d", [0, 0])
        label = dim.get("label", "")
        lines.append(
            f'<text class="dim" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(label)}</text>'
        )

    for dim in annots.get("prong_height_dims", []):
        pos = dim.get("position_2d", [0, 0])
        label = dim.get("label", "")
        lines.append(
            f'<text class="dim" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(label)}</text>'
        )

    badge = annots.get("ring_size_badge")
    if badge:
        pos = badge.get("position_2d", [0, 0])
        label = badge.get("label", "")
        lines.append(
            f'<text class="badge" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(label)}</text>'
        )

    hm = annots.get("hallmark_indicator")
    if hm:
        pos = hm.get("position_2d", [0, 0])
        label = hm.get("label", "")
        lines.append(
            f'<text class="annot" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(label)}</text>'
        )

    tcl = annots.get("total_carat_label", {})
    if tcl:
        pos = tcl.get("position_2d", [0, 0])
        label = tcl.get("label", "")
        lines.append(
            f'<text class="annot" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(label)}</text>'
        )

    mwl = annots.get("metal_weight_label")
    if mwl:
        pos = mwl.get("position_2d", [0, 0])
        label = mwl.get("label", "")
        lines.append(
            f'<text class="annot" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(label)}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def _svg_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# LLM tool registration (kerf_chat gated)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # jewelry_tech_drawing_generate
    # ------------------------------------------------------------------

    _td_generate_spec = ToolSpec(
        name="jewelry_tech_drawing_generate",
        description=(
            "Generate a multi-view setter's spec sheet for a jewelry piece.\n"
            "Produces top / front / side / iso views via Make2D plus jewelry-\n"
            "specific annotations: stone callouts, seat-depth dims, prong-height\n"
            "dims, ring-size badge, hallmark indicator, total-carat and metal-\n"
            "weight labels.\n"
            "\n"
            "Returns:\n"
            "  ok            : bool\n"
            "  views         : per-view polylines + annotations\n"
            "  annotations   : sheet-level annotation objects\n"
            "  sheet         : border / title-block layout\n"
            "  meta          : drawing_id, scale, view_names\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "piece": {
                    "type": "object",
                    "description": (
                        "Piece description dict.  Keys: metal (str), "
                        "ring_size (number|null), ring_size_system (str), "
                        "volume_mm3 (number|null), hallmark_position ([x,y]|null), "
                        "maker_mark (str|null), gemstones (array), mesh (object|null)."
                    ),
                },
                "views": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["top", "front", "side", "iso"]},
                    "description": "View names to generate (default: all four).",
                },
                "sheet_width_mm":  {"type": "number", "description": "Sheet width mm (default 297)."},
                "sheet_height_mm": {"type": "number", "description": "Sheet height mm (default 210)."},
                "scale":           {"type": "number", "description": "Drawing scale (default 1.0)."},
            },
            "required": ["piece"],
        },
    )

    @register(_td_generate_spec)
    async def run_jewelry_tech_drawing_generate(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        piece = a.get("piece")
        if piece is None:
            return err_payload("piece is required", "BAD_ARGS")
        if not isinstance(piece, dict):
            return err_payload("piece must be an object", "BAD_ARGS")

        views = a.get("views")
        scale = float(a.get("scale", 1.0))
        if scale <= 0:
            return err_payload(f"scale must be positive; got {scale}", "BAD_ARGS")

        sw = float(a.get("sheet_width_mm", _A4_WIDTH_MM))
        sh = float(a.get("sheet_height_mm", _A4_HEIGHT_MM))

        result = jewelry_tech_drawing(
            piece, views,
            sheet_width_mm=sw,
            sheet_height_mm=sh,
            scale=scale,
        )
        if not result.get("ok"):
            return err_payload(result.get("reason", "unknown error"), "OP_FAILED")
        return ok_payload(result)

    # ------------------------------------------------------------------
    # jewelry_tech_drawing_export_dxf
    # ------------------------------------------------------------------

    _td_dxf_spec = ToolSpec(
        name="jewelry_tech_drawing_export_dxf",
        description=(
            "Export a previously-generated Drawing dict to a DXF R12 string.\n"
            "\n"
            "Returns:\n"
            "  ok      : bool\n"
            "  dxf     : DXF text string\n"
            "  length  : character count\n"
            "\n"
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "drawing": {
                    "type": "object",
                    "description": "Drawing dict returned by jewelry_tech_drawing_generate.",
                },
            },
            "required": ["drawing"],
        },
    )

    @register(_td_dxf_spec)
    async def run_jewelry_tech_drawing_export_dxf(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        drawing = a.get("drawing")
        if drawing is None:
            return err_payload("drawing is required", "BAD_ARGS")

        dxf = dxf_export(drawing)
        if not dxf:
            return err_payload("DXF export failed or drawing is invalid", "OP_FAILED")
        return ok_payload({"dxf": dxf, "length": len(dxf)})

    # ------------------------------------------------------------------
    # jewelry_tech_drawing_export_svg
    # ------------------------------------------------------------------

    _td_svg_spec = ToolSpec(
        name="jewelry_tech_drawing_export_svg",
        description=(
            "Export a previously-generated Drawing dict to an SVG 1.1 string.\n"
            "\n"
            "Returns:\n"
            "  ok      : bool\n"
            "  svg     : SVG text string\n"
            "  length  : character count\n"
            "\n"
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "drawing": {
                    "type": "object",
                    "description": "Drawing dict returned by jewelry_tech_drawing_generate.",
                },
            },
            "required": ["drawing"],
        },
    )

    @register(_td_svg_spec)
    async def run_jewelry_tech_drawing_export_svg(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        drawing = a.get("drawing")
        if drawing is None:
            return err_payload("drawing is required", "BAD_ARGS")

        svg = svg_export(drawing)
        if not svg:
            return err_payload("SVG export failed or drawing is invalid", "OP_FAILED")
        return ok_payload({"svg": svg, "length": len(svg)})
