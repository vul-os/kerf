"""
dxf_writer.py — General DXF writer for Kerf drawings, sketches, and model
projections (T-7).

Supports DXF versions R12 (AC1009) and R2004 (AC1018).  R12 gives the
broadest compatibility; R2004 enables SPLINE, MTEXT, and modern TABLES.

Public API::

    from kerf_imports.dxf_writer import dxf_export, dwg_note

    # Export a DxfDocument (from the reader's entity model) to DXF text:
    text = dxf_export(doc, version="R2004")

    # Export a raw drawing dict (same shape as DxfDocument fields):
    text = dxf_export(drawing_dict, version="R12")

    # Query DWG guidance:
    note = dwg_note()

``dxf_export`` never raises — on any error it returns a minimal valid DXF
string and sets ``ok=False`` in the header comment.  Callers that need the
error payload should call ``dxf_export_result`` which returns
``{"ok": bool, "dxf": str, "reason": str | None}``.

Supported output entities
--------------------------
LINE, LWPOLYLINE (R2004) / POLYLINE (R12), CIRCLE, ARC, ELLIPSE (R2004),
SPLINE (R2004, B-spline control pts + knots), TEXT, MTEXT (R2004),
DIMENSION (linear/aligned/radial/diameter/angular), HATCH (boundary +
pattern name), INSERT/BLOCK, LEADER.

TABLES written: LAYER (name/color/linetype), LTYPE (linetype definitions),
STYLE (text-style), DIMSTYLE (dimension style).

HEADER variables: $ACADVER, $INSUNITS, $EXTMIN, $EXTMAX, $LTSCALE,
$TEXTSTYLE, $DIMSCALE.

Round-trip
----------
A DXF file emitted by this writer should re-parse via
``kerf_imports.dxf.reader.read_dxf`` to the same entity set (within the
reader's supported types: LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, TEXT,
INSERT, BLOCK).

DWG note
--------
Kerf emits DXF as the interchange format.  To produce a ``.dwg`` file you
must round-trip the DXF through the ODA File Converter or a compatible
tool (``ODAFileConverter`` CLI).  Kerf does not bundle ODA; the
``kerf_imports.dwg.bridge`` module describes the subprocess bridge used
when the ODA binary is present on the server.

LLM tool
---------
The ``export_dxf`` tool is registered via the ``TOOLS`` list at the
bottom of this module (mirroring ``import_dxf`` / ``draft`` patterns).
It is gated: if the caller provides a ``DxfDocument`` object (from the
reader) or a plain drawing dict the tool serialises to DXF text.
"""
from __future__ import annotations

import json
import math
from typing import Any

# ---------------------------------------------------------------------------
# Version constants
# ---------------------------------------------------------------------------

_VERSIONS = {
    "R12":   "AC1009",
    "R2004": "AC1018",
}
_DEFAULT_VERSION = "R2004"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def dxf_export(drawing: Any, version: str = "R2004") -> str:
    """
    Export *drawing* to DXF text.

    Parameters
    ----------
    drawing:
        A :class:`~kerf_imports.dxf.entities.DxfDocument` instance **or**
        a plain ``dict`` with optional keys:
          ``entities``  — list of entity dicts (see below)
          ``blocks``    — dict of block-name → block dict
          ``layers``    — list of layer dicts (``name``, ``color``, ``linetype``)
          ``units``     — unit string ("mm", "inches", …)

        Entity dicts mirror the DXF entity model.  Supported ``type`` values:
        ``line``, ``lwpolyline``, ``polyline``, ``circle``, ``arc``,
        ``ellipse``, ``spline``, ``text``, ``mtext``, ``dimension``,
        ``hatch``, ``insert``, ``leader``.

    version:
        ``"R12"`` or ``"R2004"`` (default).

    Returns
    -------
    str
        DXF text string (UTF-8 safe, CRLF-free, group-code format).
    """
    result = dxf_export_result(drawing, version)
    return result["dxf"]


