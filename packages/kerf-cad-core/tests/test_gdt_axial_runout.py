"""
Tests for axial (face) runout — ASME Y14.5-2018 §12.5 / §13.3 axial component.

Pure-Python, hermetic — no OCC, no DB, no fixtures from disk.

Coverage:
  1. Flat face (all z equal): axial FIM = 0, compliant
  2. Tilted face (wobble/tilt): nonzero FIM, pass/fail vs tolerance
  3. Wavy face (sinusoidal z): detected, FIM = wave amplitude range
  4. Pass just at tolerance boundary (fom = 1.0 edge case)
  5. Fail by tiny margin (FIM just over tolerance)
  6. fom correctness
  7. to_dict round-trip / key presence
  8. Re-export from gdt __init__
  9. Input validation: empty list
  10. Input validation: single point
  11. Input validation: tolerance = 0
  12. Input validation: negative tolerance
  13. Input validation: negative radial_position_mm
  14. Input validation: non-numeric fields
  15. from_dict round-trip
  16. Many-point wavy face: FIM matches analytical amplitude
"""
from __future__ import annotations

import math

import pytest

from kerf_cad_core.gdt.runout_check import (
    AxialRunoutMeasurement,
    AxialRunoutReport,
    check_axial_runout,
)
# Also check re-export from package __init__
from kerf_cad_core.gdt import (
    AxialRunoutMeasurement as ARM2,
    AxialRunoutReport as ARR2,
    check_axial_runout as car2,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_face(z: float = 5.0, n: int = 12, r: float = 25.0) -> list[AxialRunoutMeasurement]:
    """Return n equally-spaced measurements on a flat face at axial z."""
    return [
        AxialRunoutMeasurement(
            angular_position_deg=360.0 * i / n,
            radial_position_mm=r,
            axial_z_mm=z,
        )
        for i in range(n)
    ]


def _tilted_face(
    tilt_amplitude_mm: float = 0.1,
    n: int = 36,
    r: float = 25.0,
    z_nominal: float = 5.0,
) -> list[AxialRunoutMeasurement]:
    """
    Return measurements on a face tilted about an axis perpendicular to datum.
    z(theta) = z_nominal + tilt_amplitude_mm * cos(theta).
    FIM = max(z) - min(z) = 2 * tilt_amplitude_mm.
    """
    pts = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        z = z_nominal + tilt_amplitude_mm * math.cos(theta)
        pts.append(AxialRunoutMeasurement(
            angular_position_deg=math.degrees(theta),
            radial_position_mm=r,
            axial_z_mm=z,
        ))
    return pts


def _wavy_face(
    amplitude_mm: float = 0.05,
    n_waves: int = 3,
    n: int = 72,
    r: float = 25.0,
    z_nominal: float = 0.0,
) -> list[AxialRunoutMeasurement]:
    """
    Return measurements on a face with sinusoidal axial waviness.
    z(theta) = z_nominal + amplitude_mm * sin(n_waves * theta).
    FIM = 2 * amplitude_mm.
    """
    pts = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        z = z_nominal + amplitude_mm * math.sin(n_waves * theta)
        pts.append(AxialRunoutMeasurement(
            angular_position_deg=math.degrees(theta),
            radial_position_mm=r,
            axial_z_mm=z,
        ))
    return pts


# ---------------------------------------------------------------------------
# Test 1: Flat face — axial FIM = 0, compliant
# ---------------------------------------------------------------------------

def test_flat_face_fim_zero():
    """All points at z=5.0 → axial FIM=0, compliant."""
    pts = _flat_face(z=5.0, n=12)
    report = check_axial_runout(pts, tolerance_mm=0.05)
    assert report.axial_fim_mm == 0.0
    assert report.compliant is True
    assert report.fom == 0.0
    assert report.z_max_mm == pytest.approx(5.0, abs=1e-10)
    assert report.z_min_mm == pytest.approx(5.0, abs=1e-10)
    assert report.n_points == 12


def test_flat_face_at_zero_z():
    """Flat face at z=0 → FIM=0."""
    pts = _flat_face(z=0.0, n=6)
    report = check_axial_runout(pts, tolerance_mm=0.10)
    assert report.axial_fim_mm == 0.0
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 2: Tilted face — FIM = 2 * tilt_amplitude
# ---------------------------------------------------------------------------

def test_tilted_face_fim_equals_twice_amplitude():
    """
    Face tilted with amplitude 0.1 mm: z(theta) = z0 + 0.1*cos(theta).
    FIM should be 2*0.1 = 0.2 mm.
    """
    amplitude = 0.1
    pts = _tilted_face(tilt_amplitude_mm=amplitude, n=360)
    report = check_axial_runout(pts, tolerance_mm=0.25)
    assert report.axial_fim_mm == pytest.approx(2 * amplitude, abs=1e-4)
    assert report.compliant is True


def test_tilted_face_exact_two_points():
    """
    Exact geometry: one point at max, one at min of tilt.
    FIM = (z0 + a) - (z0 - a) = 2a.
    """
    a = 0.05
    z0 = 10.0
    pts = [
        AxialRunoutMeasurement(angular_position_deg=0.0, radial_position_mm=20.0,
                               axial_z_mm=z0 + a),
        AxialRunoutMeasurement(angular_position_deg=180.0, radial_position_mm=20.0,
                               axial_z_mm=z0 - a),
    ]
    report = check_axial_runout(pts, tolerance_mm=0.20)
    assert report.axial_fim_mm == pytest.approx(2 * a, abs=1e-12)
    assert report.z_max_mm == pytest.approx(z0 + a, abs=1e-12)
    assert report.z_min_mm == pytest.approx(z0 - a, abs=1e-12)
    assert report.compliant is True


def test_tilted_face_out_of_tolerance():
    """Tilt FIM=0.2 mm > tolerance=0.10 mm → compliant=False."""
    amplitude = 0.1
    pts = _tilted_face(tilt_amplitude_mm=amplitude, n=360)
    report = check_axial_runout(pts, tolerance_mm=0.10)
    assert report.axial_fim_mm == pytest.approx(2 * amplitude, abs=1e-4)
    assert report.compliant is False
    assert report.fom > 1.0


# ---------------------------------------------------------------------------
# Test 3: Wavy face — detected, FIM = 2 * wave amplitude
# ---------------------------------------------------------------------------

def test_wavy_face_detected():
    """
    Sinusoidal face with amplitude=0.05 mm and 3 waves.
    FIM should be 2*0.05 = 0.10 mm.
    """
    amplitude = 0.05
    pts = _wavy_face(amplitude_mm=amplitude, n_waves=3, n=720)
    report = check_axial_runout(pts, tolerance_mm=0.20)
    assert report.axial_fim_mm == pytest.approx(2 * amplitude, abs=1e-4)
    assert report.compliant is True


def test_wavy_face_exceeds_tolerance():
    """Wavy face FIM=0.10 mm > tolerance=0.08 mm → compliant=False."""
    amplitude = 0.05
    pts = _wavy_face(amplitude_mm=amplitude, n_waves=5, n=720)
    report = check_axial_runout(pts, tolerance_mm=0.08)
    assert report.axial_fim_mm == pytest.approx(2 * amplitude, abs=1e-4)
    assert report.compliant is False


# ---------------------------------------------------------------------------
# Test 4: Pass/fail at tolerance boundary
# ---------------------------------------------------------------------------

def test_fim_exactly_at_tolerance_passes():
    """FIM = tolerance exactly → compliant=True (boundary is inclusive)."""
    tol = 0.10
    pts = [
        AxialRunoutMeasurement(angular_position_deg=0.0, radial_position_mm=10.0,
                               axial_z_mm=0.0),
        AxialRunoutMeasurement(angular_position_deg=180.0, radial_position_mm=10.0,
                               axial_z_mm=tol),
    ]
    report = check_axial_runout(pts, tolerance_mm=tol)
    assert report.axial_fim_mm == pytest.approx(tol, abs=1e-12)
    assert report.compliant is True
    assert report.fom == pytest.approx(1.0, abs=1e-12)


def test_fim_just_over_tolerance_fails():
    """FIM slightly over tolerance → compliant=False."""
    tol = 0.10
    fim = tol + 1e-9
    pts = [
        AxialRunoutMeasurement(angular_position_deg=0.0, radial_position_mm=10.0,
                               axial_z_mm=0.0),
        AxialRunoutMeasurement(angular_position_deg=180.0, radial_position_mm=10.0,
                               axial_z_mm=fim),
    ]
    report = check_axial_runout(pts, tolerance_mm=tol)
    assert report.axial_fim_mm > tol
    assert report.compliant is False


# ---------------------------------------------------------------------------
# Test 5: fom correctness
# ---------------------------------------------------------------------------

def test_fom_correctness():
    """fom = axial_fim / tolerance_mm."""
    fim_expected = 0.08
    tol = 0.20
    pts = [
        AxialRunoutMeasurement(angular_position_deg=0.0, radial_position_mm=15.0,
                               axial_z_mm=0.0),
        AxialRunoutMeasurement(angular_position_deg=90.0, radial_position_mm=15.0,
                               axial_z_mm=fim_expected / 2),
        AxialRunoutMeasurement(angular_position_deg=180.0, radial_position_mm=15.0,
                               axial_z_mm=fim_expected),
        AxialRunoutMeasurement(angular_position_deg=270.0, radial_position_mm=15.0,
                               axial_z_mm=fim_expected / 4),
    ]
    report = check_axial_runout(pts, tolerance_mm=tol)
    assert report.axial_fim_mm == pytest.approx(fim_expected, abs=1e-12)
    assert report.fom == pytest.approx(fim_expected / tol, abs=1e-12)
    assert report.fom == pytest.approx(0.4, abs=1e-12)
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 6: to_dict / AxialRunoutReport structure
# ---------------------------------------------------------------------------

def test_to_dict_keys():
    """to_dict() returns all expected keys with correct types."""
    pts = _tilted_face(tilt_amplitude_mm=0.05, n=12)
    report = check_axial_runout(pts, tolerance_mm=0.15, datum_axis_id="B")
    d = report.to_dict()
    assert "axial_fim_mm" in d
    assert "z_max_mm" in d
    assert "z_min_mm" in d
    assert "fom" in d
    assert "compliant" in d
    assert "n_points" in d
    assert "datum_axis_id" in d
    assert "honest_caveat" in d
    assert d["n_points"] == 12
    assert d["datum_axis_id"] == "B"
    assert isinstance(d["honest_caveat"], str)
    assert len(d["honest_caveat"]) > 10


# ---------------------------------------------------------------------------
# Test 7: Re-export from gdt __init__
# ---------------------------------------------------------------------------

def test_reexport_from_gdt_init():
    """gdt package re-exports AxialRunoutMeasurement, AxialRunoutReport, check_axial_runout."""
    assert ARM2 is AxialRunoutMeasurement
    assert ARR2 is AxialRunoutReport
    assert car2 is check_axial_runout


# ---------------------------------------------------------------------------
# Test 8: Input validation — empty / single-point / bad tolerance
# ---------------------------------------------------------------------------

def test_empty_measurements_raises():
    with pytest.raises(ValueError, match="empty"):
        check_axial_runout([], tolerance_mm=0.05)


def test_single_point_raises():
    pts = [AxialRunoutMeasurement(0.0, 10.0, 5.0)]
    with pytest.raises(ValueError, match="at least 2"):
        check_axial_runout(pts, tolerance_mm=0.05)


def test_zero_tolerance_raises():
    pts = _flat_face(n=4)
    with pytest.raises(ValueError, match="tolerance_mm must be > 0"):
        check_axial_runout(pts, tolerance_mm=0.0)


def test_negative_tolerance_raises():
    pts = _flat_face(n=4)
    with pytest.raises(ValueError, match="tolerance_mm must be > 0"):
        check_axial_runout(pts, tolerance_mm=-0.1)


# ---------------------------------------------------------------------------
# Test 9: AxialRunoutMeasurement dataclass validation
# ---------------------------------------------------------------------------

def test_measurement_negative_radial_raises():
    with pytest.raises(ValueError, match="radial_position_mm"):
        AxialRunoutMeasurement(angular_position_deg=0.0,
                               radial_position_mm=-1.0,
                               axial_z_mm=5.0)


def test_measurement_zero_radial_is_valid():
    """Radial position can be 0 (measurement at the axis centre)."""
    m = AxialRunoutMeasurement(angular_position_deg=0.0,
                               radial_position_mm=0.0,
                               axial_z_mm=5.0)
    assert m.radial_position_mm == 0.0


def test_measurement_non_numeric_angle_raises():
    with pytest.raises(ValueError, match="angular_position_deg"):
        AxialRunoutMeasurement(angular_position_deg="bad",
                               radial_position_mm=10.0,
                               axial_z_mm=5.0)


def test_measurement_non_numeric_z_raises():
    with pytest.raises(ValueError, match="axial_z_mm"):
        AxialRunoutMeasurement(angular_position_deg=0.0,
                               radial_position_mm=10.0,
                               axial_z_mm=None)


# ---------------------------------------------------------------------------
# Test 10: from_dict round-trip
# ---------------------------------------------------------------------------

def test_measurement_from_dict_round_trip():
    """AxialRunoutMeasurement serialises and deserialises correctly."""
    m = AxialRunoutMeasurement(angular_position_deg=45.0,
                               radial_position_mm=20.0,
                               axial_z_mm=3.14)
    d = m.to_dict()
    m2 = AxialRunoutMeasurement.from_dict(d)
    assert m2.angular_position_deg == pytest.approx(45.0)
    assert m2.radial_position_mm == pytest.approx(20.0)
    assert m2.axial_z_mm == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# Test 11: Datum axis ID normalisation
# ---------------------------------------------------------------------------

def test_datum_axis_id_normalised_to_uppercase():
    """datum_axis_id is uppercased in the report."""
    pts = _flat_face(n=4)
    report = check_axial_runout(pts, tolerance_mm=0.05, datum_axis_id="a")
    assert report.datum_axis_id == "A"


def test_datum_axis_id_default():
    """Default datum_axis_id is 'A'."""
    pts = _flat_face(n=4)
    report = check_axial_runout(pts, tolerance_mm=0.05)
    assert report.datum_axis_id == "A"


# ---------------------------------------------------------------------------
# Test 12: Many-point wavy face analytical FIM
# ---------------------------------------------------------------------------

def test_many_point_wavy_face_analytical_fim():
    """
    High-resolution wavy face: amplitude=0.025 mm, 7 waves, 1440 points.
    FIM should converge to 2*amplitude within 1e-4 mm.
    """
    amplitude = 0.025
    pts = _wavy_face(amplitude_mm=amplitude, n_waves=7, n=1440)
    report = check_axial_runout(pts, tolerance_mm=0.10)
    assert report.axial_fim_mm == pytest.approx(2 * amplitude, abs=1e-4)
    assert report.n_points == 1440
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 13: n_points in report equals len(measurements)
# ---------------------------------------------------------------------------

def test_n_points_in_report():
    """report.n_points matches the input list length."""
    pts = _flat_face(n=24)
    report = check_axial_runout(pts, tolerance_mm=0.05)
    assert report.n_points == 24


# ---------------------------------------------------------------------------
# Test 14: honest_caveat mentions §12.5 and ASME
# ---------------------------------------------------------------------------

def test_honest_caveat_content():
    """honest_caveat references ASME and §12.5."""
    pts = _flat_face(n=4)
    report = check_axial_runout(pts, tolerance_mm=0.05)
    assert "ASME" in report.honest_caveat
    assert "12.5" in report.honest_caveat
