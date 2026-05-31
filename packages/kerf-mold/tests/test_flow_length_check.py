"""
Tests for kerf_mold.flow_length_check — L/T ratio short-shot risk checker.

Oracle coverage (Beaumont 2007 §4 Table 4.2 + Menges 2001 §6.2.1):

  1.  PP  1mm wall × 300mm flow → L/T=300, limit=300 → utilisation=1.00 → caution
       (exactly at limit, not > limit → caution, not short_shot)
  2.  ABS 1mm wall × 200mm flow → L/T=200, limit=150 → utilisation>1.0 → short_shot
  3.  PC  2mm wall × 200mm flow → L/T=100, limit=220 → utilisation≈0.45 → safe
  4.  PA66 1.5mm wall × 200mm flow → L/T≈133, limit=250 → utilisation≈0.53 → safe
  5.  POM 2mm wall × 380mm flow → L/T=190, limit=200 → utilisation=0.95 → caution
  6.  PMMA 2mm wall × 400mm flow → L/T=200, limit=180 → utilisation>1.0 → short_shot
  7.  PP 2mm wall × 480mm flow → L/T=240, limit=300 → utilisation=0.80 →
       boundary: 80 % exactly → safe (≤ threshold)
  8.  PP 2mm wall × 481mm flow → L/T=240.5, limit=300 → utilisation>0.80 → caution
  9.  recommended_min_thickness_mm = flow_length / (limit × 0.85):
       ABS 300mm flow → limit=150 → rec = 300/(150×0.85) = 300/127.5 ≈ 2.3529mm
  10. worst_feature_id reflects the feature with the highest utilisation fraction.
  11. Multiple features: worst is correctly identified among mixed safe/caution/short_shot.
  12. material_db_override adds a new grade (e.g. PEEK=120) and it is used.
  13. FlowFeature rejects zero wall_thickness_mm with ValueError.
  14. FlowFeature rejects negative flow_length_mm with ValueError.
  15. compute_flow_length_check raises ValueError on empty features list.
  16. compute_flow_length_check raises ValueError on unknown material_grade.
  17. LLM tool run_mold_check_flow_length: valid PP 1mm/300mm → caution, ok=True.
  18. LLM tool: missing 'features' key → BAD_ARGS error.
  19. LLM tool: invalid JSON → BAD_ARGS error.
  20. MATERIAL_LT_LIMITS contains the six required materials with correct values.
  21. case-insensitive material lookup: "abs" and "ABS" both work.
  22. PC 2mm × 440mm → L/T=220, limit=220 → utilisation=1.00 → caution (exact boundary)
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_mold.flow_length_check import (
    MATERIAL_LT_LIMITS,
    FlowFeature,
    FlowLengthReport,
    compute_flow_length_check,
)
from kerf_mold.flow_length_check_tool import (
    run_mold_check_flow_length,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _one(material: str, flow_mm: float, wall_mm: float, fid: str = "f1") -> FlowFeature:
    return FlowFeature(id=fid, flow_length_mm=flow_mm, wall_thickness_mm=wall_mm,
                       material_grade=material)


def _run_tool(payload: dict) -> dict:
    raw = json.dumps(payload).encode()
    result = asyncio.run(run_mold_check_flow_length(None, raw))
    return json.loads(result)


# ---------------------------------------------------------------------------
# 1. PP 1mm × 300mm → L/T=300, limit=300 → caution (exactly at limit)
# ---------------------------------------------------------------------------

def test_pp_1mm_300mm_caution():
    report = compute_flow_length_check([_one("PP", 300.0, 1.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(300.0)
    assert r["material_lt_limit"] == 300.0
    assert r["utilisation_fraction"] == pytest.approx(1.0)
    assert r["risk"] == "caution"


# ---------------------------------------------------------------------------
# 2. ABS 1mm × 200mm → L/T=200, limit=150 → short_shot
# ---------------------------------------------------------------------------

def test_abs_1mm_200mm_short_shot():
    report = compute_flow_length_check([_one("ABS", 200.0, 1.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(200.0)
    assert r["material_lt_limit"] == 150.0
    assert r["utilisation_fraction"] == pytest.approx(200.0 / 150.0)
    assert r["risk"] == "short_shot"


# ---------------------------------------------------------------------------
# 3. PC 2mm × 200mm → L/T=100, limit=220 → safe
# ---------------------------------------------------------------------------

def test_pc_2mm_200mm_safe():
    report = compute_flow_length_check([_one("PC", 200.0, 2.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(100.0)
    assert r["material_lt_limit"] == 220.0
    # utilisation stored rounded to 6 decimal places; compare with abs tolerance
    assert r["utilisation_fraction"] == pytest.approx(100.0 / 220.0, abs=1e-4)
    assert r["risk"] == "safe"


# ---------------------------------------------------------------------------
# 4. PA66 1.5mm × 200mm → L/T≈133.3, limit=250 → safe
# ---------------------------------------------------------------------------

def test_pa66_safe():
    report = compute_flow_length_check([_one("PA66", 200.0, 1.5)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(200.0 / 1.5, rel=1e-4)
    assert r["material_lt_limit"] == 250.0
    assert r["risk"] == "safe"


# ---------------------------------------------------------------------------
# 5. POM 2mm × 380mm → L/T=190, limit=200 → caution (95%)
# ---------------------------------------------------------------------------

def test_pom_caution():
    report = compute_flow_length_check([_one("POM", 380.0, 2.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(190.0)
    assert r["material_lt_limit"] == 200.0
    assert r["utilisation_fraction"] == pytest.approx(0.95)
    assert r["risk"] == "caution"


# ---------------------------------------------------------------------------
# 6. PMMA 2mm × 400mm → L/T=200, limit=180 → short_shot
# ---------------------------------------------------------------------------

def test_pmma_short_shot():
    report = compute_flow_length_check([_one("PMMA", 400.0, 2.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(200.0)
    assert r["material_lt_limit"] == 180.0
    assert r["risk"] == "short_shot"


# ---------------------------------------------------------------------------
# 7. PP 2mm × 480mm → L/T=240, utilisation=0.80 → safe (at boundary)
# ---------------------------------------------------------------------------

def test_pp_safe_at_80pct_boundary():
    report = compute_flow_length_check([_one("PP", 480.0, 2.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(240.0)
    assert r["utilisation_fraction"] == pytest.approx(240.0 / 300.0)
    assert r["risk"] == "safe"


# ---------------------------------------------------------------------------
# 8. PP 2mm × 481mm → L/T=240.5, utilisation=0.8017 → caution
# ---------------------------------------------------------------------------

def test_pp_caution_just_above_80pct():
    report = compute_flow_length_check([_one("PP", 481.0, 2.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(240.5)
    utilisation = 240.5 / 300.0
    assert utilisation > 0.80
    assert r["risk"] == "caution"


# ---------------------------------------------------------------------------
# 9. recommended_min_thickness_mm = flow / (limit × 0.85)
# ---------------------------------------------------------------------------

def test_recommended_min_thickness_abs():
    report = compute_flow_length_check([_one("ABS", 300.0, 1.0)])
    expected = 300.0 / (150.0 * 0.85)
    # rounded to 4 decimal places in output; compare with abs tolerance
    assert report.recommended_min_thickness_mm == pytest.approx(expected, abs=1e-3)


def test_recommended_min_thickness_pp():
    report = compute_flow_length_check([_one("PP", 600.0, 2.0)])
    expected = 600.0 / (300.0 * 0.85)
    assert report.recommended_min_thickness_mm == pytest.approx(expected, abs=1e-3)


# ---------------------------------------------------------------------------
# 10. worst_feature_id picks the highest utilisation feature
# ---------------------------------------------------------------------------

def test_worst_feature_id():
    features = [
        FlowFeature(id="safe_rib", flow_length_mm=100.0, wall_thickness_mm=2.0, material_grade="ABS"),
        FlowFeature(id="bad_wall", flow_length_mm=200.0, wall_thickness_mm=1.0, material_grade="ABS"),
        FlowFeature(id="ok_boss", flow_length_mm=50.0,  wall_thickness_mm=2.0, material_grade="ABS"),
    ]
    # Utilisation: safe_rib=100/(2×150)=0.333, bad_wall=200/(1×150)=1.333, ok_boss=50/(2×150)=0.167
    report = compute_flow_length_check(features)
    assert report.worst_feature_id == "bad_wall"


# ---------------------------------------------------------------------------
# 11. Multiple features: mixed risk levels, correct worst identification
# ---------------------------------------------------------------------------

def test_multi_feature_mixed_risk():
    features = [
        FlowFeature(id="f1", flow_length_mm=100.0, wall_thickness_mm=3.0, material_grade="PC"),   # safe
        FlowFeature(id="f2", flow_length_mm=400.0, wall_thickness_mm=2.0, material_grade="PC"),   # caution
        FlowFeature(id="f3", flow_length_mm=500.0, wall_thickness_mm=2.0, material_grade="PC"),   # short_shot
    ]
    report = compute_flow_length_check(features)
    by_id = {r["id"]: r for r in report.feature_results}
    assert by_id["f1"]["risk"] == "safe"
    assert by_id["f2"]["risk"] == "caution"   # L/T=200, util=200/220=0.909
    assert by_id["f3"]["risk"] == "short_shot"  # L/T=250, util=250/220>1
    assert report.worst_feature_id == "f3"


# ---------------------------------------------------------------------------
# 12. material_db_override adds new grade
# ---------------------------------------------------------------------------

def test_material_db_override():
    override = {"PEEK": 120.0}
    features = [FlowFeature(id="peek_wall", flow_length_mm=200.0, wall_thickness_mm=1.0,
                             material_grade="PEEK")]
    report = compute_flow_length_check(features, material_db_override=override)
    r = report.feature_results[0]
    assert r["material_lt_limit"] == 120.0
    assert r["lt_ratio"] == pytest.approx(200.0)
    assert r["risk"] == "short_shot"


# ---------------------------------------------------------------------------
# 13. FlowFeature rejects zero wall_thickness_mm
# ---------------------------------------------------------------------------

def test_flow_feature_zero_wall_raises():
    with pytest.raises(ValueError, match="wall_thickness_mm must be > 0"):
        FlowFeature(id="x", flow_length_mm=100.0, wall_thickness_mm=0.0, material_grade="ABS")


# ---------------------------------------------------------------------------
# 14. FlowFeature rejects negative flow_length_mm
# ---------------------------------------------------------------------------

def test_flow_feature_negative_flow_raises():
    with pytest.raises(ValueError, match="flow_length_mm must be > 0"):
        FlowFeature(id="x", flow_length_mm=-50.0, wall_thickness_mm=2.0, material_grade="ABS")


# ---------------------------------------------------------------------------
# 15. compute_flow_length_check raises on empty list
# ---------------------------------------------------------------------------

def test_empty_features_raises():
    with pytest.raises(ValueError, match="non-empty"):
        compute_flow_length_check([])


# ---------------------------------------------------------------------------
# 16. Unknown material raises ValueError
# ---------------------------------------------------------------------------

def test_unknown_material_raises():
    with pytest.raises(ValueError, match="unknown material_grade"):
        compute_flow_length_check([_one("UNOBTAINIUM", 100.0, 2.0)])


# ---------------------------------------------------------------------------
# 17. LLM tool — PP 1mm × 300mm → caution, ok=True
# ---------------------------------------------------------------------------

def test_llm_tool_pp_caution():
    payload = {
        "features": [
            {"id": "wall_01", "flow_length_mm": 300.0, "wall_thickness_mm": 1.0,
             "material_grade": "PP"}
        ]
    }
    result = _run_tool(payload)
    assert result.get("ok") is True
    assert len(result["feature_results"]) == 1
    r = result["feature_results"][0]
    assert r["risk"] == "caution"
    assert r["lt_ratio"] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# 18. LLM tool: missing 'features' → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_features():
    result = _run_tool({})
    assert "error" in result or result.get("ok") is False or "code" in result


# ---------------------------------------------------------------------------
# 19. LLM tool: invalid JSON → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_invalid_json():
    raw = b"not-valid-json"
    result = json.loads(asyncio.run(run_mold_check_flow_length(None, raw)))
    assert "error" in result or "code" in result


# ---------------------------------------------------------------------------
# 20. MATERIAL_LT_LIMITS contains the six required materials
# ---------------------------------------------------------------------------

def test_material_lt_limits_contents():
    expected = {"ABS": 150.0, "PC": 220.0, "PP": 300.0, "PA66": 250.0,
                "POM": 200.0, "PMMA": 180.0}
    for grade, limit in expected.items():
        assert grade in MATERIAL_LT_LIMITS, f"{grade} missing from MATERIAL_LT_LIMITS"
        assert MATERIAL_LT_LIMITS[grade] == limit, (
            f"{grade} limit: expected {limit}, got {MATERIAL_LT_LIMITS[grade]}"
        )


# ---------------------------------------------------------------------------
# 21. Case-insensitive material lookup
# ---------------------------------------------------------------------------

def test_case_insensitive_material():
    lower = compute_flow_length_check([_one("abs", 100.0, 2.0)])
    upper = compute_flow_length_check([_one("ABS", 100.0, 2.0)])
    assert lower.feature_results[0]["risk"] == upper.feature_results[0]["risk"]
    assert lower.feature_results[0]["material_grade"] == "ABS"


# ---------------------------------------------------------------------------
# 22. PC 2mm × 440mm → L/T=220, limit=220 → caution (exact limit boundary)
# ---------------------------------------------------------------------------

def test_pc_exact_limit_boundary_caution():
    report = compute_flow_length_check([_one("PC", 440.0, 2.0)])
    r = report.feature_results[0]
    assert r["lt_ratio"] == pytest.approx(220.0)
    assert r["utilisation_fraction"] == pytest.approx(1.0)
    assert r["risk"] == "caution"
