"""test_threedm_roundtrip_hausdorff.py — Rhino .3dm write-side + Hausdorff round-trip oracle.

Tests
-----
 1. Header magic: first 4 bytes of write_3dm_bytes output start with b'3D G'.
 2. Header exactly 32 bytes match the magic prefix.
 3. Round-trip NurbsCurve: control points identical within 1e-12.
 4. Round-trip NurbsCurve: knots identical within 1e-12.
 5. Round-trip NurbsSurface (degree 3×3, 4×4 grid): Hausdorff < 1e-6.
 6. Round-trip preserves version and units string.
 7. Round-trip rational (non-unit weight) NurbsSurface: weights within 1e-12.
 8. write_3dm_bytes() returns at least N bytes (header + chunk overhead).
 9. Empty model round-trips cleanly (no objects, no crash).
10. Multiple objects: 1 curve + 2 surfaces — all counts preserved.
11. hausdorff_distance(surface, surface) == 0 within 1e-14 (identity).
12. hausdorff_distance(sphere_R1, sphere_R2) ≈ |R1 - R2| within sampling tol.
13. write_3dm file produces the same content as write_3dm_bytes.
14. Round-trip mesh: vertex count preserved.
"""

from __future__ import annotations

import math
import os
import tempfile

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_imports.threedm_write import (
    ThreeDmFile,
    hausdorff_distance,
    read_threedm_bytes,
    write_3dm,
    write_3dm_bytes,
)


# ---------------------------------------------------------------------------
# Helpers: build canonical test geometry
# ---------------------------------------------------------------------------

def _make_cubic_curve() -> NurbsCurve:
    """Degree-3 open NURBS curve with 4 control points (clamped)."""
    pts = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, -1.0, 0.5],
        [3.0, 0.0, 1.0],
    ])
    # clamped degree-3 knot vector: n+d+1 = 4+3+1 = 8 knots
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=pts, knots=knots)


def _make_bicubic_surface() -> NurbsSurface:
    """Degree 3×3 NURBS surface with 4×4 control grid (non-rational)."""
    pts = np.array([
        [[float(i), float(j), float(i * j) * 0.1] for j in range(4)]
        for i in range(4)
    ])
    knots_u = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=3, degree_v=3,
        control_points=pts,
        knots_u=knots_u, knots_v=knots_v,
    )


def _make_rational_surface() -> NurbsSurface:
    """Degree 2×2, 3×3 rational surface with non-unit weights."""
    pts = np.array([
        [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]],
        [[1.0, 0.0, 0.5], [1.0, 1.0, 1.0], [1.0, 2.0, 0.5]],
        [[2.0, 0.0, 0.0], [2.0, 1.0, 0.0], [2.0, 2.0, 0.0]],
    ])
    w = 1.0 / math.sqrt(2.0)
    weights = np.array([
        [1.0, w,   1.0],
        [w,   w*w, w  ],
        [1.0, w,   1.0],
    ])
    knots_u = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=pts,
        knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


def _make_sphere_nurbs(radius: float = 1.0) -> NurbsSurface:
    """Standard 9×5 rational NURBS sphere (degree 2×2)."""
    r = float(radius)
    w = 1.0 / math.sqrt(2.0)

    ku = np.array([0, 0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1, 1, 1], dtype=float)
    kv = np.array([0, 0, 0, 0.5, 0.5, 1, 1, 1], dtype=float)

    nv = 5
    nu = 9

    v_angles = [-math.pi / 2, -math.pi / 4, 0.0, math.pi / 4, math.pi / 2]
    cos_phi = [math.cos(a) for a in v_angles]
    sin_phi = [math.sin(a) for a in v_angles]
    w_v = [1.0, w, 1.0, w, 1.0]

    u_angles = [k * math.pi / 4 for k in range(9)]
    cos_th = [math.cos(a) for a in u_angles]
    sin_th = [math.sin(a) for a in u_angles]
    w_u = [1.0 if k % 2 == 0 else w for k in range(9)]

    pts = np.zeros((nu, nv, 3))
    wts = np.zeros((nu, nv))

    for j in range(nv):
        for i in range(nu):
            wij = w_u[i] * w_v[j]
            pts[i, j] = [
                r * cos_th[i] * cos_phi[j],
                r * sin_th[i] * cos_phi[j],
                r * sin_phi[j],
            ]
            wts[i, j] = wij

    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=pts,
        knots_u=ku, knots_v=kv,
        weights=wts,
    )


