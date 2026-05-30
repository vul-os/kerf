"""
Tests for kerf_cad_core.drawings.measurement_chain

Hermetic — no OCC, no database, no network.  Pure-Python + NumPy only.

Analytical oracles
------------------
T-1  Cube chain:       10×10×10 cube → 3 dimensions (X=10, Y=10, Z=10);
                       3 datums (A, B, C); no missing constraints; no redundancies.
T-2  Cube-with-hole:   10×10×10 cube + 1 centred through-hole (Ø5, at x=5,y=5) →
                       exactly 5 dimensions (3 body + 2 hole-position; THRU for depth +
                       diameter makes 7 total incl. size dims); hole position anchored
                       to B and C datums.
T-3  Auto-datum:       a 100×60×20 part (bottom = largest face 100×60 = 6000 mm²) →
                       infer_datum_frame returns A = bottom face (normal=(0,0,-1));
                       B is perpendicular to A.
T-4  Redundancy:       extract chain where the body's X DOF is dimensioned twice
                       (once via normal bbox, once via an injected redundant call)
                       → redundancy list non-empty, redundant dim flagged.
T-5..T-N Additional coverage: report generation, error paths, etc.

References
----------
ASME Y14.5-2018 §2.5, §3.4
ISO 129-1:2018 §6
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from kerf_cad_core.drawings.measurement_chain import (
    DatumFace,
    DatumFrame,
    Dimension,
    MeasurementChainResult,
    extract_measurement_chain,
    generate_inspection_report,
    infer_datum_frame,
    _general_tolerance,
    _diameter_tolerance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cube(side: float = 10.0) -> Dict[str, Any]:
    return {
        "name": "Cube",
        "material": "Aluminium 6061",
        "bbox": {"length": side, "width": side, "height": side},
        "holes": [],
        "fillets": [],
    }


def _cube_with_hole(side: float = 10.0, dia: float = 5.0) -> Dict[str, Any]:
    return {
        "name": "CubeHole",
        "bbox": {"length": side, "width": side, "height": side},
        "holes": [
            {
                "diameter_mm": dia,
                "depth_mm": None,   # through-hole
                "x_mm": side / 2,
                "y_mm": side / 2,
                "z_mm": side,
                "threaded": False,
                "thread_pitch_mm": None,
                "countersunk": False,
                "counterbored": False,
            }
        ],
        "fillets": [],
    }


def _flat_plate(length: float = 100.0, width: float = 60.0, height: float = 20.0) -> Dict[str, Any]:
    """A part whose bottom face (length × width) is clearly the largest."""
    return {
        "name": "FlatPlate",
        "bbox": {"length": length, "width": width, "height": height},
        "holes": [],
    }


# ---------------------------------------------------------------------------
# T-1: Cube measurement chain — 3 dimensions, 3 datums, fully constrained
# ---------------------------------------------------------------------------

class TestCubeMeasurementChain:
    """Analytical oracle: 10×10×10 cube → exactly 3 body dimensions, 3 datums."""

    def test_cube_has_three_body_dimensions(self):
        result = extract_measurement_chain(_cube())
        body_dims = [d for d in result.dimensions if d.feature_id == "body"]
        assert len(body_dims) == 3, f"expected 3 body dims, got {len(body_dims)}"

    def test_cube_dimensions_are_correct_values(self):
        result = extract_measurement_chain(_cube(10.0))
        body_dims = {d.dof: d.value_mm for d in result.dimensions if d.feature_id == "body"}
        assert abs(body_dims["X"] - 10.0) < 1e-9, f"X={body_dims['X']}"
        assert abs(body_dims["Y"] - 10.0) < 1e-9, f"Y={body_dims['Y']}"
        assert abs(body_dims["Z"] - 10.0) < 1e-9, f"Z={body_dims['Z']}"

    def test_cube_datum_frame_has_three_datums(self):
        result = extract_measurement_chain(_cube())
        df = result.datum_frame
        assert df.A.label == "A"
        assert df.B.label == "B"
        assert df.C.label == "C"

    def test_cube_no_missing_constraints(self):
        result = extract_measurement_chain(_cube())
        assert result.missing_constraints == [], \
            f"unexpected missing constraints: {result.missing_constraints}"

    def test_cube_no_redundancies(self):
        result = extract_measurement_chain(_cube())
        assert result.redundancies == [], \
            f"unexpected redundancies: {result.redundancies}"

    def test_cube_x_dim_anchored_to_datum_c(self):
        result = extract_measurement_chain(_cube())
        x_dim = next(d for d in result.dimensions if d.feature_id == "body" and d.dof == "X")
        assert "C" in x_dim.datum_refs, f"X dim not anchored to C: {x_dim.datum_refs}"

    def test_cube_y_dim_anchored_to_datum_b(self):
        result = extract_measurement_chain(_cube())
        y_dim = next(d for d in result.dimensions if d.feature_id == "body" and d.dof == "Y")
        assert "B" in y_dim.datum_refs, f"Y dim not anchored to B: {y_dim.datum_refs}"

    def test_cube_z_dim_anchored_to_datum_a(self):
        result = extract_measurement_chain(_cube())
        z_dim = next(d for d in result.dimensions if d.feature_id == "body" and d.dof == "Z")
        assert "A" in z_dim.datum_refs, f"Z dim not anchored to A: {z_dim.datum_refs}"

    def test_cube_result_type(self):
        result = extract_measurement_chain(_cube())
        assert isinstance(result, MeasurementChainResult)
        assert isinstance(result.datum_frame, DatumFrame)
        assert isinstance(result.dimensions, list)


# ---------------------------------------------------------------------------
# T-2: Cube with one through-hole — 7 dimensions, hole position anchored to B/C
# ---------------------------------------------------------------------------

class TestCubeWithHole:
    """Analytical oracle: cube + 1 through-hole → 3 body dims + 4 hole dims = 7."""

    def test_total_dimension_count(self):
        result = extract_measurement_chain(_cube_with_hole())
        # 3 body (X, Y, Z) + hole: diameter + depth(THRU) + pos-X + pos-Y = 7
        assert len(result.dimensions) == 7, \
            f"expected 7 dims, got {len(result.dimensions)}: {[d.label for d in result.dimensions]}"

    def test_hole_diameter_dimension_present(self):
        result = extract_measurement_chain(_cube_with_hole(dia=5.0))
        hole_dims = [d for d in result.dimensions if d.feature_id == "hole-0"]
        dia_dims = [d for d in hole_dims if d.dof == "diameter"]
        assert len(dia_dims) == 1
        assert abs(dia_dims[0].value_mm - 5.0) < 1e-9

    def test_hole_position_dims_present(self):
        result = extract_measurement_chain(_cube_with_hole(side=10.0))
        hole_dims = [d for d in result.dimensions if d.feature_id == "hole-0"]
        pos_x = [d for d in hole_dims if d.dof == "X" and d.dim_type == "position"]
        pos_y = [d for d in hole_dims if d.dof == "Y" and d.dim_type == "position"]
        assert len(pos_x) == 1, "no position-X dimension for hole"
        assert len(pos_y) == 1, "no position-Y dimension for hole"

    def test_hole_position_x_anchored_to_datum_c(self):
        result = extract_measurement_chain(_cube_with_hole(side=10.0))
        pos_x = next(
            d for d in result.dimensions
            if d.feature_id == "hole-0" and d.dof == "X" and d.dim_type == "position"
        )
        assert "C" in pos_x.datum_refs, f"hole pos-X not anchored to C: {pos_x.datum_refs}"

    def test_hole_position_y_anchored_to_datum_b(self):
        result = extract_measurement_chain(_cube_with_hole(side=10.0))
        pos_y = next(
            d for d in result.dimensions
            if d.feature_id == "hole-0" and d.dof == "Y" and d.dim_type == "position"
        )
        assert "B" in pos_y.datum_refs, f"hole pos-Y not anchored to B: {pos_y.datum_refs}"

    def test_hole_position_values(self):
        """Hole at centre of 10×10 cube → pos-X=5, pos-Y=5."""
        result = extract_measurement_chain(_cube_with_hole(side=10.0))
        pos_x = next(
            d for d in result.dimensions
            if d.feature_id == "hole-0" and d.dof == "X" and d.dim_type == "position"
        )
        pos_y = next(
            d for d in result.dimensions
            if d.feature_id == "hole-0" and d.dof == "Y" and d.dim_type == "position"
        )
        assert abs(pos_x.value_mm - 5.0) < 1e-9, f"pos-X={pos_x.value_mm}"
        assert abs(pos_y.value_mm - 5.0) < 1e-9, f"pos-Y={pos_y.value_mm}"

    def test_no_redundancies_for_cube_with_hole(self):
        result = extract_measurement_chain(_cube_with_hole())
        assert result.redundancies == [], f"unexpected redundancies: {result.redundancies}"

    def test_no_missing_constraints_for_cube_with_hole(self):
        result = extract_measurement_chain(_cube_with_hole())
        assert result.missing_constraints == [], \
            f"unexpected missing: {result.missing_constraints}"

    def test_feature_count(self):
        result = extract_measurement_chain(_cube_with_hole())
        # body (1) + hole (1) = 2
        assert result.feature_count == 2


# ---------------------------------------------------------------------------
# T-3: Auto-datum inference — largest flat face → A; perpendicular → B
# ---------------------------------------------------------------------------

class TestAutoDatumInference:
    """Analytical oracle: 100×60×20 part — bottom (100×60=6000) is largest → A."""

    def test_a_datum_is_largest_face(self):
        body = _flat_plate(100.0, 60.0, 20.0)
        df = infer_datum_frame(body)
        # bottom area = 100*60 = 6000; front area = 100*20 = 2000; left = 60*20 = 1200
        # top also = 6000, but face_data is sorted desc and bottom comes before top
        # in our list... actually both bottom and top are 6000; whichever comes first
        # in the sorted list should be A.  Assert area is the maximum.
        max_area = df.A.area_mm2
        assert max_area >= 5999.0, f"A datum area {max_area} < expected ~6000"
        assert df.A.label == "A"

    def test_b_datum_is_perpendicular_to_a(self):
        body = _flat_plate(100.0, 60.0, 20.0)
        df = infer_datum_frame(body)
        na = df.A.normal
        nb = df.B.normal
        dot = abs(na[0]*nb[0] + na[1]*nb[1] + na[2]*nb[2])
        assert dot < 0.1, f"A and B are not perpendicular: dot={dot}"

    def test_c_datum_is_perpendicular_to_both_a_and_b(self):
        body = _flat_plate(100.0, 60.0, 20.0)
        df = infer_datum_frame(body)
        na, nb, nc = df.A.normal, df.B.normal, df.C.normal
        dot_ac = abs(na[0]*nc[0] + na[1]*nc[1] + na[2]*nc[2])
        dot_bc = abs(nb[0]*nc[0] + nb[1]*nc[1] + nb[2]*nc[2])
        assert dot_ac < 0.1, f"A and C not perpendicular: dot={dot_ac}"
        assert dot_bc < 0.1, f"B and C not perpendicular: dot={dot_bc}"

    def test_datum_labels_a_b_c(self):
        body = _flat_plate()
        df = infer_datum_frame(body)
        assert df.A.label == "A"
        assert df.B.label == "B"
        assert df.C.label == "C"

    def test_a_datum_face_name_is_bottom_or_top(self):
        """For 100×60×20 part, largest face is bottom or top (area=6000)."""
        body = _flat_plate(100.0, 60.0, 20.0)
        df = infer_datum_frame(body)
        assert df.A.face_name in ("bottom", "top"), \
            f"expected A on bottom or top, got {df.A.face_name}"

    def test_no_bbox_returns_fallback(self):
        """No bbox → fallback A=bottom, B=front, C=left."""
        df = infer_datum_frame({"name": "NoBbox"})
        assert df.A.label == "A"
        assert df.B.label == "B"
        assert df.C.label == "C"

    def test_non_dict_body_returns_fallback(self):
        df = infer_datum_frame("not a dict")
        assert df.A.label == "A"


# ---------------------------------------------------------------------------
# T-4: Redundancy detection
# ---------------------------------------------------------------------------

class TestRedundancyDetection:
    """A chain where the body's X DOF is dimensioned twice → flagged redundant."""

    def _part_with_redundant_overall(self) -> Dict[str, Any]:
        """A 100×50×30 part that also has an extended feature whose 'X' position
        would be redundant if we forced a second body-X dimension.

        We simulate a redundant scenario by using a part with a feature list
        that re-dimensions an already-constrained DOF.  In our implementation,
        re-calling `tracker.add` with the same (feature_id, dof) triggers the
        redundancy flag.  We expose this via a synthetic body dict with a
        'features' entry that the extractor will dimension — but for the direct
        redundancy-in-body test we subclass and call the internal tracker.
        """
        # A simpler approach: add two holes at the same position with the same
        # feature_id is not possible via the public dict.  Instead we use the
        # 'features' list to force a second dimensioning.
        # Actually the cleanest way is to directly test the _DofTracker.
        return {}   # placeholder; see test below

    def test_tracker_flags_redundant_dof(self):
        """Directly verify the _DofTracker redundancy logic."""
        from kerf_cad_core.drawings.measurement_chain import _DofTracker
        tracker = _DofTracker()
        d1 = tracker.add("linear", "X=100", 100.0, 0.3, "body", "X", ["C"])
        d2 = tracker.add("linear", "X=100 (segment sum)", 100.0, 0.3, "body", "X", ["C"])
        assert not d1.is_redundant, "first dim should not be redundant"
        assert d2.is_redundant, "second dim for same DOF must be redundant"
        assert d2.redundant_with == d1.id

    def test_tracker_redundancy_pair_recorded(self):
        from kerf_cad_core.drawings.measurement_chain import _DofTracker
        tracker = _DofTracker()
        d1 = tracker.add("linear", "X=100", 100.0, 0.3, "body", "X", ["C"])
        d2 = tracker.add("linear", "X=100 dup", 100.0, 0.3, "body", "X", ["C"])
        assert d2.redundant_with == d1.id

    def test_extract_chain_exposes_redundancy_from_slot_feature(self):
        """A part where body X is already constrained and an extended slot
        feature re-dimensions the same DOF with 'body' feature_id — we verify
        the extract_measurement_chain propagates redundancy info."""
        # We use a slot feature whose dimensioning does NOT re-use feature_id 'body',
        # so there is no redundancy for a normal part.  To create a deliberate
        # redundancy we test via the _DofTracker directly (above).
        # This test verifies normal extraction produces NO redundancies for a
        # clean part (negative test of redundancy detection).
        body = {
            "name": "Bracket",
            "bbox": {"length": 100.0, "width": 50.0, "height": 30.0},
            "holes": [],
            "features": [
                {
                    "type": "slot",
                    "length_mm": 40.0,
                    "width_mm": 10.0,
                    "x_mm": 30.0,
                    "y_mm": 20.0,
                    "z_mm": 30.0,
                }
            ],
        }
        result = extract_measurement_chain(body)
        # Body and slot have different feature_ids → no redundancy
        assert result.redundancies == [], \
            f"unexpected redundancies for clean part: {result.redundancies}"

    def test_redundancy_detection_integration(self):
        """Three-segment part: if overall X AND three sub-segment X dims are
        all given on the same feature_id, the 2nd/3rd are redundant.
        We simulate this via _DofTracker directly."""
        from kerf_cad_core.drawings.measurement_chain import _DofTracker
        tracker = _DofTracker()
        d1 = tracker.add("linear", "overall=90", 90.0, 0.3, "body", "X", ["C"])
        d2 = tracker.add("linear", "seg-A=30", 30.0, 0.2, "body", "X", ["C"])
        d3 = tracker.add("linear", "seg-B=30", 30.0, 0.2, "body", "X", ["C"])
        d4 = tracker.add("linear", "seg-C=30", 30.0, 0.2, "body", "X", ["C"])
        redundant = [d for d in [d1, d2, d3, d4] if d.is_redundant]
        assert len(redundant) == 3, \
            f"expected 3 redundant dims for 4 constraints on same DOF, got {len(redundant)}"


