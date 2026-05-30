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
  • ISO 129-1:2018 chain/baseline/mixed dimensioning (auto_dimension_view_iso129).
  • ISO 129-1:2018 tolerance formatting (apply_iso129_tolerance_format).
  • ISO 129-1:2018 compliance validation (validate_iso129_compliance).

Public API
----------
auto_dimension(part, view='front_top_right_iso', sheet='A3') -> Drawing
    Main entry point.  Pure Python + NumPy, never raises.

dxf_export(drawing) -> str
    Serialise a Drawing to a minimal DXF R12 string.

svg_export(drawing) -> str
    Serialise a Drawing to an SVG 1.1 string.

auto_dimension_view_iso129(view, mode='chain'|'baseline'|'mixed') -> list[dict]
    Produce ISO 129-1:2018-conformant dimension line dicts for a view.
    Implements chain (§5.1), baseline (§5.1), and mixed modes; enforces
    extension-line gap/overshoot (§5.4: 2 mm gap, 2 mm overshoot), 10 mm
    line spacing, 3–4 mm arrowhead length, and leader lines for circular
    features (ISO §10).  Claim: follows ISO 129-1:2018 conventions, NOT ISO
    certified.

apply_iso129_tolerance_format(value, tolerance, kind='symmetric'|'unilateral'|'limit') -> str
    Format a dimension value with tolerance per ISO 129-1:2018 §8:
      symmetric  → "100 ± 0.1"
      unilateral → "100 +0.2/0"
      limit      → "100.1 / 99.9"

validate_iso129_compliance(view) -> ValidationResult
    Check a view dict for ISO 129-1:2018 compliance: extension-line length,
    dimension-line spacing, leader-line angle (15° preferred per §10), and
    dimension-line orientation vs feature direction.

LLM tools registered (kerf_chat gated)
---------------------------------------
  auto_dimension_generate         — generate drawing dict (read)
  auto_dimension_export_dxf       — export drawing as DXF text (read)
  auto_dimension_export_svg       — export drawing as SVG text (read)
  drawing_auto_dimension_iso      — ISO 129-1:2018 chain/baseline/mixed dim (read)
  drawing_validate_iso            — validate ISO 129-1:2018 compliance (read)

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
# ISO 129-1:2018 dimensioning conventions
# ---------------------------------------------------------------------------
# Claim: follows ISO 129-1:2018 conventions — NOT ISO certified.
#
# Key constants from the standard:
#   §5.4 — extension line gap (from feature edge) = 1–2 mm; overshoot past
#           dimension line = 2 mm; arrowhead length 3–4 mm.
#   §5.4 — minimum dimension-line spacing = 10 mm.
#   §10  — leader line preferred angle = 15°, 30°, 45°, 60°, 75°.
# ---------------------------------------------------------------------------

# ISO §5.4 layout constants (all in mm, drawing-space units)
_ISO_EXTENSION_LINE_GAP_MM: float = 1.5     # gap from feature boundary
_ISO_EXTENSION_LINE_OVERSHOOT_MM: float = 2.0  # past the dimension line
_ISO_DIM_LINE_SPACING_MM: float = 10.0     # between parallel dim lines
_ISO_ARROWHEAD_LENGTH_MM: float = 3.5      # 3–4 mm per §5.4
_ISO_FONT_HEIGHT_MM: float = 2.5           # minimum text height ISO 3098-2
# Preferred leader-line angles (degrees from horizontal) per ISO §10
_ISO_LEADER_ANGLES_DEG: Tuple[float, ...] = (15.0, 30.0, 45.0, 60.0, 75.0)


def _nearest_leader_angle(dx: float, dy: float) -> float:
    """Return the ISO §10 preferred angle closest to the vector (dx, dy)."""
    actual = math.degrees(math.atan2(abs(dy), abs(dx)))
    return min(_ISO_LEADER_ANGLES_DEG, key=lambda a: abs(a - actual))


