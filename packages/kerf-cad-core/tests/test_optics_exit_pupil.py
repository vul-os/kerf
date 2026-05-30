"""
Tests for kerf_cad_core.optics.exit_pupil — OPTICS-EXIT-PUPIL-POS.

Test plan
----------
1.  stop_at_last_surface_position_zero         — trivial: stop at last surface -> z=0
2.  stop_at_last_surface_radius_equals_stop    — trivial: radius = stop_radius
3.  stop_at_last_surface_magnification_one     — trivial: magnification = 1.0
4.  thin_lens_stop_at_front_surface_z_zero     — thin lens (t=0): stop at front, EP at z=0
5.  thin_lens_stop_at_front_surface_radius     — thin lens: radius = stop_radius
6.  thin_lens_stop_at_front_surface_mag_one    — thin lens: magnification = 1.0
7.  bk7_stop_at_first_surface_virtual_pupil   — BK7 biconvex: converging rear -> virtual EP (z<0)
8.  bk7_stop_at_first_surface_finite          — BK7: position and radius are finite
9.  bk7_stop_at_first_surface_mag_near_one    — BK7: magnification near 1 (single rear surf)
10. diverging_rear_stop_negative_z             — diverging rear group -> virtual exit pupil
11. diverging_rear_stop_radius_less_stop       — diverging rear: radius < stop_radius (m<1)
12. triplet_stop_at_first_position_finite      — 3-surface: position finite
13. triplet_stop_at_first_radius_positive      — 3-surface: radius > 0
14. triplet_stop_at_second_position_finite     — 3-surface, stop at 1: position finite
15. telescope_ramsden_position                 — Ramsden disk z approx 31.25 mm (Hecht §6.6)
16. telescope_ramsden_radius                   — Ramsden disk radius approx 1.25 mm
17. telescope_ramsden_magnification            — Ramsden magnification approx 0.25 = 1/M_telescope
18. welford_single_rear_surface_position       — Welford §4.4: z approx -3.41 mm (virtual)
19. welford_single_rear_surface_radius         — Welford §4.4: radius approx 5.18 mm
20. welford_single_rear_surface_mag            — Welford §4.4: m approx 1.035
21. magnification_consistent_with_radius       — magnification == radius / (stop_diam/2)
22. diameter_equals_two_times_radius           — diameter_mm == 2 x radius_mm
23. radius_positive                            — radius_mm > 0 for valid inputs
24. position_differs_from_entrance_pupil       — EP and XP positions differ for same stack
25. report_to_dict_ok_true                     — to_dict() has ok=True
26. report_to_dict_honest_flag_paraxial        — honest_flag contains "PARAXIAL"
27. report_to_dict_has_position                — to_dict() has position_z_mm
28. report_to_dict_has_diameter                — to_dict() has diameter_mm
29. report_to_dict_has_magnification           — to_dict() has magnification
30. error_empty_surfaces                       — returns error dict for empty list
31. error_missing_surface_field               — returns error for missing 'c' key
32. error_stop_diameter_zero                   — returns error for stop_diameter_mm=0
33. error_stop_diameter_negative              — returns error for stop_diameter_mm<0
34. error_stop_index_out_of_range             — returns error for invalid stop index
35. error_n_object_lt_1                       — returns error for n_object<1
36. tool_happy_path_stop_at_last              — LLM tool: stop at last surface
37. tool_happy_path_front_stop                — LLM tool: stop at first surface returns ok JSON
38. tool_telescope_ramsden                    — LLM tool: telescope Ramsden disk
39. tool_missing_surfaces                     — LLM tool: error for missing surfaces
40. tool_missing_stop_diameter               — LLM tool: error for missing stop_diameter_mm
41. tool_bad_json                             — LLM tool: handles invalid JSON
42. tool_stop_index_kwarg                     — LLM tool: accepts optional stop_surface_index
43. tool_n_object_kwarg                       — LLM tool: accepts optional n_object

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §4.4.
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.6.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.exit_pupil import (
    ExitPupilReport,
    compute_exit_pupil,
)
from kerf_cad_core.optics.entrance_pupil import compute_entrance_pupil


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bk7_biconvex():
    """BK7 biconvex: R1=+50 mm, R2=-50 mm, t=5 mm, n=1.5168. EFL approx 48 mm."""
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _thin_singlet():
    """Thin singlet (t=0): R1=+50, R2=-50, n=1.5."""
    return [
        {"c": 1.0 / 50.0, "t": 0.0, "n": 1.5},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _diverging_biconcave():
    """Diverging biconcave: R1=-50 mm, R2=+50 mm, n=1.5168."""
    return [
        {"c": -1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c":  1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _triplet_stack():
    """Three surfaces: two lens elements."""
    return [
        {"c":  1.0 / 50.0, "t": 4.0, "n": 1.52},
        {"c": -1.0 / 50.0, "t": 10.0, "n": 1.0},
        {"c":  1.0 / 40.0, "t": 0.0,  "n": 1.0},
    ]


def _telescope_stack():
    """
    Two-element afocal telescope: objective (f=100 mm) + eyepiece (f=25 mm).

    Modelled as biconvex thin lenses (t=0 glass) separated by f_obj + f_eye = 125 mm:
      Surface 0: objective front   (c = 1/100, t=0, n=1.5)
      Surface 1: objective rear    (c = -1/100, t=125, n=1.0)   <- stop here
      Surface 2: eyepiece front    (c = 1/25, t=0, n=1.5)
      Surface 3: eyepiece rear     (c = -1/25, t=0, n=1.0)

    Stop at objective rear (index 1):
      Exit pupil (Ramsden disk): z approx 31.25 mm from eyepiece rear (surface 3).
      Ramsden disk radius approx 1.25 mm (= stop_radius / telescope_magnification = 5/4).
      Magnification approx 0.25 (Hecht §6.6).
    """
    return [
        {"c":  1.0 / 100.0, "t":   0.0, "n": 1.5},   # obj front
        {"c": -1.0 / 100.0, "t": 125.0, "n": 1.0},   # obj rear + gap (stop)
        {"c":  1.0 /  25.0, "t":   0.0, "n": 1.5},   # eye front
        {"c": -1.0 /  25.0, "t":   0.0, "n": 1.0},   # eye rear (last)
    ]


# ---------------------------------------------------------------------------
# Stop at last surface (trivial case)
# ---------------------------------------------------------------------------

def test_stop_at_last_surface_position_zero():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, ExitPupilReport)
    assert r.position_z_mm == pytest.approx(0.0, abs=1e-9)


def test_stop_at_last_surface_radius_equals_stop():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, ExitPupilReport)
    assert r.radius_mm == pytest.approx(5.0, abs=1e-9)


def test_stop_at_last_surface_magnification_one():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, ExitPupilReport)
    assert r.magnification == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Thin lens identity (t=0, stop at front surface)
# ---------------------------------------------------------------------------

def test_thin_lens_stop_at_front_surface_z_zero():
    """
    Thin-lens identity (Hecht §6.6): for a thin lens (t=0) with stop at the front
    surface, the exit pupil is at the rear surface vertex = z=0 from last surface.
    Both surfaces occupy the same plane, so the exit pupil coincides with the stop.
    """
    r = compute_exit_pupil(_thin_singlet(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.position_z_mm == pytest.approx(0.0, abs=1e-9)


def test_thin_lens_stop_at_front_surface_radius():
    r = compute_exit_pupil(_thin_singlet(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.radius_mm == pytest.approx(5.0, abs=1e-9)


def test_thin_lens_stop_at_front_surface_mag_one():
    r = compute_exit_pupil(_thin_singlet(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.magnification == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# BK7 biconvex -- stop at first surface
# ---------------------------------------------------------------------------

def test_bk7_stop_at_first_surface_virtual_pupil():
    """
    BK7 biconvex with stop at surface 0: rear surface (c = -1/50) images the stop
    to a VIRTUAL exit pupil inside the glass (position_z < 0 from last surface).
    The rear surface of a biconvex lens is diverging for rays traveling left-to-right,
    so it pushes the image of the stop inside the lens barrel (Welford 1986 §4.4).
    """
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.position_z_mm < 0.0


def test_bk7_stop_at_first_surface_finite():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert math.isfinite(r.position_z_mm)
    assert math.isfinite(r.radius_mm)


def test_bk7_stop_at_first_surface_mag_near_one():
    """BK7 biconvex: single rear surface gives magnification close to 1."""
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert 0.5 < r.magnification < 2.0


# ---------------------------------------------------------------------------
# Diverging rear group
# ---------------------------------------------------------------------------

def test_diverging_rear_stop_negative_z():
    """
    Diverging biconcave: stop at first surface. The rear convex surface (c=+1/50)
    diverges the exit-pupil ray bundle, giving a virtual exit pupil (z < 0).
    """
    r = compute_exit_pupil(_diverging_biconcave(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.position_z_mm < 0.0


def test_diverging_rear_stop_radius_less_stop():
    """Diverging rear group demagnifies: exit pupil radius < stop radius (m < 1)."""
    r = compute_exit_pupil(_diverging_biconcave(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.magnification < 1.0


# ---------------------------------------------------------------------------
# Triplet (3-surface) stack
# ---------------------------------------------------------------------------

def test_triplet_stop_at_first_position_finite():
    r = compute_exit_pupil(_triplet_stack(), stop_diameter_mm=8.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert math.isfinite(r.position_z_mm)


def test_triplet_stop_at_first_radius_positive():
    r = compute_exit_pupil(_triplet_stack(), stop_diameter_mm=8.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.radius_mm > 0.0


def test_triplet_stop_at_second_position_finite():
    r = compute_exit_pupil(_triplet_stack(), stop_diameter_mm=8.0, stop_surface_index=1)
    assert isinstance(r, ExitPupilReport)
    assert math.isfinite(r.position_z_mm)


# ---------------------------------------------------------------------------
# Oracle: telescope Ramsden disk (Hecht §6.6)
# ---------------------------------------------------------------------------

def test_telescope_ramsden_position():
    """
    Oracle (Hecht §6.6, Ramsden disk):

    Afocal telescope: objective f_obj=100 mm, eyepiece f_eye=25 mm,
    separation = f_obj + f_eye = 125 mm.  Stop at objective rear surface (index 1).

    Image of stop through eyepiece (object at -125mm from eyepiece, f=25mm):
        1/s_i = 1/f + 1/s_o = 1/25 + 1/(-125) = 4/125
        s_i = 125/4 = 31.25 mm  (Ramsden disk, real pupil behind eyepiece).

    Verified by two-ray forward paraxial trace (Welford §4.4).
    """
    r = compute_exit_pupil(_telescope_stack(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, ExitPupilReport)
    assert r.position_z_mm == pytest.approx(31.25, abs=0.1)


def test_telescope_ramsden_radius():
    """
    Oracle (Hecht §6.6): Ramsden disk radius = stop_radius / telescope_magnification
                        = 5.0 / (f_obj / f_eye) = 5.0 / 4.0 = 1.25 mm.
    """
    r = compute_exit_pupil(_telescope_stack(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, ExitPupilReport)
    assert r.radius_mm == pytest.approx(1.25, abs=0.05)


def test_telescope_ramsden_magnification():
    """
    Oracle: exit pupil magnification = 1 / telescope_angular_magnification
           = f_eye / f_obj = 25 / 100 = 0.25.
    """
    r = compute_exit_pupil(_telescope_stack(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, ExitPupilReport)
    assert r.magnification == pytest.approx(0.25, abs=0.01)


# ---------------------------------------------------------------------------
# Oracle: Welford §4.4 single rear surface
# ---------------------------------------------------------------------------

def test_welford_single_rear_surface_position():
    """
    Oracle (Welford 1986 §4.4, single refracting surface):

    BK7 biconvex, stop at surface 0 (front vertex):
      Rear surface: n_in = 1.5168 (glass), n_out = 1.0 (air), c = -1/50 mm^-1.
      Object (stop) is 5 mm to the left of the rear surface (the glass thickness).

    Paraxial imaging formula (Cartesian, single surface):
        n_out/v - n_in/u = (n_out - n_in) * c
        u = -5 mm (stop 5 mm to the left of surface)
        1.0/v - 1.5168/(-5) = (1.0 - 1.5168) * (-1/50) = 0.010336
        1.0/v = 0.010336 - 0.30336 = -0.293024
        v = -3.413 mm  (virtual image, inside glass).

    Exit pupil is virtual: z_ep approx -3.41 mm from last surface.
    """
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.position_z_mm == pytest.approx(-3.413, abs=0.01)


def test_welford_single_rear_surface_radius():
    """
    Oracle: exit pupil radius for BK7 biconvex stop@0.
    h1(z_ep) = h1_last + z_ep * u1_last = 5 + (-3.413)*(-0.05168) approx 5.1764 mm.
    """
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.radius_mm == pytest.approx(5.18, abs=0.05)


def test_welford_single_rear_surface_mag():
    """
    Oracle: magnification for BK7 biconvex stop@0 approx 1.035 (slight magnification).
    """
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.magnification == pytest.approx(1.035, abs=0.005)


# ---------------------------------------------------------------------------
# Consistency checks
# ---------------------------------------------------------------------------

def test_magnification_consistent_with_radius():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    expected_m = r.radius_mm / 5.0   # stop_radius = 5.0
    assert r.magnification == pytest.approx(expected_m, rel=1e-9)


def test_diameter_equals_two_times_radius():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, ExitPupilReport)
    assert r.diameter_mm == pytest.approx(2.0 * r.radius_mm, abs=1e-12)


def test_radius_positive():
    for idx in [0, 1]:
        r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=idx)
        assert isinstance(r, ExitPupilReport)
        assert r.radius_mm > 0.0


def test_position_differs_from_entrance_pupil():
    """
    For BK7 biconvex with stop at surface 0:
    Entrance pupil = at first surface (position_z=0, by definition stop@0).
    Exit pupil = image through rear group = virtual (z approx -3.41 mm).
    They are at different positions.
    """
    ep = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    xp = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert hasattr(ep, 'position_z_mm')
    assert isinstance(xp, ExitPupilReport)
    # EP at z=0; XP at approx -3.41mm
    assert abs(ep.position_z_mm - xp.position_z_mm) > 1.0


# ---------------------------------------------------------------------------
# to_dict / report structure
# ---------------------------------------------------------------------------

def test_report_to_dict_ok_true():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, ExitPupilReport)
    assert r.to_dict()["ok"] is True


def test_report_to_dict_honest_flag_paraxial():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, ExitPupilReport)
    assert "PARAXIAL" in r.to_dict()["honest_flag"]


def test_report_to_dict_has_position():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, ExitPupilReport)
    assert "position_z_mm" in r.to_dict()


def test_report_to_dict_has_diameter():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, ExitPupilReport)
    assert "diameter_mm" in r.to_dict()


def test_report_to_dict_has_magnification():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, ExitPupilReport)
    assert "magnification" in r.to_dict()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = compute_exit_pupil([], stop_diameter_mm=10.0)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "surfaces" in r["reason"]


def test_error_missing_surface_field():
    r = compute_exit_pupil([{"t": 5.0, "n": 1.5}], stop_diameter_mm=10.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_stop_diameter_zero():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=0.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_stop_diameter_negative():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=-5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_stop_index_out_of_range():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=99)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "stop_surface_index" in r["reason"]


def test_error_n_object_lt_1():
    r = compute_exit_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, n_object=0.5)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# LLM tool tests
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.tools import run_compute_exit_pupil  # noqa: E402


def _invoke(payload: dict) -> dict:
    return json.loads(asyncio.run(run_compute_exit_pupil(None, json.dumps(payload).encode())))


_SINGLET = [
    {"c": 0.02, "t": 5.0, "n": 1.5168},
    {"c": -0.02, "t": 0.0, "n": 1.0},
]

_TELESCOPE = [
    {"c": 0.01, "t": 0.0, "n": 1.5},
    {"c": -0.01, "t": 125.0, "n": 1.0},
    {"c": 0.04, "t": 0.0, "n": 1.5},
    {"c": -0.04, "t": 0.0, "n": 1.0},
]


def test_tool_happy_path_stop_at_last():
    """Tool: stop at last surface returns ok JSON with z=0 and m=1."""
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 10.0, "stop_surface_index": 1})
    assert data.get("ok") is True
    assert data["position_z_mm"] == pytest.approx(0.0, abs=1e-9)
    assert data["magnification"] == pytest.approx(1.0, abs=1e-9)


def test_tool_happy_path_front_stop():
    """Tool: stop at first surface returns ok JSON with finite position."""
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 10.0, "stop_surface_index": 0})
    assert data.get("ok") is True
    assert "position_z_mm" in data
    assert math.isfinite(data["position_z_mm"])


def test_tool_telescope_ramsden():
    """Tool: telescope stop at index 1 gives Ramsden disk at approx 31.25 mm."""
    data = _invoke({"surfaces": _TELESCOPE, "stop_diameter_mm": 10.0, "stop_surface_index": 1})
    assert data.get("ok") is True
    assert data["position_z_mm"] == pytest.approx(31.25, abs=0.1)
    assert data["radius_mm"] == pytest.approx(1.25, abs=0.05)
    assert data["magnification"] == pytest.approx(0.25, abs=0.01)


def test_tool_missing_surfaces():
    data = _invoke({"stop_diameter_mm": 10.0})
    assert data.get("ok") is False


def test_tool_missing_stop_diameter():
    data = _invoke({"surfaces": _SINGLET})
    assert data.get("ok") is False


def test_tool_bad_json():
    raw = asyncio.run(run_compute_exit_pupil(None, b"not valid {{{"))
    data = json.loads(raw)
    assert data.get("ok") is False or data.get("code") == "BAD_ARGS" or "error" in data


def test_tool_stop_index_kwarg():
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 8.0, "stop_surface_index": 0})
    assert data.get("ok") is True


def test_tool_n_object_kwarg():
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 8.0, "n_object": 1.0})
    assert data.get("ok") is True
