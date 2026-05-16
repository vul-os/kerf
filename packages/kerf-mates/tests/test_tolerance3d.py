"""
Tests for kerf_mates.tolerance3d -- 3D tolerance / variation analysis.

Coverage (>=25 hermetic tests):
  1-4.   Module imports, dataclass validation, axis normalisation.
  5-8.   FeatureTolerance: half_zone, sigma, projection.
  9-11.  _feature_world_pos: identity, translation, rotation.
  12-14. worst_case3d: single-tol, 3-tol chain, >wc_band>=0.
  15-17. rss3d: single-tol, matches tolerance.py rss formula, contributions sum ~100%.
  18-20. Seeded MC reproducibility; different seeds give different results; sigma converges.
  21-23. MC sigma approx equals RSS sigma for normal linear chains.
  24-25. Contribution analysis: largest tolerance ranked first; tightening dominant reduces sigma.
  26-27. Cpk / Cp / defect-ppm correctness.
  28-29. worst_case >= RSS >= 0 ordering.
  30-31. Uniform distribution MC; zero-tolerance part contributes nothing.
  32.    analyze3d returns combined dict with all three keys.
  33.    _parse_model parses dict correctly.
  34-35. LLM tool round-trip returns ok payload; bad JSON returns error.
"""

import asyncio
import json
import math
import sys

# Add all plugin src/ dirs to path (mirrors the package conftest)
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_HERE)
_PACKAGES_ROOT = os.path.dirname(_PLUGIN_ROOT)
if os.path.basename(_PACKAGES_ROOT) == "packages":
    for _e in os.listdir(_PACKAGES_ROOT):
        if not _e.startswith("kerf-"):
            continue
        _s = os.path.join(_PACKAGES_ROOT, _e, "src")
        if os.path.isdir(_s) and _s not in sys.path:
            sys.path.insert(0, _s)

from kerf_mates.tolerance3d import (
    _LCG,
    _capability,
    _collect_contributions,
    _feature_world_pos,
    _parse_model,
    analyze3d,
    monte_carlo3d,
    rss3d,
    run_tolerance3d_analysis,
    tolerance3d_analysis_spec,
    worst_case3d,
    AssemblyFeature,
    AssemblyModel,
    AssemblyPart,
    FeatureTolerance,
    MateLink,
    VALID_GDNT_TYPES,
)
# Pull in 1-D helpers for cross-check
from kerf_mates.tolerance import rss as rss1d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_1d_model(tol_values: list[float], distribution: str = "normal") -> AssemblyModel:
    """Build a collinear (Z-axis) N-part chain for 1-D equivalence checks."""
    parts = []
    chain = []
    x = 0.0
    for i, val in enumerate(tol_values):
        pid = f"p{i}"
        fid_a = f"f{i}_a"
        fid_b = f"f{i}_b"
        parts.append(AssemblyPart(
            part_id=pid,
            features=[
                AssemblyFeature(
                    feature_id=fid_a,
                    position=(0.0, 0.0, 0.0),
                    tolerances=[
                        FeatureTolerance(
                            tol_id=f"t{i}",
                            tol_type="linear",
                            value=val,
                            distribution=distribution,
                            axis=(0.0, 0.0, 1.0),
                        )
                    ],
                ),
                AssemblyFeature(
                    feature_id=fid_b,
                    position=(0.0, 0.0, val * 10),
                    tolerances=[],
                ),
            ],
            translation=(0.0, 0.0, x),
        ))
        if i > 0:
            chain.append(MateLink(
                link_id=f"link{i}",
                part_a_id=f"p{i-1}",
                feature_a_id=f"f{i-1}_b",
                part_b_id=pid,
                feature_b_id=fid_a,
                meas_dir=(0.0, 0.0, 1.0),
            ))
        x += val * 10
    return AssemblyModel(parts=parts, mate_chain=chain)


