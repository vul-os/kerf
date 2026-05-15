"""
ODB++ fab-archive writer for CircuitJSON boards.

Produces a minimal but fab-ingerable ODB++ directory tree, then tarballs
it to a .tgz archive.  No Mentor binary or proprietary SDK required —
everything is built from plain text file writes + Python's tarfile module.

ODB++ directory layout produced
────────────────────────────────
  <stem>/
    misc/
      info              — EDA tool metadata (product name, version, units)
    steps/
      pcb/
        stephdr         — step header (board units, datum, work layers)
        layers/
          <layer>/
            attrlist    — layer attribute record (type, context, polarity)
            components  — component placement records (empty for non-copper)
            features    — feature records (lines, arcs, pads, surfaces)

Layers emitted
──────────────
  top_copper, bottom_copper,
  top_silk, bottom_silk,
  top_mask, bottom_mask,
  drill, outline

(Layer names match the layer-name convention used in gerber.py / ipc2581.py.)

Feature-record encoding
───────────────────────
  Line:    L <x1> <y1> <x2> <y2> <width> <polarity>;
  Pad:     P <x> <y> <sym> <polarity> <orient> <mirror>;
  Arc:     A <xs> <ys> <xe> <ye> <xc> <yc> <cw> <width> <polarity>;
  Surface: S <polarity>; OB <x> <y>; OS <x> <y>...; OE;

Symbols (pad shapes)
────────────────────
  Circles → r<diameter>  (ODB++ round symbol)
  Rects   → rect<width>x<height>
  Ovals   → oval<width>x<height>

Units: millimetres throughout.  ODB++ coordinates are floating-point mm.

Public API
──────────
  export_odbpp(circuit_json, stem="board") -> dict
    Returns {"tgz_bytes": bytes, "manifest": list[str]}
"""

from __future__ import annotations

import io
import math
import tarfile
import tarfile as _tarfile
from datetime import datetime, timezone
from typing import Any


# ─── constants ────────────────────────────────────────────────────────────────

_EDA_PRODUCT = "Kerf Electronics"
_EDA_VERSION = "0.1.0"

# Ordered layer list — names match gerber.py / ipc2581.py conventions
_LAYERS = [
    "top_copper",
    "bottom_copper",
    "top_silk",
    "bottom_silk",
    "top_mask",
    "bottom_mask",
    "drill",
    "outline",
]

# Layer attributes: (type, context, polarity)
# context: "board" for most; "misc" for drill
_LAYER_ATTRS: dict[str, tuple[str, str, str]] = {
    "top_copper":    ("signal",     "board",  "positive"),
    "bottom_copper": ("signal",     "board",  "positive"),
    "top_silk":      ("silk_screen","board",  "positive"),
    "bottom_silk":   ("silk_screen","board",  "positive"),
    "top_mask":      ("solder_mask","board",  "negative"),
    "bottom_mask":   ("solder_mask","board",  "negative"),
    "drill":         ("drill",      "board",  "positive"),
    "outline":       ("rout",       "board",  "positive"),
}

# Map CircuitJSON layer names → ODB++ layer names
_LAYER_ALIAS: dict[str, str] = {
    "top_copper":    "top_copper",
    "bottom_copper": "bottom_copper",
    "top_silk":      "top_silk",
    "bottom_silk":   "bottom_silk",
    "top_mask":      "top_mask",
    "bottom_mask":   "bottom_mask",
    "edge_cuts":     "outline",
    "drill":         "drill",
}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mm(v: float, prec: int = 6) -> str:
    return f"{v:.{prec}f}"


def _sym_circle(d: float) -> str:
    return f"r{d:.6f}"


def _sym_rect(w: float, h: float) -> str:
    return f"rect{w:.6f}x{h:.6f}"


def _sym_oval(w: float, h: float) -> str:
    return f"oval{w:.6f}x{h:.6f}"


# ─── CircuitJSON data extraction (mirrors ipc2581.py / gerber.py) ─────────────

def _collect_source_components(circuit_json: list[dict]) -> dict[str, dict]:
    src: dict[str, dict] = {}
    for el in circuit_json:
        if el.get("type") == "source_component":
            sid = el.get("source_component_id", el.get("id", ""))
            if sid:
                src[sid] = el
    return src


