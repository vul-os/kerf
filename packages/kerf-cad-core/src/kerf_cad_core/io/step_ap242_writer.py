"""Pure-Python STEP AP242 Part 21 writer with semantic PMI (GD&T).

T-550. Companion to :mod:`kerf_cad_core.io.step_writer` (AP214, geometry
only). This module adds the missing direction: Kerf can already **read**
AP242 semantic PMI (:mod:`kerf_imports.ap242_reader`) but until this module
existed it could not **write** it, which is a one-directional wall for any
persona whose contractual deliverable is an AP242 model-based-definition
(MBD) file (aerospace, space, defense primes).

Input shape — Kerf's existing GD&T model, not a new one
--------------------------------------------------------
This writer does **not** invent a new GD&T representation. It takes the
data model that already ships alongside the STEP writer in *this same
package*, :mod:`kerf_cad_core.gdt`:

- :class:`kerf_cad_core.gdt.tolerances.GeometricTolerance` — one feature
  control frame (``feature_name``, ``symbol: ToleranceSymbol``,
  ``tolerance_value``, ``diameter_zone``, ``datum_ref: DatumReferenceFrame``,
  ``modifiers: list[ToleranceModifier]``, ``note``).
- :class:`kerf_cad_core.gdt.datums.Datum` — a nominated datum feature
  (``label``, ``datum_type``, ``feature_ref``, ``description``).
- :class:`kerf_cad_core.gdt.datums.DatumReferenceFrame` — ordered
  primary/secondary/tertiary datum labels.

(``kerf_gdnt`` is a *different* package with a parallel, independently
maintained GD&T model — ``FeatureControlFrame``/``DatumReferenceFrame`` —
aimed at homologation/inspection tooling. It is not used here because
``kerf_cad_core.gdt`` already lives in this package, is exercised by this
package's own test suite (``test_gdt.py``, ``test_gdt_callouts.py``,
``test_gdt_composite_position.py``, ...), and pulling in ``kerf-gdnt``
would add a new cross-package dependency — and a Python-version mismatch,
since ``kerf-gdnt`` requires ``>=3.11`` while this package requires
``>=3.10`` — for no benefit.)

Round-trip oracle
------------------
``kerf_imports.ap242_reader.read_ap242_pmi`` is the oracle. It used to be
a purely regex, single-type-per-instance reader that could not recognise
ISO 10303-21 *complex entity instances* or dereference
``measure_with_unit`` references — which meant the first version of this
writer flattened tolerances into simply-named entities with inline
magnitude literals to match what the reader could then parse. That traded
away real AP242 conformance for round-trip convenience, which defeats the
point of the task (a file only Kerf's own reader can read has not closed
the "cannot write AP242" wall, it has just moved it). So instead **the
reader was extended** (see ``kerf_imports/ap242_reader.py``'s own
docstring for the parser-side detail) to parse complex instances and
dereference ``measure_with_unit``, and this writer emits the schema-
shaped construct the reader now understands. Divergences 1 and 2 below
are therefore resolved; 3–6 remain and are still honestly documented
because fixing them was not required to make the output schema-shaped,
or (6) is out of scope for this task.

Divergences from strict AP242 EXPRESS (read this before you assume a bug)
--------------------------------------------------------------------------
1. **RESOLVED.** ``geometric_tolerance.magnitude`` is now a reference to
   a ``MEASURE_WITH_UNIT(LENGTH_MEASURE(v),#unit)`` entity (see
   ``ensure_length_unit``), not an inline literal. This applies to
   ``GeometricTolerance``-based GD&T tolerances. It does **not** extend to
   ``LINEAR_SIZE``/``PLUS_MINUS_TOLERANCE`` (dimensional sizes) — see
   divergence 5, which is unchanged and still uses inline literals.
2. **RESOLVED.** Each GD&T tolerance is now a genuine ISO 10303-21
   complex entity instance combining the three EXPRESS types multiple
   inheritance actually splits it across:
   ``#N=(GEOMETRIC_TOLERANCE(name,description,#magnitude,#shape_aspect)
   <LEAF_TYPE>()GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE((#dr,...)));``
   — the datum-reference co-type is only present when the tolerance
   actually carries datum references. The leaf type
   (``POSITION_TOLERANCE()``, ``FLATNESS_TOLERANCE()``, ...) correctly
   carries zero attributes of its own, matching the real schema.
3. **Numeric literal always comes first in a *dimensional-size* entity's
   parameter list.** This no longer applies to tolerances (magnitude is a
   reference now, not a literal — see divergence 1's resolution) but still
   applies to ``LINEAR_SIZE``/``PLUS_MINUS_TOLERANCE``, which remain
   inline-literal encodings (divergence 5). ``ap242_reader._first_real``
   does not skip over string literals — it just finds the first
   REAL-looking token in the whole parameter string after entity
   references are stripped. If a name string contained a digit (e.g. a
   feature note like ``"H7 bore"``) and the nominal/deviation value came
   later, the reader would pick up the wrong number. Putting the numeric
   value first sidesteps this reliably. Left as-is (not converted to
   ``measure_with_unit`` references) because doing so was not required to
   resolve the non-conformance the task flagged, and dimensional-size
   asymmetry already has its own documented gap (divergence 5).
4. **``SHAPE_ASPECT.of_shape`` is a placeholder, not a full definitional
   context.** Strict AP242 walks
   ``shape_aspect -> product_definition_shape -> product_definition ->
   product_definition_formation -> product``. ``ap242_reader`` does not
   look at ``SHAPE_ASPECT`` at all (it is not in any of the reader's
   recognised entity-name sets), so this writer emits a single shared
   ``PRODUCT_DEFINITION_SHAPE`` placeholder per document (or, when a
   :class:`~kerf_cad_core.geom.brep.Body` and a ``face_index`` are given,
   a direct reference to that face's ``ADVANCED_FACE`` entity — see
   ``_advanced_face_entity_ids``). This is enough to carry the *semantic*
   GD&T graph (kind, magnitude, datum linkage) that is this task's
   deliverable, but it is not a schema-complete definitional chain.
5. **Dimensional plus/minus asymmetry does not round-trip.**
   ``ap242_reader`` extracts at most one number per entity
   (``_first_real``). A ``LINEAR_SIZE`` recovers ``nominal``; a
   ``PLUS_MINUS_TOLERANCE`` recovers exactly one number (this writer
   emits the upper deviation there). If ``tol_plus_mm != tol_minus_mm``,
   the lower deviation is written to the file (as a later parameter) but
   the reader has no field for it and will not surface it — this is an
   existing reader limitation (its own ``dimensional_sizes`` schema
   hard-codes ``upper_tol``/``lower_tol`` to ``None`` unconditionally),
   not something this writer can fix without changing the reader, which
   is out of scope here.
6. **Composite (two-line PLTZF/FRTZF) tolerance frames are not
   supported.** Only single-line ``GeometricTolerance`` instances are
   emitted. ``kerf_cad_core.gdt.composite_tolerance_check`` /
   ``composite_position`` model two-line composite frames as a distinct
   concept; wiring that into AP242 (each line becoming a separate
   tolerance entity sharing a common grouping construct) is not
   implemented.
7. **No AP242 EXPRESS *schema* validator was available in this
   environment.** No OCCT, pythonocc-core, ST-Developer, or other full
   STEP/EXPRESS toolkit is installed (by design — "pure Python, stdlib
   only" is a hard constraint of this task's own writer code), and no
   AP242 ``.exp`` schema file was available to check attribute types,
   arity, or subtype constraints against. What *was* available and is
   used in this package's test suite
   (``test_output_is_syntactically_valid_iso10303_21_per_third_party_parser``
   in ``test_step_ap242_writer.py``) is ``steputils`` (PyPI, MIT,
   independent of Kerf) — a hand-written ISO-10303-21 **Part 21 grammar**
   parser. It confirms the file is syntactically legal Part 21 (header,
   DATA section, simple *and* complex entity-instance grammar) including
   parsing the complex instances this writer now emits. It does **not**
   check AP242 EXPRESS-schema conformance (attribute types/arity per
   entity, subtype/supertype legality) — that would need the actual
   AP242 schema loaded into an EXPRESS-aware validator, which this
   environment does not have. So: Part 21 grammar conformance is
   verified by a real third-party tool; AP242 EXPRESS-schema conformance
   is asserted **by construction** (entity shapes were written to match
   the standard's published EXPRESS definitions for
   ``geometric_tolerance`` and its subtypes) but is not independently
   verified by a schema-validating tool, and should not be described as
   such. A structural self-check in the test suite additionally confirms
   every ``#N`` reference resolves to a defined entity and the outer
   Part 21 framing (``ISO-10303-21;`` / ``HEADER`` / ``DATA`` / ``ENDSEC``
   / ``END-ISO-10303-21;``) is well-formed.

Entity coverage
----------------
- Header: ``FILE_SCHEMA`` naming the real AP242 edition-2 schema
  identifier ``AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF`` (matches
  ``kerf_imports``' own AP242 test fixtures).
- ``PRODUCT`` / ``PRODUCT_CONTEXT`` / ``APPLICATION_CONTEXT`` (so
  ``ap242_reader``'s ``product`` field round-trips).
- Optional full AP214 B-rep body, reusing
  ``kerf_cad_core.io.step_writer._collect`` verbatim (same entity graph,
  same deterministic IDs) so PMI can decorate a real solid.
- ``DATUM_FEATURE`` + ``DATUM`` per unique datum label, ``DATUM_REFERENCE``
  per (tolerance, ordinal position) pair carrying precedence.
- One ISO 10303-21 **complex entity instance** per :class:`GeometricTolerance`
  — ``GEOMETRIC_TOLERANCE`` + the leaf type named after its ``symbol``
  (``FLATNESS_TOLERANCE``, ``POSITION_TOLERANCE``, ...; see
  :data:`_SYMBOL_TO_ENTITY` for the full map) + (when ``datum_ref`` is
  non-empty) ``GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE`` — with the
  magnitude referencing a ``MEASURE_WITH_UNIT`` entity.
- ``LINEAR_SIZE`` + ``PLUS_MINUS_TOLERANCE`` per :class:`DimensionalSize`
  (these remain simple entities with inline literal values — see
  divergences 3 and 5).

Determinism
-----------
Two calls to :func:`write` with equal inputs produce byte-identical
output — entity IDs are assigned by a plain incrementing counter over the
inputs in the order given (plus the body's own deterministic IDs from
``step_writer._collect`` when a body is supplied), never by hashing or
object identity of the PMI dataclasses.

Usage::

    from kerf_cad_core.gdt import Datum, DatumReferenceFrame, GeometricTolerance, ToleranceSymbol
    from kerf_cad_core.io.step_ap242_writer import (
        ToleranceAnnotation, DatumFeatureAnnotation, write,
    )

    tol = GeometricTolerance(
        feature_name="bore1", symbol=ToleranceSymbol.POSITION,
        tolerance_value=0.1, diameter_zone=True,
        datum_ref=DatumReferenceFrame(primary="A", secondary="B"),
    )
    text = write(
        datum_features=[
            DatumFeatureAnnotation(Datum("A", DatumType.PLANE)),
            DatumFeatureAnnotation(Datum("B", DatumType.PLANE)),
        ],
        tolerances=[ToleranceAnnotation(tol)],
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from kerf_cad_core.geom.brep import Body
from kerf_cad_core.gdt.datums import Datum, DatumReferenceFrame
from kerf_cad_core.gdt.tolerances import GeometricTolerance, ToleranceSymbol
from kerf_cad_core.io.step_writer import _IDPool, _fmt_float, _footer, _collect

__all__ = [
    "ToleranceAnnotation",
    "DatumFeatureAnnotation",
    "DimensionalSize",
    "write",
]

# ---------------------------------------------------------------------------
# AP242 header
# ---------------------------------------------------------------------------

# Real AP242 edition-2 EXPRESS schema identifier — matches the identifier
# used in kerf_imports' own AP242 reader test fixtures, so a file this
# writer produces looks exactly like what kerf_imports already expects to
# see labelled AP242.
_FILE_SCHEMA_AP242 = (
    "'AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }'"
)


def _header_ap242(product_label: str) -> str:
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(('Kerf CAD AP242 PMI export'),'{product_label}');\n"
        "FILE_NAME('','',(''),(''),'kerf-cad-core step_ap242_writer','','');\n"
        f"FILE_SCHEMA(({_FILE_SCHEMA_AP242}));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )


def _escape(s: str) -> str:
    """Part 21 string literal escaping: a literal ``'`` doubles to ``''``."""
    return s.replace("'", "''")


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ToleranceAnnotation:
    """One GD&T callout to emit.

    Parameters
    ----------
    tolerance:
        A :class:`kerf_cad_core.gdt.tolerances.GeometricTolerance`.
        ``tolerance.feature_name`` is used as the toleranced feature's
        label (``SHAPE_ASPECT`` name).
    face_index:
        If a ``body`` is supplied to :func:`write` and this is not
        ``None``, binds the tolerance's shape aspect directly to the
        ``ADVANCED_FACE`` at this index in the body's deterministic
        face order (see ``_advanced_face_entity_ids``). Otherwise the
        shape aspect references the whole-part placeholder.
    """

    tolerance: GeometricTolerance
    face_index: Optional[int] = None


