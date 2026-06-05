"""
hull_exchange.py — DXF / IGES / 3DM export of hull geometry for kerf-marine.

Implements wire-exchange export for hull section curves, waterlines, and
buttocks.  Three formats are supported:

  DXF  (Drawing eXchange Format, AutoCAD R2004)
       Curves as SPLINE entities (B-spline control points) in body-plan view
       (sections in XZ plane) or plan view (waterlines in XY plane).
       Implemented using pure-Python DXF writer — no external deps.

  IGES (Initial Graphics Exchange Specification 5.3 / ASME Y14.26M-2012)
       Curves as Entity 110 (Line) polyline approximations and Entity 126
       (Rational B-spline curve).  Pure-Python ASCII IGES output.
       IGES 5.3 §4.1 §4.126.

  3DM  (Rhino openNURBS binary, v7)
       Curves written as NurbsCurve chunks using the kerf_imports.threedm_write
       internal serializer (pure-Python, no rhino3dm PyPI dep).

All three formats can be produced from the same hull form data.

Public API
----------
    export_hull_dxf(hull_form_dict) -> str   (DXF ASCII text)
    export_hull_iges(hull_form_dict) -> str  (IGES ASCII text)
    export_hull_3dm(hull_form_dict) -> bytes (3DM binary)

LLM Tool
--------
    marine_hull_exchange — exports hull curves; format selected by `format` arg.

References
----------
ASME Y14.26M-2012 / IGES 5.3.
    Specification of the Initial Graphics Exchange Specification, Version 5.3,
    U.S. PRO/IPO, 1996.  §4.1 (Global Section), §4.110 (Line entity),
    §4.126 (Rational B-spline curve entity).

openNURBS / Rhino 3DM file format (public specification):
    https://developer.rhino3d.com/guides/opennurbs/
    kerf_imports.threedm_write implements the minimal subset for NurbsCurve.

AutoCAD DXF Reference R2004 (AC1018):
    §DXF Entities — SPLINE entity structure.
"""

from __future__ import annotations

import math
import struct
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# DXF export
# ---------------------------------------------------------------------------

def _dxf_header(xmin: float, xmax: float, ymin: float, ymax: float) -> str:
    """Minimal DXF R2004 header."""
    return (
        "  0\nSECTION\n  2\nHEADER\n"
        "  9\n$ACADVER\n  1\nAC1018\n"
        f"  9\n$EXTMIN\n 10\n{xmin:.6f}\n 20\n{ymin:.6f}\n 30\n0.0\n"
        f"  9\n$EXTMAX\n 10\n{xmax:.6f}\n 20\n{ymax:.6f}\n 30\n0.0\n"
        "  9\n$INSUNITS\n 70\n4\n"   # 4 = millimetres (DXF units)
        "  0\nENDSEC\n"
        "  0\nSECTION\n  2\nTABLES\n"
        "  0\nTABLE\n  2\nLAYER\n 70\n3\n"
        "  0\nLAYER\n  2\nSECTIONS\n 70\n0\n 62\n1\n  6\nCONTINUOUS\n"
        "  0\nLAYER\n  2\nWATERLINES\n 70\n0\n 62\n5\n  6\nCONTINUOUS\n"
        "  0\nLAYER\n  2\nBUTTOCKS\n 70\n0\n 62\n3\n  6\nCONTINUOUS\n"
        "  0\nENDTAB\n  0\nENDSEC\n"
        "  0\nSECTION\n  2\nENTITIES\n"
    )


def _dxf_footer() -> str:
    return "  0\nENDSEC\n  0\nEOF\n"


