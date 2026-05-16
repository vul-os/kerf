"""
kerf_cad_core.drawings.auto_dimension
======================================

Auto-dimensioning for mechanical/engineering parts — one button to a printable
dimensioned technical drawing.

Given a *part description dict* produces a Drawing dict containing:

  • 4-view sheet (front / top / right / iso) in third-angle projection on A3
    with 1:1 or auto-scaled to fit.
  • Overall L × W × H linear dimensions placed on the front and top views.
  • Hole table: X/Y centre coordinates, diameter Ø, and quantity per unique size.
  • Thread callouts: M<size> × <pitch> × <depth> DP, one per threaded feature.
  • Fillet R callouts: one callout per unique radius.
  • Sectional view note if internal features are detected.
  • GD&T frames: parallelism / perpendicularity callouts on the largest faces;
    position tolerance on the most-critical hole pattern.
  • Title block with project metadata.
  • DXF R12 and SVG 1.1 export helpers.

Public API
----------
auto_dimension(part, view='front_top_right_iso', sheet='A3') -> Drawing
    Main entry point.  Pure Python + NumPy, never raises.

dxf_export(drawing) -> str
    Serialise a Drawing to a minimal DXF R12 string.

svg_export(drawing) -> str
    Serialise a Drawing to an SVG 1.1 string.

LLM tools registered (kerf_chat gated)
---------------------------------------
  auto_dimension_generate       — generate drawing dict (read)
  auto_dimension_export_dxf     — export drawing as DXF text (read)
  auto_dimension_export_svg     — export drawing as SVG text (read)

Part description schema (dict)
-------------------------------
part = {
  "name":    str,              # e.g. "Bracket A"
  "material": str | None,      # e.g. "Steel 1045"
  "revision": str | None,      # e.g. "A"
  "drawn_by": str | None,
  "project":  str | None,
  "bbox": {                    # overall bounding box in mm
    "length": float,           # X extent
    "width":  float,           # Y extent
    "height": float,           # Z extent
  } | None,
  "holes": [                   # cylindrical hole features
    {
      "diameter_mm": float,
      "depth_mm":    float | None,
      "x_mm":        float,    # centre X in part coords
      "y_mm":        float,    # centre Y
      "z_mm":        float,    # centre Z (top face)
      "threaded":    bool,     # True → thread callout
      "thread_pitch_mm": float | None,
      "countersunk": bool,
      "counterbored": bool,
    },
    ...
  ],
  "fillets": [                 # fillet / chamfer features
    {
      "radius_mm": float,
      "count":     int,        # how many of this radius
      "face":      str | None, # "top" | "bottom" | "edge" | None
    },
    ...
  ],
  "internal_features": bool,   # True → add sectional view note
  "mesh": {                    # optional tessellation for Make2D
    "vertices":  [[x,y,z], ...],
    "triangles": [[i,j,k], ...],
  } | None,
}

Never raises — all public functions catch exceptions internally.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Make2D soft-dep
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
# Sheet constants
# ---------------------------------------------------------------------------

_SHEET_SIZES: Dict[str, Tuple[float, float]] = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "A4": (297.0, 210.0),
    "LETTER": (279.4, 215.9),
}
_DEFAULT_SHEET = "A3"
_MARGIN_MM = 10.0
_TITLE_BLOCK_HEIGHT_MM = 25.0
_MIN_SCALE = 0.05
_MAX_SCALE = 10.0

# Third-angle projection view arrangement (front lower-left, top above front,
# right to the right of front, iso upper-right)
_THIRD_ANGLE_ORDER = ["front", "top", "right", "iso"]
_VIEW_LABELS = {
    "front": "FRONT",
    "top": "TOP",
    "right": "RIGHT",
    "iso": "ISO (3D)",
}

# ---------------------------------------------------------------------------
# Fallback tiny mesh used when no mesh supplied
# ---------------------------------------------------------------------------

def _default_mesh(bbox: Optional[Dict[str, Any]]) -> "Make2DInput":
    """Build a box mesh from a bbox dict, or unit cube if none provided."""
    lx = float((bbox or {}).get("length", 10.0))
    ly = float((bbox or {}).get("width", 10.0))
    lz = float((bbox or {}).get("height", 10.0))
    hx, hy, hz = lx / 2, ly / 2, lz / 2
    verts = np.array([
        [-hx, -hy, -hz], [ hx, -hy, -hz], [ hx,  hy, -hz], [-hx,  hy, -hz],
        [-hx, -hy,  hz], [ hx, -hy,  hz], [ hx,  hy,  hz], [-hx,  hy,  hz],
    ], dtype=float)
    faces = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ], dtype=int)
    return Make2DInput(vertices=verts, triangles=faces)


# ---------------------------------------------------------------------------
# View projection helpers
# ---------------------------------------------------------------------------

class _FallbackViewParams:
    def __init__(self, direction: List[float]):
        self.direction = direction


def _std_view_params() -> Dict[str, Any]:
    if _MAKE2D_AVAILABLE:
        return standard_views()
    # minimal fallback
    return {
        "front": _FallbackViewParams([0.0, -1.0, 0.0]),
        "top":   _FallbackViewParams([0.0,  0.0, -1.0]),
        "right": _FallbackViewParams([1.0,  0.0,  0.0]),
        "iso":   _FallbackViewParams([1.0, -1.0, -1.0]),
    }


def _run_make2d(mesh_data: Optional[Dict[str, Any]], bbox: Optional[Dict[str, Any]], view_name: str) -> Tuple[List, List]:
    if not _MAKE2D_AVAILABLE:
        return [], []
    try:
        if mesh_data:
            verts = np.array(mesh_data["vertices"], dtype=float)
            tris = np.array(mesh_data["triangles"], dtype=int)
            mesh = Make2DInput(vertices=verts, triangles=tris)
        else:
            mesh = _default_mesh(bbox)
        ok, _ = mesh.is_valid()
        if not ok:
            return [], []
        views_map = {"front": "front", "top": "top", "right": "right", "iso": "iso"}
        sv = standard_views()
        vp = sv.get(views_map.get(view_name, "front"))
        if vp is None:
            return [], []
        result = make2d(mesh, vp)
        return result.visible, result.hidden
    except Exception:
        return [], []


# ---------------------------------------------------------------------------
# Sheet layout
# ---------------------------------------------------------------------------

def _sheet_size(sheet: str) -> Tuple[float, float]:
    key = sheet.upper()
    return _SHEET_SIZES.get(key, _SHEET_SIZES[_DEFAULT_SHEET])


def _compute_scale(bbox: Optional[Dict[str, Any]], draw_w: float, draw_h: float) -> float:
    """Return best 1:N or N:1 scale so the 4-view arrangement fits the draw area."""
    if bbox is None:
        return 1.0
    L = max(float(bbox.get("length", 1.0)), 1e-3)
    W = max(float(bbox.get("width",  1.0)), 1e-3)
    H = max(float(bbox.get("height", 1.0)), 1e-3)
    # Rough estimate: front = L×H, top = L×W, right = W×H
    needed_w = (L + W) * 1.2
    needed_h = (W + H) * 1.2
    if needed_w <= 0 or needed_h <= 0:
        return 1.0
    scale = min(draw_w / needed_w, draw_h / needed_h)
    # Snap to nearest standard scale
    standards = [0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
    best = 1.0
    for s in standards:
        if s <= scale:
            best = s
    return max(_MIN_SCALE, min(_MAX_SCALE, best))


def _cell_layout(
    sheet_w: float,
    sheet_h: float,
    margin: float,
    title_h: float,
) -> Dict[str, Dict[str, float]]:
    """Return 2×2 grid layout for [front, top, right, iso] in third-angle."""
    draw_x0 = margin
    draw_y0 = margin + title_h
    draw_w = sheet_w - 2 * margin
    draw_h = sheet_h - 2 * margin - title_h
    cw = draw_w / 2
    ch = draw_h / 2
    # Third-angle: front = bottom-left, top = top-left, right = bottom-right, iso = top-right
    return {
        "front": {"x": draw_x0,        "y": draw_y0,        "w": cw, "h": ch},
        "top":   {"x": draw_x0,        "y": draw_y0 + ch,   "w": cw, "h": ch},
        "right": {"x": draw_x0 + cw,   "y": draw_y0,        "w": cw, "h": ch},
        "iso":   {"x": draw_x0 + cw,   "y": draw_y0 + ch,   "w": cw, "h": ch},
    }


# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def _extract_holes(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [h for h in (part.get("holes") or []) if isinstance(h, dict)]


def _extract_fillets(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [f for f in (part.get("fillets") or []) if isinstance(f, dict)]


def _bbox(part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return part.get("bbox") if isinstance(part.get("bbox"), dict) else None


def _hole_table(holes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build hole-table rows grouping by diameter."""
    if not holes:
        return []
    # Group by (diameter, threaded, thread_pitch)
    groups: Dict[Tuple, List[Dict[str, Any]]] = {}
    for h in holes:
        dia = float(h.get("diameter_mm", 0.0))
        threaded = bool(h.get("threaded", False))
        pitch = float(h.get("thread_pitch_mm") or 0.0) if threaded else 0.0
        key = (round(dia, 3), threaded, round(pitch, 3))
        groups.setdefault(key, []).append(h)
    rows = []
    for (dia, threaded, pitch), members in groups.items():
        row: Dict[str, Any] = {
            "diameter_mm": dia,
            "qty": len(members),
            "threaded": threaded,
            "thread_pitch_mm": pitch if threaded else None,
            "centres": [[float(h.get("x_mm", 0.0)), float(h.get("y_mm", 0.0))] for h in members],
        }
        rows.append(row)
    return rows