# ---------------------------------------------------------------------------
# Test 1 & 2: Header magic
# ---------------------------------------------------------------------------

class TestHeaderMagic:

    def test_first_4_bytes_magic(self):
        """write_3dm_bytes starts with b'3D G'."""
        model = ThreeDmFile()
        data = write_3dm_bytes(model)
        assert data[:4] == b"3D G", (
            f"Expected b'3D G', got {data[:4]!r}"
        )

    def test_header_32_bytes_match_magic_prefix(self):
        """First 32 bytes contain the openNURBS magic."""
        model = ThreeDmFile()
        data = write_3dm_bytes(model)
        assert len(data) >= 32
        assert b"3D Geometry File Format" in data[:32], (
            f"Magic not found in first 32 bytes: {data[:32]!r}"
        )


# ---------------------------------------------------------------------------
# Test 3 & 4: NurbsCurve round-trip
# ---------------------------------------------------------------------------

class TestNurbsCurveRoundTrip:

    def _roundtrip(self, crv: NurbsCurve) -> NurbsCurve:
        model = ThreeDmFile(nurbs_curves=[crv])
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert len(rt.nurbs_curves) == 1, (
            f"Expected 1 curve, got {len(rt.nurbs_curves)}"
        )
        return rt.nurbs_curves[0]

    def test_control_points_identical(self):
        """Control points survive round-trip within 1e-12."""
        crv = _make_cubic_curve()
        rt_crv = self._roundtrip(crv)
        assert rt_crv.control_points.shape == crv.control_points.shape
        assert np.allclose(crv.control_points, rt_crv.control_points, atol=1e-12), (
            "NurbsCurve control points diverged after .3dm round-trip"
        )

    def test_knots_preserved(self):
        """Knot vector survives round-trip within 1e-12."""
        crv = _make_cubic_curve()
        rt_crv = self._roundtrip(crv)
        assert np.allclose(crv.knots, rt_crv.knots, atol=1e-12)

    def test_degree_preserved(self):
        crv = _make_cubic_curve()
        rt_crv = self._roundtrip(crv)
        assert rt_crv.degree == crv.degree


# ---------------------------------------------------------------------------
# Test 5: NurbsSurface round-trip Hausdorff oracle
# ---------------------------------------------------------------------------

class TestNurbsSurfaceHausdorff:

    def test_bicubic_hausdorff_below_tolerance(self):
        """degree 3×3, 4×4 grid: Hausdorff < 1e-6 after round-trip."""
        srf = _make_bicubic_surface()
        model = ThreeDmFile(nurbs_surfaces=[srf])
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert len(rt.nurbs_surfaces) == 1
        rt_srf = rt.nurbs_surfaces[0]
        h = hausdorff_distance(srf, rt_srf, n_samples=100)
        assert h < 1e-6, (
            f"Hausdorff distance {h:.3e} exceeds 1e-6 after round-trip"
        )


# ---------------------------------------------------------------------------
# Test 6: version and units preserved
# ---------------------------------------------------------------------------

class TestVersionAndUnits:

    def test_version_7_preserved(self):
        model = ThreeDmFile(version=7, units="mm")
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert rt.version == 7

    def test_units_mm_preserved(self):
        model = ThreeDmFile(version=6, units="mm")
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert rt.units == "mm"

    def test_units_m_preserved(self):
        model = ThreeDmFile(version=6, units="m")
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert rt.units == "m"

    def test_units_in_preserved(self):
        model = ThreeDmFile(version=6, units="in")
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert rt.units == "in"


