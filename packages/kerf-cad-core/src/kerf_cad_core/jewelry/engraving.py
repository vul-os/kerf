"""
kerf_cad_core.jewelry.engraving
================================

Engraving / monogram / signet tools for jewellery CAD.

Provides pure-Python text-to-vector-outline generation and projection onto
curved surfaces.  No OCCT is required.  Each operation returns a spec dict
(node-spec hint) understood by the downstream occtWorker ``opEngravingApply``
handler.

Built-in stroke font
--------------------
A minimal single-stroke font covering uppercase A-Z, digits 0-9, and common
hallmark symbols (period, hyphen, ampersand, copyright, registered, degree, at).
Each glyph is defined as a list of polylines; every polyline is a list of
(x, y) tuples in a 1 x 1 em-square coordinate system (baseline at y=0,
cap-height at y=1).  Stroke width is carried separately as a fraction of
the em-square.

Operations
----------
text_on_curve
    Place a text string along a 3-D guide curve at uniform arc-length spacing,
    with the baseline tangent to the curve and the normal pointing up.

text_on_band_inner
    Project text onto the inner cylindrical surface of a ring band.  Produces
    a recessed-text spec for engraving depth suitable for hallmark/monogram.

signet_seal
    Raised or recessed text + monogram on a signet face, optional border,
    depth/relief.

monogram_compose
    2- or 3-initial monogram with classic styles: interlocked, stacked,
    encircled -- output vector outlines.

Diagnostics
-----------
All compute functions return a ``diagnostics`` sub-dict containing:
    total_stroke_length_mm  -- sum of all polyline segment lengths
    recessed_volume_mm3     -- approximate volume of removed material
    min_stroke_width_mm     -- smallest stroke in the rendered text
    tool_warning            -- non-empty when min_stroke_width_mm < threshold

LLM tools registered
--------------------
    jewelry_text_on_curve
    jewelry_text_on_band_inner
    jewelry_signet_seal
    jewelry_monogram_compose
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OP = "engraving_apply"

_DEFAULT_STROKE_WIDTH_FRAC = 0.08
_DEFAULT_MIN_TOOL_DIAMETER_MM = 0.3

_VALID_MONOGRAM_STYLES = frozenset(["interlocked", "stacked", "encircled"])
_VALID_ENGRAVING_MODES = frozenset(["recessed", "raised"])
_VALID_BORDER_SHAPES = frozenset(["none", "rectangle", "oval", "circle", "octagon"])
_VALID_TEXT_ALIGNMENTS = frozenset(["left", "center", "right"])

# ---------------------------------------------------------------------------
# Minimal single-stroke glyph font
# ---------------------------------------------------------------------------
# Each glyph: list of polylines; each polyline is a list of (x, y) tuples.
# Coordinate system: 0<=x<=advance_width, 0<=y<=1 (baseline y=0, cap y=1).


def _arc_pts(cx: float, cy: float, r: float, a0_deg: float, a1_deg: float,
             n: int = 8) -> List[Tuple[float, float]]:
    """Return n+1 points sampling an arc from a0_deg to a1_deg."""
    pts: List[Tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        a = math.radians(a0_deg + t * (a1_deg - a0_deg))
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _circle_pts(cx: float, cy: float, r: float, n: int = 16) -> List[Tuple[float, float]]:
    return _arc_pts(cx, cy, r, 0.0, 360.0, n)


_GLYPH_DATA: Dict[str, Dict] = {}


def _g(char: str, advance: float, strokes: List[List[Tuple[float, float]]]) -> None:
    _GLYPH_DATA[char] = {"strokes": strokes, "advance": advance}


# --- Uppercase letters -------------------------------------------------------

_g("A", 0.65, [
    [(0.0, 0.0), (0.325, 1.0), (0.65, 0.0)],
    [(0.1, 0.38), (0.55, 0.38)],
])
_g("B", 0.62, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.05, 1.0)] + _arc_pts(0.42, 0.75, 0.25, 90, -90, 6) + [(0.05, 0.5)],
    [(0.05, 0.5)] + _arc_pts(0.45, 0.25, 0.25, 90, -90, 6) + [(0.05, 0.0)],
])
_g("C", 0.60, [_arc_pts(0.32, 0.5, 0.45, 50, 310, 16)])
_g("D", 0.62, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.05, 1.0)] + _arc_pts(0.25, 0.5, 0.5, 90, -90, 12) + [(0.05, 0.0)],
])
_g("E", 0.56, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.05, 1.0), (0.55, 1.0)],
    [(0.05, 0.5), (0.50, 0.5)],
    [(0.05, 0.0), (0.55, 0.0)],
])
_g("F", 0.54, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.05, 1.0), (0.54, 1.0)],
    [(0.05, 0.52), (0.48, 0.52)],
])
_g("G", 0.62, [
    _arc_pts(0.32, 0.5, 0.45, 30, 340, 16) + [(0.55, 0.5)],
])
_g("H", 0.62, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.57, 0.0), (0.57, 1.0)],
    [(0.05, 0.5), (0.57, 0.5)],
])
_g("I", 0.30, [
    [(0.05, 0.0), (0.25, 0.0)],
    [(0.15, 0.0), (0.15, 1.0)],
    [(0.05, 1.0), (0.25, 1.0)],
])
_g("J", 0.44, [
    [(0.05, 1.0), (0.39, 1.0)],
    [(0.39, 1.0), (0.39, 0.2)] + _arc_pts(0.22, 0.2, 0.17, 0, -180, 8),
])
_g("K", 0.58, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.53, 1.0), (0.05, 0.5), (0.53, 0.0)],
])
_g("L", 0.50, [
    [(0.05, 1.0), (0.05, 0.0), (0.50, 0.0)],
])
_g("M", 0.70, [
    [(0.05, 0.0), (0.05, 1.0), (0.37, 0.3), (0.65, 1.0), (0.65, 0.0)],
])
_g("N", 0.62, [
    [(0.05, 0.0), (0.05, 1.0), (0.57, 0.0), (0.57, 1.0)],
])
_g("O", 0.62, [_circle_pts(0.31, 0.5, 0.45, 16)])
_g("P", 0.58, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.05, 1.0)] + _arc_pts(0.40, 0.74, 0.26, 90, -90, 8) + [(0.05, 0.48)],
])
_g("Q", 0.62, [
    _circle_pts(0.31, 0.5, 0.45, 16),
    [(0.37, 0.22), (0.57, 0.0)],
])
_g("R", 0.60, [
    [(0.05, 0.0), (0.05, 1.0)],
    [(0.05, 1.0)] + _arc_pts(0.40, 0.74, 0.26, 90, -90, 8) + [(0.05, 0.48)],
    [(0.28, 0.48), (0.57, 0.0)],
])
_g("S", 0.58, [
    _arc_pts(0.32, 0.74, 0.26, 30, 230, 10) +
    _arc_pts(0.32, 0.26, 0.26, 230, 30, 10),
])
_g("T", 0.56, [
    [(0.0, 1.0), (0.56, 1.0)],
    [(0.28, 1.0), (0.28, 0.0)],
])
_g("U", 0.60, [
    [(0.05, 1.0), (0.05, 0.22)] + _arc_pts(0.30, 0.22, 0.25, 180, 0, 10) + [(0.55, 1.0)],
])
_g("V", 0.60, [
    [(0.0, 1.0), (0.30, 0.0), (0.60, 1.0)],
])
_g("W", 0.72, [
    [(0.0, 1.0), (0.18, 0.0), (0.36, 0.55), (0.54, 0.0), (0.72, 1.0)],
])
_g("X", 0.58, [
    [(0.0, 1.0), (0.58, 0.0)],
    [(0.58, 1.0), (0.0, 0.0)],
])
_g("Y", 0.58, [
    [(0.0, 1.0), (0.29, 0.5), (0.58, 1.0)],
    [(0.29, 0.5), (0.29, 0.0)],
])
_g("Z", 0.56, [
    [(0.0, 1.0), (0.56, 1.0), (0.0, 0.0), (0.56, 0.0)],
])

# --- Digits ------------------------------------------------------------------

_g("0", 0.58, [_arc_pts(0.29, 0.5, 0.44, 0, 360, 16)])
_g("1", 0.32, [
    [(0.05, 0.75), (0.20, 1.0), (0.20, 0.0)],
    [(0.05, 0.0), (0.32, 0.0)],
])
_g("2", 0.56, [
    _arc_pts(0.32, 0.73, 0.26, 170, 10, 10) + [(0.0, 0.0), (0.56, 0.0)],
])
_g("3", 0.54, [
    _arc_pts(0.30, 0.73, 0.26, 150, -10, 8) + _arc_pts(0.30, 0.27, 0.26, 10, -150, 8),
])
_g("4", 0.58, [
    [(0.38, 0.0), (0.38, 1.0), (0.0, 0.38), (0.56, 0.38)],
])
_g("5", 0.54, [
    [(0.54, 1.0), (0.0, 1.0), (0.0, 0.55)] + _arc_pts(0.28, 0.3, 0.28, 150, -30, 10),
])
_g("6", 0.56, [
    _arc_pts(0.28, 0.28, 0.28, 270, 270 + 330, 14),
])
_g("7", 0.54, [
    [(0.0, 1.0), (0.54, 1.0), (0.20, 0.0)],
])
_g("8", 0.56, [
    _arc_pts(0.28, 0.74, 0.26, 0, 360, 12),
    _arc_pts(0.28, 0.26, 0.26, 0, 360, 12),
])
_g("9", 0.56, [
    list(reversed(_arc_pts(0.28, 0.72, 0.28, 270, 270 - 330, 14))),
])

# --- Symbols -----------------------------------------------------------------

_g(".", 0.24, [[(0.12, 0.0), (0.12, 0.07)]])
_g("-", 0.40, [[(0.04, 0.5), (0.36, 0.5)]])
_g("&", 0.64, [
    _arc_pts(0.26, 0.74, 0.26, 200, 0, 10) +
    [(0.0, 0.2)] +
    _arc_pts(0.20, 0.2, 0.20, 180, -30, 10) +
    [(0.64, 0.0)],
])
_g("©", 0.70, [
    _circle_pts(0.35, 0.5, 0.45, 16),
    _arc_pts(0.35, 0.5, 0.27, 45, 315, 12),
])
_g("®", 0.70, [
    _circle_pts(0.35, 0.5, 0.45, 16),
    _circle_pts(0.35, 0.5, 0.22, 12),
    [(0.26, 0.72), (0.47, 0.72)] + _arc_pts(0.47, 0.61, 0.11, 90, -90, 6) + [(0.26, 0.5)],
    [(0.37, 0.5), (0.50, 0.28)],
])
_g("°", 0.36, [_circle_pts(0.18, 0.78, 0.13, 12)])
_g("@", 0.70, [
    _arc_pts(0.35, 0.5, 0.20, 30, 330, 12) +
    _arc_pts(0.35, 0.5, 0.33, 330, 30, 12),
])

# Space
_GLYPH_DATA[" "] = {"strokes": [], "advance": 0.35}

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

_FALLBACK_GLYPH: Dict = {
    "strokes": [[(0.05, 0.0), (0.05, 1.0), (0.5, 1.0), (0.5, 0.0)]],
    "advance": 0.55,
}


def get_glyph(char: str) -> Dict:
    """Return glyph data for char, falling back to a simple rectangle."""
    return _GLYPH_DATA.get(char.upper(), _GLYPH_DATA.get(char, _FALLBACK_GLYPH))


def glyph_advance(char: str) -> float:
    return get_glyph(char)["advance"]


def text_width_em(text: str, kerning_em: float = 0.0) -> float:
    """Return total advance width in em-units for text with optional kerning."""
    if not text:
        return 0.0
    total = sum(glyph_advance(c) for c in text)
    total += kerning_em * max(0, len(text) - 1)
    return total


def render_text_outlines(
    text: str,
    cap_height_mm: float,
    kerning_mm: float = 0.0,
) -> Tuple[List[List[Tuple[float, float]]], float, float]:
    """Render text as a flat list of polylines in mm.

    Returns (polylines, total_width_mm, min_stroke_width_mm).
    """
    polylines: List[List[Tuple[float, float]]] = []
    x_cursor = 0.0
    scale = cap_height_mm  # 1 em-unit maps to cap_height_mm

    for char in text:
        g = get_glyph(char)
        adv = g["advance"]
        for stroke in g["strokes"]:
            if len(stroke) < 2:
                continue
            pts: List[Tuple[float, float]] = [
                (x_cursor + float(px) * scale, float(py) * scale)
                for (px, py) in stroke
            ]
            polylines.append(pts)
        x_cursor += adv * scale + kerning_mm

    total_width_mm = x_cursor - kerning_mm if text else 0.0
    min_stroke_width_mm = _DEFAULT_STROKE_WIDTH_FRAC * cap_height_mm
    return polylines, total_width_mm, min_stroke_width_mm


def _polyline_length(pts: List[Tuple[float, float]]) -> float:
    total = 0.0
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        total += math.hypot(dx, dy)
    return total


def total_stroke_length(polylines: List[List[Tuple[float, float]]]) -> float:
    """Return total arc-length of all polylines in mm."""
    return sum(_polyline_length(p) for p in polylines)


def _build_diagnostics(
    polylines: List[List[Tuple[float, float]]],
    min_stroke_width_mm: float,
    recessed_volume_mm3: float,
    min_tool_diameter_mm: float,
) -> dict:
    tsl = round(total_stroke_length(polylines), 4)
    tool_warn = ""
    if min_stroke_width_mm < min_tool_diameter_mm:
        tool_warn = (
            f"min_stroke_width_mm ({min_stroke_width_mm:.3f}) is below "
            f"min_tool_diameter_mm ({min_tool_diameter_mm:.3f}); "
            "consider increasing cap_height_mm or using a finer engraving tool."
        )
    return {
        "total_stroke_length_mm": tsl,
        "recessed_volume_mm3": round(recessed_volume_mm3, 6),
        "min_stroke_width_mm": round(min_stroke_width_mm, 4),
        "tool_warning": tool_warn,
    }


def _serialisable_polylines(
    polylines: List[List[Tuple[float, float]]],
) -> List[List[List[float]]]:
    """Convert polylines to JSON-serialisable [[x,y], ...] format."""
    return [[[round(x, 5), round(y, 5)] for x, y in pl] for pl in polylines]


# ---------------------------------------------------------------------------
# 1. text_on_curve
# ---------------------------------------------------------------------------

@dataclass
class TextOnCurveSpec:
    target_ref: str
    text: str
    cap_height_mm: float = 3.0
    kerning_mm: float = 0.0
    start_t: float = 0.0
    alignment: str = "left"
    mode: str = "recessed"
    depth_mm: float = 0.2
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM


def compute_text_on_curve(
    target_ref: str,
    text: str,
    *,
    cap_height_mm: float = 3.0,
    kerning_mm: float = 0.0,
    start_t: float = 0.0,
    alignment: str = "left",
    mode: str = "recessed",
    depth_mm: float = 0.2,
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM,
) -> dict:
    """Compute a text-on-curve engraving spec.

    Parameters
    ----------
    target_ref : str
        Id of the guide curve.
    text : str
        The string to engrave.
    cap_height_mm : float
        Capital-letter height in mm.
    kerning_mm : float
        Extra inter-character spacing in mm.
    start_t : float
        Curve parameter (0-1) of the text start point.
    alignment : str
        Text alignment relative to start_t.
    mode : str
        'recessed' or 'raised'.
    depth_mm : float
        Engraving depth in mm.
    min_tool_diameter_mm : float
        Tool-size warning threshold.

    Returns
    -------
    dict
        Node-spec with engraving_hints and diagnostics.
    """
    if not target_ref or not str(target_ref).strip():
        raise ValueError("target_ref is required")
    if not text or not str(text).strip():
        raise ValueError("text is required")
    cap_height_mm = float(cap_height_mm)
    if cap_height_mm <= 0:
        raise ValueError(f"cap_height_mm must be > 0; got {cap_height_mm}")
    depth_mm = float(depth_mm)
    if depth_mm <= 0:
        raise ValueError(f"depth_mm must be > 0; got {depth_mm}")
    start_t = float(start_t)
    if not (0.0 <= start_t <= 1.0):
        raise ValueError(f"start_t must be in [0, 1]; got {start_t}")
    alignment_key = str(alignment).strip().lower()
    if alignment_key not in _VALID_TEXT_ALIGNMENTS:
        raise ValueError(f"alignment must be one of {sorted(_VALID_TEXT_ALIGNMENTS)}")
    mode_key = str(mode).strip().lower()
    if mode_key not in _VALID_ENGRAVING_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_ENGRAVING_MODES)}")
    min_tool_diameter_mm = float(min_tool_diameter_mm)

    polylines, total_width_mm, min_sw = render_text_outlines(
        text, cap_height_mm, float(kerning_mm)
    )
    stroke_width_mm = _DEFAULT_STROKE_WIDTH_FRAC * cap_height_mm
    recessed_vol = total_stroke_length(polylines) * stroke_width_mm * depth_mm

    diagnostics = _build_diagnostics(polylines, min_sw, recessed_vol, min_tool_diameter_mm)

    return {
        "op": _OP,
        "feature": "text_on_curve",
        "target_ref": str(target_ref).strip(),
        "engraving_hints": {
            "text": text,
            "cap_height_mm": round(cap_height_mm, 4),
            "kerning_mm": round(float(kerning_mm), 4),
            "total_text_width_mm": round(total_width_mm, 4),
            "start_t": round(start_t, 6),
            "alignment": alignment_key,
            "mode": mode_key,
            "depth_mm": round(depth_mm, 4),
        },
        "outline_paths": _serialisable_polylines(polylines),
        "diagnostics": diagnostics,
    }


jewelry_text_on_curve_spec = ToolSpec(
    name="jewelry_text_on_curve",
    description=(
        "Place a text string along a 3-D guide curve on a jewelry piece.\n\n"
        "The baseline of the text is tangent to the guide curve; the normal "
        "direction points 'up' (away from the metal surface).  Arc-length "
        "spacing distributes glyphs uniformly along the curve.\n\n"
        "Required: file_id, target_ref, text, cap_height_mm.\n"
        "All dimensions in mm.  Returns outline_paths and diagnostics."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {"type": "string", "description": "Id of the guide curve."},
            "text": {"type": "string", "description": "Text string to engrave."},
            "cap_height_mm": {"type": "number", "description": "Capital-letter height in mm."},
            "kerning_mm": {"type": "number", "description": "Extra inter-character spacing in mm."},
            "start_t": {"type": "number", "description": "Curve parameter [0, 1] for text start."},
            "alignment": {
                "type": "string",
                "enum": sorted(_VALID_TEXT_ALIGNMENTS),
                "description": "Text alignment relative to start_t.",
            },
            "mode": {
                "type": "string",
                "enum": sorted(_VALID_ENGRAVING_MODES),
                "description": "'recessed' or 'raised'.",
            },
            "depth_mm": {"type": "number", "description": "Engraving depth in mm. Default 0.2."},
            "min_tool_diameter_mm": {"type": "number", "description": "Tool-size warning threshold."},
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref", "text", "cap_height_mm"],
    },
)


@register(jewelry_text_on_curve_spec, write=True)
async def run_jewelry_text_on_curve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    text = str(a.get("text", "")).strip()
    try:
        cap_height_mm = float(a["cap_height_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"cap_height_mm is required: {e}", "BAD_ARGS")

    try:
        spec = compute_text_on_curve(
            target_ref=target_ref,
            text=text,
            cap_height_mm=cap_height_mm,
            kerning_mm=float(a.get("kerning_mm", 0.0)),
            start_t=float(a.get("start_t", 0.0)),
            alignment=a.get("alignment", "left"),
            mode=a.get("mode", "recessed"),
            depth_mm=float(a.get("depth_mm", 0.2)),
            min_tool_diameter_mm=float(
                a.get("min_tool_diameter_mm", _DEFAULT_MIN_TOOL_DIAMETER_MM)
            ),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "text_on_curve")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "text_on_curve",
        "target_ref": spec["target_ref"],
        "total_text_width_mm": spec["engraving_hints"]["total_text_width_mm"],
        "diagnostics": spec["diagnostics"],
        "outline_paths": spec["outline_paths"],
    })


# ---------------------------------------------------------------------------
# 2. text_on_band_inner
# ---------------------------------------------------------------------------

@dataclass
class TextOnBandInnerSpec:
    target_ref: str
    text: str
    cap_height_mm: float = 2.0
    depth_mm: float = 0.15
    angular_offset_deg: float = 0.0
    kerning_mm: float = 0.0
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM


def compute_text_on_band_inner(
    target_ref: str,
    text: str,
    band_inner_diameter_mm: float,
    *,
    cap_height_mm: float = 2.0,
    depth_mm: float = 0.15,
    angular_offset_deg: float = 0.0,
    kerning_mm: float = 0.0,
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM,
) -> dict:
    """Compute text-on-inner-band engraving spec.

    Parameters
    ----------
    target_ref : str
        Id of the ring-band solid.
    text : str
        The string to engrave.
    band_inner_diameter_mm : float
        Inner diameter of the ring band in mm.
    cap_height_mm : float
        Letter height in mm.
    depth_mm : float
        Recessed depth into the metal (mm).
    angular_offset_deg : float
        Rotation of text start around band axis in degrees.
    kerning_mm : float
        Extra inter-character spacing in mm.
    min_tool_diameter_mm : float
        Tool-size warning threshold.

    Returns
    -------
    dict
        Node-spec with engraving_hints and diagnostics.
    """
    if not target_ref or not str(target_ref).strip():
        raise ValueError("target_ref is required")
    if not text or not str(text).strip():
        raise ValueError("text is required")
    band_inner_diameter_mm = float(band_inner_diameter_mm)
    if band_inner_diameter_mm <= 0:
        raise ValueError(f"band_inner_diameter_mm must be > 0; got {band_inner_diameter_mm}")
    cap_height_mm = float(cap_height_mm)
    if cap_height_mm <= 0:
        raise ValueError(f"cap_height_mm must be > 0; got {cap_height_mm}")
    depth_mm = float(depth_mm)
    if depth_mm <= 0:
        raise ValueError(f"depth_mm must be > 0; got {depth_mm}")
    kerning_mm = float(kerning_mm)
    min_tool_diameter_mm = float(min_tool_diameter_mm)
    angular_offset_deg = float(angular_offset_deg) % 360.0

    inner_circumference_mm = math.pi * band_inner_diameter_mm

    polylines, total_width_mm, min_sw = render_text_outlines(text, cap_height_mm, kerning_mm)
    stroke_width_mm = _DEFAULT_STROKE_WIDTH_FRAC * cap_height_mm
    recessed_vol = total_stroke_length(polylines) * stroke_width_mm * depth_mm

    diagnostics = _build_diagnostics(polylines, min_sw, recessed_vol, min_tool_diameter_mm)

    space_warning = ""
    if total_width_mm > inner_circumference_mm * 0.95:
        space_warning = (
            f"Text width ({total_width_mm:.2f} mm) exceeds 95% of inner "
            f"circumference ({inner_circumference_mm:.2f} mm); consider "
            "reducing cap_height_mm or shortening the text."
        )
    if space_warning:
        existing = diagnostics.get("tool_warning", "")
        diagnostics["tool_warning"] = (
            (existing + " | " + space_warning) if existing else space_warning
        )

    text_arc_deg = (total_width_mm / inner_circumference_mm) * 360.0

    return {
        "op": _OP,
        "feature": "text_on_band_inner",
        "target_ref": str(target_ref).strip(),
        "engraving_hints": {
            "text": text,
            "cap_height_mm": round(cap_height_mm, 4),
            "depth_mm": round(depth_mm, 4),
            "band_inner_diameter_mm": round(band_inner_diameter_mm, 4),
            "inner_circumference_mm": round(inner_circumference_mm, 4),
            "total_text_width_mm": round(total_width_mm, 4),
            "text_arc_deg": round(text_arc_deg, 4),
            "angular_offset_deg": round(angular_offset_deg, 4),
            "kerning_mm": round(kerning_mm, 4),
            "mode": "recessed",
        },
        "outline_paths": _serialisable_polylines(polylines),
        "diagnostics": diagnostics,
    }


jewelry_text_on_band_inner_spec = ToolSpec(
    name="jewelry_text_on_band_inner",
    description=(
        "Engrave text on the inner surface of a ring band.\n\n"
        "Projects text onto the inner cylindrical surface -- classic "
        "hallmark/personalisation engraving.  A diagnostic warning is emitted "
        "if the text is too wide for the inner circumference.\n\n"
        "Required: file_id, target_ref, text, band_inner_diameter_mm, cap_height_mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {"type": "string", "description": "Id of the ring-band solid."},
            "text": {"type": "string", "description": "Text to engrave."},
            "band_inner_diameter_mm": {
                "type": "number",
                "description": "Inner diameter of the ring band in mm.",
            },
            "cap_height_mm": {
                "type": "number",
                "description": "Letter height in mm. Default 2.",
            },
            "depth_mm": {
                "type": "number",
                "description": "Recessed engraving depth in mm. Default 0.15.",
            },
            "angular_offset_deg": {
                "type": "number",
                "description": "Rotation of text start around band axis. Default 0.",
            },
            "kerning_mm": {"type": "number", "description": "Extra spacing between chars. Default 0."},
            "min_tool_diameter_mm": {"type": "number", "description": "Tool-size warning threshold."},
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref", "text", "band_inner_diameter_mm", "cap_height_mm"],
    },
)


@register(jewelry_text_on_band_inner_spec, write=True)
async def run_jewelry_text_on_band_inner(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    text = str(a.get("text", "")).strip()
    try:
        band_inner_diameter_mm = float(a["band_inner_diameter_mm"])
        cap_height_mm = float(a["cap_height_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(
            f"band_inner_diameter_mm and cap_height_mm are required: {e}", "BAD_ARGS"
        )

    try:
        spec = compute_text_on_band_inner(
            target_ref=target_ref,
            text=text,
            band_inner_diameter_mm=band_inner_diameter_mm,
            cap_height_mm=cap_height_mm,
            depth_mm=float(a.get("depth_mm", 0.15)),
            angular_offset_deg=float(a.get("angular_offset_deg", 0.0)),
            kerning_mm=float(a.get("kerning_mm", 0.0)),
            min_tool_diameter_mm=float(
                a.get("min_tool_diameter_mm", _DEFAULT_MIN_TOOL_DIAMETER_MM)
            ),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "text_on_band_inner")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "text_on_band_inner",
        "target_ref": spec["target_ref"],
        "total_text_width_mm": spec["engraving_hints"]["total_text_width_mm"],
        "inner_circumference_mm": spec["engraving_hints"]["inner_circumference_mm"],
        "diagnostics": spec["diagnostics"],
        "outline_paths": spec["outline_paths"],
    })


# ---------------------------------------------------------------------------
# 3. signet_seal
# ---------------------------------------------------------------------------

@dataclass
class SignetSealSpec:
    target_ref: str
    text: str
    mode: str = "recessed"
    cap_height_mm: float = 4.0
    depth_mm: float = 0.3
    border_shape: str = "none"
    border_width_mm: float = 0.5
    kerning_mm: float = 0.0
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM


def compute_signet_seal(
    target_ref: str,
    text: str,
    *,
    mode: str = "recessed",
    cap_height_mm: float = 4.0,
    depth_mm: float = 0.3,
    border_shape: str = "none",
    border_width_mm: float = 0.5,
    kerning_mm: float = 0.0,
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM,
) -> dict:
    """Compute a signet-seal engraving spec.

    Parameters
    ----------
    target_ref : str
        Id of the signet face.
    text : str
        Text / monogram to engrave.
    mode : str
        'recessed' or 'raised'.
    cap_height_mm : float
        Letter height in mm.
    depth_mm : float
        Relief depth in mm.
    border_shape : str
        Border geometry: none, rectangle, oval, circle, or octagon.
    border_width_mm : float
        Border stroke width in mm.
    kerning_mm : float
        Inter-character spacing in mm.
    min_tool_diameter_mm : float
        Tool-size warning threshold.

    Returns
    -------
    dict
        Node-spec with engraving_hints, outline_paths, and diagnostics.
    """
    if not target_ref or not str(target_ref).strip():
        raise ValueError("target_ref is required")
    if not text or not str(text).strip():
        raise ValueError("text is required")
    cap_height_mm = float(cap_height_mm)
    if cap_height_mm <= 0:
        raise ValueError(f"cap_height_mm must be > 0; got {cap_height_mm}")
    depth_mm = float(depth_mm)
    if depth_mm <= 0:
        raise ValueError(f"depth_mm must be > 0; got {depth_mm}")
    border_width_mm = float(border_width_mm)
    if border_width_mm < 0:
        raise ValueError(f"border_width_mm must be >= 0; got {border_width_mm}")
    mode_key = str(mode).strip().lower()
    if mode_key not in _VALID_ENGRAVING_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_ENGRAVING_MODES)}")
    border_key = str(border_shape).strip().lower()
    if border_key not in _VALID_BORDER_SHAPES:
        raise ValueError(f"border_shape must be one of {sorted(_VALID_BORDER_SHAPES)}")
    kerning_mm = float(kerning_mm)
    min_tool_diameter_mm = float(min_tool_diameter_mm)

    polylines, total_width_mm, min_sw = render_text_outlines(text, cap_height_mm, kerning_mm)

    text_area_mm2 = total_width_mm * cap_height_mm * _DEFAULT_STROKE_WIDTH_FRAC
    recessed_vol = text_area_mm2 * depth_mm

    if border_key != "none" and border_width_mm > 0:
        perimeter_mm = 2.0 * (total_width_mm + cap_height_mm * 1.5)
        recessed_vol += perimeter_mm * border_width_mm * depth_mm

    diagnostics = _build_diagnostics(polylines, min_sw, recessed_vol, min_tool_diameter_mm)

    return {
        "op": _OP,
        "feature": "signet_seal",
        "target_ref": str(target_ref).strip(),
        "engraving_hints": {
            "text": text,
            "mode": mode_key,
            "cap_height_mm": round(cap_height_mm, 4),
            "depth_mm": round(depth_mm, 4),
            "total_text_width_mm": round(total_width_mm, 4),
            "border_shape": border_key,
            "border_width_mm": round(border_width_mm, 4),
            "kerning_mm": round(kerning_mm, 4),
        },
        "outline_paths": _serialisable_polylines(polylines),
        "diagnostics": diagnostics,
    }


jewelry_signet_seal_spec = ToolSpec(
    name="jewelry_signet_seal",
    description=(
        "Engrave a raised or recessed text / monogram seal on a signet face.\n\n"
        "Suitable for classic signet rings, wax-seal rings, and hallmark faces. "
        "Optional border: rectangle, oval, circle, octagon.\n\n"
        "Required: file_id, target_ref, text, cap_height_mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {"type": "string", "description": "Id of the signet face."},
            "text": {"type": "string", "description": "Text or monogram to seal-engrave."},
            "cap_height_mm": {"type": "number", "description": "Letter height in mm."},
            "mode": {
                "type": "string",
                "enum": sorted(_VALID_ENGRAVING_MODES),
                "description": "'recessed' (intaglio) or 'raised'. Default 'recessed'.",
            },
            "depth_mm": {"type": "number", "description": "Relief depth in mm. Default 0.3."},
            "border_shape": {
                "type": "string",
                "enum": sorted(_VALID_BORDER_SHAPES),
                "description": "Border shape. Default 'none'.",
            },
            "border_width_mm": {"type": "number", "description": "Border stroke width mm. Default 0.5."},
            "kerning_mm": {"type": "number", "description": "Extra spacing between chars. Default 0."},
            "min_tool_diameter_mm": {"type": "number", "description": "Tool-size warning threshold."},
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref", "text", "cap_height_mm"],
    },
)


@register(jewelry_signet_seal_spec, write=True)
async def run_jewelry_signet_seal(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    text = str(a.get("text", "")).strip()
    try:
        cap_height_mm = float(a["cap_height_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"cap_height_mm is required: {e}", "BAD_ARGS")

    try:
        spec = compute_signet_seal(
            target_ref=target_ref,
            text=text,
            mode=a.get("mode", "recessed"),
            cap_height_mm=cap_height_mm,
            depth_mm=float(a.get("depth_mm", 0.3)),
            border_shape=a.get("border_shape", "none"),
            border_width_mm=float(a.get("border_width_mm", 0.5)),
            kerning_mm=float(a.get("kerning_mm", 0.0)),
            min_tool_diameter_mm=float(
                a.get("min_tool_diameter_mm", _DEFAULT_MIN_TOOL_DIAMETER_MM)
            ),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "signet_seal")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "signet_seal",
        "target_ref": spec["target_ref"],
        "mode": spec["engraving_hints"]["mode"],
        "total_text_width_mm": spec["engraving_hints"]["total_text_width_mm"],
        "diagnostics": spec["diagnostics"],
        "outline_paths": spec["outline_paths"],
    })


# ---------------------------------------------------------------------------
# 4. monogram_compose
# ---------------------------------------------------------------------------

@dataclass
class MonogramComposeSpec:
    initials: str
    style: str = "interlocked"
    cap_height_mm: float = 6.0
    side_scale: float = 0.8
    depth_mm: float = 0.3
    mode: str = "recessed"
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM


def _monogram_bounding_box(
    polylines: List[List[Tuple[float, float]]],
) -> Tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) of all polyline points."""
    if not polylines or not any(polylines):
        return (0.0, 0.0, 0.0, 0.0)
    xs = [x for pl in polylines for (x, _y) in pl]
    ys = [y for pl in polylines for (_x, y) in pl]
    return (min(xs), min(ys), max(xs), max(ys))


