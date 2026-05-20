"""GK-38 — Zebra / reflection-line continuity analyser (canonical oracle tests).

Verifies the ORACLE contract stated in the GK-38 task:

  ORACLE A  — G1 join  → zebra stripes CONTINUOUS (stripe_G1_ok = True,
                          continuity_grade = "G2+" or "G1")
  ORACLE B  — G0 join  → zebra stripes BROKEN (stripe-tangent discontinuity
                          detected: stripe_G1_ok = False OR stripe_G0_max > 0)

Both oracles are backed by closed-form analytic references.  No network, no
OCCT, no database.

Surface constructions
---------------------
G1 join   — two coplanar flat planes sharing an edge.  Both have the same
            outward normal everywhere (κ = 0).  Analytic oracle:
              Z_a = Z_b  (normals identical)
              dZ_a/ds = dZ_b/ds = 0  (flat → dn/ds = 0 → dZ/ds = 0)
            ⇒ stripe_G1_ok = True,  continuity_grade ∈ {"G2+", "G1"}

G0 join   — two flat planes meeting at a 30° dihedral crease (position-
            continuous, but normal-discontinuous).
            With light = [0, 0, 1]:
              n_a = (0, 0, 1)            nL_a = 1.0
              n_b = (0, -sin30, cos30)   nL_b = cos(30°) ≈ 0.866
            The stripe VALUES differ at the seam (|Z_a − Z_b| > 0) →
            stripe_G0_max > 0 → grade ≠ "G2+" / "G1" → stripe is "broken".
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_analysis import (
    zebra_stripe_continuity_analyser,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamped(n: int, degree: int) -> np.ndarray:
    """Clamped open knot vector for n control points and given degree."""
    inner = max(0, n - degree - 1)
    parts = [np.zeros(degree + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(degree + 1))
    return np.concatenate(parts)


def _flat_plane(
    origin=(0.0, 0.0, 0.0),
    x_axis=(1.0, 0.0, 0.0),
    y_axis=(0.0, 1.0, 0.0),
    nu: int = 4,
    nv: int = 4,
) -> NurbsSurface:
    """Flat cubic NURBS plane patch (zero curvature everywhere)."""
    origin = np.asarray(origin, dtype=float)
    xa = np.asarray(x_axis, dtype=float)
    ya = np.asarray(y_axis, dtype=float)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = origin + (i / (nu - 1)) * xa + (j / (nv - 1)) * ya
    deg = min(3, nu - 1, nv - 1)
    return NurbsSurface(
        degree_u=deg,
        degree_v=deg,
        control_points=cp,
        knots_u=_clamped(nu, deg),
        knots_v=_clamped(nv, deg),
    )


def _shared_edge(x_range=(0.0, 1.0), y: float = 1.0, z: float = 0.0, n: int = 8):
    """Axis-aligned edge polyline at constant (y, z)."""
    return [[x, y, z] for x in np.linspace(x_range[0], x_range[1], n)]


# ---------------------------------------------------------------------------
# ORACLE A — G1 join: coplanar flat planes → stripes CONTINUOUS
# ---------------------------------------------------------------------------


class TestZebraG1JoinContinuous:
    """ORACLE A: two coplanar flat planes sharing an edge.

    Analytic expectations:
    - Z_a = Z_b at every seam point (normals identical).
    - dZ_a/ds = dZ_b/ds = 0 (flat surface, κ=0, Weingarten → dn/ds=0).
    - stripe_G1_tangent_max = 0 exactly.
    - stripe_G1_ok = True.
    - continuity_grade ∈ {"G2+", "G1"} (passes G1 gate).
    """

    def _surfaces(self):
        surf_a = _flat_plane(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        surf_b = _flat_plane(
            origin=(0.0, 1.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        edge = _shared_edge(x_range=(0.0, 1.0), y=1.0, z=0.0, n=10)
        return surf_a, surf_b, edge

    def test_oracle_a_stripe_G1_ok_true(self):
        """ORACLE A: G1 join must report stripe_G1_ok = True."""
        sa, sb, edge = self._surfaces()
        r = zebra_stripe_continuity_analyser(
            sa, sb, edge, num_samples=10, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert r["ok"] is True
        assert r["stripe_G1_ok"] is True, (
            f"ORACLE A: G1 join must pass stripe_G1_ok; "
            f"stripe_G1_tangent_max={r['stripe_G1_tangent_max']!r}"
        )

    def test_oracle_a_stripe_G1_tangent_near_zero(self):
        """ORACLE A: flat-plane G1 join → dZ/ds = 0 on both sides."""
        sa, sb, edge = self._surfaces()
        r = zebra_stripe_continuity_analyser(
            sa, sb, edge, num_samples=10, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0],
        )
        assert r["ok"] is True
        assert r["stripe_G1_tangent_max"] < 1e-3, (
            f"ORACLE A: flat coplanar planes → stripe tangent ≈ 0; "
            f"got {r['stripe_G1_tangent_max']!r}"
        )

    def test_oracle_a_grade_passes_G1(self):
        """ORACLE A: continuity_grade must be 'G2+' or 'G1' (not 'G0' / 'below_G0')."""
        sa, sb, edge = self._surfaces()
        r = zebra_stripe_continuity_analyser(
            sa, sb, edge, num_samples=8, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert r["ok"] is True
        assert r["continuity_grade"] in ("G2+", "G1"), (
            f"ORACLE A: G1 join must pass G1 grade; got {r['continuity_grade']!r}"
        )

    def test_oracle_a_same_surface_exact_zero(self):
        """ORACLE A: same surface on both sides → stripe tangent = 0 exactly."""
        surf = _flat_plane()
        u_mid = 0.5
        edge = [[x, u_mid, 0.0] for x in np.linspace(0.0, 1.0, 6)]
        r = zebra_stripe_continuity_analyser(
            surf, surf, edge, num_samples=6, n_stripes=8,
        )
        assert r["ok"] is True
        assert r["stripe_G1_tangent_max"] < 1e-6, (
            f"ORACLE A: same-surface stripe tangent must be 0; "
            f"got {r['stripe_G1_tangent_max']!r}"
        )
        assert r["stripe_G1_ok"] is True
        assert r["continuity_grade"] == "G2+"


# ---------------------------------------------------------------------------
# ORACLE B — G0 join: dihedral crease → stripes BROKEN
# ---------------------------------------------------------------------------


class TestZebraG0JoinBroken:
    """ORACLE B: two flat planes meeting at a dihedral crease.

    Position is continuous (G0 satisfied) but the normals differ.

    Analytic oracle (light = [0, 0, 1], n_stripes = 8):
        surf_a: normal = (0, 0, 1)           nL_a = 1.0
        surf_b: normal = (0, -sin30, cos30)  nL_b = cos(30°) ≈ 0.866
        Z_a = 0.5 + 0.5 * cos(8π * 1.0)    = 1.0  (cos(8π)   = 1)
        Z_b = 0.5 + 0.5 * cos(8π * 0.866)  ≈ 0.5 + 0.5 * cos(21.77 rad)
        |Z_a − Z_b| > 0  (stripe value discontinuous at seam)

    For n_stripes=7 (odd), nL_a=1:
        Z_a = 0.5 + 0.5 * cos(7π) = 0.5 − 0.5 = 0.0
        Vertical wall nL_b=0:
        Z_b = 0.5 + 0.5 * cos(0) = 1.0
        |Z_a − Z_b| = 1.0  (maximum possible break)
    """

    def _dihedral_30(self):
        """30° dihedral: horizontal plane + tilted plane sharing y=1 edge."""
        surf_a = _flat_plane(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        tilt = math.radians(30.0)
        ya_tilted = np.array([0.0, math.cos(tilt), math.sin(tilt)])
        surf_b = _flat_plane(
            origin=(0.0, 1.0, 0.0),
            x_axis=np.array([1.0, 0.0, 0.0]),
            y_axis=ya_tilted,
        )
        edge = _shared_edge(x_range=(0.0, 1.0), y=1.0, z=0.0, n=8)
        return surf_a, surf_b, edge

    def test_oracle_b_G0_stripe_break_detected(self):
        """ORACLE B: G0 join must have stripe_G0_max > 0 (stripes broken)."""
        sa, sb, edge = self._dihedral_30()
        r = zebra_stripe_continuity_analyser(
            sa, sb, edge, num_samples=8, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert r["ok"] is True
        assert r["stripe_G0_max"] > 1e-4, (
            f"ORACLE B: 30° dihedral must produce G0 stripe break; "
            f"stripe_G0_max={r['stripe_G0_max']!r}"
        )

    def test_oracle_b_stripe_G1_ok_false(self):
        """ORACLE B: G0 join must fail the G1 stripe gate (stripes broken)."""
        sa, sb, edge = self._dihedral_30()
        r = zebra_stripe_continuity_analyser(
            sa, sb, edge, num_samples=8, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert r["ok"] is True
        assert r["stripe_G1_ok"] is False, (
            f"ORACLE B: 30° dihedral must fail stripe_G1_ok; "
            f"grade={r['continuity_grade']!r}, G0={r['stripe_G0_max']!r}"
        )

    def test_oracle_b_grade_not_passing(self):
        """ORACLE B: continuity_grade must be 'G0' or 'below_G0' (not G1/G2+)."""
        sa, sb, edge = self._dihedral_30()
        r = zebra_stripe_continuity_analyser(
            sa, sb, edge, num_samples=8, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert r["ok"] is True
        assert r["continuity_grade"] in ("G0", "below_G0"), (
            f"ORACLE B: 30° dihedral must not pass G1 grade; "
            f"got {r['continuity_grade']!r}"
        )

    def test_oracle_b_analytic_stripe_values(self):
        """ORACLE B closed-form check for 90° dihedral with n_stripes=7.

        n_a = (0,0,1) → nL_a = 1.0 → Z_a = 0.5 + 0.5*cos(7π) = 0.0
        n_b = (0,-1,0) → nL_b = 0.0 → Z_b = 0.5 + 0.5*cos(0)  = 1.0
        |Z_a − Z_b| = 1.0 (maximum stripe break)
        """
        surf_a = _flat_plane(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        # Vertical wall extending in +Z from y=1
        surf_b = _flat_plane(
            origin=(0.0, 1.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 0.0, 1.0),
        )
        edge = _shared_edge(x_range=(0.0, 1.0), y=1.0, z=0.0, n=6)

        expected_Z_a = 0.5 + 0.5 * math.cos(7 * math.pi * 1.0)   # 0.0
        expected_Z_b = 0.5 + 0.5 * math.cos(7 * math.pi * 0.0)   # 1.0
        expected_break = abs(expected_Z_a - expected_Z_b)          # 1.0

        r = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=6, n_stripes=7,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert r["ok"] is True

        # Check per-point values against analytic oracle
        pp = r["per_point"][3]  # interior sample
        assert abs(pp["Z_a"] - expected_Z_a) < 0.05, (
            f"Z_a oracle: expected {expected_Z_a:.4f}, got {pp['Z_a']:.4f}"
        )
        assert abs(pp["Z_b"] - expected_Z_b) < 0.05, (
            f"Z_b oracle: expected {expected_Z_b:.4f}, got {pp['Z_b']:.4f}"
        )
        # stripe_G0_max should be close to expected_break
        assert r["stripe_G0_max"] > 0.5 * expected_break, (
            f"Stripe break should be ≈ {expected_break:.2f}; got {r['stripe_G0_max']:.4f}"
        )

    def test_oracle_b_stripe_break_detected_for_moderate_tilt(self):
        """Moderate-tilt dihedral creases must produce a detectable stripe break.

        Note: the striping is periodic, so certain special tilt angles can
        accidentally map both normals to the same stripe value (e.g. at 60°
        with n_stripes=8: nL_a=1 → Z=1.0, nL_b=cos60°=0.5 → cos(8π×0.5)=cos(4π)=1.0
        → also Z=1.0).  We therefore test at 30° and 45° which are non-degenerate,
        and verify that each produces G0_max > 0.
        """
        for tilt_deg in (30.0, 45.0):
            surf_a = _flat_plane(
                origin=(0.0, 0.0, 0.0),
                x_axis=(1.0, 0.0, 0.0),
                y_axis=(0.0, 1.0, 0.0),
            )
            tilt = math.radians(tilt_deg)
            ya_t = np.array([0.0, math.cos(tilt), math.sin(tilt)])
            surf_b = _flat_plane(
                origin=(0.0, 1.0, 0.0),
                x_axis=np.array([1.0, 0.0, 0.0]),
                y_axis=ya_t,
            )
            edge = _shared_edge(n=6)
            r = zebra_stripe_continuity_analyser(
                surf_a, surf_b, edge, num_samples=6, n_stripes=8,
                view_dir=[0.0, 0.0, 1.0],
            )
            assert r["ok"] is True
            # Analytic oracle: nL_a=1.0, nL_b=cos(tilt)
            nL_a = 1.0
            nL_b = math.cos(tilt)
            Z_a = 0.5 + 0.5 * math.cos(8 * math.pi * nL_a)
            Z_b = 0.5 + 0.5 * math.cos(8 * math.pi * nL_b)
            expected_break = abs(Z_a - Z_b)
            if expected_break > 0.01:
                # Only assert when the analytic oracle predicts a visible break
                assert r["stripe_G0_max"] > 0.01, (
                    f"Tilt={tilt_deg}°: analytic break={expected_break:.4f}, "
                    f"got stripe_G0_max={r['stripe_G0_max']:.4f}"
                )


# ---------------------------------------------------------------------------
# Return-value contract tests
# ---------------------------------------------------------------------------


class TestZebraReturnContract:
    """Required return keys and types."""

    REQUIRED_KEYS = {
        "ok", "reason",
        "stripe_G0_max", "stripe_G1_tangent_max", "stripe_G1_ok",
        "stripe_G2_curvature_max", "stripe_G2_ok",
        "continuity_grade", "num_samples", "n_stripes", "per_point",
    }
    REQUIRED_PP_KEYS = {
        "Z_a", "Z_b", "dZ_ds_a", "dZ_ds_b",
        "d2Z_ds2_a", "d2Z_ds2_b",
        "stripe_G0", "stripe_G1_tangent", "stripe_G2_curvature",
    }

    def test_return_keys_present(self):
        plane = _flat_plane()
        edge = _shared_edge(x_range=(0.0, 1.0), y=0.5, n=4)
        r = zebra_stripe_continuity_analyser(plane, plane, edge, num_samples=4)
        assert self.REQUIRED_KEYS <= set(r.keys()), (
            f"Missing keys: {self.REQUIRED_KEYS - set(r.keys())}"
        )

    def test_per_point_keys_present(self):
        plane = _flat_plane()
        edge = _shared_edge(x_range=(0.0, 1.0), y=0.5, n=4)
        r = zebra_stripe_continuity_analyser(plane, plane, edge, num_samples=5)
        assert r["ok"] is True
        assert len(r["per_point"]) == 5
        for pp in r["per_point"]:
            assert self.REQUIRED_PP_KEYS <= set(pp.keys())

    def test_bad_input_ok_false(self):
        plane = _flat_plane()
        edge = _shared_edge(n=2)
        assert zebra_stripe_continuity_analyser("bad", plane, edge)["ok"] is False
        assert zebra_stripe_continuity_analyser(plane, None, edge)["ok"] is False
        assert zebra_stripe_continuity_analyser(plane, plane, [[0.0, 0.0, 0.0]])["ok"] is False

    def test_n_stripes_recorded(self):
        plane = _flat_plane()
        edge = _shared_edge(n=4)
        r = zebra_stripe_continuity_analyser(plane, plane, edge, n_stripes=12)
        assert r["n_stripes"] == 12

    def test_num_samples_recorded(self):
        plane = _flat_plane()
        edge = _shared_edge(n=4)
        r = zebra_stripe_continuity_analyser(plane, plane, edge, num_samples=7)
        assert r["num_samples"] == 7
        assert len(r["per_point"]) == 7


# ---------------------------------------------------------------------------
# Determinism check
# ---------------------------------------------------------------------------


class TestZebraDeterminism:
    def test_five_calls_identical(self):
        surf_a = _flat_plane()
        tilt = math.radians(20.0)
        ya = np.array([0.0, math.cos(tilt), math.sin(tilt)])
        surf_b = _flat_plane(origin=(0.0, 1.0, 0.0), y_axis=ya)
        edge = _shared_edge(n=6)
        vals = [
            zebra_stripe_continuity_analyser(surf_a, surf_b, edge, num_samples=6)["stripe_G1_tangent_max"]
            for _ in range(5)
        ]
        assert all(abs(v - vals[0]) < 1e-12 for v in vals), (
            f"Non-deterministic results: {vals}"
        )