# ---------------------------------------------------------------------------
# Test 7: rational surface weights preserved
# ---------------------------------------------------------------------------

class TestRationalWeights:

    def test_weights_preserved_within_1e12(self):
        """Non-unit rational weights survive round-trip within 1e-12."""
        srf = _make_rational_surface()
        model = ThreeDmFile(nurbs_surfaces=[srf])
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert len(rt.nurbs_surfaces) == 1
        rt_srf = rt.nurbs_surfaces[0]
        assert rt_srf.weights is not None, "Rational surface lost weights on round-trip"
        assert srf.weights is not None
        assert np.allclose(srf.weights, rt_srf.weights, atol=1e-12), (
            "Rational weights diverged after round-trip"
        )

    def test_control_points_also_preserved(self):
        srf = _make_rational_surface()
        model = ThreeDmFile(nurbs_surfaces=[srf])
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        rt_srf = rt.nurbs_surfaces[0]
        assert np.allclose(srf.control_points, rt_srf.control_points, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 8: minimum byte count
# ---------------------------------------------------------------------------

class TestMinimumBytes:

    def test_minimum_size_single_surface(self):
        """write_3dm_bytes with a surface returns at least header+chunk overhead."""
        srf = _make_bicubic_surface()
        model = ThreeDmFile(nurbs_surfaces=[srf])
        data = write_3dm_bytes(model)
        # Header 33B + at least one chunk header 8B + non-empty payload
        assert len(data) >= 33 + 8 + 1, (
            f"Output too small: {len(data)} bytes"
        )

    def test_minimum_size_empty_model(self):
        """Even an empty model must produce the 33-byte header + end-mark."""
        model = ThreeDmFile()
        data = write_3dm_bytes(model)
        assert len(data) >= 33 + 8, (
            f"Empty model output too small: {len(data)} bytes"
        )


# ---------------------------------------------------------------------------
# Test 9: empty model round-trip
# ---------------------------------------------------------------------------

class TestEmptyModel:

    def test_empty_roundtrip_no_crash(self):
        """Empty model (no objects) round-trips cleanly."""
        model = ThreeDmFile(version=6, units="mm")
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert rt.nurbs_curves == []
        assert rt.nurbs_surfaces == []
        assert rt.meshes == []

    def test_empty_roundtrip_valid_bytes(self):
        """Empty model still produces a parseable .3dm header."""
        model = ThreeDmFile()
        data = write_3dm_bytes(model)
        assert data[:4] == b"3D G"


# ---------------------------------------------------------------------------
# Test 10: multiple objects round-trip
# ---------------------------------------------------------------------------

class TestMultipleObjects:

    def test_1_curve_2_surfaces_counts(self):
        """1 curve + 2 surfaces: all counts preserved after round-trip."""
        crv = _make_cubic_curve()
        srf1 = _make_bicubic_surface()
        srf2 = _make_rational_surface()
        model = ThreeDmFile(
            nurbs_curves=[crv],
            nurbs_surfaces=[srf1, srf2],
        )
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert len(rt.nurbs_curves) == 1, (
            f"Expected 1 curve, got {len(rt.nurbs_curves)}"
        )
        assert len(rt.nurbs_surfaces) == 2, (
            f"Expected 2 surfaces, got {len(rt.nurbs_surfaces)}"
        )

    def test_1_curve_2_surfaces_geometry_correct(self):
        """Curve control points correct even when surfaces are also present."""
        crv = _make_cubic_curve()
        srf1 = _make_bicubic_surface()
        srf2 = _make_rational_surface()
        model = ThreeDmFile(
            nurbs_curves=[crv],
            nurbs_surfaces=[srf1, srf2],
        )
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        rt_crv = rt.nurbs_curves[0]
        assert np.allclose(crv.control_points, rt_crv.control_points, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 11: Hausdorff identity
# ---------------------------------------------------------------------------

class TestHausdorffIdentity:

    def test_identity_distance_zero(self):
        """hausdorff_distance(srf, srf) == 0 within 1e-14."""
        srf = _make_bicubic_surface()
        h = hausdorff_distance(srf, srf, n_samples=50)
        assert h < 1e-14, (
            f"Hausdorff(srf, srf) = {h:.3e}, expected < 1e-14"
        )

    def test_rational_surface_identity(self):
        srf = _make_rational_surface()
        h = hausdorff_distance(srf, srf, n_samples=20)
        assert h < 1e-14


# ---------------------------------------------------------------------------
# Test 12: Hausdorff sphere radii
# ---------------------------------------------------------------------------

class TestHausdorffSphereDiff:

    def test_hausdorff_sphere_r1_vs_r2(self):
        """hausdorff_distance(sphere_R1, sphere_R2) ≈ |R1 - R2| ± sampling tol."""
        R1 = 1.0
        R2 = 2.0
        expected = abs(R1 - R2)
        s1 = _make_sphere_nurbs(R1)
        s2 = _make_sphere_nurbs(R2)
        h = hausdorff_distance(s1, s2, n_samples=30)
        # Sampling tolerance: largest pole error on R=2 sphere at 30 samples
        # is on the order of the step size between samples.  Accept 5% of R.
        tol = 0.05 * max(R1, R2)
        assert abs(h - expected) < tol, (
            f"Hausdorff(R1={R1}, R2={R2}) = {h:.6f}, expected ≈ {expected:.6f} ± {tol:.4f}"
        )

    def test_hausdorff_sphere_small_delta(self):
        """Small radius delta (0.01) is detectable."""
        R1 = 1.0
        R2 = 1.01
        s1 = _make_sphere_nurbs(R1)
        s2 = _make_sphere_nurbs(R2)
        h = hausdorff_distance(s1, s2, n_samples=30)
        # Should be close to 0.01 within generous sampling tolerance
        assert 0.001 < h < 0.1, (
            f"Hausdorff for delta=0.01 expected ~0.01, got {h:.6f}"
        )


# ---------------------------------------------------------------------------
# Test 13: write_3dm file matches write_3dm_bytes
# ---------------------------------------------------------------------------

class TestWriteFile:

    def test_file_matches_bytes(self):
        """write_3dm produces the same content as write_3dm_bytes."""
        srf = _make_bicubic_surface()
        model = ThreeDmFile(nurbs_surfaces=[srf])
        blob = write_3dm_bytes(model)

        with tempfile.NamedTemporaryFile(suffix=".3dm", delete=False) as f:
            fname = f.name
        try:
            write_3dm(model, fname)
            with open(fname, "rb") as fh:
                file_data = fh.read()
        finally:
            os.unlink(fname)

        assert file_data == blob, (
            "write_3dm file content differs from write_3dm_bytes output"
        )


# ---------------------------------------------------------------------------
# Test 14: Mesh round-trip
# ---------------------------------------------------------------------------

class TestMeshRoundTrip:

    def test_mesh_vertex_count_preserved(self):
        """Mesh vertex count survives round-trip."""
        verts = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 1.0, 0.0],
            [0.5, 0.5, 1.0],
        ])
        faces = np.array([[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]])
        mesh = {"vertices": verts, "faces": faces}
        model = ThreeDmFile(meshes=[mesh])
        data = write_3dm_bytes(model)
        rt = read_threedm_bytes(data)
        assert len(rt.meshes) == 1
        rt_verts = rt.meshes[0]["vertices"]
        assert rt_verts.shape[0] == 4, (
            f"Expected 4 vertices, got {rt_verts.shape[0]}"
        )
        assert np.allclose(verts, rt_verts, atol=1e-12)
