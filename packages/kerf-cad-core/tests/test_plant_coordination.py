"""
Tests for kerf_cad_core.piping.plant_coordination — AVEVA E3D parity.

Coverage:
  - PlantModel construction from multiple disciplines
  - Hard clash: pipe routed through a structural beam is detected
  - Clearance violation: elements within minimum clearance but not overlapping
  - No false positive when elements are well separated
  - BOM aggregation per discipline (element count, weight totals)
  - CoordinationReport groups clashes by discipline pair
  - Zone assignment: elements placed in the correct spatial zone
  - Clearance rules: discipline-pair minimum clearances
  - make_plant_element factory: invalid discipline raises ValueError

References
----------
BS 1192-4:2014 — COBie federated model exchange.
USACE EM 1110-1-1000 §5.3 — spatial coordination checking.
ASME B31.3-2022 §321 — piping clearance requirements.
"""
from __future__ import annotations

import pytest

from kerf_cad_core.piping.plant_coordination import (
    PlantDiscipline,
    PlantModel,
    PlantElement,
    CoordinationReport,
    make_plant_element,
    get_clearance_m,
    _bbox_gap,
    _bbox_overlap_volume,
    _bbox_clearance_violation_depth,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pipe(eid, x0, y0, z0, x1, y1, z1, **kw) -> PlantElement:
    return make_plant_element(eid, "piping", x0, y0, z0, x1, y1, z1, **kw)


def _beam(eid, x0, y0, z0, x1, y1, z1, **kw) -> PlantElement:
    return make_plant_element(eid, "structural", x0, y0, z0, x1, y1, z1, **kw)


def _duct(eid, x0, y0, z0, x1, y1, z1, **kw) -> PlantElement:
    return make_plant_element(eid, "hvac", x0, y0, z0, x1, y1, z1, **kw)


def _civil(eid, x0, y0, z0, x1, y1, z1, **kw) -> PlantElement:
    return make_plant_element(eid, "civil", x0, y0, z0, x1, y1, z1, **kw)


def _equip(eid, x0, y0, z0, x1, y1, z1, **kw) -> PlantElement:
    return make_plant_element(eid, "equipment", x0, y0, z0, x1, y1, z1, **kw)


# ---------------------------------------------------------------------------
# Geometry utilities
# ---------------------------------------------------------------------------

class TestBboxGeom:

    def test_bbox_gap_overlapping_is_negative(self):
        """Overlapping boxes → negative gap (penetration depth)."""
        a = ((0.0, 0.0, 0.0), (2.0, 2.0, 2.0))
        b = ((1.0, 1.0, 1.0), (3.0, 3.0, 3.0))
        gap = _bbox_gap(a, b)
        assert gap < 0.0

    def test_bbox_gap_separated_is_positive(self):
        """Separated boxes → positive gap (distance)."""
        a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        b = ((2.0, 0.0, 0.0), (3.0, 1.0, 1.0))
        gap = _bbox_gap(a, b)
        assert abs(gap - 1.0) < 1e-9

    def test_bbox_overlap_volume(self):
        """Overlapping boxes: volume of intersection = 0.5 m³."""
        a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        b = ((0.5, 0.0, 0.0), (1.5, 1.0, 1.0))
        vol = _bbox_overlap_volume(a, b)
        assert abs(vol - 0.5) < 1e-9

    def test_bbox_no_overlap_volume_zero(self):
        """Disjoint boxes: overlap volume = 0."""
        a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        b = ((2.0, 0.0, 0.0), (3.0, 1.0, 1.0))
        assert _bbox_overlap_volume(a, b) == 0.0

    def test_bbox_clearance_violation_overlapping(self):
        """Overlapping boxes: clearance violation depth > required clearance."""
        a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        b = ((0.5, 0.0, 0.0), (1.5, 1.0, 1.0))
        depth = _bbox_clearance_violation_depth(a, b, required_clearance=0.025)
        assert depth > 0.025   # required + penetration

    def test_bbox_clearance_satisfied(self):
        """Well-separated boxes: clearance depth is negative (satisfied)."""
        a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        b = ((2.0, 0.0, 0.0), (3.0, 1.0, 1.0))
        depth = _bbox_clearance_violation_depth(a, b, required_clearance=0.025)
        assert depth < 0.0   # gap (1.0) >> required_clearance (0.025)


# ---------------------------------------------------------------------------
# Clearance rules
# ---------------------------------------------------------------------------

class TestClearanceRules:

    def test_pipe_structure_clearance(self):
        """ASME B31.3 §321 — pipe-to-structure: 25 mm minimum."""
        c = get_clearance_m("piping", "structural")
        assert abs(c - 0.025) < 1e-9

    def test_duct_pipe_clearance(self):
        """SMACNA §5.4 — duct-to-pipe: 50 mm minimum."""
        c = get_clearance_m("hvac", "piping")
        assert abs(c - 0.050) < 1e-9

    def test_symmetric_clearance(self):
        """Clearance is symmetric: (a,b) == (b,a)."""
        assert get_clearance_m("structural", "piping") == get_clearance_m("piping", "structural")
        assert get_clearance_m("hvac", "structural") == get_clearance_m("structural", "hvac")

    def test_electrical_piping_clearance(self):
        """IEC 61439-3 — electrical-to-pipe: 150 mm minimum."""
        c = get_clearance_m("electrical", "piping")
        assert abs(c - 0.150) < 1e-9


# ---------------------------------------------------------------------------
# Hard clash: pipe through structural beam
# ---------------------------------------------------------------------------

class TestHardClash:

    def test_pipe_through_beam_flagged(self):
        """
        A pipe routed through a structural beam is a hard clash (AABB overlap).

        Geometry: steel beam along X from (0,4.9,3.0) to (6,5.1,3.3).
                  pipe segment along Y from (2,4.0,3.1) to (2,6.0,3.2) — passes through beam.
        """
        model = PlantModel(project_id="test-pipe-beam")
        beam = _beam("BEAM-01", 0.0, 4.9, 3.0, 6.0, 5.1, 3.3,
                     label="W200x46 beam", material="ASTM A992")
        pipe = _pipe("PIPE-01", 1.8, 4.0, 3.1, 2.2, 6.0, 3.2,
                     label="DN150 CS steam pipe", material="ASTM A106 Gr.B")
        model.add_element(beam)
        model.add_element(pipe)

        clashes = model.run_coordination_check()
        hard = [c for c in clashes if c.clash_type == "hard"]
        assert len(hard) >= 1, f"Expected hard clash; got: {clashes}"

        c = hard[0]
        assert {c.discipline_a, c.discipline_b} == {"structural", "piping"}
        assert {c.element_a, c.element_b} == {"BEAM-01", "PIPE-01"}
        assert c.overlap_volume_m3 > 0.0
        assert c.severity == "critical"

    def test_hard_clash_overlap_volume_correct(self):
        """Verify that clash overlap volume is computed correctly."""
        model = PlantModel(project_id="test-vol")
        # Two cubes: A = [0,1]³, B = [0.5,1.5]³ → overlap = [0.5,1]³ = 0.125 m³
        model.add_element(_beam("B1", 0.0, 0.0, 0.0, 1.0, 1.0, 1.0))
        model.add_element(_pipe("P1", 0.5, 0.0, 0.0, 1.5, 1.0, 1.0))
        clashes = model.run_coordination_check(check_hard_clashes=True)
        hard = [c for c in clashes if c.clash_type == "hard"]
        assert len(hard) == 1
        assert abs(hard[0].overlap_volume_m3 - 0.5) < 1e-6

    def test_duct_through_pipe_hard_clash(self):
        """HVAC duct overlapping pipe run → hard clash detected."""
        model = PlantModel(project_id="test-duct-pipe")
        duct = _duct("DUCT-01", 0.0, 0.0, 0.0, 5.0, 0.6, 0.6,
                     label="600×500 rect duct")
        pipe = _pipe("PIPE-01", 1.5, -0.1, 0.1, 1.7, 0.7, 0.5,
                     label="DN200 cooling water")
        model.add_element(duct)
        model.add_element(pipe)

        clashes = model.run_coordination_check()
        hard = [c for c in clashes if c.clash_type == "hard"]
        assert len(hard) >= 1
        assert {hard[0].discipline_a, hard[0].discipline_b} == {"hvac", "piping"}

    def test_equipment_structure_hard_clash(self):
        """Equipment AABB overlapping a structural column → critical clash."""
        model = PlantModel(project_id="test-equip")
        col = _beam("COL-01", 4.9, 4.9, 0.0, 5.1, 5.1, 10.0,
                    label="HSS 200×200 column")
        pump = _equip("PUMP-01", 4.0, 4.0, 0.0, 5.5, 6.0, 2.0,
                      label="centrifugal pump P-101")
        model.add_element(col)
        model.add_element(pump)

        clashes = model.run_coordination_check()
        hard = [c for c in clashes if c.clash_type == "hard"]
        assert len(hard) >= 1


# ---------------------------------------------------------------------------
# Clearance violation (soft clash)
# ---------------------------------------------------------------------------

class TestSoftClash:

    def test_clearance_violation_pipe_near_beam(self):
        """
        Pipe and structural beam are separated but by less than the 25 mm minimum.

        Geometry: beam end-face at x=5.0; pipe face at x=5.010 → gap 10 mm < 25 mm.
        """
        model = PlantModel(project_id="test-clearance")
        beam = _beam("BEAM-02", 0.0, 0.0, 0.0, 5.000, 0.3, 0.3)
        pipe = _pipe("PIPE-02", 5.010, 0.0, 0.0, 8.000, 0.15, 0.15)
        model.add_element(beam)
        model.add_element(pipe)

        clashes = model.run_coordination_check(
            check_hard_clashes=True,
            check_soft_clashes=True,
        )
        soft = [c for c in clashes if c.clash_type == "soft"]
        assert len(soft) >= 1, f"Expected soft clearance clash; got: {clashes}"

        c = soft[0]
        assert {c.discipline_a, c.discipline_b} == {"structural", "piping"}
        assert c.gap_m < 0.025   # actual gap < required 25 mm
        assert c.shortfall_m > 0.0
        assert c.severity in ("minor", "major")

    def test_clearance_violation_duct_near_pipe(self):
        """HVAC duct within 50 mm of pipe → soft clash (SMACNA §5.4)."""
        model = PlantModel(project_id="test-duct-clearance")
        duct = _duct("DUCT-02", 0.0, 0.0, 2.5, 4.0, 0.5, 3.0)
        # pipe 30 mm away from duct face (< 50 mm required)
        pipe = _pipe("PIPE-03", 4.030, 0.0, 2.5, 8.0, 0.2, 2.8)
        model.add_element(duct)
        model.add_element(pipe)

        clashes = model.run_coordination_check(check_soft_clashes=True)
        soft = [c for c in clashes if c.clash_type == "soft"]
        assert len(soft) >= 1
        # The required clearance for duct-pipe is 50 mm; gap is 30 mm
        c = soft[0]
        assert c.required_clearance_m == 0.050
        assert c.shortfall_m > 0.0


# ---------------------------------------------------------------------------
# No false clash when separated
# ---------------------------------------------------------------------------

class TestNoFalseClash:

    def test_no_clash_well_separated(self):
        """Well-separated elements from different disciplines → no clashes at all."""
        model = PlantModel(project_id="test-no-clash")
        model.add_element(_beam("BEAM-SEP", 0.0, 0.0, 0.0, 5.0, 0.3, 0.3))
        model.add_element(_pipe("PIPE-SEP", 0.0, 5.0, 0.0, 5.0, 5.3, 0.3))
        # 4.7 m separation (>>25 mm required)
        clashes = model.run_coordination_check()
        assert clashes == [], f"Unexpected clashes: {clashes}"

    def test_no_clash_same_discipline(self):
        """Two structural elements overlapping each other → NOT a clash (same disc)."""
        model = PlantModel(project_id="test-same-disc")
        model.add_element(_beam("BEAM-A", 0.0, 0.0, 0.0, 2.0, 0.2, 0.2))
        model.add_element(_beam("BEAM-B", 1.0, 0.0, 0.0, 3.0, 0.2, 0.2))
        clashes = model.run_coordination_check()
        assert clashes == []

    def test_no_false_clash_after_rerouting(self):
        """
        Pipe rerouted to clear the beam by >25 mm → hard clash gone, no soft either.
        Gap = 0.10 m >> 0.025 m required clearance → no clash.
        """
        model = PlantModel(project_id="test-rerouted")
        beam = _beam("BEAM-03", 0.0, 0.0, 0.0, 5.0, 0.3, 0.3)
        # Pipe z-range starts at 0.40 (gap = 0.40 - 0.30 = 0.10 m > 0.025)
        pipe = _pipe("PIPE-04", 0.0, 0.0, 0.40, 5.0, 0.15, 0.50)
        model.add_element(beam)
        model.add_element(pipe)
        clashes = model.run_coordination_check()
        assert clashes == [], f"Unexpected: {clashes}"


# ---------------------------------------------------------------------------
# BOM aggregation per discipline
# ---------------------------------------------------------------------------

class TestBomAggregation:

    def _build_model(self) -> PlantModel:
        model = PlantModel(project_id="test-bom")
        model.add_element(_beam("B1", 0, 0, 0, 5, 0.3, 0.3,
                                material="ASTM A992", quantity=1.0, weight_kg=230.0, unit_cost=450.0))
        model.add_element(_beam("B2", 5, 0, 0, 10, 0.3, 0.3,
                                material="ASTM A992", quantity=1.0, weight_kg=200.0, unit_cost=390.0))
        model.add_element(_pipe("P1", 0, 3, 0, 5, 3.15, 0.15,
                                material="A106 Gr.B", quantity=1.0, weight_kg=62.5, unit_cost=180.0))
        model.add_element(_duct("D1", 0, 0, 3, 5, 0.6, 3.5,
                                material="galv steel", quantity=1.0, weight_kg=80.0, unit_cost=220.0))
        model.add_element(_civil("FND1", -1, -1, -2, 6, 1, 0,
                                 material="concrete C30", quantity=1.0, weight_kg=5000.0, unit_cost=1200.0))
        return model

    def test_bom_disciplines_present(self):
        """BOM dict contains all disciplines used in the model."""
        model = self._build_model()
        bom = model.bom_by_discipline()
        assert "structural" in bom
        assert "piping" in bom
        assert "hvac" in bom
        assert "civil" in bom

    def test_bom_structural_count(self):
        """BOM structural: 2 beams."""
        model = self._build_model()
        bom = model.bom_by_discipline()
        assert len(bom["structural"]) == 2

    def test_bom_piping_count(self):
        """BOM piping: 1 pipe element."""
        model = self._build_model()
        bom = model.bom_by_discipline()
        assert len(bom["piping"]) == 1

    def test_bom_summary_totals(self):
        """Combined BOM summary totals add up correctly."""
        model = self._build_model()
        summary = model.combined_bom_summary()
        assert "_total" in summary
        total = summary["_total"]
        assert total["element_count"] == 5
        # structural: 230+200=430 kg, piping: 62.5, hvac: 80, civil: 5000
        expected_weight = 430.0 + 62.5 + 80.0 + 5000.0
        assert abs(total["total_weight_kg"] - expected_weight) < 0.01

    def test_bom_per_discipline_cost(self):
        """Per-discipline cost is correctly summed."""
        model = self._build_model()
        summary = model.combined_bom_summary()
        # structural: 450+390=840
        assert abs(summary["structural"]["total_cost_usd"] - 840.0) < 0.01
        # piping: 180
        assert abs(summary["piping"]["total_cost_usd"] - 180.0) < 0.01


# ---------------------------------------------------------------------------
# Coordination report: clashes grouped by discipline pair
# ---------------------------------------------------------------------------

class TestCoordinationReport:

    def test_report_groups_clashes_by_pair(self):
        """CoordinationReport.clashes_by_pair uses canonical 'a--b' key."""
        model = PlantModel(project_id="test-report")
        # Pipe overlaps structural beam → hard clash
        model.add_element(_beam("BEAM-R", 0.0, 0.0, 0.0, 5.0, 0.3, 0.3))
        model.add_element(_pipe("PIPE-R", 1.5, -0.1, 0.0, 1.7, 0.4, 0.3))
        # HVAC duct overlaps pipe → another hard clash
        model.add_element(_duct("DUCT-R", 0.0, -0.1, 0.0, 5.0, 0.4, 0.4))

        report = model.coordination_report()

        # Should have clashes
        assert report.hard_clash_count >= 1 or report.soft_clash_count >= 1
        total_in_pairs = sum(len(v) for v in report.clashes_by_pair.values())
        total_clashes = report.hard_clash_count + report.soft_clash_count
        assert total_in_pairs == total_clashes

        # All pair keys should be sorted alphabetically (canonical)
        for key in report.clashes_by_pair:
            parts = key.split("--")
            assert len(parts) == 2
            assert parts[0] <= parts[1], f"Pair key not canonical: {key}"

    def test_report_clash_severity_present(self):
        """Each clash record in the report has a severity field."""
        model = PlantModel(project_id="test-sev")
        model.add_element(_beam("BEAM-S", 0.0, 0.0, 0.0, 5.0, 0.3, 0.3))
        model.add_element(_pipe("PIPE-S", 1.5, -0.1, 0.0, 1.7, 0.4, 0.3))
        report = model.coordination_report()
        for pair_clashes in report.clashes_by_pair.values():
            for c in pair_clashes:
                assert "severity" in c
                assert c["severity"] in ("critical", "major", "minor")

    def test_report_warnings_when_empty(self):
        """Empty model produces a warning."""
        model = PlantModel(project_id="empty")
        report = model.coordination_report()
        assert any("empty" in w.lower() for w in report.warnings)

    def test_report_single_discipline_warns(self):
        """Single-discipline model: warning that coordination cannot be performed."""
        model = PlantModel(project_id="single-disc")
        model.add_element(_beam("B1", 0, 0, 0, 5, 0.3, 0.3))
        report = model.coordination_report()
        assert any("one discipline" in w.lower() for w in report.warnings)

    def test_report_hard_clash_warning(self):
        """Hard clashes produce a warning in the report."""
        model = PlantModel(project_id="clash-warn")
        model.add_element(_beam("B1", 0, 0, 0, 2, 0.3, 0.3))
        model.add_element(_pipe("P1", 0.5, -0.1, 0.0, 0.7, 0.4, 0.3))
        report = model.coordination_report()
        if report.hard_clash_count > 0:
            assert any("hard clash" in w.lower() for w in report.warnings)

    def test_multi_discipline_bom_present(self):
        """Report includes BOM for each discipline."""
        model = PlantModel(project_id="multi-bom")
        model.add_element(_beam("B1", 0, 10, 0, 5, 10.3, 0.3))
        model.add_element(_pipe("P1", 0, 0, 5, 5, 0.15, 5.15))
        model.add_element(_duct("D1", 0, -5, 2, 5, -4.5, 2.5))
        model.add_element(_civil("C1", -1, -1, -1, 6, 12, 0))
        report = model.coordination_report()
        assert "structural" in report.bom_by_discipline
        assert "piping" in report.bom_by_discipline
        assert "hvac" in report.bom_by_discipline
        assert "civil" in report.bom_by_discipline


# ---------------------------------------------------------------------------
# Spatial zones
# ---------------------------------------------------------------------------

class TestZones:

    def test_zone_assignment_correct(self):
        """Element centroid inside zone bbox → assigned to that zone."""
        model = PlantModel(project_id="test-zones")
        model.add_zone("PUMP-BAY", ((0.0, 0.0, 0.0), (10.0, 10.0, 5.0)))
        model.add_zone("PIPE-RACK", ((10.0, 0.0, 3.0), (20.0, 10.0, 10.0)))

        # Pump bay elements
        model.add_element(_equip("PUMP-101", 1.0, 1.0, 0.0, 3.0, 3.0, 2.0))
        model.add_element(_pipe("PIPE-IN", 3.0, 5.0, 0.5, 7.0, 5.15, 0.65))

        # Pipe rack element (centroid at x=14.5, y=5, z=6.5)
        model.add_element(_pipe("PIPE-RACK-01", 10.0, 0.0, 3.0, 19.0, 0.15, 10.0))

        assignment = model.assign_zones()
        assert "PUMP-101" in assignment.get("PUMP-BAY", [])
        assert "PIPE-IN" in assignment.get("PUMP-BAY", [])

    def test_unzoned_elements(self):
        """Elements outside all zone bboxes land in _unzoned bucket."""
        model = PlantModel(project_id="test-unzoned")
        model.add_zone("ZONE-A", ((0.0, 0.0, 0.0), (5.0, 5.0, 5.0)))
        model.add_element(_beam("B-FAR", 100.0, 100.0, 0.0, 105.0, 100.3, 0.3))
        assignment = model.assign_zones()
        assert "B-FAR" in assignment["_unzoned"]


# ---------------------------------------------------------------------------
# make_plant_element factory
# ---------------------------------------------------------------------------

class TestFactory:

    def test_invalid_discipline_raises(self):
        """Unknown discipline string → ValueError."""
        with pytest.raises(ValueError, match="Unknown discipline"):
            make_plant_element("X", "robotics", 0, 0, 0, 1, 1, 1)

    def test_all_disciplines_valid(self):
        """All PlantDiscipline values can be constructed."""
        for d in PlantDiscipline:
            elem = make_plant_element(f"E-{d.value}", d.value, 0, 0, 0, 1, 1, 1)
            assert elem.discipline == d

    def test_bbox_normalized(self):
        """AABB is normalized (min < max) even if input order is swapped."""
        elem = make_plant_element("X", "piping", 5, 5, 5, 0, 0, 0)
        lo, hi = elem.bbox
        assert all(lo[i] <= hi[i] for i in range(3))


# ---------------------------------------------------------------------------
# Full multi-discipline plant: combined scenario
# ---------------------------------------------------------------------------

class TestMultiDisciplinePlant:
    """Full plant scenario: structural + HVAC + piping + civil + equipment."""

    def _build_plant(self) -> PlantModel:
        model = PlantModel(project_id="PLANT-TEST-001")
        model.add_zone("PUMP-BAY", ((0.0, 0.0, 0.0), (12.0, 12.0, 6.0)))
        model.add_zone("PIPE-RACK", ((12.0, 0.0, 3.0), (30.0, 6.0, 10.0)))

        # ── Structural: columns + beams
        # Column at x=5.9–6.1, y=5.9–6.1, z=0–10
        model.add_element(_beam("COL-01", 5.9, 5.9, 0.0, 6.1, 6.1, 10.0,
                                label="HEA200 column", material="S275"))
        # Horizontal beam at z=3.0–3.3, crosses pump bay
        model.add_element(_beam("BEAM-01", 0.0, 5.9, 3.0, 12.0, 6.1, 3.3,
                                label="IPE330 beam", material="S275"))

        # ── HVAC: main supply duct along X at y=0–0.6, z=4.0–4.6
        model.add_element(_duct("DUCT-MAIN", 0.0, 0.0, 4.0, 20.0, 0.6, 4.6,
                                label="600×600 supply air duct", material="galv steel"))

        # ── Piping: steam header along X at y=5.95–6.05, z=3.1–3.2
        # This pipe passes THROUGH beam BEAM-01 → HARD CLASH
        model.add_element(_pipe("STEAM-HEADER", 0.0, 5.95, 3.1, 12.0, 6.05, 3.2,
                                label="DN150 CS steam header",
                                material="ASTM A106 Gr.B"))
        # Cooling water pipe well clear of structure at z=2.0
        model.add_element(_pipe("CW-SUPPLY", 0.0, 3.0, 2.0, 10.0, 3.15, 2.15,
                                label="DN200 CS cooling water",
                                material="ASTM A106 Gr.B"))

        # ── Civil: foundation pad
        model.add_element(_civil("FND-01", -1.0, -1.0, -1.5, 13.0, 13.0, 0.0,
                                 label="reinforced concrete slab",
                                 material="C30/37"))

        # ── Equipment: centrifugal pump (clear of structure)
        model.add_element(_equip("PUMP-101", 2.0, 2.0, 0.0, 4.0, 4.0, 1.5,
                                 label="centrifugal pump P-101"))
        return model

    def test_steam_pipe_through_beam_detected(self):
        """Steam header through beam → hard clash detected."""
        model = self._build_plant()
        clashes = model.run_coordination_check()
        hard = [c for c in clashes if c.clash_type == "hard"]
        pair_ids = [
            frozenset([c.element_a, c.element_b]) for c in hard
        ]
        assert frozenset(["STEAM-HEADER", "BEAM-01"]) in pair_ids, (
            f"Expected STEAM-HEADER vs BEAM-01 clash; got: {hard}"
        )

    def test_cooling_pipe_no_clash(self):
        """Cooling water pipe (z=2.0) clears beam (z=3.0–3.3) → no clash."""
        model = self._build_plant()
        clashes = model.run_coordination_check()
        cw_clashes = [
            c for c in clashes
            if c.element_a == "CW-SUPPLY" or c.element_b == "CW-SUPPLY"
        ]
        hard_cw = [c for c in cw_clashes if c.clash_type == "hard"]
        assert hard_cw == [], f"Unexpected hard clash for CW-SUPPLY: {hard_cw}"

    def test_report_groups_by_discipline_pair(self):
        """Report's clashes_by_pair contains 'piping--structural' key."""
        model = self._build_plant()
        report = model.coordination_report()
        # There should be a clash in the structural-piping pair
        assert "piping--structural" in report.clashes_by_pair, (
            f"Expected 'piping--structural' in pairs; got: {list(report.clashes_by_pair.keys())}"
        )

    def test_bom_all_four_disciplines(self):
        """BOM includes all four disciplines: structural, hvac, piping, civil."""
        model = self._build_plant()
        report = model.coordination_report()
        for disc in ["structural", "hvac", "piping", "civil"]:
            assert disc in report.bom_by_discipline, (
                f"Missing discipline '{disc}' in BOM"
            )

    def test_total_element_count(self):
        """Report total_elements matches elements added."""
        model = self._build_plant()
        report = model.coordination_report()
        assert report.total_elements == len(model.elements)