def compute_monogram_compose(
    initials: str,
    *,
    style: str = "interlocked",
    cap_height_mm: float = 6.0,
    side_scale: float = 0.8,
    depth_mm: float = 0.3,
    mode: str = "recessed",
    min_tool_diameter_mm: float = _DEFAULT_MIN_TOOL_DIAMETER_MM,
) -> dict:
    """Compose a 2- or 3-initial monogram and return vector outlines + spec.

    Three styles:
    - interlocked: initials overlaid at the same centre; centre letter at
      full cap_height_mm; flanking letters at cap_height_mm x side_scale.
    - stacked: initials stacked vertically.
    - encircled: interlocked layout with an enclosing circle outline.

    Parameters
    ----------
    initials : str
        2 or 3 uppercase initials.
    style : str
        One of _VALID_MONOGRAM_STYLES.
    cap_height_mm : float
        Primary letter height in mm.
    side_scale : float
        Secondary letter scale factor (0 < side_scale <= 1.5).
    depth_mm : float
        Relief depth in mm.
    mode : str
        'recessed' or 'raised'.
    min_tool_diameter_mm : float
        Tool-size warning threshold.

    Returns
    -------
    dict
        Spec with monogram_hints, outline_paths, bounding_box, and diagnostics.
    """
    initials = str(initials).strip().upper()
    if len(initials) not in (2, 3):
        raise ValueError(f"initials must be 2 or 3 characters; got {len(initials)!r}")
    for ch in initials:
        if ch not in _GLYPH_DATA and ch.upper() not in _GLYPH_DATA:
            raise ValueError(f"Character {ch!r} is not in the built-in font.")
    style_key = str(style).strip().lower()
    if style_key not in _VALID_MONOGRAM_STYLES:
        raise ValueError(f"style must be one of {sorted(_VALID_MONOGRAM_STYLES)}")
    cap_height_mm = float(cap_height_mm)
    if cap_height_mm <= 0:
        raise ValueError(f"cap_height_mm must be > 0; got {cap_height_mm}")
    side_scale = float(side_scale)
    if not (0.0 < side_scale <= 1.5):
        raise ValueError(f"side_scale must be in (0, 1.5]; got {side_scale}")
    depth_mm = float(depth_mm)
    if depth_mm <= 0:
        raise ValueError(f"depth_mm must be > 0; got {depth_mm}")
    mode_key = str(mode).strip().lower()
    if mode_key not in _VALID_ENGRAVING_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_ENGRAVING_MODES)}")
    min_tool_diameter_mm = float(min_tool_diameter_mm)

    all_polylines: List[List[Tuple[float, float]]] = []
    min_sw = _DEFAULT_STROKE_WIDTH_FRAC * cap_height_mm

    if style_key == "stacked":
        n = len(initials)
        per_height = cap_height_mm / n
        min_sw = _DEFAULT_STROKE_WIDTH_FRAC * per_height
        y_offset = (n - 1) * per_height
        for ch in initials:
            pls, w, sw = render_text_outlines(ch, per_height, 0.0)
            if sw < min_sw:
                min_sw = sw
            x_shift = (cap_height_mm - w) / 2.0
            shifted = [[(x + x_shift, y + y_offset) for x, y in pl] for pl in pls]
            all_polylines.extend(shifted)
            y_offset -= per_height

    elif style_key in ("interlocked", "encircled"):
        n = len(initials)
        if n == 2:
            heights = [cap_height_mm, cap_height_mm]
        else:
            heights = [
                cap_height_mm * side_scale,
                cap_height_mm,
                cap_height_mm * side_scale,
            ]

        for i, (ch, ht) in enumerate(zip(initials, heights)):
            pls, w, sw = render_text_outlines(ch, ht, 0.0)
            if sw < min_sw:
                min_sw = sw
            if n == 2:
                x_shift = -w / 2.0 + (i - 0.5) * w * 0.25
            else:
                if i == 0:
                    x_shift = -w * 0.9
                elif i == 1:
                    x_shift = -w / 2.0
                else:
                    x_shift = w * 0.3
            y_shift = (cap_height_mm - ht) / 2.0
            shifted = [[(x + x_shift, y + y_shift) for x, y in pl] for pl in pls]
            all_polylines.extend(shifted)

        if style_key == "encircled":
            radius = cap_height_mm * 0.72
            circle = _circle_pts(0.0, cap_height_mm / 2.0, radius, 20)
            all_polylines.append(circle)

    xmin, ymin, xmax, ymax = _monogram_bounding_box(all_polylines)
    bbox_width = round(xmax - xmin, 4)
    bbox_height = round(ymax - ymin, 4)

    stroke_width_mm = _DEFAULT_STROKE_WIDTH_FRAC * cap_height_mm
    recessed_vol = total_stroke_length(all_polylines) * stroke_width_mm * depth_mm
    diagnostics = _build_diagnostics(all_polylines, min_sw, recessed_vol, min_tool_diameter_mm)

    return {
        "op": _OP,
        "feature": "monogram_compose",
        "monogram_hints": {
            "initials": initials,
            "style": style_key,
            "cap_height_mm": round(cap_height_mm, 4),
            "side_scale": round(side_scale, 4),
            "depth_mm": round(depth_mm, 4),
            "mode": mode_key,
            "letter_count": len(initials),
        },
        "outline_paths": _serialisable_polylines(all_polylines),
        "bounding_box": {
            "xmin_mm": round(xmin, 4),
            "ymin_mm": round(ymin, 4),
            "xmax_mm": round(xmax, 4),
            "ymax_mm": round(ymax, 4),
            "width_mm": bbox_width,
            "height_mm": bbox_height,
        },
        "diagnostics": diagnostics,
    }