def _two_part_model(
    tol_a: float,
    tol_b: float,
    sep: float = 100.0,
    distribution: str = "normal",
) -> AssemblyModel:
    """Simple two-part model with one link along Z."""
    parts = [
        AssemblyPart(
            part_id="A",
            features=[
                AssemblyFeature(
                    feature_id="f_a",
                    position=(0.0, 0.0, 0.0),
                    tolerances=[
                        FeatureTolerance("t_a", "linear", tol_a,
                                         distribution=distribution)
                    ],
                )
            ],
        ),
        AssemblyPart(
            part_id="B",
            features=[
                AssemblyFeature(
                    feature_id="f_b",
                    position=(0.0, 0.0, 0.0),
                    tolerances=[
                        FeatureTolerance("t_b", "linear", tol_b,
                                         distribution=distribution)
                    ],
                )
            ],
            translation=(0.0, 0.0, sep),
        ),
    ]
    chain = [
        MateLink(
            link_id="L1",
            part_a_id="A", feature_a_id="f_a",
            part_b_id="B", feature_b_id="f_b",
            meas_dir=(0.0, 0.0, 1.0),
        )
    ]
    return AssemblyModel(parts=parts, mate_chain=chain)


# ---------------------------------------------------------------------------
# T1. Module imports and VALID_GDNT_TYPES
# ---------------------------------------------------------------------------

def test_valid_gdnt_types():
    assert "position" in VALID_GDNT_TYPES
    assert "flatness" in VALID_GDNT_TYPES
    assert "perpendicularity" in VALID_GDNT_TYPES
    assert "profile" in VALID_GDNT_TYPES
    assert "linear" in VALID_GDNT_TYPES


# ---------------------------------------------------------------------------
# T2. FeatureTolerance validation
# ---------------------------------------------------------------------------

def test_feature_tolerance_negative_value():
    import pytest
    with pytest.raises(ValueError):
        FeatureTolerance("t", "linear", -0.1)


def test_feature_tolerance_bad_type():
    import pytest
    with pytest.raises(ValueError):
        FeatureTolerance("t", "roundness", 0.05)


# ---------------------------------------------------------------------------
# T3. FeatureTolerance axis normalisation
# ---------------------------------------------------------------------------

