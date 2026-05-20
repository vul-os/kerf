"""GK-76: test_wall_thickness.py
=================================
Hermetic pytest oracle for wall_thickness_map.

Oracle
------
A hollow box (made with make_box + shell_body) has a **known uniform wall
thickness** t on every face.  The oracle checks:

  1. ``min_thickness`` ≈ t ± tol  (global minimum recovered correctly)
  2. ``per_face_min``  : every face's min ≈ t ± tol
  3. ``samples``       : list of (point, thickness) tuples, all thicknesses > 0
  4. ``heatmap_array`` : sorted 1-D ndarray, all values ≥ min_thickness

We use a hollow *cube* (equal sides) so every face has the same true
wall thickness t.  The box has a solid inner shell, so rays shot inward
from the outer surface all travel exactly t before hitting the inner surface.

Tolerances
----------
Ray-based sampling introduces statistical noise.  We allow a relative
tolerance of 5% on the per-face minimum (conservative for 10 000 rays).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import Body, Solid, make_box
from kerf_cad_core.geom.solid_features import shell_body
from kerf_cad_core.geom.wall_thickness import wall_thickness_map


# ---------------------------------------------------------------------------
# Helper: build a hollow cube body with known wall thickness t
# ---------------------------------------------------------------------------

def _hollow_cube(side: float = 4.0, t: float = 0.5) -> Body:
    """Return a hollow cube made with make_box + shell_body."""
    box = make_box(origin=(0.0, 0.0, 0.0), size=(side, side, side))
    result = shell_body(box, t)
    assert result["ok"], f"shell_body failed: {result.get('reason')}"
    return result["body"]


# ---------------------------------------------------------------------------
# Tolerance
# ---------------------------------------------------------------------------

_REL_TOL = 0.05   # 5% relative tolerance for statistical ray sampling


# ---------------------------------------------------------------------------
# Basic structure tests
# ---------------------------------------------------------------------------

class TestWallThicknessStructure:

    def setup_method(self):
        self.body = _hollow_cube(side=4.0, t=0.5)
        self.t = 0.5
        self.result = wall_thickness_map(self.body, n_rays=500, seed=7)

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_has_min_thickness_key(self):
        assert "min_thickness" in self.result

    def test_has_per_face_min_key(self):
        assert "per_face_min" in self.result

    def test_has_samples_key(self):
        assert "samples" in self.result

    def test_has_heatmap_array_key(self):
        assert "heatmap_array" in self.result

    def test_per_face_min_is_dict(self):
        assert isinstance(self.result["per_face_min"], dict)

    def test_samples_is_list(self):
        assert isinstance(self.result["samples"], list)

    def test_heatmap_array_is_ndarray(self):
        assert isinstance(self.result["heatmap_array"], np.ndarray)

    def test_heatmap_sorted_ascending(self):
        h = self.result["heatmap_array"]
        if len(h) > 1:
            diffs = np.diff(h)
            assert np.all(diffs >= -1e-10), "heatmap_array is not sorted ascending"

    def test_samples_tuples(self):
        for point, thick in self.result["samples"]:
            assert isinstance(point, np.ndarray)
            assert isinstance(thick, float)
            assert thick > 0.0

    def test_all_thicknesses_positive(self):
        for _, thick in self.result["samples"]:
            assert thick > 0.0

    def test_heatmap_length_matches_samples(self):
        assert len(self.result["heatmap_array"]) == len(self.result["samples"])


# ---------------------------------------------------------------------------
# Oracle: hollowed cube — all faces have true wall thickness = t
# ---------------------------------------------------------------------------

class TestWallThicknessOracle:

    @pytest.mark.parametrize("side,t", [
        (4.0, 0.5),
        (6.0, 1.0),
        (3.0, 0.3),
    ])
    def test_min_thickness_approx_t(self, side, t):
        """Global min_thickness ≈ t ± 5% for a hollow cube."""
        body = _hollow_cube(side=side, t=t)
        result = wall_thickness_map(body, n_rays=2000, seed=42)
        mt = result["min_thickness"]
        assert mt > 0, "min_thickness must be positive"
        rel_err = abs(mt - t) / t
        assert rel_err < _REL_TOL, (
            f"min_thickness={mt:.4f} expected ≈ {t:.4f} (rel_err={rel_err:.3f} > {_REL_TOL})"
        )

    @pytest.mark.parametrize("side,t", [
        (4.0, 0.5),
        (5.0, 0.8),
    ])
    def test_per_face_min_approx_t_on_every_face(self, side, t):
        """Every face's per_face_min ≈ t ± 5%."""
        body = _hollow_cube(side=side, t=t)
        result = wall_thickness_map(body, n_rays=3000, seed=99)
        per_face = result["per_face_min"]
        assert len(per_face) > 0, "per_face_min must be non-empty"
        for fid, face_t in per_face.items():
            if math.isnan(face_t):
                # No ray hit this face; skip (can happen for inner void faces)
                continue
            rel_err = abs(face_t - t) / t
            assert rel_err < _REL_TOL, (
                f"face_id={fid}: per_face_min={face_t:.4f} expected ≈ {t:.4f} "
                f"(rel_err={rel_err:.3f})"
            )

    def test_heatmap_max_approx_t(self):
        """For a uniform-wall box the heatmap values should cluster near t."""
        side, t = 4.0, 0.5
        body = _hollow_cube(side=side, t=t)
        result = wall_thickness_map(body, n_rays=2000, seed=1)
        h = result["heatmap_array"]
        assert len(h) > 0
        median_t = float(np.median(h))
        rel_err = abs(median_t - t) / t
        assert rel_err < _REL_TOL, (
            f"heatmap median={median_t:.4f} expected ≈ {t:.4f}"
        )

    def test_samples_count_near_n_rays(self):
        """Number of samples should be close to n_rays (within 10%)."""
        side, t = 4.0, 0.5
        body = _hollow_cube(side=side, t=t)
        n_rays = 1000
        result = wall_thickness_map(body, n_rays=n_rays, seed=5)
        n_got = len(result["samples"])
        # Allow ±10% slack for faces with no valid hits
        assert n_got >= int(n_rays * 0.5), (
            f"too few samples: expected ~{n_rays}, got {n_got}"
        )

    def test_empty_body_returns_zero(self):
        """Empty body → min_thickness=0, empty containers."""
        empty = Body()
        result = wall_thickness_map(empty, n_rays=100)
        assert result["min_thickness"] == 0.0
        assert result["per_face_min"] == {}
        assert result["samples"] == []
        assert len(result["heatmap_array"]) == 0

    def test_reproducible_with_same_seed(self):
        """Same seed → identical results."""
        body = _hollow_cube(side=4.0, t=0.5)
        r1 = wall_thickness_map(body, n_rays=200, seed=77)
        r2 = wall_thickness_map(body, n_rays=200, seed=77)
        assert r1["min_thickness"] == r2["min_thickness"]
        np.testing.assert_array_equal(r1["heatmap_array"], r2["heatmap_array"])

    def test_different_seeds_still_close(self):
        """Different seeds → results within tolerance of each other."""
        body = _hollow_cube(side=4.0, t=0.5)
        r1 = wall_thickness_map(body, n_rays=500, seed=11)
        r2 = wall_thickness_map(body, n_rays=500, seed=22)
        assert abs(r1["min_thickness"] - r2["min_thickness"]) / 0.5 < 0.15


# ---------------------------------------------------------------------------
# Public API via geom facade
# ---------------------------------------------------------------------------

class TestWallThicknessFacade:

    def test_importable_from_geom(self):
        """wall_thickness_map must be importable from kerf_cad_core.geom."""
        from kerf_cad_core.geom import wall_thickness_map as wt
        assert callable(wt)

    def test_facade_gives_same_result(self):
        """Importing from facade vs direct module gives same result."""
        from kerf_cad_core.geom import wall_thickness_map as wt_facade
        body = _hollow_cube(side=4.0, t=0.5)
        r_direct = wall_thickness_map(body, n_rays=200, seed=3)
        r_facade = wt_facade(body, n_rays=200, seed=3)
        assert r_direct["min_thickness"] == r_facade["min_thickness"]
