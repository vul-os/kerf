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
    FaceData,
    FaceInput,
    DraftValidationReport,
    UndercutReport,
    UndercutSpec,
    detect_undercuts,
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


# ===========================================================================
# Undercut Detection Tests (detect_undercuts / Menges §6.4)
# ===========================================================================
#
# 20. Simple cube — no undercuts
# 21. Boss with negative draft — detected as direct undercut
# 22. Side-action ribbed feature — requires_side_action=True
# 23. Lifter for deep groove — requires_lifter=True
# 24. Vertical walls classified correctly
# 25. Empty face list — graceful no-undercut report
# 26. Severity progression: none / minor / major / severe
# 27. Hidden undercut via shadow region (bounding-box overlap)
# 28. Pull direction other than +Z
# 29. Faces above parting line are not undercuts even with back-facing normal
# 30. UndercutReport dataclass fields present and correctly typed
# ===========================================================================


def _make_fd(
    normal,
    centroid_z=0.0,
    face_id="face",
    x_extent=None,
    y_extent=None,
):
    """Convenience: build a FaceData."""
    return FaceData(
        normal=normal,
        centroid_z=centroid_z,
        face_id=face_id,
        x_extent=x_extent,
        y_extent=y_extent,
    )


# ---------------------------------------------------------------------------
# 20. Simple cube — no undercuts
# ---------------------------------------------------------------------------

class TestSimpleCubeNoUndercut:
    """A cube whose six faces all have normals along ±X/Y/Z.

    Pull direction = +Z, parting plane at z=0.
    Top face (normal +Z, centroid_z=10) and bottom face (normal -Z, centroid_z=0)
    are on the parting plane / above it.  The four side faces have θ=90° and are
    classified as vertical walls, not undercuts.
    """

    def _cube_spec(self):
        faces = [
            _make_fd((0, 0, 1),  centroid_z=10.0, face_id="top"),
            _make_fd((0, 0, -1), centroid_z=0.0,  face_id="bottom"),
            _make_fd((1, 0, 0),  centroid_z=5.0,  face_id="side_x+"),
            _make_fd((-1, 0, 0), centroid_z=5.0,  face_id="side_x-"),
            _make_fd((0, 1, 0),  centroid_z=5.0,  face_id="side_y+"),
            _make_fd((0, -1, 0), centroid_z=5.0,  face_id="side_y-"),
        ]
        return UndercutSpec(faces=faces, pull_direction_xyz=(0, 0, 1), parting_z_mm=0.0)

    def test_no_direct_undercuts(self):
        report = detect_undercuts(self._cube_spec())
        assert report.undercut_face_indices == []

    def test_no_hidden_undercuts(self):
        report = detect_undercuts(self._cube_spec())
        assert report.hidden_undercut_face_indices == []

    def test_severity_none(self):
        report = detect_undercuts(self._cube_spec())
        assert report.severity == "none"

    def test_no_side_action_required(self):
        report = detect_undercuts(self._cube_spec())
        assert report.requires_side_action is False

    def test_no_lifter_required(self):
        report = detect_undercuts(self._cube_spec())
        assert report.requires_lifter is False


# ---------------------------------------------------------------------------
# 21. Boss with negative draft — detected as direct undercut
# ---------------------------------------------------------------------------

class TestBossNegativeDraft:
    """A boss feature whose side wall has a back-draft (normal tilts back
    toward the parting line — θ > 90°).

    The face is below the parting plane → direct undercut.
    """

    def _boss_spec(self):
        # Normal tilted 10° back into cavity: points roughly -Z + lateral.
        # With pull +Z: dot = n̂·p̂ = -sin(10°) → θ = acos(-sin(10°)) ≈ 100°
        angle_rad = math.radians(10.0)
        boss_normal = (math.cos(angle_rad), 0.0, -math.sin(angle_rad))
        # Place boss below parting plane (z=-5, parting at z=0)
        faces = [
            _make_fd(boss_normal, centroid_z=-5.0, face_id="boss_back_draft"),
            _make_fd((0, 0, 1),   centroid_z=10.0,  face_id="top"),
        ]
        return UndercutSpec(faces=faces, pull_direction_xyz=(0, 0, 1), parting_z_mm=0.0)

    def test_boss_is_undercut(self):
        report = detect_undercuts(self._boss_spec())
        assert 0 in report.undercut_face_indices

    def test_top_not_undercut(self):
        report = detect_undercuts(self._boss_spec())
        assert 1 not in report.undercut_face_indices

    def test_requires_lifter(self):
        report = detect_undercuts(self._boss_spec())
        assert report.requires_lifter is True

    def test_severity_at_least_minor(self):
        report = detect_undercuts(self._boss_spec())
        assert report.severity in ("minor", "major", "severe")


