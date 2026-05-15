"""
Tests for the weldment frame generator:
  - weldment_frame  (T-1)
  - weldment_profile_lookup (T-2)
  - weldment_cutlist (T-3)

Pure-Python, hermetic — no database, no OCCT, no ProjectCtx required.

Author: imranparuk
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.weldment import (
    compute_members,
    compute_cutlist,
    compute_multi_cutlist,
    run_weldment_frame,
    run_weldment_profile_lookup,
    run_weldment_cutlist,
    TOLERANCE_MM,
    _effective_half,
    _length3,
    _vec3,
)
from kerf_cad_core.weldment_profiles import (
    lookup_profile,
    list_profiles,
    all_designations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _ok(json_str: str) -> dict:
    d = json.loads(json_str)
    assert d.get("ok") is True or "error" not in d, f"Expected ok payload; got: {json_str}"
    return d


def _err(json_str: str) -> dict:
    d = json.loads(json_str)
    assert "error" in d or d.get("ok") is False, f"Expected error payload; got: {json_str}"
    return d


# Null ctx — tools don't use ctx for these pure-compute tools
class _NullCtx:
    pass


_ctx = _NullCtx()

# ---------------------------------------------------------------------------
# Single-member length tests
# ---------------------------------------------------------------------------

def test_single_member_correct_length():
    """A single horizontal member should have length equal to its segment length."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [{"start": [0, 0, 0], "end": [1000, 0, 0]}]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    assert len(members) == 1
    assert members[0]["raw_length_mm"] == pytest.approx(1000.0)
    # Single free end — no trimming, only gap (0 by default)
    assert members[0]["trim_start_mm"] == pytest.approx(0.0)
    assert members[0]["trim_end_mm"]   == pytest.approx(0.0)
    assert members[0]["length_mm"]     == pytest.approx(1000.0)


def test_single_member_free_joints():
    """A lone member should have both ends marked 'free'."""
    pd = lookup_profile("RHS-100x50x4")
    skeleton = [{"start": [0, 0, 0], "end": [500, 0, 0]}]
    members, _ = compute_members(skeleton, pd)
    assert members[0]["start_joint"] == "free"
    assert members[0]["end_joint"]   == "free"


def test_single_member_diagonal():
    """Diagonal member: length = sqrt(100² + 100² + 0²) = 100√2."""
    pd = lookup_profile("SQ-40x40x3")
    skeleton = [{"start": [0, 0, 0], "end": [100, 100, 0]}]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    assert members[0]["raw_length_mm"] == pytest.approx(100.0 * math.sqrt(2), rel=1e-6)


def test_single_member_unit_vector():
    """Unit vector of a member along X-axis should be [1, 0, 0]."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [{"start": [0, 0, 0], "end": [200, 0, 0]}]
    members, _ = compute_members(skeleton, pd)
    uv = members[0]["unit_vector"]
    assert uv[0] == pytest.approx(1.0, abs=1e-6)
    assert uv[1] == pytest.approx(0.0, abs=1e-6)
    assert uv[2] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# L-joint miter trim tests
# ---------------------------------------------------------------------------

def test_l_joint_miter_type():
    """Two members meeting at 90° at one end should produce miter joints."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},   # horizontal
        {"start": [500, 0, 0], "end": [500, 500, 0]},  # vertical
    ]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    # Member 0 end and Member 1 start share vertex [500,0,0]
    assert members[0]["end_joint"]   == "miter"
    assert members[1]["start_joint"] == "miter"


def test_l_joint_miter_trim_amount_90deg():
    """At 90° miter, trim = eff_half / sin(45°) = eff_half * sqrt(2)."""
    pd = lookup_profile("SQ-50x50x3")
    area = pd["area_mm2"]  # 564
    eff_half = _effective_half(area)
    expected_trim = eff_half / math.sin(math.pi / 4)

    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},
        {"start": [500, 0, 0], "end": [500, 500, 0]},
    ]
    members, _ = compute_members(skeleton, pd)
    assert members[0]["trim_end_mm"]   == pytest.approx(expected_trim, rel=1e-5)
    assert members[1]["trim_start_mm"] == pytest.approx(expected_trim, rel=1e-5)


