"""
Tests for ASME Y14.5-2018 §12.4 Circular Runout evaluation.

Covers:
  - Perfect circle (all r=10mm) at one section: FIM=0, PASS
  - Eccentric circle (cam): FIM=2mm with tol=1mm → FAIL
  - Eccentric circle: FIM=2mm with tol=2mm → PASS (boundary)
  - Eccentric circle: FIM=2mm with tol=2.001mm → PASS (just inside)
  - Multi-section: governing is the worst section
  - Multi-section: pass/fail cascades from governing section
  - Margin computation: positive on pass, negative on fail
  - num_measurements_total accumulates across all sections
  - Single section, large N
  - governing_axial_position_mm reports correct section's axial position
  - RunoutMeasurement validation: r≤0 raises
  - RunoutMeasurement validation: non-numeric raises
  - CircularRunoutSpec: empty sections list raises
  - CircularRunoutSpec: section with fewer than 3 points raises
  - CircularRunoutSpec: tolerance ≤ 0 raises
  - CircularRunoutSpec: empty datum_axis_id raises
  - to_dict / from_dict round-trip preserves values
  - honest_caveat is non-empty string
  - datum_axis_id normalised to uppercase
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.gdt.runout_circular import (
    RunoutMeasurement,
    CircularRunoutSpec,
    CircularRunoutReport,
    check_circular_runout,
    _HONEST_CAVEAT,
    _MIN_POINTS_PER_SECTION,
)


# ---------------------------------------------------------------------------
# Helper: build a uniform-radius section (perfect circle)
# ---------------------------------------------------------------------------

def _perfect_section(
    radius: float,
    n_points: int = 12,
    axial_z: float = 0.0,
) -> list[RunoutMeasurement]:
    """N equally-spaced measurements all at the same radius — FIM = 0."""
    return [
        RunoutMeasurement(
            angular_position_deg=i * 360.0 / n_points,
            radial_measurement_mm=radius,
            axial_position_mm=axial_z,
        )
        for i in range(n_points)
    ]


def _eccentric_section(
    nominal_radius: float,
    eccentricity: float,
    n_points: int = 12,
    axial_z: float = 0.0,
) -> list[RunoutMeasurement]:
    """
    Simulate an eccentric cylinder measured about the datum axis.
    r(θ) = nominal_radius + eccentricity * cos(θ)
    FIM = 2 * eccentricity  (max − min of a cosine over 0..360°)
    """
    pts: list[RunoutMeasurement] = []
    for i in range(n_points):
        theta_deg = i * 360.0 / n_points
        theta_rad = math.radians(theta_deg)
        r = nominal_radius + eccentricity * math.cos(theta_rad)
        pts.append(
            RunoutMeasurement(
                angular_position_deg=theta_deg,
                radial_measurement_mm=r,
                axial_position_mm=axial_z,
            )
        )
    return pts


# ---------------------------------------------------------------------------
# Test 1: Perfect circle — FIM=0, PASS
# ---------------------------------------------------------------------------

def test_perfect_circle_fim_zero_pass():
    """All radii equal: FIM=0 for a perfect circle — must PASS."""
    section = _perfect_section(radius=10.0, n_points=12, axial_z=0.0)
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=0.05,
        datum_axis_id="A",
    )
    report = check_circular_runout(spec)

    assert report.pass_fail == "PASS"
    assert report.max_fim_mm == pytest.approx(0.0, abs=1e-10)
    assert len(report.fim_per_section_mm) == 1
    assert report.fim_per_section_mm[0] == pytest.approx(0.0, abs=1e-10)
    assert report.margin_mm == pytest.approx(0.05, abs=1e-10)
    assert report.num_measurements_total == 12
    assert report.governing_axial_position_mm == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 2: Eccentric circle (cam-like), FIM=2mm, tol=1mm → FAIL
# ---------------------------------------------------------------------------

def test_eccentric_circle_fail():
    """Eccentric cylinder with 1mm axis offset: FIM=2mm, tol=1mm → FAIL."""
    # eccentricity = 1mm → FIM = 2 * 1 = 2mm
    section = _eccentric_section(
        nominal_radius=25.0, eccentricity=1.0, n_points=36, axial_z=5.0
    )
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=1.0,
        datum_axis_id="A",
    )
    report = check_circular_runout(spec)

    assert report.pass_fail == "FAIL"
    assert report.max_fim_mm == pytest.approx(2.0, rel=1e-6)
    assert report.margin_mm == pytest.approx(-1.0, rel=1e-6)  # 1.0 − 2.0 = −1.0
    assert report.governing_axial_position_mm == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Test 3: Eccentric circle, FIM=2mm, tol=2mm → PASS (exact boundary)
# ---------------------------------------------------------------------------

def test_eccentric_circle_boundary_pass():
    """FIM == tolerance exactly — must PASS (≤ not <)."""
    section = _eccentric_section(
        nominal_radius=10.0, eccentricity=1.0, n_points=360, axial_z=0.0
    )
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=2.0,
        datum_axis_id="A",
    )
    report = check_circular_runout(spec)
    # FIM ≈ 2 * 1.0 = 2.0 mm (from cosine over 360 uniform points, exact to machine eps)
    assert report.max_fim_mm == pytest.approx(2.0, rel=1e-4)
    assert report.pass_fail == "PASS"
    assert report.margin_mm >= 0.0


# ---------------------------------------------------------------------------
# Test 4: Eccentric circle, FIM=2mm, tol=2.001mm → PASS (just inside)
# ---------------------------------------------------------------------------

def test_eccentric_circle_just_inside_pass():
    """Tolerance slightly above FIM: should PASS with positive margin."""
    section = _eccentric_section(
        nominal_radius=15.0, eccentricity=1.0, n_points=360, axial_z=0.0
    )
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=2.001,
        datum_axis_id="A",
    )
    report = check_circular_runout(spec)
    assert report.pass_fail == "PASS"
    assert report.margin_mm > 0.0


# ---------------------------------------------------------------------------
# Test 5: Multi-section — governing is the WORST section
# ---------------------------------------------------------------------------

def test_multi_section_governing_is_worst():
    """
    Three sections with increasing eccentricity.
    Governing section = the one with highest FIM.
    """
    # Section 0: FIM ≈ 0.2 mm, axial z=0
    s0 = _eccentric_section(nominal_radius=10.0, eccentricity=0.1, n_points=36, axial_z=0.0)
    # Section 1: FIM ≈ 1.0 mm, axial z=10
    s1 = _eccentric_section(nominal_radius=10.0, eccentricity=0.5, n_points=36, axial_z=10.0)
    # Section 2: FIM ≈ 2.0 mm, axial z=20  ← governing
    s2 = _eccentric_section(nominal_radius=10.0, eccentricity=1.0, n_points=36, axial_z=20.0)

    spec = CircularRunoutSpec(
        measurements_per_cross_section=[s0, s1, s2],
        tolerance_mm=0.5,
        datum_axis_id="B",
    )
    report = check_circular_runout(spec)

    assert report.pass_fail == "FAIL"
    assert len(report.fim_per_section_mm) == 3
    assert report.max_fim_mm == pytest.approx(report.fim_per_section_mm[2], rel=1e-9)
    assert report.governing_axial_position_mm == pytest.approx(20.0)
    assert report.fim_per_section_mm[0] < report.fim_per_section_mm[1]
    assert report.fim_per_section_mm[1] < report.fim_per_section_mm[2]


# ---------------------------------------------------------------------------
# Test 6: Multi-section where only one section fails
# ---------------------------------------------------------------------------

def test_multi_section_one_section_fails():
    """
    Two sections: one passes, one fails.
    Overall result must be FAIL and governing must be the failing section.
    """
    s_pass = _perfect_section(radius=8.0, n_points=12, axial_z=0.0)
    s_fail = _eccentric_section(nominal_radius=8.0, eccentricity=0.6, n_points=36, axial_z=50.0)

    spec = CircularRunoutSpec(
        measurements_per_cross_section=[s_pass, s_fail],
        tolerance_mm=1.0,
    )
    report = check_circular_runout(spec)

    assert report.pass_fail == "FAIL"
    assert report.fim_per_section_mm[0] == pytest.approx(0.0, abs=1e-10)
    assert report.fim_per_section_mm[1] == pytest.approx(1.2, rel=1e-5)
    assert report.governing_axial_position_mm == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Test 7: Multi-section — all pass, governing is still reported
# ---------------------------------------------------------------------------

def test_multi_section_all_pass():
    """All sections pass; governing_axial_position_mm = section with highest FIM."""
    s0 = _eccentric_section(nominal_radius=10.0, eccentricity=0.1, n_points=36, axial_z=0.0)
    s1 = _eccentric_section(nominal_radius=10.0, eccentricity=0.05, n_points=36, axial_z=5.0)

    spec = CircularRunoutSpec(
        measurements_per_cross_section=[s0, s1],
        tolerance_mm=0.5,
    )
    report = check_circular_runout(spec)

    assert report.pass_fail == "PASS"
    assert report.governing_axial_position_mm == pytest.approx(0.0)  # s0 has higher FIM
    assert report.margin_mm > 0.0


# ---------------------------------------------------------------------------
# Test 8: margin_mm is correct (positive and negative cases)
# ---------------------------------------------------------------------------

def test_margin_positive_on_pass():
    section = _perfect_section(radius=5.0, n_points=8, axial_z=0.0)
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=0.1,
    )
    report = check_circular_runout(spec)
    assert report.margin_mm == pytest.approx(0.1, abs=1e-10)  # 0.1 − 0.0


def test_margin_negative_on_fail():
    section = _eccentric_section(nominal_radius=10.0, eccentricity=1.0, n_points=36, axial_z=0.0)
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=0.5,
    )
    report = check_circular_runout(spec)
    assert report.pass_fail == "FAIL"
    # margin ≈ 0.5 − 2.0 = −1.5
    assert report.margin_mm == pytest.approx(0.5 - report.max_fim_mm, rel=1e-6)
    assert report.margin_mm < 0.0


# ---------------------------------------------------------------------------
# Test 9: num_measurements_total accumulates across sections
# ---------------------------------------------------------------------------

def test_num_measurements_total():
    s0 = _perfect_section(radius=10.0, n_points=8, axial_z=0.0)
    s1 = _perfect_section(radius=10.0, n_points=12, axial_z=5.0)
    s2 = _perfect_section(radius=10.0, n_points=6, axial_z=10.0)

    spec = CircularRunoutSpec(
        measurements_per_cross_section=[s0, s1, s2],
        tolerance_mm=0.05,
    )
    report = check_circular_runout(spec)
    assert report.num_measurements_total == 8 + 12 + 6


# ---------------------------------------------------------------------------
# Test 10: RunoutMeasurement validation — r ≤ 0 raises ValueError
# ---------------------------------------------------------------------------

def test_runout_measurement_zero_radius_raises():
    with pytest.raises(ValueError, match="radial_measurement_mm must be > 0"):
        RunoutMeasurement(angular_position_deg=0.0, radial_measurement_mm=0.0)


def test_runout_measurement_negative_radius_raises():
    with pytest.raises(ValueError, match="radial_measurement_mm must be > 0"):
        RunoutMeasurement(angular_position_deg=90.0, radial_measurement_mm=-5.0)


# ---------------------------------------------------------------------------
# Test 11: RunoutMeasurement validation — non-numeric raises
# ---------------------------------------------------------------------------

def test_runout_measurement_non_numeric_radius_raises():
    with pytest.raises(ValueError, match="radial_measurement_mm must be numeric"):
        RunoutMeasurement(angular_position_deg=0.0, radial_measurement_mm="bad")  # type: ignore[arg-type]


def test_runout_measurement_non_numeric_angle_raises():
    with pytest.raises(ValueError, match="angular_position_deg must be numeric"):
        RunoutMeasurement(angular_position_deg="bad", radial_measurement_mm=10.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 12: CircularRunoutSpec — empty sections list raises
# ---------------------------------------------------------------------------

def test_spec_empty_sections_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        CircularRunoutSpec(
            measurements_per_cross_section=[],
            tolerance_mm=0.05,
        )


# ---------------------------------------------------------------------------
# Test 13: CircularRunoutSpec — section with fewer than 3 points raises
# ---------------------------------------------------------------------------

def test_spec_section_too_few_points_raises():
    two_pts = [
        RunoutMeasurement(0.0, 10.0),
        RunoutMeasurement(180.0, 10.0),
    ]
    with pytest.raises(ValueError, match="minimum 3 required"):
        CircularRunoutSpec(
            measurements_per_cross_section=[two_pts],
            tolerance_mm=0.05,
        )


def test_spec_section_one_point_raises():
    one_pt = [RunoutMeasurement(0.0, 10.0)]
    with pytest.raises(ValueError, match="minimum 3 required"):
        CircularRunoutSpec(
            measurements_per_cross_section=[one_pt],
            tolerance_mm=0.1,
        )


# ---------------------------------------------------------------------------
# Test 14: CircularRunoutSpec — tolerance ≤ 0 raises
# ---------------------------------------------------------------------------

def test_spec_zero_tolerance_raises():
    section = _perfect_section(radius=10.0, n_points=4)
    with pytest.raises(ValueError, match="tolerance_mm must be > 0"):
        CircularRunoutSpec(
            measurements_per_cross_section=[section],
            tolerance_mm=0.0,
        )


def test_spec_negative_tolerance_raises():
    section = _perfect_section(radius=10.0, n_points=4)
    with pytest.raises(ValueError, match="tolerance_mm must be > 0"):
        CircularRunoutSpec(
            measurements_per_cross_section=[section],
            tolerance_mm=-0.1,
        )


# ---------------------------------------------------------------------------
# Test 15: datum_axis_id normalised to uppercase
# ---------------------------------------------------------------------------

def test_datum_axis_id_normalised_uppercase():
    section = _perfect_section(radius=10.0, n_points=4)
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=0.05,
        datum_axis_id="b",
    )
    assert spec.datum_axis_id == "B"


# ---------------------------------------------------------------------------
# Test 16: to_dict / from_dict round-trip
# ---------------------------------------------------------------------------

def test_to_dict_from_dict_round_trip():
    s0 = _eccentric_section(nominal_radius=10.0, eccentricity=0.2, n_points=8, axial_z=0.0)
    s1 = _eccentric_section(nominal_radius=10.0, eccentricity=0.5, n_points=8, axial_z=15.0)

    spec = CircularRunoutSpec(
        measurements_per_cross_section=[s0, s1],
        tolerance_mm=0.8,
        datum_axis_id="C",
    )
    report_orig = check_circular_runout(spec)

    # Round-trip spec via dict
    spec2 = CircularRunoutSpec.from_dict(spec.to_dict())
    report2 = check_circular_runout(spec2)

    assert report_orig.pass_fail == report2.pass_fail
    assert report_orig.max_fim_mm == pytest.approx(report2.max_fim_mm, rel=1e-9)
    assert report_orig.num_measurements_total == report2.num_measurements_total

    # Round-trip report via to_dict
    d = report_orig.to_dict()
    assert d["pass_fail"] == report_orig.pass_fail
    assert d["max_fim_mm"] == pytest.approx(report_orig.max_fim_mm, rel=1e-9)
    assert d["num_measurements_total"] == report_orig.num_measurements_total
    assert isinstance(d["honest_caveat"], str) and len(d["honest_caveat"]) > 0


# ---------------------------------------------------------------------------
# Test 17: honest_caveat is a non-empty string
# ---------------------------------------------------------------------------

def test_honest_caveat_non_empty():
    section = _perfect_section(radius=10.0, n_points=4)
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[section],
        tolerance_mm=0.05,
    )
    report = check_circular_runout(spec)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 50  # substantive, not a one-liner
    assert "datum" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 18: Minimum valid section (exactly 3 points)
# ---------------------------------------------------------------------------

def test_minimum_three_points_per_section():
    """Exactly 3 measurements in a section — minimum allowed, should not raise."""
    three_pts = [
        RunoutMeasurement(0.0,   10.0, axial_position_mm=0.0),
        RunoutMeasurement(120.0, 10.5, axial_position_mm=0.0),
        RunoutMeasurement(240.0, 10.2, axial_position_mm=0.0),
    ]
    spec = CircularRunoutSpec(
        measurements_per_cross_section=[three_pts],
        tolerance_mm=1.0,
    )
    report = check_circular_runout(spec)
    assert report.max_fim_mm == pytest.approx(0.5, abs=1e-10)  # 10.5 − 10.0
    assert report.pass_fail == "PASS"
    assert report.num_measurements_total == 3


# ---------------------------------------------------------------------------
# Test 19: governing_axial_position_mm for tied FIM — first section wins
# ---------------------------------------------------------------------------

def test_tied_fim_first_section_governs():
    """Two sections with identical FIM — first section is reported as governing."""
    s0 = _eccentric_section(nominal_radius=10.0, eccentricity=0.5, n_points=36, axial_z=0.0)
    s1 = _eccentric_section(nominal_radius=10.0, eccentricity=0.5, n_points=36, axial_z=100.0)

    spec = CircularRunoutSpec(
        measurements_per_cross_section=[s0, s1],
        tolerance_mm=2.0,
    )
    report = check_circular_runout(spec)
    # Both FIMs ≈ 1.0 mm.  First section should govern (implementation: strict >)
    assert report.governing_axial_position_mm == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 20: conical surface simulation (varying nominal radii across sections)
# ---------------------------------------------------------------------------

def test_conical_surface_per_section_independence():
    """
    Conical feature: each cross-section has a different nominal radius but
    perfect form (eccentricity=0).  All FIMs should be 0 → PASS.
    This confirms circular runout is evaluated PER SECTION (not globally).
    """
    sections = []
    for z_mm in [0.0, 10.0, 20.0, 30.0]:
        # Nominal radius varies with z (cone) but no eccentricity
        r_nom = 10.0 + 0.5 * z_mm  # r grows 0.5 mm per mm axially
        sections.append(_perfect_section(radius=r_nom, n_points=12, axial_z=z_mm))

    spec = CircularRunoutSpec(
        measurements_per_cross_section=sections,
        tolerance_mm=0.01,
    )
    report = check_circular_runout(spec)
    assert report.pass_fail == "PASS"
    assert report.max_fim_mm == pytest.approx(0.0, abs=1e-10)
    for fim in report.fim_per_section_mm:
        assert fim == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Test 21: CircularRunoutSpec — empty datum_axis_id raises
# ---------------------------------------------------------------------------

def test_spec_empty_datum_axis_id_raises():
    section = _perfect_section(radius=10.0, n_points=4)
    with pytest.raises(ValueError, match="datum_axis_id must not be empty"):
        CircularRunoutSpec(
            measurements_per_cross_section=[section],
            tolerance_mm=0.1,
            datum_axis_id="   ",
        )


# ---------------------------------------------------------------------------
# Test 22: Large N measurement set — performance sanity + correctness
# ---------------------------------------------------------------------------

def test_large_measurement_set():
    """1000 points per section, 5 sections — should run quickly and correctly."""
    sections = [
        _eccentric_section(
            nominal_radius=50.0,
            eccentricity=0.02 * (s + 1),
            n_points=200,
            axial_z=float(s * 25),
        )
        for s in range(5)
    ]
    spec = CircularRunoutSpec(
        measurements_per_cross_section=sections,
        tolerance_mm=0.3,
    )
    report = check_circular_runout(spec)
    assert report.num_measurements_total == 5 * 200
    # Section 4 (eccentricity=0.1) has highest FIM ≈ 0.2 mm
    assert report.governing_axial_position_mm == pytest.approx(4 * 25.0)
    assert report.max_fim_mm == pytest.approx(0.2, rel=1e-4)
    assert report.pass_fail == "PASS"