def _thread_callouts(holes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return one callout dict per unique threaded hole spec."""
    seen: Dict[str, Dict[str, Any]] = {}
    for h in holes:
        if not h.get("threaded"):
            continue
        dia = float(h.get("diameter_mm", 0.0))
        pitch = float(h.get("thread_pitch_mm") or 1.0)
        depth = h.get("depth_mm")
        label = f"M{dia:.0f} ×{pitch:.1f}"
        if depth is not None:
            label += f" ×{float(depth):.0f} DP"
        key = label
        if key not in seen:
            seen[key] = {
                "type": "thread_callout",
                "label": label,
                "diameter_mm": dia,
                "pitch_mm": pitch,
                "depth_mm": float(depth) if depth is not None else None,
                "x_mm": float(h.get("x_mm", 0.0)),
                "y_mm": float(h.get("y_mm", 0.0)),
            }
    return list(seen.values())


def _fillet_callouts(fillets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return one callout per unique fillet radius."""
    seen: Dict[float, Dict[str, Any]] = {}
    for f in fillets:
        r = round(float(f.get("radius_mm", 0.0)), 4)
        if r <= 0:
            continue
        if r not in seen:
            seen[r] = {
                "type": "fillet_callout",
                "radius_mm": r,
                "label": f"R{r:.2f}",
                "count": int(f.get("count", 1)),
                "face": f.get("face"),
            }
        else:
            seen[r]["count"] += int(f.get("count", 1))
    return list(seen.values())


def _overall_dims(
    bbox: Optional[Dict[str, Any]],
    layout: Dict[str, Dict[str, float]],
    scale: float,
) -> Dict[str, List[Dict[str, Any]]]:
    """Place L×W×H linear dimensions on front (L, H) and top (L, W) views."""
    result: Dict[str, List[Dict[str, Any]]] = {"front": [], "top": [], "right": []}
    if bbox is None:
        return result
    L = float(bbox.get("length", 0.0))
    W = float(bbox.get("width",  0.0))
    H = float(bbox.get("height", 0.0))

    def _cell_cx(name: str) -> float:
        c = layout[name]
        return c["x"] + c["w"] * 0.5

    def _cell_cy(name: str) -> float:
        c = layout[name]
        return c["y"] + c["h"] * 0.5

    # Front view: width dimension (L) along bottom, height dimension (H) along right side
    fcx, fcy = _cell_cx("front"), _cell_cy("front")
    half_L = L * scale / 2
    half_H = H * scale / 2
    half_W = W * scale / 2

    result["front"].append({
        "type": "linear_dim",
        "axis": "horizontal",
        "label": f"L={L:.2f}",
        "p1": [fcx - half_L, fcy + half_H + 6.0],
        "p2": [fcx + half_L, fcy + half_H + 6.0],
        "value_mm": L,
        "view": "front",
    })
    result["front"].append({
        "type": "linear_dim",
        "axis": "vertical",
        "label": f"H={H:.2f}",
        "p1": [fcx + half_L + 6.0, fcy - half_H],
        "p2": [fcx + half_L + 6.0, fcy + half_H],
        "value_mm": H,
        "view": "front",
    })

    # Top view: length (L) and width (W)
    tcx, tcy = _cell_cx("top"), _cell_cy("top")
    result["top"].append({
        "type": "linear_dim",
        "axis": "horizontal",
        "label": f"L={L:.2f}",
        "p1": [tcx - half_L, tcy + half_W + 6.0],
        "p2": [tcx + half_L, tcy + half_W + 6.0],
        "value_mm": L,
        "view": "top",
    })
    result["top"].append({
        "type": "linear_dim",
        "axis": "vertical",
        "label": f"W={W:.2f}",
        "p1": [tcx + half_L + 6.0, tcy - half_W],
        "p2": [tcx + half_L + 6.0, tcy + half_W],
        "value_mm": W,
        "view": "top",
    })

    # Right view: width (W) and height (H) for completeness
    rcx, rcy = _cell_cx("right"), _cell_cy("right")
    result["right"].append({
        "type": "linear_dim",
        "axis": "horizontal",
        "label": f"W={W:.2f}",
        "p1": [rcx - half_W, rcy + half_H + 6.0],
        "p2": [rcx + half_W, rcy + half_H + 6.0],
        "value_mm": W,
        "view": "right",
    })

    return result


def _hole_table_annotations(
    table: List[Dict[str, Any]],
    layout: Dict[str, Dict[str, float]],
) -> List[Dict[str, Any]]:
    """Return a list of hole-table annotation dicts to be placed on the top view."""
    if not table:
        return []
    cell = layout["front"]
    # Place hole table below front view
    base_x = cell["x"] + 2.0
    base_y = cell["y"] + 2.0  # inside bottom of front view cell
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(table):
        dia = row["diameter_mm"]
        qty = row["qty"]
        threaded = row["threaded"]
        pitch = row.get("thread_pitch_mm")
        label = f"Ø{dia:.2f}  ×{qty}"
        if threaded and pitch:
            label += f"  M{dia:.0f}"
        rows.append({
            "type": "hole_table_row",
            "label": label,
            "diameter_mm": dia,
            "qty": qty,
            "threaded": threaded,
            "position_2d": [base_x, base_y + i * 4.5],
        })
    return rows


def _gdt_frames(
    bbox: Optional[Dict[str, Any]],
    holes: List[Dict[str, Any]],
    layout: Dict[str, Dict[str, float]],
    scale: float,
) -> List[Dict[str, Any]]:
    """Place GD&T frames for the dominant faces and hole pattern."""
    frames: List[Dict[str, Any]] = []
    if bbox is None:
        return frames

    L = float(bbox.get("length", 0.0))
    W = float(bbox.get("width",  0.0))
    H = float(bbox.get("height", 0.0))

    # Determine largest face — used as primary datum
    face_areas = {"front": L * H, "top": L * W, "right": W * H}
    largest = max(face_areas, key=face_areas.__getitem__)

    # Parallelism on top face relative to front-face datum A
    cell = layout.get(largest, layout["front"])
    cx = cell["x"] + cell["w"] * 0.5
    cy = cell["y"] + cell["h"] * 0.5
    half_dim = max(L, W, H) * scale / 2
    frames.append({
        "type": "gdt_frame",
        "symbol": "//",
        "tolerance_mm": 0.05,
        "datum": "A",
        "label": "// 0.05 A",
        "position_2d": [cx + half_dim + 10.0, cy],
        "view": largest,
    })

    # Perpendicularity on the right face relative to datum A
    r_cell = layout["right"]
    rx = r_cell["x"] + r_cell["w"] * 0.5
    ry = r_cell["y"] + r_cell["h"] * 0.5
    frames.append({
        "type": "gdt_frame",
        "symbol": "⊥",
        "tolerance_mm": 0.05,
        "datum": "A",
        "label": "⊥ 0.05 A",
        "position_2d": [rx + W * scale / 2 + 10.0, ry],
        "view": "right",
    })

    # Position tolerance on the most-critical hole pattern (≥2 holes)
    if len(holes) >= 2:
        t_cell = layout["top"]
        tx = t_cell["x"] + t_cell["w"] * 0.5
        ty = t_cell["y"] + t_cell["h"] * 0.5
        frames.append({
            "type": "gdt_frame",
            "symbol": "⊕",
            "tolerance_mm": 0.1,
            "datum": "A|B|C",
            "label": "⊕ Ø0.10 A B C",
            "position_2d": [tx + L * scale / 2 + 12.0, ty],
            "view": "top",
        })

    return frames


def _title_block_content(part: Dict[str, Any], sheet_str: str, scale: float) -> Dict[str, Any]:
    return {
        "type": "title_block",
        "name":     str(part.get("name", "Untitled")),
        "material": str(part.get("material") or ""),
        "revision": str(part.get("revision") or "A"),
        "drawn_by": str(part.get("drawn_by") or ""),
        "project":  str(part.get("project") or ""),
        "sheet":    sheet_str,
        "scale":    f"1:{1/scale:.0f}" if scale < 1 else f"{scale:.0f}:1" if scale > 1 else "1:1",
    }


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def auto_dimension(
    part: Any,
    view: str = "front_top_right_iso",
    sheet: str = "A3",
) -> Dict[str, Any]:
    """Generate an auto-dimensioned technical drawing from a part description.

    Parameters
    ----------
    part : dict
        Part description (see module docstring for schema).
    view : str
        Reserved for future view presets; currently always produces
        front/top/right/iso 4-view layout.
    sheet : str
        Sheet size code: 'A0'..'A4', 'LETTER'.  Default 'A3'.

    Returns
    -------
    dict
        Drawing structure::

            {
              "ok": True,
              "views": {
                "<view_name>": {
                  "visible":     [polyline, ...],
                  "hidden":      [polyline, ...],
                  "bbox":        {"x","y","w","h"},
                  "label":       str,
                  "dimensions":  [...],
                },
                ...
              },
              "annotations": {
                "overall_dims":      [...],
                "hole_table":        [...],
                "thread_callouts":   [...],
                "fillet_callouts":   [...],
                "section_note":      str | None,
                "gdt_frames":        [...],
                "title_block":       {...},
              },
              "sheet": {
                "size":              str,
                "width_mm":          float,
                "height_mm":         float,
                "margin_mm":         float,
                "title_block_height_mm": float,
                "border":            [[x,y],...],
                "title_block":       [[x,y],...],
              },
              "meta": {
                "drawing_id":  str,
                "scale":       float,
                "view_names":  [str,...],
              },
            }

    Never raises.
    """
    try:
        return _build_drawing(part, view, sheet)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _build_drawing(
    part: Any,
    view: str,
    sheet: str,
) -> Dict[str, Any]:
    if not isinstance(part, dict):
        raise ValueError("part must be a dict")

    sheet_upper = sheet.upper()
    if sheet_upper not in _SHEET_SIZES:
        raise ValueError(
            f"Unknown sheet size {sheet!r}. Valid: {sorted(_SHEET_SIZES.keys())}"
        )

    sw, sh = _sheet_size(sheet_upper)
    margin = _MARGIN_MM
    tb_h = _TITLE_BLOCK_HEIGHT_MM

    draw_w = sw - 2 * margin
    draw_h = sh - 2 * margin - tb_h

    bbox = _bbox(part)
    scale = _compute_scale(bbox, draw_w, draw_h)
    layout = _cell_layout(sw, sh, margin, tb_h)

    holes = _extract_holes(part)
    fillets = _extract_fillets(part)
    mesh_data = part.get("mesh") if isinstance(part.get("mesh"), dict) else None

    # Build per-view data
    views_out: Dict[str, Any] = {}
    for vname in _THIRD_ANGLE_ORDER:
        visible, hidden = _run_make2d(mesh_data, bbox, vname)
        cell = layout[vname]
        cx = cell["x"] + cell["w"] * 0.5
        cy = cell["y"] + cell["h"] * 0.5

        def _offset(poly: List) -> List[List[float]]:
            return [[cx + pt[0] * scale, cy + pt[1] * scale] for pt in poly]

        vis_scaled = [_offset(p) for p in visible]
        hid_scaled = [_offset(p) for p in hidden]

        views_out[vname] = {
            "visible":    vis_scaled,
            "hidden":     hid_scaled,
            "bbox":       cell,
            "label":      _VIEW_LABELS[vname],
            "dimensions": [],  # populated below
        }

    # Overall L×W×H dimensions
    overall_dim_map = _overall_dims(bbox, layout, scale)
    for vname, dims in overall_dim_map.items():
        if vname in views_out:
            views_out[vname]["dimensions"].extend(dims)

    # Hole table
    table = _hole_table(holes)
    hole_table_annots = _hole_table_annotations(table, layout)

    # Thread callouts — placed on front view
    thread_calls = _thread_callouts(holes)
    for i, tc in enumerate(thread_calls):
        cell = layout["front"]
        tc["position_2d"] = [
            cell["x"] + cell["w"] - 30.0,
            cell["y"] + cell["h"] - 6.0 - i * 5.0,
        ]

    # Fillet callouts — placed on iso view
    fillet_calls = _fillet_callouts(fillets)
    for i, fc in enumerate(fillet_calls):
        cell = layout["iso"]
        fc["position_2d"] = [
            cell["x"] + 2.0,
            cell["y"] + cell["h"] - 6.0 - i * 5.0,
        ]

    # Section note
    section_note: Optional[str] = None
    if part.get("internal_features"):
        section_note = "SECTION A-A: see detail view for internal features"

    # GD&T frames
    gdt_frames = _gdt_frames(bbox, holes, layout, scale)

    # Title block
    title_block_content = _title_block_content(part, sheet_upper, scale)

    # Sheet border and title block border
    border = [
        [margin, margin],
        [sw - margin, margin],
        [sw - margin, sh - margin],
        [margin, sh - margin],
        [margin, margin],
    ]
    tb_border = [
        [margin, margin],
        [sw - margin, margin],
        [sw - margin, margin + tb_h],
        [margin, margin + tb_h],
        [margin, margin],
    ]

    return {
        "ok": True,
        "views": views_out,
        "annotations": {
            "overall_dims":    [d for v in overall_dim_map.values() for d in v],
            "hole_table":      hole_table_annots,
            "thread_callouts": thread_calls,
            "fillet_callouts": fillet_calls,
            "section_note":    section_note,
            "gdt_frames":      gdt_frames,
            "title_block":     title_block_content,
        },
        "sheet": {
            "size":                  sheet_upper,
            "width_mm":              sw,
            "height_mm":             sh,
            "margin_mm":             margin,
            "title_block_height_mm": tb_h,
            "border":                border,
            "title_block":           tb_border,
        },
        "meta": {
            "drawing_id": str(uuid.uuid4()),
            "scale":      scale,
            "view_names": _THIRD_ANGLE_ORDER[:],
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


def _dxf_line(x0: float, y0: float, x1: float, y1: float, layer: str = "0") -> str:
    return (
        f"0\nLINE\n8\n{layer}\n"
        f"10\n{x0:.6f}\n20\n{y0:.6f}\n30\n0.0\n"
        f"11\n{x1:.6f}\n21\n{y1:.6f}\n31\n0.0\n"
    )


def _dxf_polyline_lines(pts: List[List[float]], layer: str = "0") -> str:
    lines = []
    for i in range(len(pts) - 1):
        lines.append(_dxf_line(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1], layer))
    return "".join(lines)


def _dxf_text(x: float, y: float, text: str, height: float = 2.5, layer: str = "ANNOT") -> str:
    return (
        f"0\nTEXT\n8\n{layer}\n"
        f"10\n{x:.6f}\n20\n{y:.6f}\n30\n0.0\n"
        f"40\n{height:.3f}\n"
        f"1\n{text}\n"
    )


def dxf_export(drawing: Dict[str, Any]) -> str:
    """Serialise a Drawing dict to a DXF R12 string.  Never raises."""
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
    for poly in [sheet.get("border", []), sheet.get("title_block", [])]:
        if poly:
            entities.append(_dxf_polyline_lines(poly, layer="BORDER"))

    # Views
    for vname, vdata in drawing.get("views", {}).items():
        for poly in vdata.get("visible", []):
            entities.append(_dxf_polyline_lines(poly, layer="VISIBLE"))
        for poly in vdata.get("hidden", []):
            entities.append(_dxf_polyline_lines(poly, layer="HIDDEN"))
        # View label
        bbox = vdata.get("bbox", {})
        if bbox:
            entities.append(_dxf_text(
                bbox.get("x", 0) + 2, bbox.get("y", 0) + 2,
                vdata.get("label", vname.upper()),
                height=3.0, layer="VIEWLABEL",
            ))
        # Dimensions
        for dim in vdata.get("dimensions", []):
            p1 = dim.get("p1", [0, 0])
            p2 = dim.get("p2", [0, 0])
            entities.append(_dxf_line(p1[0], p1[1], p2[0], p2[1], layer="DIM"))
            mid = [(p1[0]+p2[0])/2, (p1[1]+p2[1])/2]
            entities.append(_dxf_text(mid[0], mid[1], dim.get("label", ""), layer="DIM"))

    # Sheet-level annotations
    annots = drawing.get("annotations", {})
    for ht_row in annots.get("hole_table", []):
        pos = ht_row.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], ht_row.get("label", ""), layer="HOLE_TABLE"))
    for tc in annots.get("thread_callouts", []):
        pos = tc.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], tc.get("label", ""), layer="THREAD"))
    for fc in annots.get("fillet_callouts", []):
        pos = fc.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], fc.get("label", ""), layer="FILLET"))
    for gf in annots.get("gdt_frames", []):
        pos = gf.get("position_2d", [0, 0])
        entities.append(_dxf_text(pos[0], pos[1], gf.get("label", ""), layer="GDT"))
    sn = annots.get("section_note")
    if sn:
        sheet_w = sheet.get("width_mm", 420.0)
        sheet_h = sheet.get("height_mm", 297.0)
        entities.append(_dxf_text(sheet_w / 2, sheet_h / 2 + 20, sn, layer="SECTION"))
    tb = annots.get("title_block", {})
    if tb:
        m = sheet.get("margin_mm", 10.0)
        entities.append(_dxf_text(m + 2, m + 2, f"{tb.get('name','')}  Rev:{tb.get('revision','')}", layer="TITLE"))
        entities.append(_dxf_text(m + 2, m + 7, f"Mat:{tb.get('material','')}  Scale:{tb.get('scale','')}", layer="TITLE"))
        entities.append(_dxf_text(m + 2, m + 12, f"Project:{tb.get('project','')}  By:{tb.get('drawn_by','')}", layer="TITLE"))

    return _DXF_HEADER + "".join(entities) + _DXF_FOOTER


