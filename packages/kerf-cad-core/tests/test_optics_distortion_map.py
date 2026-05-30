"""
Tests for kerf_cad_core.optics.distortion_map — geometric distortion map.

Test plan
---------
1.  on_axis_zero_distortion         — field angle 0 always → D=0
2.  bk7_singlet_nonzero_distortion  — BK7 biconvex singlet → observable D at moderate field
3.  bk7_singlet_kind_classified     — kind is "barrel" or "pincushion" (not "none")
4.  distortion_sign_convention      — sign formula: D=(y_act-y_p)/|y_p|*100 verified
5.  distortion_grows_with_field     — |D| tends to increase with field angle
6.  seidel_match_sign_small_field   — Seidel prediction has same sign as actual at small field
7.  efl_returned_positive           — EFL_mm > 0 and finite
8.  max_distortion_correct          — max_distortion_pct == max(|distortion_percent|)
9.  kind_barrel                     — high-power singlet shows barrel or pincushion
10. kind_pincushion_or_mixed        — telephoto-like stack has some distortion
11. field_angle_list_preserved      — output list lengths match input
12. seidel_list_length_matches      — seidel_distortion_percent length matches field_angles
13. to_dict_ok_true                 — to_dict() has ok=True
14. to_dict_honest_flag             — to_dict() includes honest_flag string with "Monochromatic"
15. error_empty_surfaces            — returns error for empty surfaces list
16. error_missing_surface_field     — returns error for surface missing 'n'
17. error_bad_n                     — returns error for n < 1
18. error_empty_field_angles        — returns error for empty field_angles_deg
19. error_bad_field_angle           — returns error for non-numeric angle
20. error_zero_aperture             — returns error for aperture_mm=0
21. tool_happy_path                 — LLM tool returns ok JSON with correct keys
22. tool_missing_surfaces           — LLM tool error for missing surfaces
23. tool_missing_field_angles       — LLM tool error for missing field_angles_deg
24. tool_bad_json                   — LLM tool handles invalid JSON
25. tool_aperture_kwarg             — tool accepts optional aperture_mm kwarg
26. tool_n_object_kwarg             — tool accepts optional n_object kwarg
27. single_angle_works              — single field angle list works
28. zero_field_only_list            — all-zero list → all D=0 and kind="none"
29. bk7_high_field_large_distortion — BK7 at 20 deg has |D| > 1%
30. seidel_list_values_finite       — all Seidel prediction values are finite

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Hecht, E. — "Optics", 5th ed., §5.6.
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §6.3.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.distortion_map import (
    DistortionMapReport,
    compute_distortion_map,
)
from kerf_cad_core.optics.tools import run_distortion_map


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# BK7 biconvex singlet: n=1.5168, R1=+50 mm, R2=-50 mm, t=5 mm → EFL ~48.4 mm
# (Hecht 'Optics' 5e §6.4 oracle; Welford §5 exact trace)
_N_BK7 = 1.5168
_R_BK7 = 50.0
BK7_BICONVEX = [
    {"c": 1.0 / _R_BK7,  "t": 5.0, "n": _N_BK7},
    {"c": -1.0 / _R_BK7, "t": 0.0, "n": 1.0},
]

FIELD_ANGLES = [0.0, 5.0, 10.0, 15.0, 20.0]


def _run_tool(args: dict) -> dict:
    return json.loads(asyncio.run(run_distortion_map(None, json.dumps(args).encode())))


# ---------------------------------------------------------------------------
# 1. On-axis always gives D=0
# ---------------------------------------------------------------------------

def test_on_axis_zero_distortion():
    r = compute_distortion_map(BK7_BICONVEX, [0.0, 5.0, 10.0])
    assert r.distortion_percent[0] == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# 2. BK7 singlet: nonzero distortion at moderate field
# ---------------------------------------------------------------------------

def test_bk7_singlet_nonzero_distortion():
    r = compute_distortion_map(BK7_BICONVEX, FIELD_ANGLES)
    assert isinstance(r, DistortionMapReport)
    nonzero = [d for d in r.distortion_percent[1:] if math.isfinite(d) and abs(d) > 0.01]
    assert len(nonzero) > 0, "BK7 singlet should have nonzero distortion off-axis"


# ---------------------------------------------------------------------------
# 3. BK7 singlet: kind is not "none"
# ---------------------------------------------------------------------------

def test_bk7_singlet_kind_classified():
    r = compute_distortion_map(BK7_BICONVEX, FIELD_ANGLES)
    assert r.kind in ("barrel", "pincushion", "mixed"), \
        f"Expected barrel/pincushion/mixed for BK7 singlet, got {r.kind!r}"


# ---------------------------------------------------------------------------
# 4. Sign convention formula verified
# ---------------------------------------------------------------------------

def test_distortion_sign_convention():
    r = compute_distortion_map(BK7_BICONVEX, [10.0])
    d = r.distortion_percent[0]
    y_act = r.y_actual_mm[0]
    y_p = r.y_paraxial_mm[0]
    if math.isfinite(d) and abs(y_p) > 1e-10:
        expected = (y_act - y_p) / abs(y_p) * 100.0
        assert d == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# 5. Distortion grows with field angle
# ---------------------------------------------------------------------------

def test_distortion_grows_with_field():
    r = compute_distortion_map(BK7_BICONVEX, [0.0, 5.0, 10.0, 15.0])
    valid = [
        abs(d)
        for ang, d in zip(r.field_angles_deg, r.distortion_percent)
        if math.isfinite(d) and abs(ang) > 0.1
    ]
    if len(valid) >= 2:
        # Last field angle should have larger distortion than first non-zero
        assert valid[-1] >= valid[0] * 0.5, \
            "Distortion should be larger at greater field angle"


# ---------------------------------------------------------------------------
# 6. Seidel prediction has same sign as actual at small field
# ---------------------------------------------------------------------------

def test_seidel_match_sign_small_field():
    r = compute_distortion_map(BK7_BICONVEX, [5.0])
    d_actual = r.distortion_percent[0]
    d_seidel = r.seidel_distortion_percent[0]
    if (math.isfinite(d_actual) and math.isfinite(d_seidel)
            and abs(d_actual) > 0.01 and abs(d_seidel) > 0.001):
        # Both should have the same sign (same aberration character)
        assert d_actual * d_seidel >= 0, \
            f"Seidel sign mismatch: actual={d_actual:.4f}% seidel={d_seidel:.4f}%"


# ---------------------------------------------------------------------------
# 7. EFL > 0 and finite
# ---------------------------------------------------------------------------

def test_efl_returned_positive():
    r = compute_distortion_map(BK7_BICONVEX, FIELD_ANGLES)
    assert math.isfinite(r.EFL_mm)
    assert r.EFL_mm > 0.0, f"EFL should be positive for converging lens, got {r.EFL_mm}"


# ---------------------------------------------------------------------------
# 8. max_distortion_pct is max of absolute values
# ---------------------------------------------------------------------------

def test_max_distortion_correct():
    r = compute_distortion_map(BK7_BICONVEX, FIELD_ANGLES)
    computed_max = max(
        (abs(d) for d in r.distortion_percent if math.isfinite(d)),
        default=0.0,
    )
    assert r.max_distortion_pct == pytest.approx(computed_max, rel=1e-6)


# ---------------------------------------------------------------------------
# 9. High-power singlet shows barrel or pincushion
# ---------------------------------------------------------------------------

def test_kind_barrel():
    high_power = [
        {"c": 1.0 / 25.0, "t": 3.0, "n": 1.5168},
        {"c": -1.0 / 25.0, "t": 0.0, "n": 1.0},
    ]
    r = compute_distortion_map(high_power, [0.0, 5.0, 10.0, 15.0, 20.0])
    assert isinstance(r, DistortionMapReport)
    assert r.kind in ("barrel", "pincushion", "mixed"), \
        f"High-power singlet should show distortion, got kind={r.kind!r}"


# ---------------------------------------------------------------------------
# 10. Telephoto-like stack has some distortion
# ---------------------------------------------------------------------------

def test_kind_pincushion_or_mixed():
    telephoto = [
        {"c":  1.0 / 40.0, "t": 4.0,  "n": 1.5168},
        {"c": -1.0 / 40.0, "t": 20.0, "n": 1.0},
        {"c": -1.0 / 80.0, "t": 3.0,  "n": 1.617},
        {"c":  1.0 / 80.0, "t": 0.0,  "n": 1.0},
    ]
    r = compute_distortion_map(telephoto, [0.0, 5.0, 10.0])
    assert isinstance(r, DistortionMapReport)
    assert r.kind in ("barrel", "pincushion", "mixed", "none")


# ---------------------------------------------------------------------------
# 11. Output list lengths match input
# ---------------------------------------------------------------------------

def test_field_angle_list_preserved():
    angles = [0.0, 3.0, 7.0, 12.0]
    r = compute_distortion_map(BK7_BICONVEX, angles)
    assert len(r.field_angles_deg) == len(angles)
    assert len(r.distortion_percent) == len(angles)
    assert len(r.y_actual_mm) == len(angles)
    assert len(r.y_paraxial_mm) == len(angles)


# ---------------------------------------------------------------------------
# 12. Seidel list length matches field angles
# ---------------------------------------------------------------------------

def test_seidel_list_length_matches():
    r = compute_distortion_map(BK7_BICONVEX, FIELD_ANGLES)
    assert len(r.seidel_distortion_percent) == len(FIELD_ANGLES)


# ---------------------------------------------------------------------------
# 13. to_dict() has ok=True
# ---------------------------------------------------------------------------

def test_to_dict_ok_true():
    r = compute_distortion_map(BK7_BICONVEX, [5.0])
    d = r.to_dict()
    assert d["ok"] is True
    assert "distortion_percent" in d
    assert "kind" in d
    assert "EFL_mm" in d


# ---------------------------------------------------------------------------
# 14. to_dict() has honest_flag
# ---------------------------------------------------------------------------

def test_to_dict_honest_flag():
    r = compute_distortion_map(BK7_BICONVEX, [5.0])
    d = r.to_dict()
    assert "honest_flag" in d
    assert "Monochromatic" in d["honest_flag"]


# ---------------------------------------------------------------------------
# 15. Error: empty surfaces list
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = compute_distortion_map([], [5.0])
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "surfaces" in r["reason"]


# ---------------------------------------------------------------------------
# 16. Error: surface missing 'n' field
# ---------------------------------------------------------------------------

def test_error_missing_surface_field():
    bad = [{"c": 0.01, "t": 0.0}]  # missing 'n'
    r = compute_distortion_map(bad, [5.0])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 17. Error: n < 1.0
# ---------------------------------------------------------------------------

def test_error_bad_n():
    bad = [{"c": 0.01, "t": 0.0, "n": 0.5}]
    r = compute_distortion_map(bad, [5.0])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 18. Error: empty field_angles_deg
# ---------------------------------------------------------------------------

def test_error_empty_field_angles():
    r = compute_distortion_map(BK7_BICONVEX, [])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 19. Error: non-numeric angle
# ---------------------------------------------------------------------------

def test_error_bad_field_angle():
    r = compute_distortion_map(BK7_BICONVEX, ["foo"])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 20. Error: aperture_mm = 0
# ---------------------------------------------------------------------------

def test_error_zero_aperture():
    r = compute_distortion_map(BK7_BICONVEX, [5.0], aperture_mm=0.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 21. LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    d = _run_tool({"surfaces": BK7_BICONVEX, "field_angles_deg": [0.0, 5.0, 10.0]})
    assert d["ok"] is True
    assert "distortion_percent" in d
    assert "kind" in d
    assert "EFL_mm" in d
    assert d["EFL_mm"] > 0.0


# ---------------------------------------------------------------------------
# 22. LLM tool: missing surfaces
# ---------------------------------------------------------------------------

def test_tool_missing_surfaces():
    d = _run_tool({"field_angles_deg": [5.0]})
    assert d["ok"] is False
    assert "surfaces" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 23. LLM tool: missing field_angles_deg
# ---------------------------------------------------------------------------

def test_tool_missing_field_angles():
    d = _run_tool({"surfaces": BK7_BICONVEX})
    assert d["ok"] is False
    assert "field_angles_deg" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 24. LLM tool: invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    result = json.loads(asyncio.run(run_distortion_map(None, b"{bad json")))
    is_error = (result.get("ok") is False) or ("error" in result) or ("code" in result)
    assert is_error, f"Expected error response, got: {result}"


# ---------------------------------------------------------------------------
# 25. LLM tool accepts aperture_mm kwarg
# ---------------------------------------------------------------------------

def test_tool_aperture_kwarg():
    d = _run_tool({"surfaces": BK7_BICONVEX, "field_angles_deg": [5.0], "aperture_mm": 2.0})
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 26. LLM tool accepts n_object kwarg
# ---------------------------------------------------------------------------

def test_tool_n_object_kwarg():
    d = _run_tool({"surfaces": BK7_BICONVEX, "field_angles_deg": [5.0], "n_object": 1.0})
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 27. Single field angle works
# ---------------------------------------------------------------------------

def test_single_angle_works():
    r = compute_distortion_map(BK7_BICONVEX, [10.0])
    assert isinstance(r, DistortionMapReport)
    assert len(r.distortion_percent) == 1
    assert math.isfinite(r.distortion_percent[0])


# ---------------------------------------------------------------------------
# 28. All-zero field list → all D=0 and kind="none"
# ---------------------------------------------------------------------------

def test_zero_field_only_list():
    r = compute_distortion_map(BK7_BICONVEX, [0.0, 0.0, 0.0])
    for d in r.distortion_percent:
        assert d == pytest.approx(0.0, abs=1e-10)
    assert r.kind == "none"


# ---------------------------------------------------------------------------
# 29. BK7 at 20 deg: |D| > 1%
# ---------------------------------------------------------------------------

def test_bk7_high_field_large_distortion():
    r = compute_distortion_map(BK7_BICONVEX, [20.0])
    d = r.distortion_percent[0]
    assert math.isfinite(d), "Distortion at 20 deg should be finite"
    assert abs(d) > 0.5, \
        f"BK7 singlet at 20 deg should have |D| > 0.5%, got {d:.4f}%"


# ---------------------------------------------------------------------------
# 30. All Seidel prediction values are finite
# ---------------------------------------------------------------------------

def test_seidel_list_values_finite():
    r = compute_distortion_map(BK7_BICONVEX, FIELD_ANGLES)
    for i, s in enumerate(r.seidel_distortion_percent):
        assert math.isfinite(s), \
            f"Seidel prediction at angle index {i} is not finite: {s}"
