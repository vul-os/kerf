"""
Tests for kerf_cad_core.piping.multi_discipline_federation — AVEVA E3D parity Wave 12B.

Covers:
- Discipline enum
- DisciplineSubmodel and FederatedPlantModel construction
- cross_discipline_clashes(): HVAC duct overlapping structural beam → clash detected
- coordinate_system_consistency(): unit mismatch, datum mismatch flagged
- detect_stale_submodels(): SHA change detection

References: BS 1192-4:2014, USACE EM 1110-1-1000.
"""
from __future__ import annotations

import pytest

from kerf_cad_core.piping.multi_discipline_federation import (
    Discipline,
    DisciplineSubmodel,
    FederatedPlantModel,
    detect_stale_submodels,
    make_element,
    _bbox_intersection,
    _bbox_volume,
)


# ---------------------------------------------------------------------------
# Discipline enum
# ---------------------------------------------------------------------------

def test_discipline_values():
    assert Discipline.STRUCTURAL.value == "structural"
    assert Discipline.HVAC.value == "hvac"
    assert Discipline.PIPING_PROCESS.value == "piping_process"
    assert Discipline.CIVIL.value == "civil"


# ---------------------------------------------------------------------------
# AABB helpers
# ---------------------------------------------------------------------------

def test_bbox_intersection_overlapping():
    a = ((0.0, 0.0, 0.0), (2.0, 2.0, 2.0))
    b = ((1.0, 1.0, 1.0), (3.0, 3.0, 3.0))
    result = _bbox_intersection(a, b)
    assert result is not None
    assert result == ((1.0, 1.0, 1.0), (2.0, 2.0, 2.0))


def test_bbox_intersection_touching_edge():
    """Touching at a face (zero thickness) → no overlap volume."""
    a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    b = ((1.0, 0.0, 0.0), (2.0, 1.0, 1.0))
    result = _bbox_intersection(a, b)
    assert result is None


def test_bbox_intersection_disjoint():
    a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    b = ((2.0, 2.0, 2.0), (3.0, 3.0, 3.0))
    assert _bbox_intersection(a, b) is None


def test_bbox_volume():
    bbox = ((0.0, 0.0, 0.0), (2.0, 3.0, 4.0))
    assert abs(_bbox_volume(bbox) - 24.0) < 1e-9


# ---------------------------------------------------------------------------
# Cross-discipline clash detection
# ---------------------------------------------------------------------------

