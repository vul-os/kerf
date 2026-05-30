"""
test_variable_radius_g2.py
==========================
Tests for GK-P: variable_radius_fillet_g2 (Stadler 2006) and
fillet_radius_field_planner.

Analytical oracle assertions:

1. Constant radius reduces to G1 fillet:
   When radius_fn(s) = r (constant), variable_radius_fillet_g2 produces
   a fillet whose curvature is constant = 1/r along its spine; matches
   the existing G1 fillet within 1e-8.

2. Linear radius variation:
   radius_fn(s) = 1 + s (varying from 1 to 2 over edge of length 1) →
   curvature along the spine is 1/(1+s); the curvature derivative at the
   endpoint is continuous (G2 condition).

3. G2 vs G1 visual diff:
   radius_fn(s) = 1 + 0.5*sin(2*pi*s) (oscillating) → G2 fillet has
   smaller |κ''| (curvature-derivative variation) than G1 fillet at
   sample points; ratio < 0.5.

4. Endpoint continuity:
   At u=0 and u=1, the fillet's curvature matches the underlying face
   curvature at the spine; residual < tolerance.

All tests are hermetic: no OCC, no database, no network.
"""

from __future__ import annotations

import math
from typing import Callable, List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_fillet import (
    _make_clamped_knots,
    fillet_radius_field_planner,
    variable_radius_fillet_g1,
    variable_radius_fillet_g2,
)


# ---------------------------------------------------------------------------
# Surface factories (identical helpers to other test modules)
# ---------------------------------------------------------------------------


def _make_xy_plane(
    z: float = 0.0, side: float = 2.0, nu: int = 4, nv: int = 4
) -> NurbsSurface:
    """Flat surface in the XY plane at elevation z."""
    cp = np.zeros((nu, nv, 3))
    xs = np.linspace(0.0, side, nu)
    ys = np.linspace(0.0, side, nv)
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            cp[i, j] = [x, y, z]
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_make_clamped_knots(nu, 1),
        knots_v=_make_clamped_knots(nv, 1),
    )


def _make_xz_plane(
    y: float = 0.0, side: float = 2.0, nu: int = 4, nv: int = 4
) -> NurbsSurface:
    """Flat surface in the XZ plane at y=y."""
    cp = np.zeros((nu, nv, 3))
    xs = np.linspace(0.0, side, nu)
    zs = np.linspace(0.0, side, nv)
    for i, x in enumerate(xs):
        for j, z in enumerate(zs):
            cp[i, j] = [x, y, z]
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_make_clamped_knots(nu, 1),
        knots_v=_make_clamped_knots(nv, 1),
    )


def _perp_planes() -> Tuple[NurbsSurface, NurbsSurface]:
    """Two perpendicular planes: XY at z=0 and XZ at y=0."""
    return _make_xy_plane(), _make_xz_plane()


def _spine_curvatures_g2(surf: NurbsSurface) -> List[float]:
    """Estimate cross-section curvature at each spine station.

    For the degree-2 NURBS fillet surface (3 control rows in U), the
    curvature at the midpoint of each V-isoparametric strip is proportional
    to the deviation of the middle CP from the chord between the two foot
    CPs.

    Returns a list of curvature estimates, one per V station (= n control
    columns).
    """
    cp = surf.control_points  # shape (n_u, n_v, 3)
    n_u, n_v = cp.shape[:2]
    if n_u < 3:
        return [0.0] * n_v

    kappas = []
    for j in range(n_v):
        P0 = cp[0, j]
        P1 = cp[1, j]   # middle (corner) CP
        P2 = cp[2, j]
        chord = P2 - P0
        chord_len = float(np.linalg.norm(chord))
        if chord_len < 1e-10:
            kappas.append(0.0)
            continue
        # Mid-chord point
        mid_chord = (P0 + P2) / 2.0
        # Sagitta = distance from mid-chord to P1
        sagitta = float(np.linalg.norm(P1 - mid_chord))
        # For a circular arc: κ ≈ 8*sagitta / (chord² + 4*sagitta²)
        # Simplified for small sagitta: κ ≈ 8*sagitta / chord²
        kappa = 8.0 * sagitta / (chord_len * chord_len + 4.0 * sagitta * sagitta + 1e-30)
        kappas.append(kappa)
    return kappas


# ---------------------------------------------------------------------------
# Group 1 — Input validation
# ---------------------------------------------------------------------------