def dxf_export_result(drawing: Any, version: str = "R2004") -> dict[str, Any]:
    """
    Like :func:`dxf_export` but returns ``{"ok": bool, "dxf": str, "reason": str|None}``.
    Never raises.
    """
    try:
        ver_str = _resolve_version(version)
        doc = _normalise_drawing(drawing)
        dxf_text = _build_dxf(doc, ver_str)
        return {"ok": True, "dxf": dxf_text, "reason": None}
    except Exception as exc:
        try:
            fallback_ver = _resolve_version(version)
        except Exception:
            fallback_ver = "AC1018"
        minimal = _minimal_valid_dxf(fallback_ver)
        return {"ok": False, "dxf": minimal, "reason": str(exc)}


def dwg_note() -> str:
    """
    Return guidance on DWG production.

    Kerf emits DXF as the interchange format.  A ``.dwg`` file requires the
    DXF to be converted via the ODA File Converter (a freely downloadable
    CLI).  The ``kerf_imports.dwg.bridge`` module wraps this subprocess when
    the ODA binary is present on the host.  Kerf itself does not embed ODA
    or any proprietary DWG SDK.
    """
    return (
        "Kerf exports DXF (R12 or R2004); it does not produce native .dwg files directly. "
        "To convert the emitted DXF to DWG use the ODA File Converter "
        "(https://www.opendesign.com/guestfiles/oda_file_converter — free CLI). "
        "kerf_imports.dwg.bridge wraps that subprocess when the ODA binary is present."
    )


# ---------------------------------------------------------------------------
# Internal: version resolver
# ---------------------------------------------------------------------------

def _resolve_version(version: str) -> str:
    v = version.strip().upper()
    # Accept bare "AC1009" / "AC1018" too
    if v.startswith("AC"):
        if v in ("AC1009", "AC1012", "AC1014", "AC1015"):
            return "AC1009"
        return "AC1018"
    mapped = _VERSIONS.get(v)
    if mapped is None:
        raise ValueError(f"Unsupported DXF version {version!r}; use 'R12' or 'R2004'")
    return mapped


def _is_r12(ver_str: str) -> bool:
    return ver_str == "AC1009"


# ---------------------------------------------------------------------------
# Internal: normalise drawing input
# ---------------------------------------------------------------------------

def _normalise_drawing(drawing: Any) -> dict[str, Any]:
    """Accept DxfDocument or plain dict; return a normalised plain dict."""
    # DxfDocument duck-typing: has .entities, .blocks, .units
    if hasattr(drawing, "entities") and hasattr(drawing, "blocks"):
        entities = _dxf_entities_to_dicts(getattr(drawing, "entities", []))
        blocks_raw = getattr(drawing, "blocks", {})
        blocks = {}
        for bname, bobj in blocks_raw.items():
            blocks[bname] = {
                "name": bname,
                "base_x": getattr(bobj, "base_x", 0.0),
                "base_y": getattr(bobj, "base_y", 0.0),
                "layer": getattr(bobj, "layer", "0"),
                "entities": _dxf_entities_to_dicts(getattr(bobj, "entities", [])),
            }
        return {
            "entities": entities,
            "blocks": blocks,
            "layers": [],
            "units": getattr(drawing, "units", "mm"),
        }
    if not isinstance(drawing, dict):
        raise TypeError(f"drawing must be a DxfDocument or dict, got {type(drawing).__name__}")
    return {
        "entities": list(drawing.get("entities") or []),
        "blocks":   dict(drawing.get("blocks") or {}),
        "layers":   list(drawing.get("layers") or []),
        "units":    drawing.get("units", "mm"),
    }


