"""
Tests for kerf_cad_core.optics.entrance_pupil — OPTICS-ENTRANCE-PUPIL-POS.

Test plan
----------
1.  stop_at_first_surface_position_zero       — stop at idx 0: position_z = 0
2.  stop_at_first_surface_radius_equals_stop  — stop at idx 0: radius = stop_radius
3.  stop_at_first_surface_magnification_one   — stop at idx 0: magnification = 1.0
4.  stop_at_first_surface_default_index       — default stop_surface_index=0 works
5.  stop_behind_converging_front_positive_z   — converging front + rear stop → positive z
6.  stop_behind_converging_front_finite       — converging front + rear stop: result finite
7.  stop_behind_converging_front_mag_nonunit  — converging front + rear stop: m ≠ 1
8.  diverging_front_rear_stop_negative_z      — diverging front lens → virtual pupil (neg z)
9.  diverging_front_rear_stop_radius_gt_stop  — diverging front magnifies the stop
10. triplet_rear_stop_position_finite         — 3-surface stack: position is finite
11. triplet_rear_stop_radius_positive         — 3-surface stack: radius > 0
12. bk7_biconvex_stop_at_first_surface        — BK7 biconvex: stop at 0, m=1
13. bk7_biconvex_stop_at_second_surface       — BK7 biconvex: stop at 1, position finite
14. plano_convex_stop_at_second              — plano-convex, stop at 1: finite result
15. magnification_consistent_with_radius      — magnification == radius_mm / (stop_diam/2)
16. diameter_equals_two_times_radius          — diameter_mm == 2 × radius_mm
17. radius_positive                           — radius_mm > 0 for valid inputs
18. report_to_dict_ok_true                    — to_dict() has ok=True
19. report_to_dict_honest_flag_paraxial       — honest_flag contains "PARAXIAL"
20. report_to_dict_has_position               — to_dict() has position_z_mm
21. report_to_dict_has_diameter               — to_dict() has diameter_mm
22. report_to_dict_has_magnification          — to_dict() has magnification
23. error_empty_surfaces                      — returns error dict for empty list
24. error_missing_surface_field               — returns error for missing 'c' key
25. error_stop_diameter_zero                  — returns error for stop_diameter_mm=0
26. error_stop_diameter_negative              — returns error for stop_diameter_mm<0
27. error_stop_index_out_of_range             — returns error for invalid stop index
28. error_n_object_lt_1                       — returns error for n_object<1
29. welford_single_surface_pupil_position     — Welford §4.4: single refracting surface
30. welford_single_surface_pupil_magnification — Welford §4.4: magnification check
31. thin_lens_stop_at_lens_identity          — thin lens, stop at lens: pos=0, m=1
32. tool_happy_path_stop_at_first            — LLM tool: stop at first surface
33. tool_happy_path_rear_stop                — LLM tool: rear stop returns ok JSON
34. tool_missing_surfaces                    — LLM tool: error for missing surfaces
35. tool_missing_stop_diameter               — LLM tool: error for missing stop_diameter_mm
36. tool_bad_json                            — LLM tool: handles invalid JSON
37. tool_stop_index_kwarg                    — LLM tool: accepts optional stop_surface_index
38. tool_n_object_kwarg                      — LLM tool: accepts optional n_object

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

from kerf_cad_core.optics.entrance_pupil import (
    EntrancePupilReport,
    compute_entrance_pupil,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bk7_biconvex():
    """BK7 biconvex: R1=+50 mm, R2=-50 mm, t=5 mm, n=1.5168. EFL≈48 mm."""
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _plano_convex():
    """Plano-convex: R1=+50 mm, R2=flat, t=5 mm, n=1.5168."""
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": 0.0, "t": 0.0, "n": 1.0},
    ]


def _diverging_biconvex():
    """Diverging (biconcave): R1=-50 mm, R2=+50 mm, t=5 mm, n=1.5168.
    Front surface has negative power; a rear stop gives a virtual entrance pupil."""
    return [
        {"c": -1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": 1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _triplet_stack():
    """Three surfaces: front lens + rear two surfaces."""
    return [
        {"c":  1.0 / 50.0, "t": 4.0, "n": 1.52},
        {"c": -1.0 / 50.0, "t": 10.0, "n": 1.0},
        {"c":  1.0 / 40.0, "t": 0.0,  "n": 1.0},
    ]


# ---------------------------------------------------------------------------
# Stop at first surface (trivial case)
# ---------------------------------------------------------------------------

def test_stop_at_first_surface_position_zero():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, EntrancePupilReport)
    assert r.position_z_mm == pytest.approx(0.0, abs=1e-9)


def test_stop_at_first_surface_radius_equals_stop():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, EntrancePupilReport)
    assert r.radius_mm == pytest.approx(5.0, abs=1e-9)


def test_stop_at_first_surface_magnification_one():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, EntrancePupilReport)
    assert r.magnification == pytest.approx(1.0, abs=1e-9)


def test_stop_at_first_surface_default_index():
    """Default stop_surface_index=0: identical to explicit 0."""
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, EntrancePupilReport)
    assert r.position_z_mm == pytest.approx(0.0, abs=1e-9)
    assert r.magnification == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Stop behind a converging front element
# ---------------------------------------------------------------------------

def test_stop_behind_converging_front_positive_z():
    """
    BK7 biconvex: stop at rear surface (index 1), front surface is converging.
    The converging front surface images the stop to a position BEHIND the first
    surface (positive z), because the stop is much closer than the focal length.
    Welford 1986 §4.4: for a stop close to a converging front lens (d << f),
    the entrance pupil is located at positive z (real image inside the barrel).
    """
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert r.position_z_mm > 0.0


def test_stop_behind_converging_front_finite():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert math.isfinite(r.position_z_mm)
    assert math.isfinite(r.radius_mm)


def test_stop_behind_converging_front_mag_nonunit():
    """Magnification ≠ 1 for a rear stop through a converging front element."""
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert not math.isclose(r.magnification, 1.0, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# Stop behind a diverging front element → virtual (negative z) entrance pupil
# ---------------------------------------------------------------------------

def test_diverging_front_rear_stop_negative_z():
    """
    Diverging front lens (biconcave: R1=-50, R2=+50, n=1.5168): a stop at
    the rear surface produces a VIRTUAL entrance pupil in object space
    (position_z_mm < 0 = in front of the first surface).
    Welford 1986 §4.4: diverging front group → virtual entrance pupil.
    Hecht §6.6: virtual pupil = pupil appears on same side as the object.
    """
    r = compute_entrance_pupil(_diverging_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert r.position_z_mm < 0.0


def test_diverging_front_rear_stop_radius_gt_stop():
    """Diverging front magnifies: pupil radius > stop radius (m > 1)."""
    r = compute_entrance_pupil(_diverging_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert r.magnification > 1.0


# ---------------------------------------------------------------------------
# Triplet (3-surface) stack
# ---------------------------------------------------------------------------

def test_triplet_rear_stop_position_finite():
    r = compute_entrance_pupil(_triplet_stack(), stop_diameter_mm=8.0, stop_surface_index=2)
    assert isinstance(r, EntrancePupilReport)
    assert math.isfinite(r.position_z_mm)


def test_triplet_rear_stop_radius_positive():
    r = compute_entrance_pupil(_triplet_stack(), stop_diameter_mm=8.0, stop_surface_index=2)
    assert isinstance(r, EntrancePupilReport)
    assert r.radius_mm > 0.0


# ---------------------------------------------------------------------------
# BK7 biconvex specific
# ---------------------------------------------------------------------------

def test_bk7_biconvex_stop_at_first_surface():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=12.0, stop_surface_index=0)
    assert isinstance(r, EntrancePupilReport)
    assert r.position_z_mm == pytest.approx(0.0, abs=1e-9)
    assert r.diameter_mm == pytest.approx(12.0, abs=1e-9)


def test_bk7_biconvex_stop_at_second_surface():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert math.isfinite(r.position_z_mm)
    assert r.radius_mm > 0.0


def test_plano_convex_stop_at_second():
    r = compute_entrance_pupil(_plano_convex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert math.isfinite(r.position_z_mm)
    assert r.radius_mm > 0.0


# ---------------------------------------------------------------------------
# Consistency checks
# ---------------------------------------------------------------------------

def test_magnification_consistent_with_radius():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    expected_m = r.radius_mm / 5.0   # stop_radius = 5.0
    assert r.magnification == pytest.approx(expected_m, rel=1e-9)


def test_diameter_equals_two_times_radius():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    assert r.diameter_mm == pytest.approx(2.0 * r.radius_mm, abs=1e-12)


def test_radius_positive():
    for idx in [0, 1]:
        r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=idx)
        assert isinstance(r, EntrancePupilReport)
        assert r.radius_mm > 0.0


# ---------------------------------------------------------------------------
# to_dict / report structure
# ---------------------------------------------------------------------------

def test_report_to_dict_ok_true():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, EntrancePupilReport)
    assert r.to_dict()["ok"] is True


def test_report_to_dict_honest_flag_paraxial():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, EntrancePupilReport)
    assert "PARAXIAL" in r.to_dict()["honest_flag"]


def test_report_to_dict_has_position():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, EntrancePupilReport)
    assert "position_z_mm" in r.to_dict()


def test_report_to_dict_has_diameter():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, EntrancePupilReport)
    assert "diameter_mm" in r.to_dict()


def test_report_to_dict_has_magnification():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0)
    assert isinstance(r, EntrancePupilReport)
    assert "magnification" in r.to_dict()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = compute_entrance_pupil([], stop_diameter_mm=10.0)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "surfaces" in r["reason"]


def test_error_missing_surface_field():
    r = compute_entrance_pupil([{"t": 5.0, "n": 1.5}], stop_diameter_mm=10.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_stop_diameter_zero():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=0.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_stop_diameter_negative():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=-5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_stop_index_out_of_range():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, stop_surface_index=99)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "stop_surface_index" in r["reason"]


def test_error_n_object_lt_1():
    r = compute_entrance_pupil(_bk7_biconvex(), stop_diameter_mm=10.0, n_object=0.5)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# Oracle tests: Welford §4.4 / Hecht §6.6
# ---------------------------------------------------------------------------

def test_welford_single_surface_pupil_position():
    """
    Oracle (Welford 1986 §4.4, single refracting surface):

    A single spherical refracting surface: n1=1.0 (air), n2=1.5168 (glass),
    R=+50 mm (c=1/50), followed by a stop at t=5 mm behind the surface.

    Reverse-trace (Welford §4.4):
      Start: h=stop_r, u=0 in medium n2=1.5168.
      Transfer back 5 mm: h = stop_r (unchanged, u=0).
      Refract at surface (c_rev = -1/50, n_in=1.5168, n_out=1.0):
        nu' = n_in*u - h*c_rev*(n_out - n_in)
            = 1.5168*0 - stop_r*(-1/50)*(1.0 - 1.5168)
            = stop_r*(1/50)*(-0.5168)
            = -stop_r * 0.010336
        u_out = nu' / n_out = -stop_r * 0.010336 / 1.0

      position_z_mm = -h / u_out
                    = -stop_r / (-stop_r * 0.010336)
                    = 1 / 0.010336
                    ≈ 96.75 mm

    The entrance pupil is at z ≈ 96.75 mm (real image, inside the barrel).
    Magnification D = n_obj * u2b_final (see docstring):
      Second ray: u2b = 1/n_stop = 1/1.5168 at stop; after 5mm transfer and refraction
        → D ≈ 0.9659 (slight demagnification by front surface).
    """
    surfaces = [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]
    stop_r = 5.0
    r = compute_entrance_pupil(surfaces, stop_diameter_mm=2 * stop_r, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)

    # Position: ~96.75 mm (analytical result above)
    assert r.position_z_mm == pytest.approx(96.75, abs=0.5)  # within 0.5mm

    # Magnification: ~0.966 (slight demagnification through converging front)
    assert r.magnification == pytest.approx(0.966, abs=0.01)


def test_welford_single_surface_pupil_magnification():
    """
    Oracle: D matrix element for single refracting surface.
    D = n_obj * u2b = 1.0 * 0.9659 ≈ 0.9659.
    Radius = D * stop_radius = 0.9659 * 5 ≈ 4.83 mm.
    """
    surfaces = [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]
    r = compute_entrance_pupil(surfaces, stop_diameter_mm=10.0, stop_surface_index=1)
    assert isinstance(r, EntrancePupilReport)
    # Pupil radius = 0.966 * 5.0 ≈ 4.83 mm
    assert r.radius_mm == pytest.approx(4.83, abs=0.05)
    assert r.magnification < 1.0  # slightly demagnified


def test_thin_lens_stop_at_lens_identity():
    """
    Thin-lens identity (Hecht §6.6): for a thin lens with the aperture stop
    at the lens, the entrance pupil coincides with the lens; position=0, m=1.
    Model: two thin surfaces (t=0 between them), stop at surface 0.
    """
    thin_singlet = [
        {"c": 1.0 / 50.0, "t": 0.0, "n": 1.5},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]
    r = compute_entrance_pupil(thin_singlet, stop_diameter_mm=10.0, stop_surface_index=0)
    assert isinstance(r, EntrancePupilReport)
    assert r.position_z_mm == pytest.approx(0.0, abs=1e-9)
    assert r.magnification == pytest.approx(1.0, abs=1e-9)
    assert r.radius_mm == pytest.approx(5.0, abs=1e-9)


# ---------------------------------------------------------------------------
# LLM tool tests
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.tools import run_compute_entrance_pupil  # noqa: E402


def _invoke(payload: dict) -> dict:
    return json.loads(asyncio.run(run_compute_entrance_pupil(None, json.dumps(payload).encode())))


_SINGLET = [
    {"c": 0.02, "t": 5.0, "n": 1.5168},
    {"c": -0.02, "t": 0.0, "n": 1.0},
]


def test_tool_happy_path_stop_at_first():
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 10.0, "stop_surface_index": 0})
    assert data.get("ok") is True
    assert data["position_z_mm"] == pytest.approx(0.0, abs=1e-9)
    assert data["magnification"] == pytest.approx(1.0, abs=1e-9)
    assert "diameter_mm" in data


def test_tool_happy_path_rear_stop():
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 10.0, "stop_surface_index": 1})
    assert data.get("ok") is True
    assert "position_z_mm" in data
    assert math.isfinite(data["position_z_mm"])


def test_tool_missing_surfaces():
    data = _invoke({"stop_diameter_mm": 10.0})
    assert data.get("ok") is False


def test_tool_missing_stop_diameter():
    data = _invoke({"surfaces": _SINGLET})
    assert data.get("ok") is False


def test_tool_bad_json():
    raw = asyncio.run(run_compute_entrance_pupil(None, b"not valid {{{"))
    data = json.loads(raw)
    assert data.get("ok") is False or data.get("code") == "BAD_ARGS" or "error" in data


def test_tool_stop_index_kwarg():
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 8.0, "stop_surface_index": 1})
    assert data.get("ok") is True


def test_tool_n_object_kwarg():
    data = _invoke({"surfaces": _SINGLET, "stop_diameter_mm": 8.0, "n_object": 1.0})
    assert data.get("ok") is True
    assert data["magnification"] == pytest.approx(1.0, abs=1e-9)
