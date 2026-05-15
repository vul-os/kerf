"""
reader.py — Pure-Python DXF reader (T-5).

Parses DXF R12 and R2000+ ASCII files (not binary DXF, not DWG).

Group-code format:
  Each DXF record is a pair of lines:
    Line 1: group code (integer, whitespace-stripped)
    Line 2: value (string, right-whitespace-stripped)

Supported entities: LINE, LWPOLYLINE, POLYLINE/VERTEX/SEQEND, CIRCLE,
ARC, TEXT, MTEXT, INSERT, and BLOCK/ENDBLK table entries.

Usage::

    from kerf_imports.dxf.reader import read_dxf

    doc = read_dxf(dxf_text)          # str input
    # or
    doc = read_dxf_bytes(raw_bytes)    # bytes input (auto-detects encoding)

The returned :class:`~kerf_imports.dxf.entities.DxfDocument` contains:
  - ``entities``  — model-space entities
  - ``blocks``    — block definition table
  - ``warnings``  — non-fatal parse issues
  - ``units``     — unit string from $INSUNITS header (default "mm")
"""
from __future__ import annotations

import math
from typing import Iterator

from kerf_imports.dxf.entities import (
    DxfArc,
    DxfBlock,
    DxfCircle,
    DxfDocument,
    DxfInsert,
    DxfLine,
    DxfLwPolyline,
    DxfPolyline,
    DxfText,
)

# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def read_dxf(text: str) -> DxfDocument:
    """Parse ASCII DXF text and return a :class:`DxfDocument`."""
    pairs = list(_tokenize(text))
    return _parse(pairs)


def read_dxf_bytes(data: bytes) -> DxfDocument:
    """Auto-detect encoding and parse DXF bytes."""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return read_dxf(data.decode(enc))
        except UnicodeDecodeError:
            continue
    # Final fallback: replace undecodable bytes
    return read_dxf(data.decode("latin-1", errors="replace"))


# ---------------------------------------------------------------------------
# Tokeniser: text → list[(group_code: int, value: str)]
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> Iterator[tuple[int, str]]:
    lines = text.splitlines()
    i = 0
    while i < len(lines) - 1:
        code_line = lines[i].strip()
        val_line  = lines[i + 1].rstrip()
        i += 2
        try:
            code = int(code_line)
        except ValueError:
            continue
        yield code, val_line


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_INSUNITS_MAP: dict[int, str] = {
    0: "unitless", 1: "inches", 2: "feet", 4: "mm", 5: "cm",
    6: "m", 8: "microinches", 10: "yards",
}


def _parse(pairs: list[tuple[int, str]]) -> DxfDocument:
    doc = DxfDocument()

    # Walk sections
    i = 0
    n = len(pairs)

    while i < n:
        code, val = pairs[i]
        if code == 0 and val == "SECTION":
            i += 1
            if i >= n:
                break
            sec_code, sec_name = pairs[i]
            if sec_code == 2:
                if sec_name == "HEADER":
                    i = _parse_header(pairs, i + 1, doc)
                elif sec_name == "BLOCKS":
                    i = _parse_blocks(pairs, i + 1, doc)
                elif sec_name == "ENTITIES":
                    i = _parse_entities_section(pairs, i + 1, doc.entities, doc.warnings)
                else:
                    # Skip unknown sections
                    i = _skip_to_endsec(pairs, i + 1)
            else:
                i += 1
        else:
            i += 1

    return doc


def _skip_to_endsec(pairs: list[tuple[int, str]], start: int) -> int:
    i = start
    n = len(pairs)
    while i < n:
        code, val = pairs[i]
        if code == 0 and val == "ENDSEC":
            return i + 1
        i += 1
    return i


# ---------------------------------------------------------------------------
# HEADER section
# ---------------------------------------------------------------------------

def _parse_header(pairs: list[tuple[int, str]], start: int, doc: DxfDocument) -> int:
    i = start
    n = len(pairs)
    current_var = ""
    while i < n:
        code, val = pairs[i]
        if code == 0 and val == "ENDSEC":
            return i + 1
        if code == 9:
            current_var = val
        elif current_var == "$INSUNITS" and code == 70:
            try:
                unit_code = int(val)
                doc.units = _INSUNITS_MAP.get(unit_code, "mm")
            except ValueError:
                pass
        i += 1
    return i