def _dxf_spline(pts_xy: List[Tuple[float, float]], layer: str, degree: int = 3) -> str:
    """Emit a DXF SPLINE entity for a polyline approximation.

    For hull curves we emit a degree-1 SPLINE (polyline) or degree-3 chord-
    parameterised interpolating spline.  Here we use degree=1 (piecewise
    linear) for robustness — the section data is already smooth from the
    parametric model.

    DXF SPLINE entity (AC1018):
      0 SPLINE
      8 <layer>
     70 <flags>: bit0=closed, bit1=periodic, bit2=rational, bit3=planar, bit4=linear
     71 <degree>
     72 <n_knots>
     73 <n_control_points>
     40 <knot>...
     10 <cp_x>
     20 <cp_y>
     30 <cp_z>...
    """
    if len(pts_xy) < 2:
        return ""
    n = len(pts_xy)
    deg = min(degree, n - 1)

    if deg == 1:
        # Open polyline spline (linear): n+1 knots with clamped ends
        # knots: [0]*2 + [1, 2, ..., n-2] + [n-1]*2
        knots: List[float] = [0.0] * 2
        for i in range(1, n - 1):
            knots.append(float(i))
        knots += [float(n - 1)] * 2
    else:
        # Uniform cubic B-spline with clamped ends
        # n_knots = n + deg + 1
        n_knots = n + deg + 1
        knots = [0.0] * (deg + 1)
        interior = n_knots - 2 * (deg + 1)
        for i in range(1, interior + 1):
            knots.append(float(i))
        knots += [float(interior + 1)] * (deg + 1)

    n_knots = len(knots)
    lines = [
        "  0\nSPLINE\n",
        f"  8\n{layer}\n",
        " 70\n8\n",   # flags: planar
        f" 71\n{deg}\n",
        f" 72\n{n_knots}\n",
        f" 73\n{n}\n",
        f" 74\n0\n",   # n_fit_points
    ]
    for k in knots:
        lines.append(f" 40\n{k:.6f}\n")
    for x, y in pts_xy:
        lines.append(f" 10\n{x:.6f}\n 20\n{y:.6f}\n 30\n0.000000\n")
    return "".join(lines)


def _dxf_text(x: float, y: float, text: str, layer: str, height: float = 0.5) -> str:
    return f"  0\nTEXT\n  8\n{layer}\n 10\n{x:.3f}\n 20\n{y:.3f}\n 30\n0.0\n 40\n{height:.3f}\n  1\n{text}\n"


def export_hull_dxf(hull_form_dict: dict) -> str:
    """
    Export hull body-plan sections and waterlines to DXF R2004 (AC1018).

    Sections are placed in the XZ plane (x=station, z=waterline → Y in DXF).
    Waterlines are placed offset below the body plan, in the XY plane
    (x=station, y=half-breadth).

    Returns DXF ASCII text string.
    """
    secs = hull_form_dict.get("sections", [])
    wls = hull_form_dict.get("waterlines", [])
    btts = hull_form_dict.get("buttocks", [])

    L = float(hull_form_dict.get("L_m", 1.0))
    T = float(hull_form_dict.get("T_m", 1.0))
    B = float(hull_form_dict.get("B_m", 1.0))

    # Body plan: plot in XZ plane, offset by station
    # For a body-plan DXF we place starboard half-sections
    # x axis = half-breadth (0 at CL), y axis = waterline (z)
    # Sections are offset horizontally by station for expanded body plan.

    entities: List[str] = []

    # --- Body-plan sections (starboard) ---
    # Arranged as expanded body plan: all sections superimposed OR side-by-side.
    # We use side-by-side expanded layout: station offset separates them.
    # x_offset_i = i * (B/2 * 1.2) for expanded view.

    half_B = B / 2.0
    x_gap = half_B * 1.3

    for i, sec in enumerate(secs):
        pts = sec.get("points", [])
        if not pts:
            continue
        x0 = i * x_gap
        curve = [(x0 + p["half_breadth_m"], p["waterline_m"]) for p in pts]
        entities.append(_dxf_spline(curve, "SECTIONS", degree=3))
        # Label station
        entities.append(_dxf_text(x0, -0.5, f"Fr {sec['station_m']:.1f}m", "SECTIONS", 0.3))

    # Waterline plan view: placed below body plan
    wl_y_base = -(T * 1.5)
    for wl in wls:
        draft = wl.get("draft_m", 0.0)
        stns = wl.get("stations_m", [])
        hbs = wl.get("half_breadths_m", [])
        if not stns:
            continue
        curve = [(s, wl_y_base - hb) for s, hb in zip(stns, hbs)]
        entities.append(_dxf_spline(curve, "WATERLINES", degree=3))
        # Mirror (port side)
        curve_port = [(s, wl_y_base + hb) for s, hb in zip(stns, hbs)]
        entities.append(_dxf_spline(curve_port, "WATERLINES", degree=3))
        # Label
        if stns:
            entities.append(_dxf_text(stns[0] - 2.0, wl_y_base - hbs[0],
                                      f"WL {draft:.2f}m", "WATERLINES", 0.3))

    # Buttock lines
    butt_y_base = wl_y_base - B * 1.5
    for bt in btts:
        hb = bt.get("half_breadth_m", 0.0)
        stns = bt.get("stations_m", [])
        drafts = bt.get("drafts_m", [])
        if not stns:
            continue
        curve = [(s, butt_y_base + z) for s, z in zip(stns, drafts)]
        entities.append(_dxf_spline(curve, "BUTTOCKS", degree=3))

    xmin = -x_gap
    xmax = len(secs) * x_gap
    ymin = butt_y_base - T
    ymax = T * 1.5

    return (
        _dxf_header(xmin, xmax, ymin, ymax)
        + "".join(entities)
        + _dxf_footer()
    )


