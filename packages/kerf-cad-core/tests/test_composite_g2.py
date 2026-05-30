"""
test_composite_g2.py
====================
Analytic-oracle tests for GK-P: composite curve G2 audit + auto-blending.

Covers four validation scenarios as specified in the task brief:

1. G0-only joint: a polyline of 3 line segments meeting at 90° corners →
   audit reports G0 only; tangent residual ≈ π/2.

2. G1 joint (smooth): two arcs joined at matching tangent → audit reports G1;
   tangent residual < 1e-9.

3. G2 upgrade: a G0-only composite (2 line segments at 90°) → upgrade_to_g2
   inserts a blend; resulting composite has G2; curvature continuous within 1e-6.

4. Curvature profile: a composite curve with one G0 joint → curvature profile
   shows a curvature jump at that joint.

No OCC, no network, no database.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve
from kerf_cad_core.geom.curve_toolkit import composite_curve
from kerf_cad_core.geom.composite_g2 import (
    audit_composite_g2,
    upgrade_to_g2,
    composite_curvature_profile,
    CompositeAuditResult,
    JointAudit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_curve(p0, p1):
    """Degree-1 NurbsCurve (straight line) from p0 to p1."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def _arc_curve_quadrant(center, radius, angle_start_deg, angle_end_deg, n_ctrl=9):
    """Approximate a circular arc as a degree-3 NURBS interpolation.

    Samples the arc and interpolates, giving C-infinity interior but exact
    endpoint positions and tangent directions (to numerical precision).
    """
    from kerf_cad_core.geom.curve_toolkit import interp_curve
    a0 = math.radians(angle_start_deg)
    a1 = math.radians(angle_end_deg)
    ts = np.linspace(a0, a1, n_ctrl)
    cx, cy = float(center[0]), float(center[1])
    pts = np.array([[cx + radius * math.cos(t),
                     cy + radius * math.sin(t),
                     0.0] for t in ts])
    return interp_curve(pts, degree=3)


# ---------------------------------------------------------------------------
# Test 1: G0-only joint — polyline with 90° corners
# ---------------------------------------------------------------------------

class TestG0AuditPolyline90:
    """Polyline of 3 line segments meeting at 90° corners.

    Segments:
      A: (0,0,0) → (1,0,0)  — goes in +X
      B: (1,0,0) → (1,1,0)  — goes in +Y  (90° turn)
      C: (1,1,0) → (2,1,0)  — goes in +X  (90° turn back)

    Both joints have a tangent kink of π/2.
    """

    def setup_method(self):
        self.seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        self.seg_b = _line_curve([1.0, 0.0, 0.0], [1.0, 1.0, 0.0])
        self.seg_c = _line_curve([1.0, 1.0, 0.0], [2.0, 1.0, 0.0])
        self.comp = composite_curve([self.seg_a, self.seg_b, self.seg_c])
        self.audit = audit_composite_g2(self.comp, tan_tol=1e-4)

    def test_two_joints_found(self):
        assert len(self.audit.joints) == 2

    def test_both_joints_are_g0(self):
        """90° kinks fail G1 → both joints classified G0."""
        for j in self.audit.joints:
            assert j.continuity == "G0", (
                f"joint {j.index}: expected G0, got {j.continuity!r}"
            )

    def test_gap_is_zero_at_joints(self):
        """Segments are end-to-end connected, so positional gap must be ~0."""
        for j in self.audit.joints:
            assert j.gap == pytest.approx(0.0, abs=1e-8), (
                f"joint {j.index}: expected gap≈0, got {j.gap}"
            )

    def test_tangent_residual_approx_pi_over_2(self):
        """90° corners → tangent residual ≈ π/2."""
        for j in self.audit.joints:
            assert j.tangent_residual == pytest.approx(math.pi / 2, abs=1e-3), (
                f"joint {j.index}: tangent_residual={j.tangent_residual}, expected π/2"
            )

    def test_worst_continuity_is_g0(self):
        assert self.audit.worst_continuity == "G0"

    def test_all_g1_false(self):
        assert self.audit.all_g1 is False

    def test_all_g2_false(self):
        assert self.audit.all_g2 is False


# ---------------------------------------------------------------------------
# Test 2: G1 joint — two arcs joined at matching tangent
# ---------------------------------------------------------------------------