def _collect_pcb_components(circuit_json: list[dict]) -> list[dict]:
    return [el for el in circuit_json if el.get("type") == "pcb_component"]


def _board_dims(circuit_json: list[dict]) -> tuple[float, float]:
    for el in circuit_json:
        if el.get("type") in ("pcb_board", "board"):
            w = float(el.get("width", 100.0))
            h = float(el.get("height", 100.0))
            return w, h
    return 100.0, 100.0


def _outline_vertices(circuit_json: list[dict], w: float, h: float) -> list[tuple[float, float]]:
    for el in circuit_json:
        if el.get("type") == "pcb_outline_path":
            pts = el.get("route", el.get("points", []))
            if len(pts) >= 3:
                return [(float(p.get("x", 0)), float(p.get("y", 0))) for p in pts]
    cx = 0.0
    cy = 0.0
    for el in circuit_json:
        if el.get("type") in ("pcb_board", "board"):
            cx = float(el.get("center_x", el.get("x", 0)))
            cy = float(el.get("center_y", el.get("y", 0)))
            x0, y0 = cx - w / 2, cy - h / 2
            x1, y1 = cx + w / 2, cy + h / 2
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]


def _classify_elements(circuit_json: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {
        "pads": [],
        "vias": [],
        "traces": [],
        "silk_text": [],
        "silk_line": [],
        "copper_pour": [],
        "outline": [],
        "board": [],
        "holes": [],
    }
    for el in circuit_json:
        t = el.get("type", "")
        if t in ("pcb_smtpad", "pcb_pad", "pcb_plated_pad", "pcb_component_pad"):
            out["pads"].append(el)
        elif t == "pcb_via":
            out["vias"].append(el)
        elif t == "pcb_trace":
            out["traces"].append(el)
        elif t in ("pcb_silkscreen_text", "pcb_text"):
            out["silk_text"].append(el)
        elif t in ("pcb_silkscreen_line", "pcb_silkscreen_path", "pcb_line"):
            out["silk_line"].append(el)
        elif t in ("copper_pour_fill", "pcb_copper_pour"):
            out["copper_pour"].append(el)
        elif t in ("pcb_board", "board"):
            out["board"].append(el)
        elif t == "pcb_outline_path":
            out["outline"].append(el)
        elif t in ("pcb_hole", "pcb_mounting_hole"):
            out["holes"].append(el)
    return out


def _pad_layer(elem: dict) -> str:
    layer = elem.get("layer", "")
    if layer and layer in _LAYER_ALIAS:
        return _LAYER_ALIAS[layer]
    if layer:
        return layer
    side = elem.get("side", elem.get("pcb_layer", ""))
    if "bottom" in side:
        return "bottom_copper"
    return "top_copper"


def _pad_sym(elem: dict) -> str:
    shape = elem.get("shape", elem.get("pad_shape", "rect"))
    w = float(elem.get("width", elem.get("size_x", 1.5)))
    h = float(elem.get("height", elem.get("size_y", w)))
    if shape in ("circle", "round"):
        return _sym_circle(max(w, h))
    if shape in ("oblong", "oval"):
        return _sym_oval(w, h)
    return _sym_rect(w, h)


def _trace_route_points(trace: dict) -> list[dict]:
    for key in ("route", "points", "vertices"):
        pts = trace.get(key)
        if isinstance(pts, list):
            return pts
    return []


# ─── Feature-record builders per layer ───────────────────────────────────────

class _FeatureSet:
    """Accumulates ODB++ feature records for a single layer."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        # Collected symbol names (for the symbol table at the top)
        self._syms: list[str] = []
        self._sym_set: set[str] = set()

    def _add_sym(self, sym: str) -> int:
        if sym not in self._sym_set:
            self._syms.append(sym)
            self._sym_set.add(sym)
        return self._syms.index(sym)

    def line(self, x1: float, y1: float, x2: float, y2: float,
             width: float, polarity: str = "P") -> None:
        sym = _sym_circle(width)
        idx = self._add_sym(sym)
        self._lines.append(
            f"L {_mm(x1)} {_mm(y1)} {_mm(x2)} {_mm(y2)} {idx} {polarity} 0;"
        )

    def pad(self, x: float, y: float, sym: str,
            polarity: str = "P", orient: int = 0, mirror: int = 0) -> None:
        idx = self._add_sym(sym)
        self._lines.append(
            f"P {_mm(x)} {_mm(y)} {idx} {polarity} {orient} {mirror};"
        )

    def surface(self, vertices: list[tuple[float, float]],
                polarity: str = "P") -> None:
        if len(vertices) < 3:
            return
        lines = [f"S {polarity};"]
        x0, y0 = vertices[0]
        lines.append(f"OB {_mm(x0)} {_mm(y0)} I;")
        for x, y in vertices[1:]:
            lines.append(f"OS {_mm(x)} {_mm(y)};")
        # Close
        lines.append(f"OS {_mm(x0)} {_mm(y0)};")
        lines.append("OE;")
        self._lines.extend(lines)

    def render(self) -> str:
        sections: list[str] = [
            "UNITS=MM",
            "#",
            "# Feature records for Kerf Electronics ODB++ export",
            f"# Generated: {_ts()}",
            "#",
        ]
        if self._syms:
            sections.append("# SYMBOL TABLE")
            for i, sym in enumerate(self._syms):
                sections.append(f"#{i} {sym}")
            sections.append("#")
        sections.append("# FEATURES")
        sections.extend(self._lines)
        return "\n".join(sections) + "\n"


# ─── File content builders ────────────────────────────────────────────────────

def _build_misc_info(stem: str) -> str:
    return (
        f"PRODUCT={_EDA_PRODUCT}\n"
        f"VERSION={_EDA_VERSION}\n"
        f"ODB_VERSION=7.0\n"
        f"STEP_NAME=pcb\n"
        f"CREATION_DATE={_ts()}\n"
        f"UNITS=MM\n"
        f"STEP={stem}\n"
    )


def _build_stephdr(circuit_json: list[dict], stem: str) -> str:
    w, h = _board_dims(circuit_json)
    layers_section = "\n".join(f"LAYER={lyr}" for lyr in _LAYERS)
    return (
        f"STEP={stem}\n"
        f"UNITS=MM\n"
        f"DATUM_X=0.000000\n"
        f"DATUM_Y=0.000000\n"
        f"BOARD_WIDTH={_mm(w)}\n"
        f"BOARD_HEIGHT={_mm(h)}\n"
        f"WORK_LAYER=top_copper\n"
        f"#\n"
        f"# LAYER LIST\n"
        f"{layers_section}\n"
    )


def _build_attrlist(layer: str) -> str:
    ltype, ctx, polarity = _LAYER_ATTRS.get(layer, ("signal", "board", "positive"))
    return (
        f".string layer_name {layer}\n"
        f".string type {ltype}\n"
        f".string context {ctx}\n"
        f".string polarity {polarity}\n"
    )


def _build_components(layer: str,
                      pcb_components: list[dict],
                      source_map: dict[str, dict]) -> str:
    """Build ODB++ component placement file for a given layer."""
    lines = [
        f"# ODB++ component placement — layer: {layer}",
        f"# Generated: {_ts()}",
        "#",
        "UNITS=MM",
    ]

    # Only copper layers carry components
    is_top = layer == "top_copper"
    is_bot = layer == "bottom_copper"
    if not (is_top or is_bot):
        # Empty component file for non-copper layers
        return "\n".join(lines) + "\n"

    for comp in pcb_components:
        comp_layer = comp.get("layer", "top_copper")
        if _LAYER_ALIAS.get(comp_layer, comp_layer) != layer:
            continue
        sid = comp.get("source_component_id", "")
        src = source_map.get(sid, {})
        refdes = src.get("name", src.get("refdes", sid or "?"))
        value = src.get("value", src.get("part_value", ""))
        footprint = src.get("footprint", "")
        x = float(comp.get("x", 0.0))
        y = float(comp.get("y", 0.0))
        rot = float(comp.get("rotation", 0.0))
        mirror = 0  # bottom-side would be mirror=1; handled via layer routing
        lines.append(
            f"CMP {_mm(x)} {_mm(y)} {rot:.4f} {mirror} {refdes} "
            f"{footprint} {value};"
        )

    return "\n".join(lines) + "\n"


def _build_features(
    layer: str,
    classified: dict[str, list[dict]],
    circuit_json: list[dict],
) -> str:
    fs = _FeatureSet()
    w, h = _board_dims(circuit_json)

    if layer in ("top_copper", "bottom_copper"):
        # Pads
        for pad in classified["pads"]:
            pad_lyr = _pad_layer(pad)
            if pad_lyr != layer:
                continue
            x = float(pad.get("x", 0.0))
            y = float(pad.get("y", 0.0))
            sym = _pad_sym(pad)
            fs.pad(x, y, sym)

        # Vias (appear on both copper layers)
        for via in classified["vias"]:
            x = float(via.get("x", 0.0))
            y = float(via.get("y", 0.0))
            od = float(via.get("outer_diameter", via.get("diameter", 0.6)))
            sym = _sym_circle(od)
            fs.pad(x, y, sym)

        # Traces
        for trace in classified["traces"]:
            route = _trace_route_points(trace)
            if len(route) < 2:
                continue
            for i in range(len(route) - 1):
                p1, p2 = route[i], route[i + 1]
                trace_lyr = _LAYER_ALIAS.get(p1.get("layer", "top_copper"),
                                             p1.get("layer", "top_copper"))
                if trace_lyr != layer:
                    continue
                x1 = float(p1.get("x", 0.0))
                y1 = float(p1.get("y", 0.0))
                x2 = float(p2.get("x", 0.0))
                y2 = float(p2.get("y", 0.0))
                lw = float(p1.get("width", p1.get("trace_width", 0.25)))
                fs.line(x1, y1, x2, y2, lw)

        # Copper pours
        for pour in classified["copper_pour"]:
            pour_lyr = _LAYER_ALIAS.get(pour.get("layer", "top_copper"),
                                         pour.get("layer", "top_copper"))
            if pour_lyr != layer:
                continue
            poly_raw = pour.get("polygon", pour.get("filled_polygon",
                                pour.get("outline", [])))
            if isinstance(poly_raw, list) and len(poly_raw) >= 3:
                verts = [(float(p.get("x", 0.0)), float(p.get("y", 0.0)))
                         for p in poly_raw]
                fs.surface(verts)

    elif layer in ("top_silk", "bottom_silk"):
        silk_side = "top" if layer == "top_silk" else "bottom"

        for stext in classified["silk_text"]:
            el_lyr = stext.get("layer", "")
            el_side = "bottom" if "bottom" in el_lyr else "top"
            if el_side != silk_side:
                continue
            x = float(stext.get("x", 0.0))
            y = float(stext.get("y", 0.0))
            th = float(stext.get("font_size", stext.get("height", 1.0)))
            txt = stext.get("text", "")
            tw = len(txt) * th * 0.6 or th
            fs.line(x, y, x + tw, y, th * 0.15)

        for sline in classified["silk_line"]:
            el_lyr = sline.get("layer", "")
            el_side = "bottom" if "bottom" in el_lyr else "top"
            if el_side != silk_side:
                continue
            pts_raw = sline.get("route", sline.get("points",
                                sline.get("vertices", [])))
            lw = float(sline.get("stroke_width", sline.get("width", 0.15)))
            pts = [(float(p.get("x", 0.0)), float(p.get("y", 0.0)))
                   for p in pts_raw]
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                fs.line(x1, y1, x2, y2, lw)

    elif layer in ("top_mask", "bottom_mask"):
        mask_side = "top" if layer == "top_mask" else "bottom"
        _VIA_MASK = 0.1

        for pad in classified["pads"]:
            pad_lyr = _pad_layer(pad)
            pad_side = "top" if "top" in pad_lyr else "bottom"
            if pad_side != mask_side:
                continue
            x = float(pad.get("x", 0.0))
            y = float(pad.get("y", 0.0))
            shape = pad.get("shape", pad.get("pad_shape", "rect"))
            pw = float(pad.get("width", pad.get("size_x", 1.5)))
            ph = float(pad.get("height", pad.get("size_y", pw)))
            if shape in ("circle", "round"):
                sym = _sym_circle(max(pw, ph) + 0.1)
            elif shape in ("oblong", "oval"):
                sym = _sym_oval(pw + 0.1, ph + 0.1)
            else:
                sym = _sym_rect(pw + 0.1, ph + 0.1)
            fs.pad(x, y, sym)

        for via in classified["vias"]:
            x = float(via.get("x", 0.0))
            y = float(via.get("y", 0.0))
            od = float(via.get("outer_diameter", via.get("diameter", 0.6)))
            sym = _sym_circle(od + _VIA_MASK)
            fs.pad(x, y, sym)

    elif layer == "drill":
        _DEFAULT_DRILL = 0.3

        for via in classified["vias"]:
            x = float(via.get("x", 0.0))
            y = float(via.get("y", 0.0))
            hd = float(via.get("hole_diameter",
                       via.get("drill_diameter",
                       via.get("drill", _DEFAULT_DRILL))))
            sym = _sym_circle(hd)
            fs.pad(x, y, sym)

        for pad in classified["pads"]:
            drill = pad.get("hole_diameter", pad.get("drill_diameter",
                            pad.get("drill", pad.get("drill_size", 0.0))))
            d = float(drill) if drill is not None else 0.0
            if d > 0:
                x = float(pad.get("x", 0.0))
                y = float(pad.get("y", 0.0))
                sym = _sym_circle(d)
                fs.pad(x, y, sym)

        for hole in classified["holes"]:
            x = float(hole.get("x", 0.0))
            y = float(hole.get("y", 0.0))
            d = float(hole.get("hole_diameter", hole.get("diameter", 3.2)))
            if d > 0:
                sym = _sym_circle(d)
                fs.pad(x, y, sym)

    elif layer == "outline":
        verts = _outline_vertices(circuit_json, w, h)
        if len(verts) >= 2:
            lw = 0.1
            for i in range(len(verts)):
                x1, y1 = verts[i]
                x2, y2 = verts[(i + 1) % len(verts)]
                fs.line(x1, y1, x2, y2, lw)

    return fs.render()


# ─── Tree builder ─────────────────────────────────────────────────────────────

def _build_tree(
    circuit_json: list[dict],
    stem: str,
) -> dict[str, bytes]:
    """Build the full ODB++ directory tree, returning {path: bytes}."""

    source_map = _collect_source_components(circuit_json)
    pcb_components = _collect_pcb_components(circuit_json)
    classified = _classify_elements(circuit_json)

    files: dict[str, bytes] = {}

    # misc/info
    files[f"{stem}/misc/info"] = _build_misc_info(stem).encode()

    # steps/pcb/stephdr
    files[f"{stem}/steps/pcb/stephdr"] = _build_stephdr(circuit_json, stem).encode()

    # per-layer files
    for lyr in _LAYERS:
        base = f"{stem}/steps/pcb/layers/{lyr}"

        files[f"{base}/attrlist"] = _build_attrlist(lyr).encode()

        files[f"{base}/components"] = _build_components(
            lyr, pcb_components, source_map
        ).encode()

        files[f"{base}/features"] = _build_features(
            lyr, classified, circuit_json
        ).encode()

    return files


# ─── tgz packer ───────────────────────────────────────────────────────────────

def _pack_tgz(tree: dict[str, bytes]) -> bytes:
    """Pack the {path: bytes} tree into an in-memory .tgz archive."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, data in sorted(tree.items()):
            ti = tarfile.TarInfo(name=path)
            ti.size = len(data)
            ti.mtime = int(datetime.now(timezone.utc).timestamp())
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


# ─── Public API ───────────────────────────────────────────────────────────────

def export_odbpp(
    circuit_json: list[dict],
    stem: str = "board",
) -> dict:
    """Generate an ODB++ archive from a CircuitJSON array.

    Args:
        circuit_json: The parsed CircuitJSON array (tscircuit PCB data model).
        stem: Base name used as the top-level directory inside the archive
              (also used as the step name). Default ``"board"``.

    Returns:
        dict with keys:
          ``tgz_bytes``  — bytes of the .tgz archive.
          ``manifest``   — sorted list of paths inside the archive.
    """
    if not isinstance(circuit_json, list):
        circuit_json = []

    tree = _build_tree(circuit_json, stem)
    tgz_bytes = _pack_tgz(tree)

    return {
        "tgz_bytes": tgz_bytes,
        "manifest": sorted(tree.keys()),
    }
