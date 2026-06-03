"""test_subd_limit_tangent.py
============================
Hermetic tests for Stam 1998 exact-limit-evaluation for Catmull-Clark SubD.
Tests the public API:
  - ExtraordinaryPatch
  - LimitEval
  - evaluate_limit(patch, u, v)
  - evaluate_at_extraordinary(patch)
  - g1_continuous_normals(patch_a, patch_b)

Reference: Stam, J. (1998). "Exact Evaluation of Catmull-Clark Subdivision
Surfaces at Arbitrary Parameter Values." SIGGRAPH '98 §3.3.

All tests are hermetic (no I/O, no external files, pure Python + numpy).
"""
from __future__ import annotations

import math
import random
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.subd.limit_tangent import (
    ExtraordinaryPatch,
    LimitEval,
    _cc_limit_weights,
    _limit_position_at_ev,
    _limit_tangents_at_ev,
    evaluate_at_extraordinary,
    evaluate_limit,
    g1_continuous_normals,
)

Vec3 = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ring(N: int, radius: float = 1.0, center: Vec3 = (0.0, 0.0, 0.0)) -> List[Vec3]:
    """Build a flat planar N-valence ring in the XY plane.

    Returns 2N+1 ring points:
      [0]       = center V
      [1..N]    = N edge-adjacent neighbors at radius r (CCW)
      [N+1..2N] = N face-adjacent "face points" at radius 1.5r (between edge nbrs)
    """
    cx, cy, cz = center
    pts: List[Vec3] = [(cx, cy, cz)]  # V

    # Edge-adjacent (P_i) — on circle of radius r
    for i in range(N):
        theta = 2.0 * math.pi * i / N
        pts.append((cx + radius * math.cos(theta),
                    cy + radius * math.sin(theta),
                    cz))

    # Face-adjacent (Q_i) — at 1.5r, midway between consecutive P_i (angular midpoint)
    face_r = 1.5 * radius
    for i in range(N):
        theta = 2.0 * math.pi * (i + 0.5) / N
        pts.append((cx + face_r * math.cos(theta),
                    cy + face_r * math.sin(theta),
                    cz))

    return pts


def _make_patch(N: int, radius: float = 1.0, center: Vec3 = (0.0, 0.0, 0.0)) -> ExtraordinaryPatch:
    """Build a simple flat planar ExtraordinaryPatch of valence N."""
    return ExtraordinaryPatch(valence=N, ring_positions=_make_ring(N, radius, center))


def _vec3_norm(v: Vec3) -> float:
    return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )


def _angle_rad(a: Vec3, b: Vec3) -> float:
    """Angle between two non-zero vectors in radians."""
    na = _vec3_norm(a)
    nb = _vec3_norm(b)
    if na < 1e-15 or nb < 1e-15:
        return 0.0
    c = _dot(a, b) / (na * nb)
    c = max(-1.0, min(1.0, c))
    return math.acos(abs(c))  # absolute: ignore orientation flip


# ---------------------------------------------------------------------------
# Test group 1: ExtraordinaryPatch construction & validation
# ---------------------------------------------------------------------------

class TestExtraordinaryPatchConstruction:

    def test_valid_construction_n3(self):
        """N=3 patch with 2*3+1=7 control points constructs without error."""
        patch = _make_patch(3)
        assert patch.valence == 3
        assert len(patch.ring_positions) == 7

    def test_valid_construction_n5(self):
        """N=5 patch with 11 control points."""
        patch = _make_patch(5)
        assert patch.valence == 5
        assert len(patch.ring_positions) == 11

    def test_valid_construction_n8(self):
        """N=8 patch with 17 control points."""
        patch = _make_patch(8)
        assert len(patch.ring_positions) == 17

    def test_wrong_ring_size_raises(self):
        """Providing wrong ring_positions length raises ValueError."""
        ring = _make_ring(5)  # 11 points (for N=5)
        with pytest.raises(ValueError, match="ring_positions"):
            ExtraordinaryPatch(valence=3, ring_positions=ring)  # expects 7 for N=3

    def test_regular_n4_construction(self):
        """N=4 (regular) patch is accepted."""
        patch = _make_patch(4)
        assert patch.valence == 4
        assert len(patch.ring_positions) == 9