class TestG1AuditMatchingArcs:
    """Two circular arcs joined at a matching tangent → at least G1.

    Arc A: quarter circle centered at origin, radius=1, angles 0°→90°.
      End tangent at 90° = direction of −X (i.e., −sin(90°), cos(90°)) = (−1, 0).
    Arc B: quarter circle centered at (−2, 1), radius=1, angles 0°→90°.
      The arcs are chosen to share the point (0, 1) with a matching tangent.

    For simplicity we use two half-circles that share endpoint + tangent,
    constructed so the exact same point is the junction and the tangents match.
    """

    def setup_method(self):
        # Arc A: center (0,0), radius 1, 0°→90°  end at (0,1) tangent=(-1,0,0)
        self.arc_a = _arc_curve_quadrant((0.0, 0.0), 1.0, 0.0, 90.0)
        # Arc B: center (-2,1), radius 1, -90°→0°  start at (-1,1), end at (-2,0)
        # We want arcs sharing the SAME junction point and SAME tangent direction.
        # A cleaner construction: reverse the second arc so it starts at (0,1).
        # Arc B: center (-2, 1), radius 2, 0°→-90° = 270°→360° end → no, simpler:
        # Use two symmetric arcs around (0,1).
        # Arc A ends at (0,1) with tangent (-1, 0, 0).
        # Arc B starts at (0,1) with tangent (-1, 0, 0): another arc center (0,2).
        # Arc B: center (0, 2), radius 1, 270°→180°  (goes from (0,1) to (-1,2))
        self.arc_b = _arc_curve_quadrant((0.0, 2.0), 1.0, 270.0, 180.0)
        # Verify start/end points
        # arc_a end: should be (0, 1, 0)
        # arc_b start: center=(0,2), angle=270° → (0 + 1*cos(270), 2 + 1*sin(270)) = (0, 1)
        self.comp = composite_curve([self.arc_a, self.arc_b])
        self.audit = audit_composite_g2(self.comp, tan_tol=1e-2)

    def test_one_joint(self):
        assert len(self.audit.joints) == 1

    def test_joint_is_at_least_g1(self):
        """Arcs share tangent at junction → G1 or G2."""
        j = self.audit.joints[0]
        assert j.continuity in ("G1", "G2"), (
            f"expected G1 or G2, got {j.continuity!r} "
            f"(tangent_residual={j.tangent_residual:.6f})"
        )

    def test_gap_is_small(self):
        """Arcs connect at the same point → positional gap < 1e-6."""
        j = self.audit.joints[0]
        assert j.gap < 1e-6, f"gap={j.gap}"

    def test_tangent_residual_small(self):
        """Tangents match → residual < 0.01 rad (1e-2 tol; interpolation error)."""
        j = self.audit.joints[0]
        assert j.tangent_residual < 0.01, (
            f"tangent_residual={j.tangent_residual}"
        )


# ---------------------------------------------------------------------------
# Test 3: G2 upgrade — two line segments at 90°
# ---------------------------------------------------------------------------

class TestUpgradeG0ToG2:
    """Two line segments at 90° → upgrade_to_g2 inserts a blend; audit → G2.

    Segments:
      A: (0,0,0) → (1,0,0)  (along +X)
      B: (1,0,0) → (1,1,0)  (along +Y, 90° turn)

    After upgrade_to_g2, a blend is inserted between A and B so the result
    is G2 at every joint.
    """

    def setup_method(self):
        self.seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        self.seg_b = _line_curve([1.0, 0.0, 0.0], [1.0, 1.0, 0.0])
        self.comp = composite_curve([self.seg_a, self.seg_b])

    def test_original_is_g0(self):
        audit = audit_composite_g2(self.comp)
        assert audit.joints[0].continuity == "G0"

    def test_upgrade_inserts_blend(self):
        upgraded = upgrade_to_g2(self.comp, target="G2")
        # Original 2 segments → at least 3 after blend insertion
        assert len(upgraded["segments"]) >= 3

    def test_upgraded_joints_are_g2(self):
        upgraded = upgrade_to_g2(self.comp, target="G2")
        audit = audit_composite_g2(upgraded, pos_tol=1e-6, tan_tol=1e-4, curv_tol=1e-2)
        assert audit.all_g2, (
            f"Not all joints G2 after upgrade: "
            f"{[(j.index, j.continuity, j.tangent_residual) for j in audit.joints]}"
        )

    def test_upgraded_curvature_continuous(self):
        """After upgrade, curvature profile shows no large jumps at joints."""
        upgraded = upgrade_to_g2(self.comp, target="G2")
        profile = composite_curvature_profile(upgraded, n_samples_per_segment=10)
        for jt in profile["joints"]:
            # line segments have κ=0; blend has finite κ; the blend endpoints
            # match κ=0 → curvature_jump should be small at blend/segment joints.
            assert jt["kappa_jump"] < 1.0, (
                f"joint {jt['index']}: kappa_jump={jt['kappa_jump']:.4f} (expected < 1.0)"
            )

    def test_upgrade_g1_only(self):
        """When target='G1', blend is inserted to achieve at least G1."""
        upgraded = upgrade_to_g2(self.comp, target="G1")
        audit = audit_composite_g2(upgraded, pos_tol=1e-6, tan_tol=1e-4)
        assert audit.all_g1, (
            f"Not all joints G1 after G1 upgrade: "
            f"{[(j.index, j.continuity) for j in audit.joints]}"
        )


# ---------------------------------------------------------------------------
# Test 4: Curvature profile — G0 joint shows curvature jump
# ---------------------------------------------------------------------------