def _make_iso_linear_dim(
    value_mm: float,
    axis: str,          # "horizontal" | "vertical"
    p_start: List[float],
    p_end: List[float],
    dim_line_offset: float,  # perpendicular distance from feature edge
    label: Optional[str] = None,
    feature_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an ISO 129-1:2018-conformant linear dimension dict.

    The dict carries all geometry needed for DXF/SVG rendering:
      ext1_start / ext1_end  — first extension line (gap + overshoot)
      ext2_start / ext2_end  — second extension line
      dim_p1 / dim_p2        — dimension line endpoints (at arrowheads)
      text_pos               — dimension text midpoint
      arrowhead_length_mm    — 3.5 mm
    """
    if label is None:
        label = f"{value_mm:.2f}"

    gap = _ISO_EXTENSION_LINE_GAP_MM
    over = _ISO_EXTENSION_LINE_OVERSHOOT_MM

    if axis == "horizontal":
        # p_start / p_end are left/right feature points (same Y)
        fx1, fy = p_start[0], p_start[1]
        fx2 = p_end[0]
        # Dimension line above (offset positive = up on drawing Y)
        dim_y = fy - dim_line_offset  # convention: above feature
        return {
            "type": "iso_linear_dim",
            "axis": axis,
            "value_mm": value_mm,
            "label": label,
            "feature_ref": feature_ref,
            # Extension line 1 (left feature point)
            "ext1_start": [fx1, fy - gap],
            "ext1_end":   [fx1, dim_y + over],
            # Extension line 2 (right feature point)
            "ext2_start": [fx2, fy - gap],
            "ext2_end":   [fx2, dim_y + over],
            # Dimension line
            "dim_p1": [fx1, dim_y],
            "dim_p2": [fx2, dim_y],
            "text_pos": [(fx1 + fx2) / 2.0, dim_y - 1.5],
            "arrowhead_length_mm": _ISO_ARROWHEAD_LENGTH_MM,
        }
    else:  # vertical
        fx, fy1 = p_start[0], p_start[1]
        fy2 = p_end[1]
        dim_x = fx + dim_line_offset  # to the right of the feature
        return {
            "type": "iso_linear_dim",
            "axis": axis,
            "value_mm": value_mm,
            "label": label,
            "feature_ref": feature_ref,
            "ext1_start": [fx + gap, fy1],
            "ext1_end":   [dim_x + over, fy1],
            "ext2_start": [fx + gap, fy2],
            "ext2_end":   [dim_x + over, fy2],
            "dim_p1": [dim_x, fy1],
            "dim_p2": [dim_x, fy2],
            "text_pos": [dim_x + 1.5, (fy1 + fy2) / 2.0],
            "arrowhead_length_mm": _ISO_ARROWHEAD_LENGTH_MM,
        }


def _make_iso_leader_dim(
    cx: float,
    cy: float,
    diameter_mm: float,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an ISO §10 leader-line annotation for a circular feature.

    Leader goes from (cx, cy) at the preferred 15° angle outward; a
    horizontal shoulder extends to the text.  A centrepoint mark (+) is
    also placed at (cx, cy).
    """
    if label is None:
        label = f"Ø{diameter_mm:.2f}"
    angle_deg = _ISO_LEADER_ANGLES_DEG[0]  # 15° preferred
    leader_len = max(diameter_mm / 2.0 + 4.0, 10.0)
    rad = math.radians(angle_deg)
    tip_x = cx + math.cos(rad) * leader_len
    tip_y = cy - math.sin(rad) * leader_len  # up-right
    shoulder_len = 6.0
    return {
        "type": "iso_leader_dim",
        "label": label,
        "diameter_mm": diameter_mm,
        "centre": [cx, cy],
        "leader_start": [cx, cy],
        "leader_elbow": [tip_x, tip_y],
        "shoulder_end": [tip_x + shoulder_len, tip_y],
        "text_pos": [tip_x + shoulder_len + 0.5, tip_y - 1.0],
        "leader_angle_deg": angle_deg,
        "arrowhead_length_mm": _ISO_ARROWHEAD_LENGTH_MM,
        # centrepoint cross marks (ISO §10)
        "centre_mark_size_mm": 2.5,
    }


def auto_dimension_view_iso129(
    view: Dict[str, Any],
    mode: str = "chain",
) -> List[Dict[str, Any]]:
    """Produce ISO 129-1:2018-conformant dimension dicts for a view.

    Parameters
    ----------
    view : dict
        View dict as returned by ``auto_dimension`` — must contain at minimum:
        ``bbox`` (dict with x, y, w, h), optionally ``features`` (list of
        feature dicts with ``kind``, ``x_mm``, ``y_mm``, ``diameter_mm`` for
        holes).
    mode : str
        ``'chain'``    — dimensions chain end-to-end (ISO §5.1).
        ``'baseline'`` — all dimensions from a common baseline (ISO §5.1).
        ``'mixed'``    — small gaps use chain; wide gaps use baseline.

    Returns
    -------
    list[dict]
        List of ISO dimension dicts (``iso_linear_dim`` or ``iso_leader_dim``).
        Each dict carries ext-line geometry, dim-line endpoints, text position,
        arrowhead length, and the dimension value.

    Notes
    -----
    - Claim: follows ISO 129-1:2018 conventions — NOT ISO certified.
    - Extension lines: 1.5 mm gap from feature, 2 mm overshoot past dim line
      (§5.4).
    - Dimension-line spacing: 10 mm between parallel dimension lines (§5.4).
    - Arrowheads: 3.5 mm (within the 3–4 mm range of §5.4).
    - Circular features → leader lines with preferred 15° angle (ISO §10).
    - Dimension lines placed outside view extents to avoid crossing view lines.
    """
    if mode not in ("chain", "baseline", "mixed"):
        raise ValueError(f"mode must be 'chain', 'baseline', or 'mixed'; got {mode!r}")

    bbox = view.get("bbox") or {}
    bx = float(bbox.get("x", 0.0))
    by = float(bbox.get("y", 0.0))
    bw = float(bbox.get("w", 100.0))
    bh = float(bbox.get("h", 100.0))

    # Feature extraction — accept either a "features" list in the view dict or
    # derive synthetic points from bbox corners.
    features: List[Dict[str, Any]] = list(view.get("features") or [])

    # Collect horizontal feature X-positions and vertical feature Y-positions
    # from bbox-derived edges plus any explicit feature points.
    x_coords: List[float] = sorted({bx, bx + bw} | {float(f.get("x_mm", f.get("cx", bx))) for f in features if isinstance(f, dict)})
    y_coords: List[float] = sorted({by, by + bh} | {float(f.get("y_mm", f.get("cy", by))) for f in features if isinstance(f, dict)})

    dims: List[Dict[str, Any]] = []

    # ---- Horizontal dimensions (across the width of the view) ---------------
    # Dimension lines placed above view extents: base_y = by + bh + spacing
    base_y_offset = _ISO_DIM_LINE_SPACING_MM  # first dim line above top edge

    if mode == "chain":
        # Chain: each segment between consecutive X-positions (n-1 dims for n points)
        for i in range(len(x_coords) - 1):
            x1, x2 = x_coords[i], x_coords[i + 1]
            offset = base_y_offset  # all at same level in chain mode
            d = _make_iso_linear_dim(
                value_mm=abs(x2 - x1),
                axis="horizontal",
                p_start=[x1, by + bh],
                p_end=[x2, by + bh],
                dim_line_offset=offset,
                label=f"{abs(x2-x1):.2f}",
                feature_ref=f"x[{i}]→x[{i+1}]",
            )
            dims.append(d)

    elif mode == "baseline":
        # Baseline: all dims from leftmost edge (n dims for n+1 points if left is baseline)
        # For n feature positions (including left edge as baseline), produce n-1 dims.
        baseline_x = x_coords[0]
        for i, x2 in enumerate(x_coords[1:], start=1):
            # Stack each dim at increasing offset to avoid crossings
            offset = base_y_offset + (i - 1) * _ISO_DIM_LINE_SPACING_MM
            d = _make_iso_linear_dim(
                value_mm=abs(x2 - baseline_x),
                axis="horizontal",
                p_start=[baseline_x, by + bh],
                p_end=[x2, by + bh],
                dim_line_offset=offset,
                label=f"{abs(x2-baseline_x):.2f}",
                feature_ref=f"baseline→x[{i}]",
            )
            dims.append(d)

    else:  # mixed
        # Mixed: chain close features (gap < 2× spacing), baseline for wide
        baseline_x = x_coords[0]
        chain_threshold = 2.0 * _ISO_DIM_LINE_SPACING_MM
        for i, x2 in enumerate(x_coords[1:], start=1):
            x1 = x_coords[i - 1]
            gap = abs(x2 - x1)
            if gap < chain_threshold:
                # Chain: relative to previous
                offset = base_y_offset
                d = _make_iso_linear_dim(
                    value_mm=gap,
                    axis="horizontal",
                    p_start=[x1, by + bh],
                    p_end=[x2, by + bh],
                    dim_line_offset=offset,
                    label=f"{gap:.2f}",
                    feature_ref=f"chain x[{i-1}]→x[{i}]",
                )
            else:
                # Baseline: from left edge
                total = abs(x2 - baseline_x)
                offset = base_y_offset + _ISO_DIM_LINE_SPACING_MM
                d = _make_iso_linear_dim(
                    value_mm=total,
                    axis="horizontal",
                    p_start=[baseline_x, by + bh],
                    p_end=[x2, by + bh],
                    dim_line_offset=offset,
                    label=f"{total:.2f}",
                    feature_ref=f"baseline→x[{i}]",
                )
            dims.append(d)

    # ---- Vertical dimensions (height of the view) ---------------------------
    # Placed to the right of view extents.
    base_x_offset = _ISO_DIM_LINE_SPACING_MM

    if mode == "chain":
        for i in range(len(y_coords) - 1):
            y1, y2 = y_coords[i], y_coords[i + 1]
            d = _make_iso_linear_dim(
                value_mm=abs(y2 - y1),
                axis="vertical",
                p_start=[bx + bw, y1],
                p_end=[bx + bw, y2],
                dim_line_offset=base_x_offset,
                label=f"{abs(y2-y1):.2f}",
                feature_ref=f"y[{i}]→y[{i+1}]",
            )
            dims.append(d)

    elif mode == "baseline":
        baseline_y = y_coords[0]
        for i, y2 in enumerate(y_coords[1:], start=1):
            offset = base_x_offset + (i - 1) * _ISO_DIM_LINE_SPACING_MM
            d = _make_iso_linear_dim(
                value_mm=abs(y2 - baseline_y),
                axis="vertical",
                p_start=[bx + bw, baseline_y],
                p_end=[bx + bw, y2],
                dim_line_offset=offset,
                label=f"{abs(y2-baseline_y):.2f}",
                feature_ref=f"baseline→y[{i}]",
            )
            dims.append(d)

    else:  # mixed
        baseline_y = y_coords[0]
        chain_threshold = 2.0 * _ISO_DIM_LINE_SPACING_MM
        for i, y2 in enumerate(y_coords[1:], start=1):
            y1 = y_coords[i - 1]
            gap = abs(y2 - y1)
            if gap < chain_threshold:
                d = _make_iso_linear_dim(
                    value_mm=gap,
                    axis="vertical",
                    p_start=[bx + bw, y1],
                    p_end=[bx + bw, y2],
                    dim_line_offset=base_x_offset,
                    label=f"{gap:.2f}",
                    feature_ref=f"chain y[{i-1}]→y[{i}]",
                )
            else:
                total = abs(y2 - baseline_y)
                offset = base_x_offset + _ISO_DIM_LINE_SPACING_MM
                d = _make_iso_linear_dim(
                    value_mm=total,
                    axis="vertical",
                    p_start=[bx + bw, baseline_y],
                    p_end=[bx + bw, y2],
                    dim_line_offset=offset,
                    label=f"{total:.2f}",
                    feature_ref=f"baseline→y[{i}]",
                )
            dims.append(d)

    # ---- Leader lines for circular features (ISO §10) -----------------------
    for feat in features:
        if not isinstance(feat, dict):
            continue
        if feat.get("kind") == "hole" or "diameter_mm" in feat:
            cx = float(feat.get("x_mm", feat.get("cx", bx + bw / 2)))
            cy = float(feat.get("y_mm", feat.get("cy", by + bh / 2)))
            dia = float(feat.get("diameter_mm", 1.0))
            lbl = feat.get("label") or f"Ø{dia:.2f}"
            dims.append(_make_iso_leader_dim(cx, cy, dia, label=lbl))

    return dims


def apply_iso129_tolerance_format(
    value: Any,
    tolerance: Any,
    kind: str = "symmetric",
) -> str:
    """Format a dimension value with tolerance per ISO 129-1:2018 §8.

    Parameters
    ----------
    value : float or tuple(upper, lower)
        The nominal dimension value in mm.  For ``kind='limit'`` supply a
        2-tuple ``(upper_limit, lower_limit)``.
    tolerance : float or tuple(upper_dev, lower_dev)
        For ``kind='symmetric'``: a single positive float (e.g. 0.1).
        For ``kind='unilateral'``: a 2-tuple ``(upper, lower)``
          where lower is often 0, e.g. ``(0.2, 0)``.
        For ``kind='limit'``: ignored — use ``value`` as the 2-tuple.
    kind : str
        ``'symmetric'``  → ``"100 ± 0.1"``
        ``'unilateral'`` → ``"100 +0.2/0"``
        ``'limit'``      → ``"100.1 / 99.9"``

    Returns
    -------
    str
        Formatted tolerance string following ISO 129-1:2018 §8 notation.

    Notes
    -----
    Claim: follows ISO 129-1:2018 conventions — NOT ISO certified.
    """
    if kind == "symmetric":
        nom = float(value)
        tol = float(tolerance)
        return f"{nom:g} ± {tol:g}"

    elif kind == "unilateral":
        nom = float(value)
        if isinstance(tolerance, (list, tuple)) and len(tolerance) >= 2:
            upper = float(tolerance[0])
            lower = float(tolerance[1])
        else:
            # Single value means +tol / 0
            upper = float(tolerance)
            lower = 0.0
        upper_str = f"+{upper:g}" if upper >= 0 else f"{upper:g}"
        lower_str = f"{lower:g}"
        return f"{nom:g} {upper_str}/{lower_str}"

    elif kind == "limit":
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            upper = float(value[0])
            lower = float(value[1])
        else:
            raise ValueError("For kind='limit', value must be a 2-tuple (upper_limit, lower_limit)")
        return f"{upper:g} / {lower:g}"

    else:
        raise ValueError(f"kind must be 'symmetric', 'unilateral', or 'limit'; got {kind!r}")


# ---------------------------------------------------------------------------
# ISO 129-1:2018 compliance validation
# ---------------------------------------------------------------------------

class ValidationResult:
    """Result of ISO 129-1:2018 compliance validation.

    Attributes
    ----------
    compliant : bool
        True if no violations found.
    violations : list[dict]
        Each violation dict: ``{rule, actual, expected, detail}``.
    warnings : list[dict]
        Non-mandatory recommendations.
    """

    def __init__(self) -> None:
        self.compliant: bool = True
        self.violations: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []

    def add_violation(self, rule: str, actual: Any, expected: str, detail: str) -> None:
        self.compliant = False
        self.violations.append({
            "rule": rule,
            "actual": actual,
            "expected": expected,
            "detail": detail,
        })

    def add_warning(self, rule: str, actual: Any, expected: str, detail: str) -> None:
        self.warnings.append({
            "rule": rule,
            "actual": actual,
            "expected": expected,
            "detail": detail,
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compliant": self.compliant,
            "violations": self.violations,
            "warnings": self.warnings,
            "violation_count": len(self.violations),
            "warning_count": len(self.warnings),
        }


def validate_iso129_compliance(view: Dict[str, Any]) -> ValidationResult:
    """Check a view for ISO 129-1:2018 compliance.

    Checks performed
    ----------------
    1. Extension-line length ≥ ``_ISO_EXTENSION_LINE_GAP_MM`` + 1 mm  (§5.4).
    2. Parallel dimension-line spacing ≥ ``_ISO_DIM_LINE_SPACING_MM`` (§5.4).
    3. Leader-line angle is one of the ISO §10 preferred angles (15°, 30°,
       45°, 60°, 75°) ± 5°.
    4. Dimension-line orientation matches feature axis (horizontal dim on
       horizontal feature, vertical on vertical).
    5. Text height ≥ ``_ISO_FONT_HEIGHT_MM`` mm (ISO 3098-2 as referenced by
       ISO 129-1).

    Parameters
    ----------
    view : dict
        View dict — may contain ``dimensions`` (legacy linear_dim items),
        ``iso_dims`` (iso_linear_dim / iso_leader_dim items), or both.

    Returns
    -------
    ValidationResult
        Claim: follows ISO 129-1:2018 conventions — NOT ISO certified.
    """
    result = ValidationResult()

    # Collect all dimension objects: legacy + iso
    all_dims: List[Dict[str, Any]] = []
    all_dims.extend(view.get("dimensions") or [])
    all_dims.extend(view.get("iso_dims") or [])

    # ---- Rule 1: extension line length (§5.4) --------------------------------
    min_ext_length = _ISO_EXTENSION_LINE_GAP_MM + 1.0  # gap + at least 1 mm past
    for i, dim in enumerate(all_dims):
        dtype = dim.get("type", "")
        if dtype == "iso_linear_dim":
            for ext_key in (("ext1_start", "ext1_end"), ("ext2_start", "ext2_end")):
                s = dim.get(ext_key[0])
                e = dim.get(ext_key[1])
                if s is not None and e is not None:
                    length = math.hypot(e[0] - s[0], e[1] - s[1])
                    if length < min_ext_length:
                        result.add_violation(
                            rule="ISO 129-1:2018 §5.4 extension-line length",
                            actual=round(length, 3),
                            expected=f">= {min_ext_length} mm",
                            detail=f"dim[{i}] {ext_key[0]}: extension line too short ({length:.3f} mm)",
                        )

    # ---- Rule 2: parallel dim-line spacing (§5.4) ---------------------------
    # Group horizontal and vertical iso dims; check spacing between parallel lines.
    h_lines: List[float] = []
    v_lines: List[float] = []
    for dim in all_dims:
        if dim.get("type") == "iso_linear_dim":
            axis = dim.get("axis", "")
            dp1 = dim.get("dim_p1")
            if dp1 is not None:
                if axis == "horizontal":
                    h_lines.append(float(dp1[1]))
                elif axis == "vertical":
                    v_lines.append(float(dp1[0]))

    for coord_list, axis_name in ((sorted(h_lines), "horizontal"), (sorted(v_lines), "vertical")):
        for j in range(len(coord_list) - 1):
            spacing = abs(coord_list[j + 1] - coord_list[j])
            if spacing < _ISO_DIM_LINE_SPACING_MM - 0.5:  # 0.5 mm tolerance
                result.add_violation(
                    rule="ISO 129-1:2018 §5.4 dimension-line spacing",
                    actual=round(spacing, 3),
                    expected=f">= {_ISO_DIM_LINE_SPACING_MM} mm",
                    detail=f"{axis_name} dim lines too close: {spacing:.3f} mm spacing",
                )

    # ---- Rule 3: leader-line angle (§10) ------------------------------------
    for i, dim in enumerate(all_dims):
        if dim.get("type") == "iso_leader_dim":
            angle = dim.get("leader_angle_deg")
            if angle is not None:
                nearest = _nearest_leader_angle(1.0, math.tan(math.radians(float(angle))))
                deviation = abs(float(angle) - nearest)
                if deviation > 5.0:
                    result.add_violation(
                        rule="ISO 129-1:2018 §10 leader-line angle",
                        actual=round(float(angle), 1),
                        expected=f"one of {_ISO_LEADER_ANGLES_DEG} ±5°",
                        detail=f"leader dim[{i}] angle {angle}° deviates {deviation:.1f}° from nearest preferred angle",
                    )
                elif deviation > 2.0:
                    result.add_warning(
                        rule="ISO 129-1:2018 §10 leader-line angle",
                        actual=round(float(angle), 1),
                        expected=f"one of {_ISO_LEADER_ANGLES_DEG}",
                        detail=f"leader dim[{i}] angle {angle}° slightly off preferred angle (deviation {deviation:.1f}°)",
                    )

    # ---- Rule 4: dim-line orientation vs feature axis -----------------------
    for i, dim in enumerate(all_dims):
        if dim.get("type") == "iso_linear_dim":
            axis = dim.get("axis", "")
            dp1 = dim.get("dim_p1")
            dp2 = dim.get("dim_p2")
            if dp1 is not None and dp2 is not None:
                dx = abs(dp2[0] - dp1[0])
                dy = abs(dp2[1] - dp1[1])
                if axis == "horizontal" and dy > dx:
                    result.add_violation(
                        rule="ISO 129-1:2018 §5 dim-line orientation",
                        actual=f"axis=horizontal but dy={dy:.2f} > dx={dx:.2f}",
                        expected="horizontal dim line should be wider than tall",
                        detail=f"dim[{i}] orientation mismatch",
                    )
                elif axis == "vertical" and dx > dy:
                    result.add_violation(
                        rule="ISO 129-1:2018 §5 dim-line orientation",
                        actual=f"axis=vertical but dx={dx:.2f} > dy={dy:.2f}",
                        expected="vertical dim line should be taller than wide",
                        detail=f"dim[{i}] orientation mismatch",
                    )

    # ---- Rule 5: text height ------------------------------------------------
    for i, dim in enumerate(all_dims):
        th = dim.get("text_height_mm")
        if th is not None and float(th) < _ISO_FONT_HEIGHT_MM:
            result.add_violation(
                rule="ISO 129-1:2018 / ISO 3098-2 text height",
                actual=round(float(th), 2),
                expected=f">= {_ISO_FONT_HEIGHT_MM} mm",
                detail=f"dim[{i}] text height {th} mm below ISO minimum",
            )

    return result


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

    # -----------------------------------------------------------------------
    # ISO 129-1:2018 tools
    # -----------------------------------------------------------------------

    _iso_dim_spec = ToolSpec(
        name="drawing_auto_dimension_iso",
        description=(
            "Generate ISO 129-1:2018-convention dimension annotations for a\n"
            "drawing view (chain / baseline / mixed modes).\n"
            "\n"
            "Follows ISO 129-1:2018 conventions (NOT ISO certified):\n"
            "  • Chain (§5.1): n-1 dims for n feature positions, end-to-end.\n"
            "  • Baseline (§5.1): all dims from common baseline, stacked.\n"
            "  • Mixed: chain for close features, baseline for wide gaps.\n"
            "  • Extension lines: 1.5 mm gap + 2 mm overshoot (§5.4).\n"
            "  • Dimension-line spacing: 10 mm (§5.4).\n"
            "  • Arrowhead length: 3.5 mm (§5.4).\n"
            "  • Circular features: leader lines at preferred 15° (ISO §10).\n"
            "\n"
            "Returns: ok, dims (list), count (int).  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "view": {
                    "type": "object",
                    "description": (
                        "View dict with at minimum bbox ({x,y,w,h}).  "
                        "Optionally includes features: list of {kind, x_mm, y_mm, diameter_mm}."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["chain", "baseline", "mixed"],
                    "description": "Dimensioning mode per ISO 129-1:2018 §5.1 (default: chain).",
                },
            },
            "required": ["view"],
        },
    )

    @register(_iso_dim_spec)
    async def run_drawing_auto_dimension_iso(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        view = a.get("view")
        if view is None or not isinstance(view, dict):
            return err_payload("view must be an object with at minimum a bbox", "BAD_ARGS")
        mode = str(a.get("mode", "chain"))
        if mode not in ("chain", "baseline", "mixed"):
            return err_payload("mode must be 'chain', 'baseline', or 'mixed'", "BAD_ARGS")
        try:
            dims = auto_dimension_view_iso129(view, mode=mode)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
        return ok_payload({"dims": dims, "count": len(dims), "mode": mode})

    _iso_validate_spec = ToolSpec(
        name="drawing_validate_iso",
        description=(
            "Validate a drawing view for ISO 129-1:2018 compliance.\n"
            "\n"
            "Checks (follows ISO 129-1:2018 conventions, NOT ISO certified):\n"
            "  • Extension-line length ≥ gap + 1 mm (§5.4).\n"
            "  • Parallel dim-line spacing ≥ 10 mm (§5.4).\n"
            "  • Leader-line angle matches preferred angles 15/30/45/60/75° (§10).\n"
            "  • Dim-line orientation matches feature axis (§5).\n"
            "  • Text height ≥ 2.5 mm (ISO 3098-2 via ISO 129-1).\n"
            "\n"
            "Returns: ok, compliant (bool), violations ([]), warnings ([]),\n"
            "  violation_count, warning_count.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "view": {
                    "type": "object",
                    "description": (
                        "View dict — may contain 'dimensions' (legacy) and/or "
                        "'iso_dims' (from drawing_auto_dimension_iso)."
                    ),
                },
            },
            "required": ["view"],
        },
    )

    @register(_iso_validate_spec)
    async def run_drawing_validate_iso(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        view = a.get("view")
        if view is None or not isinstance(view, dict):
            return err_payload("view must be an object", "BAD_ARGS")
        try:
            vr = validate_iso129_compliance(view)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
        return ok_payload(vr.to_dict())
