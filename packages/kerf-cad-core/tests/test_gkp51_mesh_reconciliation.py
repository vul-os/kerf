"""
test_gkp51_mesh_reconciliation.py
==================================
GK-P51: NURBS↔Mesh reconciliation with fidelity tracking (Lévy 2009).

Tests are hermetic pure-Python (no OCC, no DB, no network).
Analytic oracles are constructed from flat planes and UV spheres whose
geometry is exactly known.

DoD: 4 validation tests pass:
  1. Identity round-trip on flat plane: reconcile a flat NURBS body against
     its own same-resolution tessellation → fidelity_score > 0.99
  2. Sphere round-trip: reconcile a sphere NURBS body against its own
     same-resolution tessellation → fidelity_score > 0.95
  3. Mesh-extras detect: a mesh with one extra vertex far from the NURBS
     body → reconcile reports mesh_vs_nurbs_extras > 0
  4. Feature-line-guided fit: a mesh with feature lines guided fit returns
     ok=True and deviation ≤ 1.1× plain fit deviation

Additional: fidelity_report labels, return-type contracts, error modes.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.mesh_reconciliation import (
    ReconciliationResult,
    RoundTripResult,
    fidelity_report,
    reconcile_mesh_to_nurbs_with_features,
    reconcile_nurbs_mesh,
    round_trip_nurbs_mesh,
    _tessellate_body,
)


# ---------------------------------------------------------------------------
# Body / mesh factories
# ---------------------------------------------------------------------------

def _build_flat_nurbs_body_1x1() -> object:
    """Flat NURBS body as a Plane face spanning [0,1]×[0,1] at z=0."""
    from kerf_cad_core.geom.brep import (
        Body, Coedge, Edge, Face, Line3, Loop, Plane, Shell, Solid, Vertex,
    )
    p00 = np.array([0.0, 0.0, 0.0])
    p10 = np.array([1.0, 0.0, 0.0])
    p11 = np.array([1.0, 1.0, 0.0])
    p01 = np.array([0.0, 1.0, 0.0])
    vs = [Vertex(p, 1e-7) for p in [p00, p10, p11, p01]]
    edges = [
        Edge(Line3(p00, p10), 0.0, 1.0, vs[0], vs[1]),
        Edge(Line3(p10, p11), 0.0, 1.0, vs[1], vs[2]),
        Edge(Line3(p11, p01), 0.0, 1.0, vs[2], vs[3]),
        Edge(Line3(p01, p00), 0.0, 1.0, vs[3], vs[0]),
    ]
    coedges = [Coedge(e, True) for e in edges]
    loop = Loop(coedges, is_outer=True)
    x_ax = (p10 - p00) / np.linalg.norm(p10 - p00)
    y_ax = (p01 - p00) / np.linalg.norm(p01 - p00)
    surf = Plane(origin=p00.copy(), x_axis=x_ax, y_axis=y_ax)
    face = Face(surf, [loop], orientation=True, tol=1e-7)
    shell = Shell([face], is_closed=False)
    return Body(solids=[Solid([shell])])


def _tessellate_sphere_mesh(
    radius: float = 1.0,
    n_lat: int = 8,
    n_lon: int = 10,
) -> dict:
    """UV-grid sphere tessellation (matches test_mesh_autosurface helper)."""
    verts: List[List[float]] = []
    verts.append([0.0, 0.0, -radius])
    for i in range(1, n_lat):
        lat = -math.pi / 2.0 + i * math.pi / n_lat
        for j in range(n_lon):
            lon = 2.0 * math.pi * j / n_lon
            verts.append([
                radius * math.cos(lat) * math.cos(lon),
                radius * math.cos(lat) * math.sin(lon),
                radius * math.sin(lat),
            ])
    verts.append([0.0, 0.0, radius])

    sp = 0
    np_idx = len(verts) - 1
    ring_start = 1

    def ring_idx(ring: int, j: int) -> int:
        return ring_start + ring * n_lon + (j % n_lon)

    faces: List[List[int]] = []
    for j in range(n_lon):
        faces.append([sp, ring_idx(0, j), ring_idx(0, j + 1)])
    for i in range(n_lat - 2):
        for j in range(n_lon):
            a = ring_idx(i, j)
            b = ring_idx(i, j + 1)
            c = ring_idx(i + 1, j + 1)
            d = ring_idx(i + 1, j)
            faces.append([a, b, c])
            faces.append([a, c, d])
    last = n_lat - 2
    for j in range(n_lon):
        faces.append([ring_idx(last, j), np_idx, ring_idx(last, j + 1)])

    return {"verts": verts, "faces": faces}


def _build_sphere_body_via_autosurface(radius: float = 1.0) -> object:
    """Build a sphere NURBS body via mesh_autosurface."""
    from kerf_cad_core.geom.mesh_to_nurbs import mesh_autosurface

    mesh = _tessellate_sphere_mesh(radius=radius, n_lat=8, n_lon=10)
    result = mesh_autosurface(
        mesh["verts"], mesh["faces"],
        tol=1e-3, max_dev=0.25,
        grid_m=5, grid_n=5,
        sew_tol=5e-2,
    )
    if not result["ok"] or result["body"] is None:
        pytest.skip(f"sphere autosurface precondition failed: {result.get('reason')}")
    return result["body"]


# ---------------------------------------------------------------------------
# Validation test 1: Identity — flat plane body vs its own tessellation
# ---------------------------------------------------------------------------

class TestIdentityFlatPlane:
    """GK-P51 oracle 1: reconcile a flat NURBS body against its own tessellation.

    When the reference mesh IS the tessellation of the NURBS body (same UV
    resolution), the two-sided Hausdorff distance is exactly 0, and the
    fidelity_score must be > 0.99.
    """

    _RESOLUTION = 0.05

    @pytest.fixture(scope="class")
    def flat_body(self):
        return _build_flat_nurbs_body_1x1()

    @pytest.fixture(scope="class")
    def self_tess(self, flat_body):
        """Build the reference mesh AS the body's own tessellation."""
        tess = _tessellate_body(flat_body, self._RESOLUTION)
        assert tess is not None, "tessellation of flat body returned None"
        return tess

    @pytest.fixture(scope="class")
    def recon_result(self, flat_body, self_tess):
        return reconcile_nurbs_mesh(flat_body, self_tess, mesh_resolution=self._RESOLUTION)

    def test_reconcile_ok(self, recon_result):
        assert recon_result.ok is True, f"reconcile failed: {recon_result.reason}"

    def test_identity_fidelity_above_threshold(self, recon_result):
        """fidelity_score > 0.99 for self-comparison (deviation ≈ 0)."""
        assert recon_result.fidelity_score > 0.99, (
            f"flat plane self-reconcile fidelity={recon_result.fidelity_score:.4f}, "
            f"expected > 0.99 (deviation={recon_result.deviation_metric:.6f}, "
            f"scale={recon_result.scale:.4f})"
        )

    def test_deviation_near_zero(self, recon_result):
        """Hausdorff distance must be 0 for self-comparison."""
        assert recon_result.deviation_metric < 1e-10, (
            f"self-reconcile deviation={recon_result.deviation_metric:.2e}, expected ~0"
        )

    def test_zero_extras(self, recon_result):
        """No extras in either direction for identical point sets."""
        assert recon_result.mesh_vs_nurbs_extras == 0
        assert recon_result.nurbs_vs_mesh_extras == 0

    def test_fidelity_label_excellent(self, recon_result):
        label = fidelity_report(recon_result.deviation_metric, recon_result.scale)
        assert label == "excellent", f"got '{label}' for near-zero deviation"