def test_feature_tolerance_axis_normalised():
    ft = FeatureTolerance("t", "linear", 0.1, axis=(3.0, 4.0, 0.0))
    mag = math.sqrt(ft.axis[0] ** 2 + ft.axis[1] ** 2 + ft.axis[2] ** 2)
    assert abs(mag - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# T4. FeatureTolerance half_zone / sigma
# ---------------------------------------------------------------------------

def test_feature_tolerance_half_zone_and_sigma():
    ft = FeatureTolerance("t", "position", 0.06)
    assert abs(ft.half_zone() - 0.03) < 1e-12
    assert abs(ft.sigma() - 0.01) < 1e-12


# ---------------------------------------------------------------------------
# T5. Projection: parallel axis => 1.0, orthogonal => 0.0
# ---------------------------------------------------------------------------

def test_feature_tolerance_projection_parallel():
    ft = FeatureTolerance("t", "linear", 0.1, axis=(0.0, 0.0, 1.0))
    assert abs(ft.projection((0.0, 0.0, 1.0)) - 1.0) < 1e-10


def test_feature_tolerance_projection_orthogonal():
    ft = FeatureTolerance("t", "flatness", 0.1, axis=(1.0, 0.0, 0.0))
    assert abs(ft.projection((0.0, 0.0, 1.0))) < 1e-10


# ---------------------------------------------------------------------------
# T6. _feature_world_pos -- identity (no translation, no rotation)
# ---------------------------------------------------------------------------

def test_feature_world_pos_identity():
    part = AssemblyPart(part_id="P")
    feat = AssemblyFeature(feature_id="f", position=(1.0, 2.0, 3.0))
    pos = _feature_world_pos(part, feat)
    assert abs(pos[0] - 1.0) < 1e-10
    assert abs(pos[1] - 2.0) < 1e-10
    assert abs(pos[2] - 3.0) < 1e-10


# ---------------------------------------------------------------------------
# T7. _feature_world_pos -- translation only
# ---------------------------------------------------------------------------

def test_feature_world_pos_translation():
    part = AssemblyPart(part_id="P", translation=(10.0, 20.0, 30.0))
    feat = AssemblyFeature(feature_id="f", position=(1.0, 0.0, 0.0))
    pos = _feature_world_pos(part, feat)
    assert abs(pos[0] - 11.0) < 1e-9
    assert abs(pos[1] - 20.0) < 1e-9
    assert abs(pos[2] - 30.0) < 1e-9


# ---------------------------------------------------------------------------
# T8. _feature_world_pos -- 90 deg Rz rotation
# ---------------------------------------------------------------------------

def test_feature_world_pos_rotation_rz_90():
    part = AssemblyPart(part_id="P", rotation_deg=(0.0, 0.0, 90.0))
    feat = AssemblyFeature(feature_id="f", position=(1.0, 0.0, 0.0))
    pos = _feature_world_pos(part, feat)
    # After Rz(90), (1,0,0) -> (0,1,0)
    assert abs(pos[0] - 0.0) < 1e-9
    assert abs(pos[1] - 1.0) < 1e-9
    assert abs(pos[2] - 0.0) < 1e-9


# ---------------------------------------------------------------------------
# T9. worst_case3d -- single tolerance
# ---------------------------------------------------------------------------

def test_worst_case3d_single_tol():
    model = _two_part_model(0.2, 0.0, sep=50.0)
    res = worst_case3d(model)
    assert res["ok"]
    # half_zone of t_a = 0.1, projected onto Z = 1.0
    assert abs(res["wc_band"] - 0.1) < 1e-10
    assert abs(res["max"] - (res["nominal"] + 0.1)) < 1e-10
    assert abs(res["min"] - (res["nominal"] - 0.1)) < 1e-10


# ---------------------------------------------------------------------------
# T10. worst_case3d -- multi-tol chain: band = sum of half-zones
# ---------------------------------------------------------------------------

def test_worst_case3d_multi_tol_sum():
    model = _two_part_model(0.2, 0.4, sep=100.0)
    res = worst_case3d(model)
    assert res["ok"]
    # half-zones: 0.1 + 0.2 = 0.3
    assert abs(res["wc_band"] - 0.3) < 1e-9


# ---------------------------------------------------------------------------
# T11. worst_case3d -- wc_band >= 0
# ---------------------------------------------------------------------------

def test_worst_case3d_band_nonnegative():
    model = _two_part_model(0.05, 0.05)
    res = worst_case3d(model)
    assert res["ok"]
    assert res["wc_band"] >= 0.0


# ---------------------------------------------------------------------------
# T12-T13. rss3d -- single-tol and multi-tol
# ---------------------------------------------------------------------------

def test_rss3d_single_tol():
    model = _two_part_model(0.2, 0.0, sep=50.0)
    res = rss3d(model)
    assert res["ok"]
    # Only t_a contributes: sigma = 0.1/3, rss_band = 3 * 0.1/3 = 0.1
    assert abs(res["rss_band"] - 0.1) < 1e-9


def test_rss3d_multi_tol_formula():
    # Check formula: rss_sigma = sqrt(sum(sigma_i^2)), rss_band = 3 * rss_sigma
    tol_a, tol_b = 0.3, 0.6
    model = _two_part_model(tol_a, tol_b, sep=100.0)
    res = rss3d(model)
    assert res["ok"]
    sig_a = (tol_a / 2) / 3
    sig_b = (tol_b / 2) / 3
    expected_sigma = math.sqrt(sig_a ** 2 + sig_b ** 2)
    expected_band = 3.0 * expected_sigma
    assert abs(res["rss_band"] - expected_band) < 1e-9


# ---------------------------------------------------------------------------
# T14. rss3d contributions sum to ~100%
# ---------------------------------------------------------------------------

def test_rss3d_contributions_sum_to_100():
    model = _two_part_model(0.2, 0.4)
    res = rss3d(model)
    assert res["ok"]
    total_pct = sum(c["variance_contribution_pct"] for c in res["contributions"])
    assert abs(total_pct - 100.0) < 0.01


# ---------------------------------------------------------------------------
# T15. 1-D equivalence: 3D RSS matches tolerance.py rss for linear Z-chain
# ---------------------------------------------------------------------------

def test_rss3d_matches_1d_rss():
    """A Z-axis 3D chain reproduces the 1-D RSS result.

    tolerance.py rss() treats half_span=(plus+minus)/2 as the 1-sigma input:
        rss_band_1d = k * sqrt(sum(half_span_i^2))   [k=3]

    tolerance3d rss3d() uses sigma = half_zone/3 (assumes +/-3sigma = full zone):
        rss_band_3d = 3 * sqrt(sum((half_zone/3)^2))
                    = 3 * sqrt(sum((half_zone^2)/9))
                    = sqrt(sum(half_zone^2))

    To reproduce the same number: set value_3d = 6 * sigma_1d so that
        half_zone_3d = value_3d/2 = 3 * sigma_1d
        sigma_3d     = half_zone_3d/3 = sigma_1d  -- identical 1-sigma

    For a tolerance.py dim with plus=p, minus=p:
        half_span_1d = p  =>  set value_3d = 6*p
    """
    plus_values = [0.1, 0.05, 0.02]  # same as the canonical test_rss case
    # Build 3D model: value = 6 * plus so sigma_3d = plus (matching 1D convention)
    parts = [
        AssemblyPart(
            part_id="A",
            features=[
                AssemblyFeature(
                    feature_id="fa",
                    position=(0.0, 0.0, 0.0),
                    tolerances=[
                        FeatureTolerance(f"t{i}", "linear", 6.0 * p)
                        for i, p in enumerate(plus_values)
                    ],
                )
            ],
        ),
        AssemblyPart(
            part_id="B",
            features=[AssemblyFeature(feature_id="fb")],
            translation=(0.0, 0.0, 17.0),
        ),
    ]
    chain = [
        MateLink("L1", "A", "fa", "B", "fb", meas_dir=(0.0, 0.0, 1.0))
    ]
    model = AssemblyModel(parts=parts, mate_chain=chain)
    res3d = rss3d(model)

    # 1-D reference
    dims1d = [
        {"nominal": 10.0, "plus": plus_values[0], "minus": plus_values[0]},
        {"nominal": 5.0,  "plus": plus_values[1], "minus": plus_values[1]},
        {"nominal": 2.0,  "plus": plus_values[2], "minus": plus_values[2]},
    ]
    res1d = rss1d(dims1d, rss_k=3.0)

    # rss_band_3d = 3 * sqrt(sum(sigma_i^2)) = 3 * sqrt(sum(plus_i^2)) = rss_band_1d
    assert abs(res3d["rss_band"] - res1d["rss_range"] / 2) < 1e-8


# ---------------------------------------------------------------------------
# T16-T17. Seeded MC reproducibility
# ---------------------------------------------------------------------------

def test_mc3d_seeded_reproducible():
    model = _two_part_model(0.3, 0.2)
    r1 = monte_carlo3d(model, samples=500, seed=7)
    r2 = monte_carlo3d(model, samples=500, seed=7)
    assert r1["mean"] == r2["mean"]
    assert r1["sigma"] == r2["sigma"]
    assert r1["p50"] == r2["p50"]


def test_mc3d_different_seeds_differ():
    model = _two_part_model(0.3, 0.2)
    r1 = monte_carlo3d(model, samples=1000, seed=1)
    r2 = monte_carlo3d(model, samples=1000, seed=2)
    # Very unlikely to be identical
    assert r1["mean"] != r2["mean"]


# ---------------------------------------------------------------------------
# T18. MC sigma ~ RSS sigma for normal linear chain (large N)
# ---------------------------------------------------------------------------

def test_mc3d_sigma_approx_rss_sigma():
    """MC sigma should converge to RSS sigma for a normal linear chain."""
    model = _two_part_model(0.3, 0.6)
    mc = monte_carlo3d(model, samples=50000, seed=42)
    rss = rss3d(model)
    assert mc["ok"] and rss["ok"]
    # Allow 5% relative tolerance
    assert abs(mc["sigma"] - rss["rss_sigma"]) / rss["rss_sigma"] < 0.05


# ---------------------------------------------------------------------------
# T19. Contribution analysis: largest tolerance ranked first
# ---------------------------------------------------------------------------

def test_contribution_largest_first():
    # tol_a = 0.1, tol_b = 0.5 -- tol_b should be top contributor
    model = _two_part_model(0.1, 0.5)
    res = rss3d(model)
    assert res["ok"]
    contribs = res["contributions"]
    assert len(contribs) >= 2
    assert contribs[0]["tol_id"] == "t_b"
    assert contribs[0]["variance_contribution_pct"] > contribs[1]["variance_contribution_pct"]


# ---------------------------------------------------------------------------
# T20. Tightening dominant tolerance most reduces output sigma
# ---------------------------------------------------------------------------

def test_tightening_dominant_reduces_sigma():
    model_base = _two_part_model(0.5, 0.1)
    rss_base = rss3d(model_base)

    model_tight = _two_part_model(0.1, 0.1)  # tighten dominant (t_a)
    rss_tight = rss3d(model_tight)

    assert rss_tight["rss_sigma"] < rss_base["rss_sigma"]


# ---------------------------------------------------------------------------
# T21. worst_case >= RSS >= nominal range check
# ---------------------------------------------------------------------------

def test_wc_ge_rss_ge_zero():
    model = _two_part_model(0.4, 0.3)
    wc = worst_case3d(model)
    rs = rss3d(model)
    assert wc["ok"] and rs["ok"]
    assert wc["wc_band"] >= rs["rss_band"]
    assert rs["rss_band"] >= 0.0


# ---------------------------------------------------------------------------
# T22. Cpk math correct (simple two-sided spec)
# ---------------------------------------------------------------------------

def test_cpk_math_correct():
    mean, sigma = 10.0, 0.1
    usl, lsl = 10.3, 9.7
    cap = _capability(mean, sigma, usl, lsl)
    # Cp = (USL - LSL) / (6 * sigma) = 0.6 / 0.6 = 1.0
    assert abs(cap["cp"] - 1.0) < 1e-9
    # Cpk = min((USL-mean)/sigma, (mean-LSL)/sigma) / 3
    zu = (usl - mean) / sigma
    zl = (mean - lsl) / sigma
    expected_cpk = min(zu, zl) / 3.0
    assert abs(cap["cpk"] - expected_cpk) < 1e-9


# ---------------------------------------------------------------------------
# T23. Cp / Cpk with one-sided spec
# ---------------------------------------------------------------------------

def test_cpk_one_sided_usl():
    mean, sigma = 0.0, 1.0
    cap = _capability(mean, sigma, usl=3.0, lsl=None)
    assert "cp" not in cap  # no bilateral spec
    assert abs(cap["cpk"] - 1.0) < 1e-9  # (3-0)/1 / 3


# ---------------------------------------------------------------------------
# T24. defect_ppm with perfectly centered distribution
# ---------------------------------------------------------------------------

def test_defect_ppm_symmetric():
    # +/-3sigma perfectly centered: ppm ~ 2700
    mean, sigma = 0.0, 1.0
    cap = _capability(mean, sigma, usl=3.0, lsl=-3.0)
    assert 2500 < cap["defect_ppm"] < 2800


# ---------------------------------------------------------------------------
# T25. MC returns Cpk when spec limits provided
# ---------------------------------------------------------------------------

def test_mc3d_returns_cpk_with_spec():
    model = _two_part_model(0.2, 0.2)
    # Nominal gap ~ 100.0
    model.usl = 100.6
    model.lsl = 99.4
    mc = monte_carlo3d(model, samples=10000, seed=99)
    assert mc["ok"]
    assert "cpk" in mc
    assert mc["cpk"] > 0


# ---------------------------------------------------------------------------
# T26. Uniform distribution MC stays within half-zone bounds
# ---------------------------------------------------------------------------

def test_mc3d_uniform_within_bounds():
    tol = 0.6  # half-zone = 0.3
    model = _two_part_model(tol, 0.0, sep=50.0, distribution="uniform")
    mc = monte_carlo3d(model, samples=5000, seed=5)
    assert mc["ok"]
    # Max simulated deviation from nominal should be <= half-zone (0.3)
    nominal = mc["nominal"]
    assert mc["max_simulated"] <= nominal + 0.31
    assert mc["min_simulated"] >= nominal - 0.31


# ---------------------------------------------------------------------------
# T27. Zero tolerance contributes nothing to sigma
# ---------------------------------------------------------------------------

def test_zero_tol_no_sigma_contribution():
    model = _two_part_model(0.0, 0.4)
    rs = rss3d(model)
    assert rs["ok"]
    # Only t_b contributes
    sig_b = (0.4 / 2) / 3
    assert abs(rs["rss_sigma"] - sig_b) < 1e-9


# ---------------------------------------------------------------------------
# T28. analyze3d returns combined dict
# ---------------------------------------------------------------------------

def test_analyze3d_combined():
    model = _two_part_model(0.2, 0.3)
    res = analyze3d(model, samples=1000, seed=1)
    assert res["ok"]
    assert "worst_case" in res
    assert "rss" in res
    assert "monte_carlo" in res
    assert res["worst_case"]["ok"]
    assert res["rss"]["ok"]
    assert res["monte_carlo"]["ok"]


# ---------------------------------------------------------------------------
# T29. _parse_model round-trip
# ---------------------------------------------------------------------------

def test_parse_model_roundtrip():
    data = {
        "parts": [
            {
                "part_id": "PA",
                "translation": [0.0, 0.0, 0.0],
                "features": [
                    {
                        "feature_id": "fa",
                        "position": [0.0, 0.0, 0.0],
                        "tolerances": [
                            {"tol_id": "t1", "tol_type": "position", "value": 0.1},
                        ],
                    }
                ],
            },
            {
                "part_id": "PB",
                "translation": [0.0, 0.0, 50.0],
                "features": [
                    {
                        "feature_id": "fb",
                        "position": [0.0, 0.0, 0.0],
                        "tolerances": [],
                    }
                ],
            },
        ],
        "mate_chain": [
            {
                "link_id": "L1",
                "part_a_id": "PA",
                "feature_a_id": "fa",
                "part_b_id": "PB",
                "feature_b_id": "fb",
                "meas_dir": [0.0, 0.0, 1.0],
            }
        ],
        "usl": 50.2,
        "lsl": 49.8,
    }
    model = _parse_model(data)
    assert not isinstance(model, dict)  # no error
    assert len(model.parts) == 2
    assert model.usl == 50.2
    assert model.lsl == 49.8


# ---------------------------------------------------------------------------
# T30. LLM tool round-trip -- valid input
# ---------------------------------------------------------------------------

def test_llm_tool_valid():
    payload = {
        "parts": [
            {
                "part_id": "A",
                "translation": [0.0, 0.0, 0.0],
                "features": [
                    {
                        "feature_id": "fa",
                        "tolerances": [
                            {"tol_id": "t1", "tol_type": "linear", "value": 0.2}
                        ],
                    }
                ],
            },
            {
                "part_id": "B",
                "translation": [0.0, 0.0, 100.0],
                "features": [
                    {"feature_id": "fb", "tolerances": []}
                ],
            },
        ],
        "mate_chain": [
            {
                "part_a_id": "A", "feature_a_id": "fa",
                "part_b_id": "B", "feature_b_id": "fb",
            }
        ],
        "samples": 500,
        "seed": 7,
    }
    result = asyncio.get_event_loop().run_until_complete(
        run_tolerance3d_analysis(None, json.dumps(payload).encode())
    )
    data = json.loads(result)
    assert data["ok"]
    assert "monte_carlo" in data


# ---------------------------------------------------------------------------
# T31. LLM tool -- bad JSON returns error payload
# ---------------------------------------------------------------------------

def test_llm_tool_bad_json():
    result = asyncio.get_event_loop().run_until_complete(
        run_tolerance3d_analysis(None, b"not json {{{")
    )
    data = json.loads(result)
    # err_payload returns {"error": ..., "code": ...} (no "ok" key)
    assert data.get("ok") is not True
    assert "error" in data or "code" in data


# ---------------------------------------------------------------------------
# T32. MC p50 near nominal for zero-mean normal chains
# ---------------------------------------------------------------------------

def test_mc3d_p50_near_nominal():
    model = _two_part_model(0.3, 0.3, sep=75.0)
    mc = monte_carlo3d(model, samples=20000, seed=42)
    assert mc["ok"]
    assert abs(mc["p50"] - mc["nominal"]) < 0.05


# ---------------------------------------------------------------------------
# T33. LCG seeding: same seed -> same sequence
# ---------------------------------------------------------------------------

def test_lcg_deterministic():
    rng1 = _LCG(123)
    rng2 = _LCG(123)
    seq1 = [rng1.random() for _ in range(20)]
    seq2 = [rng2.random() for _ in range(20)]
    assert seq1 == seq2


# ---------------------------------------------------------------------------
# T34. LCG: different seeds -> different sequences
# ---------------------------------------------------------------------------

def test_lcg_different_seeds():
    rng1 = _LCG(1)
    rng2 = _LCG(2)
    seq1 = [rng1.random() for _ in range(10)]
    seq2 = [rng2.random() for _ in range(10)]
    assert seq1 != seq2


# ---------------------------------------------------------------------------
# T35. Box-Muller output is zero-mean and unit-variance (large N)
# ---------------------------------------------------------------------------

def test_lcg_gauss_stats():
    rng = _LCG(999)
    n = 50000
    vals = [rng.gauss() for _ in range(n)]
    mean = sum(vals) / n
    var = sum(v ** 2 for v in vals) / n
    assert abs(mean) < 0.03
    assert abs(var - 1.0) < 0.05
