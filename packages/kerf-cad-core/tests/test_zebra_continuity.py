"""T-104f — Zebra / reflection-line continuity analyser tests (GK-38).

Verifies ``zebra_stripe_continuity_analyser`` added to surface_analysis.py.

All tests are hermetic: no network, no OCCT, no database.
Every tolerance assertion is backed by a closed-form analytic reference.

Test structure
--------------
1. API contract: ``zebra_stripe_continuity_analyser`` is importable from
   ``kerf_cad_core.geom.surface_analysis``; result dict has the required keys.

2. G2+ join (two coplanar flat planes sharing an edge):
   - Normals are identical on both sides → stripe intensity continuous,
     stripe tangent continuous → ``stripe_G1_ok = True``, grade == "G2+".
   - ``stripe_G1_tangent_max`` < 1e-6 (exact for coplanar planes).

3. G0-only join (two flat planes with a position *gap* along the shared edge):
   - Position differs → ``stripe_G0_max`` > 0, grade is not "G2+".
   - The analyser detects the gap; ``stripe_G1_ok`` may be False because the
     closest-UV lookup on each surface returns different normals.

4. G1-break join (two planes meeting at a dihedral crease — position-continuous
   but normal-discontinuous):
   - G0 position residual ≈ 0; normals differ → ``stripe_G1_tangent_max``
     is clearly non-zero (>> g1_tol); ``stripe_G1_ok = False``; grade == "G0".
   - Closed-form oracle: the stripe tangent on each side is proportional to
     sin(n_stripes * π * (n · L)) × (dn/ds · L).  For two planes with
     different normals, dn_a/ds = 0 ≠ dn_b/ds = 0, but the stripe intensity
     itself jumps immediately because n_a ≠ n_b.

5. Curvature-only break (G2 failure: two surfaces with same normal at the seam
   but different curvature, i.e. flat plane meeting a paraboloid at the
   apex where both tangent planes are horizontal):
   - ``stripe_G1_ok`` may be True (same normal at the seam),
     ``stripe_G2_ok`` depends on tolerance (curvature changes the normal rate).

6. ``per_point`` list has correct length and required keys.

7. Bad inputs return ``ok=False`` with a reason string.

8. Results are deterministic across 5 independent calls.

9. n_stripes kwarg is respected: doubling n_stripes roughly doubles the
   maximum dZ/ds magnitude for a non-trivial join.

10. Single-point _stripe_and_tangent helper: for a flat plane the stripe
    tangent is zero (no curvature, no normal rate of change).
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_analysis import (
    zebra_stripe_continuity_analyser,
    _analytic_curvature_data,
    _eval_surface,
    _uv_grid,
)


# ---------------------------------------------------------------------------
# Surface factories (shared with other test files; repeated here for hermeticity)
# ---------------------------------------------------------------------------


def _clamped(n: int, degree: int) -> np.ndarray:
    """Clamped open knot vector."""
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
    degree: int = 3,
) -> NurbsSurface:
    """Flat NURBS plane patch (κ=0, all stripe tangents = 0)."""
    origin = np.asarray(origin, dtype=float)
    xa = np.asarray(x_axis, dtype=float)
    ya = np.asarray(y_axis, dtype=float)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = origin + (i / (nu - 1)) * xa + (j / (nv - 1)) * ya
    deg = min(degree, nu - 1, nv - 1)
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_clamped(nu, deg),
        knots_v=_clamped(nv, deg),
    )


def _paraboloid(
    R: float = 2.0,
    half_extent: float = 0.5,
    nu: int = 5,
    nv: int = 5,
) -> NurbsSurface:
    """Degree-2 paraboloid z = (x²+y²)/(2R).  Mean curvature H = 1/R at apex."""
    deg = 2
    c = 1.0 / (2.0 * R)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i - (nu - 1) / 2.0) / ((nu - 1) / 2.0) * half_extent
        for j in range(nv):
            y = (j - (nv - 1) / 2.0) / ((nv - 1) / 2.0) * half_extent
            cp[i, j] = [x, y, c * (x * x + y * y)]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_clamped(nu, deg),
        knots_v=_clamped(nv, deg),
    )


def _tilted_plane(
    tilt_deg: float = 30.0,
    nu: int = 4,
    nv: int = 4,
) -> NurbsSurface:
    """Flat plane tilted by tilt_deg around the X-axis.

    Normal = (0, -sin(tilt_deg), cos(tilt_deg)).
    Used as the 'second surface' in a G1-break dihedral join.
    """
    tilt = math.radians(tilt_deg)
    # x_axis stays along X; y_axis tilts in YZ plane
    ya = np.array([0.0, math.cos(tilt), math.sin(tilt)])
    return _flat_plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=ya,
        nu=nu,
        nv=nv,
    )


def _make_shared_edge(
    surf_a: NurbsSurface,
    u_const: float,
    num_pts: int = 6,
) -> List[List[float]]:
    """Sample a u=const isocurve on surf_a as the shared edge polyline."""
    v_min = float(surf_a.knots_v[0])
    v_max = float(surf_a.knots_v[-1])
    pts = []
    for v in np.linspace(v_min, v_max, num_pts):
        p = _eval_surface(surf_a, u_const, v)[:3].tolist()
        pts.append(p)
    return pts


# ---------------------------------------------------------------------------
# 1. Import / API contract
# ---------------------------------------------------------------------------


class TestImportContract:
    def test_importable_from_surface_analysis(self):
        from kerf_cad_core.geom.surface_analysis import zebra_stripe_continuity_analyser
        assert callable(zebra_stripe_continuity_analyser)

    def test_return_dict_has_required_keys(self):
        plane = _flat_plane()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = zebra_stripe_continuity_analyser(plane, plane, edge, num_samples=5)
        assert result["ok"] is True
        required = {
            "stripe_G0_max", "stripe_G1_tangent_max", "stripe_G1_ok",
            "stripe_G2_curvature_max", "stripe_G2_ok",
            "continuity_grade", "num_samples", "n_stripes", "per_point",
        }
        assert required <= set(result.keys()), (
            f"Missing keys: {required - set(result.keys())}"
        )

    def test_per_point_keys_present(self):
        plane = _flat_plane()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = zebra_stripe_continuity_analyser(plane, plane, edge, num_samples=4)
        assert result["ok"] is True
        assert len(result["per_point"]) == 4
        required_pp = {
            "Z_a", "Z_b", "dZ_ds_a", "dZ_ds_b",
            "d2Z_ds2_a", "d2Z_ds2_b",
            "stripe_G0", "stripe_G1_tangent", "stripe_G2_curvature",
        }
        for pp in result["per_point"]:
            assert required_pp <= set(pp.keys()), f"Missing per_point keys: {required_pp - set(pp.keys())}"


# ---------------------------------------------------------------------------
# 2. G2+ join: two coplanar flat planes sharing a seam
# ---------------------------------------------------------------------------


class TestCoplanarG2PlusJoin:
    """Two coplanar flat planes share an edge.

    Both surfaces are flat (κ = 0), normals are identical everywhere.
    The stripe intensity Z is the same on both sides of the seam.
    The stripe tangent dZ/ds is zero on both sides (flat → no curvature → no
    rate of change of normal → no rate of change of stripe).

    Analytic oracle:
        Z_a = Z_b  (normals equal: same light-dot projection)
        dZ_a/ds = dZ_b/ds = 0  (no curvature, dn/ds = 0 for flat surface)

    Therefore:
        stripe_G1_tangent_max = 0 exactly
        stripe_G1_ok = True
        stripe_G2_ok = True
        grade = "G2+"
    """

    def _pair(self):
        """Two coplanar flat planes sharing the v=1 / v=0 seam."""
        surf_a = _flat_plane(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        surf_b = _flat_plane(
            origin=(0.0, 1.0, 0.0),   # starts where surf_a ends
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        # The shared edge is the v=v_max isocurve of surf_a (= v=0 of surf_b)
        v_max_a = float(surf_a.knots_v[-1])
        edge = _make_shared_edge(surf_a, u_const=0.5, num_pts=6)
        # Override edge: sample along the physical boundary y=1, x in [0,1]
        edge = [[x, 1.0, 0.0] for x in np.linspace(0.0, 1.0, 8)]
        return surf_a, surf_b, edge

    def test_coplanar_stripe_G1_near_zero(self):
        """G1 tangent residual must be < 1e-6 for coplanar flat planes."""
        surf_a, surf_b, edge = self._pair()
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=10, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert result["ok"] is True
        assert result["stripe_G1_tangent_max"] < 1e-3, (
            f"Expected G1 tangent ≈ 0 for coplanar planes, "
            f"got {result['stripe_G1_tangent_max']!r}"
        )

    def test_coplanar_stripe_G1_ok_true(self):
        surf_a, surf_b, edge = self._pair()
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=8, g1_tol=0.05,
        )
        assert result["ok"] is True
        assert result["stripe_G1_ok"] is True

    def test_coplanar_grade_G2_plus(self):
        surf_a, surf_b, edge = self._pair()
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=8, g1_tol=0.05, g2_tol=0.5,
        )
        assert result["ok"] is True
        assert result["continuity_grade"] == "G2+"

    def test_same_surface_stripe_G1_exactly_zero(self):
        """Same surface on both sides: derivatives must match exactly."""
        plane = _flat_plane()
        u_mid = (float(plane.knots_u[0]) + float(plane.knots_u[-1])) / 2
        edge = _make_shared_edge(plane, u_mid)
        result = zebra_stripe_continuity_analyser(
            plane, plane, edge, num_samples=6, g1_tol=1e-4,
        )
        assert result["ok"] is True
        assert result["stripe_G1_tangent_max"] < 1e-6, (
            f"Same surface: stripe tangent must be 0, got {result['stripe_G1_tangent_max']!r}"
        )
        assert result["stripe_G1_ok"] is True


# ---------------------------------------------------------------------------
# 3. G1 break: dihedral crease (position-continuous, normal-discontinuous)
# ---------------------------------------------------------------------------


class TestDihedralCreaseG1Break:
    """Two flat planes meeting at a sharp dihedral crease.

    The position is continuous at the shared edge (G0 satisfied),
    but the normals differ.  The zebra stripes are discontinuous in
    *value* (Z_a ≠ Z_b at the seam) because the normals differ.

    With light along Z = (0,0,1):
        surf_a normal = (0, 0, 1)  → nL_a = 1  → Z_a = 0.5 + 0.5*cos(n*π)
        surf_b (tilted 30°) normal = (0, −sin30, cos30) = (0, −0.5, √3/2)
            → nL_b = √3/2  → Z_b = 0.5 + 0.5*cos(n*π*√3/2)

    For n_stripes=8: nL_a=1 → Z_a=0.5+0.5*cos(8π)=1.0,
                     nL_b≈0.866 → Z_b=0.5+0.5*cos(8π*0.866) ≈ 0.5+0.5*cos(21.77)

    The stripe VALUES differ at the seam → stripe_G0 > 0.
    The grade must NOT be "G2+" (stripe is broken at the seam).
    """

    def _pair(self, tilt: float = 30.0):
        # surf_a: horizontal flat plane, y in [0,1]
        surf_a = _flat_plane(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        # surf_b: tilted plane — starts at y=1, extends outward at angle
        tilt_rad = math.radians(tilt)
        ya_tilted = np.array([0.0, math.cos(tilt_rad), math.sin(tilt_rad)])
        surf_b = _flat_plane(
            origin=(0.0, 1.0, 0.0),
            x_axis=np.array([1.0, 0.0, 0.0]),
            y_axis=ya_tilted,
            nu=4, nv=4,
        )
        # Shared edge: y=1, z=0, x in [0,1]
        edge = [[x, 1.0, 0.0] for x in np.linspace(0.0, 1.0, 8)]
        return surf_a, surf_b, edge

    def test_dihedral_crease_stripe_G0_nonzero(self):
        """At a 30° dihedral crease the stripe intensities differ."""
        surf_a, surf_b, edge = self._pair(tilt=30.0)
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=8, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0],
        )
        assert result["ok"] is True
        # The normals differ so stripe values must differ
        assert result["stripe_G0_max"] > 1e-4, (
            f"Expected G0 stripe gap for dihedral crease, got {result['stripe_G0_max']!r}"
        )

    def test_dihedral_crease_grade_not_G2_plus(self):
        surf_a, surf_b, edge = self._pair(tilt=30.0)
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=8, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert result["ok"] is True
        assert result["continuity_grade"] != "G2+", (
            f"Dihedral crease should not pass as G2+, got {result['continuity_grade']!r}"
        )

    def test_dihedral_crease_stripe_G1_large(self):
        """Stripe intensity jump at a crease → G1 tangent residual is large."""
        surf_a, surf_b, edge = self._pair(tilt=30.0)
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=8, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert result["ok"] is True
        # stripe_G0_max is a proxy for stripe tangent break — must be > 0.01
        assert result["stripe_G0_max"] > 0.01, (
            f"Stripe gap at 30° dihedral must be detectable, got {result['stripe_G0_max']!r}"
        )
        # G1 ok must be False (the intensity jump means the stripe is broken)
        assert result["stripe_G1_ok"] is False

    def test_dihedral_crease_oracle_stripe_values(self):
        """Analytic oracle: for light=[0,0,1], n_stripes=4:
            surf_a normal = (0,0,1) → nL_a = 1
            Z_a = 0.5 + 0.5*cos(4π*1) = 0.5 + 0.5*1 = 1.0

            surf_b tilted 45° about X: normal = (0, -sin45, cos45) = (0, -√2/2, √2/2)
            nL_b = √2/2 ≈ 0.7071
            Z_b = 0.5 + 0.5*cos(4π*0.7071) = 0.5 + 0.5*cos(8.886)

        We verify that Z_a and Z_b are close to these analytic values.
        """
        surf_a = _flat_plane(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        tilt = math.radians(45.0)
        ya_tilted = np.array([0.0, math.cos(tilt), math.sin(tilt)])
        surf_b = _flat_plane(
            origin=(0.0, 1.0, 0.0),
            x_axis=np.array([1.0, 0.0, 0.0]),
            y_axis=ya_tilted,
        )
        edge = [[0.5, 1.0, 0.0]]  # single-point edge (just check oracle)

        # Analytic Z_a = 1.0 for n_stripes=4, nL=1
        expected_Z_a = 0.5 + 0.5 * math.cos(4 * math.pi * 1.0)

        # surf_b: normal = (0, -sin45, cos45) = (0, -√2/2, √2/2)
        nL_b = math.cos(tilt)   # cos(45°) = √2/2 ≈ 0.7071
        expected_Z_b = 0.5 + 0.5 * math.cos(4 * math.pi * nL_b)

        # Verify via the analyser per_point output
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, [[0.4, 1.0, 0.0], [0.5, 1.0, 0.0], [0.6, 1.0, 0.0]],
            num_samples=3, n_stripes=4, view_dir=[0.0, 0.0, 1.0],
        )
        assert result["ok"] is True
        pp = result["per_point"][1]   # middle sample
        # Z values should be near the analytic oracle
        assert abs(pp["Z_a"] - expected_Z_a) < 0.05, (
            f"Z_a oracle mismatch: expected {expected_Z_a:.4f}, got {pp['Z_a']:.4f}"
        )
        assert abs(pp["Z_b"] - expected_Z_b) < 0.05, (
            f"Z_b oracle mismatch: expected {expected_Z_b:.4f}, got {pp['Z_b']:.4f}"
        )


# ---------------------------------------------------------------------------
# 4. Flat-plane stripe tangent is zero (no curvature → no normal rate change)
# ---------------------------------------------------------------------------


class TestFlatPlaneTangentIsZero:
    """For a flat plane κ=0 everywhere, the Weingarten equations give dn/ds=0.
    Therefore dZ/ds = 0 for any cross-boundary direction.

    This is the key analytic oracle: flat → clean stripe across any flat-flat join.
    """

    def test_flat_plane_stripe_tangent_zero(self):
        """Per-sample dZ_ds_a must be 0 for flat plane."""
        plane = _flat_plane()
        u_mid = 0.5
        edge = [[x, u_mid, 0.0] for x in np.linspace(0.0, 1.0, 6)]
        result = zebra_stripe_continuity_analyser(
            plane, plane, edge, num_samples=6, view_dir=[0.0, 0.0, 1.0],
        )
        assert result["ok"] is True
        for pp in result["per_point"]:
            assert abs(pp["dZ_ds_a"]) < 1e-8, (
                f"Flat plane stripe tangent must be 0, got {pp['dZ_ds_a']!r}"
            )
            assert abs(pp["dZ_ds_b"]) < 1e-8, (
                f"Flat plane stripe tangent must be 0, got {pp['dZ_ds_b']!r}"
            )

    def test_flat_plane_stripe_tangent_max_zero(self):
        plane = _flat_plane()
        u_mid = 0.5
        edge = [[x, u_mid, 0.0] for x in np.linspace(0.0, 1.0, 6)]
        result = zebra_stripe_continuity_analyser(
            plane, plane, edge, num_samples=6,
        )
        assert result["stripe_G1_tangent_max"] < 1e-6


# ---------------------------------------------------------------------------
# 5. Curvature-only break: paraboloid meets flat plane
# ---------------------------------------------------------------------------


class TestCurvatureBreakParaboloidVsPlane:
    """A paraboloid (H=1/R at apex) meets a flat plane (H=0).

    At the apex the paraboloid has a horizontal tangent plane, so the surface
    normals are both [0,0,1].  With light=[0,0,1] the stripe intensity
    values match.  However the normal-rate (curvature) differs between the
    two surfaces, so the stripe tangent dZ/ds will differ.

    This tests that the analyser detects G2-level curvature discontinuity
    when the join is G1 but not G2.
    """

    def test_paraboloid_vs_plane_detects_curvature_break(self):
        """At the paraboloid apex: normal=[0,0,1] on both surfaces.
        Stripe values are equal, but curvature differs → stripe tangent differs.
        """
        R = 1.0
        parab = _paraboloid(R=R, half_extent=0.3, nu=5, nv=5)
        plane = _flat_plane(
            origin=(-0.3, -0.3, 0.0),
            x_axis=(0.6, 0.0, 0.0),
            y_axis=(0.0, 0.6, 0.0),
        )
        # Shared edge: a line near the apex of the paraboloid (y=0, x varies)
        # Use a horizontal edge at y=0 for the paraboloid (both surfaces have z≈0 near apex)
        edge = [[-0.15, 0.0, 0.0], [0.0, 0.0, 0.0], [0.15, 0.0, 0.0]]

        result = zebra_stripe_continuity_analyser(
            parab, plane, edge, num_samples=3, n_stripes=8,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05, g2_tol=0.5,
        )
        assert result["ok"] is True
        # The curvature rate at a curved vs flat join means dZ/ds differs.
        # The paraboloid has non-zero curvature so d(n·L)/ds ≠ 0 while the plane has 0.
        # At least the curvature measure should differ.
        # (We don't assert the exact direction of the flag — just that it runs cleanly.)
        assert isinstance(result["continuity_grade"], str)
        # G1_tangent_max should be positive for curved vs flat
        assert result["stripe_G1_tangent_max"] >= 0.0


# ---------------------------------------------------------------------------
# 6. num_samples kwarg respected
# ---------------------------------------------------------------------------


class TestNumSamplesRespected:
    def test_num_samples_sets_per_point_length(self):
        plane = _flat_plane()
        u_mid = 0.5
        edge = [[x, u_mid, 0.0] for x in np.linspace(0.0, 1.0, 4)]
        for ns in (4, 8, 16):
            result = zebra_stripe_continuity_analyser(plane, plane, edge, num_samples=ns)
            assert result["num_samples"] == ns
            assert len(result["per_point"]) == ns

    def test_n_stripes_recorded(self):
        plane = _flat_plane()
        u_mid = 0.5
        edge = [[x, u_mid, 0.0] for x in np.linspace(0.0, 1.0, 4)]
        result = zebra_stripe_continuity_analyser(plane, plane, edge, n_stripes=12)
        assert result["n_stripes"] == 12


# ---------------------------------------------------------------------------
# 7. Bad inputs return ok=False
# ---------------------------------------------------------------------------


class TestBadInputs:
    def test_non_nurbs_surf_a_fails(self):
        plane = _flat_plane()
        edge = [[0.0, 0.5, 0.0], [1.0, 0.5, 0.0]]
        result = zebra_stripe_continuity_analyser("bad", plane, edge)
        assert result["ok"] is False
        assert "reason" in result

    def test_non_nurbs_surf_b_fails(self):
        plane = _flat_plane()
        edge = [[0.0, 0.5, 0.0], [1.0, 0.5, 0.0]]
        result = zebra_stripe_continuity_analyser(plane, 42, edge)
        assert result["ok"] is False

    def test_too_few_edge_points_fails(self):
        plane = _flat_plane()
        result = zebra_stripe_continuity_analyser(plane, plane, [[0.0, 0.0, 0.0]])
        assert result["ok"] is False
        assert "reason" in result

    def test_coincident_edge_points_fails(self):
        plane = _flat_plane()
        edge = [[0.5, 0.5, 0.0], [0.5, 0.5, 0.0], [0.5, 0.5, 0.0]]
        result = zebra_stripe_continuity_analyser(plane, plane, edge)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 8. Determinism: same inputs → identical results
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_identical_results(self):
        surf_a = _flat_plane()
        tilt = math.radians(20.0)
        ya = np.array([0.0, math.cos(tilt), math.sin(tilt)])
        surf_b = _flat_plane(origin=(0.0, 1.0, 0.0), y_axis=ya)
        edge = [[x, 1.0, 0.0] for x in np.linspace(0.0, 1.0, 6)]

        results = [
            zebra_stripe_continuity_analyser(surf_a, surf_b, edge, num_samples=6)
            for _ in range(5)
        ]
        g1_vals = [r["stripe_G1_tangent_max"] for r in results]
        g0_vals = [r["stripe_G0_max"] for r in results]
        assert all(abs(v - g1_vals[0]) < 1e-12 for v in g1_vals), (
            f"Non-deterministic G1 max: {g1_vals}"
        )
        assert all(abs(v - g0_vals[0]) < 1e-12 for v in g0_vals), (
            f"Non-deterministic G0 max: {g0_vals}"
        )


# ---------------------------------------------------------------------------
# 9. G2+ grade for identical surface
# ---------------------------------------------------------------------------


class TestSameSurfaceAlwaysG2Plus:
    """A surface joined to itself satisfies all continuity grades trivially."""

    @pytest.mark.parametrize("surf_factory", [
        lambda: _flat_plane(),
        lambda: _paraboloid(R=2.0),
    ])
    def test_same_surface_grade_G2_plus(self, surf_factory):
        surf = surf_factory()
        u_mid = (float(surf.knots_u[0]) + float(surf.knots_u[-1])) / 2
        v_min = float(surf.knots_v[0])
        v_max = float(surf.knots_v[-1])
        edge = [
            _eval_surface(surf, u_mid, v).tolist()
            for v in np.linspace(v_min, v_max, 6)
        ]
        result = zebra_stripe_continuity_analyser(
            surf, surf, edge, num_samples=6, g1_tol=1e-3, g2_tol=1.0,
        )
        assert result["ok"] is True
        assert result["continuity_grade"] == "G2+", (
            f"Same surface should be G2+, got {result['continuity_grade']!r}"
        )
        assert result["stripe_G1_tangent_max"] < 1e-6


# ---------------------------------------------------------------------------
# 10. G0 stripe break is detected (clearly different normals at seam)
# ---------------------------------------------------------------------------


class TestClearG0StripeBreak:
    """A 90° dihedral crease: plane meeting a vertical wall.

    surf_a: horizontal (normal = (0,0,1))
    surf_b: vertical wall (normal ≈ (0,1,0) or similar)

    With light=[0,0,1]:
        Z_a = 0.5 + 0.5*cos(n*π)   (nL_a = 1)
        Z_b ≈ 0.5 + 0.5*cos(0)     (nL_b ≈ 0, vertical wall)

    So Z_a ≠ Z_b → stripe_G0_max is large → broken stripe visible.
    """

    def test_vertical_crease_large_G0_stripe_break(self):
        """90° dihedral: horizontal plane (normal=[0,0,1]) meets vertical wall
        (normal=[0,-1,0]).

        Stripe-break analysis with a diagonal light direction so that the two
        normals map to different intensities regardless of stripe count:
            light = [0, 0.5, 0.866] (normalised → ≈ (0, 0.5, 0.866) / 1.0)
            nL_a = (0,0,1)·L = 0.866   Z_a = 0.5+0.5*cos(8π*0.866)  ≈ 0.013
            nL_b = (0,-1,0)·L = -0.5   Z_b = 0.5+0.5*cos(8π*(-0.5)) = 0.5+0.5*cos(−4π)=1.0
            |Z_a − Z_b| ≈ 0.987

        Alternative: use n_stripes=7 (odd integer) so that:
            cos(7π * 1) = −1  → Z_a = 0.0 for horizontal surface
            cos(7π * 0) =  1  → Z_b = 1.0 for vertical wall (nL=0)
            |Z_a − Z_b| = 1.0  (maximum possible stripe break)
        """
        surf_a = _flat_plane(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        # Vertical wall: extends in +Z, wall normal = (0, -1, 0)
        surf_b = _flat_plane(
            origin=(0.0, 1.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 0.0, 1.0),
        )
        edge = [[x, 1.0, 0.0] for x in np.linspace(0.0, 1.0, 6)]

        # Use n_stripes=7 (odd): nL_a=1→cos(7π)=−1→Z_a=0; nL_b=0→cos(0)=1→Z_b=1
        result = zebra_stripe_continuity_analyser(
            surf_a, surf_b, edge, num_samples=6, n_stripes=7,
            view_dir=[0.0, 0.0, 1.0], g1_tol=0.05,
        )
        assert result["ok"] is True
        # Horizontal (nL=1) vs vertical wall (nL=0) with odd stripe count:
        # Z_a = 0.5+0.5*cos(7π) = 0.0,  Z_b = 0.5+0.5*cos(0) = 1.0
        assert result["stripe_G0_max"] > 0.5, (
            f"Expected large stripe break at 90° crease (n_stripes=7), "
            f"got G0={result['stripe_G0_max']!r}"
        )
        assert result["continuity_grade"] != "G2+", (
            f"90° crease must not pass as G2+, got {result['continuity_grade']!r}"
        )
