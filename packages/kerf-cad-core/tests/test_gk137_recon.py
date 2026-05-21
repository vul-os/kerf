"""Tests for GK-137 — point-cloud → mesh reconstruction.

Oracles
-------
1. Sample ~500 points on a unit sphere; reconstruct with ball-pivoting.
   The Hausdorff distance from every reconstructed vertex to the analytic
   sphere surface must be < 0.15 * r (r = 1).

2. Same oracle applies to the Poisson-lite method.

3. Public import path works: kerf_cad_core.geom.reconstruct_mesh.

4. Output dict has the required keys with correct shapes and dtypes.

5. Error paths return {"ok": False, ...}.
"""

import math
import numpy as np
import pytest

from kerf_cad_core.geom.recon import reconstruct_mesh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sphere_points(n: int = 500, r: float = 1.0, seed: int = 42) -> np.ndarray:
    """Sample *n* approximately uniform points on a sphere of radius *r*."""
    rng = np.random.default_rng(seed)
    # Fibonacci / golden-ratio spiral for uniform coverage
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    indices = np.arange(n, dtype=float)
    theta = np.arccos(1.0 - 2.0 * (indices + 0.5) / n)  # polar
    phi = 2.0 * math.pi * indices / golden               # azimuthal
    pts = np.column_stack([
        r * np.sin(theta) * np.cos(phi),
        r * np.sin(theta) * np.sin(phi),
        r * np.cos(theta),
    ])
    return pts


def _hausdorff_to_sphere(verts: np.ndarray, r: float = 1.0) -> float:
    """Return the max |distance-from-origin - r| over all vertices."""
    dists = np.linalg.norm(verts, axis=1)
    return float(np.max(np.abs(dists - r)))


# ---------------------------------------------------------------------------
# Ball-pivoting oracle
# ---------------------------------------------------------------------------

class TestBallPivotingSphere:
    """Primary oracle: ball-pivoting on a unit sphere."""

    TOL = 0.15  # Hausdorff tolerance as fraction of r

    @pytest.fixture(scope="class")
    def result(self):
        pts = _sphere_points(500)
        return reconstruct_mesh(pts, method="ball_pivoting")

    def test_ok(self, result):
        assert result.get("ok") is True, f"reconstruct_mesh failed: {result.get('reason')}"

    def test_has_required_keys(self, result):
        for key in ("verts", "faces", "n_verts", "n_faces"):
            assert key in result, f"missing key '{key}'"

    def test_verts_shape(self, result):
        verts = result["verts"]
        assert isinstance(verts, np.ndarray)
        assert verts.ndim == 2 and verts.shape[1] == 3, (
            f"expected (V, 3) verts, got {verts.shape}"
        )

    def test_faces_shape(self, result):
        faces = result["faces"]
        assert isinstance(faces, np.ndarray)
        assert faces.ndim == 2 and faces.shape[1] == 3, (
            f"expected (F, 3) faces, got {faces.shape}"
        )

    def test_faces_dtype(self, result):
        assert result["faces"].dtype == np.int64, (
            f"faces dtype should be int64, got {result['faces'].dtype}"
        )

    def test_at_least_one_face(self, result):
        assert result["n_faces"] >= 1, "no faces produced"

    def test_n_verts_consistent(self, result):
        assert result["n_verts"] == len(result["verts"])

    def test_n_faces_consistent(self, result):
        assert result["n_faces"] == len(result["faces"])

    def test_face_indices_in_range(self, result):
        n_v = result["n_verts"]
        faces = result["faces"]
        assert int(faces.min()) >= 0
        assert int(faces.max()) < n_v

    def test_hausdorff_to_sphere(self, result):
        """Reconstructed verts must lie within 0.15*r of the analytic sphere."""
        r = 1.0
        hd = _hausdorff_to_sphere(result["verts"], r)
        tol = self.TOL * r
        assert hd < tol, (
            f"Hausdorff distance {hd:.4f} >= tolerance {tol:.4f} (tol*r)"
        )


# ---------------------------------------------------------------------------
# Poisson-lite oracle
# ---------------------------------------------------------------------------

class TestPoissonSphere:
    """Poisson-lite on a unit sphere."""

    TOL = 0.15

    @pytest.fixture(scope="class")
    def result(self):
        pts = _sphere_points(500, seed=7)
        return reconstruct_mesh(pts, method="poisson")

    def test_ok(self, result):
        assert result.get("ok") is True, f"poisson failed: {result.get('reason')}"

    def test_has_required_keys(self, result):
        for key in ("verts", "faces", "n_verts", "n_faces"):
            assert key in result, f"missing key '{key}'"

    def test_verts_shape(self, result):
        verts = result["verts"]
        assert isinstance(verts, np.ndarray)
        assert verts.ndim == 2 and verts.shape[1] == 3

    def test_faces_dtype(self, result):
        assert result["faces"].dtype == np.int64

    def test_at_least_one_face(self, result):
        assert result["n_faces"] >= 1

    def test_hausdorff_to_sphere(self, result):
        r = 1.0
        hd = _hausdorff_to_sphere(result["verts"], r)
        tol = self.TOL * r
        assert hd < tol, (
            f"Poisson Hausdorff distance {hd:.4f} >= tolerance {tol:.4f}"
        )


# ---------------------------------------------------------------------------
# Public import path
# ---------------------------------------------------------------------------

class TestPublicImport:
    def test_import_from_geom(self):
        from kerf_cad_core.geom import reconstruct_mesh as rm
        assert callable(rm)

    def test_direct_import(self):
        from kerf_cad_core.geom.recon import reconstruct_mesh as rm
        assert callable(rm)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_unknown_method(self):
        pts = _sphere_points(50)
        r = reconstruct_mesh(pts, method="magic")
        assert r["ok"] is False
        assert "magic" in r["reason"]

    def test_too_few_points(self):
        r = reconstruct_mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        assert r["ok"] is False

    def test_wrong_shape(self):
        r = reconstruct_mesh([[0, 0], [1, 0], [0, 1], [0, 0.5]])
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# Explicit radius parameter
# ---------------------------------------------------------------------------

class TestExplicitRadius:
    def test_explicit_radius_ball_pivoting(self):
        pts = _sphere_points(300)
        r = reconstruct_mesh(pts, method="ball_pivoting", radius=0.4)
        assert r.get("ok") is True
        assert r["n_faces"] >= 1

    def test_explicit_radius_poisson(self):
        pts = _sphere_points(300)
        r = reconstruct_mesh(pts, method="poisson", radius=0.15)
        assert r.get("ok") is True
        assert r["n_faces"] >= 1