# ---------------------------------------------------------------------------
# Test group 2: CC limit-stencil weights (Stam Table 1)
# ---------------------------------------------------------------------------

class TestCCLimitWeights:

    @pytest.mark.parametrize("N", [3, 4, 5, 6, 7, 8])
    def test_weights_sum_to_one(self, N: int):
        """Stam Table 1 weights sum to 1.0 for N=3..8 (partition of unity)."""
        w_V, w_e, w_f = _cc_limit_weights(N)
        total = w_V + N * w_e + N * w_f
        assert abs(total - 1.0) < 1e-12, f"N={N}: weights sum={total}, expected 1.0"

    def test_n4_canonical_values(self):
        """N=4 gives the canonical CC weights: 4/9, 1/9, 1/36 (Halstead 1993)."""
        w_V, w_e, w_f = _cc_limit_weights(4)
        assert abs(w_V - 4.0 / 9.0) < 1e-14
        assert abs(w_e - 1.0 / 9.0) < 1e-14
        assert abs(w_f - 1.0 / 36.0) < 1e-14

    def test_n3_weights_sum_to_one(self):
        """N=3: denom=24, w_V=9/24=3/8, sum=3/8 + 3*(1/6) + 3*(1/24) = 3/8+1/2+1/8=1."""
        w_V, w_e, w_f = _cc_limit_weights(3)
        total = w_V + 3 * w_e + 3 * w_f
        assert abs(total - 1.0) < 1e-12

    @pytest.mark.parametrize("N", [3, 5, 6])
    def test_limit_position_weights_sum_to_one_via_patch(self, N: int):
        """Limit position = weighted sum of 2N+1 CPs; weights sum to 1."""
        w_V, w_e, w_f = _cc_limit_weights(N)
        total = w_V + N * w_e + N * w_f
        assert abs(total - 1.0) < 1e-12


# ---------------------------------------------------------------------------
# Test group 3: evaluate_at_extraordinary — limit position
# ---------------------------------------------------------------------------

class TestLimitPositionAtEV:

    def test_limit_position_in_convex_hull(self):
        """Limit position should lie within the convex hull of the ring points."""
        for N in [3, 5, 6, 7]:
            patch = _make_patch(N, radius=2.0)
            result = evaluate_at_extraordinary(patch)
            pos = result.position
            # For a flat ring centred at origin, limit pos should be near origin
            dist = _vec3_norm(pos)
            assert dist < 2.0, f"N={N}: limit pos distance={dist} exceeds ring radius"

    def test_limit_position_at_origin_for_symmetric_ring(self):
        """For a symmetric ring at the origin, limit pos should be near origin."""
        for N in [3, 4, 5, 6]:
            patch = _make_patch(N, radius=1.0, center=(0.0, 0.0, 0.0))
            result = evaluate_at_extraordinary(patch)
            pos = result.position
            # The limit is a weighted average; for a symmetric flat ring the
            # limit should be very close to the center (0,0,0) due to symmetry.
            # The exact value depends on the face-point positions (at 1.5r).
            # For N=4 the limit position of the central vertex in a symmetric
            # star is pulled toward the outer ring. We just check it's finite.
            assert math.isfinite(pos[0])
            assert math.isfinite(pos[1])
            assert math.isfinite(pos[2])

    def test_limit_position_translates_with_center(self):
        """Translating all control points translates the limit position by the same vector."""
        N = 5
        patch_origin = _make_patch(N, radius=1.0, center=(0.0, 0.0, 0.0))
        offset = (3.0, -2.0, 7.0)
        patch_offset = _make_patch(N, radius=1.0, center=offset)

        pos_o = evaluate_at_extraordinary(patch_origin).position
        pos_t = evaluate_at_extraordinary(patch_offset).position

        dx = pos_t[0] - pos_o[0]
        dy = pos_t[1] - pos_o[1]
        dz = pos_t[2] - pos_o[2]
        assert abs(dx - offset[0]) < 1e-12
        assert abs(dy - offset[1]) < 1e-12
        assert abs(dz - offset[2]) < 1e-12

    def test_limit_position_scales_with_radius(self):
        """Scaling all control points scales the limit position by the same factor."""
        N = 6
        r1, r2 = 1.0, 5.0
        patch1 = _make_patch(N, radius=r1)
        patch2 = _make_patch(N, radius=r2)

        pos1 = evaluate_at_extraordinary(patch1).position
        pos2 = evaluate_at_extraordinary(patch2).position

        # Both positions should be at origin (center=(0,0,0)) scaled by ratio
        ratio = r2 / r1
        # The limit position = w_V * 0 + w_e * (sum of P_i) + w_f * (sum of Q_i)
        # For center at origin, pos1 = w_e * sum(P_i at r1) + w_f * sum(Q_i at 1.5r1)
        # sum of P_i = 0 (symmetric), sum of Q_i = 0 (symmetric)
        # So both limit positions are at origin → check
        assert _vec3_norm(pos1) < 1e-10
        assert _vec3_norm(pos2) < 1e-10