@dataclass
class DatumFeatureAnnotation:
    """One datum feature declaration.

    ``datum`` is a :class:`kerf_cad_core.gdt.datums.Datum`.
    """

    datum: Datum
    face_index: Optional[int] = None


@dataclass
class DimensionalSize:
    """A toleranced linear dimension (nominal ± upper/lower deviation).

    There is no existing dataclass in ``kerf_cad_core.gdt`` for a single
    toleranced *size* dimension (``dimension_chain.DimensionLink`` is the
    closest relative but carries an assembly-stack-up-specific
    ``direction`` field that has no meaning for a single drawing
    dimension), so this is a small, purpose-built holder — not a
    competing GD&T model. Field names (``nominal_mm``, ``tol_plus_mm``,
    ``tol_minus_mm``) intentionally match ``DimensionLink``'s convention.
    """

    feature_name: str
    nominal_mm: float
    tol_plus_mm: float = 0.0
    tol_minus_mm: float = 0.0
    face_index: Optional[int] = None


# ---------------------------------------------------------------------------
# Symbol -> STEP AP242 tolerance entity name
# ---------------------------------------------------------------------------

# Maps kerf_cad_core.gdt.tolerances.ToleranceSymbol -> the AP242 leaf
# entity name that ap242_reader recognises (see
# kerf_imports.ap242_reader._TOLERANCE_ENTITY_NAMES).
_SYMBOL_TO_ENTITY: Dict[ToleranceSymbol, str] = {
    ToleranceSymbol.STRAIGHTNESS: "STRAIGHTNESS_TOLERANCE",
    ToleranceSymbol.FLATNESS: "FLATNESS_TOLERANCE",
    ToleranceSymbol.CIRCULARITY: "CIRCULARITY_TOLERANCE",
    ToleranceSymbol.CYLINDRICITY: "CYLINDRICITY_TOLERANCE",
    ToleranceSymbol.PROFILE_LINE: "LINE_PROFILE_TOLERANCE",
    ToleranceSymbol.PROFILE_SURFACE: "SURFACE_PROFILE_TOLERANCE",
    ToleranceSymbol.PARALLELISM: "PARALLELISM_TOLERANCE",
    ToleranceSymbol.PERPENDICULARITY: "PERPENDICULARITY_TOLERANCE",
    ToleranceSymbol.ANGULARITY: "ANGULARITY_TOLERANCE",
    ToleranceSymbol.POSITION: "POSITION_TOLERANCE",
    ToleranceSymbol.CONCENTRICITY: "CONCENTRICITY_TOLERANCE",
    ToleranceSymbol.SYMMETRY: "SYMMETRY_TOLERANCE",
    ToleranceSymbol.RUNOUT: "CIRCULAR_RUNOUT_TOLERANCE",
    ToleranceSymbol.TOTAL_RUNOUT: "TOTAL_RUNOUT_TOLERANCE",
}