def test_l_joint_trimmed_length():
    """Trimmed length = raw_length - trim_start - trim_end."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},
        {"start": [500, 0, 0], "end": [500, 500, 0]},
    ]
    members, _ = compute_members(skeleton, pd)
    for m in members:
        expected = m["raw_length_mm"] - m["trim_start_mm"] - m["trim_end_mm"]
        assert m["length_mm"] == pytest.approx(expected, rel=1e-6)


def test_l_joint_free_far_ends():
    """The free ends of an L-joint (not meeting at vertex) remain 'free'."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},
        {"start": [500, 0, 0], "end": [500, 500, 0]},
    ]
    members, _ = compute_members(skeleton, pd)
    assert members[0]["start_joint"] == "free"
    assert members[1]["end_joint"]   == "free"


# ---------------------------------------------------------------------------
# T-joint butt tests
# ---------------------------------------------------------------------------

def test_t_joint_butt_type():
    """
    Three members at one vertex (T- or star-joint) must produce butt joints,
    not miter.
    """
    pd = lookup_profile("SQ-50x50x3")
    # Three members meeting at origin
    skeleton = [
        {"start": [0, 0, 0], "end": [500,  0,   0]},  # +X
        {"start": [0, 0, 0], "end": [0,    500, 0]},  # +Y
        {"start": [0, 0, 0], "end": [0,    0,   500]}, # +Z
    ]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    # All start joints (meeting at origin) must be butt
    for m in members:
        assert m["start_joint"] == "butt"


def test_t_joint_two_members_coplanar_butt():
    """
    A true T-joint: one long pass-through, one cross member butting.
    Here we simulate by placing a 3-way meeting where the longest member passes
    through and the shorter one butts.

    Actually for a 2-member meeting with collinear-same-direction vectors:
    endpoints appear as: A→B and B→C collinear — those share vertex B, and
    B is the end of the first and start of the second.  They are anti-parallel
    (d0 pointing right, d1 also pointing right) so cross = 0 → butt.
    """
    pd = lookup_profile("RHS-100x50x4")
    # Two collinear members end-to-end — their away-dirs at the shared vertex
    # are opposite (both pointing away along X)
    skeleton = [
        {"start": [0, 0, 0],   "end": [500, 0, 0]},   # d = [1,0,0]
        {"start": [500, 0, 0], "end": [1000, 0, 0]},  # d = [1,0,0]
    ]
    members, errors = compute_members(skeleton, pd)
    assert not errors
    # At shared vertex: member0 end going away=[1,0,0], member1 start going away=[1,0,0]
    # cross product = 0 → parallel → butt
    assert members[0]["end_joint"] == "butt"
    assert members[1]["start_joint"] == "butt"


# ---------------------------------------------------------------------------
# Rectangle frame (4-member) cut-list test
# ---------------------------------------------------------------------------

def _rect_frame_skeleton(w: float, h: float) -> list[dict]:
    """Axis-aligned rectangle in the XY-plane, 4 edges."""
    return [
        {"start": [0, 0, 0],  "end": [w, 0, 0]},   # bottom
        {"start": [w, 0, 0],  "end": [w, h, 0]},   # right
        {"start": [w, h, 0],  "end": [0, h, 0]},   # top
        {"start": [0, h, 0],  "end": [0, 0, 0]},   # left
    ]


def test_rect_frame_member_count():
    """Rectangle frame has exactly 4 members."""
    pd = lookup_profile("SQ-50x50x3")
    members, errors = compute_members(_rect_frame_skeleton(1000, 600), pd)
    assert not errors
    assert len(members) == 4


def test_rect_frame_member_ids():
    """Member IDs should be 1-based sequential."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_rect_frame_skeleton(1000, 600), pd)
    assert [m["member_id"] for m in members] == [1, 2, 3, 4]


def test_rect_frame_all_miter_joints():
    """In a closed rectangle frame all joints are miter (2-member coplanar)."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_rect_frame_skeleton(1000, 600), pd)
    for m in members:
        assert m["start_joint"] == "miter"
        assert m["end_joint"]   == "miter"