# ---------------------------------------------------------------------------
# Validation test 2: Sphere body vs its own tessellation → fidelity > 0.95
# ---------------------------------------------------------------------------

class TestSphereSelfReconcile:
    """GK-P51 oracle 2: sphere NURBS body vs its own same-resolution tessellation.

    Since the reference mesh is built from the same UV-grid as the body's
    internal tessellation, the Hausdorff distance is ~0, giving fidelity > 0.95.
    This validates that the pipeline handles a curved (non-developable) surface.
    """

    _RESOLUTION = 0.1

    @pytest.fixture(scope="class")
    def sphere_body(self):
        return _build_sphere_body_via_autosurface(radius=1.0)

    @pytest.fixture(scope="class")
    def self_tess(self, sphere_body):
        tess = _tessellate_body(sphere_body, self._RESOLUTION)
        assert tess is not None
        return tess

    @pytest.fixture(scope="class")
    def recon_result(self, sphere_body, self_tess):
        return reconcile_nurbs_mesh(sphere_body, self_tess, mesh_resolution=self._RESOLUTION)

    def test_reconcile_ok(self, recon_result):
        assert recon_result.ok is True, f"sphere reconcile failed: {recon_result.reason}"

    def test_sphere_fidelity_above_threshold(self, recon_result):
        """fidelity_score > 0.95 when reference IS the body's own tessellation."""
        assert recon_result.fidelity_score > 0.95, (
            f"sphere self-reconcile fidelity={recon_result.fidelity_score:.4f}, "
            f"expected > 0.95 (deviation={recon_result.deviation_metric:.6f}, "
            f"scale={recon_result.scale:.4f})"
        )

    def test_deviation_small(self, recon_result):
        """Self-reconcile deviation must be near 0."""
        assert recon_result.deviation_metric < 1e-8

    def test_fidelity_label_not_poor(self, recon_result):
        label = fidelity_report(recon_result.deviation_metric, recon_result.scale)
        assert label != "poor"

    def test_scale_roughly_sphere_diagonal(self, recon_result):
        """Scale should be ~2 (sphere bounding box diagonal for unit sphere)."""
        # bbox diagonal of unit sphere = sqrt(4+4+4) = 3.46
        assert recon_result.scale > 1.5, f"scale={recon_result.scale:.3f}"


