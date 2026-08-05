"""Pytest suite for kerf_cad_core.io.step_ap242_writer (T-550).

Round-trip oracle: kerf_imports.ap242_reader.read_ap242_pmi. Every GD&T
tolerance type the reader recognises (kerf_cad_core.gdt.tolerances
.ToleranceSymbol's 14 values, plus PLUS_MINUS_TOLERANCE for dimensional
sizes) gets its own round-trip test, plus structural / determinism /
AP214-non-regression / body-integration coverage.

NOTE on import order: importing ``kerf_cad_core.geom.brep`` before
``kerf_cad_core.io.*`` avoids a pre-existing circular-import quirk in
this package (``kerf_cad_core/io/__init__.py`` -> ``step_reader`` ->
``geom.brep`` -> ``geom/__init__`` -> ``geom.io.step_read`` -> back into
``kerf_cad_core.io.step_reader`` while it is still initialising). The
existing ``test_step_writer.py`` follows the same convention; it is not
something this task introduced.
"""

from __future__ import annotations

import re

import pytest

from kerf_cad_core.geom.brep import make_box

from kerf_cad_core.gdt import Datum, DatumReferenceFrame, GeometricTolerance, ToleranceSymbol
from kerf_cad_core.gdt.datums import DatumType
from kerf_cad_core.gdt.modifiers import ToleranceModifier
from kerf_cad_core.io.step_writer import write as write_ap214
from kerf_cad_core.io.step_ap242_writer import (
    DatumFeatureAnnotation,
    DimensionalSize,
    ToleranceAnnotation,
    write,
)

from kerf_imports.ap242_reader import read_ap242_pmi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_ENTITY_REF_RE = re.compile(r"#(\d+)")
_ENTITY_DEF_RE = re.compile(r"#(\d+)\s*=")


def _defined_ids(text: str) -> set[int]:
    return {int(m.group(1)) for m in _ENTITY_DEF_RE.finditer(text)}


def _referenced_ids(text: str) -> set[int]:
    # Every '#NNN' anywhere in the DATA section, including inside parameter
    # lists and nested lists — this deliberately over-counts (also matches
    # the defining '#NNN=' token) but that's fine: we only use it to check
    # "every reference resolves", not to count references precisely.
    data = text.split("DATA;", 1)[1] if "DATA;" in text else text
    return {int(m.group(1)) for m in _ALL_ENTITY_REF_RE.finditer(data)}


def _assert_well_formed_part21(text: str) -> None:
    assert text.strip().startswith("ISO-10303-21;")
    assert text.strip().endswith("END-ISO-10303-21;")
    assert "DATA;" in text and "ENDSEC;" in text
    defined = _defined_ids(text)
    referenced = _referenced_ids(text)
    dangling = referenced - defined
    assert not dangling, f"dangling entity references: {sorted(dangling)}"


# ---------------------------------------------------------------------------
# Header / structure
# ---------------------------------------------------------------------------

def test_file_schema_is_ap242_not_ap214():
    text = write(tolerances=[
        ToleranceAnnotation(GeometricTolerance(
            feature_name="f", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02,
        ))
    ])
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    assert m is not None
    assert "AP242" in m.group(1)
    assert "AP214" not in m.group(1)
    assert "AUTOMOTIVE_DESIGN" not in m.group(1)


