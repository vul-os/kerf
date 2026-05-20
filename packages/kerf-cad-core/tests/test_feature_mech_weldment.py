"""
T-20: Mech — weldment profile library + cuts.

Scope: weldment.py + weldment_profiles.py
  - I-beam, channel, square tube profile catalog
  - Miter / cope cuts on frame members
  - 25+ frame layouts: member length, miter angle, cut volume vs analytic
  - Weld seam topology (joint types + trim geometry)
  - Boundaries, malformed input, idempotency

Hermetic: no database, no OCCT, no network.
File: packages/kerf-cad-core/tests/test_feature_mech_weldment.py

Author: imranparuk
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.weldment import (
    TOLERANCE_MM,
    _angle_between,
    _are_coplanar,
    _cross3,
    _dot3,
    _effective_half,
    _length3,
    _norm3,
    _vec3,
    compute_cutlist,
    compute_members,
    compute_multi_cutlist,
    run_weldment_cutlist,
    run_weldment_frame,
    run_weldment_profile_lookup,
)
from kerf_cad_core.weldment_profiles import (
    all_designations,
    list_profiles,
    lookup_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ok(json_str: str) -> dict:
    d = json.loads(json_str)
    assert d.get("ok") is True, f"Expected ok:true; got: {json_str}"
    return d


def _err(json_str: str) -> dict:
    d = json.loads(json_str)
    assert "error" in d or d.get("ok") is False, f"Expected error; got: {json_str}"
    return d


class _NullCtx:
    pass


_ctx = _NullCtx()


def _frame_json(skeleton, profile, **kw):
    body = {"skeleton": skeleton, "profile": profile, **kw}
    return json.dumps(body).encode()


def _rect(w, h):
    """Closed axis-aligned rectangle skeleton in XY plane."""
    return [
        {"start": [0, 0, 0],  "end": [w, 0, 0]},
        {"start": [w, 0, 0],  "end": [w, h, 0]},
        {"start": [w, h, 0],  "end": [0, h, 0]},
        {"start": [0, h, 0],  "end": [0, 0, 0]},
    ]


def _box_frame(w, d, h):
    """12-edge box frame (cuboid skeleton)."""
    # bottom 4
    edges = _rect(w, d)
    # top 4 (raised by h)
    top = [{"start": [e["start"][0], e["start"][1], h],
            "end":   [e["end"][0],   e["end"][1],   h]} for e in _rect(w, d)]
    # 4 vertical columns
    verts = [
        {"start": [0, 0, 0], "end": [0, 0, h]},
        {"start": [w, 0, 0], "end": [w, 0, h]},
        {"start": [w, d, 0], "end": [w, d, h]},
        {"start": [0, d, 0], "end": [0, d, h]},
    ]
    return edges + top + verts


# ---------------------------------------------------------------------------
# 1. Profile catalog: I-beam family (IBEAM)
# ---------------------------------------------------------------------------

def test_ibeam_ipe100_fields():
    """IBEAM-IPE100 has correct height and family."""
    pd = lookup_profile("IBEAM-IPE100")
    assert pd is not None
    assert pd["family"] == "IBEAM"
    assert pd["dims_mm"]["h"] == pytest.approx(100.0)
    assert pd["area_mm2"] > 0
    assert pd["mass_per_m_kg"] > 0


def test_ibeam_ipe200_dimensions():
    """IBEAM-IPE200: h=200, area and mass positive."""
    pd = lookup_profile("IBEAM-IPE200")
    assert pd["dims_mm"]["h"] == pytest.approx(200.0)
    assert pd["area_mm2"] > 0


def test_ibeam_ipe300_heavier_than_200():
    """Larger IPE section must be heavier per metre than smaller."""
    pd200 = lookup_profile("IBEAM-IPE200")
    pd300 = lookup_profile("IBEAM-IPE300")
    assert pd300["mass_per_m_kg"] > pd200["mass_per_m_kg"]


def test_ibeam_family_list():
    """list_profiles('IBEAM') returns only IBEAM entries."""
    ibeams = list_profiles("IBEAM")
    assert len(ibeams) >= 3
    for p in ibeams:
        assert p["family"] == "IBEAM"


# ---------------------------------------------------------------------------
# 2. Profile catalog: channel family (CHANNEL)
# ---------------------------------------------------------------------------

def test_channel_lookup_fields():
    """CHANNEL-100x50x5 has correct h, b, t dims and family."""
    pd = lookup_profile("CHANNEL-100x50x5")
    assert pd is not None
    assert pd["family"] == "CHANNEL"
    assert pd["dims_mm"]["h"] == pytest.approx(100.0)
    assert pd["area_mm2"] > 0
    assert pd["mass_per_m_kg"] > 0


def test_channel_family_list():
    """list_profiles('CHANNEL') returns only channel entries."""
    channels = list_profiles("CHANNEL")
    assert len(channels) >= 2
    for p in channels:
        assert p["family"] == "CHANNEL"


# ---------------------------------------------------------------------------
# 3. Profile catalog: square tube (SQ)
# ---------------------------------------------------------------------------

def test_sq_lookup_fields():
    """SQ-50x50x3 has correct od, t, and positive mass."""
    pd = lookup_profile("SQ-50x50x3")
    assert pd["family"] == "SQ"
    assert pd["dims_mm"]["od"] == pytest.approx(50.0)
    assert pd["dims_mm"]["t"] == pytest.approx(3.0)
    assert pd["mass_per_m_kg"] > 0


def test_sq_thicker_wall_heavier():
    """SQ-50x50x4 must be heavier per metre than SQ-50x50x3 (thicker wall)."""
    pd3 = lookup_profile("SQ-50x50x3")
    pd4 = lookup_profile("SQ-50x50x4")
    assert pd4["mass_per_m_kg"] > pd3["mass_per_m_kg"]


def test_sq_larger_od_heavier():
    """SQ-100x100x5 must be heavier than SQ-50x50x3."""
    small = lookup_profile("SQ-50x50x3")
    large = lookup_profile("SQ-100x100x5")
    assert large["mass_per_m_kg"] > small["mass_per_m_kg"]


def test_all_designations_sorted():
    """all_designations() returns a sorted list with no duplicates."""
    desigs = all_designations()
    assert desigs == sorted(desigs)
    assert len(desigs) == len(set(desigs))


def test_catalog_size():
    """Catalog has at least 50 profiles across all families."""
    assert len(list_profiles()) >= 50


def test_designation_key_in_profile():
    """Every profile dict returned by lookup includes the designation key."""
    for desig in ["SQ-40x40x3", "IBEAM-IPE200", "CHANNEL-100x50x5",
                  "CHS-60.3x4", "ANGLE-65x65x6", "RHS-100x50x4"]:
        pd = lookup_profile(desig)
        assert pd is not None, f"Missing profile {desig}"
        assert pd["designation"] == desig


# ---------------------------------------------------------------------------
# 4. Frame layouts: member lengths
# ---------------------------------------------------------------------------

def test_single_member_raw_length():
    """Single 1 000 mm member: raw_length_mm == 1 000."""
    pd = lookup_profile("SQ-50x50x3")
    members, errors = compute_members(
        [{"start": [0, 0, 0], "end": [1000, 0, 0]}], pd
    )
    assert not errors
    assert members[0]["raw_length_mm"] == pytest.approx(1000.0)
    assert members[0]["length_mm"] == pytest.approx(1000.0)  # free both ends


def test_diagonal_member_length():
    """3-4-5 triangle diagonal (300-400 mm) → raw_length = 500 mm."""
    pd = lookup_profile("SQ-40x40x3")
    members, errors = compute_members(
        [{"start": [0, 0, 0], "end": [300, 400, 0]}], pd
    )
    assert not errors
    assert members[0]["raw_length_mm"] == pytest.approx(500.0, rel=1e-6)


def test_3d_diagonal_member_length():
    """3D diagonal (1-1-1 unit vector → length sqrt(3))."""
    pd = lookup_profile("RHS-100x50x4")
    L = 1000.0
    members, errors = compute_members(
        [{"start": [0, 0, 0], "end": [L, L, L]}], pd
    )
    assert not errors
    expected = math.sqrt(3) * L
    assert members[0]["raw_length_mm"] == pytest.approx(expected, rel=1e-6)


def test_rect_frame_member_lengths_analytic():
    """Rectangle 1000×600: bottom/top = 1000-trim, sides = 600-trim."""
    pd = lookup_profile("SQ-50x50x3")
    members, errors = compute_members(_rect(1000, 600), pd)
    assert not errors
    # Bottom & top have raw_length=1000; left/right have raw_length=600
    horiz = [m for m in members if m["raw_length_mm"] == pytest.approx(1000.0)]
    vert  = [m for m in members if m["raw_length_mm"] == pytest.approx(600.0)]
    assert len(horiz) == 2
    assert len(vert)  == 2
    # Trimmed lengths must be shorter (mitered at 90°)
    for m in horiz + vert:
        assert m["length_mm"] < m["raw_length_mm"]


def test_square_frame_all_members_equal_length():
    """Perfect square frame (500×500) → all 4 members trimmed identically."""
    pd = lookup_profile("SQ-50x50x3")
    members, errors = compute_members(_rect(500, 500), pd)
    assert not errors
    lengths = [m["length_mm"] for m in members]
    assert max(lengths) == pytest.approx(min(lengths), rel=1e-6)


def test_l_shaped_two_members():
    """L-shape: two members at 90° → each trimmed by eff_half/sin(45°)."""
    pd = lookup_profile("SQ-50x50x3")
    eff_half = _effective_half(pd["area_mm2"])
    expected_trim = eff_half / math.sin(math.pi / 4)
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},
        {"start": [500, 0, 0], "end": [500, 500, 0]},
    ]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    assert members[0]["trim_end_mm"]   == pytest.approx(expected_trim, rel=1e-5)
    assert members[1]["trim_start_mm"] == pytest.approx(expected_trim, rel=1e-5)


def test_obtuse_angle_miter_trim_smaller_than_90():
    """120° joint → bisector angle = 60° → trim less than 90° miter."""
    pd = lookup_profile("SQ-50x50x3")
    eff_half = _effective_half(pd["area_mm2"])

    # Two members meeting at origin at 120° interior angle.
    # Away-dir0 points +X; away-dir1 points at 120° from +X = (-0.5, sqrt(3)/2).
    # Angle between away-dirs = 60°; trim = eff_half / sin(30°) = eff_half / 0.5
    # But 90° miter gives trim = eff_half / sin(45°).
    # At 120° meeting: interior=120°, between away-dirs=60°, half=30°.
    sin_60 = math.sin(math.radians(60) / 2)  # sin(30°) = 0.5
    expected_trim_120 = eff_half / sin_60

    sin_45 = math.sin(math.pi / 4)
    expected_trim_90 = eff_half / sin_45

    # 120° joint yields more trim (narrower bisector angle)
    # The 90° interior angle: away-dirs span 90°, half=45°, trim=eff/sin45
    # The 120° interior angle: away-dirs span 60°, half=30°, trim=eff/sin30 = 2×eff
    assert expected_trim_120 > expected_trim_90


def test_box_frame_12_members():
    """12-edge box frame → 12 members."""
    pd = lookup_profile("RHS-100x50x4")
    members, errors = compute_members(_box_frame(600, 400, 300), pd)
    assert not errors
    assert len(members) == 12


def test_box_frame_member_ids_sequential():
    """Member IDs are 1-based sequential integers."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_box_frame(500, 500, 500), pd)
    expected = list(range(1, len(members) + 1))
    assert [m["member_id"] for m in members] == expected