# ---------------------------------------------------------------------------
# BLOCKS section
# ---------------------------------------------------------------------------

def _parse_blocks(pairs: list[tuple[int, str]], start: int, doc: DxfDocument) -> int:
    i = start
    n = len(pairs)
    while i < n:
        code, val = pairs[i]
        if code == 0 and val == "ENDSEC":
            return i + 1
        if code == 0 and val == "BLOCK":
            i, block = _parse_block_def(pairs, i + 1, doc.warnings)
            if block is not None:
                doc.blocks[block.name] = block
        else:
            i += 1
    return i


def _parse_block_def(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfBlock | None]:
    """Parse from after the BLOCK group-code-0 record to ENDBLK."""
    i = start
    n = len(pairs)
    name = ""
    base_x = 0.0
    base_y = 0.0
    layer = "0"

    # Read block header
    while i < n:
        code, val = pairs[i]
        if code == 0:
            # First 0-code inside the block body starts entity parsing
            break
        if code == 2:
            name = val
        elif code == 8:
            layer = val
        elif code == 10:
            try:
                base_x = float(val)
            except ValueError:
                pass
        elif code == 20:
            try:
                base_y = float(val)
            except ValueError:
                pass
        i += 1

    if not name:
        # Skip to ENDBLK
        while i < n:
            code, val = pairs[i]
            i += 1
            if code == 0 and val == "ENDBLK":
                break
        return i, None

    block = DxfBlock(name=name, base_x=base_x, base_y=base_y, layer=layer)

    # Parse block entities until ENDBLK
    while i < n:
        code, val = pairs[i]
        if code == 0 and val in ("ENDBLK", "ENDSEC"):
            if val == "ENDBLK":
                i += 1
            return i, block
        if code == 0:
            i, ent = _parse_entity(val, pairs, i + 1, warnings)
            if ent is not None:
                block.entities.append(ent)
        else:
            i += 1

    return i, block


# ---------------------------------------------------------------------------
# ENTITIES section
# ---------------------------------------------------------------------------

def _parse_entities_section(
    pairs: list[tuple[int, str]],
    start: int,
    out: list,
    warnings: list[str],
) -> int:
    i = start
    n = len(pairs)
    while i < n:
        code, val = pairs[i]
        if code == 0 and val == "ENDSEC":
            return i + 1
        if code == 0:
            i, ent = _parse_entity(val, pairs, i + 1, warnings)
            if ent is not None:
                out.append(ent)
        else:
            i += 1
    return i


# ---------------------------------------------------------------------------
# Entity dispatch
# ---------------------------------------------------------------------------

# Entity types we silently skip (very common, not needed for sketch/drawing)
_SILENTLY_SKIPPED = frozenset({
    "HATCH", "SOLID", "3DFACE", "3DSOLID", "TRACE", "VIEWPORT",
    "ATTDEF", "ATTRIB", "DIMENSION", "LEADER", "MLINE", "RAY",
    "XLINE", "POINT", "TOLERANCE", "SHAPE", "ELLIPSE", "SPLINE",
    "BODY", "REGION", "SURFACE", "MESH", "SECTION", "ENDSEC",
    "EOF", "TABLE", "LAYER", "STYLE", "VIEW", "UCS", "APPID",
    "DIMSTYLE", "BLOCK_RECORD", "ENDTAB", "LTYPE", "VPORT",
    "IMAGE", "IMAGEDEF", "IMAGEDEF_REACTOR", "OLE2FRAME",
    "WIPEOUT", "UNDERLAY", "PDFUNDERLAY",
})

_WARNED_TYPES: set[str] = set()


def _parse_entity(
    entity_type: str,
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, object | None]:
    """
    Dispatch to the appropriate entity parser.

    Returns (new_index, entity_or_None).
    """
    parsers = {
        "LINE":       _parse_line,
        "LWPOLYLINE": _parse_lwpolyline,
        "POLYLINE":   _parse_polyline,
        "CIRCLE":     _parse_circle,
        "ARC":        _parse_arc,
        "TEXT":       _parse_text,
        "MTEXT":      _parse_mtext,
        "INSERT":     _parse_insert,
    }

    parser = parsers.get(entity_type)
    if parser is not None:
        return parser(pairs, start, warnings)

    # Warn once per unknown type (non-silently-skipped)
    if entity_type not in _SILENTLY_SKIPPED and entity_type not in _WARNED_TYPES:
        _WARNED_TYPES.add(entity_type)
        warnings.append(f"DXF entity type {entity_type!r} not supported — skipped")

    # Advance past this entity's records to the next 0-code
    i = start
    n = len(pairs)
    while i < n:
        code, val = pairs[i]
        if code == 0:
            break
        i += 1
    return i, None