def test_rect_frame_cutlist_total_count():
    """Cut list for uniform profile should produce 2 distinct lengths (W-trim, H-trim)."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_rect_frame_skeleton(1000, 600), pd)
    cl = compute_cutlist(members, pd)
    # All 4 members have a trimmed length; there should be ≤ 2 distinct sizes
    assert len(cl["pieces"]) <= 2
    # Total quantity across all pieces = 4
    total_qty = sum(p["quantity"] for p in cl["pieces"])
    assert total_qty == 4


def test_rect_frame_cutlist_total_mass_positive():
    """Total mass must be positive."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_rect_frame_skeleton(1000, 600), pd)
    cl = compute_cutlist(members, pd)
    assert cl["total_mass_kg"] > 0.0


def test_rect_frame_cutlist_mass_formula():
    """total_mass_kg == (total_length_mm / 1000) * mass_per_m_kg."""
    pd = lookup_profile("SQ-50x50x3")
    members, _ = compute_members(_rect_frame_skeleton(1000, 600), pd)
    cl = compute_cutlist(members, pd)
    expected = (cl["total_length_mm"] / 1000.0) * pd["mass_per_m_kg"]
    assert cl["total_mass_kg"] == pytest.approx(expected, rel=1e-5)


def test_rect_frame_total_length_sane():
    """Total length must be less than the sum of raw edge lengths (trimming removes material)."""
    pd = lookup_profile("SQ-50x50x3")
    skeleton = _rect_frame_skeleton(1000, 600)
    members, _ = compute_members(skeleton, pd)
    cl = compute_cutlist(members, pd)
    raw_total = sum(m["raw_length_mm"] for m in members)
    assert cl["total_length_mm"] < raw_total


# ---------------------------------------------------------------------------
# Profile catalog lookup tests
# ---------------------------------------------------------------------------

def test_profile_lookup_sq():
    """SQ-50x50x3 is in the catalog and has expected fields."""
    pd = lookup_profile("SQ-50x50x3")
    assert pd is not None
    assert pd["family"] == "SQ"
    assert pd["area_mm2"] == pytest.approx(564.0)
    assert pd["mass_per_m_kg"] == pytest.approx(4.43)
    assert "od" in pd["dims_mm"]
    assert pd["dims_mm"]["od"] == 50.0
    assert pd["dims_mm"]["t"]  == 3.0


def test_profile_lookup_ipe200():
    """IBEAM-IPE200 is in the catalog."""
    pd = lookup_profile("IBEAM-IPE200")
    assert pd is not None
    assert pd["family"] == "IBEAM"
    assert pd["dims_mm"]["h"] == 200.0


def test_profile_lookup_angle():
    """ANGLE-65x65x6 is in the catalog."""
    pd = lookup_profile("ANGLE-65x65x6")
    assert pd is not None
    assert pd["family"] == "ANGLE"
    assert pd["dims_mm"]["leg"] == 65.0


def test_profile_lookup_channel():
    """CHANNEL-100x50x5 is in the catalog."""
    pd = lookup_profile("CHANNEL-100x50x5")
    assert pd is not None
    assert pd["family"] == "CHANNEL"
    assert pd["dims_mm"]["h"] == 100.0


def test_profile_lookup_chs():
    """CHS-60x3 is in the catalog."""
    pd = lookup_profile("CHS-60.3x4")
    assert pd is not None
    assert pd["family"] == "CHS"


def test_profile_lookup_rhs():
    """RHS-100x50x4 is in the catalog."""
    pd = lookup_profile("RHS-100x50x4")
    assert pd is not None
    assert pd["family"] == "RHS"
    assert pd["dims_mm"]["w"] == 100.0
    assert pd["dims_mm"]["d"] == 50.0


def test_profile_lookup_returns_designation():
    """lookup_profile result includes the designation key."""
    pd = lookup_profile("SQ-40x40x3")
    assert pd["designation"] == "SQ-40x40x3"


def test_profile_list_all():
    """list_profiles() returns all profiles; count > 50."""
    all_p = list_profiles()
    assert len(all_p) > 50


def test_profile_list_family_sq():
    """list_profiles('SQ') returns only SQ family entries."""
    sq = list_profiles("SQ")
    assert len(sq) > 0
    for p in sq:
        assert p["family"] == "SQ"


def test_profile_all_designations_sorted():
    """all_designations() returns a sorted list."""
    desigs = all_designations()
    assert desigs == sorted(desigs)


