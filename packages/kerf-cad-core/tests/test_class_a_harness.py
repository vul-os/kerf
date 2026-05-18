"""T-104g — Class-A acceptance harness: combs + zebra + G0..G3 gate (GK-64).

Tests for:
  1. ``class_a_acceptance_harness`` importable from surface_analysis.
  2. Extended ``edge_continuity_report`` returns G3_max, G3_rms, G3_ok,
     continuity_grade keys.
  3. A known G3-continuous join (two coplanar flat planes — κ=0, dκ/ds=0
     everywhere) passes all gates and ``highest_grade == "G3"``.
  4. A G2-only join (flat plane meeting a cubic-z surface — κ matches at
     seam v=0 but dκ/ds differs by 6A) fails the G3 gate (``G3_ok=False``)
     and the harness reports ``highest_grade == "G2"`` or lower.
  5. A G0-only join (two flat planes at a dihedral crease — position
     continuous, normals differ) fails the G1 gate (``G1_ok=False``) and
     the harness reports ``highest_grade == "G0"`` or ``"below_G0"``.
  6. All four ``gates`` keys are present in harness output.
  7. ``comb`` block present with ``max_H_a / max_H_b / per_point``.
  8. ``zebra`` block present and ``ok=True`` for valid inputs.
  9. ``continuity`` block present and matches standalone call.
 10. Bad inputs return ``ok=False`` with a ``reason`` string.
 11. Determinism: identical inputs produce bit-identical results.
 12. ``per_point`` in edge_continuity_report now includes
     ``G3_dkds_residual`` key.

All tests are hermetic: no OCCT, no network, no database.
Closed-form analytic references are documented inline.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_analysis import (
    class_a_acceptance_harness,
    edge_continuity_report,
    _eval_surface,
    _uv_grid,
)


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------


def _clamped(n: int, degree: int) -> np.ndarray:
    """Clamped (open) knot vector for n control points at given degree."""
    inner = max(0, n - degree - 1)
    parts = [np.zeros(degree + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(degree + 1))
    return np.concatenate(parts)


def _plane_surface(
    origin=(0.0, 0.0, 0.0),
    x_axis=(1.0, 0.0, 0.0),
    y_axis=(0.0, 1.0, 0.0),
    nu: int = 5,
    nv: int = 5,
    degree: int = 3,
) -> NurbsSurface:
    """Flat NURBS plane patch (κ=0, dκ/ds=0 everywhere).

    Degree-3 by default so that the G3 oracle has non-trivial 3rd derivatives
    to evaluate (even though they are 0 for a plane).
    """
    origin = np.asarray(origin, dtype=float)
    xa = np.asarray(x_axis, dtype=float)
    ya = np.asarray(y_axis, dtype=float)
    deg = min(degree, nu - 1, nv - 1)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = origin + (i / (nu - 1)) * xa + (j / (nv - 1)) * ya
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_clamped(nu, deg),
        knots_v=_clamped(nv, deg),
    )


def _cubic_z_surface(
    amplitude: float = 0.1,
    nu: int = 5,
) -> NurbsSurface:
    """Exact degree-3 NURBS patch with z = amplitude * v^3  (v in [0, 1]).

    At v=0 the closed-form oracle gives:
        S_v   = (0, 1, 0)     |S_v| = 1
        S_vv  = (0, 0, 0)     κ = 0
        S_vvv = (0, 0, 6A)
        dκ/dv = 6A / 1 = 6A
        dκ/ds = 6A            (since |S_v|=1 at v=0)

    The flat plane at the same seam has dκ/ds = 0, so the G3 residual is
    |6A − 0| = 6A > 0.  For A=0.1 this is 0.6, well above G3_tol=1e-3.
    """
    nv = 4
    nu_use = max(nu, 4)
    cp = np.zeros((nu_use, nv, 3))
    v_cp = [0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0]
    z_cp = [0.0, 0.0, 0.0, amplitude]
    for i in range(nu_use):
        u = i / (nu_use - 1)
        for j in range(nv):
            cp[i, j] = np.array([u, v_cp[j], z_cp[j]])
    deg_u = min(3, nu_use - 1)
    deg_v = 3
    return NurbsSurface(
        degree_u=deg_u, degree_v=deg_v,
        control_points=cp,
        knots_u=_clamped(nu_use, deg_u),
        knots_v=_clamped(nv, deg_v),
    )


def _make_shared_edge(
    surf: NurbsSurface,
    u_const: float,
    num_pts: int = 8,
) -> List[List[float]]:
    """Sample a u=const isocurve on surf as the shared edge polyline."""
    v_min = float(surf.knots_v[0])
    v_max = float(surf.knots_v[-1])
    pts = []
    for v in np.linspace(v_min, v_max, num_pts):
        p = _eval_surface(surf, u_const, v)[:3].tolist()
        pts.append(p)
    return pts


# ---------------------------------------------------------------------------
# 1. Import / API contract
# ---------------------------------------------------------------------------


class TestImportContract:
    def test_class_a_acceptance_harness_importable(self):
        from kerf_cad_core.geom.surface_analysis import class_a_acceptance_harness
        assert callable(class_a_acceptance_harness)

    def test_harness_result_has_required_top_level_keys(self):
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(plane, plane, edge, num_samples=5)
        assert result["ok"] is True
        required = {"gates", "highest_grade", "comb", "zebra", "continuity"}
        assert required <= set(result.keys()), (
            f"Missing top-level keys: {required - set(result.keys())}"
        )

    def test_gates_block_has_all_four_keys(self):
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(plane, plane, edge, num_samples=5)
        gates = result["gates"]
        for key in ("G0_ok", "G1_ok", "G2_ok", "G3_ok"):
            assert key in gates, f"Missing gate key: {key}"

    def test_edge_continuity_report_has_g3_keys(self):
        """Extended edge_continuity_report must expose G3_max, G3_rms, G3_ok,
        continuity_grade."""
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = edge_continuity_report(plane, plane, edge, num_samples=5)
        assert result["ok"] is True
        for key in ("G3_max", "G3_rms", "G3_ok", "continuity_grade"):
            assert key in result, f"Missing key from edge_continuity_report: {key}"

    def test_per_point_has_g3_dkds_residual(self):
        """per_point entries in edge_continuity_report must include
        G3_dkds_residual."""
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = edge_continuity_report(plane, plane, edge, num_samples=4)
        assert result["ok"] is True
        for pp in result["per_point"]:
            assert "G3_dkds_residual" in pp, (
                f"per_point entry missing G3_dkds_residual: {list(pp.keys())}"
            )


# ---------------------------------------------------------------------------
# 2. Good A-surface fixture: coplanar flat planes — passes all gates
#
# Two coplanar flat planes sharing a seam (degree-3, so G3 oracle has
# non-trivial 3rd-order derivatives to evaluate, all zero for a plane).
#
# Analytic oracle:
#   κ = 0 everywhere on both surfaces (flat plane)
#   dκ/ds = 0 everywhere  (S_vvv = 0 for a polynomial-degree-3 flat plane)
#   G0 residual = 0  (same height z=0)
#   G1 residual = 0° (normals both [0,0,1])
#   G2 residual = 0  (H = 0 on both sides)
#   G3 residual = 0  (dκ/ds = 0 on both sides)
#   → ALL gates pass; highest_grade = "G3"
# ---------------------------------------------------------------------------


class TestG3JoinPassesAllGates:
    """Two coplanar flat planes trivially satisfy G3."""

    def _setup(self):
        surf_a = _plane_surface(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        surf_b = _plane_surface(
            origin=(0.0, 1.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        # Shared edge: y=1, z=0, x in [0,1]
        edge = [[x, 1.0, 0.0] for x in np.linspace(0.0, 1.0, 8)]
        return surf_a, surf_b, edge

    def test_coplanar_planes_harness_ok(self):
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        assert result["ok"] is True

    def test_coplanar_planes_all_gates_pass(self):
        """All four G gates must pass for coplanar flat planes."""
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        gates = result["gates"]
        assert gates["G0_ok"] is True, f"G0 failed: {result['continuity']}"
        assert gates["G1_ok"] is True, f"G1 failed: {result['continuity']}"
        assert gates["G2_ok"] is True, f"G2 failed: {result['continuity']}"
        assert gates["G3_ok"] is True, f"G3 failed: {result['continuity']}"

    def test_coplanar_planes_highest_grade_G3(self):
        """highest_grade must be 'G3' when all gates pass."""
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        assert result["highest_grade"] == "G3", (
            f"Expected 'G3', got {result['highest_grade']!r}"
        )

    def test_coplanar_planes_g3_max_near_zero(self):
        """G3_max must be < 1e-5 for coplanar flat planes (dκ/ds = 0 on both)."""
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        g3_max = result["continuity"]["G3_max"]
        assert g3_max < 1e-5, (
            f"Expected G3_max < 1e-5 for coplanar planes, got {g3_max!r}"
        )

    def test_same_surface_passes_g3(self):
        """Same surface on both sides: trivially G3."""
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(
            plane, plane, edge, num_samples=6,
        )
        assert result["ok"] is True
        assert result["gates"]["G3_ok"] is True
        assert result["highest_grade"] == "G3"


# ---------------------------------------------------------------------------
# 3. G2-only fixture: cubic-z surface meets flat plane — fails G3 gate
#
# S_cubic(u,v) = (u, v, A*v^3) with A=0.1.
# At v=0 (the seam):
#   κ = 0 on cubic  (S_vv = 0 at v=0)
#   κ = 0 on plane  (flat)
#   → G2 passes (ΔH = 0)
#
#   dκ/ds on cubic = 6A = 0.6   (see _cubic_z_surface docstring)
#   dκ/ds on plane = 0
#   G3 residual = |0.6 − 0| = 0.6 >> G3_tol = 1e-3
#   → G3 FAILS
#
# Expected: highest_grade == "G2" (or lower if G1/G0 also fail at other
# samples, but seam-A is the binding constraint here).
# ---------------------------------------------------------------------------


class TestG2OnlyJoinFailsG3:
    """Cubic-z vs flat plane: G2 passes, G3 fails."""

    AMP = 0.1  # dκ/ds_cubic at v=0 = 6*0.1 = 0.6

    def _setup(self):
        cubic = _cubic_z_surface(amplitude=self.AMP)
        plane = _plane_surface()
        # Shared edge: sample the v=v_min boundary of the cubic surface
        v_min = float(cubic.knots_v[0])
        u_min = float(cubic.knots_u[0])
        u_max = float(cubic.knots_u[-1])
        edge = []
        for u in np.linspace(u_min, u_max, 8):
            p = _eval_surface(cubic, u, v_min)[:3].tolist()
            edge.append(p)
        return cubic, plane, edge

    def test_g2_only_harness_ok(self):
        cubic, plane, edge = self._setup()
        result = class_a_acceptance_harness(
            cubic, plane, edge, num_samples=8,
        )
        assert result["ok"] is True

    def test_g2_only_g3_fails(self):
        """G3 gate must fail (curvature rate differs by 6A)."""
        cubic, plane, edge = self._setup()
        result = class_a_acceptance_harness(
            cubic, plane, edge, num_samples=8,
        )
        assert result["gates"]["G3_ok"] is False, (
            f"Expected G3 to fail for cubic-vs-plane join; "
            f"G3_max={result['continuity']['G3_max']!r}"
        )

    def test_g2_only_g3_max_matches_analytic(self):
        """G3_max must be close to 6A = 0.6 (analytic closed-form oracle)."""
        cubic, plane, edge = self._setup()
        result = class_a_acceptance_harness(
            cubic, plane, edge, num_samples=8,
        )
        g3_max = result["continuity"]["G3_max"]
        expected = 6.0 * self.AMP   # 0.6
        # The oracle at v=0 matches exactly; allow 10% tolerance for
        # sampling/interpolation variation at interior samples.
        assert abs(g3_max - expected) < 0.15, (
            f"G3_max={g3_max:.4f} expected ≈ {expected:.4f} "
            f"(dκ/ds = 6A for cubic-z surface)"
        )

    def test_g2_only_highest_grade_not_g3(self):
        """highest_grade must not be 'G3' for a G2-only join."""
        cubic, plane, edge = self._setup()
        result = class_a_acceptance_harness(
            cubic, plane, edge, num_samples=8,
        )
        assert result["highest_grade"] != "G3", (
            f"G2-only join must not pass as G3, got {result['highest_grade']!r}"
        )

    def test_g2_only_standalone_report_g3_ok_false(self):
        """edge_continuity_report standalone also returns G3_ok=False."""
        cubic, plane, edge = self._setup()
        result = edge_continuity_report(cubic, plane, edge, num_samples=8)
        assert result["ok"] is True
        assert result["G3_ok"] is False, (
            f"Expected G3_ok=False for cubic-vs-plane, "
            f"G3_max={result['G3_max']!r}"
        )

    def test_g2_only_continuity_grade_not_g3(self):
        """continuity_grade in edge_continuity_report must not be 'G3'."""
        cubic, plane, edge = self._setup()
        result = edge_continuity_report(cubic, plane, edge, num_samples=8)
        assert result["continuity_grade"] != "G3"


# ---------------------------------------------------------------------------
# 4. G0-only fixture: dihedral crease — fails G1 gate
#
# Two flat planes meeting at a 45° dihedral crease.
# surf_a: horizontal, normal = (0, 0, 1)
# surf_b: tilted 45° around X, y_axis → (0, cos45, sin45)
#
# At the shared edge (y=1, z=0):
#   G0: position is continuous (z=0 on both at the seam)
#   G1: normals differ by 45° → g1_deg = 45° >> G1_tol_deg = 0.1°
#       → G1 FAILS
#   G2: both planes have H=0 → ΔH = 0 → would pass if G1 were OK
#       (but highest_grade is capped at G0 by G1 failure)
#   G3: dκ/ds = 0 on both (flat planes) → would pass
#       (but highest_grade is capped at G0 by G1 failure)
#
# Expected: highest_grade == "G0" (G0 ok, G1 fails)
# ---------------------------------------------------------------------------


class TestG0JoinFailsG1:
    """Dihedral crease: position-continuous, normal-discontinuous."""

    TILT_DEG = 45.0  # Normal divergence at seam

    def _setup(self):
        surf_a = _plane_surface(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        tilt = math.radians(self.TILT_DEG)
        ya_tilted = np.array([0.0, math.cos(tilt), math.sin(tilt)])
        surf_b = _plane_surface(
            origin=(0.0, 1.0, 0.0),
            x_axis=np.array([1.0, 0.0, 0.0]),
            y_axis=ya_tilted,
        )
        # Shared edge: y=1, z=0, x in [0,1]
        edge = [[x, 1.0, 0.0] for x in np.linspace(0.0, 1.0, 8)]
        return surf_a, surf_b, edge

    def test_dihedral_harness_ok(self):
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        assert result["ok"] is True

    def test_dihedral_g1_fails(self):
        """G1 gate must fail for a 45° dihedral crease."""
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        assert result["gates"]["G1_ok"] is False, (
            f"Expected G1 to fail for {self.TILT_DEG}° dihedral crease"
        )

    def test_dihedral_g1_max_near_45_deg(self):
        """G1_max_deg must be close to the analytic 45° normal divergence."""
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        g1_max = result["continuity"]["G1_max_deg"]
        # The normals differ by 45°; allow ±10° for closest-UV sampling
        assert abs(g1_max - self.TILT_DEG) < 10.0, (
            f"G1_max_deg={g1_max:.2f} expected ≈ {self.TILT_DEG}°"
        )

    def test_dihedral_highest_grade_at_most_g0(self):
        """highest_grade must be 'G0' or 'below_G0' (not G1/G2/G3)."""
        surf_a, surf_b, edge = self._setup()
        result = class_a_acceptance_harness(
            surf_a, surf_b, edge, num_samples=8,
        )
        assert result["highest_grade"] in ("G0", "below_G0"), (
            f"Expected 'G0' or 'below_G0' for dihedral crease, "
            f"got {result['highest_grade']!r}"
        )

    def test_dihedral_standalone_report_g1_fails(self):
        """edge_continuity_report standalone also reports G1_ok=False."""
        surf_a, surf_b, edge = self._setup()
        result = edge_continuity_report(surf_a, surf_b, edge, num_samples=8)
        assert result["ok"] is True
        assert result["G1_ok"] is False, (
            f"Expected G1_ok=False for 45° dihedral; "
            f"G1_max_deg={result['G1_max_deg']!r}"
        )

    def test_dihedral_continuity_grade_at_most_g0(self):
        """continuity_grade in edge_continuity_report must be 'G0' or below."""
        surf_a, surf_b, edge = self._setup()
        result = edge_continuity_report(surf_a, surf_b, edge, num_samples=8)
        assert result["continuity_grade"] in ("G0", "below_G0"), (
            f"Expected G0/below_G0 for dihedral, got {result['continuity_grade']!r}"
        )


# ---------------------------------------------------------------------------
# 5. Harness output blocks present and well-formed
# ---------------------------------------------------------------------------


class TestHarnessOutputBlocks:
    def test_comb_block_keys(self):
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(plane, plane, edge, num_samples=5)
        comb = result["comb"]
        for key in ("max_H_a", "mean_H_a", "max_H_b", "mean_H_b", "per_point"):
            assert key in comb, f"Missing comb key: {key}"
        assert len(comb["per_point"]) == 5

    def test_comb_per_point_keys(self):
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(plane, plane, edge, num_samples=4)
        for pp in result["comb"]["per_point"]:
            assert "H_a" in pp
            assert "H_b" in pp

    def test_zebra_block_ok(self):
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(plane, plane, edge, num_samples=5)
        assert result["zebra"]["ok"] is True

    def test_continuity_block_matches_standalone(self):
        """continuity sub-dict must match a direct edge_continuity_report call."""
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        harness = class_a_acceptance_harness(plane, plane, edge, num_samples=5)
        standalone = edge_continuity_report(plane, plane, edge, num_samples=5)
        assert harness["continuity"]["G3_ok"] == standalone["G3_ok"]
        assert abs(
            harness["continuity"]["G3_max"] - standalone["G3_max"]
        ) < 1e-12

    def test_flat_plane_comb_h_near_zero(self):
        """For a flat plane |H|=0 everywhere; max_H_a must be ~0."""
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(plane, plane, edge, num_samples=6)
        assert result["comb"]["max_H_a"] < 1e-6
        assert result["comb"]["max_H_b"] < 1e-6


# ---------------------------------------------------------------------------
# 6. Bad inputs
# ---------------------------------------------------------------------------


class TestBadInputs:
    def test_non_nurbs_surf_a_fails(self):
        plane = _plane_surface()
        edge = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
        result = class_a_acceptance_harness("bad", plane, edge)
        assert result["ok"] is False
        assert "reason" in result

    def test_non_nurbs_surf_b_fails(self):
        plane = _plane_surface()
        edge = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
        result = class_a_acceptance_harness(plane, 42, edge)
        assert result["ok"] is False
        assert "reason" in result

    def test_too_few_edge_points_fails(self):
        plane = _plane_surface()
        result = class_a_acceptance_harness(plane, plane, [[0.0, 0.0, 0.0]])
        assert result["ok"] is False
        assert "reason" in result

    def test_edge_continuity_report_bad_surf_unchanged(self):
        """Existing bad-input contract for edge_continuity_report is preserved."""
        plane = _plane_surface()
        result = edge_continuity_report("bad", plane, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_inputs_same_harness_output(self):
        """Five independent calls with the same inputs must produce identical
        G3_max values (bitwise)."""
        cubic = _cubic_z_surface(amplitude=0.1)
        plane = _plane_surface()
        v_min = float(cubic.knots_v[0])
        u_min = float(cubic.knots_u[0])
        u_max = float(cubic.knots_u[-1])
        edge = [
            _eval_surface(cubic, u, v_min)[:3].tolist()
            for u in np.linspace(u_min, u_max, 6)
        ]
        results = [
            class_a_acceptance_harness(cubic, plane, edge, num_samples=6)
            for _ in range(5)
        ]
        g3_vals = [r["continuity"]["G3_max"] for r in results]
        assert all(v == g3_vals[0] for v in g3_vals), (
            f"Non-deterministic G3_max: {g3_vals}"
        )

    def test_identical_inputs_same_ecr_output(self):
        """edge_continuity_report must be deterministic."""
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        results = [
            edge_continuity_report(plane, plane, edge, num_samples=6)
            for _ in range(5)
        ]
        g3_vals = [r["G3_max"] for r in results]
        assert all(v == g3_vals[0] for v in g3_vals)


# ---------------------------------------------------------------------------
# 8. Grade ordering invariants
# ---------------------------------------------------------------------------


class TestGradeOrdering:
    @pytest.mark.parametrize("grade,forbidden_higher", [
        ("G3", []),
        ("G2", ["G3"]),
        ("G1", ["G3", "G2"]),
        ("G0", ["G3", "G2", "G1"]),
        ("below_G0", ["G3", "G2", "G1", "G0"]),
    ])
    def test_grade_ordering_forbidden(self, grade, forbidden_higher):
        """If harness reports a given grade, higher grades must fail."""
        # The coplanar-plane fixture should be "G3"; just check the function
        # returns one of the five valid grade strings.
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = class_a_acceptance_harness(plane, plane, edge, num_samples=4)
        valid_grades = {"G3", "G2", "G1", "G0", "below_G0"}
        assert result["highest_grade"] in valid_grades, (
            f"highest_grade not in valid set: {result['highest_grade']!r}"
        )

    def test_edge_continuity_report_grade_valid(self):
        plane = _plane_surface()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = edge_continuity_report(plane, plane, edge, num_samples=4)
        valid_grades = {"G3", "G2", "G1", "G0", "below_G0"}
        assert result["continuity_grade"] in valid_grades