jewelry_monogram_compose_spec = ToolSpec(
    name="jewelry_monogram_compose",
    description=(
        "Compose a 2- or 3-initial monogram in a classic style.\n\n"
        "Styles: interlocked (overlapping), stacked (vertical), "
        "encircled (interlocked with circle border).\n\n"
        "Returns vector outline_paths and bounding_box dimensions.\n"
        "Required: initials, cap_height_mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "initials": {
                "type": "string",
                "description": "2 or 3 uppercase initials (e.g. 'JRS', 'AB').",
            },
            "cap_height_mm": {
                "type": "number",
                "description": "Height of the primary initial in mm.",
            },
            "style": {
                "type": "string",
                "enum": sorted(_VALID_MONOGRAM_STYLES),
                "description": "Monogram composition style. Default 'interlocked'.",
            },
            "side_scale": {
                "type": "number",
                "description": "Scale of flanking initials relative to cap_height_mm. Default 0.8.",
            },
            "depth_mm": {"type": "number", "description": "Engraving depth in mm. Default 0.3."},
            "mode": {
                "type": "string",
                "enum": sorted(_VALID_ENGRAVING_MODES),
                "description": "'recessed' or 'raised'. Default 'recessed'.",
            },
            "min_tool_diameter_mm": {"type": "number", "description": "Tool-size warning threshold."},
        },
        "required": ["initials", "cap_height_mm"],
    },
)


@register(jewelry_monogram_compose_spec, write=False)
async def run_jewelry_monogram_compose(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    initials = str(a.get("initials", "")).strip()
    if not initials:
        return err_payload("initials is required", "BAD_ARGS")

    try:
        cap_height_mm = float(a["cap_height_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"cap_height_mm is required: {e}", "BAD_ARGS")

    try:
        spec = compute_monogram_compose(
            initials=initials,
            style=a.get("style", "interlocked"),
            cap_height_mm=cap_height_mm,
            side_scale=float(a.get("side_scale", 0.8)),
            depth_mm=float(a.get("depth_mm", 0.3)),
            mode=a.get("mode", "recessed"),
            min_tool_diameter_mm=float(
                a.get("min_tool_diameter_mm", _DEFAULT_MIN_TOOL_DIAMETER_MM)
            ),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    return ok_payload({
        "op": _OP,
        "feature": "monogram_compose",
        "initials": spec["monogram_hints"]["initials"],
        "style": spec["monogram_hints"]["style"],
        "bounding_box": spec["bounding_box"],
        "diagnostics": spec["diagnostics"],
        "outline_paths": spec["outline_paths"],
    })