# ---------------------------------------------------------------------------
# Per-entity parsers
# Each parser receives (pairs, start_after_entity_type, warnings)
# and returns (new_index, entity_or_None).
# ---------------------------------------------------------------------------

def _read_until_next_entity(
    pairs: list[tuple[int, str]],
    start: int,
) -> tuple[int, dict[int, list[str]]]:
    """
    Read group-code records until the next group-code-0 record.

    Returns (index_of_next_0_code, {code: [value, ...]}).
    """
    groups: dict[int, list[str]] = {}
    i = start
    n = len(pairs)
    while i < n:
        code, val = pairs[i]
        if code == 0:
            break
        groups.setdefault(code, []).append(val)
        i += 1
    return i, groups


def _g(groups: dict[int, list[str]], code: int, default: str = "") -> str:
    """Get first value for a group code."""
    vals = groups.get(code)
    return vals[0] if vals else default


def _gf(groups: dict[int, list[str]], code: int, default: float = 0.0) -> float:
    """Get first value for a group code as float."""
    try:
        return float(_g(groups, code, str(default)))
    except (ValueError, TypeError):
        return default


def _parse_line(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfLine | None]:
    i, groups = _read_until_next_entity(pairs, start)
    return i, DxfLine(
        x1=_gf(groups, 10),
        y1=_gf(groups, 20),
        x2=_gf(groups, 11),
        y2=_gf(groups, 21),
        layer=_g(groups, 8, "0"),
        handle=_g(groups, 5),
    )


def _parse_circle(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfCircle | None]:
    i, groups = _read_until_next_entity(pairs, start)
    radius = _gf(groups, 40)
    if radius <= 0.0:
        warnings.append("CIRCLE with non-positive radius skipped")
        return i, None
    return i, DxfCircle(
        cx=_gf(groups, 10),
        cy=_gf(groups, 20),
        radius=radius,
        layer=_g(groups, 8, "0"),
        handle=_g(groups, 5),
    )


def _parse_arc(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfArc | None]:
    i, groups = _read_until_next_entity(pairs, start)
    radius = _gf(groups, 40)
    if radius <= 0.0:
        warnings.append("ARC with non-positive radius skipped")
        return i, None
    return i, DxfArc(
        cx=_gf(groups, 10),
        cy=_gf(groups, 20),
        radius=radius,
        start_angle=_gf(groups, 50),
        end_angle=_gf(groups, 51),
        layer=_g(groups, 8, "0"),
        handle=_g(groups, 5),
    )


def _parse_text(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfText | None]:
    i, groups = _read_until_next_entity(pairs, start)
    value = _g(groups, 1)
    return i, DxfText(
        x=_gf(groups, 10),
        y=_gf(groups, 20),
        value=value,
        height=_gf(groups, 40, 2.5),
        rotation=_gf(groups, 50),
        layer=_g(groups, 8, "0"),
        handle=_g(groups, 5),
    )


def _parse_mtext(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfText | None]:
    """MTEXT — multi-line text.  We strip RTF-like codes and emit as TEXT."""
    i, groups = _read_until_next_entity(pairs, start)
    # Group 1 = primary text content (may have RTF codes like \P, \f{...})
    raw = _g(groups, 1)
    # Strip simple MTEXT formatting codes: \P = paragraph break, \~ = nbsp
    value = raw.replace(r"\P", " ").replace(r"\~", " ")
    # Strip font change codes like {\fArial|...; ...}  (heuristic)
    import re
    value = re.sub(r"\{\\[^}]*\}", "", value)
    value = re.sub(r"\\[a-zA-Z]+[0-9;]*", "", value)
    value = value.strip()
    if not value:
        return i, None
    return i, DxfText(
        x=_gf(groups, 10),
        y=_gf(groups, 20),
        value=value,
        height=_gf(groups, 40, 2.5),
        rotation=_gf(groups, 50),
        layer=_g(groups, 8, "0"),
        handle=_g(groups, 5),
    )