# ---------------------------------------------------------------------------
# Unknown-profile error tests
# ---------------------------------------------------------------------------

def test_unknown_profile_compute_members():
    """compute_members does not raise; returns error list when profile is unknown."""
    # compute_members takes a profile_data dict — pass a badly constructed one
    # The tool-level runner handles unknown profile detection.
    result = _run(run_weldment_frame(
        _ctx,
        json.dumps({
            "skeleton": [{"start": [0, 0, 0], "end": [500, 0, 0]}],
            "profile": "NONEXISTENT-999x999x99",
        }).encode(),
    ))
    d = json.loads(result)
    assert d.get("ok") is False or "error" in d
    assert "NONEXISTENT-999x999x99" in (d.get("error", "") + json.dumps(d.get("errors", [])))


def test_unknown_profile_error_code():
    """Unknown profile should return UNKNOWN_PROFILE error code."""
    result = _run(run_weldment_frame(
        _ctx,
        json.dumps({
            "skeleton": [{"start": [0, 0, 0], "end": [100, 0, 0]}],
            "profile": "BOGUS",
        }).encode(),
    ))
    d = json.loads(result)
    assert d.get("code") == "UNKNOWN_PROFILE" or d.get("ok") is False


def test_unknown_profile_in_cutlist():
    """weldment_cutlist returns ok:false for unknown profile in member list."""
    result = _run(run_weldment_cutlist(
        _ctx,
        json.dumps({
            "members": [{"profile": "DOES-NOT-EXIST", "length_mm": 500.0}],
        }).encode(),
    ))
    d = json.loads(result)
    assert d.get("ok") is False


# ---------------------------------------------------------------------------
# Zero-length edge error tests
# ---------------------------------------------------------------------------

def test_zero_length_edge_error():
    """Zero-length edge (start == end) should return ok:false with an error."""
    result = _run(run_weldment_frame(
        _ctx,
        json.dumps({
            "skeleton": [{"start": [100, 0, 0], "end": [100, 0, 0]}],
            "profile": "SQ-50x50x3",
        }).encode(),
    ))
    d = json.loads(result)
    assert d.get("ok") is False


def test_zero_length_edge_in_mixed_skeleton():
    """If any edge in the skeleton is zero-length, the whole call fails."""
    result = _run(run_weldment_frame(
        _ctx,
        json.dumps({
            "skeleton": [
                {"start": [0, 0, 0], "end": [500, 0, 0]},  # valid
                {"start": [0, 0, 0], "end": [0, 0, 0]},     # degenerate
            ],
            "profile": "SQ-50x50x3",
        }).encode(),
    ))
    d = json.loads(result)
    assert d.get("ok") is False