# ---------------------------------------------------------------------------
# SVG export
# ---------------------------------------------------------------------------


def svg_export(drawing: Dict[str, Any]) -> str:
    """Serialise a Drawing dict to an SVG 1.1 string.  Never raises."""
    try:
        return _svg_export_inner(drawing)
    except Exception:
        return ""


def _svg_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def _svg_pts(pts: List[List[float]]) -> str:
    return " ".join(f"{p[0]:.3f},{p[1]:.3f}" for p in pts)


def _svg_export_inner(drawing: Dict[str, Any]) -> str:
    if not drawing.get("ok"):
        return ""

    sheet = drawing.get("sheet", {})
    sw = sheet.get("width_mm", 420.0)
    sh = sheet.get("height_mm", 297.0)

    lines: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{sw}mm" height="{sh}mm" '
        f'viewBox="0 0 {sw} {sh}" version="1.1">',
        '<defs><style>'
        '.vis{stroke:#000;stroke-width:0.3;fill:none}'
        '.hid{stroke:#555;stroke-width:0.15;stroke-dasharray:2 1;fill:none}'
        '.bdr{stroke:#000;stroke-width:0.5;fill:none}'
        '.dim{stroke:#00f;stroke-width:0.2;fill:none}'
        '.txt{font-family:monospace;font-size:2.5px;fill:#000}'
        '.lbl{font-family:sans-serif;font-size:3px;fill:#222;font-weight:bold}'
        '.gdt{font-family:monospace;font-size:2px;fill:#900}'
        '.ttl{font-family:sans-serif;font-size:3px;fill:#000}'
        '</style></defs>',
    ]

    # Sheet border
    for poly_key in ("border", "title_block"):
        poly = sheet.get(poly_key, [])
        if poly:
            lines.append(f'<polyline class="bdr" points="{_svg_pts(poly)}"/>')

    # Views
    for vname, vdata in drawing.get("views", {}).items():
        bbox = vdata.get("bbox", {})
        bx, by = bbox.get("x", 0), bbox.get("y", 0)
        bw, bh = bbox.get("w", 0), bbox.get("h", 0)
        # View cell border
        lines.append(
            f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh:.2f}" '
            f'class="bdr" fill="none"/>'
        )
        # View label
        lines.append(
            f'<text class="lbl" x="{bx+2:.1f}" y="{by+6:.1f}">'
            f'{_svg_escape(vdata.get("label", vname.upper()))}</text>'
        )
        for poly in vdata.get("visible", []):
            pts = _svg_pts(poly)
            if pts:
                lines.append(f'<polyline class="vis" points="{pts}"/>')
        for poly in vdata.get("hidden", []):
            pts = _svg_pts(poly)
            if pts:
                lines.append(f'<polyline class="hid" points="{pts}"/>')
        for dim in vdata.get("dimensions", []):
            p1 = dim.get("p1", [0, 0])
            p2 = dim.get("p2", [0, 0])
            lines.append(
                f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" '
                f'x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" class="dim"/>'
            )
            mx, my = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
            lines.append(
                f'<text class="txt" x="{mx:.2f}" y="{my-1:.2f}">'
                f'{_svg_escape(dim.get("label",""))}</text>'
            )

    # Sheet-level annotations
    annots = drawing.get("annotations", {})
    for ht_row in annots.get("hole_table", []):
        pos = ht_row.get("position_2d", [0, 0])
        lines.append(
            f'<text class="txt" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(ht_row.get("label",""))}</text>'
        )
    for tc in annots.get("thread_callouts", []):
        pos = tc.get("position_2d", [0, 0])
        lines.append(
            f'<text class="txt" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(tc.get("label",""))}</text>'
        )
    for fc in annots.get("fillet_callouts", []):
        pos = fc.get("position_2d", [0, 0])
        lines.append(
            f'<text class="txt" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(fc.get("label",""))}</text>'
        )
    for gf in annots.get("gdt_frames", []):
        pos = gf.get("position_2d", [0, 0])
        lines.append(
            f'<text class="gdt" x="{pos[0]:.2f}" y="{pos[1]:.2f}">'
            f'{_svg_escape(gf.get("label",""))}</text>'
        )
    sn = annots.get("section_note")
    if sn:
        lines.append(
            f'<text class="txt" x="{sw/2:.2f}" y="{sh/2+20:.2f}" '
            f'text-anchor="middle">{_svg_escape(sn)}</text>'
        )
    tb = annots.get("title_block", {})
    if tb:
        m = sheet.get("margin_mm", 10.0)
        lines.append(
            f'<text class="ttl" x="{m+2:.1f}" y="{m+5:.1f}">'
            f'{_svg_escape(str(tb.get("name","")))}'
            f'  Rev:{_svg_escape(str(tb.get("revision","")))}</text>'
        )
        lines.append(
            f'<text class="ttl" x="{m+2:.1f}" y="{m+10:.1f}">'
            f'Mat:{_svg_escape(str(tb.get("material","")))}'
            f'  Scale:{_svg_escape(str(tb.get("scale","")))}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


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

    _ad_generate_spec = ToolSpec(
        name="auto_dimension_generate",
        description=(
            "Auto-dimension a mechanical part — generate a fully annotated\n"
            "4-view (front/top/right/iso) technical drawing on an A3 sheet.\n"
            "\n"
            "Returns:\n"
            "  ok               : bool\n"
            "  views            : per-view polylines + dimension annotations\n"
            "  annotations      : overall dims, hole table, thread callouts,\n"
            "                     fillet callouts, GD&T frames, title block\n"
            "  sheet            : border / title-block layout\n"
            "  meta             : drawing_id, scale, view_names\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "part": {
                    "type": "object",
                    "description": (
                        "Part description dict.  Keys: name (str), material (str|null), "
                        "revision (str|null), drawn_by (str|null), project (str|null), "
                        "bbox ({length,width,height} in mm|null), holes (array|null), "
                        "fillets (array|null), internal_features (bool), mesh (object|null)."
                    ),
                },
                "sheet": {
                    "type": "string",
                    "enum": ["A0", "A1", "A2", "A3", "A4", "LETTER"],
                    "description": "Sheet size (default A3).",
                },
            },
            "required": ["part"],
        },
    )

    @register(_ad_generate_spec)
    async def run_auto_dimension_generate(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        part = a.get("part")
        if part is None:
            return err_payload("part is required", "BAD_ARGS")
        if not isinstance(part, dict):
            return err_payload("part must be an object", "BAD_ARGS")
        sheet = str(a.get("sheet", "A3"))
        result = auto_dimension(part, sheet=sheet)
        if not result.get("ok"):
            return err_payload(result.get("reason", "unknown error"), "OP_FAILED")
        return ok_payload(result)

    _ad_dxf_spec = ToolSpec(
        name="auto_dimension_export_dxf",
        description=(
            "Export an auto-dimension Drawing dict to DXF R12 text.\n"
            "\n"
            "Returns: ok, dxf (str), length (int).  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "drawing": {"type": "object", "description": "Drawing dict from auto_dimension_generate."},
            },
            "required": ["drawing"],
        },
    )

    @register(_ad_dxf_spec)
    async def run_auto_dimension_export_dxf(ctx: "ProjectCtx", args: bytes) -> str:
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

    _ad_svg_spec = ToolSpec(
        name="auto_dimension_export_svg",
        description=(
            "Export an auto-dimension Drawing dict to SVG 1.1 text.\n"
            "\n"
            "Returns: ok, svg (str), length (int).  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "drawing": {"type": "object", "description": "Drawing dict from auto_dimension_generate."},
            },
            "required": ["drawing"],
        },
    )

    @register(_ad_svg_spec)
    async def run_auto_dimension_export_svg(ctx: "ProjectCtx", args: bytes) -> str:
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