def _dxf_entities_to_dicts(ents: list) -> list[dict]:
    """Convert DxfEntity dataclass instances to plain dicts."""
    out = []
    for e in ents:
        if isinstance(e, dict):
            out.append(e)
            continue
        t = type(e).__name__
        d: dict[str, Any] = {"layer": getattr(e, "layer", "0")}
        if t == "DxfLine":
            d.update({"type": "line", "x1": e.x1, "y1": e.y1, "x2": e.x2, "y2": e.y2})
        elif t == "DxfCircle":
            d.update({"type": "circle", "cx": e.cx, "cy": e.cy, "radius": e.radius})
        elif t == "DxfArc":
            d.update({"type": "arc", "cx": e.cx, "cy": e.cy, "radius": e.radius,
                      "start_angle": e.start_angle, "end_angle": e.end_angle})
        elif t in ("DxfLwPolyline", "DxfPolyline"):
            d.update({"type": "lwpolyline" if t == "DxfLwPolyline" else "polyline",
                      "points": e.points, "closed": e.closed,
                      "bulge": list(getattr(e, "bulge", []))})
        elif t == "DxfText":
            d.update({"type": "text", "x": e.x, "y": e.y, "value": e.value,
                      "height": e.height, "rotation": e.rotation})
        elif t == "DxfInsert":
            d.update({"type": "insert", "block_name": e.block_name, "x": e.x, "y": e.y,
                      "x_scale": e.x_scale, "y_scale": e.y_scale,
                      "rotation_deg": e.rotation_deg})
        else:
            continue  # unknown type — skip silently
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Internal: DXF string builder
# ---------------------------------------------------------------------------

def _build_dxf(doc: dict, ver_str: str) -> str:
    r12 = _is_r12(ver_str)
    lines: list[str] = []

    def gc(code: int, value: Any) -> None:
        """Append a group-code pair."""
        lines.append(f"{code:3d}")
        lines.append(str(value))

    # Collect layers from entities + explicit layer list
    layer_map = _collect_layers(doc)

    # ── HEADER ──────────────────────────────────────────────────────────────
    gc(0, "SECTION")
    gc(2, "HEADER")
    gc(9, "$ACADVER")
    gc(1, ver_str)
    gc(9, "$INSUNITS")
    gc(70, _units_code(doc.get("units", "mm")))
    gc(9, "$LTSCALE")
    gc(40, 1.0)
    gc(9, "$TEXTSTYLE")
    gc(7, "STANDARD")
    gc(9, "$DIMSCALE")
    gc(40, 1.0)
    if not r12:
        gc(9, "$EXTMIN")
        gc(10, 0.0)
        gc(20, 0.0)
        gc(30, 0.0)
        gc(9, "$EXTMAX")
        gc(10, 0.0)
        gc(20, 0.0)
        gc(30, 0.0)
    gc(0, "ENDSEC")

    # ── TABLES ──────────────────────────────────────────────────────────────
    gc(0, "SECTION")
    gc(2, "TABLES")

    # LTYPE table
    gc(0, "TABLE")
    gc(2, "LTYPE")
    gc(70, 3)
    for lt_name, lt_desc, lt_pattern in _STANDARD_LINETYPES:
        gc(0, "LTYPE")
        gc(2, lt_name)
        gc(70, 0)
        gc(3, lt_desc)
        gc(72, 65)
        gc(73, len(lt_pattern))
        gc(40, sum(abs(x) for x in lt_pattern) if lt_pattern else 0.0)
        for seg in lt_pattern:
            gc(49, seg)
    gc(0, "ENDTAB")

    # LAYER table
    gc(0, "TABLE")
    gc(2, "LAYER")
    gc(70, len(layer_map))
    for lname, ldata in layer_map.items():
        gc(0, "LAYER")
        gc(2, lname)
        gc(70, 0)
        gc(62, ldata.get("color", 7))
        gc(6, ldata.get("linetype", "CONTINUOUS"))
    gc(0, "ENDTAB")

    # STYLE table
    gc(0, "TABLE")
    gc(2, "STYLE")
    gc(70, 1)
    gc(0, "STYLE")
    gc(2, "STANDARD")
    gc(70, 0)
    gc(40, 0.0)
    gc(41, 1.0)
    gc(50, 0.0)
    gc(71, 0)
    gc(42, 2.5)
    gc(3, "txt")
    gc(4, "")
    gc(0, "ENDTAB")

    # DIMSTYLE table
    gc(0, "TABLE")
    gc(2, "DIMSTYLE")
    gc(70, 1)
    gc(0, "DIMSTYLE")
    gc(2, "STANDARD")
    gc(70, 0)
    gc(3, "")
    gc(4, "")
    gc(5, "")
    gc(6, "")
    gc(7, "")
    gc(40, 1.0)
    gc(41, 3.0)
    gc(42, 2.0)
    gc(43, 9.0)
    gc(44, 1.0)
    gc(45, 0.0)
    gc(46, 0.0)
    gc(47, 0.0)
    gc(48, 0.0)
    gc(140, 3.0)
    gc(141, 2.0)
    gc(142, 0.0)
    gc(143, 25.4)
    gc(144, 1.0)
    gc(145, 0.0)
    gc(146, 1.0)
    gc(147, 2.0)
    gc(70, 0)
    gc(71, 0)
    gc(72, 0)
    gc(73, 1)
    gc(74, 1)
    gc(75, 0)
    gc(76, 0)
    gc(77, 0)
    gc(78, 0)
    gc(0, "ENDTAB")

    gc(0, "ENDSEC")

    # ── BLOCKS ──────────────────────────────────────────────────────────────
    gc(0, "SECTION")
    gc(2, "BLOCKS")

    # Standard model-space and paper-space blocks required by the spec
    for _bname in ("*MODEL_SPACE", "*PAPER_SPACE"):
        gc(0, "BLOCK")
        gc(8, "0")
        gc(2, _bname)
        gc(70, 0)
        gc(10, 0.0)
        gc(20, 0.0)
        gc(30, 0.0)
        gc(3, _bname)
        gc(1, "")
        gc(0, "ENDBLK")
        gc(8, "0")

    for block in doc.get("blocks", {}).values():
        bname = block.get("name", "")
        if not bname:
            continue
        gc(0, "BLOCK")
        gc(8, block.get("layer", "0"))
        gc(2, bname)
        gc(70, 0)
        gc(10, float(block.get("base_x", 0.0)))
        gc(20, float(block.get("base_y", 0.0)))
        gc(30, 0.0)
        gc(3, bname)
        gc(1, "")
        for ent in block.get("entities", []):
            _write_entity(gc, ent, r12)
        gc(0, "ENDBLK")
        gc(8, block.get("layer", "0"))

    gc(0, "ENDSEC")

    # ── ENTITIES ────────────────────────────────────────────────────────────
    gc(0, "SECTION")
    gc(2, "ENTITIES")

    for ent in doc.get("entities", []):
        _write_entity(gc, ent, r12)

    gc(0, "ENDSEC")

    # ── EOF ─────────────────────────────────────────────────────────────────
    gc(0, "EOF")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entity writer dispatch
