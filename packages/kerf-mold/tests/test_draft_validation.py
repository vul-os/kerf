"""
Tests for kerf_mold.draft_validation — B-rep face draft-angle validation.

Oracle coverage (all analytic, no magic numbers):

  1.  Vertical-wall box (zero draft)        → all 4 side faces fail.
  2.  Box with 2° draft + smooth            → all side faces pass (≥ 0.5°).
  3.  Box with 2° draft + SPI-A2 texture    → side faces pass (2° ≥ 0.5°).
  4.  Box with 0.5° draft + SPI-B1          → side faces fail (0.5° < 1.5° req).
  5.  Box with 0.5° draft + smooth outer    → side faces pass (0.5° ≥ 0.5°).
  6.  Inner wall (core side), smooth        → min required = 1.0°.
  7.  Rib face, smooth                      → min required = 1.0°.
  8.  Boss face, smooth                     → min required = 0.5°.
  9.  Top/bottom face (normal || pull)      → always passes regardless of finish.
 10.  Degenerate face (zero normal)         → flagged, passes=False.
 11.  Mixed shape: some pass, some fail     → per-face pass/fail correct.
 12.  Custom pull direction (+X)            → geometry consistent.
 13.  SPI grade lookup: B1 → 1.5°; D3 → 4.0°.
 14.  Unknown surface finish                → ValueError.
 15.  Zero pull direction                   → ValueError.
 16.  LLM tool round-trip: valid input      → ok=True with per_face_results.
 17.  LLM tool: invalid JSON               → error response.
 18.  LLM tool: empty faces list            → error response.
 19.  Plugin registers mold_validate_draft.

References
----------
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001 — §3.4 Draft angles.
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007
  — §4 Part geometry, draft, and moldability.
SPI Surface Finish Standard (PLASTICS Industry Association).
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

from kerf_mold.draft_validation import (
    FaceInput,
    DraftValidationReport,
    validate_draft,
    _min_draft_for_finish,
)
from kerf_mold.draft_validation_tool import (
    _VALIDATE_DRAFT_SPEC,
    run_mold_validate_draft,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vertical_face(axis: str = "x", sign: float = 1.0) -> FaceInput:
    """Return a FaceInput whose normal is perpendicular to Z (vertical wall)."""
    if axis == "x":
        return FaceInput(normal=(sign, 0.0, 0.0), face_id=f"{axis}{'+' if sign > 0 else '-'}")
    if axis == "y":
        return FaceInput(normal=(0.0, sign, 0.0), face_id=f"{axis}{'+' if sign > 0 else '-'}")
    raise ValueError(f"axis must be x or y, got {axis!r}")


def _drafted_face(draft_deg: float, axis: str = "x", sign: float = 1.0) -> FaceInput:
    """Return a FaceInput whose normal is tilted `draft_deg` from the XY plane.

    A face with `draft_deg` means its normal makes angle (90° - draft_deg)
    with the pull (+Z). So the Z component = sin(draft_rad), lateral = cos(draft_rad).
    """
    draft_rad = math.radians(draft_deg)
    z_comp = math.sin(draft_rad)
    lateral = math.cos(draft_rad)
    if axis == "x":
        return FaceInput(normal=(sign * lateral, 0.0, z_comp), face_id=f"drafted_{draft_deg}deg_{axis}")
    if axis == "y":
        return FaceInput(normal=(0.0, sign * lateral, z_comp), face_id=f"drafted_{draft_deg}deg_{axis}")
    raise ValueError(f"axis must be x or y, got {axis!r}")


def _top_face() -> FaceInput:
    return FaceInput(normal=(0.0, 0.0, 1.0), face_id="top")


def _bottom_face() -> FaceInput:
    return FaceInput(normal=(0.0, 0.0, -1.0), face_id="bottom")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# 1. Vertical-wall box (zero draft) → all 4 side faces fail
# ---------------------------------------------------------------------------

class TestZeroDraftBox:
    def test_all_four_sides_fail(self):
        faces = [
            _vertical_face("x", +1.0),
            _vertical_face("x", -1.0),
            _vertical_face("y", +1.0),
            _vertical_face("y", -1.0),
        ]
        report = validate_draft(faces, pull_direction=(0, 0, 1), surface_finish="smooth")
        assert report.faces_failing == 4
        assert report.faces_passing == 0
        for r in report.per_face_results:
            assert r.passes is False
            assert r.angle_deg == pytest.approx(0.0, abs=1e-6)

    def test_summary_mentions_4_fail(self):
        faces = [_vertical_face("x", +1.0)] * 4
        report = validate_draft(faces)
        assert "4" in report.summary


# ---------------------------------------------------------------------------
# 2. Box with 2° draft + smooth → all side faces pass
# ---------------------------------------------------------------------------

class TestTwoDegreeSmooth:
    def test_sides_pass_smooth(self):
        faces = [
            _drafted_face(2.0, "x", +1.0),
            _drafted_face(2.0, "x", -1.0),
            _drafted_face(2.0, "y", +1.0),
            _drafted_face(2.0, "y", -1.0),
        ]
        report = validate_draft(faces, surface_finish="smooth")
        assert report.faces_failing == 0
        for r in report.per_face_results:
            assert r.passes is True
            assert r.angle_deg == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# 3. 2° draft + SPI-A2 texture (mirror polish, outer min 0.5°) → pass
# ---------------------------------------------------------------------------

class TestTwoDegreeTexturedA2:
    def test_a2_min_draft(self):
        # A2 = fine diamond polish — same as smooth baseline (0.5°)
        req = _min_draft_for_finish("A2", "outer")
        assert req == pytest.approx(0.5, abs=1e-9)

    def test_2deg_a2_passes(self):
        faces = [_drafted_face(2.0, "x", +1.0)]
        report = validate_draft(faces, surface_finish="A2")
        assert report.faces_passing == 1
        assert report.faces_failing == 0


# ---------------------------------------------------------------------------
# 4. 0.5° draft + SPI-B1 (600-grit paper, min 1.5°) → fail
# ---------------------------------------------------------------------------

class TestHalfDegTexturedB1:
    def test_b1_min_draft_is_1_5deg(self):
        # B1 = 600-grit paper → 1.5° outer minimum (Menges 2001 §3.4)
        req = _min_draft_for_finish("B1", "outer")
        assert req == pytest.approx(1.5, abs=1e-9)

    def test_0_5deg_fails_b1(self):
        faces = [_drafted_face(0.5, "x", +1.0)]
        report = validate_draft(faces, surface_finish="B1")
        assert report.faces_failing == 1
        r = report.per_face_results[0]
        assert r.passes is False
        assert r.required_min_deg == pytest.approx(1.5, abs=1e-9)


# ---------------------------------------------------------------------------
# 5. 0.5° draft + smooth outer → exactly at limit → pass
# ---------------------------------------------------------------------------

class TestHalfDegSmoothOuter:
    def test_passes_at_limit(self):
        faces = [_drafted_face(0.5, "x", +1.0)]
        report = validate_draft(faces, surface_finish="smooth")
        assert report.faces_passing == 1
        r = report.per_face_results[0]
        assert r.passes is True
        assert r.required_min_deg == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# 6. Inner wall region → smooth min = 1.0°
# ---------------------------------------------------------------------------

class TestInnerWallRegion:
    def test_inner_min_is_1deg(self):
        req = _min_draft_for_finish("smooth", "inner")
        assert req == pytest.approx(1.0)

    def test_0_5deg_inner_fails(self):
        fi = FaceInput(normal=(1.0, 0.0, math.sin(math.radians(0.5))), region="inner")
        report = validate_draft([fi], surface_finish="smooth")
        assert report.faces_failing == 1

    def test_1_5deg_inner_passes(self):
        fi = FaceInput(normal=(1.0, 0.0, math.sin(math.radians(1.5))), region="inner")
        report = validate_draft([fi], surface_finish="smooth")
        assert report.faces_passing == 1


# ---------------------------------------------------------------------------
# 7. Rib face → smooth min = 1.0°
# ---------------------------------------------------------------------------

class TestRibRegion:
    def test_rib_min_is_1deg(self):
        req = _min_draft_for_finish("smooth", "rib")
        assert req == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 8. Boss face → smooth min = 0.5°
# ---------------------------------------------------------------------------

class TestBossRegion:
    def test_boss_min_is_0_5deg(self):
        req = _min_draft_for_finish("smooth", "boss")
        assert req == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 9. Top/bottom face (normal || pull) → always passes
# ---------------------------------------------------------------------------

class TestTopBottomFaces:
    def test_top_face_always_passes(self):
        report = validate_draft([_top_face()], surface_finish="B1")
        assert report.faces_passing == 1
        assert report.per_face_results[0].passes is True

    def test_bottom_face_always_passes(self):
        report = validate_draft([_bottom_face()], surface_finish="D3")
        assert report.faces_passing == 1

    def test_top_face_angle_is_90(self):
        report = validate_draft([_top_face()])
        assert report.per_face_results[0].angle_deg == pytest.approx(90.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 10. Degenerate face (zero normal) → flagged, passes=False
# ---------------------------------------------------------------------------

class TestDegenerateFace:
    def test_zero_normal_flagged(self):
        fi = FaceInput(normal=(0.0, 0.0, 0.0), face_id="degen")
        report = validate_draft([fi])
        assert report.faces_degenerate == 1
        assert report.faces_failing == 1
        r = report.per_face_results[0]
        assert r.is_degenerate is True
        assert r.passes is False
        # angle_deg is NaN for degenerate faces
        assert math.isnan(r.angle_deg)


# ---------------------------------------------------------------------------
# 11. Mixed shape: some pass, some fail
# ---------------------------------------------------------------------------

class TestMixedShape:
    def test_mixed_per_face_results(self):
        faces = [
            _top_face(),                      # pass (top/bottom)
            _bottom_face(),                   # pass (top/bottom)
            _drafted_face(2.0, "x", +1.0),   # pass smooth (2° ≥ 0.5°)
            _vertical_face("x", -1.0),       # fail (0°)
            _drafted_face(0.3, "y", +1.0),   # fail (0.3° < 0.5°)
        ]
        report = validate_draft(faces, surface_finish="smooth")
        assert report.faces_passing == 3
        assert report.faces_failing == 2
        results_by_id = {r.face_id: r for r in report.per_face_results}
        assert results_by_id["top"].passes is True
        assert results_by_id["bottom"].passes is True
        assert results_by_id["drafted_2.0deg_x"].passes is True
        assert results_by_id["x-"].passes is False
        assert results_by_id["drafted_0.3deg_y"].passes is False


# ---------------------------------------------------------------------------
# 12. Custom pull direction (+X)
# ---------------------------------------------------------------------------

class TestCustomPullDirection:
    def test_pull_x_axis(self):
        # Face normal = (1,0,0), pull = (1,0,0) → parallel → draft = 90° → pass
        fi = FaceInput(normal=(1.0, 0.0, 0.0), face_id="x_normal")
        report = validate_draft([fi], pull_direction=(1.0, 0.0, 0.0))
        assert report.faces_passing == 1
        assert report.per_face_results[0].angle_deg == pytest.approx(90.0, abs=1e-6)

    def test_pull_x_vertical_is_z_normal(self):
        # If pull = +X, then a Z-facing wall is vertical → needs draft
        fi = FaceInput(normal=(0.0, 0.0, 1.0), face_id="z_normal")
        report = validate_draft([fi], pull_direction=(1.0, 0.0, 0.0))
        assert report.per_face_results[0].angle_deg == pytest.approx(0.0, abs=1e-6)
        assert report.faces_failing == 1


# ---------------------------------------------------------------------------
# 13. SPI grade lookups
# ---------------------------------------------------------------------------

class TestSPIGradeLookup:
    def test_b1_outer(self):
        assert _min_draft_for_finish("B1", "outer") == pytest.approx(1.5)

    def test_d3_outer(self):
        assert _min_draft_for_finish("D3", "outer") == pytest.approx(4.0)

    def test_c2_outer(self):
        assert _min_draft_for_finish("C2", "outer") == pytest.approx(2.5)

    def test_spi_alias_lowercase(self):
        assert _min_draft_for_finish("b1", "outer") == pytest.approx(_min_draft_for_finish("B1", "outer"))

    def test_spi_alias_with_prefix(self):
        assert _min_draft_for_finish("spi-b1", "outer") == pytest.approx(_min_draft_for_finish("B1", "outer"))

    def test_b1_inner_adds_region_bump(self):
        # inner bump = (1.0 - 0.5) = 0.5° on top of outer 1.5° → 2.0°
        req = _min_draft_for_finish("B1", "inner")
        assert req == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 14. Unknown surface finish → ValueError
# ---------------------------------------------------------------------------

class TestUnknownFinish:
    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown surface_finish"):
            _min_draft_for_finish("X999", "outer")


# ---------------------------------------------------------------------------
# 15. Zero pull direction → ValueError
# ---------------------------------------------------------------------------

class TestZeroPullDirection:
    def test_zero_pull_raises(self):
        with pytest.raises((ValueError, ZeroDivisionError)):
            validate_draft([_top_face()], pull_direction=(0.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# 16. LLM tool round-trip: valid input → ok=True
# ---------------------------------------------------------------------------

class TestLLMToolRoundTrip:
    def test_valid_input_returns_ok(self):
        args = json.dumps({
            "faces": [
                {"normal": [0, 0, 1], "face_id": "top", "region": "outer"},
                {"normal": [1, 0, 0], "face_id": "side_x", "region": "outer"},
            ],
            "pull_direction": [0, 0, 1],
            "surface_finish": "smooth",
        }).encode()
        result = json.loads(_run(run_mold_validate_draft(CTX, args)))
        assert result.get("ok") is True
        assert "per_face_results" in result
        assert len(result["per_face_results"]) == 2
        # top face should pass, side_x (vertical) should fail
        by_id = {r["face_id"]: r for r in result["per_face_results"]}
        assert by_id["top"]["passes"] is True
        assert by_id["side_x"]["passes"] is False

    def test_textured_4_side_faces_all_fail_b1(self):
        # 4 vertical side faces + B1 texture → all fail (0° < 1.5°)
        args = json.dumps({
            "faces": [
                {"normal": [1, 0, 0]},
                {"normal": [-1, 0, 0]},
                {"normal": [0, 1, 0]},
                {"normal": [0, -1, 0]},
            ],
            "surface_finish": "B1",
        }).encode()
        result = json.loads(_run(run_mold_validate_draft(CTX, args)))
        assert result["ok"] is True
        assert result["faces_failing"] == 4
        assert result["faces_passing"] == 0

    def test_default_pull_is_z(self):
        args = json.dumps({
            "faces": [{"normal": [0, 0, 1]}],
        }).encode()
        result = json.loads(_run(run_mold_validate_draft(CTX, args)))
        assert result["ok"] is True
        assert result["pull_direction"] == pytest.approx([0.0, 0.0, 1.0], abs=1e-6)

    def test_degenerate_face_flagged_in_tool(self):
        args = json.dumps({
            "faces": [{"normal": [0, 0, 0], "face_id": "degen"}],
        }).encode()
        result = json.loads(_run(run_mold_validate_draft(CTX, args)))
        assert result["ok"] is True
        assert result["faces_degenerate"] == 1
        r = result["per_face_results"][0]
        assert r["is_degenerate"] is True
        assert r["passes"] is False
        assert r["angle_deg"] is None  # NaN serialised as None


# ---------------------------------------------------------------------------
# 17. LLM tool: invalid JSON
# ---------------------------------------------------------------------------

class TestLLMToolInvalidJSON:
    def test_invalid_json_returns_error(self):
        result = json.loads(_run(run_mold_validate_draft(CTX, b"not json")))
        assert result.get("ok") is False or "error" in result

    def test_bad_normal_returns_error(self):
        args = json.dumps({
            "faces": [{"normal": [1, 2]}],  # only 2 components
        }).encode()
        result = json.loads(_run(run_mold_validate_draft(CTX, args)))
        assert result.get("ok") is False or "error" in result


# ---------------------------------------------------------------------------
# 18. LLM tool: empty faces list
# ---------------------------------------------------------------------------

class TestLLMToolEmptyFaces:
    def test_empty_faces_returns_error(self):
        args = json.dumps({"faces": []}).encode()
        result = json.loads(_run(run_mold_validate_draft(CTX, args)))
        assert result.get("ok") is False or "error" in result

    def test_missing_faces_key_returns_error(self):
        args = json.dumps({"pull_direction": [0, 0, 1]}).encode()
        result = json.loads(_run(run_mold_validate_draft(CTX, args)))
        assert result.get("ok") is False or "error" in result


# ---------------------------------------------------------------------------
# 19. Plugin registers mold_validate_draft
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    def test_mold_validate_draft_registered(self):
        from kerf_mold.plugin import register
        from fastapi import FastAPI

        class _MockReg:
            def __init__(self):
                self.registered: dict = {}

            def register(self, name, spec, handler):
                self.registered[name] = (spec, handler)

        class _MockCtx:
            def __init__(self):
                self.tools = _MockReg()

        app = FastAPI()
        ctx = _MockCtx()

        async def _go():
            return await register(app, ctx)

        asyncio.get_event_loop().run_until_complete(_go())

        assert "mold_validate_draft" in ctx.tools.registered, (
            "mold_validate_draft not registered by plugin"
        )

    def test_tool_spec_name(self):
        assert _VALIDATE_DRAFT_SPEC.name == "mold_validate_draft"