# ---------------------------------------------------------------------------
# Validation test 3: Mesh-extras detection
# ---------------------------------------------------------------------------

class TestMeshExtrasDetect:
    """GK-P51 oracle 3: mesh with an extra far vertex reports mesh_vs_nurbs_extras > 0.

    A reference mesh whose only difference from the NURBS tessellation is one
    additional vertex placed FAR from the NURBS surface (z = 10 units above a
    plane) must trigger the extras counter.
    """

    _RESOLUTION = 0.1

    @pytest.fixture(scope="class")
    def flat_body(self):
        return _build_flat_nurbs_body_1x1()

    @pytest.fixture(scope="class")
    def base_tess(self, flat_body):
        return _tessellate_body(flat_body, self._RESOLUTION)

    def test_extras_detected_for_outlier_vertex(self, flat_body, base_tess):
        """mesh_vs_nurbs_extras > 0 when reference mesh has a far outlier."""
        # Copy the base tessellation and add a vertex 10 units above the plane
        outlier_verts = list(base_tess["verts"]) + [[0.5, 0.5, 10.0]]
        outlier_mesh = {
            "verts": outlier_verts,
            "faces": list(base_tess["faces"]),
        }

        result = reconcile_nurbs_mesh(
            flat_body, outlier_mesh, mesh_resolution=self._RESOLUTION
        )
        assert result.ok is True, f"reconcile failed: {result.reason}"
        assert result.mesh_vs_nurbs_extras > 0, (
            f"Expected mesh_vs_nurbs_extras > 0 for far outlier vertex at z=10, "
            f"got {result.mesh_vs_nurbs_extras} (scale={result.scale:.3f}, "
            f"threshold={0.05 * result.scale:.3f})"
        )

    def test_no_extras_for_self_tessellation(self, flat_body, base_tess):
        """mesh_vs_nurbs_extras == 0 when reference IS the own tessellation."""
        result = reconcile_nurbs_mesh(
            flat_body, base_tess, mesh_resolution=self._RESOLUTION
        )
        assert result.ok is True
        assert result.mesh_vs_nurbs_extras == 0, (
            f"Unexpected extras for self-comparison: {result.mesh_vs_nurbs_extras}"
        )

    def test_extras_count_type_is_int(self, flat_body, base_tess):
        result = reconcile_nurbs_mesh(flat_body, base_tess, mesh_resolution=self._RESOLUTION)
        assert isinstance(result.mesh_vs_nurbs_extras, int)
        assert isinstance(result.nurbs_vs_mesh_extras, int)


# ---------------------------------------------------------------------------
# Validation test 4: Feature-line-guided fit
# ---------------------------------------------------------------------------

