"""
Tests for kerf_cad_core.optics.fno_working — OPTICS-FNO-WORKING.

Test plan
---------
Physics / formula verification:
 1. infinity_focus_no_penalty     — m=0: N_w=N, loss=0, factor=1.0
 2. one_to_one_macro_f4           — f/4 at m=-1: N_w=8.0, loss=2 stops, factor=0.25
 3. half_life_size_f28            — f/2.8 at m=-0.5: N_w=4.2, loss≈1.17 stops
 4. two_to_one_magnification      — f/4 at m=-2: N_w=12.0, loss≈3.17 stops
 5. tenth_life_size               — f/4 at m=-0.1: N_w=4.4, small loss
 6. positive_magnification        — m=+0.5 (virtual image path): |m| still used → N_w=N*1.5
 7. irradiance_factor_unity_infinity — m=0 → factor=1.0
 8. irradiance_factor_quarter_macro  — m=-1 → factor=0.25 exactly
 9. irradiance_factor_formula     — (N/N_w)² == factor for arbitrary m
10. loss_stops_formula            — 2*log2(1+|m|) consistency check
11. loss_and_factor_consistency   — 2^(-loss) == factor (energy conservation check)
12. working_fno_faster_than_nominal — N_w >= N always (equality at m=0)
13. high_magnification            — f/2 at m=-4: N_w=10, loss=log2(25) stops

Dataclass / API tests:
14. spec_fields_stored            — FnoWorkingSpec stores both fields correctly
15. report_to_dict_ok_key         — .to_dict() has ok=True
16. report_to_dict_all_keys       — all expected keys present in dict
17. report_honest_caveat_present  — honest_caveat contains key keywords

Error / validation tests:
18. error_zero_f_number           — raises ValueError for N=0
19. error_negative_f_number       — raises ValueError for N<0

LLM tool tests:
20. tool_infinity_focus           — LLM tool returns ok JSON for m=0
21. tool_macro_1to1               — LLM tool: f/4, m=-1 → working_fno=8.0
22. tool_missing_nominal_f_number — LLM tool: missing required field → error
23. tool_missing_magnification    — LLM tool: missing required field → error
24. tool_bad_json                 — LLM tool: invalid JSON → error
25. tool_positive_magnification   — LLM tool: m=+0.5 → ok (absolute value)
26. tool_zero_magnification       — LLM tool: m=0.0 → loss=0
27. tool_loss_stops_positive      — loss_stops >= 0 for any m
28. tool_irradiance_factor_le1    — image_irradiance_factor in (0, 1] for any m

Total: 28 tests (well above 12 minimum).

References
----------
Hecht, E. — "Optics", 5th ed. (2017), §6.4.
Smith, W.J. — "Modern Optical Engineering", 4th ed. (2008), §4.5.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.fno_working import (
    FnoWorkingReport,
    FnoWorkingSpec,
    compute_working_fno,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute(N: float, m: float) -> FnoWorkingReport:
    return compute_working_fno(FnoWorkingSpec(nominal_f_number=N, magnification=m))


# ---------------------------------------------------------------------------
# Physics / formula verification
# ---------------------------------------------------------------------------

def test_infinity_focus_no_penalty():
    """m=0 (infinity focus): N_w == N, loss == 0, factor == 1.0."""
    r = _compute(4.0, 0.0)
    assert isinstance(r, FnoWorkingReport)
    assert math.isclose(r.working_f_number, 4.0, rel_tol=1e-9)
    assert math.isclose(r.exposure_loss_stops, 0.0, abs_tol=1e-12)
    assert math.isclose(r.image_irradiance_factor, 1.0, rel_tol=1e-9)


def test_one_to_one_macro_f4():
    """f/4 at 1:1 macro (m=-1): N_w = 8.0, loss = 2 stops, factor = 0.25."""
    r = _compute(4.0, -1.0)
    assert isinstance(r, FnoWorkingReport)
    assert math.isclose(r.working_f_number, 8.0, rel_tol=1e-9)
    assert math.isclose(r.exposure_loss_stops, 2.0, rel_tol=1e-9)
    assert math.isclose(r.image_irradiance_factor, 0.25, rel_tol=1e-9)


def test_half_life_size_f28():
    """f/2.8 at 1:2 (m=-0.5): N_w = 4.2, loss ≈ 1.170 stops."""
    r = _compute(2.8, -0.5)
    assert isinstance(r, FnoWorkingReport)
    assert math.isclose(r.working_f_number, 4.2, rel_tol=1e-9)
    # loss = 2 * log2(1.5) ≈ 2 * 0.58496... ≈ 1.16993...
    expected_loss = 2.0 * math.log2(1.5)
    assert math.isclose(r.exposure_loss_stops, expected_loss, rel_tol=1e-9)
    # 1.17 stops rounded to 2 d.p.
    assert abs(r.exposure_loss_stops - 1.17) < 0.005


def test_two_to_one_magnification():
    """f/4 at 2:1 (m=-2): N_w = 12.0, loss = 2*log2(3) ≈ 3.170 stops."""
    r = _compute(4.0, -2.0)
    assert isinstance(r, FnoWorkingReport)
    assert math.isclose(r.working_f_number, 12.0, rel_tol=1e-9)
    expected_loss = 2.0 * math.log2(3.0)
    assert math.isclose(r.exposure_loss_stops, expected_loss, rel_tol=1e-9)


def test_tenth_life_size():
    """f/4 at 1:10 (m=-0.1): N_w = 4.4, small but nonzero loss."""
    r = _compute(4.0, -0.1)
    assert isinstance(r, FnoWorkingReport)
    assert math.isclose(r.working_f_number, 4.4, rel_tol=1e-9)
    assert r.exposure_loss_stops > 0.0
    assert r.exposure_loss_stops < 0.5  # small penalty at 1:10


def test_positive_magnification():
    """m=+0.5 (virtual image, e.g. loupe at less than focal length):
    |m|=0.5, so N_w = N * 1.5 — same penalty as m=-0.5."""
    r_pos = _compute(4.0, 0.5)
    r_neg = _compute(4.0, -0.5)
    assert math.isclose(r_pos.working_f_number, r_neg.working_f_number, rel_tol=1e-9)
    assert math.isclose(r_pos.exposure_loss_stops, r_neg.exposure_loss_stops, rel_tol=1e-9)


def test_irradiance_factor_unity_infinity():
    """m=0 → image_irradiance_factor = 1.0 (no light loss)."""
    r = _compute(2.8, 0.0)
    assert math.isclose(r.image_irradiance_factor, 1.0, rel_tol=1e-9)


def test_irradiance_factor_quarter_macro():
    """m=-1 (1:1 macro) → image_irradiance_factor = 0.25 (quarter the irradiance)."""
    r = _compute(8.0, -1.0)  # any N should give 0.25
    assert math.isclose(r.image_irradiance_factor, 0.25, rel_tol=1e-9)


def test_irradiance_factor_formula():
    """image_irradiance_factor = (N/N_w)² for arbitrary m."""
    r = _compute(5.6, -0.3)
    expected = (r.nominal_f_number / r.working_f_number) ** 2
    assert math.isclose(r.image_irradiance_factor, expected, rel_tol=1e-9)


def test_loss_stops_formula():
    """exposure_loss_stops = 2 * log2(1 + |m|) for arbitrary m."""
    for m in [-0.1, -0.5, -1.0, -2.0, 0.7]:
        r = _compute(4.0, m)
        expected = 2.0 * math.log2(1.0 + abs(m))
        assert math.isclose(r.exposure_loss_stops, expected, rel_tol=1e-9), (
            f"m={m}: got {r.exposure_loss_stops}, expected {expected}"
        )


def test_loss_and_factor_consistency():
    """2^(-loss_stops) == image_irradiance_factor (energy conservation link)."""
    for m in [0.0, -0.25, -0.5, -1.0, -2.0]:
        r = _compute(4.0, m)
        # factor = (N/N_w)^2 = 1/(1+|m|)^2
        # loss = 2*log2(1+|m|)  → 2^loss = (1+|m|)^2 → 2^(-loss) = factor
        assert math.isclose(
            2.0 ** (-r.exposure_loss_stops),
            r.image_irradiance_factor,
            rel_tol=1e-9,
        ), f"m={m}"


def test_working_fno_faster_than_nominal():
    """N_w >= N for all m (working f-number is always >= nominal)."""
    for m in [0.0, -0.01, -0.1, -0.5, -1.0, -2.0, 0.5]:
        r = _compute(4.0, m)
        assert r.working_f_number >= r.nominal_f_number - 1e-12, f"m={m}"


def test_high_magnification():
    """f/2 at 4:1 (m=-4): N_w = 10.0, loss = 2*log2(5) ≈ 4.644 stops."""
    r = _compute(2.0, -4.0)
    assert math.isclose(r.working_f_number, 10.0, rel_tol=1e-9)
    expected_loss = 2.0 * math.log2(5.0)
    assert math.isclose(r.exposure_loss_stops, expected_loss, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Dataclass / API tests
# ---------------------------------------------------------------------------

def test_spec_fields_stored():
    """FnoWorkingSpec stores fields correctly."""
    spec = FnoWorkingSpec(nominal_f_number=4.0, magnification=-1.0)
    assert spec.nominal_f_number == 4.0
    assert spec.magnification == -1.0


def test_report_to_dict_ok_key():
    """to_dict() returns ok=True."""
    r = _compute(4.0, -1.0)
    assert r.to_dict().get("ok") is True


def test_report_to_dict_all_keys():
    """to_dict() contains all expected output keys."""
    r = _compute(4.0, -1.0)
    d = r.to_dict()
    for key in (
        "ok",
        "nominal_f_number",
        "working_f_number",
        "exposure_loss_stops",
        "image_irradiance_factor",
        "honest_caveat",
    ):
        assert key in d, f"missing key: {key!r}"


def test_report_honest_caveat_present():
    """honest_caveat mentions the thin-lens approximation and pupil."""
    r = _compute(4.0, -1.0)
    caveat = r.honest_caveat.lower()
    assert "thin-lens" in caveat or "thin lens" in caveat
    assert "pupil" in caveat


# ---------------------------------------------------------------------------
# Error / validation tests
# ---------------------------------------------------------------------------

def test_error_zero_f_number():
    """ValueError raised for nominal_f_number=0."""
    with pytest.raises(ValueError, match="nominal_f_number"):
        _compute(0.0, -1.0)


def test_error_negative_f_number():
    """ValueError raised for nominal_f_number < 0."""
    with pytest.raises(ValueError, match="nominal_f_number"):
        _compute(-2.8, -1.0)


# ---------------------------------------------------------------------------
# LLM tool tests
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.tools import run_compute_working_fno  # noqa: E402


def _invoke(payload: dict) -> dict:
    """Invoke the LLM tool with a dict payload and return parsed JSON."""
    return json.loads(
        asyncio.run(run_compute_working_fno(None, json.dumps(payload).encode()))
    )


def test_tool_infinity_focus():
    """LLM tool: m=0 → ok=True, working_f_number == nominal_f_number."""
    data = _invoke({"nominal_f_number": 4.0, "magnification": 0.0})
    assert data.get("ok") is True
    assert math.isclose(data["working_f_number"], 4.0, rel_tol=1e-9)


def test_tool_macro_1to1():
    """LLM tool: f/4, m=-1 → working_f_number=8.0, loss=2.0 stops."""
    data = _invoke({"nominal_f_number": 4.0, "magnification": -1.0})
    assert data.get("ok") is True
    assert math.isclose(data["working_f_number"], 8.0, rel_tol=1e-9)
    assert math.isclose(data["exposure_loss_stops"], 2.0, rel_tol=1e-9)


def test_tool_missing_nominal_f_number():
    """LLM tool: missing nominal_f_number → error."""
    data = _invoke({"magnification": -1.0})
    assert data.get("ok") is False


def test_tool_missing_magnification():
    """LLM tool: missing magnification → error."""
    data = _invoke({"nominal_f_number": 4.0})
    assert data.get("ok") is False


def test_tool_bad_json():
    """LLM tool: invalid JSON → BAD_ARGS error."""
    data = json.loads(
        asyncio.run(run_compute_working_fno(None, b"not valid json {{"))
    )
    # err_payload returns {"ok": False, "code": "BAD_ARGS", ...} or {"error": ..., "code": ...}
    assert data.get("ok") is False or data.get("code") == "BAD_ARGS" or "error" in data


def test_tool_positive_magnification():
    """LLM tool: m=+0.5 → ok (absolute value used)."""
    data = _invoke({"nominal_f_number": 4.0, "magnification": 0.5})
    assert data.get("ok") is True
    assert math.isclose(data["working_f_number"], 6.0, rel_tol=1e-9)


def test_tool_zero_magnification():
    """LLM tool: m=0.0 → loss=0, factor=1.0."""
    data = _invoke({"nominal_f_number": 5.6, "magnification": 0.0})
    assert data.get("ok") is True
    assert math.isclose(data["exposure_loss_stops"], 0.0, abs_tol=1e-12)
    assert math.isclose(data["image_irradiance_factor"], 1.0, rel_tol=1e-9)


def test_tool_loss_stops_positive():
    """LLM tool: exposure_loss_stops >= 0 for any magnification."""
    for m in [0.0, -0.1, -0.5, -1.0, -2.0, 0.5]:
        data = _invoke({"nominal_f_number": 4.0, "magnification": m})
        assert data.get("ok") is True
        assert data["exposure_loss_stops"] >= -1e-12, f"m={m}"


def test_tool_irradiance_factor_le1():
    """LLM tool: image_irradiance_factor in (0, 1] for any magnification."""
    for m in [0.0, -0.25, -0.5, -1.0, -2.0]:
        data = _invoke({"nominal_f_number": 4.0, "magnification": m})
        assert data.get("ok") is True
        f = data["image_irradiance_factor"]
        assert 0.0 < f <= 1.0 + 1e-12, f"m={m}: factor={f}"