def _entity_name_for_symbol(symbol: ToleranceSymbol) -> str:
    try:
        return _SYMBOL_TO_ENTITY[symbol]
    except KeyError as exc:
        raise ValueError(
            f"step_ap242_writer: no AP242 tolerance entity mapping for "
            f"ToleranceSymbol {symbol!r}. Known symbols: "
            f"{sorted(s.value for s in _SYMBOL_TO_ENTITY)}"
        ) from exc


# ---------------------------------------------------------------------------
# Body integration helpers
# ---------------------------------------------------------------------------

def _advanced_face_entity_ids(body_lines: Sequence[tuple]) -> List[int]:
    """Return ADVANCED_FACE entity ids in body-traversal order.

    ``body_lines`` is ``step_writer._collect(body)``'s return value,
    already sorted by entity id. IDs are assigned sequentially during
    traversal (see step_writer's docstring), so ascending-id order among
    ADVANCED_FACE entities matches ``sorted(shell.faces, key=id)``
    traversal order concatenated across shells — i.e. exactly the order
    a caller would index into via ``face_index``.
    """
    ids: List[int] = []
    for eid, line in body_lines:
        # line looks like "#12=ADVANCED_FACE('face13',(...` — check the
        # entity name right after '='.
        eq = line.find("=")
        if eq != -1 and line[eq + 1:].startswith("ADVANCED_FACE("):
            ids.append(eid)
    return ids