def test_box_frame_vertical_members_raw_length():
    """Vertical columns of a 300 mm tall box have raw_length=300."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_box_frame(600, 400, 300), pd)
    vert = [m for m in members if m["raw_length_mm"] == pytest.approx(300.0)]
    assert len(vert) == 4


# ---------------------------------------------------------------------------
# 5. Miter angle analytic verification
# ---------------------------------------------------------------------------

def test_miter_angle_90deg_joint_type():
    """Two members at 90° → joint type = miter."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},
        {"start": [500, 0, 0], "end": [500, 300, 0]},
    ]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    assert members[0]["end_joint"]   == "miter"
    assert members[1]["start_joint"] == "miter"


def test_collinear_joint_is_butt():
    """Collinear co-directional members at shared vertex → butt joint."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},
        {"start": [500, 0, 0], "end": [1000, 0, 0]},
    ]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    assert members[0]["end_joint"]   == "butt"
    assert members[1]["start_joint"] == "butt"


def test_three_way_joint_all_butt():
    """Three members at one vertex → all butt joints at that vertex."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [
        {"start": [0, 0, 0], "end": [500,  0,   0]},
        {"start": [0, 0, 0], "end": [0,    500, 0]},
        {"start": [0, 0, 0], "end": [0,    0,   500]},
    ]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    for m in members:
        assert m["start_joint"] == "butt"


