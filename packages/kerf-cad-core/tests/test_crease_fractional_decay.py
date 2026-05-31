"""test_crease_fractional_decay.py
===================================
GK-P14 — Tests for semi-sharp fractional crease decay
(DeRose et al. 1998 §4 / OpenSubdiv).

Run with: pytest packages/kerf-cad-core/tests/test_crease_fractional_decay.py -v
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.subd.crease_fractional_decay import (
    CreasedEdge,
    FractionalCreaseSpec,
    CreaseDecayResult,
    apply_fractional_crease_decay,
    _decay_sharpness,
    _smooth_weight,
)
from kerf_cad_core.subd.cage_area import SubdCage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_cube_cage() -> SubdCage:
    """Return a simple cube cage (8 vertices, 6 quad faces)."""
    verts = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    ]
    faces = [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [0, 1, 5, 4],
        [2, 3, 7, 6],
        [1, 2, 6, 5],
        [0, 3, 7, 4],
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


def _make_spec(
    edges: list[CreasedEdge],
    level: int,
    cage: SubdCage | None = None,
) -> FractionalCreaseSpec:
    if cage is None:
        cage = _simple_cube_cage()
    return FractionalCreaseSpec(cage=cage, edges=edges, subdivision_level=level)


# ---------------------------------------------------------------------------
# 1. Internal helpers: _decay_sharpness
# ---------------------------------------------------------------------------

class TestDecaySharpness:
    def test_level_zero_returns_unchanged(self):
        assert _decay_sharpness(3.0, 0) == 3.0

    def test_level_one_subtracts_one(self):
        assert _decay_sharpness(3.0, 1) == pytest.approx(2.0)

    def test_clamps_at_zero(self):
        assert _decay_sharpness(2.0, 5) == pytest.approx(0.0)

    def test_negative_input_clamped_to_zero(self):
        assert _decay_sharpness(-1.0, 0) == 0.0

    def test_fractional_input(self):
        assert _decay_sharpness(0.5, 1) == pytest.approx(0.0)

    def test_fractional_decay_partial(self):
        assert _decay_sharpness(1.5, 1) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 2. Internal helpers: _smooth_weight
# ---------------------------------------------------------------------------

class TestSmoothWeight:
    def test_s_zero_is_fully_smooth(self):
        assert _smooth_weight(0.0) == pytest.approx(1.0)

    def test_s_one_is_fully_sharp(self):
        assert _smooth_weight(1.0) == pytest.approx(0.0)

    def test_s_two_is_fully_sharp(self):
        assert _smooth_weight(2.0) == pytest.approx(0.0)

    def test_s_half_is_midpoint(self):
        assert _smooth_weight(0.5) == pytest.approx(0.5)

    def test_s_quarter_blend(self):
        assert _smooth_weight(0.25) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# 3. Infinite sharpness (s=100) stays sharp at all levels
# ---------------------------------------------------------------------------

class TestInfiniteSharpness:
    """Sharpness 100 ≈ ∞: still sharp after many levels."""

    def test_inf_sharp_at_level_0(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=100.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=0))
        assert res.decayed_edges[0].sharpness == pytest.approx(100.0)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(0.0)

    def test_inf_sharp_at_level_5(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=100.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=5))
        assert res.decayed_edges[0].sharpness == pytest.approx(95.0)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(0.0)

    def test_inf_sharp_at_level_99(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=100.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=99))
        assert res.decayed_edges[0].sharpness == pytest.approx(1.0)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(0.0)  # s_L=1 → sharp

    def test_inf_sharp_at_level_100(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=100.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=100))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)
        assert res.num_fully_decayed == 1

    def test_inf_sharp_num_decayed_zero_before_100_levels(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=100.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=50))
        assert res.num_fully_decayed == 0


# ---------------------------------------------------------------------------
# 4. Sharpness 2.0 across levels (standard DeRose example)
# ---------------------------------------------------------------------------

class TestSharpness2:
    """s=2.0: sharp at L=0, s=1 at L=1, s=0 at L=2+."""

    def test_level_0_sharpness(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=0))
        assert res.decayed_edges[0].sharpness == pytest.approx(2.0)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(0.0)

    def test_level_1_sharpness(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=1))
        assert res.decayed_edges[0].sharpness == pytest.approx(1.0)
        # s_L = 1.0 → clamp(1.0, 0, 1) = 1.0 → smooth_weight = 0.0 (fully sharp)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(0.0)

    def test_level_2_smooth(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=2))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(1.0)
        assert res.num_fully_decayed == 1

    def test_level_3_stays_smooth(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=3))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(1.0)
        assert res.num_fully_decayed == 1


# ---------------------------------------------------------------------------
# 5. Sharpness 0.5 (half-sharp)
# ---------------------------------------------------------------------------

class TestSharpness05:
    """s=0.5: partially blended at L=0, fully smooth at L=1."""

    def test_level_0_half_sharp(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=0.5)
        res = apply_fractional_crease_decay(_make_spec([edge], level=0))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.5)
        # smooth_weight = 1 - clamp(0.5, 0, 1) = 0.5
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(0.5)

    def test_level_1_fully_smooth(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=0.5)
        res = apply_fractional_crease_decay(_make_spec([edge], level=1))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(1.0)
        assert res.num_fully_decayed == 1


# ---------------------------------------------------------------------------
# 6. Mixed crease set
# ---------------------------------------------------------------------------

class TestMixedCreaseSet:
    """Multiple edges with different sharpness values."""

    def _make_mixed_edges(self) -> list[CreasedEdge]:
        return [
            CreasedEdge(v0_idx=0, v1_idx=1, sharpness=10.0),  # very sharp
            CreasedEdge(v0_idx=1, v1_idx=2, sharpness=3.0),   # moderately sharp
            CreasedEdge(v0_idx=2, v1_idx=3, sharpness=1.5),   # fractional
            CreasedEdge(v0_idx=3, v1_idx=0, sharpness=0.3),   # partial (will decay L=0)
        ]

    def test_level_0_all_preserved(self):
        edges = self._make_mixed_edges()
        res = apply_fractional_crease_decay(_make_spec(edges, level=0))
        assert res.decayed_edges[0].sharpness == pytest.approx(10.0)
        assert res.decayed_edges[1].sharpness == pytest.approx(3.0)
        assert res.decayed_edges[2].sharpness == pytest.approx(1.5)
        assert res.decayed_edges[3].sharpness == pytest.approx(0.3)
        assert res.num_fully_decayed == 0

    def test_level_1_each_decremented(self):
        edges = self._make_mixed_edges()
        res = apply_fractional_crease_decay(_make_spec(edges, level=1))
        assert res.decayed_edges[0].sharpness == pytest.approx(9.0)
        assert res.decayed_edges[1].sharpness == pytest.approx(2.0)
        assert res.decayed_edges[2].sharpness == pytest.approx(0.5)
        assert res.decayed_edges[3].sharpness == pytest.approx(0.0)  # 0.3 - 1 = 0
        assert res.num_fully_decayed == 1

    def test_level_3_two_decayed(self):
        edges = self._make_mixed_edges()
        res = apply_fractional_crease_decay(_make_spec(edges, level=3))
        assert res.decayed_edges[0].sharpness == pytest.approx(7.0)
        assert res.decayed_edges[1].sharpness == pytest.approx(0.0)  # 3 - 3 = 0
        assert res.decayed_edges[2].sharpness == pytest.approx(0.0)  # 1.5 - 3 = 0
        assert res.decayed_edges[3].sharpness == pytest.approx(0.0)
        assert res.num_fully_decayed == 3

    def test_max_sharpness_remaining(self):
        edges = self._make_mixed_edges()
        res = apply_fractional_crease_decay(_make_spec(edges, level=2))
        # After L=2: [8.0, 1.0, 0.0, 0.0] → max = 8.0
        assert res.max_sharpness_remaining == pytest.approx(8.0)

    def test_partial_edge_smoothing_weight(self):
        """Edge s=1.5 at L=1 → s_L=0.5 → smooth_weight=0.5."""
        edges = self._make_mixed_edges()
        res = apply_fractional_crease_decay(_make_spec(edges, level=1))
        # index 2 is s=1.5 → at L=1: s_L=0.5
        assert res.effective_dihedral_smoothing_per_edge[2] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 7. Monotonicity: effective_dihedral_smoothing increases with level
# ---------------------------------------------------------------------------

class TestMonotonicity:
    """smooth_weight for any edge must be non-decreasing as level increases."""

    def test_monotonic_increasing_s2(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        weights = []
        for L in range(6):
            res = apply_fractional_crease_decay(_make_spec([edge], level=L))
            weights.append(res.effective_dihedral_smoothing_per_edge[0])
        for i in range(len(weights) - 1):
            assert weights[i] <= weights[i + 1], (
                f"Non-monotonic at level {i}: w[{i}]={weights[i]}, w[{i+1}]={weights[i+1]}"
            )

    def test_monotonic_increasing_s15(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=1.5)
        weights = []
        for L in range(5):
            res = apply_fractional_crease_decay(_make_spec([edge], level=L))
            weights.append(res.effective_dihedral_smoothing_per_edge[0])
        for i in range(len(weights) - 1):
            assert weights[i] <= weights[i + 1], (
                f"Non-monotonic at level {i}"
            )

    def test_monotonic_increasing_s05(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=0.5)
        weights = [
            apply_fractional_crease_decay(_make_spec([edge], level=L))
            .effective_dihedral_smoothing_per_edge[0]
            for L in range(3)
        ]
        assert weights[0] <= weights[1] <= weights[2]


# ---------------------------------------------------------------------------
# 8. Empty edge list
# ---------------------------------------------------------------------------

class TestEmptyEdgeList:
    def test_empty_returns_zeros(self):
        res = apply_fractional_crease_decay(_make_spec([], level=0))
        assert res.decayed_edges == []
        assert res.effective_dihedral_smoothing_per_edge == []
        assert res.max_sharpness_remaining == pytest.approx(0.0)
        assert res.num_fully_decayed == 0


# ---------------------------------------------------------------------------
# 9. Level 0 is identity
# ---------------------------------------------------------------------------

class TestLevelZeroIsIdentity:
    def test_level_zero_unchanged(self):
        edges = [
            CreasedEdge(v0_idx=0, v1_idx=1, sharpness=3.7),
            CreasedEdge(v0_idx=2, v1_idx=3, sharpness=0.1),
        ]
        res = apply_fractional_crease_decay(_make_spec(edges, level=0))
        assert res.decayed_edges[0].sharpness == pytest.approx(3.7)
        assert res.decayed_edges[1].sharpness == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# 10. Re-export from subd package
# ---------------------------------------------------------------------------

class TestReExport:
    def test_importable_from_subd_init(self):
        from kerf_cad_core.subd import (
            CreasedEdge as CE,
            FractionalCreaseSpec as FCS,
            CreaseDecayResult as CDR,
            apply_fractional_crease_decay as afcd,
        )
        assert CE is CreasedEdge
        assert FCS is FractionalCreaseSpec
        assert CDR is CreaseDecayResult
        assert afcd is apply_fractional_crease_decay


# ---------------------------------------------------------------------------
# 11. Honest caveat is non-empty and mentions key scope limitation
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def test_caveat_non_empty(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=1))
        assert res.honest_caveat
        assert len(res.honest_caveat) > 50

    def test_caveat_mentions_schedule_only(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=1))
        caveat_lower = res.honest_caveat.lower()
        assert "schedule" in caveat_lower or "does not" in caveat_lower or "not" in caveat_lower

    def test_caveat_mentions_derose(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=0))
        assert "DeRose" in res.honest_caveat or "derose" in res.honest_caveat.lower()


# ---------------------------------------------------------------------------
# 12. Specific OpenSubdiv convention: s=10 at level 9
# ---------------------------------------------------------------------------

class TestOpenSubdivConvention:
    """s=10 (≈∞) should still be sharp at level 9, fully decayed at level 10."""

    def test_sharp_at_level_9(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=10.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=9))
        assert res.decayed_edges[0].sharpness == pytest.approx(1.0)
        # s_L=1.0 → smooth_weight=0.0 (still sharp)
        assert res.effective_dihedral_smoothing_per_edge[0] == pytest.approx(0.0)

    def test_smooth_at_level_10(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=10.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=10))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)
        assert res.num_fully_decayed == 1


# ---------------------------------------------------------------------------
# 13. Negative sharpness clamped to zero
# ---------------------------------------------------------------------------

class TestNegativeSharpnessClamped:
    def test_negative_clamped_at_input(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=-3.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=0))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)
        assert res.num_fully_decayed == 1

    def test_zero_sharpness_stays_zero(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=0.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=5))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 14. Large subdivision level (no negative sharpness)
# ---------------------------------------------------------------------------

class TestLargeSubdivisionLevel:
    def test_large_level_clamps_to_zero(self):
        edge = CreasedEdge(v0_idx=0, v1_idx=1, sharpness=5.0)
        res = apply_fractional_crease_decay(_make_spec([edge], level=1000))
        assert res.decayed_edges[0].sharpness == pytest.approx(0.0)
        assert res.decayed_edges[0].sharpness >= 0.0  # never negative

    def test_multiple_edges_all_zero_large_level(self):
        edges = [
            CreasedEdge(v0_idx=0, v1_idx=1, sharpness=2.0),
            CreasedEdge(v0_idx=1, v1_idx=2, sharpness=5.0),
            CreasedEdge(v0_idx=2, v1_idx=3, sharpness=0.5),
        ]
        res = apply_fractional_crease_decay(_make_spec(edges, level=500))
        for e in res.decayed_edges:
            assert e.sharpness == pytest.approx(0.0)
        assert res.num_fully_decayed == 3
        assert res.max_sharpness_remaining == pytest.approx(0.0)
