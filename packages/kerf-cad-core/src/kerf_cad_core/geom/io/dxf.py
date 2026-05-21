"""
geom/io/dxf.py
==============
Pure-Python DXF R12 ASCII read + write for 2D geometry (GK-125).

Supported entity types (read and write)
---------------------------------------
LINE        Two-point line segment.
CIRCLE      Full circle defined by centre + radius.
ARC         Circular arc defined by centre, radius, start angle, end angle
            (angles in degrees, counter-clockwise).
LWPOLYLINE  Lightweight polyline (DXF R14+ group-code form).
SPLINE      B-spline / NURBS curve (degree, knot vector, control points).

Layer table
-----------
Each entity's ``"layer"`` key carries the layer name.  The optional
*layers* argument to ``write_dxf`` is a mapping of layer-name →
``{"color": int, "linetype": str}`` for writing a LAYER table.

Public API
----------
``read_dxf(path) -> dict``
    Parse a DXF ASCII file.  Returns::

        {
            "entities": list[dict],   # one dict per entity (see below)
            "layers":   list[str],    # unique layer names, insertion order
        }

    Entity dicts (common keys for every entity):
        ``type``   : str  — "LINE" | "CIRCLE" | "ARC" | "LWPOLYLINE" | "SPLINE"
        ``layer``  : str  — layer name (default "0")
        ``handle`` : str  — DXF entity handle, if present

    Entity-specific keys:
        LINE        : ``start`` [x,y,z], ``end`` [x,y,z]
        CIRCLE      : ``center`` [x,y,z], ``radius`` float
        ARC         : ``center`` [x,y,z], ``radius`` float,
                      ``start_angle`` float, ``end_angle`` float
        LWPOLYLINE  : ``vertices`` [[x,y], …], ``closed`` bool,
                      ``const_width`` float
        SPLINE      : ``degree`` int, ``knots`` [float,…],
                      ``control_points`` [[x,y,z],…], ``closed`` bool

``write_dxf(path, entities, *, layers=None) -> None``
    Write entities to a DXF R12/R14 ASCII file.

    *entities* is a list of dicts (same schema as returned by ``read_dxf``).
    *layers* is an optional ``dict[str, dict]`` mapping layer name to
    optional attrs ``{"color": int, "linetype": str}``.

``DxfReadError`` / ``DxfWriteError``
    Raised on parse / serialization failures.
"""

from __future__ import annotations

import math
import os
from typing import Any