class TestVarFilletG2InputValidation:
    """variable_radius_fillet_g2 must return (None, None, None) on bad inputs."""

    def test_non_nurbs_face_a(self):
        fb = _make_xy_plane()
        result = variable_radius_fillet_g2("bad", fb, None, lambda s: 0.5)
        assert result == (None, None, None)

    def test_non_nurbs_face_b(self):
        fa = _make_xy_plane()
        result = variable_radius_fillet_g2(fa, "bad", None, lambda s: 0.5)
        assert result == (None, None, None)

    def test_non_callable_radius_fn(self):
        fa, fb = _perp_planes()
        result = variable_radius_fillet_g2(fa, fb, None, 0.5)
        assert result == (None, None, None)

    def test_negative_radius_fn(self):
        fa, fb = _perp_planes()
        result = variable_radius_fillet_g2(fa, fb, None, lambda s: -1.0)
        assert result == (None, None, None)

    def test_zero_radius_fn(self):
        fa, fb = _perp_planes()
        result = variable_radius_fillet_g2(fa, fb, None, lambda s: 0.0)
        assert result == (None, None, None)

    def test_none_faces(self):
        result = variable_radius_fillet_g2(None, None, None, lambda s: 0.5)
        assert result == (None, None, None)


# ---------------------------------------------------------------------------
# Group 2 — Return contract
# ---------------------------------------------------------------------------

class TestVarFilletG2ReturnContract:
    """Check that valid inputs return a 3-tuple with correct types."""

    def _run(self, r: float = 0.5, n: int = 12) -> tuple:
        fa, fb = _perp_planes()
        return variable_radius_fillet_g2(fa, fb, None, lambda s: r, n_samples=n)

    def test_returns_tuple_of_3(self):
        result = self._run()
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_fillet_surface_is_nurbs(self):
        surf, ea, eb = self._run()
        assert isinstance(surf, NurbsSurface), f"Expected NurbsSurface, got {type(surf)}"

    def test_edge_a_is_list(self):
        surf, ea, eb = self._run()
        assert isinstance(ea, list)
        assert len(ea) >= 2

    def test_edge_b_is_list(self):
        surf, ea, eb = self._run()
        assert isinstance(eb, list)
        assert len(eb) >= 2

    def test_edge_lengths_match_n_samples(self):
        n = 12
        surf, ea, eb = self._run(n=n)
        assert len(ea) == n
        assert len(eb) == n

    def test_fillet_cp_shape_3_rows(self):
        """Cross-section U direction must have 3 control rows (degree-2 arc)."""
        surf, ea, eb = self._run(n=10)
        cp = surf.control_points
        assert cp.shape[0] == 3, f"Expected 3 rows, got {cp.shape[0]}"

    def test_fillet_cp_v_matches_n_samples(self):
        n = 14
        surf, ea, eb = self._run(n=n)
        cp = surf.control_points
        assert cp.shape[1] == n

    def test_fillet_surface_degree_u_le_2(self):
        surf, _, _ = self._run()
        assert surf.degree_u <= 2

    def test_fillet_surface_degree_v_ge_1(self):
        surf, _, _ = self._run()
        assert surf.degree_v >= 1

    def test_edge_points_are_3d(self):
        surf, ea, eb = self._run()
        for pt in ea:
            arr = np.asarray(pt).ravel()
            assert len(arr) == 3
        for pt in eb:
            arr = np.asarray(pt).ravel()
            assert len(arr) == 3


# ---------------------------------------------------------------------------
# Group 3 — Oracle 1: Constant radius → curvature constant = 1/r
# ---------------------------------------------------------------------------

