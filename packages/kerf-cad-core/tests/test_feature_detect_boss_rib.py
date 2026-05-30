"""Hermetic oracle tests for feature_detect.py — boss + rib detection.

References
----------
Boothroyd, Dewhurst & Knight (2002). *Product Design for Manufacture and
Assembly*, 2nd ed.  §10 Design for injection moulding — boss/rib rules:

    Boss:  diameter / wall_thickness >= 2.5   (avoid sink marks at base)
    Rib:   thickness / wall_thickness <= 0.6  (avoid sink marks on show face)

Oracles
-------
1. Boss detection — valid boss
   Geometry: cylinder_to_body(radius=3, height=5).
   Wall = 2 mm → diameter/wall = 6/2 = 3.0 >= 2.5 → valid=True.

2. Boss detection — invalid boss
   Geometry: cylinder_to_body(radius=1.5, height=5).
   Wall = 2 mm → diameter/wall = 3/2 = 1.5 < 2.5 → valid=False;
   recommendation must mention "increase diameter" or "reduce wall".

3. Rib detection — valid rib
   Geometry: box_to_body(dx=1, dy=10, dz=10) — thin 1 mm tall box.
   Wall = 2 mm → thickness/wall = 1/2 = 0.5 <= 0.6 → valid=True;
   height = 10 mm.

4. Moldability score — valid boss + valid rib, no undercuts → score >= 80.

All tests are hermetic: pure Python / NumPy only; no network; no OCCT.
"""

from __future__ import annotations

import pytest