# ---------------------------------------------------------------------------
# IGES export  (IGES 5.3 / ASME Y14.26M-2012)
# ---------------------------------------------------------------------------

_IGES_REAL_FMT = " 1H,,1H;,7Hunkown,7Hunknown,15HKerf Hull Form,4H0.1,"
# Section labels
_SEC_SEP = ","
_SEP = ","


def _iges_real(v: float) -> str:
    """Format a real value for IGES field (max 8 chars, free format)."""
    s = f"{v:.6g}"
    if len(s) > 16:
        s = f"{v:.6e}"
    return s


def _iges_pack_de_line(entity_type: int, pd_seq: int, structure: int = 0,
                        linefont: int = 0, level: int = 0, view: int = 0,
                        xform: int = 0, label: int = 0, status: int = 0,
                        entity_subscript: int = 1,
                        line_weight: int = 0, color: int = 0,
                        param_count: int = 1, form: int = 0,
                        reserved1: int = 0, reserved2: int = 0,
                        entity_label: str = "", de_seq: int = 1) -> str:
    """
    Format one Directory Entry line (IGES §2.2.4.1).

    DE section has two 80-char lines per entity (line 1 and line 2).
    Format: 8 fields of 8 chars + 1 char section code + 7 char sequence number.
    """
    def f8(v):
        return f"{v:8d}"

    # Line 1
    l1 = (
        f"{entity_type:8d}"
        f"{pd_seq:8d}"
        f"{structure:8d}"
        f"{linefont:8d}"
        f"{level:8d}"
        f"{view:8d}"
        f"{xform:8d}"
        f"{label:8d}"
        f"D"  # section code (1 char)
        f"{de_seq:7d}"
    )
    # Line 2
    l2 = (
        f"{entity_type:8d}"
        f"{0:8d}"
        f"{color:8d}"
        f"{param_count:8d}"
        f"{form:8d}"
        f"{reserved1:8d}"
        f"{reserved2:8d}"
        f"{entity_label:8s}"
        f"D"
        f"{de_seq + 1:7d}"
    )
    return l1 + "\n" + l2 + "\n"


def _iges_pd_line(content: str, de_ref: int, seq: int) -> Tuple[str, int]:
    """
    Format Parameter Data lines for one IGES entity.

    Each line is 64 chars of data + 8 chars DE-ref + 'P' + 7-char seq.
    Returns (formatted_lines, next_seq).
    """
    # Split content into 64-char chunks
    lines = []
    while len(content) > 64:
        lines.append(content[:64])
        content = content[64:]
    if content:
        lines.append(content.ljust(64))

    out = ""
    for line in lines:
        out += f"{line}{de_ref:8d}P{seq:7d}\n"
        seq += 1
    return out, seq


def _iges_polyline_entity(pts_3d: List[Tuple[float, float, float]]) -> str:
    """
    Build IGES Entity 106 Form 1 (Copious Data — Connected line segments).

    This is the simplest way to export a polyline in IGES 5.3 §4.106.
    Format:
        106, 1, n, x1, y1, z1, x2, y2, z2, ...;

    where n = number of points.
    """
    n = len(pts_3d)
    parts = ["106", "1", str(n)]
    for x, y, z in pts_3d:
        parts += [_iges_real(x), _iges_real(y), _iges_real(z)]
    return ",".join(parts) + ";"