# ---------------------------------------------------------------------------
# 22. Side-action ribbed feature — requires_side_action=True
# ---------------------------------------------------------------------------

class TestSideActionRib:
    """A ribbed feature below the parting line.

    Three back-drafted rib faces below the parting plane → major severity →
    requires_side_action=True.
    """

    def _rib_spec(self, n_rib_faces=3):
        angle_rad = math.radians(15.0)
        rib_normal = (math.cos(angle_rad), 0.0, -math.sin(angle_rad))
        faces = []
        for k in range(n_rib_faces):
            faces.append(_make_fd(
                rib_normal, centroid_z=-10.0,
                face_id=f"rib_{k}",
            ))
        faces.append(_make_fd((0, 0, 1), centroid_z=10.0, face_id="top"))
        return UndercutSpec(faces=faces, pull_direction_xyz=(0, 0, 1), parting_z_mm=0.0)

    def test_requires_side_action(self):
        report = detect_undercuts(self._rib_spec(3))
        assert report.requires_side_action is True

    def test_severity_major_for_three_undercuts(self):
        report = detect_undercuts(self._rib_spec(3))
        assert report.severity in ("major", "severe")

    def test_all_rib_faces_detected(self):
        report = detect_undercuts(self._rib_spec(3))
        assert len(report.undercut_face_indices) == 3


# ---------------------------------------------------------------------------
# 23. Lifter for deep groove — requires_lifter=True
# ---------------------------------------------------------------------------

class TestLifterForDeepGroove:
    """One internal groove face has a back-draft below the parting line.

    Single direct undercut → minor severity but requires_lifter=True.
    """

    def _groove_spec(self):
        # Back-drafted by 5°
        angle_rad = math.radians(5.0)
        groove_normal = (0.0, math.cos(angle_rad), -math.sin(angle_rad))
        faces = [
            _make_fd(groove_normal, centroid_z=-3.0, face_id="groove_back"),
            _make_fd((0, 0, 1),     centroid_z=10.0, face_id="top"),
            _make_fd((0, 0, -1),    centroid_z=0.0,  face_id="bottom"),
        ]
        return UndercutSpec(faces=faces, pull_direction_xyz=(0, 0, 1), parting_z_mm=0.0)

    def test_requires_lifter(self):
        report = detect_undercuts(self._groove_spec())
        assert report.requires_lifter is True

    def test_groove_face_is_undercut(self):
        report = detect_undercuts(self._groove_spec())
        assert 0 in report.undercut_face_indices

    def test_severity_minor_single_undercut(self):
        report = detect_undercuts(self._groove_spec())
        assert report.severity == "minor"


# ---------------------------------------------------------------------------
# 24. Vertical walls classified correctly
# ---------------------------------------------------------------------------

class TestVerticalWallClassification:
    """Faces with θ ≈ 90° (normals exactly perpendicular to pull) should
    appear in vertical_wall_face_indices and NOT in undercut indices."""

    def _spec(self):
        faces = [
            _make_fd((1, 0, 0), centroid_z=5.0, face_id="side_x"),
            _make_fd((0, 1, 0), centroid_z=5.0, face_id="side_y"),
        ]
        return UndercutSpec(faces=faces, pull_direction_xyz=(0, 0, 1), parting_z_mm=0.0)

    def test_vertical_walls_detected(self):
        report = detect_undercuts(self._spec())
        assert len(report.vertical_wall_face_indices) == 2

    def test_vertical_walls_not_undercuts(self):
        report = detect_undercuts(self._spec())
        for i in report.vertical_wall_face_indices:
            assert i not in report.undercut_face_indices

    def test_severity_none(self):
        report = detect_undercuts(self._spec())
        assert report.severity == "none"


