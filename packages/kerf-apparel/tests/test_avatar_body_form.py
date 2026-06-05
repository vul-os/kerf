"""
Tests for kerf_apparel.avatar — parametric dress-form generator.

DoD oracles
-----------
1. build_body_form returns a BodyForm with expected landmark count.
2. Girth at bust landmark matches the supplied bust_cm within 0.01 cm.
3. Girth at waist landmark matches the supplied waist_cm within 0.01 cm.
4. Girth at hip landmark matches the supplied hip_cm within 0.01 cm.
5. body_form_girth interpolation is bounded.
6. body_form_to_obj produces valid OBJ starting with '#' comment.
7. Mesh is water-tight: vertex count and face count are positive.
8. build_body_form raises ValueError on nonsense inputs.
9. body_form_landmark_summary returns dict with at least 10 keys.
10. Female vs male forms differ in cross-section depth (fb_ratio difference).
11. run_avatar_body_form LLM tool returns expected payload keys.
12. run_avatar_body_form with include_obj=False omits OBJ string.
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_apparel.avatar import (
    build_body_form,
    body_form_girth,
    body_form_to_obj,
    body_form_landmark_summary,
    LANDMARK_HEIGHTS,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. Landmark count
# ---------------------------------------------------------------------------

class TestBuildBodyForm:
    def test_landmark_count(self):
        bf = build_body_form()
        assert len(bf.landmarks) == len(LANDMARK_HEIGHTS)

    def test_landmark_names_present(self):
        bf = build_body_form()
        for name in ("bust", "waist", "hip", "knee", "neck"):
            assert name in bf.landmarks, f"missing landmark: {name}"

    def test_bust_girth_matches(self):
        bust = 96.0
        bf = build_body_form(bust_cm=bust)
        g = bf.landmarks["bust"].girth_cm
        assert abs(g - bust) < 0.01, f"bust girth {g:.3f} != {bust}"

    def test_waist_girth_matches(self):
        waist = 72.0
        bf = build_body_form(waist_cm=waist)
        g = bf.landmarks["waist"].girth_cm
        assert abs(g - waist) < 0.01

    def test_hip_girth_matches(self):
        hip = 100.0
        bf = build_body_form(hip_cm=hip)
        g = bf.landmarks["hip"].girth_cm
        assert abs(g - hip) < 0.01

    def test_mesh_positive(self):
        bf = build_body_form()
        assert bf.vertices is not None
        assert bf.faces is not None
        assert len(bf.vertices) > 0
        assert len(bf.faces) > 0

    def test_face_indices_in_range(self):
        bf = build_body_form(n_vertices_per_ring=16)
        n_verts = len(bf.vertices)
        assert bf.faces.max() < n_verts

    def test_female_vs_male_depth(self):
        """Male form has larger b/a ratio → deeper cross-section at bust."""
        f = build_body_form(sex="female")
        m = build_body_form(sex="male")
        b_f = f.landmarks["bust"].b_cm
        b_m = m.landmarks["bust"].b_cm
        # Male ratio is 0.75, female is 0.72 → male has relatively larger b
        assert b_m > b_f, f"male b {b_m:.3f} <= female b {b_f:.3f}"

    def test_invalid_height_raises(self):
        with pytest.raises(ValueError, match="height_cm"):
            build_body_form(height_cm=-1.0)

    def test_invalid_sex_raises(self):
        with pytest.raises(ValueError, match="sex"):
            build_body_form(sex="robot")

    def test_zero_bust_raises(self):
        with pytest.raises(ValueError):
            build_body_form(bust_cm=0.0)


# ---------------------------------------------------------------------------
# 2. Girth interpolation
# ---------------------------------------------------------------------------

class TestBodyFormGirth:
    def test_girth_at_bust_landmark(self):
        bf = build_body_form(bust_cm=92.0, waist_cm=74.0, hip_cm=96.0)
        g_bust = body_form_girth(bf, LANDMARK_HEIGHTS["bust"])
        assert abs(g_bust - 92.0) < 0.02

    def test_girth_bounded_floor(self):
        bf = build_body_form()
        g = body_form_girth(bf, 0.0)
        assert g > 0

    def test_girth_bounded_crown(self):
        bf = build_body_form()
        g = body_form_girth(bf, 1.0)
        assert g > 0

    def test_girth_clamp_negative(self):
        bf = build_body_form()
        g_neg = body_form_girth(bf, -0.5)
        g_zero = body_form_girth(bf, 0.0)
        assert g_neg == g_zero

    def test_girth_mid_positive(self):
        bf = build_body_form()
        g_mid = body_form_girth(bf, 0.5)
        assert g_mid > 0


# ---------------------------------------------------------------------------
# 3. OBJ export
# ---------------------------------------------------------------------------

class TestBodyFormToObj:
    def test_obj_has_vertex_lines(self):
        bf = build_body_form(n_vertices_per_ring=8)
        obj = body_form_to_obj(bf)
        v_lines = [l for l in obj.splitlines() if l.startswith("v ")]
        assert len(v_lines) == len(bf.vertices)

    def test_obj_has_face_lines(self):
        bf = build_body_form(n_vertices_per_ring=8)
        obj = body_form_to_obj(bf)
        f_lines = [l for l in obj.splitlines() if l.startswith("f ")]
        assert len(f_lines) == len(bf.faces)

    def test_obj_starts_with_comment(self):
        bf = build_body_form(n_vertices_per_ring=8)
        obj = body_form_to_obj(bf)
        assert obj.startswith("#")

    def test_obj_face_indices_1based(self):
        """OBJ face indices must be >= 1."""
        bf = build_body_form(n_vertices_per_ring=8)
        obj = body_form_to_obj(bf)
        for line in obj.splitlines():
            if line.startswith("f "):
                indices = [int(i) for i in line.split()[1:]]
                assert all(idx >= 1 for idx in indices)


# ---------------------------------------------------------------------------
# 4. Landmark summary
# ---------------------------------------------------------------------------

class TestLandmarkSummary:
    def test_returns_dict_with_keys(self):
        bf = build_body_form()
        s = body_form_landmark_summary(bf)
        assert isinstance(s, dict)
        assert len(s) >= 10

    def test_each_entry_has_required_fields(self):
        bf = build_body_form()
        s = body_form_landmark_summary(bf)
        for name, entry in s.items():
            assert "z_cm" in entry
            assert "girth_cm" in entry
            assert "half_width_cm" in entry
            assert "half_depth_cm" in entry


# ---------------------------------------------------------------------------
# 5. LLM tool dispatch
# ---------------------------------------------------------------------------

def _dispatch_avatar(params: dict) -> dict:
    """Call the LLM tool handler and parse the JSON response."""
    from kerf_apparel._compat import ProjectCtx
    from kerf_apparel.tools import run_avatar_body_form
    ctx = ProjectCtx()
    raw = _run(run_avatar_body_form(ctx, json.dumps(params).encode()))
    return json.loads(raw)


def _is_success(d: dict) -> bool:
    """ok_payload returns the payload directly; no 'ok' key — success = no 'error' key."""
    return "error" not in d


def _is_error(d: dict) -> bool:
    return "error" in d


class TestAvatarBodyFormTool:
    def test_default_params(self):
        result = _dispatch_avatar({})
        assert _is_success(result), f"unexpected error: {result.get('error')}"
        assert "landmarks" in result
        assert "n_vertices" in result
        assert "n_faces" in result

    def test_custom_measurements(self):
        result = _dispatch_avatar({
            "height_cm": 175.0,
            "bust_cm": 100.0,
            "waist_cm": 82.0,
            "hip_cm": 104.0,
            "sex": "female",
        })
        assert _is_success(result)
        assert result["bust_cm"] == 100.0

    def test_include_obj_true(self):
        result = _dispatch_avatar({"include_obj": True, "n_vertices_per_ring": 8})
        assert _is_success(result)
        assert "obj" in result
        assert result["obj"].startswith("#")

    def test_include_obj_false(self):
        result = _dispatch_avatar({"include_obj": False, "n_vertices_per_ring": 8})
        assert _is_success(result)
        assert "obj" not in result

    def test_male_sex(self):
        result = _dispatch_avatar({"sex": "male", "include_obj": False})
        assert _is_success(result)
        assert result["sex"] == "male"

    def test_invalid_height(self):
        result = _dispatch_avatar({"height_cm": -5.0})
        assert _is_error(result)

    def test_landmark_bust_girth_close(self):
        bust = 88.0
        result = _dispatch_avatar({"bust_cm": bust, "include_obj": False})
        assert _is_success(result)
        bust_lm = result["landmarks"].get("bust", {})
        assert abs(bust_lm.get("girth_cm", 0) - bust) < 0.02

    def test_method_label_in_response(self):
        result = _dispatch_avatar({"include_obj": False})
        assert _is_success(result)
        assert "CAESAR" in result.get("method", "")

    def test_n_slices_positive(self):
        result = _dispatch_avatar({"include_obj": False})
        assert _is_success(result)
        assert result["n_slices"] > 0
        assert result["n_vertices"] > 0
        assert result["n_faces"] > 0