def test_free_ends_lone_member():
    """Single member has both joints = free."""
    pd = lookup_profile("CHS-60.3x4")
    members, _ = compute_members(
        [{"start": [0, 0, 0], "end": [800, 0, 0]}], pd
    )
    assert members[0]["start_joint"] == "free"
    assert members[0]["end_joint"]   == "free"
    assert members[0]["trim_start_mm"] == pytest.approx(0.0)
    assert members[0]["trim_end_mm"]   == pytest.approx(0.0)


def test_miter_trim_symmetry_for_equal_members():
    """In an L-joint between equal-length members, both get identical trim."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},
        {"start": [500, 0, 0], "end": [500, 500, 0]},
    ]
    members, _ = compute_members(skeleton, pd)
    assert members[0]["trim_end_mm"] == pytest.approx(members[1]["trim_start_mm"])


# ---------------------------------------------------------------------------
# 6. Cut volume vs analytic: cutlist mass
# ---------------------------------------------------------------------------

def test_cutlist_mass_formula_single_profile():
    """total_mass_kg == (total_length_mm / 1000) * mass_per_m_kg."""
    pd = lookup_profile("IBEAM-IPE200")
    members_raw = [
        {"profile": "IBEAM-IPE200", "length_mm": 2000.0},
        {"profile": "IBEAM-IPE200", "length_mm": 1500.0},
        {"profile": "IBEAM-IPE200", "length_mm": 1000.0},
    ]
    cl = compute_cutlist(members_raw, pd)
    expected = (4500.0 / 1000.0) * pd["mass_per_m_kg"]
    assert cl["total_length_mm"] == pytest.approx(4500.0)
    assert cl["total_mass_kg"]   == pytest.approx(expected, rel=1e-5)


def test_cutlist_groups_identical_lengths():
    """Identical lengths collapse to quantity > 1 in a single piece entry."""
    pd = lookup_profile("CHANNEL-100x50x5")
    members_raw = [
        {"profile": "CHANNEL-100x50x5", "length_mm": 750.0},
        {"profile": "CHANNEL-100x50x5", "length_mm": 750.0},
        {"profile": "CHANNEL-100x50x5", "length_mm": 750.0},
    ]
    cl = compute_cutlist(members_raw, pd)
    assert len(cl["pieces"]) == 1
    assert cl["pieces"][0]["quantity"] == 3


def test_multi_cutlist_grand_total():
    """compute_multi_cutlist sums correctly across two profiles."""
    pd_sq  = lookup_profile("SQ-50x50x3")
    pd_ipe = lookup_profile("IBEAM-IPE200")
    members_raw = [
        {"profile": "SQ-50x50x3",  "length_mm": 1000.0},
        {"profile": "IBEAM-IPE200", "length_mm": 2000.0},
    ]
    result = compute_multi_cutlist(members_raw, {
        "SQ-50x50x3": pd_sq, "IBEAM-IPE200": pd_ipe
    })
    assert len(result) == 2
    desigs = {c["designation"] for c in result}
    assert "SQ-50x50x3" in desigs
    assert "IBEAM-IPE200" in desigs
    grand = sum(c["total_mass_kg"] for c in result)
    assert grand > 0


def test_cutlist_sorted_by_length_descending():
    """Cut list pieces for one profile are sorted length descending."""
    pd = lookup_profile("SQ-50x50x3")
    members_raw = [
        {"profile": "SQ-50x50x3", "length_mm": 300.0},
        {"profile": "SQ-50x50x3", "length_mm": 500.0},
        {"profile": "SQ-50x50x3", "length_mm": 200.0},
    ]
    cl = compute_cutlist(members_raw, pd)
    lengths = [p["length_mm"] for p in cl["pieces"]]
    assert lengths == sorted(lengths, reverse=True)


def test_rect_frame_cutlist_mass_less_than_raw():
    """Rect frame cut mass < raw mass (trimming removes material)."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_rect(1000, 600), pd)
    cl = compute_cutlist(members, pd)
    raw_total = sum(m["raw_length_mm"] for m in members)
    raw_mass  = (raw_total / 1000.0) * pd["mass_per_m_kg"]
    assert cl["total_mass_kg"] < raw_mass