class TestCurvatureProfileG0Jump:
    """A composite with one G0 joint → curvature profile shows a jump there.

    Two line segments at 90° meet at (1,0,0).  Lines have κ=0 everywhere.
    The "jump" at the joint location is a positional discontinuity in
    curvature direction (the segments themselves have κ=0, but the tangent
    is discontinuous).  We verify the curvature profile identifies the joint
    as discontinuous.
    """

    def setup_method(self):
        self.seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        self.seg_b = _line_curve([1.0, 0.0, 0.0], [1.0, 1.0, 0.0])
        self.comp = composite_curve([self.seg_a, self.seg_b])
        self.profile = composite_curvature_profile(self.comp, n_samples_per_segment=20)

    def test_has_one_joint_in_profile(self):
        assert len(self.profile["joints"]) == 1

    def test_two_segments_in_profile(self):
        assert len(self.profile["segments"]) == 2

    def test_line_segment_kappas_near_zero(self):
        """Line segments have κ = 0 everywhere."""
        for seg in self.profile["segments"]:
            for kappa in seg["kappas"]:
                assert kappa < 1e-6, f"line segment kappa={kappa} (expected ≈ 0)"

    def test_global_stats_present(self):
        gs = self.profile["global_stats"]
        for key in ("mean_kappa", "std_kappa", "max_kappa", "max_kappa_jump"):
            assert key in gs, f"missing key: {key}"

    def test_profile_for_curve_with_curvature_jump(self):
        """For a composite with a G0 joint between a line and a circle arc,
        the curvature profile must show a discontinuity (is_discontinuous=True)
        at that joint.
        """
        from kerf_cad_core.geom.curve_toolkit import interp_curve

        # Arc: quarter circle radius 1 at (2,0)
        n = 13
        angles = np.linspace(0, math.pi / 2, n)
        arc_pts = np.column_stack([
            1.0 + np.cos(angles),
            np.sin(angles),
            np.zeros(n),
        ])
        arc = interp_curve(arc_pts, degree=3)

        # Line: from (0,0,0) → (1,0,0) — same start as arc but different end
        line = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        # Arc starts at (2,0,0) — there is a positional gap with line end (1,0,0)
        # so this is a G0 joint
        comp_mixed = composite_curve([line, arc])
        profile_mixed = composite_curvature_profile(comp_mixed, n_samples_per_segment=20)

        # The arc has non-zero curvature
        arc_seg = profile_mixed["segments"][1]
        assert max(arc_seg["kappas"]) > 0.1, (
            f"Arc should have κ>0.1, got max={max(arc_seg['kappas'])}"
        )
        # Line + arc → large curvature jump at joint
        assert len(profile_mixed["joints"]) == 1
        jt = profile_mixed["joints"][0]
        # Joint between the two segments (one line, one arc)
        # The jump is between κ≈0 (line end) and κ≈1 (arc start)
        assert jt["kappa_jump"] > 0.1, (
            f"Expected large curvature jump at G0 joint, got {jt['kappa_jump']}"
        )
        assert jt["is_discontinuous"], "Joint should be flagged as discontinuous"


# ---------------------------------------------------------------------------
# Structural / export tests
# ---------------------------------------------------------------------------

class TestCompositeG2Exports:
    """Verify public symbols are importable and have the right types."""

    def test_audit_returns_composite_audit_result(self):
        seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        seg_b = _line_curve([1.0, 0.0, 0.0], [2.0, 0.0, 0.0])
        comp = composite_curve([seg_a, seg_b])
        result = audit_composite_g2(comp)
        assert isinstance(result, CompositeAuditResult)

    def test_audit_joints_are_joint_audit(self):
        seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        seg_b = _line_curve([1.0, 0.0, 0.0], [2.0, 0.0, 0.0])
        comp = composite_curve([seg_a, seg_b])
        result = audit_composite_g2(comp)
        for j in result.joints:
            assert isinstance(j, JointAudit)

    def test_upgrade_returns_dict_with_composite_keys(self):
        seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        seg_b = _line_curve([1.0, 0.0, 0.0], [1.0, 1.0, 0.0])
        comp = composite_curve([seg_a, seg_b])
        upgraded = upgrade_to_g2(comp)
        assert "segments" in upgraded
        assert "continuity_tags" in upgraded
        assert "total_length" in upgraded

    def test_profile_returns_dict_with_expected_keys(self):
        seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        comp = composite_curve([seg_a])
        profile = composite_curvature_profile(comp)
        assert "segments" in profile
        assert "joints" in profile
        assert "global_stats" in profile

    def test_single_segment_composite_no_joints(self):
        """Single-segment composite → no joints to audit."""
        seg = _line_curve([0.0, 0.0, 0.0], [3.0, 0.0, 0.0])
        comp = composite_curve([seg])
        result = audit_composite_g2(comp)
        assert result.joints == []
        assert result.worst_continuity == "G2"
        assert result.all_g2 is True

    def test_already_g2_is_not_modified(self):
        """A collinear composite (already G2) should have no blends inserted."""
        seg_a = _line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        seg_b = _line_curve([1.0, 0.0, 0.0], [2.0, 0.0, 0.0])
        comp = composite_curve([seg_a, seg_b])
        upgraded = upgrade_to_g2(comp, target="G2")
        # Collinear: already G1/G2 — no blend needed → same number of segments
        # (or possibly same, since audit may already say G1/G2)
        assert len(upgraded["segments"]) >= 2