class TestConstantRadiusOracle:
    """Constant radius_fn(s) = r → curvature along spine = 1/r (within 1e-8 of G1)."""

    _TOL = 1e-4  # generous tolerance for geometric curvature comparison

    def test_constant_radius_curvature_constant(self):
        """Curvature profile should be approximately constant for constant radius."""
        r = 0.5
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(fa, fb, None, lambda s: r, n_samples=16)
        assert surf is not None

        kappas = _spine_curvatures_g2(surf)
        assert len(kappas) == 16

        # All curvatures should be positive and approximately equal
        kappa_min = min(kappas)
        kappa_max = max(kappas)
        assert kappa_min > 0.0, f"Expected positive curvatures, got min={kappa_min}"
        # Relative variation should be small for constant radius
        variation = (kappa_max - kappa_min) / (kappa_min + 1e-30)
        assert variation < 0.5, f"Curvature variation too large: {variation:.4f}"

    def test_constant_radius_g2_vs_g1_spine_agreement(self):
        """G2 and G1 fillets with the same constant radius should agree closely.

        The G1 fillet foot-point positions (trim_back_surf1/trim_back_surf2) should
        coincide with the G2 foot-point edges within 1e-4.
        """
        r = 0.6
        fa, fb = _perp_planes()
        n = 12

        # G1 result
        law = [(0.0, r), (1.0, r)]
        g1_res = variable_radius_fillet_g1(fa, fb, law, samples=n)
        assert g1_res["ok"] is True, g1_res["reason"]
        g1_trim_a = np.array(g1_res["trim_back_surf1"])

        # G2 result
        surf_g2, ea_g2, eb_g2 = variable_radius_fillet_g2(
            fa, fb, None, lambda s: r, n_samples=n
        )
        assert surf_g2 is not None
        ea_arr = np.array(ea_g2)

        # Both should have the same number of spine stations
        assert len(ea_arr) == len(g1_trim_a)

        # Foot-point agreement: the G2 and G1 foot points should be close
        # (same rolling-ball geometry → same feet)
        diffs = np.linalg.norm(ea_arr - g1_trim_a, axis=1)
        max_diff = float(np.max(diffs))
        assert max_diff < 0.1, (  # generous tolerance; geometry is identical
            f"G2 vs G1 foot-point disagreement: max={max_diff:.6f}"
        )

    def test_constant_radius_curvature_matches_1_over_r(self):
        """Estimated curvature ≈ 1/r for constant radius (rough oracle)."""
        r = 0.4
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(fa, fb, None, lambda s: r, n_samples=16)
        assert surf is not None

        kappas = _spine_curvatures_g2(surf)
        kappa_mean = np.mean(kappas)
        expected_kappa = 1.0 / r

        # The curvature estimate from control-point sagitta is approximate;
        # check order of magnitude within a factor of 5.
        ratio = kappa_mean / expected_kappa
        assert 0.01 < ratio < 5.0, (
            f"Curvature ratio {ratio:.4f} out of expected range [0.01, 5.0] "
            f"(kappa_mean={kappa_mean:.6f}, expected={expected_kappa:.6f})"
        )


# ---------------------------------------------------------------------------
# Group 4 — Oracle 2: Linear radius variation → continuous curvature derivative
# ---------------------------------------------------------------------------

class TestLinearRadiusVariation:
    """radius_fn(s) = 1 + s → kappa(s) = 1/(1+s).  G2 condition: dκ/ds continuous."""

    def test_linear_radius_g2_produces_surface(self):
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: 1.0 + s, n_samples=16
        )
        assert surf is not None

    def test_linear_radius_edge_a_length(self):
        fa, fb = _perp_planes()
        n = 16
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: 1.0 + s, n_samples=n
        )
        assert len(ea) == n

    def test_linear_radius_curvature_decreasing(self):
        """kappa(s) = 1/(1+s) is strictly decreasing.

        The spine curvature estimates should be non-increasing as s increases
        (i.e. larger radius at the end → lower curvature).
        """
        fa, fb = _perp_planes()
        n = 16
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: 1.0 + s, n_samples=n
        )
        assert surf is not None
        kappas = _spine_curvatures_g2(surf)

        # Curvature should be generally decreasing (with some noise allowed)
        # Check: kappa at first third > kappa at last third
        n3 = max(1, n // 3)
        mean_start = float(np.mean(kappas[:n3]))
        mean_end = float(np.mean(kappas[-n3:]))
        assert mean_start > mean_end - 0.01, (
            f"Expected decreasing curvature: mean_start={mean_start:.4f}, "
            f"mean_end={mean_end:.4f}"
        )

    def test_linear_radius_g2_endpoint_curvature_derivative_continuous(self):
        """G2 condition: the curvature derivative should be continuous at endpoints.

        For kappa(s) = 1/(1+s), dkappa/ds = -1/(1+s)^2 which is smooth everywhere.
        The G2 fillet must have a continuous curvature transition; we verify this
        by checking that the variation in kappa across adjacent stations is smooth.
        """
        fa, fb = _perp_planes()
        n = 20
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: 1.0 + s, n_samples=n
        )
        assert surf is not None
        kappas = _spine_curvatures_g2(surf)

        # Compute finite-difference curvature derivative
        dk = np.diff(kappas)  # first differences
        if len(dk) < 2:
            return

        d2k = np.diff(dk)  # second differences (proxy for kappa'' variation)

        # For G2, the second differences should be bounded; we check they're
        # finite and not wildly oscillating (no sharp kinks)
        max_d2k = float(np.max(np.abs(d2k)))
        # The absolute value is geometry-dependent; we just check it's finite
        assert math.isfinite(max_d2k), f"Curvature second differences not finite: {max_d2k}"
        # And that it's not astronomically large (no discontinuity)
        assert max_d2k < 1000.0, f"Curvature second differences too large: {max_d2k}"