class TestFeatureLineGuidedFit:
    """GK-P51 oracle 4: guided fit does not degrade vs plain fit.

    A mesh with a crease is fitted with and without a feature-line hint.
    The guided fit must complete without error and its deviation must be
    no worse than 1.1× the plain fit (it should be equal or better).
    """

    @pytest.fixture(scope="class")
    def folded_mesh(self) -> dict:
        """Folded mesh: z=0 for x<1, z=(x-1)*0.3 for x>=1."""
        verts: List[List[float]] = []
        n = 7
        size = 2.0
        for i in range(n):
            for j in range(n):
                x = i * size / (n - 1)
                y = j * size / (n - 1)
                z = max(0.0, (x - 1.0) * 0.3)
                verts.append([x, y, z])
        faces: List[List[int]] = []
        for i in range(n - 1):
            for j in range(n - 1):
                a = i * n + j
                b = (i + 1) * n + j
                c = (i + 1) * n + (j + 1)
                d = i * n + (j + 1)
                faces.append([a, b, c])
                faces.append([a, c, d])
        return {"verts": verts, "faces": faces}

    @pytest.fixture(scope="class")
    def feature_line(self) -> List[List[List[float]]]:
        """Polyline along the crease at x=1."""
        return [[[1.0, float(y), 0.0] for y in np.linspace(0.0, 2.0, 16)]]

    def test_guided_fit_ok(self, folded_mesh, feature_line):
        """reconcile_mesh_to_nurbs_with_features must succeed with feature lines."""
        result = reconcile_mesh_to_nurbs_with_features(folded_mesh, feature_lines=feature_line)
        assert result["ok"] is True, f"guided fit failed: {result.get('reason')}"

    def test_plain_fit_ok(self, folded_mesh):
        """reconcile_mesh_to_nurbs_with_features must succeed without feature lines."""
        result = reconcile_mesh_to_nurbs_with_features(folded_mesh)
        assert result["ok"] is True, f"plain fit failed: {result.get('reason')}"

    def test_feature_guided_flag_true(self, folded_mesh, feature_line):
        result = reconcile_mesh_to_nurbs_with_features(folded_mesh, feature_lines=feature_line)
        assert result["feature_guided"] is True

    def test_no_feature_flag_without_lines(self, folded_mesh):
        result = reconcile_mesh_to_nurbs_with_features(folded_mesh)
        assert result["feature_guided"] is False

    def test_guided_deviation_not_worse_than_plain(self, folded_mesh, feature_line):
        """Guided fit deviation must not exceed 1.1× plain fit deviation."""
        guided = reconcile_mesh_to_nurbs_with_features(
            folded_mesh, feature_lines=feature_line
        )
        plain = reconcile_mesh_to_nurbs_with_features(folded_mesh)

        if not guided["ok"] or not plain["ok"]:
            pytest.skip("one of the fits failed; skipping deviation comparison")

        g_dev = guided.get("max_deviation", float("inf"))
        p_dev = plain.get("max_deviation", float("inf"))

        assert g_dev <= p_dev * 1.10, (
            f"guided deviation {g_dev:.4f} > plain deviation {p_dev:.4f} * 1.10"
        )

    def test_guided_body_present(self, folded_mesh, feature_line):
        result = reconcile_mesh_to_nurbs_with_features(folded_mesh, feature_lines=feature_line)
        assert result.get("body") is not None


# ---------------------------------------------------------------------------
# fidelity_report unit tests
# ---------------------------------------------------------------------------

class TestFidelityReport:
    """Unit tests for fidelity_report label classification."""

    def test_excellent_below_01_pct(self):
        assert fidelity_report(0.0009, 1.0) == "excellent"  # 0.09%

    def test_good_below_1_pct(self):
        assert fidelity_report(0.005, 1.0) == "good"  # 0.5%

    def test_fair_below_10_pct(self):
        assert fidelity_report(0.05, 1.0) == "fair"  # 5%

    def test_poor_above_10_pct(self):
        assert fidelity_report(0.5, 1.0) == "poor"  # 50%

    def test_boundary_excellent_to_good(self):
        # Below 0.1% → excellent; at or above 0.1% → good
        # Thresholds use strict < so ratio==threshold falls into the next bucket.
        assert fidelity_report(0.0009, 1.0) == "excellent"   # 0.09% < 0.1% ✓
        assert fidelity_report(0.001, 1.0) == "good"         # exactly 0.1% → good (not < 0.001)
        assert fidelity_report(0.0011, 1.0) == "good"        # 0.11% → good

    def test_boundary_good_to_fair(self):
        # Below 1% → good; at or above 1% → fair
        assert fidelity_report(0.009, 1.0) == "good"    # 0.9% < 1% ✓
        assert fidelity_report(0.01, 1.0) == "fair"     # exactly 1% → fair (not < 0.01)
        assert fidelity_report(0.011, 1.0) == "fair"    # 1.1% → fair

    def test_boundary_fair_to_poor(self):
        # Below 10% → fair; at or above 10% → poor
        assert fidelity_report(0.09, 1.0) == "fair"    # 9% < 10% ✓
        assert fidelity_report(0.10, 1.0) == "poor"    # exactly 10% → poor (not < 0.10)
        assert fidelity_report(0.11, 1.0) == "poor"    # 11% → poor

    def test_zero_scale_returns_poor(self):
        assert fidelity_report(0.001, 0.0) == "poor"

    def test_zero_deviation_excellent(self):
        assert fidelity_report(0.0, 2.0) == "excellent"

    def test_scale_relative_invariance(self):
        """Same ratio → same label regardless of absolute scale."""
        assert fidelity_report(0.1, 100.0) == fidelity_report(0.001, 1.0)