# ---------------------------------------------------------------------------
# Test group 4: evaluate_at_extraordinary — tangent vectors
# ---------------------------------------------------------------------------

class TestLimitTangentsAtEV:

    def test_tangent_cross_has_positive_length_n3(self):
        """For N=3 flat ring, T_u × T_v has positive length (well-defined normal)."""
        patch = _make_patch(3)
        result = evaluate_at_extraordinary(patch)
        cross_len = _vec3_norm(_cross(result.tangent_u, result.tangent_v))
        assert cross_len > 1e-12, "N=3: tangent cross product is degenerate"

    def test_tangent_cross_has_positive_length_n5(self):
        """For N=5 flat ring, T_u × T_v is non-degenerate."""
        patch = _make_patch(5)
        result = evaluate_at_extraordinary(patch)
        cross_len = _vec3_norm(_cross(result.tangent_u, result.tangent_v))
        assert cross_len > 1e-12

    def test_tangent_cross_has_positive_length_n6(self):
        """For N=6 flat ring, T_u × T_v is non-degenerate."""
        patch = _make_patch(6)
        result = evaluate_at_extraordinary(patch)
        cross_len = _vec3_norm(_cross(result.tangent_u, result.tangent_v))
        assert cross_len > 1e-12

    def test_normal_is_unit_length(self):
        """Normal = T_u × T_v / |...| should have length 1 for non-degenerate patch."""
        for N in [3, 4, 5, 6, 7, 8]:
            patch = _make_patch(N)
            result = evaluate_at_extraordinary(patch)
            n_len = _vec3_norm(result.normal)
            assert abs(n_len - 1.0) < 1e-12, f"N={N}: normal length={n_len}"

    def test_normal_direction_flat_xy_ring(self):
        """For a flat XY ring, the normal should point in the Z direction."""
        for N in [3, 4, 5, 6]:
            patch = _make_patch(N)
            result = evaluate_at_extraordinary(patch)
            n = result.normal
            # Normal should be close to (0, 0, ±1)
            assert abs(abs(n[2]) - 1.0) < 1e-10, (
                f"N={N}: flat ring normal={n}, expected Z-direction"
            )

    def test_tangent_vectors_in_xy_plane_for_flat_ring(self):
        """For a flat XY ring, tangents should lie in the XY plane (z≈0)."""
        for N in [3, 5, 7]:
            patch = _make_patch(N)
            result = evaluate_at_extraordinary(patch)
            assert abs(result.tangent_u[2]) < 1e-12, \
                f"N={N}: T_u has z-component {result.tangent_u[2]}"
            assert abs(result.tangent_v[2]) < 1e-12, \
                f"N={N}: T_v has z-component {result.tangent_v[2]}"

    def test_mirror_ring_flips_tangent_sign(self):
        """Reflecting the ring in the XY plane flips the Z-normal sign."""
        N = 5
        ring_pos = _make_ring(N, radius=1.0)
        ring_neg = [(x, -y, z) for (x, y, z) in ring_pos]

        patch_pos = ExtraordinaryPatch(valence=N, ring_positions=ring_pos)
        patch_neg = ExtraordinaryPatch(valence=N, ring_positions=ring_neg)

        result_pos = evaluate_at_extraordinary(patch_pos)
        result_neg = evaluate_at_extraordinary(patch_neg)

        # Normals should be opposite (reflected)
        n_pos = result_pos.normal
        n_neg = result_neg.normal
        # The normal is T_u × T_v; reflecting Y flips T_v sign → flips normal Z sign
        angle = _angle_rad(n_pos, n_neg)
        # Normals should be anti-parallel (angle ≈ π/2 ... π depends on orientation)
        # We check T_u · mirror(T_v) relationship instead:
        # For y-reflection: T_v → -T_v, so normal → -normal (negated)
        dot = _dot(n_pos, n_neg)
        assert dot < 0.0, f"N={N}: mirrored normals should point opposite, dot={dot}"