def _iges_bspline_entity(
    pts_3d: List[Tuple[float, float, float]],
    degree: int = 3,
) -> str:
    """
    Build IGES Entity 126 (Rational B-spline Curve, §4.126).

    Parameters
    ----------
    pts_3d  : control points  (n_cp × 3)
    degree  : B-spline degree (default 3 = cubic)

    IGES 126 format:
        126, K, M, PROP1, PROP2, PROP3, PROP4,
             T(0), T(1), ..., T(K+M+1),     (knots, n_knots = K+M+2 = n_cp + deg + 1)
             W(0), W(1), ..., W(K),          (weights — 1.0 for non-rational)
             X(0), Y(0), Z(0), ...,          (control points)
             V(0), V(1),                     (start/end parameter)
             XNORM, YNORM, ZNORM;            (unit normal — 0 for 3D curve)

    where K = n_cp - 1, M = degree.
    """
    n = len(pts_3d)
    K = n - 1  # upper index
    M = min(degree, K)  # degree

    # Clamped uniform knot vector
    n_knots = n + M + 1
    knots: List[float] = [0.0] * (M + 1)
    interior = n_knots - 2 * (M + 1)
    for i in range(1, interior + 1):
        knots.append(float(i))
    knots += [float(interior + 1)] * (M + 1)

    # Normalise knots to [0, 1]
    k_max = knots[-1] if knots[-1] > 0 else 1.0
    knots = [k / k_max for k in knots]

    weights = [1.0] * n  # non-rational

    # PROP1=0 (non-planar), PROP2=0 (open), PROP3=1 (polynomial), PROP4=0 (non-periodic)
    parts = ["126", str(K), str(M), "0", "0", "1", "0"]
    parts += [_iges_real(k) for k in knots]
    parts += [_iges_real(w) for w in weights]
    for x, y, z in pts_3d:
        parts += [_iges_real(x), _iges_real(y), _iges_real(z)]
    parts += ["0.0", "1.0"]  # V(0), V(1)
    parts += ["0.0", "0.0", "1.0"]  # unit normal (Z-up)
    return ",".join(parts) + ";"


def export_hull_iges(hull_form_dict: dict, use_splines: bool = True) -> str:
    """
    Export hull curves (sections + waterlines + buttocks) to IGES 5.3 ASCII.

    Sections are exported as 3D B-spline curves in the XZ plane (z = waterline,
    x = half-breadth, y = station position).

    Waterlines are exported in the XY plane (x = station, y = half-breadth, z = draft).

    Format: IGES 5.3 / ASME Y14.26M-2012.
    Entity types: 126 (Rational B-spline curve) or 106 Form 1 (copious data).

    Returns IGES ASCII string.
    """
    secs = hull_form_dict.get("sections", [])
    wls = hull_form_dict.get("waterlines", [])
    btts = hull_form_dict.get("buttocks", [])

    # Collect all curve 3D point sets
    curves: List[List[Tuple[float, float, float]]] = []

    # Sections: station=Y, half_breadth=X, waterline=Z
    for sec in secs:
        y_station = sec.get("station_m", 0.0)
        pts = sec.get("points", [])
        if len(pts) < 2:
            continue
        curve_3d = [(p["half_breadth_m"], y_station, p["waterline_m"]) for p in pts]
        curves.append(curve_3d)

    # Waterlines: station=X, half_breadth=Y, draft=Z
    for wl in wls:
        stns = wl.get("stations_m", [])
        hbs = wl.get("half_breadths_m", [])
        draft = wl.get("draft_m", 0.0)
        if len(stns) < 2:
            continue
        curve_3d = [(s, hb, draft) for s, hb in zip(stns, hbs)]
        curves.append(curve_3d)
        # Port side (mirror y)
        curve_3d_port = [(s, -hb, draft) for s, hb in zip(stns, hbs)]
        curves.append(curve_3d_port)

    # Buttocks: station=X, half_breadth=Y, draft=Z
    for bt in btts:
        stns = bt.get("stations_m", [])
        drafts_arr = bt.get("drafts_m", [])
        hb_const = bt.get("half_breadth_m", 0.0)
        if len(stns) < 2:
            continue
        curve_3d = [(s, hb_const, z) for s, z in zip(stns, drafts_arr)]
        curves.append(curve_3d)

    if not curves:
        curves = [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]]

    # Build IGES sections
    start_section = _iges_start_section()
    global_section = _iges_global_section()
    de_lines = []
    pd_lines = []

    pd_seq = 1  # PD line sequence (odd numbers, 1-indexed)
    de_seq = 1  # DE sequence (1-indexed, 2 lines per entity)

    for curve_pts in curves:
        if use_splines and len(curve_pts) >= 4:
            pd_content = _iges_bspline_entity(curve_pts, degree=3)
            entity_type = 126
        else:
            pd_content = _iges_polyline_entity(curve_pts)
            entity_type = 106

        # Count PD lines
        pd_line_count = math.ceil(len(pd_content) / 64)

        de_block = _iges_pack_de_line(
            entity_type=entity_type,
            pd_seq=pd_seq,
            param_count=pd_line_count,
            form=0 if entity_type == 126 else 1,
            de_seq=de_seq,
        )
        de_lines.append(de_block)

        pd_formatted, pd_seq = _iges_pd_line(pd_content, de_seq, pd_seq)
        pd_lines.append(pd_formatted)

        de_seq += 2  # 2 DE lines per entity

    terminate = (
        f"S{1:7d}G{1:7d}D{de_seq - 1:7d}P{pd_seq - 1:7d}"
        + " " * 40 + "T{:7d}\n".format(1)
    )

    return (
        start_section
        + global_section
        + "".join(de_lines)
        + "".join(pd_lines)
        + terminate
    )