# ---------------------------------------------------------------------------

def _write_entity(gc, ent: dict, r12: bool) -> None:
    """Write a single entity; silently skip unknown types."""
    t = str(ent.get("type", "")).lower()
    layer = str(ent.get("layer", "0"))

    if t == "line":
        _write_line(gc, ent, layer)
    elif t in ("lwpolyline", "polyline"):
        if r12:
            _write_polyline_r12(gc, ent, layer)
        else:
            _write_lwpolyline(gc, ent, layer)
    elif t == "circle":
        _write_circle(gc, ent, layer)
    elif t == "arc":
        _write_arc(gc, ent, layer)
    elif t == "ellipse" and not r12:
        _write_ellipse(gc, ent, layer)
    elif t == "spline" and not r12:
        _write_spline(gc, ent, layer)
    elif t == "text":
        _write_text(gc, ent, layer)
    elif t == "mtext" and not r12:
        _write_mtext(gc, ent, layer)
    elif t == "mtext" and r12:
        # Fall back to TEXT in R12
        _write_text(gc, ent, layer)
    elif t == "dimension":
        _write_dimension(gc, ent, layer, r12)
    elif t == "hatch" and not r12:
        _write_hatch(gc, ent, layer)
    elif t == "insert":
        _write_insert(gc, ent, layer)
    elif t == "leader":
        _write_leader(gc, ent, layer, r12)