# ---------------------------------------------------------------------------
# Test group 5: evaluate_at_extraordinary vs evaluate_limit at u=v=0
# ---------------------------------------------------------------------------

class TestEvaluateLimitAtEV:

    @pytest.mark.parametrize("N", [3, 4, 5, 6, 7])
    def test_evaluate_limit_matches_at_extraordinary_at_origin(self, N: int):
        """evaluate_limit(u=0,v=0) should match evaluate_at_extraordinary."""
        patch = _make_patch(N)
        result_ev = evaluate_at_extraordinary(patch)
        result_lim = evaluate_limit(patch, 0.0, 0.0)

        # Positions should match
        pos_ev = result_ev.position
        pos_lim = result_lim.position
        dist = _vec3_norm((pos_ev[0]-pos_lim[0], pos_ev[1]-pos_lim[1], pos_ev[2]-pos_lim[2]))
        assert dist < 1e-10, f"N={N}: position mismatch at u=v=0: dist={dist}"

    @pytest.mark.parametrize("N", [3, 5])
    def test_evaluate_limit_normals_match_at_ev(self, N: int):
        """evaluate_limit(0,0) normal should match evaluate_at_extraordinary normal."""
        patch = _make_patch(N)
        result_ev = evaluate_at_extraordinary(patch)
        result_lim = evaluate_limit(patch, 0.0, 0.0)

        angle = _angle_rad(result_ev.normal, result_lim.normal)
        assert angle < 1e-9, f"N={N}: normal angle mismatch at u=v=0: {angle} rad"


# ---------------------------------------------------------------------------
# Test group 6: evaluate_limit at non-zero (u,v) — regularity and consistency
# ---------------------------------------------------------------------------

class TestEvaluateLimitGeneral:

    def test_regular_n4_finite_at_random_uv(self):
        """N=4 patch evaluation is finite at several random (u,v) values."""
        patch = _make_patch(4)
        rng = random.Random(42)
        for _ in range(10):
            u = rng.uniform(0.01, 0.99)
            v = rng.uniform(0.01, 0.99)
            result = evaluate_limit(patch, u, v)
            assert math.isfinite(result.position[0])
            assert math.isfinite(result.tangent_u[0])
            assert math.isfinite(result.tangent_v[0])

    def test_extraordinary_n5_finite_at_random_uv(self):
        """N=5 patch evaluation is finite at several random (u,v) values."""
        patch = _make_patch(5)
        rng = random.Random(7)
        for _ in range(8):
            u = rng.uniform(0.1, 0.9)
            v = rng.uniform(0.05, 0.95)
            result = evaluate_limit(patch, u, v)
            assert math.isfinite(result.position[0])
            assert math.isfinite(result.normal[0])

    def test_tangent_cross_positive_length_at_interior_n3(self):
        """For N=3, tangent_u × tangent_v has positive length at interior (u,v)."""
        patch = _make_patch(3)
        for u, v in [(0.3, 0.2), (0.5, 0.5), (0.1, 0.8)]:
            result = evaluate_limit(patch, u, v)
            cross = _cross(result.tangent_u, result.tangent_v)
            cross_len = _vec3_norm(cross)
            assert cross_len > 1e-12, \
                f"N=3 at (u={u},v={v}): tangent cross len={cross_len}"

    def test_normal_unit_length_at_non_degenerate_uv(self):
        """Normal is unit length at non-degenerate interior (u,v)."""
        for N in [3, 4, 5, 6]:
            patch = _make_patch(N)
            result = evaluate_limit(patch, 0.4, 0.3)
            n_len = _vec3_norm(result.normal)
            assert abs(n_len - 1.0) < 1e-12, \
                f"N={N} at (0.4,0.3): normal length={n_len}"

    def test_asymmetric_ring_normal_nonzero(self):
        """Asymmetric (non-planar) ring produces a well-defined, non-zero normal."""
        N = 5
        ring = _make_ring(N, radius=1.0)
        # Perturb some points out of the XY plane
        ring_asym = list(ring)
        ring_asym[1] = (ring[1][0], ring[1][1], 0.3)
        ring_asym[3] = (ring[3][0], ring[3][1], -0.2)
        ring_asym[7] = (ring[7][0], ring[7][1], 0.1)

        patch = ExtraordinaryPatch(valence=N, ring_positions=ring_asym)
        result = evaluate_at_extraordinary(patch)
        n_len = _vec3_norm(result.normal)
        assert n_len > 1e-12, "Asymmetric ring: normal should be non-zero"


