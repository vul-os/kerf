"""
spreadsheet.py — FreeCAD Spreadsheet → Kerf .equations translator.

FreeCAD's ``Spreadsheet::Sheet`` objects store cells in a flat property
map.  Each cell is exposed as a property with the cell address as the
name (e.g. ``A1``, ``B2``).  FreeCAD also supports cell *aliases* — a
named binding that makes a cell referenceable as a model parameter.

We extract all aliased cells (and any explicitly named expression cells)
and emit a Kerf ``.equations`` file::

    {
      "version": 1,
      "params": [
        {"name": "wall_thickness", "expr": "2",            "unit": "mm"},
        {"name": "hole_radius",    "expr": "wall_thickness / 4"},
        ...
      ],
      "freecad_ref": {"name": "...", "label": "..."},
      "warnings": [...]
    }

Cells without an alias are included in a separate ``raw_cells`` block
(keyed by address) so the caller can inspect non-named data, but they are
NOT emitted as named params (an anonymous spreadsheet value is not a
useful model parameter).

FreeCAD cell XML shape (inside ``Spreadsheet::Sheet`` ObjectData)::

    <Property name="cells" type="Spreadsheet::PropertySheet">
      <Cells>
        <Cell address="A1" content="wall_thickness" />     <!-- header/label -->
        <Cell address="B1" content="2 mm" />               <!-- raw value -->
        <Cell address="B1" alias="wall_thickness"
              content="2 mm" />                            <!-- aliased -->
        <Cell address="B2" alias="hole_radius"
              content="=wall_thickness / 4" />             <!-- formula -->
      </Cells>
    </Property>

Content starting with ``=`` is an expression; others are literal values.
"""
from __future__ import annotations

import re
from typing import Any