__all__ = [
    "read_dxf",
    "write_dxf",
    "DxfReadError",
    "DxfWriteError",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DxfReadError(Exception):
    """Raised when a DXF file cannot be parsed."""


class DxfWriteError(Exception):
    """Raised when a DXF file cannot be written."""


# ---------------------------------------------------------------------------
# DXF group-code constants
# ---------------------------------------------------------------------------

_GC_ENTITY_TYPE = 0
_GC_HANDLE = 5
_GC_LAYER = 8
_GC_LINETYPE = 6
_GC_COLOR = 62

# Coordinate group codes
_GC_X1 = 10   # First point X  (start / center)
_GC_Y1 = 20
_GC_Z1 = 30
_GC_X2 = 11   # Second point X (end)
_GC_Y2 = 21
_GC_Z2 = 31
_GC_RADIUS = 40
_GC_START_ANGLE = 50
_GC_END_ANGLE = 51

# LWPOLYLINE
_GC_LWPOLY_COUNT = 90       # vertex count
_GC_LWPOLY_FLAGS = 70       # flags (bit 0 = closed)
_GC_LWPOLY_CONST_WIDTH = 43

# SPLINE
_GC_SPLINE_FLAGS = 70       # bit 0 = closed
_GC_SPLINE_DEGREE = 71
_GC_SPLINE_KNOT_COUNT = 72
_GC_SPLINE_CP_COUNT = 73
_GC_SPLINE_KNOT = 40        # knot value (same as RADIUS group code — context-dependent)
_GC_SPLINE_CP_X = 10
_GC_SPLINE_CP_Y = 20
_GC_SPLINE_CP_Z = 30

# LTYPE / LAYER table entries
_GC_TABLE_NAME = 2
_GC_LAYER_FLAGS = 70
_GC_LAYER_COLOR = 62
_GC_LAYER_LINETYPE = 6


# ---------------------------------------------------------------------------
# Low-level DXF tokenizer
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[tuple[int, str]]:
    """Return a list of (group_code, value_string) pairs."""
    lines = text.splitlines()
    pairs: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        code_line = lines[i].strip()
        if i + 1 >= len(lines):
            break
        val_line = lines[i + 1]  # preserve leading whitespace — needed for string values
        try:
            code = int(code_line)
        except ValueError:
            i += 2
            continue
        pairs.append((code, val_line.strip()))
        i += 2
    return pairs


# ---------------------------------------------------------------------------
# Reader helpers
# ---------------------------------------------------------------------------

def _group_slice(pairs: list[tuple[int, str]], start: int, end: int) -> list[tuple[int, str]]:
    return pairs[start:end]


def _find_section(pairs: list[tuple[int, str]], name: str) -> tuple[int, int] | None:
    """Return (start_idx, end_idx) of a SECTION…ENDSEC block for *name*."""
    i = 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == 0 and val == "SECTION":
            if i + 1 < len(pairs) and pairs[i + 1] == (2, name):
                # find ENDSEC
                j = i + 2
                while j < len(pairs):
                    if pairs[j] == (0, "ENDSEC"):
                        return i, j
                    j += 1
        i += 1
    return None


def _parse_float(s: str) -> float:
    try:
        return float(s)
    except ValueError as exc:
        raise DxfReadError(f"Expected float, got {s!r}") from exc


def _parse_int(s: str) -> int:
    try:
        return int(s)
    except ValueError as exc:
        raise DxfReadError(f"Expected int, got {s!r}") from exc


# ---------------------------------------------------------------------------
# Layer-table parser
# ---------------------------------------------------------------------------

def _parse_layer_table(pairs: list[tuple[int, str]]) -> list[str]:
    """Return ordered list of layer names from the TABLES → LAYER section."""
    layers: list[str] = []
    i = 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == 0 and val == "LAYER":
            # scan until next 0-code
            j = i + 1
            name = "0"
            while j < len(pairs) and pairs[j][0] != 0:
                gc, gv = pairs[j]
                if gc == _GC_TABLE_NAME:
                    name = gv
                j += 1
            if name not in layers:
                layers.append(name)
        i += 1
    return layers


# ---------------------------------------------------------------------------
# Entity parsers
# ---------------------------------------------------------------------------

def _parse_entities_section(pairs: list[tuple[int, str]]) -> list[dict[str, Any]]:
    """Parse all entities from an ENTITIES section token list."""
    entities: list[dict[str, Any]] = []
    i = 0
    n = len(pairs)

    while i < n:
        code, val = pairs[i]
        if code != 0:
            i += 1
            continue

        etype = val.upper()
        if etype in ("ENDSEC", "EOF", "ENDBLK"):
            break

        if etype == "LINE":
            i, ent = _parse_line(pairs, i + 1)
            ent["type"] = "LINE"
            entities.append(ent)

        elif etype == "CIRCLE":
            i, ent = _parse_circle(pairs, i + 1)
            ent["type"] = "CIRCLE"
            entities.append(ent)

        elif etype == "ARC":
            i, ent = _parse_arc(pairs, i + 1)
            ent["type"] = "ARC"
            entities.append(ent)

        elif etype == "LWPOLYLINE":
            i, ent = _parse_lwpolyline(pairs, i + 1)
            ent["type"] = "LWPOLYLINE"
            entities.append(ent)

        elif etype == "SPLINE":
            i, ent = _parse_spline(pairs, i + 1)
            ent["type"] = "SPLINE"
            entities.append(ent)

        else:
            # skip unknown entity
            i += 1

    return entities


def _common_header() -> dict[str, Any]:
    return {"layer": "0", "handle": ""}


def _scan_common(pairs: list[tuple[int, str]], idx: int, d: dict) -> int:
    """Read common entity group codes at current position (5, 8).
    Returns same idx (does not consume; caller drives the loop)."""
    code, val = pairs[idx]
    if code == _GC_HANDLE:
        d["handle"] = val
    elif code == _GC_LAYER:
        d["layer"] = val
    return idx


def _body_end(pairs: list[tuple[int, str]], start: int) -> int:
    """Return the index of the next 0-code group after *start*, or len(pairs)."""
    i = start
    while i < len(pairs):
        if pairs[i][0] == 0:
            return i
        i += 1
    return i


def _parse_line(pairs: list[tuple[int, str]], start: int) -> tuple[int, dict]:
    d = _common_header()
    d.update({"start": [0.0, 0.0, 0.0], "end": [0.0, 0.0, 0.0]})
    end = _body_end(pairs, start)
    for gc, gv in pairs[start:end]:
        if gc == _GC_HANDLE:
            d["handle"] = gv
        elif gc == _GC_LAYER:
            d["layer"] = gv
        elif gc == _GC_X1:
            d["start"][0] = _parse_float(gv)
        elif gc == _GC_Y1:
            d["start"][1] = _parse_float(gv)
        elif gc == _GC_Z1:
            d["start"][2] = _parse_float(gv)
        elif gc == _GC_X2:
            d["end"][0] = _parse_float(gv)
        elif gc == _GC_Y2:
            d["end"][1] = _parse_float(gv)
        elif gc == _GC_Z2:
            d["end"][2] = _parse_float(gv)
    return end, d


def _parse_circle(pairs: list[tuple[int, str]], start: int) -> tuple[int, dict]:
    d = _common_header()
    d.update({"center": [0.0, 0.0, 0.0], "radius": 1.0})
    end = _body_end(pairs, start)
    for gc, gv in pairs[start:end]:
        if gc == _GC_HANDLE:
            d["handle"] = gv
        elif gc == _GC_LAYER:
            d["layer"] = gv
        elif gc == _GC_X1:
            d["center"][0] = _parse_float(gv)
        elif gc == _GC_Y1:
            d["center"][1] = _parse_float(gv)
        elif gc == _GC_Z1:
            d["center"][2] = _parse_float(gv)
        elif gc == _GC_RADIUS:
            d["radius"] = _parse_float(gv)
    return end, d


def _parse_arc(pairs: list[tuple[int, str]], start: int) -> tuple[int, dict]:
    d = _common_header()
    d.update({
        "center": [0.0, 0.0, 0.0],
        "radius": 1.0,
        "start_angle": 0.0,
        "end_angle": 360.0,
    })
    end = _body_end(pairs, start)
    for gc, gv in pairs[start:end]:
        if gc == _GC_HANDLE:
            d["handle"] = gv
        elif gc == _GC_LAYER:
            d["layer"] = gv
        elif gc == _GC_X1:
            d["center"][0] = _parse_float(gv)
        elif gc == _GC_Y1:
            d["center"][1] = _parse_float(gv)
        elif gc == _GC_Z1:
            d["center"][2] = _parse_float(gv)
        elif gc == _GC_RADIUS:
            d["radius"] = _parse_float(gv)
        elif gc == _GC_START_ANGLE:
            d["start_angle"] = _parse_float(gv)
        elif gc == _GC_END_ANGLE:
            d["end_angle"] = _parse_float(gv)
    return end, d


def _parse_lwpolyline(pairs: list[tuple[int, str]], start: int) -> tuple[int, dict]:
    """Parse LWPOLYLINE.

    DXF LWPOLYLINE vertex data is encoded as repeating 10/20 group code pairs
    within the entity body.
    """
    d = _common_header()
    d.update({
        "vertices": [],
        "closed": False,
        "const_width": 0.0,
    })
    end = _body_end(pairs, start)
    # We need to reconstruct vertices from repeated 10/20 codes.
    # Strategy: collect all 10-codes as X, and 20-codes as Y, in order.
    xs: list[float] = []
    ys: list[float] = []
    flags = 0
    for gc, gv in pairs[start:end]:
        if gc == _GC_HANDLE:
            d["handle"] = gv
        elif gc == _GC_LAYER:
            d["layer"] = gv
        elif gc == _GC_LWPOLY_FLAGS:
            flags = _parse_int(gv)
        elif gc == _GC_LWPOLY_CONST_WIDTH:
            d["const_width"] = _parse_float(gv)
        elif gc == 10:
            xs.append(_parse_float(gv))
        elif gc == 20:
            ys.append(_parse_float(gv))
    d["closed"] = bool(flags & 1)
    # Pair up xs and ys
    d["vertices"] = [[x, y] for x, y in zip(xs, ys)]
    return end, d


def _parse_spline(pairs: list[tuple[int, str]], start: int) -> tuple[int, dict]:
    """Parse SPLINE entity.

    Group-code layout (abbreviated):
        70  flags
        71  degree
        72  knot count
        73  control-point count
        40  knot value (repeated)
        10/20/30  control-point X/Y/Z (repeated)
    """
    d = _common_header()
    d.update({
        "degree": 3,
        "knots": [],
        "control_points": [],
        "closed": False,
    })
    end = _body_end(pairs, start)

    knot_count = 0
    cp_count = 0
    flags = 0
    # Collect knots and control points from repeated group codes.
    # Knots: gc==40; control points: gc==10/20/30 (repeated triplets).
    raw_knots: list[float] = []
    cp_xs: list[float] = []
    cp_ys: list[float] = []
    cp_zs: list[float] = []

    # We use a two-pass approach: first parse scalar fields, then vectors.
    for gc, gv in pairs[start:end]:
        if gc == _GC_HANDLE:
            d["handle"] = gv
        elif gc == _GC_LAYER:
            d["layer"] = gv
        elif gc == 70:
            flags = _parse_int(gv)
        elif gc == 71:
            d["degree"] = _parse_int(gv)
        elif gc == 72:
            knot_count = _parse_int(gv)
        elif gc == 73:
            cp_count = _parse_int(gv)
        elif gc == 40:
            raw_knots.append(_parse_float(gv))
        elif gc == 10:
            cp_xs.append(_parse_float(gv))
        elif gc == 20:
            cp_ys.append(_parse_float(gv))
        elif gc == 30:
            cp_zs.append(_parse_float(gv))

    d["closed"] = bool(flags & 1)
    d["knots"] = raw_knots
    # Pad z if missing
    while len(cp_zs) < len(cp_xs):
        cp_zs.append(0.0)
    d["control_points"] = [
        [x, y, z] for x, y, z in zip(cp_xs, cp_ys, cp_zs)
    ]
    return end, d


# ---------------------------------------------------------------------------
# Public read
# ---------------------------------------------------------------------------

def read_dxf(path: str | os.PathLike) -> dict[str, Any]:
    """Read a DXF ASCII file and return ``{"entities": [...], "layers": [...]}``.

    Raises ``DxfReadError`` on parse failures.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise DxfReadError(f"Cannot open {path}: {exc}") from exc

    pairs = _tokenize(text)

    # --- Parse TABLES section for layer names ---
    tables_range = _find_section(pairs, "TABLES")
    table_layers: list[str] = []
    if tables_range:
        ts, te = tables_range
        table_layers = _parse_layer_table(pairs[ts:te])

    # --- Parse ENTITIES section ---
    ent_range = _find_section(pairs, "ENTITIES")
    entities: list[dict] = []
    if ent_range:
        es, ee = ent_range
        entities = _parse_entities_section(pairs[es + 2:ee])

    # Build final layer list: table layers first, then any layer referenced
    # by entities but not in the table.
    seen: set[str] = set(table_layers)
    all_layers = list(table_layers)
    for ent in entities:
        lyr = ent.get("layer", "0")
        if lyr not in seen:
            seen.add(lyr)
            all_layers.append(lyr)

    # Ensure "0" is always present
    if "0" not in seen:
        all_layers.insert(0, "0")

    return {"entities": entities, "layers": all_layers}


# ---------------------------------------------------------------------------
# Writer helpers
# ---------------------------------------------------------------------------

def _gc(code: int, value: Any) -> str:
    """Format a single DXF group-code pair as two lines."""
    return f"{code:>3}\n{value}\n"


def _write_header() -> str:
    lines = []
    lines.append(_gc(0, "SECTION"))
    lines.append(_gc(2, "HEADER"))
    lines.append(_gc(9, "$ACADVER"))
    lines.append(_gc(1, "AC1009"))   # R12
    lines.append(_gc(0, "ENDSEC"))
    return "".join(lines)


def _write_tables(layer_names: list[str], layer_attrs: dict[str, dict]) -> str:
    lines = []
    lines.append(_gc(0, "SECTION"))
    lines.append(_gc(2, "TABLES"))
    lines.append(_gc(0, "TABLE"))
    lines.append(_gc(2, "LAYER"))
    lines.append(_gc(70, len(layer_names)))
    for name in layer_names:
        attrs = layer_attrs.get(name, {})
        color = attrs.get("color", 7)
        linetype = attrs.get("linetype", "CONTINUOUS")
        lines.append(_gc(0, "LAYER"))
        lines.append(_gc(2, name))
        lines.append(_gc(70, 0))           # flags: 0 = on, unlocked
        lines.append(_gc(62, color))
        lines.append(_gc(6, linetype))
    lines.append(_gc(0, "ENDTAB"))
    lines.append(_gc(0, "ENDSEC"))
    return "".join(lines)


def _fmt_float(v: float) -> str:
    """Format a float in a DXF-friendly way (no trailing zeros, no exp for normal range)."""
    if v == 0.0:
        return "0.0"
    # Use repr-level precision, strip unnecessary zeros
    s = f"{v:.10g}"
    if "." not in s and "e" not in s:
        s = s + ".0"
    return s


def _write_entity(ent: dict[str, Any]) -> str:
    etype = ent.get("type", "").upper()
    layer = ent.get("layer", "0")
    lines = []

    if etype == "LINE":
        s = ent.get("start", [0, 0, 0])
        e = ent.get("end", [0, 0, 0])
        lines.append(_gc(0, "LINE"))
        lines.append(_gc(8, layer))
        lines.append(_gc(10, _fmt_float(s[0])))
        lines.append(_gc(20, _fmt_float(s[1])))
        lines.append(_gc(30, _fmt_float(s[2] if len(s) > 2 else 0.0)))
        lines.append(_gc(11, _fmt_float(e[0])))
        lines.append(_gc(21, _fmt_float(e[1])))
        lines.append(_gc(31, _fmt_float(e[2] if len(e) > 2 else 0.0)))

    elif etype == "CIRCLE":
        c = ent.get("center", [0, 0, 0])
        r = ent.get("radius", 1.0)
        lines.append(_gc(0, "CIRCLE"))
        lines.append(_gc(8, layer))
        lines.append(_gc(10, _fmt_float(c[0])))
        lines.append(_gc(20, _fmt_float(c[1])))
        lines.append(_gc(30, _fmt_float(c[2] if len(c) > 2 else 0.0)))
        lines.append(_gc(40, _fmt_float(r)))

    elif etype == "ARC":
        c = ent.get("center", [0, 0, 0])
        r = ent.get("radius", 1.0)
        sa = ent.get("start_angle", 0.0)
        ea = ent.get("end_angle", 360.0)
        lines.append(_gc(0, "ARC"))
        lines.append(_gc(8, layer))
        lines.append(_gc(10, _fmt_float(c[0])))
        lines.append(_gc(20, _fmt_float(c[1])))
        lines.append(_gc(30, _fmt_float(c[2] if len(c) > 2 else 0.0)))
        lines.append(_gc(40, _fmt_float(r)))
        lines.append(_gc(50, _fmt_float(sa)))
        lines.append(_gc(51, _fmt_float(ea)))

    elif etype == "LWPOLYLINE":
        verts = ent.get("vertices", [])
        closed = ent.get("closed", False)
        const_width = ent.get("const_width", 0.0)
        flags = 1 if closed else 0
        lines.append(_gc(0, "LWPOLYLINE"))
        lines.append(_gc(8, layer))
        lines.append(_gc(90, len(verts)))
        lines.append(_gc(70, flags))
        if const_width != 0.0:
            lines.append(_gc(43, _fmt_float(const_width)))
        for v in verts:
            lines.append(_gc(10, _fmt_float(v[0])))
            lines.append(_gc(20, _fmt_float(v[1])))

    elif etype == "SPLINE":
        degree = ent.get("degree", 3)
        knots = ent.get("knots", [])
        cps = ent.get("control_points", [])
        closed = ent.get("closed", False)
        flags = 1 if closed else 0
        lines.append(_gc(0, "SPLINE"))
        lines.append(_gc(8, layer))
        lines.append(_gc(70, flags))
        lines.append(_gc(71, degree))
        lines.append(_gc(72, len(knots)))
        lines.append(_gc(73, len(cps)))
        for k in knots:
            lines.append(_gc(40, _fmt_float(k)))
        for cp in cps:
            lines.append(_gc(10, _fmt_float(cp[0])))
            lines.append(_gc(20, _fmt_float(cp[1])))
            lines.append(_gc(30, _fmt_float(cp[2] if len(cp) > 2 else 0.0)))

    else:
        raise DxfWriteError(f"Unsupported entity type: {etype!r}")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Public write
# ---------------------------------------------------------------------------

def write_dxf(
    path: str | os.PathLike,
    entities: list[dict[str, Any]],
    *,
    layers: dict[str, dict] | None = None,
) -> None:
    """Write *entities* to a DXF ASCII file at *path*.

    *layers* maps layer name → ``{"color": int, "linetype": str}``.
    Raises ``DxfWriteError`` on failures.
    """
    if layers is None:
        layers = {}

    # Collect all layer names referenced by entities + explicit layers dict
    seen_layers: list[str] = []
    seen_set: set[str] = set()

    def _add_layer(name: str) -> None:
        if name not in seen_set:
            seen_set.add(name)
            seen_layers.append(name)

    _add_layer("0")
    for name in layers:
        _add_layer(name)
    for ent in entities:
        _add_layer(ent.get("layer", "0"))

    try:
        parts = [
            _write_header(),
            _write_tables(seen_layers, layers),
            _gc(0, "SECTION") + _gc(2, "ENTITIES"),
        ]
        for ent in entities:
            try:
                parts.append(_write_entity(ent))
            except DxfWriteError:
                raise
            except Exception as exc:
                raise DxfWriteError(f"Failed to write entity {ent!r}: {exc}") from exc
        parts.append(_gc(0, "ENDSEC"))
        parts.append(_gc(0, "EOF"))

        content = "".join(parts)
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(content)
    except DxfWriteError:
        raise
    except OSError as exc:
        raise DxfWriteError(f"Cannot write {path}: {exc}") from exc
    except Exception as exc:
        raise DxfWriteError(f"Unexpected error writing DXF: {exc}") from exc