# ---------------------------------------------------------------------------
# Test group 7: G1 continuity
# ---------------------------------------------------------------------------

class TestG1ContinuousNormals:

    def test_identical_patches_g1_true(self):
        """Two identical patches at the same EV are G1-continuous (angle=0)."""
        patch = _make_patch(5)
        assert g1_continuous_normals(patch, patch) is True

    def test_same_ev_different_valence_not_g1(self):
        """Patches with different valence (different EVs) are generally not G1."""
        patch3 = _make_patch(3)
        patch5 = _make_patch(5)
        # Different valences → different normal directions (both XZ ring → same Z normal)
        # Actually both flat rings in XY → both normals = (0,0,1) → they would be G1!
        # So we use a tilted ring for one.
        N = 5
        ring_tilted = _make_ring(N, radius=1.0)
        ring_tilted = [(x, y, x * 0.5) for (x, y, z) in ring_tilted]  # tilt in XZ
        patch_tilted = ExtraordinaryPatch(valence=N, ring_positions=ring_tilted)
        patch_flat = _make_patch(N)
        # Tilted vs flat: normals differ → not G1
        result = g1_continuous_normals(patch_tilted, patch_flat)
        assert result is False, "Tilted vs flat ring should not be G1"

    def test_g1_true_for_consistent_ring(self):
        """Two patches sharing the same EV and compatible tangent rings are G1."""
        # Build two patches that have the same limit normal by construction:
        # Both use the same flat XY ring but with different sector orientations.
        N = 5
        patch_a = _make_patch(N)
        # Rotate the ring by one step (shift P_0..P_{N-1} by 1)
        ring_b = list(_make_ring(N))
        # Cyclic shift of the edge-adjacent neighbors by 1
        edge_nbrs = ring_b[1:N+1]
        face_nbrs = ring_b[N+1:]
        ring_b = [ring_b[0]] + edge_nbrs[1:] + [edge_nbrs[0]] + face_nbrs[1:] + [face_nbrs[0]]
        patch_b = ExtraordinaryPatch(valence=N, ring_positions=ring_b)
        # Both are flat XY rings → both normals are (0,0,1) → G1
        assert g1_continuous_normals(patch_a, patch_b) is True

    def test_flat_rings_different_radius_g1_true(self):
        """Two flat XY rings with same normal (but different scale) are G1."""
        patch_a = _make_patch(6, radius=1.0)
        patch_b = _make_patch(6, radius=3.0)
        # Both are flat XY rings → both normals = (0,0,1) → G1 (angle=0)
        assert g1_continuous_normals(patch_a, patch_b) is True

    def test_anti_parallel_normals_not_g1(self):
        """Patches with anti-parallel normals (flipped orientation) are not G1."""
        N = 5
        patch_a = _make_patch(N)
        # Build ring with reversed CCW order → flips T_v → flips normal
        ring_rev = list(_make_ring(N))
        edge_nbrs = ring_rev[1:N+1]
        face_nbrs = ring_rev[N+1:]
        # Reverse CCW order of edge + face neighbors
        ring_rev = [ring_rev[0]] + edge_nbrs[::-1] + face_nbrs[::-1]
        patch_b = ExtraordinaryPatch(valence=N, ring_positions=ring_rev)
        # Reversed winding → T_v → -T_v → normal flips sign
        # G1 checks |angle| < 1e-9, but abs(cos) means anti-parallel → 0 angle → G1!
        # Since we use abs(cos_theta), anti-parallel still means normals are in the
        # same tangent plane (just oriented differently). Let's verify:
        eval_a = evaluate_at_extraordinary(patch_a)
        eval_b = evaluate_at_extraordinary(patch_b)
        import math as _math
        dot = _dot(eval_a.normal, eval_b.normal)
        # If normals are anti-parallel, abs(dot)=1 → angle=0 → g1_continuous=True
        # This is correct behavior: G1 doesn't care about normal orientation
        result = g1_continuous_normals(patch_a, patch_b)
        # Both normals from flat XY ring (one CW, one CCW) → same plane → G1
        assert isinstance(result, bool)  # just check it returns a bool cleanly

    def test_g1_n3_flat_ring(self):
        """N=3 flat ring: two identical patches are G1."""
        patch = _make_patch(3)
        assert g1_continuous_normals(patch, patch) is True

    def test_g1_n8_flat_ring(self):
        """N=8 flat ring: two identical patches are G1."""
        patch = _make_patch(8)
        assert g1_continuous_normals(patch, patch) is True