# ---------------------------------------------------------------------------
# 25. Empty face list — graceful no-undercut report
# ---------------------------------------------------------------------------

class TestEmptyFaceList:
    def test_empty_faces_severity_none(self):
        spec = UndercutSpec(faces=[], pull_direction_xyz=(0, 0, 1), parting_z_mm=0.0)
        report = detect_undercuts(spec)
        assert report.severity == "none"
        assert report.undercut_face_indices == []
        assert report.hidden_undercut_face_indices == []
        assert report.requires_side_action is False
        assert report.requires_lifter is False


# ---------------------------------------------------------------------------
# 26. Severity progression: none / minor / major / severe
# ---------------------------------------------------------------------------

class TestSeverityProgression:
    """Build specs with increasing numbers of back-drafted faces to exercise
    each severity bucket."""

    @staticmethod
    def _back_drafted_faces(n: int):
        angle_rad = math.radians(10.0)
        normal = (math.cos(angle_rad), 0.0, -math.sin(angle_rad))
        return [_make_fd(normal, centroid_z=-5.0, face_id=f"u{k}") for k in range(n)]

    def test_zero_undercuts_is_none(self):
        spec = UndercutSpec(
            faces=[_make_fd((0, 0, 1), centroid_z=10.0)],
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )
        report = detect_undercuts(spec)
        assert report.severity == "none"

    def test_one_undercut_is_minor(self):
        spec = UndercutSpec(
            faces=self._back_drafted_faces(1),
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )
        report = detect_undercuts(spec)
        assert report.severity == "minor"

    def test_two_undercuts_is_minor(self):
        spec = UndercutSpec(
            faces=self._back_drafted_faces(2),
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )
        report = detect_undercuts(spec)
        assert report.severity == "minor"

    def test_three_undercuts_is_major(self):
        spec = UndercutSpec(
            faces=self._back_drafted_faces(3),
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )
        report = detect_undercuts(spec)
        assert report.severity == "major"

    def test_six_undercuts_is_severe(self):
        spec = UndercutSpec(
            faces=self._back_drafted_faces(6),
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )
        report = detect_undercuts(spec)
        assert report.severity == "severe"


# ---------------------------------------------------------------------------
# 27. Hidden undercut via shadow region (bounding-box overlap)
# ---------------------------------------------------------------------------

class TestHiddenUndercut:
    """Face A is below the parting line, has positive draft (θ < 90°), but is
    shadowed by an overhanging face B directly above it (same XY footprint,
    higher centroid_z).  Face A → hidden undercut.
    """

    def _spec(self):
        # Face A: below parting (z=-5), slight inward draft (θ ≈ 80° < 90°)
        # Normal tilts toward +Z: dot = sin(10°) → θ = acos(sin(10°)) ≈ 80°
        angle_rad = math.radians(10.0)
        face_a_normal = (math.cos(angle_rad), 0.0, math.sin(angle_rad))
        face_a = _make_fd(
            face_a_normal, centroid_z=-5.0, face_id="under_shelf",
            x_extent=(0.0, 10.0), y_extent=(0.0, 10.0),
        )
        # Face B: above (z=5), overhanging, same XY footprint
        face_b = _make_fd(
            (0.0, 0.0, 1.0), centroid_z=5.0, face_id="overhang",
            x_extent=(0.0, 10.0), y_extent=(0.0, 10.0),
        )
        return UndercutSpec(
            faces=[face_a, face_b],
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )

    def test_hidden_undercut_detected(self):
        report = detect_undercuts(self._spec())
        assert 0 in report.hidden_undercut_face_indices

    def test_overhang_not_flagged(self):
        report = detect_undercuts(self._spec())
        assert 1 not in report.hidden_undercut_face_indices
        assert 1 not in report.undercut_face_indices

    def test_requires_side_action(self):
        report = detect_undercuts(self._spec())
        assert report.requires_side_action is True

    def test_non_overlapping_extents_no_hidden_undercut(self):
        """If the overhanging face is laterally offset, no shadow → no hidden undercut."""
        angle_rad = math.radians(10.0)
        face_a_normal = (math.cos(angle_rad), 0.0, math.sin(angle_rad))
        face_a = _make_fd(
            face_a_normal, centroid_z=-5.0, face_id="under_shelf",
            x_extent=(0.0, 10.0), y_extent=(0.0, 10.0),
        )
        # Face B shifted far away on X axis (no overlap)
        face_b = _make_fd(
            (0.0, 0.0, 1.0), centroid_z=5.0, face_id="overhang",
            x_extent=(20.0, 30.0), y_extent=(0.0, 10.0),
        )
        spec = UndercutSpec(
            faces=[face_a, face_b],
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )
        report = detect_undercuts(spec)
        assert 0 not in report.hidden_undercut_face_indices