from .types import FCStdObject


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def translate_spreadsheet(obj: FCStdObject) -> dict[str, Any]:
    """
    Translate a ``Spreadsheet::Sheet`` FCStdObject into a Kerf ``.equations``
    dict.

    Parameters
    ----------
    obj :
        An :class:`~kerf_imports.freecad.types.FCStdObject` with
        ``type == "Spreadsheet::Sheet"``.

    Returns
    -------
    dict
        Kerf ``.equations`` payload with keys:
        ``version``      — always 1
        ``params``       — list of ``{name, expr, unit?, comment?}`` dicts
        ``raw_cells``    — dict of ``{address: {content, alias?}}`` for all cells
        ``freecad_ref``  — provenance
        ``warnings``     — list of warning strings
    """
    warnings: list[str] = []
    raw_cells: dict[str, dict[str, str]] = {}
    aliased: list[tuple[str, str, str]] = []

    # FreeCAD stores cell data in ``Spreadsheet::PropertySheet`` (now handled
    # by property_parsers._parse_spreadsheet_cells → list of cell dicts).
    # The property name in Document.xml is ``cells`` (lowercase).
    cells_list = obj.properties.get("cells")

    if cells_list is None:
        # Alternate casing used by older FreeCAD versions
        cells_list = obj.properties.get("Cells")

    if isinstance(cells_list, list):
        # Injected via the _cell_list sentinel path or directly from the parser
        obj.properties["_cell_list"] = cells_list

    raw_xml_cells = _extract_cells_from_raw_xml(obj)
    if raw_xml_cells is not None:
        raw_cells, aliased, extra_warnings = raw_xml_cells
        warnings.extend(extra_warnings)
    else:
        # Nothing usable — return an empty equations file with a warning
        warnings.append(
            f"Spreadsheet '{obj.label}': no cell data found — "
            "the parser does not have access to the raw Document.xml at "
            "this stage; cells property was not decoded."
        )

    # Build params list from aliased cells
    params: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for alias, address, content in aliased:
        safe_name = _sanitise_name(alias)
        if safe_name != alias:
            warnings.append(
                f"cell {address}: alias {alias!r} sanitised to {safe_name!r} "
                "to form a valid parameter name."
            )
        if safe_name in seen_names:
            warnings.append(
                f"cell {address}: duplicate alias {safe_name!r} — skipped."
            )
            continue
        seen_names.add(safe_name)

        expr, unit = _parse_cell_content(content)
        param: dict[str, Any] = {"name": safe_name, "expr": expr}
        if unit:
            param["unit"] = unit
        params.append(param)

    return {
        "version": 1,
        "params": params,
        "raw_cells": raw_cells,
        "freecad_ref": {
            "name": obj.name,
            "label": obj.label,
            "type": obj.type,
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Raw XML cell extraction
# ---------------------------------------------------------------------------

def _extract_cells_from_raw_xml(
    obj: FCStdObject,
) -> tuple[dict, list, list] | None:
    """
    Extract cell data from the FCStdObject properties.

    Returns (raw_cells_dict, aliased_list, warnings) or None if not available.
    """
    # Check if properties has a pre-parsed list form (from property_parsers)
    pre_parsed = obj.properties.get("_cell_list")
    if isinstance(pre_parsed, list):
        return _cells_from_list(pre_parsed)

    # Fall back to XML fragment stored under a sentinel key
    xml_fragment = obj.properties.get("_raw_cells_xml")
    if isinstance(xml_fragment, (str, bytes)):
        return _cells_from_xml_fragment(xml_fragment)

    return None


def _cells_from_list(
    cell_list: list[dict],
) -> tuple[dict, list, list]:
    """Process a pre-parsed list of cell dicts."""
    raw_cells: dict[str, dict] = {}
    aliased: list[tuple[str, str, str]] = []
    warnings: list[str] = []

    for cell in cell_list:
        address = cell.get("address", "")
        content = cell.get("content", "")
        alias = cell.get("alias", "")
        entry: dict[str, str] = {"content": content}
        if alias:
            entry["alias"] = alias
        raw_cells[address] = entry
        if alias:
            aliased.append((alias, address, content))

    return raw_cells, aliased, warnings


def _cells_from_xml_fragment(
    fragment: str | bytes,
) -> tuple[dict, list, list]:
    """Parse a ``<Cells>...</Cells>`` XML fragment into cell data."""
    import xml.etree.ElementTree as ET

    raw_cells: dict[str, dict] = {}
    aliased: list[tuple[str, str, str]] = []
    warnings: list[str] = []

    if isinstance(fragment, bytes):
        fragment = fragment.decode("utf-8", errors="replace")

    # Wrap in a root element if needed
    if not fragment.strip().startswith("<Cells"):
        fragment = f"<Cells>{fragment}</Cells>"

    try:
        root = ET.fromstring(fragment)
    except ET.ParseError as exc:
        warnings.append(f"failed to parse cell XML fragment: {exc}")
        return raw_cells, aliased, warnings

    for cell_elem in root.iter("Cell"):
        address = cell_elem.get("address", "")
        content = cell_elem.get("content", "")
        alias = cell_elem.get("alias", "")
        if not address:
            continue
        entry: dict[str, str] = {"content": content}
        if alias:
            entry["alias"] = alias
        raw_cells[address] = entry
        if alias:
            aliased.append((alias, address, content))

    return raw_cells, aliased, warnings


# ---------------------------------------------------------------------------
# Cell content parsing
# ---------------------------------------------------------------------------

_UNIT_RE = re.compile(
    r"^(.*?)\s*(mm|cm|m|in|ft|deg|rad|kg|g|N|Pa|MPa|GPa)\s*$",
    re.IGNORECASE,
)


def _parse_cell_content(content: str) -> tuple[str, str]:
    """
    Split a FreeCAD cell content string into (expr, unit).

    FreeCAD cell content examples::

        "2 mm"          → expr="2",               unit="mm"
        "=wall_t / 4"   → expr="wall_t / 4",      unit=""
        "10"            → expr="10",               unit=""
        "45 deg"        → expr="45",               unit="deg"

    Expression cells start with ``=``; the ``=`` is stripped (Kerf's
    evaluator uses bare mathjs, not a spreadsheet ``=`` prefix).
    """
    content = content.strip()
    if not content:
        return "0", ""

    # Strip leading = (FreeCAD formula marker)
    is_formula = content.startswith("=")
    if is_formula:
        expr_raw = content[1:].strip()
        # Formulas typically don't have unit suffixes
        return expr_raw, ""

    # Try to split a trailing unit
    m = _UNIT_RE.match(content)
    if m:
        return m.group(1).strip(), m.group(2).lower()

    return content, ""


# ---------------------------------------------------------------------------
# Name sanitisation
# ---------------------------------------------------------------------------

def _sanitise_name(name: str) -> str:
    """
    Coerce a FreeCAD alias to a valid Kerf parameter name (JS-identifier-ish).

    Rules: letters/digits/underscore, must not start with a digit.
    Invalid chars are replaced with ``_``.
    """
    if not name:
        return "_unnamed"
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if safe[0].isdigit():
        safe = "_" + safe
    return safe