def test_document_is_well_formed_part21():
    tol = GeometricTolerance(feature_name="f", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(tolerances=[ToleranceAnnotation(tol)])
    _assert_well_formed_part21(text)


def test_reader_accepts_the_schema_without_warning():
    tol = GeometricTolerance(feature_name="f", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(tolerances=[ToleranceAnnotation(tol)])
    result = read_ap242_pmi(text)
    assert result["ok"] is True
    assert not any("not AP242" in w for w in result["warnings"])


def test_product_name_round_trips():
    tol = GeometricTolerance(feature_name="f", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(tolerances=[ToleranceAnnotation(tol)], product_name="BracketA")
    result = read_ap242_pmi(text)
    assert result["product"] == "BracketA"


def test_write_is_deterministic():
    tol = GeometricTolerance(
        feature_name="bore1", symbol=ToleranceSymbol.POSITION, tolerance_value=0.1,
        diameter_zone=True, datum_ref=DatumReferenceFrame(primary="A", secondary="B"),
    )
    kwargs = dict(
        datum_features=[
            DatumFeatureAnnotation(Datum("A", DatumType.PLANE)),
            DatumFeatureAnnotation(Datum("B", DatumType.PLANE)),
        ],
        tolerances=[ToleranceAnnotation(tol)],
        dimensional_sizes=[DimensionalSize("bore1", 25.0, 0.05, 0.05)],
        product_name="WidgetBody",
    )
    t1 = write(**kwargs)
    t2 = write(**kwargs)
    assert t1 == t2


def test_write_to_file(tmp_path):
    tol = GeometricTolerance(feature_name="f", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    p = tmp_path / "out.stp"
    text = write(tolerances=[ToleranceAnnotation(tol)], path=str(p))
    assert p.read_text(encoding="utf-8") == text


def test_semantic_pmi_has_no_graphical_annotations():
    """This writer emits GEOMETRIC_TOLERANCE-family entities directly — no
    DRAUGHTING_CALLOUT / ANNOTATION_OCCURRENCE presentation layer. That is
    the semantic-vs-graphical distinction the task calls out: tolerances
    must be present as machine-readable entities even with zero graphical
    annotation entities."""
    tol = GeometricTolerance(feature_name="f", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(tolerances=[ToleranceAnnotation(tol)])
    result = read_ap242_pmi(text)
    assert result["annotations"] == []
    assert len(result["tolerances"]) == 1


# ---------------------------------------------------------------------------
# Every GD&T tolerance type the reader supports — one test each
# ---------------------------------------------------------------------------

# (symbol, expected AP242 entity name, whether the test FCF carries datum refs)
_TOLERANCE_CASES = [
    (ToleranceSymbol.STRAIGHTNESS, "STRAIGHTNESS_TOLERANCE", False),
    (ToleranceSymbol.FLATNESS, "FLATNESS_TOLERANCE", False),
    (ToleranceSymbol.CIRCULARITY, "CIRCULARITY_TOLERANCE", False),
    (ToleranceSymbol.CYLINDRICITY, "CYLINDRICITY_TOLERANCE", False),
    (ToleranceSymbol.PROFILE_LINE, "LINE_PROFILE_TOLERANCE", False),
    (ToleranceSymbol.PROFILE_SURFACE, "SURFACE_PROFILE_TOLERANCE", False),
    (ToleranceSymbol.PARALLELISM, "PARALLELISM_TOLERANCE", True),
    (ToleranceSymbol.PERPENDICULARITY, "PERPENDICULARITY_TOLERANCE", True),
    (ToleranceSymbol.ANGULARITY, "ANGULARITY_TOLERANCE", True),
    (ToleranceSymbol.POSITION, "POSITION_TOLERANCE", True),
    (ToleranceSymbol.CONCENTRICITY, "CONCENTRICITY_TOLERANCE", True),
    (ToleranceSymbol.SYMMETRY, "SYMMETRY_TOLERANCE", True),
    (ToleranceSymbol.RUNOUT, "CIRCULAR_RUNOUT_TOLERANCE", True),
    (ToleranceSymbol.TOTAL_RUNOUT, "TOTAL_RUNOUT_TOLERANCE", True),
]


@pytest.mark.parametrize("symbol,entity_name,with_datum", _TOLERANCE_CASES)
def test_tolerance_type_round_trips(symbol, entity_name, with_datum):
    datum_ref = DatumReferenceFrame(primary="A") if with_datum else DatumReferenceFrame()
    tol = GeometricTolerance(
        feature_name="feat_x",
        symbol=symbol,
        tolerance_value=0.075,
        datum_ref=datum_ref,
    )
    datum_features = (
        [DatumFeatureAnnotation(Datum("A", DatumType.PLANE))] if with_datum else []
    )
    text = write(
        tolerances=[ToleranceAnnotation(tol)],
        datum_features=datum_features,
    )
    _assert_well_formed_part21(text)
    result = read_ap242_pmi(text)

    kinds = {t["kind"] for t in result["tolerances"]}
    assert entity_name in kinds, f"expected {entity_name} in {kinds}"

    entry = next(t for t in result["tolerances"] if t["kind"] == entity_name)
    assert entry["magnitude"] == pytest.approx(0.075)
    assert entry["name"] == "feat_x"

    if with_datum:
        datum_labels = {d["label"] for d in result["datums"] if d.get("label")}
        assert "A" in datum_labels


def test_all_symbols_have_an_entity_mapping():
    """Every ToleranceSymbol enum member must be covered — this catches a
    future symbol addition that forgot to update the AP242 writer's map."""
    from kerf_cad_core.io.step_ap242_writer import _SYMBOL_TO_ENTITY

    for sym in ToleranceSymbol:
        assert sym in _SYMBOL_TO_ENTITY, f"{sym} has no AP242 entity mapping"


def test_unmapped_symbol_raises_clear_error():
    from kerf_cad_core.io.step_ap242_writer import _entity_name_for_symbol

    with pytest.raises(ValueError, match="no AP242 tolerance entity mapping"):
        _entity_name_for_symbol("not-a-real-symbol")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Datum reference frame precedence + auto-fallback
# ---------------------------------------------------------------------------

def test_primary_secondary_tertiary_datums_round_trip():
    tol = GeometricTolerance(
        feature_name="slot1", symbol=ToleranceSymbol.POSITION, tolerance_value=0.2,
        datum_ref=DatumReferenceFrame(primary="A", secondary="B", tertiary="C"),
    )
    text = write(
        datum_features=[
            DatumFeatureAnnotation(Datum("A", DatumType.PLANE)),
            DatumFeatureAnnotation(Datum("B", DatumType.PLANE)),
            DatumFeatureAnnotation(Datum("C", DatumType.POINT)),
        ],
        tolerances=[ToleranceAnnotation(tol)],
    )
    result = read_ap242_pmi(text)
    labels = {d["label"] for d in result["datums"] if d.get("label")}
    assert labels >= {"A", "B", "C"}

    dr_count = sum(1 for d in result["datums"] if d["kind"] == "datum_reference")
    assert dr_count == 3

    tol_entry = next(t for t in result["tolerances"] if t["kind"] == "POSITION_TOLERANCE")
    # refs merged across the complex instance's co-types:
    # GEOMETRIC_TOLERANCE's own refs = [measure, shape_aspect], plus
    # GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE's [dr_A, dr_B, dr_C].
    assert len(tol_entry["refs"]) == 5


def test_datum_auto_created_when_not_declared():
    """A tolerance can reference a datum label that was never passed via
    `datum_features` — the writer auto-creates a minimal DATUM_FEATURE/
    DATUM pair so the label still round-trips (documented convenience
    fallback, not silent data loss)."""
    tol = GeometricTolerance(
        feature_name="f", symbol=ToleranceSymbol.PERPENDICULARITY, tolerance_value=0.05,
        datum_ref=DatumReferenceFrame(primary="Z"),
    )
    text = write(tolerances=[ToleranceAnnotation(tol)])
    result = read_ap242_pmi(text)
    labels = {d["label"] for d in result["datums"] if d.get("label")}
    assert "Z" in labels


def test_datum_feature_and_datum_kinds_both_present():
    tol = GeometricTolerance(
        feature_name="f", symbol=ToleranceSymbol.SYMMETRY, tolerance_value=0.1,
        datum_ref=DatumReferenceFrame(primary="A"),
    )
    text = write(
        datum_features=[DatumFeatureAnnotation(Datum("A", DatumType.CENTRE_PLANE))],
        tolerances=[ToleranceAnnotation(tol)],
    )
    result = read_ap242_pmi(text)
    kinds = {d["kind"] for d in result["datums"]}
    assert "datum_feature" in kinds
    assert "datum" in kinds


# ---------------------------------------------------------------------------
# Dimensional sizes (plus/minus)
# ---------------------------------------------------------------------------

def test_dimensional_size_nominal_round_trips():
    text = write(dimensional_sizes=[DimensionalSize("shaft_dia", 12.5, 0.02, 0.02)])
    result = read_ap242_pmi(text)
    assert len(result["dimensional_sizes"]) == 1
    ds = result["dimensional_sizes"][0]
    assert ds["nominal"] == pytest.approx(12.5)
    assert ds["name"] == "shaft_dia"


def test_dimensional_size_upper_deviation_round_trips_as_plus_minus_tolerance():
    text = write(dimensional_sizes=[DimensionalSize("shaft_dia", 12.5, 0.03, 0.01)])
    result = read_ap242_pmi(text)
    pm = next(t for t in result["tolerances"] if t["kind"] == "PLUS_MINUS_TOLERANCE")
    assert pm["magnitude"] == pytest.approx(0.03)  # upper deviation, per divergence #5
    assert pm["name"] == "shaft_dia"


def test_dimensional_size_name_with_digits_does_not_corrupt_nominal():
    """Regression for divergence #3: a name containing a digit (e.g. an
    'H7'-style callout) must not be picked up by the reader's naive
    leftmost-number scan ahead of the real nominal value."""
    text = write(dimensional_sizes=[DimensionalSize("H7_bore_1", 12.5, 0.0, 0.0)])
    result = read_ap242_pmi(text)
    ds = result["dimensional_sizes"][0]
    assert ds["nominal"] == pytest.approx(12.5)


def test_multiple_dimensional_sizes():
    text = write(dimensional_sizes=[
        DimensionalSize("bore_a", 10.0, 0.02, 0.02),
        DimensionalSize("bore_b", 20.0, 0.05, 0.05),
    ])
    result = read_ap242_pmi(text)
    nominals = sorted(ds["nominal"] for ds in result["dimensional_sizes"])
    assert nominals == pytest.approx([10.0, 20.0])


# ---------------------------------------------------------------------------
# Body integration (PMI decorating a real B-rep)
# ---------------------------------------------------------------------------

def test_body_brep_entity_graph_present():
    body = make_box(size=(1.0, 1.0, 1.0))
    tol = GeometricTolerance(feature_name="top", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(body=body, tolerances=[ToleranceAnnotation(tol)])
    assert len(re.findall(r"=\s*ADVANCED_FACE\s*\(", text)) == 6
    assert len(re.findall(r"=\s*MANIFOLD_SOLID_BREP\s*\(", text)) == 1
    _assert_well_formed_part21(text)


def test_body_tolerance_binds_to_specific_face():
    body = make_box(size=(1.0, 1.0, 1.0))
    tol = GeometricTolerance(feature_name="top", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(body=body, tolerances=[ToleranceAnnotation(tol, face_index=0)])

    # The SHAPE_ASPECT for 'top' should reference an ADVANCED_FACE id, not
    # the whole-part placeholder.
    m = re.search(r"#(\d+)=SHAPE_ASPECT\('top',[^;]*#(\d+),\.T\.\);", text)
    assert m is not None
    sa_of_shape_id = int(m.group(2))
    of_shape_line = re.search(rf"#{sa_of_shape_id}=([A-Z_]+)\(", text)
    assert of_shape_line is not None
    assert of_shape_line.group(1) == "ADVANCED_FACE"


def test_body_tolerance_without_face_index_uses_whole_part():
    body = make_box(size=(1.0, 1.0, 1.0))
    tol = GeometricTolerance(feature_name="whole", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(body=body, tolerances=[ToleranceAnnotation(tol)])  # no face_index

    m = re.search(r"#(\d+)=SHAPE_ASPECT\('whole',[^;]*#(\d+),\.T\.\);", text)
    assert m is not None
    sa_of_shape_id = int(m.group(2))
    of_shape_line = re.search(rf"#{sa_of_shape_id}=([A-Z_]+)\(", text)
    assert of_shape_line is not None
    assert of_shape_line.group(1) == "MANIFOLD_SOLID_BREP"


def test_body_and_pmi_ids_never_collide():
    body = make_box(size=(1.0, 1.0, 1.0))
    tol = GeometricTolerance(feature_name="top", symbol=ToleranceSymbol.FLATNESS, tolerance_value=0.02)
    text = write(body=body, tolerances=[ToleranceAnnotation(tol, face_index=0)])
    _assert_well_formed_part21(text)
    ids = [int(m.group(1)) for m in _ENTITY_DEF_RE.finditer(text)]
    assert len(ids) == len(set(ids)), "duplicate entity ids in output"
    assert ids == sorted(ids), "entity ids should be monotonically increasing"


def test_ap242_round_trip_with_body_still_reads():
    body = make_box(size=(1.0, 1.0, 1.0))
    tol = GeometricTolerance(
        feature_name="top", symbol=ToleranceSymbol.POSITION, tolerance_value=0.1,
        datum_ref=DatumReferenceFrame(primary="A"),
    )
    text = write(
        body=body,
        datum_features=[DatumFeatureAnnotation(Datum("A", DatumType.PLANE), face_index=1)],
        tolerances=[ToleranceAnnotation(tol, face_index=0)],
    )
    result = read_ap242_pmi(text)
    assert result["ok"] is True
    assert any(t["kind"] == "POSITION_TOLERANCE" for t in result["tolerances"])
    assert any(d.get("label") == "A" for d in result["datums"])


# ---------------------------------------------------------------------------
# Modifiers / notes / diameter zone survive into the description text
# ---------------------------------------------------------------------------

def test_modifiers_and_note_appear_in_description():
    tol = GeometricTolerance(
        feature_name="bore1", symbol=ToleranceSymbol.POSITION, tolerance_value=0.1,
        diameter_zone=True, modifiers=[ToleranceModifier.MMC],
        datum_ref=DatumReferenceFrame(primary="A"),
        note="critical fit",
    )
    text = write(
        datum_features=[DatumFeatureAnnotation(Datum("A", DatumType.PLANE))],
        tolerances=[ToleranceAnnotation(tol)],
    )
    assert "MMC" in text
    assert "diameter_zone" in text
    assert "critical fit" in text


# ---------------------------------------------------------------------------
# AP214 writer non-regression
# ---------------------------------------------------------------------------

def test_ap214_writer_unaffected():
    """step_writer.write (AP214) must keep behaving exactly as before —
    this module must not have modified it."""
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_ap214(body)
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    assert m is not None
    assert "AUTOMOTIVE_DESIGN" in m.group(1)
    assert len(re.findall(r"=\s*ADVANCED_FACE\s*\(", text)) == 6


# ---------------------------------------------------------------------------
# Third-party ISO-10303-21 syntax validation
# ---------------------------------------------------------------------------
#
# This writer's own runtime code is pure Python / stdlib only (no new
# dependency for kerf_cad_core itself), and this environment has no full
# EXPRESS engine to check the output against the AP242 *schema* (see the
# module docstring's divergence list, point 7). What *is* checkable
# independently of Kerf's own code is whether the file is syntactically
# legal ISO-10303-21 Part 21 — i.e. would a real STEP toolkit's file-level
# parser (not just Kerf's own reader) accept the exchange structure,
# header, and entity-instance grammar, *including* the complex entity
# instance syntax this writer emits for tolerances?
# `steputils` (MIT, PyPI, https://pypi.org/project/steputils/ — a
# hand-written ISO-10303-21 lexer/parser, unrelated to Kerf) answers that
# question. It IS declared as a test-only dependency in this package's
# pyproject.toml (`[project.optional-dependencies] dev`, alongside pytest
# itself) and this test uses a hard `import`, not `importorskip` — it
# fails loudly rather than skipping silently if the dependency is ever
# missing from the test environment, so a green run is real evidence, not
# an absence of one.

def test_output_is_syntactically_valid_iso10303_21_per_third_party_parser():
    # Hard import, not importorskip: `steputils` is declared as a test
    # dependency in packages/kerf-cad-core/pyproject.toml precisely so this
    # check cannot silently skip in CI and read as a pass.
    import steputils.p21 as p21

    body = make_box(size=(1.0, 1.0, 1.0))
    tol = GeometricTolerance(
        feature_name="top", symbol=ToleranceSymbol.POSITION, tolerance_value=0.1,
        diameter_zone=True, datum_ref=DatumReferenceFrame(primary="A", secondary="B"),
    )
    text = write(
        body=body,
        datum_features=[
            DatumFeatureAnnotation(Datum("A", DatumType.PLANE), face_index=1),
            DatumFeatureAnnotation(Datum("B", DatumType.PLANE), face_index=2),
        ],
        tolerances=[ToleranceAnnotation(tol, face_index=0)],
        dimensional_sizes=[DimensionalSize("bore1", 25.0, 0.05, 0.05)],
        product_name="BracketA",
    )

    # p21.loads raises on any structural/grammar violation — a clean parse
    # is the pass condition (this is what "no ParseError" verifies). This
    # validates Part 21 *grammar* only (including the complex-entity-
    # instance syntax this writer now emits) — NOT AP242 EXPRESS-schema
    # conformance (attribute types/arity per entity). See the writer
    # module's docstring, divergence 7, for why no schema validator was
    # available in this environment.
    stepfile = p21.loads(text)

    assert stepfile.header.get("FILE_SCHEMA") is not None
    data_section = stepfile.data[0]
    assert len(data_section.instances) > 0

    names: set[str] = set()
    complex_instance_seen = False
    for inst in data_section.instances.values():
        if hasattr(inst, "entities"):  # ComplexEntityInstance
            complex_instance_seen = True
            names.update(e.name for e in inst.entities)
        else:  # SimpleEntityInstance
            names.add(inst.entity.name)

    assert complex_instance_seen, (
        "expected at least one real ISO 10303-21 complex entity instance "
        "(the tolerance encoding) — steputils.p21 distinguishes these from "
        "simple instances via a 'ComplexEntityInstance' with an `.entities` "
        "list rather than a single `.entity`"
    )
    assert "GEOMETRIC_TOLERANCE" in names
    assert "POSITION_TOLERANCE" in names
    assert "GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE" in names
    assert "MEASURE_WITH_UNIT" in names
    assert "DATUM_FEATURE" in names
    assert "ADVANCED_FACE" in names
    assert "MANIFOLD_SOLID_BREP" in names