def test_degenerate_edge_compute_members():
    """compute_members returns an error for zero-length edges."""
    pd = lookup_profile("SQ-50x50x3")
    _, errors = compute_members(
        [{"start": [0, 0, 0], "end": [0, 0, 0]}], pd
    )
    assert len(errors) > 0
    assert any("zero-length" in e or "degenerate" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Mass rollup tests
# ---------------------------------------------------------------------------

def test_cutlist_mass_rollup_single_profile():
    """Single-profile rollup: total_mass_kg matches manual calculation."""
    pd = lookup_profile("SQ-50x50x3")
    members = [
        {"profile": "SQ-50x50x3", "length_mm": 1000.0},
        {"profile": "SQ-50x50x3", "length_mm": 600.0},
        {"profile": "SQ-50x50x3", "length_mm": 600.0},
        {"profile": "SQ-50x50x3", "length_mm": 1000.0},
    ]
    cl = compute_cutlist(members, pd)
    expected_len = 3200.0
    expected_mass = (expected_len / 1000.0) * pd["mass_per_m_kg"]
    assert cl["total_length_mm"] == pytest.approx(expected_len)
    assert cl["total_mass_kg"]   == pytest.approx(expected_mass, rel=1e-5)


def test_cutlist_multi_profile_via_tool():
    """weldment_cutlist tool handles two different profiles and sums grand total."""
    members = [
        {"profile": "SQ-50x50x3",   "length_mm": 1000.0},
        {"profile": "IBEAM-IPE200",  "length_mm": 2000.0},
    ]
    result = _run(run_weldment_cutlist(
        _ctx, json.dumps({"members": members}).encode()
    ))
    d = json.loads(result)
    assert d.get("ok") is True
    assert len(d["cutlist"]) == 2
    # Grand total must equal sum of per-profile totals
    grand = sum(c["total_mass_kg"] for c in d["cutlist"])
    assert d["grand_total_mass_kg"] == pytest.approx(grand, rel=1e-6)
    assert d["grand_total_mass_kg"] > 0.0


def test_cutlist_rollup_groups_equal_lengths():
    """Members with identical length are grouped into a single piece entry."""
    members = [
        {"profile": "SQ-50x50x3", "length_mm": 500.0},
        {"profile": "SQ-50x50x3", "length_mm": 500.0},
        {"profile": "SQ-50x50x3", "length_mm": 500.0},
    ]
    pd = lookup_profile("SQ-50x50x3")
    cl = compute_cutlist(members, pd)
    assert len(cl["pieces"]) == 1
    assert cl["pieces"][0]["quantity"] == 3
    assert cl["pieces"][0]["length_mm"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# weldment_frame tool (runner) integration tests
# ---------------------------------------------------------------------------

def test_tool_frame_ok_response():
    """weldment_frame tool returns ok:true for a valid single edge."""
    result = _run(run_weldment_frame(
        _ctx,
        json.dumps({
            "skeleton": [{"start": [0, 0, 0], "end": [1000, 0, 0]}],
            "profile": "RHS-100x50x4",
        }).encode(),
    ))
    d = json.loads(result)
    assert d.get("ok") is True
    assert d["member_count"] == 1
    assert d["members"][0]["length_mm"] == pytest.approx(1000.0)


def test_tool_frame_includes_cutlist():
    """weldment_frame result includes a cutlist with total_mass_kg."""
    result = _run(run_weldment_frame(
        _ctx,
        json.dumps({
            "skeleton": _rect_frame_skeleton(1000, 600),
            "profile": "SQ-50x50x3",
        }).encode(),
    ))
    d = json.loads(result)
    assert d["cutlist"]["total_mass_kg"] > 0.0


def test_tool_frame_gap_reduces_lengths():
    """Providing gap_mm > 0 reduces member lengths compared to gap=0."""
    skeleton = _rect_frame_skeleton(500, 500)
    profile = "SQ-50x50x3"

    r0 = json.loads(_run(run_weldment_frame(
        _ctx, json.dumps({"skeleton": skeleton, "profile": profile, "gap_mm": 0.0}).encode()
    )))
    r2 = json.loads(_run(run_weldment_frame(
        _ctx, json.dumps({"skeleton": skeleton, "profile": profile, "gap_mm": 5.0}).encode()
    )))

    total_0 = sum(m["length_mm"] for m in r0["members"])
    total_2 = sum(m["length_mm"] for m in r2["members"])
    assert total_2 < total_0


def test_tool_profile_lookup_single():
    """weldment_profile_lookup returns a single profile when designation is given."""
    result = _run(run_weldment_profile_lookup(
        _ctx,
        json.dumps({"designation": "IBEAM-IPE300"}).encode(),
    ))
    d = json.loads(result)
    assert d["ok"] is True
    assert d["profile"]["family"] == "IBEAM"


def test_tool_profile_lookup_list_family():
    """weldment_profile_lookup lists all CHS profiles when family='CHS'."""
    result = _run(run_weldment_profile_lookup(
        _ctx,
        json.dumps({"family": "CHS"}).encode(),
    ))
    d = json.loads(result)
    assert d["ok"] is True
    assert d["count"] > 5
    for p in d["profiles"]:
        assert p["family"] == "CHS"


def test_tool_profile_lookup_unknown_returns_error():
    """weldment_profile_lookup returns ok:false for an unknown designation."""
    result = _run(run_weldment_profile_lookup(
        _ctx,
        json.dumps({"designation": "UNKNOWN-9x9x9"}).encode(),
    ))
    d = json.loads(result)
    assert d.get("ok") is False


def test_tool_cutlist_empty_members_error():
    """weldment_cutlist returns an error for empty members list."""
    result = _run(run_weldment_cutlist(
        _ctx, json.dumps({"members": []}).encode()
    ))
    d = json.loads(result)
    assert "error" in d or d.get("ok") is False