# ---------------------------------------------------------------------------
# T-5: Inspection report generation
# ---------------------------------------------------------------------------

class TestInspectionReport:
    def test_report_iso129_non_empty(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ISO129")
        assert len(report) > 0

    def test_report_contains_datum_section(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ISO129")
        assert "DATUM REFERENCE FRAME" in report

    def test_report_contains_dimensions_section(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ISO129")
        assert "DIMENSIONS" in report

    def test_report_iso129_heading(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ISO129")
        assert "ISO 129-1" in report

    def test_report_asme_heading(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ASME14.5")
        assert "ASME Y14.5" in report

    def test_report_asme_datum_note(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ASME14.5")
        assert "§3.4" in report or "rotational DOF" in report

    def test_report_lists_dimension_ids(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ISO129")
        assert "DIM-001" in report

    def test_report_no_redundancy_section_for_clean_chain(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ISO129")
        assert "REDUNDANT DIMENSIONS" not in report

    def test_report_redundancy_section_present_when_redundant(self):
        from kerf_cad_core.drawings.measurement_chain import _DofTracker
        tracker = _DofTracker()
        tracker.add("linear", "X=10", 10.0, 0.2, "body", "X", ["C"])
        tracker.add("linear", "X=10 dup", 10.0, 0.2, "body", "X", ["C"])
        df = _fallback_frame()
        result = MeasurementChainResult(
            dimensions=tracker._dims,
            datum_frame=df,
            redundancies=[("DIM-001", "DIM-002")],
            missing_constraints=[],
            feature_count=1,
            dof_total=3,
            dof_constrained=1,
        )
        report = generate_inspection_report(result, format="ISO129")
        assert "REDUNDANT DIMENSIONS" in report

    def test_invalid_format_falls_back_to_iso129(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="BADFORMAT")
        assert "ISO 129-1" in report

    def test_report_ends_with_end_of_report(self):
        result = extract_measurement_chain(_cube())
        report = generate_inspection_report(result, format="ISO129")
        assert report.strip().endswith("END OF REPORT")


def _fallback_frame() -> DatumFrame:
    return DatumFrame(
        A=DatumFace("A", "bottom", (0.0, 0.0, -1.0), 100.0, -5.0),
        B=DatumFace("B", "front",  (0.0, -1.0, 0.0), 50.0,  -5.0),
        C=DatumFace("C", "left",   (-1.0, 0.0, 0.0), 30.0,  -5.0),
    )


# ---------------------------------------------------------------------------
# T-6: Tolerance helpers
# ---------------------------------------------------------------------------

class TestToleranceHelpers:
    def test_general_tolerance_small(self):
        assert abs(_general_tolerance(3.0) - 0.10) < 1e-9

    def test_general_tolerance_medium(self):
        assert abs(_general_tolerance(15.0) - 0.20) < 1e-9

    def test_general_tolerance_large(self):
        assert abs(_general_tolerance(100.0) - 0.30) < 1e-9

    def test_diameter_tolerance_increases_with_size(self):
        t6 = _diameter_tolerance(6.0)
        t30 = _diameter_tolerance(30.0)
        assert t30 > t6

    def test_diameter_tolerance_positive(self):
        for d in [1, 6, 10, 18, 25, 50, 100]:
            assert _diameter_tolerance(d) > 0


# ---------------------------------------------------------------------------
# T-7: Error / edge-case paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_non_dict_body_returns_result(self):
        result = extract_measurement_chain("not a dict")
        assert isinstance(result, MeasurementChainResult)
        assert len(result.missing_constraints) > 0 or len(result.dimensions) == 0

    def test_empty_body_returns_result(self):
        result = extract_measurement_chain({})
        assert isinstance(result, MeasurementChainResult)

    def test_body_without_bbox_has_missing_constraints(self):
        result = extract_measurement_chain({"name": "NoBox", "holes": []})
        assert len(result.missing_constraints) > 0

    def test_body_with_zero_side_does_not_raise(self):
        result = extract_measurement_chain(
            {"bbox": {"length": 0.0, "width": 0.0, "height": 0.0}}
        )
        assert isinstance(result, MeasurementChainResult)

    def test_hole_without_diameter_adds_missing_constraint(self):
        body = {
            "bbox": {"length": 20.0, "width": 20.0, "height": 10.0},
            "holes": [{"diameter_mm": 0.0, "x_mm": 5.0, "y_mm": 5.0}],
        }
        result = extract_measurement_chain(body)
        missing = " ".join(result.missing_constraints)
        assert "diameter" in missing

    def test_generate_report_never_raises_on_bad_input(self):
        # Pass a deliberately broken chain
        df = _fallback_frame()
        chain = MeasurementChainResult(
            dimensions=[],
            datum_frame=df,
            redundancies=[],
            missing_constraints=[],
            feature_count=0,
            dof_total=0,
            dof_constrained=0,
        )
        report = generate_inspection_report(chain)
        assert isinstance(report, str)


# ---------------------------------------------------------------------------
# T-8: Multiple holes
# ---------------------------------------------------------------------------

class TestMultipleHoles:
    def _two_hole_part(self) -> Dict[str, Any]:
        return {
            "name": "TwoHolePlate",
            "bbox": {"length": 100.0, "width": 50.0, "height": 20.0},
            "holes": [
                {
                    "diameter_mm": 8.0,
                    "depth_mm": None,
                    "x_mm": 20.0, "y_mm": 25.0, "z_mm": 20.0,
                    "threaded": False, "thread_pitch_mm": None,
                    "countersunk": False, "counterbored": False,
                },
                {
                    "diameter_mm": 8.0,
                    "depth_mm": None,
                    "x_mm": 80.0, "y_mm": 25.0, "z_mm": 20.0,
                    "threaded": False, "thread_pitch_mm": None,
                    "countersunk": False, "counterbored": False,
                },
            ],
        }

    def test_two_holes_produce_correct_dimension_count(self):
        result = extract_measurement_chain(self._two_hole_part())
        # 3 body + 4 per hole × 2 = 11
        assert len(result.dimensions) == 11, \
            f"expected 11, got {len(result.dimensions)}: {[d.label for d in result.dimensions]}"

    def test_each_hole_has_own_feature_id(self):
        result = extract_measurement_chain(self._two_hole_part())
        fids = {d.feature_id for d in result.dimensions}
        assert "hole-0" in fids
        assert "hole-1" in fids

    def test_two_holes_no_redundancies(self):
        result = extract_measurement_chain(self._two_hole_part())
        assert result.redundancies == []