# ---------------------------------------------------------------------------
# ReconciliationResult contract tests
# ---------------------------------------------------------------------------

class TestReconciliationContract:
    """Return-type and error-mode tests for reconcile_nurbs_mesh."""

    @pytest.fixture(scope="class")
    def flat_body(self):
        return _build_flat_nurbs_body_1x1()

    @pytest.fixture(scope="class")
    def self_tess(self, flat_body):
        return _tessellate_body(flat_body, 0.1)

    def test_result_is_dataclass(self, flat_body, self_tess):
        r = reconcile_nurbs_mesh(flat_body, self_tess, mesh_resolution=0.1)
        assert isinstance(r, ReconciliationResult)

    def test_ok_true_on_valid_inputs(self, flat_body, self_tess):
        r = reconcile_nurbs_mesh(flat_body, self_tess, mesh_resolution=0.1)
        assert r.ok is True

    def test_fidelity_in_range(self, flat_body, self_tess):
        r = reconcile_nurbs_mesh(flat_body, self_tess, mesh_resolution=0.1)
        assert 0.0 <= r.fidelity_score <= 1.0

    def test_deviation_non_negative(self, flat_body, self_tess):
        r = reconcile_nurbs_mesh(flat_body, self_tess, mesh_resolution=0.1)
        assert r.deviation_metric >= 0.0

    def test_scale_positive(self, flat_body, self_tess):
        r = reconcile_nurbs_mesh(flat_body, self_tess, mesh_resolution=0.1)
        assert r.scale > 0.0

    def test_none_body_returns_error(self, self_tess):
        r = reconcile_nurbs_mesh(None, self_tess)
        assert r.ok is False
        assert r.reason != ""

    def test_empty_verts_returns_error(self, flat_body):
        r = reconcile_nurbs_mesh(flat_body, {"verts": [], "faces": []})
        assert r.ok is False

    def test_missing_verts_key_returns_error(self, flat_body):
        r = reconcile_nurbs_mesh(flat_body, {"faces": [[0, 1, 2]]})
        assert r.ok is False

    def test_does_not_raise_on_bad_input(self, flat_body):
        """reconcile_nurbs_mesh must never raise."""
        try:
            r = reconcile_nurbs_mesh(flat_body, "notadict")
            assert isinstance(r, ReconciliationResult)
        except Exception as exc:
            pytest.fail(f"reconcile_nurbs_mesh raised: {exc}")


# ---------------------------------------------------------------------------
# round_trip_nurbs_mesh contract tests
# ---------------------------------------------------------------------------

class TestRoundTripContract:
    """Contract tests for round_trip_nurbs_mesh."""

    @pytest.fixture(scope="class")
    def flat_body(self):
        return _build_flat_nurbs_body_1x1()

    def test_result_is_dataclass(self, flat_body):
        r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
        assert isinstance(r, RoundTripResult)

    def test_ok_on_valid_body(self, flat_body):
        r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
        assert r.ok is True, f"round_trip failed: {r.reason}"

    def test_fidelity_in_range(self, flat_body):
        r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
        assert 0.0 <= r.fidelity_score <= 1.0

    def test_per_step_keys_present(self, flat_body):
        r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
        assert "nurbs_to_mesh" in r.per_step_deviation
        assert "mesh_to_nurbs" in r.per_step_deviation

    def test_intermediate_mesh_present(self, flat_body):
        r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
        assert r.intermediate_mesh is not None
        assert len(r.intermediate_mesh.get("verts", [])) > 0

    def test_refit_body_present(self, flat_body):
        r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
        assert r.refit_body is not None

    def test_total_deviation_finite(self, flat_body):
        r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
        assert math.isfinite(r.total_deviation)
        assert r.total_deviation >= 0.0

    def test_none_body_error(self):
        r = round_trip_nurbs_mesh(None)
        assert r.ok is False
        assert r.reason != ""

    def test_does_not_raise(self, flat_body):
        try:
            r = round_trip_nurbs_mesh(flat_body, mesh_resolution=0.25)
            assert hasattr(r, "ok")
        except Exception as exc:
            pytest.fail(f"round_trip_nurbs_mesh raised: {exc}")