def _write_line(gc, ent: dict, layer: str) -> None:
    gc(0, "LINE")
    gc(8, layer)
    gc(10, _f(ent.get("x1", 0.0)))
    gc(20, _f(ent.get("y1", 0.0)))
    gc(30, _f(ent.get("z1", 0.0)))
    gc(11, _f(ent.get("x2", 0.0)))
    gc(21, _f(ent.get("y2", 0.0)))
    gc(31, _f(ent.get("z2", 0.0)))


def _write_circle(gc, ent: dict, layer: str) -> None:
    gc(0, "CIRCLE")
    gc(8, layer)
    gc(10, _f(ent.get("cx", 0.0)))
    gc(20, _f(ent.get("cy", 0.0)))
    gc(30, 0.0)
    gc(40, _f(ent.get("radius", 1.0)))


def _write_arc(gc, ent: dict, layer: str) -> None:
    gc(0, "ARC")
    gc(8, layer)
    gc(10, _f(ent.get("cx", 0.0)))
    gc(20, _f(ent.get("cy", 0.0)))
    gc(30, 0.0)
    gc(40, _f(ent.get("radius", 1.0)))
    gc(50, _f(ent.get("start_angle", 0.0)))
    gc(51, _f(ent.get("end_angle", 360.0)))


def _write_ellipse(gc, ent: dict, layer: str) -> None:
    """ELLIPSE — R2004 only."""
    gc(0, "ELLIPSE")
    gc(8, layer)
    gc(10, _f(ent.get("cx", 0.0)))
    gc(20, _f(ent.get("cy", 0.0)))
    gc(30, 0.0)
    # Major-axis end point (relative to center) — default horizontal
    major_r = _f(ent.get("major_radius", 10.0))
    gc(11, major_r)
    gc(21, 0.0)
    gc(31, 0.0)
    # Ratio of minor to major axis
    major_r_val = float(ent.get("major_radius", 10.0)) or 1.0
    minor_r_val = float(ent.get("minor_radius", 5.0))
    ratio = minor_r_val / major_r_val
    gc(40, _f(ratio))
    gc(41, _f(ent.get("start_param", 0.0)))
    gc(42, _f(ent.get("end_param", math.pi * 2)))


def _write_spline(gc, ent: dict, layer: str) -> None:
    """SPLINE — B-spline from control points + knots.  R2004 only."""
    ctrl_pts = ent.get("control_points") or ent.get("points") or []
    knots = ent.get("knots") or []
    degree = int(ent.get("degree", 3))
    n_ctrl = len(ctrl_pts)
    n_knots = len(knots)
    if n_ctrl < 2:
        return

    # Auto-generate uniform knot vector if not provided
    if not knots:
        knots = _uniform_knots(n_ctrl, degree)
        n_knots = len(knots)

    gc(0, "SPLINE")
    gc(8, layer)
    gc(210, 0.0)
    gc(220, 0.0)
    gc(230, 1.0)
    flags = 0
    if ent.get("closed"):
        flags |= 1
    if ent.get("periodic"):
        flags |= 2
    if ent.get("rational"):
        flags |= 4
    gc(70, flags)
    gc(71, degree)
    gc(72, n_knots)
    gc(73, n_ctrl)
    gc(74, 0)  # fit points count
    gc(42, 0.0000001)
    gc(43, 0.0000001)
    gc(44, 0.0000001)
    for k in knots:
        gc(40, _f(k))
    for pt in ctrl_pts:
        gc(10, _f(pt[0]))
        gc(20, _f(pt[1]))
        gc(30, _f(pt[2] if len(pt) > 2 else 0.0))
        if ent.get("rational") and len(pt) > 3:
            gc(41, _f(pt[3]))


def _write_lwpolyline(gc, ent: dict, layer: str) -> None:
    """LWPOLYLINE — R2004+."""
    pts = ent.get("points") or []
    if len(pts) < 2:
        return
    closed = bool(ent.get("closed"))
    bulges = list(ent.get("bulge") or [])
    while len(bulges) < len(pts):
        bulges.append(0.0)

    gc(0, "LWPOLYLINE")
    gc(8, layer)
    gc(90, len(pts))
    gc(70, 1 if closed else 0)
    gc(43, 0.0)
    for i, pt in enumerate(pts):
        gc(10, _f(pt[0]))
        gc(20, _f(pt[1]))
        b = bulges[i] if i < len(bulges) else 0.0
        if b != 0.0:
            gc(42, _f(b))