# ---------------------------------------------------------------------------
# 28. Pull direction other than +Z
# ---------------------------------------------------------------------------

class TestCustomPullDirectionUndercut:
    """With pull direction = +X, a face normal pointing -X below the parting
    plane (here parting_z_mm is interpreted as parting coordinate in the
    Z axis — but centroid_z is still the Z-coord; we use parting_z=0 and
    place face with centroid_z < 0 to be "below" parting).

    Face with normal (-1, 0, 0) and pull +X: dot = -1 → θ = 180° > 90° → undercut.
    """

    def _spec(self):
        faces = [
            _make_fd((-1, 0, 0), centroid_z=-5.0, face_id="back_x"),
            _make_fd((1, 0, 0),  centroid_z=5.0,  face_id="front_x"),
        ]
        return UndercutSpec(
            faces=faces,
            pull_direction_xyz=(1, 0, 0),
            parting_z_mm=0.0,
        )

    def test_back_face_is_undercut(self):
        report = detect_undercuts(self._spec())
        assert 0 in report.undercut_face_indices

    def test_front_face_not_undercut(self):
        report = detect_undercuts(self._spec())
        assert 1 not in report.undercut_face_indices


# ---------------------------------------------------------------------------
# 29. Faces ABOVE parting line with back-facing normal are NOT undercuts
# ---------------------------------------------------------------------------

class TestAbovePartingNotUndercut:
    """A face with a back-drafted normal (θ > 90°) but centroid_z >= parting_z
    is on the cavity side and will not be scraped — not an undercut.
    """

    def _spec(self):
        angle_rad = math.radians(10.0)
        back_normal = (math.cos(angle_rad), 0.0, -math.sin(angle_rad))
        faces = [
            # centroid_z=5.0 which is >= parting_z_mm=0 → NOT below parting
            _make_fd(back_normal, centroid_z=5.0, face_id="above_parting_back"),
        ]
        return UndercutSpec(faces=faces, pull_direction_xyz=(0, 0, 1), parting_z_mm=0.0)

    def test_above_parting_not_undercut(self):
        report = detect_undercuts(self._spec())
        assert 0 not in report.undercut_face_indices

    def test_severity_none(self):
        report = detect_undercuts(self._spec())
        assert report.severity == "none"


# ---------------------------------------------------------------------------
# 30. UndercutReport dataclass fields present and correctly typed
# ---------------------------------------------------------------------------

class TestUndercutReportFields:
    def test_report_has_required_fields(self):
        spec = UndercutSpec(
            faces=[_make_fd((0, 0, 1), centroid_z=5.0)],
            pull_direction_xyz=(0, 0, 1),
            parting_z_mm=0.0,
        )
        report = detect_undercuts(spec)
        assert isinstance(report.undercut_face_indices, list)
        assert isinstance(report.hidden_undercut_face_indices, list)
        assert isinstance(report.vertical_wall_face_indices, list)
        assert report.severity in ("none", "minor", "major", "severe")
        assert isinstance(report.requires_side_action, bool)
        assert isinstance(report.requires_lifter, bool)
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 0

    def test_undercut_spec_defaults(self):
        spec = UndercutSpec(faces=[_make_fd((0, 0, 1))])
        assert spec.pull_direction_xyz == (0.0, 0.0, 1.0)
        assert spec.parting_z_mm == 0.0
        assert spec.undercut_threshold_deg == 90.0