def _make_structural_submodel(elements: list[dict]) -> DisciplineSubmodel:
    return DisciplineSubmodel(
        discipline=Discipline.STRUCTURAL,
        file_path="structural.ifc",
        last_modified_iso="2024-01-01T00:00:00.000000Z",
        element_count=len(elements),
        bbox=((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
        sha256="abc123",
        elements=elements,
    )


def _make_hvac_submodel(elements: list[dict]) -> DisciplineSubmodel:
    return DisciplineSubmodel(
        discipline=Discipline.HVAC,
        file_path="hvac.ifc",
        last_modified_iso="2024-01-01T00:00:00.000000Z",
        element_count=len(elements),
        bbox=((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
        sha256="def456",
        elements=elements,
    )


def test_cross_discipline_clashes_overlapping_beam_duct():
    """HVAC duct overlapping structural beam → at least 1 clash."""
    # Structural beam: 5m long along X at Y=5, Z=3-3.5
    beam = make_element("beam-1", 0.0, 4.8, 3.0, 5.0, 5.2, 3.5)
    # HVAC duct: crosses at X=2-3, Y=4-6, Z=3.1-3.4 (overlaps beam)
    duct = make_element("duct-1", 2.0, 4.0, 3.1, 3.0, 6.0, 3.4)

    sm_struct = _make_structural_submodel([beam])
    sm_hvac = _make_hvac_submodel([duct])

    model = FederatedPlantModel(
        project_id="test-plant",
        submodels=[sm_struct, sm_hvac],
    )

    clashes = model.cross_discipline_clashes()
    assert len(clashes) >= 1, f"Expected ≥1 clash, got {clashes}"
    c = clashes[0]
    assert {c["discipline_a"], c["discipline_b"]} == {"structural", "hvac"}
    assert c["clash_volume_m3"] > 0.0


def test_cross_discipline_no_clash_when_clear():
    """Non-overlapping elements → no clashes."""
    beam = make_element("beam-1", 0.0, 0.0, 0.0, 5.0, 0.5, 0.5)
    duct = make_element("duct-1", 10.0, 10.0, 5.0, 15.0, 10.5, 5.5)

    model = FederatedPlantModel(
        project_id="test-plant",
        submodels=[_make_structural_submodel([beam]), _make_hvac_submodel([duct])],
    )
    assert model.cross_discipline_clashes() == []


def test_cross_discipline_clash_volume_correct():
    """Verify clash volume calculation."""
    # Two 1m³ cubes with 0.5m³ overlap
    elem_a = make_element("A", 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    elem_b = make_element("B", 0.5, 0.0, 0.0, 1.5, 1.0, 1.0)

    sm_a = _make_structural_submodel([elem_a])
    sm_b = _make_hvac_submodel([elem_b])
    model = FederatedPlantModel(project_id="test", submodels=[sm_a, sm_b])

    clashes = model.cross_discipline_clashes()
    assert len(clashes) == 1
    assert abs(clashes[0]["clash_volume_m3"] - 0.5) < 1e-6


def test_cross_discipline_multiple_clashes():
    """Multiple overlapping elements → multiple clashes."""
    beams = [
        make_element("beam-1", 0.0, 0.0, 0.0, 2.0, 0.3, 0.3),
        make_element("beam-2", 5.0, 0.0, 0.0, 7.0, 0.3, 0.3),
    ]
    ducts = [
        make_element("duct-1", 0.5, -0.1, 0.0, 1.5, 0.2, 0.2),  # overlaps beam-1
        make_element("duct-2", 5.5, -0.1, 0.0, 6.5, 0.2, 0.2),  # overlaps beam-2
    ]
    sm_s = _make_structural_submodel(beams)
    sm_h = _make_hvac_submodel(ducts)
    model = FederatedPlantModel(project_id="test", submodels=[sm_s, sm_h])
    clashes = model.cross_discipline_clashes()
    assert len(clashes) >= 2


# ---------------------------------------------------------------------------
# Coordinate system consistency
# ---------------------------------------------------------------------------

def test_coordinate_consistency_all_same():
    """Identical coordinate systems → no warnings."""
    submodels = [
        DisciplineSubmodel(
            discipline=Discipline.STRUCTURAL,
            file_path="", last_modified_iso="", element_count=0,
            bbox=((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            sha256="a",
            coordinate_system="metric-SI", datum_elevation=0.0, grid_ref="LOCAL",
        ),
        DisciplineSubmodel(
            discipline=Discipline.HVAC,
            file_path="", last_modified_iso="", element_count=0,
            bbox=((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            sha256="b",
            coordinate_system="metric-SI", datum_elevation=0.0, grid_ref="LOCAL",
        ),
    ]
    model = FederatedPlantModel(project_id="p1", submodels=submodels)
    warnings = model.coordinate_system_consistency()
    assert warnings == [], f"Expected no warnings, got: {warnings}"


def test_coordinate_consistency_unit_mismatch():
    """Mixed metric + imperial unit systems → warning flagged."""
    submodels = [
        DisciplineSubmodel(
            discipline=Discipline.STRUCTURAL,
            file_path="", last_modified_iso="", element_count=0,
            bbox=((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            sha256="a", coordinate_system="metric-SI", datum_elevation=0.0,
        ),
        DisciplineSubmodel(
            discipline=Discipline.CIVIL,
            file_path="", last_modified_iso="", element_count=0,
            bbox=((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            sha256="b", coordinate_system="imperial-ft", datum_elevation=0.0,
        ),
    ]
    model = FederatedPlantModel(project_id="p1", submodels=submodels)
    warnings = model.coordinate_system_consistency()
    assert len(warnings) >= 1
    assert any("mismatch" in w.lower() or "coordinate" in w.lower() for w in warnings)


def test_coordinate_consistency_datum_mismatch():
    """Different datum elevations → inconsistency warning."""
    submodels = [
        DisciplineSubmodel(
            discipline=Discipline.STRUCTURAL,
            file_path="", last_modified_iso="", element_count=0,
            bbox=((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            sha256="a", coordinate_system="metric-SI", datum_elevation=0.0,
        ),
        DisciplineSubmodel(
            discipline=Discipline.PIPING_PROCESS,
            file_path="", last_modified_iso="", element_count=0,
            bbox=((0.0, 0.0, 5.0), (20.0, 20.0, 15.0)),
            sha256="b", coordinate_system="metric-SI", datum_elevation=5.0,
        ),
    ]
    model = FederatedPlantModel(project_id="p1", submodels=submodels)
    warnings = model.coordinate_system_consistency()
    assert len(warnings) >= 1
    assert any("datum" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# detect_stale_submodels
# ---------------------------------------------------------------------------

def _make_submodel(disc: Discipline, sha: str) -> DisciplineSubmodel:
    return DisciplineSubmodel(
        discipline=disc,
        file_path="", last_modified_iso="", element_count=0,
        bbox=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        sha256=sha,
    )


def test_detect_stale_none_changed():
    model = FederatedPlantModel(project_id="p", submodels=[
        _make_submodel(Discipline.STRUCTURAL, "sha-struct"),
        _make_submodel(Discipline.HVAC, "sha-hvac"),
    ])
    sha_now = {"structural": "sha-struct", "hvac": "sha-hvac"}
    stale = detect_stale_submodels(model, sha_now)
    assert stale == []


def test_detect_stale_one_changed():
    """Changed structural SHA → structural flagged as stale."""
    model = FederatedPlantModel(project_id="p", submodels=[
        _make_submodel(Discipline.STRUCTURAL, "sha-struct-old"),
        _make_submodel(Discipline.HVAC, "sha-hvac"),
    ])
    sha_now = {"structural": "sha-struct-NEW", "hvac": "sha-hvac"}
    stale = detect_stale_submodels(model, sha_now)
    assert Discipline.STRUCTURAL in stale
    assert Discipline.HVAC not in stale


def test_detect_stale_all_changed():
    model = FederatedPlantModel(project_id="p", submodels=[
        _make_submodel(Discipline.STRUCTURAL, "old1"),
        _make_submodel(Discipline.HVAC, "old2"),
        _make_submodel(Discipline.CIVIL, "old3"),
    ])
    sha_now = {"structural": "new1", "hvac": "new2", "civil": "new3"}
    stale = detect_stale_submodels(model, sha_now)
    assert len(stale) == 3


def test_detect_stale_missing_discipline_skipped():
    """Discipline not in sha_now dict → not included in stale list."""
    model = FederatedPlantModel(project_id="p", submodels=[
        _make_submodel(Discipline.STRUCTURAL, "sha1"),
        _make_submodel(Discipline.HVAC, "sha2"),
    ])
    # Only provide HVAC SHA
    sha_now = {"hvac": "sha2-changed"}
    stale = detect_stale_submodels(model, sha_now)
    assert Discipline.STRUCTURAL not in stale
    assert Discipline.HVAC in stale