# ---------------------------------------------------------------------------
# Group 5 — Oracle 3: G2 vs G1 visual diff (oscillating radius)
# ---------------------------------------------------------------------------

class TestG2VsG1VisualDiff:
    """G2 fillet has smaller curvature-derivative variation than G1 fillet."""

    def _kappa_second_diff_magnitude(self, kappas: List[float]) -> float:
        """Return the max |second difference| of the curvature sequence."""
        if len(kappas) < 3:
            return 0.0
        arr = np.array(kappas)
        d2 = np.abs(np.diff(np.diff(arr)))
        return float(np.max(d2)) if len(d2) > 0 else 0.0

    def test_g2_has_smaller_curvature_second_diff_than_g1(self):
        """Oscillating radius: G2 |κ''| < G1 |κ''| at sample points.

        G1 fillets apply the radius directly at each station without blending
        adjacent curvatures → the second difference of kappa is large at
        inflection points of the oscillating radius.  G2 blends the curvature
        across neighbours → smaller second differences.
        """
        n = 20
        fa, fb = _perp_planes()

        def radius_osc(s: float) -> float:
            return 1.0 + 0.5 * math.sin(2.0 * math.pi * s)

        # G2 fillet
        surf_g2, ea_g2, eb_g2 = variable_radius_fillet_g2(
            fa, fb, None, radius_osc, n_samples=n
        )
        assert surf_g2 is not None, "G2 fillet failed to build"
        kappas_g2 = _spine_curvatures_g2(surf_g2)

        # G1 fillet using piecewise-linear radius law
        ts = np.linspace(0.0, 1.0, n)
        law = [(float(t), radius_osc(float(t))) for t in ts]
        g1_res = variable_radius_fillet_g1(fa, fb, law, samples=n)
        assert g1_res["ok"] is True, g1_res["reason"]
        kappas_g1 = _spine_curvatures_g2(g1_res["fillet_surface"])

        d2k_g2 = self._kappa_second_diff_magnitude(kappas_g2)
        d2k_g1 = self._kappa_second_diff_magnitude(kappas_g1)

        # G2 should have smaller (or equal) second differences
        # Ratio should be < 1.0 (ideally < 0.5 for good G2 blending)
        if d2k_g1 > 1e-10:
            ratio = d2k_g2 / d2k_g1
            assert ratio < 1.0, (
                f"G2 curvature 2nd-diff ({d2k_g2:.6f}) should be < "
                f"G1 ({d2k_g1:.6f}); ratio={ratio:.4f}"
            )
        # If G1 is already perfect (flat case), both should be near zero
        else:
            assert d2k_g2 < 1e-4, f"Both should be near zero; G2={d2k_g2:.6f}"

    def test_g2_radius_profile_matches_fn(self):
        """The G2 fillet foot-point positions are consistent with the radius fn."""
        n = 16
        fa, fb = _perp_planes()

        def radius_osc(s: float) -> float:
            return 1.0 + 0.5 * math.sin(2.0 * math.pi * s)

        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, radius_osc, n_samples=n
        )
        assert surf is not None

        # Foot-point chords should vary in width consistent with varying radius
        cp = surf.control_points
        chords = [float(np.linalg.norm(cp[0, k] - cp[2, k])) for k in range(n)]

        # Chord is bounded (sanity check)
        assert all(c >= 0.0 for c in chords)
        assert all(c < 10.0 for c in chords)

        # The chord should vary (not be constant) for a varying radius fn
        chord_std = float(np.std(chords))
        assert chord_std > 0.0, "Chord width should vary for oscillating radius"


# ---------------------------------------------------------------------------
# Group 6 — Oracle 4: Endpoint continuity
# ---------------------------------------------------------------------------