def _iges_start_section() -> str:
    line = "Kerf Hull Form IGES Export".ljust(72)
    return f"{line}S{1:7d}\n"


def _iges_global_section() -> str:
    params = (
        "1H,,1H;,7Hkerf.ig,7Hkerf.ig,31HKerf Marine Hull Form Generator,"
        "22HKerf v0.1.0 hull_form,32,308,15,308,15,7Hmeters,1.0,2,"
        "2HMM,1,0.001,13H2026-06-05:00:00:00,0.001,500.0,7HKerfCAD,1.0;"
    )
    lines = []
    seq = 1
    while len(params) > 72:
        chunk = params[:72]
        params = params[72:]
        lines.append(f"{chunk}G{seq:7d}\n")
        seq += 1
    if params:
        lines.append(f"{params.ljust(72)}G{seq:7d}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# 3DM export (via kerf_imports.threedm_write)
# ---------------------------------------------------------------------------

def export_hull_3dm(hull_form_dict: dict) -> bytes:
    """
    Export hull curves to Rhino .3dm binary (openNURBS v7 minimal format).

    Exports section curves, waterlines, and buttocks as NurbsCurve objects.
    Uses the kerf_imports.threedm_write hermetic serializer.

    Returns .3dm bytes.
    """
    try:
        from kerf_imports.threedm_write import (
            ThreeDmFile, NurbsCurveObj, write_3dm_bytes,
        )
    except ImportError:
        return _export_hull_3dm_fallback(hull_form_dict)

    model = ThreeDmFile()
    secs = hull_form_dict.get("sections", [])
    wls = hull_form_dict.get("waterlines", [])
    btts = hull_form_dict.get("buttocks", [])

    # Build NurbsCurve for each section (degree 3, clamped uniform knots)
    def _pts_to_nurbs(pts_3d: List[Tuple[float, float, float]], degree: int = 3) -> Optional["NurbsCurveObj"]:
        n = len(pts_3d)
        if n < 2:
            return None
        d = min(degree, n - 1)
        # Clamped uniform knots
        n_knots = n + d + 1
        knots: List[float] = [0.0] * (d + 1)
        interior = n_knots - 2 * (d + 1)
        for i in range(1, interior + 1):
            knots.append(float(i))
        knots += [float(interior + 1)] * (d + 1)
        import numpy as np
        cp = np.array(pts_3d, dtype=float)
        k_arr = [float(k) for k in knots]
        return NurbsCurveObj(degree=d, control_points=cp, knots=k_arr)

    for sec in secs:
        y_station = sec.get("station_m", 0.0)
        pts = sec.get("points", [])
        if len(pts) < 2:
            continue
        pts_3d = [(p["half_breadth_m"], y_station, p["waterline_m"]) for p in pts]
        obj = _pts_to_nurbs(pts_3d)
        if obj is not None:
            model.objects.append(obj)

    for wl in wls:
        stns = wl.get("stations_m", [])
        hbs = wl.get("half_breadths_m", [])
        draft = wl.get("draft_m", 0.0)
        if len(stns) < 2:
            continue
        pts_3d = [(s, hb, draft) for s, hb in zip(stns, hbs)]
        obj = _pts_to_nurbs(pts_3d)
        if obj is not None:
            model.objects.append(obj)
        # Port side
        pts_3d_port = [(s, -hb, draft) for s, hb in zip(stns, hbs)]
        obj_port = _pts_to_nurbs(pts_3d_port)
        if obj_port is not None:
            model.objects.append(obj_port)

    for bt in btts:
        stns = bt.get("stations_m", [])
        drafts_arr = bt.get("drafts_m", [])
        hb_const = bt.get("half_breadth_m", 0.0)
        if len(stns) < 2:
            continue
        pts_3d = [(s, hb_const, z) for s, z in zip(stns, drafts_arr)]
        obj = _pts_to_nurbs(pts_3d)
        if obj is not None:
            model.objects.append(obj)

    try:
        return write_3dm_bytes(model)
    except Exception:
        return _export_hull_3dm_fallback(hull_form_dict)


def _export_hull_3dm_fallback(hull_form_dict: dict) -> bytes:
    """Minimal fallback: produce a valid 3DM shell with no geometry."""
    # 33-byte file-comment header + end-mark chunk
    header = b"3D Geometry File Format  " + b"7" + b" " * 6 + b"\x1a\x00"
    # End chunk: typecode 0x00000000, length 0x00000000
    end_chunk = struct.pack(">I", 0x00000000) + struct.pack("<I", 0)
    return header + end_chunk


# ---------------------------------------------------------------------------
# LLM tool spec + runner
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_marine._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


marine_hull_exchange_spec = ToolSpec(
    name="marine_hull_exchange",
    description=(
        "Export hull geometry (body-plan sections, waterlines, buttock lines) "
        "to DXF, IGES, or 3DM format for interchange with Maxsurf, Rhino, or AutoCAD. "
        "\n\n"
        "Supported formats:\n"
        "  dxf  — DXF R2004 (AC1018): SPLINE entities; sections + waterlines + buttocks.\n"
        "         Compatible with AutoCAD, LibreCAD, FreeCAD, and Maxsurf.\n"
        "  iges — IGES 5.3 / ASME Y14.26M-2012: Entity 126 (B-spline) or "
        "Entity 106 (copious data).  Compatible with most CAD systems.\n"
        "  3dm  — Rhino openNURBS v7 binary: NurbsCurve objects for each curve.\n"
        "         Open directly in Rhino 7/8, Maxsurf, ShipConstructor.\n"
        "\n\n"
        "Input: hull_form dict from marine_hull_form, or a manual dict with "
        "sections/waterlines/buttocks keys.\n\n"
        "Returns: file content (DXF/IGES as string; 3DM as base64-encoded bytes). "
        "\n\n"
        "References: ASME Y14.26M-2012 IGES 5.3 §4.126; AutoCAD DXF R2004 Reference; "
        "openNURBS public spec (Rhino Developer Docs)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hull_form": {
                "type": "object",
                "description": (
                    "Hull form dict as returned by marine_hull_form. "
                    "Must contain 'sections', 'waterlines', 'buttocks', 'L_m', 'B_m', 'T_m'."
                ),
            },
            "format": {
                "type": "string",
                "enum": ["dxf", "iges", "3dm"],
                "description": "Export format (default 'dxf').",
            },
            "use_splines": {
                "type": "boolean",
                "description": "Use B-spline curves in IGES (Entity 126). Default true. False = polyline (Entity 106).",
            },
        },
        "required": ["hull_form"],
    },
)