def _whole_part_ref(body_lines: Sequence[tuple]) -> Optional[int]:
    """Best-effort id of the body's root solid/shell, for PMI that isn't
    bound to a specific face."""
    for eid, line in body_lines:
        eq = line.find("=")
        if eq != -1 and line[eq + 1:].startswith("MANIFOLD_SOLID_BREP("):
            return eid
    for eid, line in body_lines:
        eq = line.find("=")
        if eq != -1 and (
            line[eq + 1:].startswith("CLOSED_SHELL(")
            or line[eq + 1:].startswith("OPEN_SHELL(")
        ):
            return eid
    return None


# ---------------------------------------------------------------------------
# Core PMI emission
# ---------------------------------------------------------------------------

def _emit_pmi(
    pool: _IDPool,
    tolerances: Sequence[ToleranceAnnotation],
    datum_features: Sequence[DatumFeatureAnnotation],
    dimensional_sizes: Sequence[DimensionalSize],
    advanced_face_ids: List[int],
    whole_part_id: Optional[int],
) -> List[tuple]:
    lines: List[tuple] = []

    def emit(eid: int, text: str) -> None:
        lines.append((eid, text))

    # Shared PRODUCT_DEFINITION_SHAPE placeholder (divergence #4 above).
    placeholder_pds_id = pool.alloc()
    emit(
        placeholder_pds_id,
        f"#{placeholder_pds_id}=PRODUCT_DEFINITION_SHAPE('','',$);",
    )

    def of_shape_ref(face_index: Optional[int]) -> int:
        """Resolve a face_index (or lack of one) to an entity id to point
        SHAPE_ASPECT.of_shape at. Falls back to a shared placeholder."""
        if face_index is not None and 0 <= face_index < len(advanced_face_ids):
            return advanced_face_ids[face_index]
        if whole_part_id is not None:
            return whole_part_id
        return placeholder_pds_id

    def emit_shape_aspect(label: str, face_index: Optional[int]) -> int:
        sa_id = pool.alloc()
        ref = of_shape_ref(face_index)
        emit(
            sa_id,
            f"#{sa_id}=SHAPE_ASPECT('{_escape(label)}',"
            f"'{_escape(label)} shape aspect',#{ref},.T.);",
        )
        return sa_id

    # ---- Datum features + datums, deduplicated by label -----------------
    datum_entity_by_label: Dict[str, int] = {}

    for ann in datum_features:
        d = ann.datum
        label = str(d.label)
        description = (d.description or "") + f" ({d.datum_type.value})"
        sa_id = emit_shape_aspect(f"datum_{label}", ann.face_index)

        df_id = pool.alloc()
        emit(
            df_id,
            f"#{df_id}=DATUM_FEATURE('{_escape(label)}',"
            f"'{_escape(description)}',#{sa_id});",
        )

        d_id = pool.alloc()
        emit(
            d_id,
            f"#{d_id}=DATUM('{_escape(label)}',"
            f"'{_escape(description)}',#{sa_id},.T.);",
        )
        datum_entity_by_label[label] = d_id

    def ensure_datum(label: str) -> int:
        """Auto-create a minimal DATUM_FEATURE/DATUM pair for a label
        referenced by a GeometricTolerance.datum_ref but not declared via
        `datum_features` — a documented convenience fallback, not silent
        data loss (the label itself is still exact)."""
        if label in datum_entity_by_label:
            return datum_entity_by_label[label]
        sa_id = emit_shape_aspect(f"datum_{label}", None)
        df_id = pool.alloc()
        emit(df_id, f"#{df_id}=DATUM_FEATURE('{_escape(label)}','',#{sa_id});")
        d_id = pool.alloc()
        emit(d_id, f"#{d_id}=DATUM('{_escape(label)}','',#{sa_id},.T.);")
        datum_entity_by_label[label] = d_id
        return d_id

    # ---- Shared LENGTH_UNIT chain for GEOMETRIC_TOLERANCE magnitudes ------
    # Lazily created: only emitted at all if there is at least one
    # tolerance, and shared by every tolerance in the document (all Kerf
    # GD&T tolerance zones are millimetre widths, never angular).
    length_unit_id: Optional[int] = None

    def ensure_length_unit() -> int:
        nonlocal length_unit_id
        if length_unit_id is None:
            si_id = pool.alloc()
            emit(si_id, f"#{si_id}=SI_UNIT($,.MILLI.,.METRE.);")
            unit_id = pool.alloc()
            emit(unit_id, f"#{unit_id}=LENGTH_UNIT(#{si_id});")
            length_unit_id = unit_id
        return length_unit_id

    # ---- Tolerances -------------------------------------------------------
    #
    # Emitted as genuine ISO 10303-21 *complex entity instances* — the
    # syntax the standard actually uses for EXPRESS multiple inheritance —
    # rather than a single flat leaf-named entity. One instance number
    # simultaneously instantiates:
    #   GEOMETRIC_TOLERANCE(name, description, magnitude_ref, shape_aspect)
    #   <leaf-type>()                              -- e.g. POSITION_TOLERANCE()
    #   GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE((datum_ref, ...))   -- only
    #       when the tolerance actually carries datum references
    # magnitude_ref points at a MEASURE_WITH_UNIT entity (also real AP242
    # shape — see ensure_length_unit above), not an inline literal. This
    # closes both divergences 1 and 2 from the module docstring's original
    # list. kerf_imports.ap242_reader has been extended (see that module's
    # own docstring) to parse this syntax and dereference the magnitude, so
    # the round-trip oracle now recovers a schema-shaped file rather than
    # dictating a schema-violating one.
    for ann in tolerances:
        tol = ann.tolerance
        leaf_entity_name = _entity_name_for_symbol(tol.symbol)
        magnitude = float(tol.tolerance_value)
        name = tol.feature_name

        description_bits = [tol.note or ""]
        if tol.modifiers:
            description_bits.append(
                "modifiers=" + ",".join(m.value for m in tol.modifiers)
            )
        if tol.diameter_zone:
            description_bits.append("diameter_zone")
        if tol.is_feature_of_size:
            description_bits.append("feature_of_size")
        if tol.projected_zone_height is not None:
            description_bits.append(f"projected_height={tol.projected_zone_height}")
        description = "; ".join(b for b in description_bits if b)

        sa_id = emit_shape_aspect(name, ann.face_index)

        unit_id = ensure_length_unit()
        measure_id = pool.alloc()
        emit(
            measure_id,
            f"#{measure_id}=MEASURE_WITH_UNIT("
            f"LENGTH_MEASURE({_fmt_float(magnitude)}),#{unit_id});",
        )

        datum_labels = tol.datum_ref.labels if tol.datum_ref else []
        datum_reference_clause = ""
        if datum_labels:
            dr_ids: List[int] = []
            for precedence, label in enumerate(datum_labels, start=1):
                d_id = ensure_datum(label)
                dr_id = pool.alloc()
                emit(
                    dr_id,
                    f"#{dr_id}=DATUM_REFERENCE({precedence},#{d_id});",
                )
                dr_ids.append(dr_id)
            refs_list = ",".join(f"#{i}" for i in dr_ids)
            datum_reference_clause = (
                f"GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE(({refs_list}))"
            )

        tol_id = pool.alloc()
        emit(
            tol_id,
            f"#{tol_id}=(GEOMETRIC_TOLERANCE('{_escape(name)}',"
            f"'{_escape(description)}',#{measure_id},#{sa_id})"
            f"{leaf_entity_name}()"
            f"{datum_reference_clause});",
        )

    # ---- Dimensional sizes --------------------------------------------
    for dsz in dimensional_sizes:
        sa_id = emit_shape_aspect(dsz.feature_name, dsz.face_index)

        lin_id = pool.alloc()
        emit(
            lin_id,
            f"#{lin_id}=LINEAR_SIZE({_fmt_float(float(dsz.nominal_mm))},"
            f"'{_escape(dsz.feature_name)}',#{sa_id});",
        )

        pm_id = pool.alloc()
        emit(
            pm_id,
            f"#{pm_id}=PLUS_MINUS_TOLERANCE("
            f"{_fmt_float(float(dsz.tol_plus_mm))},"
            f"{_fmt_float(float(dsz.tol_minus_mm))},"
            f"'{_escape(dsz.feature_name)}',#{lin_id});",
        )

    lines.sort(key=lambda x: x[0])
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write(
    body: Optional[Body] = None,
    tolerances: Sequence[ToleranceAnnotation] = (),
    datum_features: Sequence[DatumFeatureAnnotation] = (),
    dimensional_sizes: Sequence[DimensionalSize] = (),
    path: Optional[str] = None,
    label: str = "kerf_export",
    product_name: Optional[str] = None,
) -> str:
    """Serialise GD&T + (optionally) a B-rep body to an AP242 Part 21 string.

    Parameters
    ----------
    body:
        Optional :class:`~kerf_cad_core.geom.brep.Body`. When given, its
        full B-rep is emitted first (byte-for-byte the same entity graph
        ``kerf_cad_core.io.step_writer.write`` would produce for it,
        reusing ``_collect`` verbatim) and PMI entities reference its
        faces where ``face_index`` is supplied on an annotation.
    tolerances, datum_features, dimensional_sizes:
        The GD&T content to emit — see :class:`ToleranceAnnotation`,
        :class:`DatumFeatureAnnotation`, :class:`DimensionalSize`.
    path:
        If given, write the result to this file path (UTF-8).
    label:
        Label embedded in FILE_DESCRIPTION.
    product_name:
        Name for the PRODUCT entity (defaults to ``label``).

    Returns
    -------
    str
        The full AP242 Part 21 text (header + data + footer).
    """
    product_name = product_name or label

    parts: List[str] = [_header_ap242(product_name)]

    body_lines: List[tuple] = []
    if body is not None:
        body_lines = _collect(body)
        for _eid, line in body_lines:
            parts.append(line + "\n")

    body_max_id = max((eid for eid, _ in body_lines), default=0)

    # Header entities: PRODUCT / PRODUCT_CONTEXT / APPLICATION_CONTEXT.
    # Numbered to start right after the body's ids (or at 1 if no body),
    # so they never collide with step_writer's own numbering.
    header_pool = _IDPool()
    header_pool._next = body_max_id + 1  # continue numbering; see module docstring

    actx_id = header_pool.alloc()
    parts.append(
        f"#{actx_id}=APPLICATION_CONTEXT("
        f"'managed model based 3d engineering');\n"
    )
    pctx_id = header_pool.alloc()
    parts.append(f"#{pctx_id}=PRODUCT_CONTEXT('',#{actx_id},'mechanical');\n")
    pid = header_pool.alloc()
    parts.append(
        f"#{pid}=PRODUCT('{_escape(product_name)}',"
        f"'{_escape(product_name)}',$,(#{pctx_id}));\n"
    )

    # PMI entities continue numbering after the header entities.
    pmi_pool = _IDPool()
    pmi_pool._next = header_pool.next_id

    advanced_face_ids = _advanced_face_entity_ids(body_lines)
    whole_part_id = _whole_part_ref(body_lines)

    pmi_lines = _emit_pmi(
        pmi_pool,
        tolerances,
        datum_features,
        dimensional_sizes,
        advanced_face_ids,
        whole_part_id,
    )
    for _eid, line in pmi_lines:
        parts.append(line + "\n")

    parts.append(_footer())
    result = "".join(parts)

    if path is not None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(result)

    return result