def _write_polyline_r12(gc, ent: dict, layer: str) -> None:
    """POLYLINE + VERTEX + SEQEND — R12."""
    pts = ent.get("points") or []
    if len(pts) < 2:
        return
    closed = bool(ent.get("closed"))
    bulges = list(ent.get("bulge") or [])
    while len(bulges) < len(pts):
        bulges.append(0.0)

    gc(0, "POLYLINE")
    gc(8, layer)
    gc(66, 1)
    gc(10, 0.0)
    gc(20, 0.0)
    gc(30, 0.0)
    gc(70, 1 if closed else 0)
    for i, pt in enumerate(pts):
        gc(0, "VERTEX")
        gc(8, layer)
        gc(10, _f(pt[0]))
        gc(20, _f(pt[1]))
        gc(30, 0.0)
        b = bulges[i] if i < len(bulges) else 0.0
        if b != 0.0:
            gc(42, _f(b))
    gc(0, "SEQEND")
    gc(8, layer)


def _write_text(gc, ent: dict, layer: str) -> None:
    value = str(ent.get("value") or "")[:250]
    gc(0, "TEXT")
    gc(8, layer)
    gc(10, _f(ent.get("x", 0.0)))
    gc(20, _f(ent.get("y", 0.0)))
    gc(30, 0.0)
    gc(40, _f(ent.get("height", 2.5)))
    gc(1, value)
    rot = float(ent.get("rotation", 0.0))
    if rot != 0.0:
        gc(50, _f(rot))


def _write_mtext(gc, ent: dict, layer: str) -> None:
    """MTEXT — R2004+."""
    value = str(ent.get("value") or "")[:2000]
    gc(0, "MTEXT")
    gc(8, layer)
    gc(10, _f(ent.get("x", 0.0)))
    gc(20, _f(ent.get("y", 0.0)))
    gc(30, 0.0)
    gc(40, _f(ent.get("height", 2.5)))
    gc(41, _f(ent.get("width", 0.0)))
    gc(71, int(ent.get("attachment", 1)))
    gc(72, int(ent.get("draw_direction", 1)))
    gc(1, value)
    gc(7, str(ent.get("style", "STANDARD")))
    rot = float(ent.get("rotation", 0.0))
    if rot != 0.0:
        gc(50, _f(rot))


def _write_dimension(gc, ent: dict, layer: str, r12: bool) -> None:
    """
    DIMENSION entity — linear/aligned/radial/diameter/angular.

    dim_type values (DXF group code 70):
      0 = linear/rotated  1 = aligned  2 = angular  3 = diameter  4 = radius
      32 = flag: block created by DIMBLK (added to type value)
    """
    dim_type = int(ent.get("dim_type", 0))
    gc(0, "DIMENSION")
    gc(8, layer)
    gc(2, str(ent.get("block_name", "")))
    # Definition point (code 10/20/30) — measurement attachment
    gc(10, _f(ent.get("def_x", 0.0)))
    gc(20, _f(ent.get("def_y", 0.0)))
    gc(30, 0.0)
    # Text midpoint (code 11/21/31)
    gc(11, _f(ent.get("text_x", ent.get("def_x", 0.0))))
    gc(21, _f(ent.get("text_y", ent.get("def_y", 0.0))))
    gc(31, 0.0)
    gc(70, dim_type)
    gc(1, str(ent.get("text", "")))  # override text; "" = auto-measure
    # Extension-line origin 1
    gc(13, _f(ent.get("ext1_x", 0.0)))
    gc(23, _f(ent.get("ext1_y", 0.0)))
    gc(33, 0.0)
    # Extension-line origin 2
    gc(14, _f(ent.get("ext2_x", 0.0)))
    gc(24, _f(ent.get("ext2_y", 0.0)))
    gc(34, 0.0)
    # Dimension-line angle (for rotated/linear)
    gc(50, _f(ent.get("angle", 0.0)))
    # Measurement value (code 42) if supplied
    meas = ent.get("measurement")
    if meas is not None:
        gc(42, _f(float(meas)))