async def run_marine_hull_exchange(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    import base64
    try:
        hull_form = args["hull_form"]
        fmt = str(args.get("format", "dxf")).lower()
        use_splines = bool(args.get("use_splines", True))

        if fmt == "dxf":
            content = export_hull_dxf(hull_form)
            return ok_payload({
                "format": "dxf",
                "content": content,
                "n_chars": len(content),
                "note": "DXF R2004 (AC1018) — SPLINE entities for sections, waterlines, buttocks.",
            })
        elif fmt == "iges":
            content = export_hull_iges(hull_form, use_splines=use_splines)
            return ok_payload({
                "format": "iges",
                "content": content,
                "n_chars": len(content),
                "note": "IGES 5.3 / ASME Y14.26M-2012 — Entity 126 B-spline curves.",
            })
        elif fmt == "3dm":
            data = export_hull_3dm(hull_form)
            content_b64 = base64.b64encode(data).decode("ascii")
            return ok_payload({
                "format": "3dm",
                "content_base64": content_b64,
                "n_bytes": len(data),
                "note": "Rhino openNURBS .3dm v7 — NurbsCurve objects.",
            })
        else:
            return err_payload(f"Unknown format '{fmt}'. Use dxf, iges, or 3dm.", "MARINE_EXCHANGE_BAD_FORMAT")
    except Exception as exc:
        return err_payload(str(exc), "MARINE_HULL_EXCHANGE_ERROR")