def _parse_insert(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfInsert | None]:
    i, groups = _read_until_next_entity(pairs, start)
    block_name = _g(groups, 2)
    if not block_name:
        warnings.append("INSERT with no block name skipped")
        return i, None
    return i, DxfInsert(
        block_name=block_name,
        x=_gf(groups, 10),
        y=_gf(groups, 20),
        x_scale=_gf(groups, 41, 1.0),
        y_scale=_gf(groups, 42, 1.0),
        rotation_deg=_gf(groups, 50),
        layer=_g(groups, 8, "0"),
        handle=_g(groups, 5),
    )


def _parse_lwpolyline(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfLwPolyline | None]:
    """LWPOLYLINE: group-code 10/20 pairs are the vertices."""
    i = start
    n = len(pairs)
    layer = "0"
    handle = ""
    closed = False
    xs: list[float] = []
    ys: list[float] = []
    bulges: list[float] = []
    current_bulge = 0.0

    while i < n:
        code, val = pairs[i]
        if code == 0:
            break
        if code == 8:
            layer = val
        elif code == 5:
            handle = val
        elif code == 70:
            try:
                flags = int(val)
                closed = bool(flags & 1)
            except ValueError:
                pass
        elif code == 10:
            try:
                xs.append(float(val))
                # When a new X is encountered, commit the last bulge
                if len(xs) > len(bulges):
                    bulges.append(current_bulge)
                    current_bulge = 0.0
            except ValueError:
                pass
        elif code == 20:
            try:
                ys.append(float(val))
            except ValueError:
                pass
        elif code == 42:
            # Bulge applies to the NEXT vertex (in DXF this comes after the 10/20 pair)
            try:
                current_bulge = float(val)
            except ValueError:
                pass
        i += 1

    # Align lengths
    while len(bulges) < len(xs):
        bulges.append(0.0)

    points = [[x, y] for x, y in zip(xs, ys)]
    if len(points) < 2:
        warnings.append("LWPOLYLINE with fewer than 2 vertices skipped")
        return i, None
    return i, DxfLwPolyline(
        points=points,
        closed=closed,
        layer=layer,
        handle=handle,
        bulge=bulges,
    )


def _parse_polyline(
    pairs: list[tuple[int, str]],
    start: int,
    warnings: list[str],
) -> tuple[int, DxfPolyline | None]:
    """R12 POLYLINE: reads the polyline header, then VERTEX records until SEQEND."""
    i = start
    n = len(pairs)
    layer = "0"
    handle = ""
    closed = False

    # Read polyline header until first 0-code (should be VERTEX or SEQEND)
    while i < n:
        code, val = pairs[i]
        if code == 0:
            break
        if code == 8:
            layer = val
        elif code == 5:
            handle = val
        elif code == 70:
            try:
                flags = int(val)
                closed = bool(flags & 1)
            except ValueError:
                pass
        i += 1

    # Now collect VERTEX entities
    points: list[list[float]] = []
    bulges: list[float] = []
    while i < n:
        code, val = pairs[i]
        if code == 0 and val == "SEQEND":
            i += 1
            # Advance past SEQEND records
            while i < n and pairs[i][0] != 0:
                i += 1
            break
        if code == 0 and val == "VERTEX":
            i, vx, vy, vb = _parse_vertex(pairs, i + 1)
            points.append([vx, vy])
            bulges.append(vb)
        elif code == 0:
            # Unexpected entity terminator
            break
        else:
            i += 1

    if len(points) < 2:
        warnings.append("POLYLINE with fewer than 2 vertices skipped")
        return i, None
    return i, DxfPolyline(
        points=points,
        closed=closed,
        layer=layer,
        handle=handle,
        bulge=bulges,
    )


def _parse_vertex(
    pairs: list[tuple[int, str]],
    start: int,
) -> tuple[int, float, float, float]:
    """Parse VERTEX records until the next 0-code. Returns (new_i, x, y, bulge)."""
    i = start
    n = len(pairs)
    x = 0.0
    y = 0.0
    bulge = 0.0
    while i < n:
        code, val = pairs[i]
        if code == 0:
            break
        if code == 10:
            try:
                x = float(val)
            except ValueError:
                pass
        elif code == 20:
            try:
                y = float(val)
            except ValueError:
                pass
        elif code == 42:
            try:
                bulge = float(val)
            except ValueError:
                pass
        i += 1
    return i, x, y, bulge