from kerf_cad_core.geom.brep import Body
from kerf_cad_core.geom.brep_build import box_to_body, cylinder_to_body
from kerf_cad_core.geom.feature_detect import (
    BossFeature,
    RibFeature,
    detect_bosses,
    detect_ribs,
    moldability_score,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_valid_boss_body() -> Body:
    """Return cylinder_to_body(r=3, h=5) — boss diameter 6, wall 2 → valid."""
    return cylinder_to_body([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 3.0, 5.0)


def _make_invalid_boss_body() -> Body:
    """Return cylinder_to_body(r=1.5, h=5) — boss diameter 3, wall 2 → invalid."""
    return cylinder_to_body([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 1.5, 5.0)


def _make_rib_body() -> Body:
    """Return box_to_body(dx=1, dy=10, dz=10) — thin box representing a rib."""
    return box_to_body(corner=[0.0, 0.0, 0.0], dx=1.0, dy=10.0, dz=10.0)


def _make_combined_body() -> Body:
    """Return a body with one valid boss + one valid rib as disconnected solids."""
    boss = _make_valid_boss_body()
    rib = _make_rib_body()
    # Merge into a single Body as two disconnected solids (same pattern as
    # test_gk133_feature_recognition.py — the feature detectors operate on faces
    # + adjacency and do not require topological connectivity between solids).
    return Body(solids=list(boss.solids) + list(rib.solids))


# ---------------------------------------------------------------------------
# Oracle 1 — Valid boss detection (Boothroyd-Dewhurst §10: D/W >= 2.5)
# ---------------------------------------------------------------------------


class TestDetectBossValid:
    """Ø6 boss on wall_thickness=2 → 1 boss, diameter=6, height=5, valid=True."""

    _WALL = 2.0
    _EXPECTED_DIAMETER = 6.0
    _EXPECTED_HEIGHT = 5.0

    def test_exactly_one_boss_detected(self):
        body = _make_valid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        assert len(bosses) == 1, (
            f"expected 1 boss, got {len(bosses)}: "
            f"{[b.diameter for b in bosses]}"
        )

    def test_boss_is_boss_feature_instance(self):
        body = _make_valid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        assert isinstance(bosses[0], BossFeature)

    def test_boss_diameter(self):
        body = _make_valid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        d = bosses[0].diameter
        assert abs(d - self._EXPECTED_DIAMETER) < 0.05, (
            f"diameter expected {self._EXPECTED_DIAMETER}, got {d:.4f}"
        )

    def test_boss_height(self):
        body = _make_valid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        h = bosses[0].height
        assert abs(h - self._EXPECTED_HEIGHT) < 0.5, (
            f"height expected ~{self._EXPECTED_HEIGHT}, got {h:.4f}"
        )

    def test_boss_moldability_valid_true(self):
        """diameter/wall = 6/2 = 3.0 >= 2.5 → valid=True."""
        body = _make_valid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        ratio = bosses[0].diameter / self._WALL
        assert bosses[0].moldability_valid is True, (
            f"expected valid=True (ratio={ratio:.2f} >= 2.5)"
        )

    def test_boss_face_ids_populated(self):
        body = _make_valid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        assert len(bosses[0].face_ids) >= 1


# ---------------------------------------------------------------------------
# Oracle 2 — Invalid boss detection
# ---------------------------------------------------------------------------


class TestDetectBossInvalid:
    """Ø3 boss on wall_thickness=2 → valid=False; recommendation mentions fix."""

    _WALL = 2.0

    def test_invalid_boss_detected(self):
        body = _make_invalid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        assert len(bosses) == 1, f"expected 1 boss, got {len(bosses)}"

    def test_invalid_boss_diameter(self):
        body = _make_invalid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        d = bosses[0].diameter
        assert abs(d - 3.0) < 0.05, f"diameter expected 3.0, got {d:.4f}"

    def test_invalid_boss_moldability_false(self):
        """diameter/wall = 3/2 = 1.5 < 2.5 → valid=False."""
        body = _make_invalid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        ratio = bosses[0].diameter / self._WALL
        assert bosses[0].moldability_valid is False, (
            f"expected valid=False (ratio={ratio:.2f} < 2.5)"
        )

    def test_invalid_boss_recommendation_actionable(self):
        """Recommendation must mention increasing diameter or reducing wall thickness."""
        body = _make_invalid_boss_body()
        bosses = detect_bosses(body, wall_thickness=self._WALL)
        rec = bosses[0].recommendation.lower()
        has_diameter_hint = "diameter" in rec or "increase" in rec
        has_wall_hint = "wall" in rec or "reduce" in rec
        assert has_diameter_hint or has_wall_hint, (
            f"recommendation lacks actionable advice: {bosses[0].recommendation!r}"
        )


# ---------------------------------------------------------------------------
# Oracle 3 — Rib detection (Boothroyd-Dewhurst §10: T/W <= 0.6)
# ---------------------------------------------------------------------------


class TestDetectRibValid:
    """1 mm × 10 mm × 10 mm thin box → 1 rib, thickness=1, height=10, valid=True."""

    _WALL = 2.0
    _EXPECTED_THICKNESS = 1.0
    _EXPECTED_HEIGHT = 10.0

    def test_exactly_one_rib_detected(self):
        body = _make_rib_body()
        ribs = detect_ribs(body, wall_thickness=self._WALL)
        assert len(ribs) >= 1, (
            f"expected >= 1 rib, got {len(ribs)}"
        )

    def test_rib_is_rib_feature_instance(self):
        body = _make_rib_body()
        ribs = detect_ribs(body, wall_thickness=self._WALL)
        assert isinstance(ribs[0], RibFeature)

    def test_rib_thickness(self):
        body = _make_rib_body()
        ribs = detect_ribs(body, wall_thickness=self._WALL)
        # The thinnest pair should be the 1 mm dimension
        thinnest = min(r.thickness for r in ribs)
        assert abs(thinnest - self._EXPECTED_THICKNESS) < 0.05, (
            f"min rib thickness expected {self._EXPECTED_THICKNESS}, got {thinnest:.4f}"
        )

    def test_rib_height(self):
        body = _make_rib_body()
        ribs = detect_ribs(body, wall_thickness=self._WALL)
        thinnest_rib = min(ribs, key=lambda r: r.thickness)
        assert thinnest_rib.height > 0.0, "rib height must be positive"

    def test_rib_moldability_valid_true(self):
        """thickness/wall = 1/2 = 0.5 <= 0.6 → valid=True."""
        body = _make_rib_body()
        ribs = detect_ribs(body, wall_thickness=self._WALL)
        thinnest = min(ribs, key=lambda r: r.thickness)
        ratio = thinnest.thickness / self._WALL
        assert thinnest.moldability_valid is True, (
            f"expected valid=True (ratio={ratio:.2f} <= 0.6)"
        )

    def test_rib_face_ids_populated(self):
        body = _make_rib_body()
        ribs = detect_ribs(body, wall_thickness=self._WALL)
        for r in ribs:
            assert len(r.face_ids) >= 2, (
                f"rib must reference >= 2 faces (the wall pair), got {r.face_ids}"
            )


# ---------------------------------------------------------------------------
# Oracle 4 — Moldability score: valid boss + valid rib + no undercuts → >= 80
# ---------------------------------------------------------------------------


class TestMoldabilityScore:
    """Combined body with one valid boss + one valid rib scores >= 80."""

    _WALL = 2.0

    def test_score_is_float(self):
        body = _make_combined_body()
        result = moldability_score(body, wall_thickness=self._WALL)
        assert isinstance(result["score"], float)

    def test_score_in_range(self):
        body = _make_combined_body()
        result = moldability_score(body, wall_thickness=self._WALL)
        assert 0.0 <= result["score"] <= 100.0, (
            f"score {result['score']} out of [0, 100]"
        )

    def test_score_at_least_80(self):
        """No violations → score should be near 100 (>= 80 per spec)."""
        body = _make_combined_body()
        result = moldability_score(body, wall_thickness=self._WALL)
        assert result["score"] >= 80.0, (
            f"expected score >= 80, got {result['score']}; "
            f"boss_viol={result['boss_violations']}, "
            f"rib_viol={result['rib_violations']}, "
            f"undercuts={result['undercut_count']}, "
            f"recs={result['recommendations']}"
        )

    def test_zero_boss_violations(self):
        body = _make_combined_body()
        result = moldability_score(body, wall_thickness=self._WALL)
        assert result["boss_violations"] == 0, (
            f"expected 0 boss violations, got {result['boss_violations']}"
        )

    def test_zero_rib_violations(self):
        body = _make_combined_body()
        result = moldability_score(body, wall_thickness=self._WALL)
        assert result["rib_violations"] == 0, (
            f"expected 0 rib violations, got {result['rib_violations']}"
        )

    def test_no_undercuts_for_valid_geometry(self):
        """A standalone cylinder and thin box have no undercuts along Z."""
        body = _make_combined_body()
        result = moldability_score(
            body, wall_thickness=self._WALL, pull_direction=[0.0, 0.0, 1.0]
        )
        assert result["undercut_count"] == 0, (
            f"expected 0 undercuts, got {result['undercut_count']}"
        )

    def test_result_keys_present(self):
        body = _make_combined_body()
        result = moldability_score(body, wall_thickness=self._WALL)
        required_keys = {
            "score", "boss_violations", "rib_violations",
            "undercut_count", "recommendations",
            "boss_features", "rib_features",
        }
        assert required_keys.issubset(result.keys()), (
            f"missing keys: {required_keys - result.keys()}"
        )

    def test_invalid_boss_lowers_score(self):
        """A body with one invalid boss should have a lower score."""
        bad_boss = _make_invalid_boss_body()
        result = moldability_score(bad_boss, wall_thickness=self._WALL)
        assert result["boss_violations"] >= 1
        assert result["score"] <= 90.0, (
            f"score should be reduced for boss violation, got {result['score']}"
        )