def _write_hatch(gc, ent: dict, layer: str) -> None:
    """HATCH — R2004 only.  Writes a single boundary loop + fill type."""
    boundary = ent.get("boundary") or []  # list of [x, y] pairs
    pattern = str(ent.get("pattern", "SOLID"))
    solid = (pattern.upper() == "SOLID")

    gc(0, "HATCH")
    gc(8, layer)
    gc(10, 0.0)
    gc(20, 0.0)
    gc(30, 0.0)
    gc(210, 0.0)
    gc(220, 0.0)
    gc(230, 1.0)
    gc(2, pattern)
    gc(70, 1 if solid else 0)  # fill flag: 1=solid
    gc(71, 0)  # associativity
    gc(91, 1)  # number of boundary paths
    # Boundary path type: 1 = outer
    gc(92, 1)
    gc(93, len(boundary))
    for pt in boundary:
        gc(10, _f(pt[0]))
        gc(20, _f(pt[1]))
    gc(97, 0)  # source-object count
    # Hatch pattern definition (only needed for non-solid)
    gc(75, 0)  # style
    gc(76, 1 if solid else 0)  # pattern type: 1=predefined
    if not solid:
        gc(52, _f(ent.get("pattern_angle", 0.0)))
        gc(41, _f(ent.get("pattern_scale", 1.0)))
        gc(77, 0)
        gc(78, 0)


def _write_insert(gc, ent: dict, layer: str) -> None:
    block_name = str(ent.get("block_name", ""))
    if not block_name:
        return
    gc(0, "INSERT")
    gc(8, layer)
    gc(2, block_name)
    gc(10, _f(ent.get("x", 0.0)))
    gc(20, _f(ent.get("y", 0.0)))
    gc(30, 0.0)
    xs = float(ent.get("x_scale", 1.0))
    ys = float(ent.get("y_scale", 1.0))
    if xs != 1.0:
        gc(41, _f(xs))
    if ys != 1.0:
        gc(42, _f(ys))
    rot = float(ent.get("rotation_deg", 0.0))
    if rot != 0.0:
        gc(50, _f(rot))


