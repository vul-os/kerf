"""
ap242_reader.py — AP242 PMI / GD&T annotation reader.

Parses STEP Part 21 files (AP242 ed.1/ed.2) at the text level — no OCCT or
kernel dependency.  Extracts:

  • PMI annotations (DRAUGHTING_CALLOUT, ANNOTATION_OCCURRENCE,
    PMI_REPRESENTATION_ITEM, ANNOTATION_PLANE)
  • Datum reference frames (DATUM_FEATURE, DATUM_REFERENCE_COMPARTMENT,
    DATUM_REFERENCE_ELEMENT, DATUM)
  • GD&T tolerances (GEOMETRIC_TOLERANCE, GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE,
    PLUS_MINUS_TOLERANCE, SYMMETRY_TOLERANCE, CYLINDRICITY_TOLERANCE,
    FLATNESS_TOLERANCE, PERPENDICULARITY_TOLERANCE, PARALLELISM_TOLERANCE,
    ANGULARITY_TOLERANCE, CIRCULARITY_TOLERANCE, STRAIGHTNESS_TOLERANCE,
    POSITION_TOLERANCE, TOTAL_RUNOUT_TOLERANCE, CIRCULAR_RUNOUT_TOLERANCE)
  • Dimensional sizes (DIMENSIONAL_SIZE, LINEAR_SIZE,
    DIMENSIONAL_CHARACTERISTIC_REPRESENTATION)

Entity tokeniser is shared with the STEP reader in kerf_cad_core.io.step_reader
(regex-level: #NNN = ENTITY_NAME(...)).

Complex entity instances
─────────────────────────
Real AP242 files express EXPRESS multiple inheritance (e.g. a tolerance
that is simultaneously a ``geometric_tolerance``, a specific leaf type
such as ``position_tolerance``, and — when it carries datum references —
a ``geometric_tolerance_with_datum_reference``) using ISO 10303-21
*complex entity instance* syntax::

    #10=(GEOMETRIC_TOLERANCE('name','desc',#21,#22)POSITION_TOLERANCE()
         GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE((#23)));

i.e. one instance number, several co-instantiated type records
back-to-back inside one outer set of parentheses, with no name before
the first ``(``. ``_normalise_entities`` recognises this form (in
addition to plain ``#N=NAME(...)`` simple instances) via
``_split_complex_instance`` and yields one ``(id, type_name, params)``
tuple *per co-type*, all sharing the same instance id — so a complex
tolerance instance produces multiple tuples with the same ``id`` and
different ``type_name``/``params``. ``read_ap242_pmi`` groups tuples by
id before building the ``tolerances`` list (see ``_dereference_magnitude``
and the tolerance-processing loop below), so a complex instance is
reported as a single tolerance record — kind taken from the most specific
(leaf) co-type, refs merged across all tolerance-family co-types at that
id, magnitude dereferenced through any ``...MEASURE_WITH_UNIT``-style
entity referenced from it (falling back to an inline literal for
older/simpler encodings that don't use a measure reference at all).

This also means ``geometric_tolerance.magnitude`` no longer needs to be a
bare inline number: if it references a ``measure_with_unit`` entity whose
own parameters embed a typed measure value (``LENGTH_MEASURE(0.05)``,
``PLANE_ANGLE_MEASURE(0.02)``, ...), that value is dereferenced and used
as ``magnitude``. This is a genuine, if partial, EXPRESS-aware capability
(dereferencing one hop through a SELECT-typed value) — it is still not a
general EXPRESS processor: only measure dereferencing and complex
instances for the tolerance-entity family are handled, nothing else.

Output schema
─────────────
read_ap242_pmi(step_text) → {
  "ok": True,
  "schema": str | None,
  "product": str | None,
  "annotations": [
    {
      "kind": "pmi_annotation" | "draughting_callout" | "annotation_plane",
      "id": int,          # entity ID
      "name": str | None,
      "refs": [int],      # referenced entity IDs
    },
    ...
  ],
  "datums": [
    {
      "kind": "datum_feature" | "datum" | "datum_reference",
      "id": int,
      "label": str | None,
      "refs": [int],
    },
    ...
  ],
  "tolerances": [
    {
      "kind": str,          # e.g. "GEOMETRIC_TOLERANCE", "FLATNESS_TOLERANCE" …
      "id": int,
      "name": str | None,
      "magnitude": float | None,
      "unit": str | None,
      "refs": [int],
    },
    ...
  ],
  "dimensional_sizes": [
    {
      "id": int,
      "name": str | None,
      "nominal": float | None,
      "upper_tol": float | None,
      "lower_tol": float | None,
      "refs": [int],
    },
    ...
  ],
  "drawing_annotations": [
    # Merged flat list suitable for a .drawing annotation list.
    # Each item: {"type": str, "label": str, "id": int, "refs": [int]}
    ...
  ],
  "warnings": [str],
}
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["read_ap242_pmi", "AP242ReadError"]


class AP242ReadError(ValueError):
    """Raised only for completely unparseable input."""


# ─── Regex constants ──────────────────────────────────────────────────────────

# Entity line: #NNN = ENTITY_NAME ( ... )
_ENTITY_RE = re.compile(
    r"#(\d+)\s*=\s*([A-Z_][A-Z0-9_]*)\s*\((.*)\)\s*;",
    re.DOTALL,
)

# STEP file may split entities over many physical lines; we need to reassemble.
# We normalise into one logical line per entity before applying _ENTITY_RE.

_REF_RE = re.compile(r"#(\d+)")
_STRING_RE = re.compile(r"'([^']*)'")
_REAL_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?")

# PMI annotation entity names
_PMI_ENTITY_NAMES: frozenset[str] = frozenset({
    "PMI_REPRESENTATION_ITEM",
    "DRAUGHTING_CALLOUT",
    "ANNOTATION_OCCURRENCE",
    "ANNOTATION_PLANE",
    "ANNOTATION_FILL_AREA",
    "DRAUGHTING_ELEMENTS",
    "DRAUGHTING_MODEL_ITEM_ASSOCIATION",
    "ANNOTATION_TEXT",
})

# Datum entity names
_DATUM_ENTITY_NAMES: frozenset[str] = frozenset({
    "DATUM_FEATURE",
    "DATUM",
    "DATUM_REFERENCE",
    "DATUM_REFERENCE_COMPARTMENT",
    "DATUM_REFERENCE_ELEMENT",
    "DATUM_TARGET",
    "PLACED_DATUM_TARGET_FEATURE",
    "DATUM_SYSTEM",
    "REFERENCE_ELEMENT",
})

# Tolerance entity names
_TOLERANCE_ENTITY_NAMES: frozenset[str] = frozenset({
    "GEOMETRIC_TOLERANCE",
    "GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE",
    "GEOMETRIC_TOLERANCE_WITH_DEFINED_UNIT",
    "PLUS_MINUS_TOLERANCE",
    "SYMMETRY_TOLERANCE",
    "CYLINDRICITY_TOLERANCE",
    "FLATNESS_TOLERANCE",
    "PERPENDICULARITY_TOLERANCE",
    "PARALLELISM_TOLERANCE",
    "ANGULARITY_TOLERANCE",
    "CIRCULARITY_TOLERANCE",
    "STRAIGHTNESS_TOLERANCE",
    "POSITION_TOLERANCE",
    "TOTAL_RUNOUT_TOLERANCE",
    "CIRCULAR_RUNOUT_TOLERANCE",
    "SURFACE_PROFILE_TOLERANCE",
    "LINE_PROFILE_TOLERANCE",
    "CONCENTRICITY_TOLERANCE",
    "COAXIALITY_TOLERANCE",
    "TOLERANCE_VALUE",
})

# The generic EXPRESS supertypes a tolerance complex-instance co-instantiates
# alongside its specific leaf type (e.g. POSITION_TOLERANCE,
# FLATNESS_TOLERANCE, ...). When merging a complex instance's co-types into
# one tolerance record, the *leaf* type is reported as "kind" in preference
# to these — the leaf is what actually says which GD&T symbol this is; the
# generic wrapper by itself is ambiguous (e.g. GEOMETRIC_TOLERANCE_WITH_
# DATUM_REFERENCE alone could be perpendicularity, position, symmetry, ...).
_GENERIC_TOLERANCE_WRAPPER_NAMES: frozenset[str] = frozenset({
    "GEOMETRIC_TOLERANCE",
    "GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE",
    "GEOMETRIC_TOLERANCE_WITH_DEFINED_UNIT",
})

# Dimensional size entity names
_DIM_ENTITY_NAMES: frozenset[str] = frozenset({
    "DIMENSIONAL_SIZE",
    "DIMENSIONAL_SIZE_WITH_PATH",
    "LINEAR_SIZE",
    "DIMENSIONAL_CHARACTERISTIC_REPRESENTATION",
    "DIMENSION_RELATED_TOLERANCE_ZONE_ELEMENT",
})

# Combined set for fast entity-type routing
_ALL_PMI_TYPES = (
    _PMI_ENTITY_NAMES
    | _DATUM_ENTITY_NAMES
    | _TOLERANCE_ENTITY_NAMES
    | _DIM_ENTITY_NAMES
)


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)


def _first_string(params: str) -> str | None:
    m = _STRING_RE.search(params)
    return m.group(1) if m else None


def _all_refs(params: str) -> list[int]:
    return [int(m.group(1)) for m in _REF_RE.finditer(params)]


def _first_real(params: str) -> float | None:
    # Skip entity references (e.g. #12) before scanning for floats
    stripped = _REF_RE.sub(" ", params)
    m = _REAL_RE.search(stripped)
    try:
        return float(m.group()) if m else None
    except (ValueError, AttributeError):
        return None


# A typed ("SELECT") measure value embedded as a parameter, e.g.
# LENGTH_MEASURE(0.05) or PLANE_ANGLE_MEASURE(0.02) — this is how
# measure_with_unit's value_component attribute is serialised in real
# STEP files (see ap242_pmi_sample.stp fixture and
# kerf_cad_core.io.step_ap242_writer's MEASURE_WITH_UNIT emission).
_MEASURE_VALUE_RE = re.compile(
    r"[A-Z_]*MEASURE\s*\(\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?)\s*\)"
)


def _dereference_magnitude(
    by_id: dict[int, list[tuple[str, str]]], ref_ids: list[int]
) -> float | None:
    """
    Given the ids a tolerance entity references (in the order they appear),
    find the first one whose own entity record embeds a typed measure value
    (``..._MEASURE(value)``, e.g. inside a ``MEASURE_WITH_UNIT`` entity) and
    return that value.

    This is what lets ``geometric_tolerance.magnitude`` be a real reference
    to a ``measure_with_unit`` entity (as strict AP242 requires) rather than
    a bare inline literal on the tolerance entity itself: the magnitude is
    one dereference hop away, and this function performs that hop. Returns
    ``None`` if no referenced entity carries a recognisable measure value.
    """
    for rid in ref_ids:
        for _ename, params in by_id.get(rid, []):
            m = _MEASURE_VALUE_RE.search(params)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
    return None


_SIMPLE_INSTANCE_RE = re.compile(
    r"^#(\d+)\s*=\s*([A-Z_][A-Z0-9_]*)\s*\((.*)\)\s*$", re.DOTALL
)
_COMPLEX_INSTANCE_RE = re.compile(r"^#(\d+)\s*=\s*\((.*)\)\s*$", re.DOTALL)
_IDENT_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


def _split_complex_instance(inner: str) -> list[tuple[str, str]]:
    """
    Split the body of an ISO 10303-21 *complex entity instance* — already
    stripped of its outer parentheses, e.g.
    ``GEOMETRIC_TOLERANCE('a','b',#1,#2)POSITION_TOLERANCE()`` — into a
    list of ``(type_name, params)`` pairs, one per co-instantiated type.

    Each co-type is ``NAME(...)`` back-to-back with no separator; the
    parameter list can itself contain nested parentheses (e.g. a datum
    reference list ``((#12,#13))``) and string literals containing
    parentheses, so this is a small hand-written scanner rather than a
    regex — the same reason ``_normalise_entities`` uses one for the
    outer statement split.
    """
    parts: list[tuple[str, str]] = []
    i = 0
    n = len(inner)
    while i < n:
        while i < n and inner[i].isspace():
            i += 1
        if i >= n:
            break
        m = _IDENT_RE.match(inner, i)
        if not m:
            break
        name = m.group(0)
        j = m.end()
        while j < n and inner[j].isspace():
            j += 1
        if j >= n or inner[j] != "(":
            break
        depth = 0
        in_string = False
        k = j
        start_params = j + 1
        while k < n:
            ch = inner[k]
            if ch == "'" and not in_string:
                in_string = True
            elif ch == "'" and in_string:
                in_string = False
            elif ch == "(" and not in_string:
                depth += 1
            elif ch == ")" and not in_string:
                depth -= 1
                if depth == 0:
                    break
            k += 1
        params = inner[start_params:k]
        parts.append((name.upper(), params))
        i = k + 1
    return parts


def _normalise_entities(text: str) -> list[tuple[int, str, str]]:
    """
    Reassemble multi-line entity instances into (id, name, params) tuples.

    STEP Part 21 entities can span many lines terminated by ';'.
    Strategy: remove comments, then scan for '#NNN = NAME(' ...');\n' patterns
    by collecting characters until the statement is balanced.

    Both plain *simple* entity instances (``#N=NAME(...)``) and ISO
    10303-21 *complex* entity instances (``#N=(NAME1(...)NAME2(...));``,
    used for EXPRESS multiple inheritance) are recognised. A complex
    instance yields multiple tuples that all share the same ``id`` — one
    per co-instantiated type — via :func:`_split_complex_instance`.
    """
    text = _strip_comments(text)
    results: list[tuple[int, str, str]] = []

    # Find DATA section
    data_m = re.search(r"DATA\s*;", text, re.IGNORECASE)
    end_m = re.search(r"ENDSEC\s*;", text[data_m.end():] if data_m else text, re.IGNORECASE)

    if data_m:
        start = data_m.end()
        end = (start + end_m.start()) if end_m else len(text)
        data_section = text[start:end]
    else:
        data_section = text

    # Tokenise by ';' boundaries, being careful about strings
    # Simple approach: split by ';' when we're not inside a string literal
    statements: list[str] = []
    cur: list[str] = []
    in_string = False
    for ch in data_section:
        if ch == "'" and not in_string:
            in_string = True
            cur.append(ch)
        elif ch == "'" and in_string:
            in_string = False
            cur.append(ch)
        elif ch == ";" and not in_string:
            stmt = "".join(cur).strip()
            if stmt:
                statements.append(stmt)
            cur = []
        else:
            cur.append(ch)

    for stmt in statements:
        # Collapse whitespace/newlines
        stmt = re.sub(r"\s+", " ", stmt).strip()

        m = _SIMPLE_INSTANCE_RE.match(stmt)
        if m:
            eid = int(m.group(1))
            ename = m.group(2).upper()
            params = m.group(3)
            results.append((eid, ename, params))
            continue

        m = _COMPLEX_INSTANCE_RE.match(stmt)
        if m:
            eid = int(m.group(1))
            inner = m.group(2)
            for ename, params in _split_complex_instance(inner):
                results.append((eid, ename, params))
            continue

    return results


# ─── Public reader ────────────────────────────────────────────────────────────

def read_ap242_pmi(step_text: str) -> dict[str, Any]:
    """
    Parse AP242 PMI / GD&T annotations from a STEP Part 21 text string.

    Returns a structured dict with keys: ok, schema, product, annotations,
    datums, tolerances, dimensional_sizes, drawing_annotations, warnings.
    """
    warnings: list[str] = []

    # ── Header fields ──────────────────────────────────────────────────────
    schema: str | None = None
    product: str | None = None

    m_schema = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", step_text, re.IGNORECASE)
    if m_schema:
        schema = m_schema.group(1)
        if "AP242" not in schema.upper():
            warnings.append(f"FILE_SCHEMA is '{schema}' — not AP242; continuing anyway")

    m_prod = re.search(r"\bPRODUCT\s*\(\s*'([^']*)'", step_text, re.IGNORECASE)
    if m_prod:
        product = m_prod.group(1)

    # ── Parse entity instances ─────────────────────────────────────────────
    try:
        entities = _normalise_entities(step_text)
    except Exception as exc:
        return {"ok": False, "reason": f"entity parse error: {exc}"}

    annotations: list[dict] = []
    datums: list[dict] = []
    tolerances: list[dict] = []
    dimensional_sizes: list[dict] = []

    # Every (id -> [(name, params), ...]) tuple set, including entities
    # outside the PMI/datum/tolerance/dim families (e.g. MEASURE_WITH_UNIT,
    # SHAPE_ASPECT) — needed so tolerance magnitude dereferencing can look
    # up whatever an entity's refs point at, regardless of that target's
    # own category.
    by_id: dict[int, list[tuple[str, str]]] = {}
    for eid, ename, params in entities:
        by_id.setdefault(eid, []).append((ename, params))

    seen_tolerance_ids: set[int] = set()

    for eid, ename, params in entities:
        if ename in _PMI_ENTITY_NAMES:
            annotations.append({
                "kind": ename.lower(),
                "id": eid,
                "name": _first_string(params),
                "refs": _all_refs(params),
            })

        elif ename in _DATUM_ENTITY_NAMES:
            datums.append({
                "kind": ename.lower(),
                "id": eid,
                "label": _first_string(params),
                "refs": _all_refs(params),
            })

        elif ename in _TOLERANCE_ENTITY_NAMES:
            # A complex entity instance (see _split_complex_instance) yields
            # several (id, name, params) tuples that share one id — one per
            # EXPRESS co-type (e.g. GEOMETRIC_TOLERANCE + POSITION_TOLERANCE
            # + GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE). Process each id
            # exactly once, merging across all of its tolerance-family
            # co-types, so a complex instance becomes one tolerance record
            # rather than one per co-type.
            if eid in seen_tolerance_ids:
                continue
            seen_tolerance_ids.add(eid)

            sub_parts = [
                (n, p) for n, p in by_id.get(eid, []) if n in _TOLERANCE_ENTITY_NAMES
            ]
            if not sub_parts:
                sub_parts = [(ename, params)]

            names = [n for n, _ in sub_parts]
            leaf_candidates = [
                n for n in names if n not in _GENERIC_TOLERANCE_WRAPPER_NAMES
            ]
            kind = leaf_candidates[0] if leaf_candidates else names[0]

            merged_refs: list[int] = []
            for _n, p in sub_parts:
                for r in _all_refs(p):
                    if r not in merged_refs:
                        merged_refs.append(r)

            name_val: str | None = None
            for _n, p in sub_parts:
                s = _first_string(p)
                if s is not None:
                    name_val = s
                    break

            magnitude = _dereference_magnitude(by_id, merged_refs)
            if magnitude is None:
                # Back-compat fallback: a bare inline literal in one of the
                # co-type's own parameter lists (older/simpler encodings
                # that never used a measure_with_unit reference).
                for _n, p in sub_parts:
                    v = _first_real(p)
                    if v is not None:
                        magnitude = v
                        break

            tolerances.append({
                "kind": kind,
                "id": eid,
                "name": name_val,
                "magnitude": magnitude,
                "unit": None,
                "refs": merged_refs,
            })

        elif ename in _DIM_ENTITY_NAMES:
            nominal = _first_real(params)
            dimensional_sizes.append({
                "id": eid,
                "name": _first_string(params),
                "nominal": nominal,
                "upper_tol": None,
                "lower_tol": None,
                "refs": _all_refs(params),
            })

    # ── Build flat drawing_annotations list ───────────────────────────────
    drawing_annotations: list[dict] = []

    for ann in annotations:
        label = ann.get("name") or ann["kind"].replace("_", " ").title()
        drawing_annotations.append({
            "type": ann["kind"],
            "label": label,
            "id": ann["id"],
            "refs": ann["refs"],
        })

    for datum in datums:
        label = datum.get("label") or datum["kind"].replace("_", " ").title()
        drawing_annotations.append({
            "type": datum["kind"],
            "label": label,
            "id": datum["id"],
            "refs": datum["refs"],
        })

    for tol in tolerances:
        mag_str = f" ±{tol['magnitude']}" if tol["magnitude"] is not None else ""
        label = (tol.get("name") or tol["kind"].replace("_", " ").title()) + mag_str
        drawing_annotations.append({
            "type": tol["kind"].lower(),
            "label": label,
            "id": tol["id"],
            "refs": tol["refs"],
        })

    for dim in dimensional_sizes:
        nom_str = f" {dim['nominal']}" if dim["nominal"] is not None else ""
        label = (dim.get("name") or "Dimensional Size") + nom_str
        drawing_annotations.append({
            "type": "dimensional_size",
            "label": label,
            "id": dim["id"],
            "refs": dim["refs"],
        })

    return {
        "ok": True,
        "schema": schema,
        "product": product,
        "annotations": annotations,
        "datums": datums,
        "tolerances": tolerances,
        "dimensional_sizes": dimensional_sizes,
        "drawing_annotations": drawing_annotations,
        "warnings": warnings,
    }