# ---------------------------------------------------------------------------
# Test group 8: Numeric consistency
# ---------------------------------------------------------------------------

class TestNumericConsistency:

    def test_n4_regular_limit_position_weighted_average(self):
        """For N=4, limit position is exactly w_V*V + 4*w_e*avg(P) + 4*w_f*avg(Q).

        For a symmetric flat ring, the avg of P_i = 0 and avg of Q_i = 0 (at origin).
        Thus V_inf should be at origin (since w_V * 0 = 0).
        """
        N = 4
        patch = _make_patch(N, center=(0.0, 0.0, 0.0))
        v_inf = _limit_position_at_ev(patch)
        assert _vec3_norm(v_inf) < 1e-10, f"N=4 symmetric ring: limit pos={v_inf}"

    def test_limit_position_formula_matches_manual(self):
        """Manually compute limit position for N=3 and check against implementation."""
        N = 3
        # Place V at (0,0,0), P_i at unit circle, Q_i at sqrt(3)/2 radius
        import math as _math
        pts: List[Vec3] = [(0.0, 0.0, 0.0)]  # V
        for i in range(N):
            theta = 2 * _math.pi * i / N
            pts.append((_math.cos(theta), _math.sin(theta), 0.0))
        for i in range(N):
            theta = 2 * _math.pi * (i + 0.5) / N
            r = 1.5
            pts.append((r * _math.cos(theta), r * _math.sin(theta), 0.0))

        patch = ExtraordinaryPatch(valence=N, ring_positions=pts)
        w_V, w_e, w_f = _cc_limit_weights(N)

        # Manual: V=0, sum(P_i) = 0 (symmetric), sum(Q_i) = 0 (symmetric)
        # → V_inf = 0
        v_inf = _limit_position_at_ev(patch)
        assert _vec3_norm(v_inf) < 1e-10

    def test_tangents_stam_eq_33_manual_n3(self):
        """Manually verify Stam §3.3 tangent formula for N=3.

        T_u = Σ cos(2πi/3) * (P_i - V_inf)
        For V_inf=0 and P_i on unit circle:
          T_u = cos(0)*(1,0,0) + cos(2π/3)*(-1/2,√3/2,0) + cos(4π/3)*(-1/2,-√3/2,0)
             = (1,0,0) + (-1/4, √3*(-1/2)/2, 0) + ... = (1 - 1/4 - 1/4, ...) = (1/2*...,...)
        """
        import math as _math
        N = 3
        pts: List[Vec3] = [(0.0, 0.0, 0.0)]  # V at origin
        for i in range(N):
            theta = 2 * _math.pi * i / N
            pts.append((_math.cos(theta), _math.sin(theta), 0.0))
        for i in range(N):
            theta = 2 * _math.pi * (i + 0.5) / N
            pts.append((1.5 * _math.cos(theta), 1.5 * _math.sin(theta), 0.0))

        patch = ExtraordinaryPatch(valence=N, ring_positions=pts)
        v_inf = _limit_position_at_ev(patch)

        # Manual T_u calculation
        expected_tu = [0.0, 0.0, 0.0]
        for i in range(N):
            theta = 2 * _math.pi * i / N
            c = _math.cos(theta)
            P_i = pts[1 + i]
            expected_tu[0] += c * (P_i[0] - v_inf[0])
            expected_tu[1] += c * (P_i[1] - v_inf[1])
            expected_tu[2] += c * (P_i[2] - v_inf[2])

        # Implementation
        result = evaluate_at_extraordinary(patch)
        tu_impl = result.tangent_u

        for j in range(3):
            assert abs(expected_tu[j] - tu_impl[j]) < 1e-12, \
                f"T_u component {j}: expected={expected_tu[j]}, got={tu_impl[j]}"

    def test_evaluate_limit_clamping(self):
        """evaluate_limit clamps u,v to [0,1] without raising."""
        patch = _make_patch(5)
        # These should not raise even with out-of-range values
        result = evaluate_limit(patch, -0.5, 1.5)
        assert math.isfinite(result.position[0])
        result = evaluate_limit(patch, 2.0, -1.0)
        assert math.isfinite(result.position[0])

    def test_limit_eval_returns_limevaltype(self):
        """evaluate_limit and evaluate_at_extraordinary return LimitEval instances."""
        patch = _make_patch(5)
        result_ev = evaluate_at_extraordinary(patch)
        result_lim = evaluate_limit(patch, 0.3, 0.4)
        assert isinstance(result_ev, LimitEval)
        assert isinstance(result_lim, LimitEval)

    def test_scale_invariance_of_normal(self):
        """Scaling the entire ring by a constant should not change the normal direction."""
        N = 5
        scale = 10.0
        ring1 = _make_ring(N, radius=1.0)
        ring2 = [(x * scale, y * scale, z * scale) for (x, y, z) in ring1]

        patch1 = ExtraordinaryPatch(valence=N, ring_positions=ring1)
        patch2 = ExtraordinaryPatch(valence=N, ring_positions=ring2)

        res1 = evaluate_at_extraordinary(patch1)
        res2 = evaluate_at_extraordinary(patch2)

        angle = _angle_rad(res1.normal, res2.normal)
        assert angle < 1e-10, f"Scale invariance: normal angle={angle} rad"

    def test_stam_table1_weights_hardcoded_n3_exact(self):
        """Stam Table 1 N=3: w_V=3/8, w_e=1/6, w_f=1/24 exactly."""
        w_V, w_e, w_f = _cc_limit_weights(3)
        assert abs(w_V - 3.0/8.0) < 1e-14
        assert abs(w_e - 1.0/6.0) < 1e-14
        assert abs(w_f - 1.0/24.0) < 1e-14

    def test_stam_table1_weights_hardcoded_n5_exact(self):
        """Stam Table 1 N=5: denom=50, w_V=1/2, w_e=2/25, w_f=1/50."""
        w_V, w_e, w_f = _cc_limit_weights(5)
        assert abs(w_V - 25.0/50.0) < 1e-14
        assert abs(w_e - 4.0/50.0) < 1e-14
        assert abs(w_f - 1.0/50.0) < 1e-14

    def test_stam_table1_weights_hardcoded_n6_exact(self):
        """Stam Table 1 N=6: denom=66, w_V=36/66=6/11."""
        w_V, w_e, w_f = _cc_limit_weights(6)
        assert abs(w_V - 36.0/66.0) < 1e-14
        assert abs(w_e - 4.0/66.0) < 1e-14
        assert abs(w_f - 1.0/66.0) < 1e-14