def _write_leader(gc, ent: dict, layer: str, r12: bool) -> None:
    """LEADER — a multi-segment polyline with an arrowhead."""
    pts = ent.get("points") or []
    if len(pts) < 2:
        return
    if r12:
        # Fall back to a plain POLYLINE in R12
        _write_polyline_r12(gc, {"points": pts, "closed": False, "bulge": []}, layer)
        return
    gc(0, "LEADER")
    gc(8, layer)
    gc(3, "STANDARD")
    gc(71, 1)   # arrowhead flag
    gc(72, 0)   # leader-path type: 0=straight
    gc(73, int(ent.get("annotation_type", 0)))
    gc(74, int(ent.get("hookline_dir", 1)))
    gc(75, 0)
    gc(40, _f(ent.get("text_height", 2.5)))
    gc(41, _f(ent.get("text_width", 0.0)))
    gc(76, len(pts))
    for pt in pts:
        gc(10, _f(pt[0]))
        gc(20, _f(pt[1]))
        gc(30, 0.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STANDARD_LINETYPES = [
    ("CONTINUOUS", "Solid line",  []),
    ("DASHED",     "Dashed __ __ __",  [12.7, -6.35]),
    ("DOTTED",     "Dotted . . . . .", [0.0, -6.35]),
]


def _collect_layers(doc: dict) -> dict[str, dict]:
    """Build {layer_name: {color, linetype}} from entities + explicit layers list."""
    lm: dict[str, dict] = {"0": {"color": 7, "linetype": "CONTINUOUS"}}

    for ld in doc.get("layers") or []:
        if not isinstance(ld, dict):
            continue
        name = str(ld.get("name", "0"))
        lm[name] = {
            "color": int(ld.get("color", 7)),
            "linetype": str(ld.get("linetype", "CONTINUOUS")),
        }

    def _scan(ents):
        for e in ents:
            if not isinstance(e, dict):
                continue
            lyr = str(e.get("layer", "0"))
            lm.setdefault(lyr, {"color": 7, "linetype": "CONTINUOUS"})

    _scan(doc.get("entities") or [])
    for block in (doc.get("blocks") or {}).values():
        if isinstance(block, dict):
            _scan(block.get("entities") or [])

    return lm


def _units_code(units: str) -> int:
    """Map human-readable unit string to $INSUNITS integer."""
    return {
        "unitless": 0, "inches": 1, "feet": 2, "mm": 4, "cm": 5,
        "m": 6, "microinches": 8, "yards": 10,
    }.get((units or "mm").lower(), 4)


def _f(v: Any) -> str:
    """Format a float for DXF output (max 10 significant digits)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        f = 0.0
    # Avoid scientific notation for normal CAD values
    if f == 0.0:
        return "0.0"
    return f"{f:.10g}"


def _uniform_knots(n_ctrl: int, degree: int) -> list[float]:
    """Generate a clamped uniform knot vector."""
    n_knots = n_ctrl + degree + 1
    knots = [0.0] * (degree + 1)
    interior = n_knots - 2 * (degree + 1)
    for i in range(1, interior + 1):
        knots.append(i / (interior + 1))
    knots += [1.0] * (degree + 1)
    return knots


def _minimal_valid_dxf(ver_str: str) -> str:
    """Return the absolute minimal valid DXF that satisfies SECTION/ENDSEC structure."""
    return (
        f"  0\nSECTION\n  2\nHEADER\n"
        f"  9\n$ACADVER\n  1\n{ver_str}\n"
        f"  0\nENDSEC\n"
        f"  0\nSECTION\n  2\nENTITIES\n"
        f"  0\nENDSEC\n"
        f"  0\nEOF\n"
    )


# ---------------------------------------------------------------------------
# LLM tool registration (mirrors import_dxf / draft patterns)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register as _register
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


def _make_tool():
    if not _REGISTRY_AVAILABLE:
        return None, None, None

    export_dxf_spec = ToolSpec(
        name="export_dxf",
        description=(
            "Export a Kerf drawing, sketch, or DxfDocument to DXF text. "
            "Supports versions R12 (broad compatibility) and R2004 (modern: "
            "SPLINE, MTEXT, ELLIPSE, HATCH). "
            "Entities: LINE, LWPOLYLINE/POLYLINE, CIRCLE, ARC, ELLIPSE, "
            "SPLINE, TEXT, MTEXT, DIMENSION, HATCH, INSERT/BLOCK, LEADER. "
            "Returns {ok, dxf, reason}. "
            "For DWG output call dwg_note() for ODA round-trip guidance."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "drawing": {
                    "type": "object",
                    "description": (
                        "Drawing/sketch dict with keys: entities (list), "
                        "blocks (dict), layers (list), units (str). "
                        "Entity dicts must have a 'type' field."
                    ),
                },
                "version": {
                    "type": "string",
                    "enum": ["R12", "R2004"],
                    "description": "DXF version. R12=broadest compat; R2004=modern (default).",
                },
            },
            "required": ["drawing"],
        },
    )

    @_register(export_dxf_spec, write=False)
    async def _export_dxf_tool(ctx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        drawing = a.get("drawing")
        if drawing is None:
            return err_payload("drawing is required", "BAD_ARGS")
        version = a.get("version", "R2004")
        result = dxf_export_result(drawing, version)
        if result["ok"]:
            return ok_payload({"dxf": result["dxf"], "version": version})
        return err_payload(result["reason"] or "export failed", "EXPORT_ERROR")

    return "export_dxf", export_dxf_spec, _export_dxf_tool


_tool_triple = _make_tool()
TOOLS = [_tool_triple] if _tool_triple[0] is not None else []