# ---------------------------------------------------------------------------
# 7. Weld seam topology: joint field consistency
# ---------------------------------------------------------------------------

def test_trimmed_length_equals_raw_minus_trims():
    """length_mm == raw_length_mm - trim_start_mm - trim_end_mm for all members."""
    pd = lookup_profile("RHS-100x50x4")
    members, _ = compute_members(_box_frame(600, 400, 300), pd)
    for m in members:
        expected = m["raw_length_mm"] - m["trim_start_mm"] - m["trim_end_mm"]
        assert m["length_mm"] == pytest.approx(max(0.0, expected), rel=1e-6)


def test_unit_vector_is_normalised():
    """unit_vector magnitude is 1.0 for all members of a complex frame."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_box_frame(800, 600, 400), pd)
    for m in members:
        uv = m["unit_vector"]
        mag = math.sqrt(sum(x ** 2 for x in uv))
        assert mag == pytest.approx(1.0, abs=1e-6)


def test_gap_mm_adds_to_all_ends():
    """gap_mm=5 increases trim at every joint end vs gap_mm=0."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = _rect(1000, 600)
    m0, _ = compute_members(skeleton, pd, gap_mm=0.0)
    m5, _ = compute_members(skeleton, pd, gap_mm=5.0)
    for a, b in zip(m0, m5):
        # trim_start_mm with gap must be >= trim without
        assert b["trim_start_mm"] >= a["trim_start_mm"] - 1e-9
        assert b["trim_end_mm"]   >= a["trim_end_mm"]   - 1e-9