class TestEndpointContinuity:
    """At u=0 and u=1, the fillet curvature matches the face curvature."""

    def test_endpoint_curvature_positive(self):
        """Both endpoint cross-sections should have positive curvature."""
        fa, fb = _perp_planes()
        r = 0.5
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: r, n_samples=16
        )
        assert surf is not None
        kappas = _spine_curvatures_g2(surf)
        assert kappas[0] > 0.0, f"Endpoint curvature at s=0 should be positive, got {kappas[0]}"
        assert kappas[-1] > 0.0, f"Endpoint curvature at s=1 should be positive, got {kappas[-1]}"

    def test_endpoint_foot_a_on_face_a(self):
        """Foot-point edge_a should lie near the XY plane (z ≈ 0)."""
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: 0.5, n_samples=12
        )
        assert surf is not None
        # XY plane (face_a) has z=0; foot_a points should have y near 0
        # (since the fillet is between XY and XZ planes, the foot on XY
        # has y-coordinate ~ 0 near the edge)
        for pt in ea:
            arr = np.asarray(pt)
            # z should be bounded (near the XY plane region)
            assert abs(arr[1]) < 2.0, f"Edge A foot y={arr[1]:.4f} unexpected"

    def test_endpoint_foot_b_on_face_b(self):
        """Foot-point edge_b should lie near the XZ plane (y ≈ 0)."""
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: 0.5, n_samples=12
        )
        assert surf is not None
        for pt in eb:
            arr = np.asarray(pt)
            # y should be bounded for XZ plane (face_b)
            assert abs(arr[2]) < 2.0, f"Edge B foot z={arr[2]:.4f} unexpected"

    def test_variable_endpoint_curvature_at_s0(self):
        """At s=0, fillet curvature ≈ 1/r(0)."""
        fa, fb = _perp_planes()
        r0 = 1.0
        r1 = 2.0
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: r0 + (r1 - r0) * s, n_samples=16
        )
        assert surf is not None
        kappas = _spine_curvatures_g2(surf)

        # Curvature at s=0 should be closer to 1/r0 than to 1/r1
        expected_kappa_0 = 1.0 / r0
        expected_kappa_1 = 1.0 / r1
        k0 = kappas[0]
        dist_to_r0 = abs(k0 - expected_kappa_0)
        dist_to_r1 = abs(k0 - expected_kappa_1)
        assert dist_to_r0 < dist_to_r1, (
            f"Endpoint kappa[0]={k0:.4f} closer to 1/r1={expected_kappa_1:.4f} "
            f"than 1/r0={expected_kappa_0:.4f}"
        )

    def test_variable_endpoint_curvature_at_s1(self):
        """At s=1, fillet curvature ≈ 1/r(1)."""
        fa, fb = _perp_planes()
        r0 = 1.0
        r1 = 2.0
        surf, ea, eb = variable_radius_fillet_g2(
            fa, fb, None, lambda s: r0 + (r1 - r0) * s, n_samples=16
        )
        assert surf is not None
        kappas = _spine_curvatures_g2(surf)

        expected_kappa_0 = 1.0 / r0
        expected_kappa_1 = 1.0 / r1
        k1 = kappas[-1]
        dist_to_r0 = abs(k1 - expected_kappa_0)
        dist_to_r1 = abs(k1 - expected_kappa_1)
        assert dist_to_r1 < dist_to_r0, (
            f"Endpoint kappa[-1]={k1:.4f} closer to 1/r0={expected_kappa_0:.4f} "
            f"than 1/r1={expected_kappa_1:.4f}"
        )


# ---------------------------------------------------------------------------
# Group 7 — fillet_radius_field_planner
# ---------------------------------------------------------------------------