def test_idempotency_same_result_twice():
    """compute_members is deterministic: two identical calls produce same output."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = _box_frame(600, 400, 300)
    m1, e1 = compute_members(skeleton, pd)
    m2, e2 = compute_members(skeleton, pd)
    assert e1 == e2
    for a, b in zip(m1, m2):
        assert a["length_mm"]     == pytest.approx(b["length_mm"])
        assert a["start_joint"]   == b["start_joint"]
        assert a["end_joint"]     == b["end_joint"]
        assert a["trim_start_mm"] == pytest.approx(b["trim_start_mm"])
        assert a["trim_end_mm"]   == pytest.approx(b["trim_end_mm"])


# ---------------------------------------------------------------------------
# 8. Boundary / malformed input tests
# ---------------------------------------------------------------------------

def test_empty_skeleton_returns_error():
    """Empty skeleton list → errors, no members."""
    pd = lookup_profile("SQ-50x50x3")
    members, errors = compute_members([], pd)
    assert len(errors) > 0
    assert members == []


def test_zero_length_edge_error():
    """Zero-length edge (start == end) → ok:false from runner."""
    result = _run(run_weldment_frame(
        _ctx,
        _frame_json([{"start": [0, 0, 0], "end": [0, 0, 0]}], "SQ-50x50x3"),
    ))
    d = json.loads(result)
    assert d.get("ok") is False


def _is_error(d: dict) -> bool:
    """True if the payload represents an error (either ok:false or has error/code key)."""
    return d.get("ok") is False or "error" in d or "errors" in d or "code" in d


def test_unknown_profile_returns_error_code():
    """Unknown profile → UNKNOWN_PROFILE code."""
    result = _run(run_weldment_frame(
        _ctx,
        _frame_json([{"start": [0, 0, 0], "end": [500, 0, 0]}], "BOGUS-9x9"),
    ))
    d = json.loads(result)
    assert _is_error(d)
    assert d.get("code") == "UNKNOWN_PROFILE" or "BOGUS-9x9" in json.dumps(d)


def test_missing_profile_field_returns_error():
    """Omitting 'profile' field → BAD_ARGS."""
    result = _run(run_weldment_frame(
        _ctx,
        json.dumps({"skeleton": [{"start": [0, 0, 0], "end": [1, 0, 0]}]}).encode(),
    ))
    d = json.loads(result)
    assert _is_error(d)


def test_negative_gap_returns_error():
    """Negative gap_mm → BAD_ARGS."""
    result = _run(run_weldment_frame(
        _ctx,
        _frame_json([{"start": [0, 0, 0], "end": [500, 0, 0]}], "SQ-50x50x3", gap_mm=-1.0),
    ))
    d = json.loads(result)
    assert _is_error(d)


def test_bad_alignment_returns_error():
    """Invalid alignment value → BAD_ARGS."""
    result = _run(run_weldment_frame(
        _ctx,
        _frame_json([{"start": [0, 0, 0], "end": [500, 0, 0]}], "SQ-50x50x3", alignment="top"),
    ))
    d = json.loads(result)
    assert _is_error(d)


def test_cutlist_empty_members_error():
    """Empty members list → error from cutlist runner."""
    result = _run(run_weldment_cutlist(
        _ctx, json.dumps({"members": []}).encode()
    ))
    d = json.loads(result)
    assert _is_error(d)


def test_cutlist_unknown_profile_error():
    """Unknown profile in cutlist members → ok:false."""
    result = _run(run_weldment_cutlist(
        _ctx, json.dumps({"members": [{"profile": "NOPE-1x1", "length_mm": 100.0}]}).encode()
    ))
    d = json.loads(result)
    assert d.get("ok") is False


def test_profile_lookup_unknown_designation():
    """weldment_profile_lookup for unknown designation → ok:false."""
    result = _run(run_weldment_profile_lookup(
        _ctx, json.dumps({"designation": "NOTREAL-99x99x9"}).encode()
    ))
    d = json.loads(result)
    assert d.get("ok") is False


# ---------------------------------------------------------------------------
# 9. Tool runner integration: frame layouts
# ---------------------------------------------------------------------------

def test_tool_single_member_response():
    """weldment_frame tool: single member → ok:true, member_count=1."""
    result = _run(run_weldment_frame(
        _ctx, _frame_json([{"start": [0, 0, 0], "end": [2000, 0, 0]}], "IBEAM-IPE200"),
    ))
    d = _ok(result)
    assert d["member_count"] == 1
    assert d["members"][0]["raw_length_mm"] == pytest.approx(2000.0)


def test_tool_rect_frame_cutlist_in_response():
    """weldment_frame for a rectangle includes cutlist with total_mass_kg > 0."""
    result = _run(run_weldment_frame(
        _ctx, _frame_json(_rect(1200, 800), "SQ-50x50x3"),
    ))
    d = _ok(result)
    assert d["cutlist"]["total_mass_kg"] > 0.0


def test_tool_multi_profile_cutlist():
    """weldment_cutlist for two profiles returns grand_total across both."""
    members = [
        {"profile": "SQ-50x50x3",  "length_mm": 1000.0},
        {"profile": "IBEAM-IPE200", "length_mm": 2000.0},
    ]
    result = _run(run_weldment_cutlist(
        _ctx, json.dumps({"members": members}).encode()
    ))
    d = _ok(result)
    assert d["grand_total_mass_kg"] > 0.0
    grand = sum(c["total_mass_kg"] for c in d["cutlist"])
    assert d["grand_total_mass_kg"] == pytest.approx(grand, rel=1e-6)


def test_tool_profile_lookup_list_all():
    """weldment_profile_lookup with no args returns full catalog (≥50)."""
    result = _run(run_weldment_profile_lookup(
        _ctx, json.dumps({}).encode()
    ))
    d = _ok(result)
    assert d["count"] >= 50


def test_tool_profile_lookup_list_sq_family():
    """weldment_profile_lookup family=SQ returns only SQ entries."""
    result = _run(run_weldment_profile_lookup(
        _ctx, json.dumps({"family": "SQ"}).encode()
    ))
    d = _ok(result)
    for p in d["profiles"]:
        assert p["family"] == "SQ"


def test_tool_corner_alignment_accepted():
    """alignment='corner' is accepted and reflected in member output."""
    result = _run(run_weldment_frame(
        _ctx,
        _frame_json([{"start": [0, 0, 0], "end": [500, 0, 0]}], "SQ-50x50x3", alignment="corner"),
    ))
    d = _ok(result)
    assert d["alignment"] == "corner"
    assert d["members"][0]["alignment"] == "corner"


def test_tool_gap_reduces_total_length():
    """gap_mm=10 reduces total trimmed length compared to gap_mm=0."""
    skeleton = _rect(1000, 600)
    r0 = _ok(_run(run_weldment_frame(
        _ctx, _frame_json(skeleton, "SQ-50x50x3", gap_mm=0.0)
    )))
    r1 = _ok(_run(run_weldment_frame(
        _ctx, _frame_json(skeleton, "SQ-50x50x3", gap_mm=10.0)
    )))
    total0 = sum(m["length_mm"] for m in r0["members"])
    total1 = sum(m["length_mm"] for m in r1["members"])
    assert total1 < total0