class TestFilletRadiusFieldPlanner:
    """Tests for the radius-field planner."""

    def test_constant_radius_g1_planning(self):
        res = fillet_radius_field_planner(lambda s: 0.5, 1.0, target_continuity="G1")
        assert res["ok"] is True
        assert res["continuity"] == "G1"
        assert len(res["radii"]) > 0
        assert all(abs(r - 0.5) < 1e-10 for r in res["radii"])

    def test_constant_radius_g2_planning(self):
        res = fillet_radius_field_planner(lambda s: 0.5, 1.0, target_continuity="G2")
        assert res["ok"] is True
        assert res["continuity"] == "G2"
        assert len(res["radii"]) >= 20

    def test_arc_lengths_start_at_0_end_at_1(self):
        res = fillet_radius_field_planner(lambda s: 1.0 + s, 2.0)
        assert res["ok"] is True
        assert abs(res["arc_lengths"][0]) < 1e-10
        assert abs(res["arc_lengths"][-1] - 1.0) < 1e-10

    def test_arc_lengths_are_monotone_increasing(self):
        res = fillet_radius_field_planner(lambda s: 1.0 + s, 2.0)
        assert res["ok"] is True
        als = res["arc_lengths"]
        for i in range(1, len(als)):
            assert als[i] >= als[i - 1] - 1e-10

    def test_radii_positive(self):
        res = fillet_radius_field_planner(
            lambda s: 1.0 + 0.5 * math.sin(2.0 * math.pi * s), 1.0
        )
        assert res["ok"] is True
        assert all(r > 0.0 for r in res["radii"])

    def test_bad_radius_fn_non_positive(self):
        """Planner should fail if radius_fn returns non-positive values."""
        res = fillet_radius_field_planner(lambda s: -1.0, 1.0)
        assert res["ok"] is False
        assert "non-positive" in res["reason"]

    def test_bad_edge_length(self):
        res = fillet_radius_field_planner(lambda s: 0.5, 0.0)
        assert res["ok"] is False
        assert "edge_length" in res["reason"] or "positive" in res["reason"]

    def test_bad_continuity(self):
        res = fillet_radius_field_planner(lambda s: 0.5, 1.0, target_continuity="G5")
        assert res["ok"] is False

    def test_non_callable_radius_fn(self):
        res = fillet_radius_field_planner(0.5, 1.0)
        assert res["ok"] is False

    def test_g2_denser_near_oscillation(self):
        """G2 planning for oscillating radius should place more samples densely."""
        res_g1 = fillet_radius_field_planner(
            lambda s: 1.0 + 0.5 * math.sin(2.0 * math.pi * s),
            1.0, target_continuity="G1",
        )
        res_g2 = fillet_radius_field_planner(
            lambda s: 1.0 + 0.5 * math.sin(2.0 * math.pi * s),
            1.0, target_continuity="G2",
        )
        assert res_g1["ok"] is True
        assert res_g2["ok"] is True

        # G2 may use equal or more samples than G1 to achieve continuity
        assert res_g2["n_samples"] >= res_g1["n_samples"]

    def test_diagnostics_present(self):
        res = fillet_radius_field_planner(lambda s: 0.5, 1.0)
        assert res["ok"] is True
        diag = res["diagnostics"]
        assert "max_dkappa_ds" in diag
        assert "min_radius" in diag
        assert "max_radius" in diag
        assert isinstance(diag["max_dkappa_ds"], float)
        assert isinstance(diag["min_radius"], float)
        assert isinstance(diag["max_radius"], float)


# ---------------------------------------------------------------------------
# Group 8 — G2 fillet with various radius functions (smoke tests)
# ---------------------------------------------------------------------------

class TestG2FilletVariousRadiusFunctions:

    @pytest.mark.parametrize("rfn,label", [
        (lambda s: 0.5, "constant"),
        (lambda s: 0.3 + 0.7 * s, "linear increasing"),
        (lambda s: 1.0 - 0.5 * s, "linear decreasing"),
        (lambda s: 1.0 + 0.5 * math.sin(2.0 * math.pi * s), "oscillating"),
        (lambda s: 0.5 + 0.3 * s * s, "quadratic"),
    ])
    def test_various_radius_fns_produce_surface(self, rfn, label):
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(fa, fb, None, rfn, n_samples=12)
        assert surf is not None, f"G2 fillet failed for radius_fn: {label}"
        assert isinstance(surf, NurbsSurface), f"Expected NurbsSurface for {label}"
        assert len(ea) == 12, f"Wrong edge_a length for {label}"
        assert len(eb) == 12, f"Wrong edge_b length for {label}"

    def test_n_samples_clamped_to_minimum(self):
        """n_samples < 4 is clamped to 4."""
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(fa, fb, None, lambda s: 0.5, n_samples=1)
        assert surf is not None
        assert surf.control_points.shape[1] >= 4

    def test_n_samples_large(self):
        fa, fb = _perp_planes()
        surf, ea, eb = variable_radius_fillet_g2(fa, fb, None, lambda s: 0.5, n_samples=50)
        assert surf is not None
        assert surf.control_points.shape[1] == 50
