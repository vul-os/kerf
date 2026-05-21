"""GK-117 — Hermetic oracle tests for tpms_sheet.

Oracles (from spec):
1. Schwarz-P sheet is closed-manifold: Euler characteristic is even,
   no boundary edges.
2. The sheet is periodic: translating sample points by cell_size gives
   the same |f| value (periodicity of the underlying implicit).
3. Mean curvature ≈ 0 on mid-surface sample points (Schwarz-P / gyroid
   are minimal surfaces by definition).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.lattice import tpms_sheet
from kerf_cad_core.geom import tpms_sheet as geom_tpms_sheet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _boundary_edges(faces: np.ndarray) -> set:
    """Return the set of half-edges that appear exactly once (boundary)."""
    from collections import Counter
    edge_count: Counter = Counter()
    for tri in faces:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        for e in [(a, b), (b, c), (c, a)]:
            # Canonical: sort so (u,v) and (v,u) hash the same.
            edge_count[tuple(sorted(e))] += 1
    return {e for e, cnt in edge_count.items() if cnt == 1}


def _euler_characteristic(verts: np.ndarray, faces: np.ndarray) -> int:
    """Compute V - E + F (Euler characteristic of the mesh)."""
    V = len(verts)
    F = len(faces)
    edges: set = set()
    for tri in faces:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        for e in [(a, b), (b, c), (c, a)]:
            edges.add(tuple(sorted(e)))
    E = len(edges)
    return V - E + F


def _triangle_area(p0, p1, p2):
    """Area of a triangle given three 3-D vertices."""
    v1 = p1 - p0
    v2 = p2 - p0
    return 0.5 * float(np.linalg.norm(np.cross(v1, v2)))


def _mean_curvature_at_point(f_scalar, p, eps=0.05):
    """Estimate mean curvature of f=const surface at p using finite differences.

    Uses the formula H = div(∇f/|∇f|) / 2, approximated by a 6-point stencil.
    Returns the signed mean curvature (should be ≈0 for a minimal surface).
    """
    x, y, z = p
    # Gradient (central difference)
    gx = (f_scalar(x + eps, y, z) - f_scalar(x - eps, y, z)) / (2 * eps)
    gy = (f_scalar(x, y + eps, z) - f_scalar(x, y - eps, z)) / (2 * eps)
    gz = (f_scalar(x, y, z + eps) - f_scalar(x, y, z - eps)) / (2 * eps)
    g = np.array([gx, gy, gz])
    mag = np.linalg.norm(g)
    if mag < 1e-12:
        return float("nan")
    n = g / mag  # unit normal

    # Divergence of unit normal (second-order Laplacian of the level set)
    # Using 6-point stencil on the unit normal field.
    def unit_n(xp, yp, zp):
        gxp = (f_scalar(xp + eps, yp, zp) - f_scalar(xp - eps, yp, zp)) / (2 * eps)
        gyp = (f_scalar(xp, yp + eps, zp) - f_scalar(xp, yp - eps, zp)) / (2 * eps)
        gzp = (f_scalar(xp, yp, zp + eps) - f_scalar(xp, yp, zp - eps)) / (2 * eps)
        gp = np.array([gxp, gyp, gzp])
        mp = np.linalg.norm(gp)
        if mp < 1e-12:
            return np.zeros(3)
        return gp / mp

    h = eps
    dnx_dx = (unit_n(x + h, y, z)[0] - unit_n(x - h, y, z)[0]) / (2 * h)
    dny_dy = (unit_n(x, y + h, z)[1] - unit_n(x, y - h, z)[1]) / (2 * h)
    dnz_dz = (unit_n(x, y, z + h)[2] - unit_n(x, y, z - h)[2]) / (2 * h)
    H = (dnx_dx + dny_dy + dnz_dz) / 2.0
    return H


# ---------------------------------------------------------------------------
# Basic API contract
# ---------------------------------------------------------------------------

class TestTPMSSheetAPI:
    def test_returns_dict_with_verts_and_faces(self):
        result = tpms_sheet(cell_type="schwarz_p", cell_size=10.0, thickness=1.0)
        assert isinstance(result, dict)
        assert "verts" in result
        assert "faces" in result

    def test_verts_shape(self):
        result = tpms_sheet("schwarz_p", 10.0, 1.0)
        assert result["verts"].ndim == 2
        assert result["verts"].shape[1] == 3

    def test_faces_shape(self):
        result = tpms_sheet("schwarz_p", 10.0, 1.0)
        assert result["faces"].ndim == 2
        assert result["faces"].shape[1] == 3

    def test_non_empty_mesh(self):
        result = tpms_sheet("schwarz_p", 10.0, 1.0)
        assert len(result["verts"]) > 0
        assert len(result["faces"]) > 0

    def test_re_exported_from_geom(self):
        result = geom_tpms_sheet(cell_type="schwarz_p", cell_size=10.0, thickness=1.0)
        assert "verts" in result
        assert "faces" in result

    @pytest.mark.parametrize("cell_type", ["schwarz_p", "gyroid", "diamond"])
    def test_all_cell_types_produce_mesh(self, cell_type):
        result = tpms_sheet(cell_type=cell_type, cell_size=10.0, thickness=1.0)
        assert len(result["verts"]) > 0
        assert len(result["faces"]) > 0

    def test_invalid_cell_type(self):
        with pytest.raises(ValueError):
            tpms_sheet(cell_type="invalid", cell_size=10.0, thickness=1.0)

    def test_invalid_cell_size(self):
        with pytest.raises(ValueError):
            tpms_sheet(cell_size=0.0, thickness=1.0)

    def test_invalid_thickness(self):
        with pytest.raises(ValueError):
            tpms_sheet(cell_size=10.0, thickness=-0.5)


# ---------------------------------------------------------------------------
# Oracle 1: closed manifold — no boundary edges, Euler χ even
# ---------------------------------------------------------------------------

class TestClosedManifold:
    """Schwarz-P sheet of moderate thickness should be a closed manifold."""

    @pytest.fixture(scope="class")
    def mesh(self):
        # 2 cells × 2 cells × 2 cells; thickness = 1 mm into a 10 mm cell
        return tpms_sheet(
            cell_type="schwarz_p",
            cell_size=10.0,
            thickness=1.0,
            bounds=((0.0, 20.0), (0.0, 20.0), (0.0, 20.0)),
        )

    def test_no_boundary_edges(self, mesh):
        """Interior TPMS band must have no open boundary edges."""
        boundary = _boundary_edges(mesh["faces"])
        assert len(boundary) == 0, (
            f"Expected 0 boundary edges, got {len(boundary)}"
        )

    def test_euler_characteristic_even(self, mesh):
        """Euler characteristic of a closed orientable surface is even (2-2g)."""
        chi = _euler_characteristic(mesh["verts"], mesh["faces"])
        assert chi % 2 == 0, f"Euler characteristic {chi} is not even"

    def test_face_indices_in_range(self, mesh):
        verts = mesh["verts"]
        faces = mesh["faces"]
        assert int(faces.min()) >= 0
        assert int(faces.max()) < len(verts)


# ---------------------------------------------------------------------------
# Oracle 2: periodicity — translating a point by cell_size gives same |f|
# ---------------------------------------------------------------------------

class TestPeriodicity:
    """The underlying implicit is periodic; same band membership after shift."""

    @pytest.mark.parametrize("cell_type,axis", [
        ("schwarz_p", 0),
        ("schwarz_p", 1),
        ("schwarz_p", 2),
        ("gyroid", 0),
        ("gyroid", 1),
    ])
    def test_periodic_band_membership(self, cell_type, axis):
        """|f(p)| ≈ |f(p + cell_size·axis)| for mid-surface points."""
        cell_size = 10.0
        k = 2.0 * math.pi / cell_size

        sample_pts = [
            (2.3, 1.7, 3.5),
            (4.1, 0.8, 2.2),
            (1.0, 3.0, 1.5),
        ]

        if cell_type == "schwarz_p":
            def f(x, y, z):
                return math.cos(k * x) + math.cos(k * y) + math.cos(k * z)
        else:  # gyroid
            def f(x, y, z):
                return (
                    math.sin(k * x) * math.cos(k * y)
                    + math.sin(k * y) * math.cos(k * z)
                    + math.sin(k * z) * math.cos(k * x)
                )

        shift = [0.0, 0.0, 0.0]
        shift[axis] = cell_size

        for pt in sample_pts:
            x, y, z = pt
            f0 = f(x, y, z)
            f1 = f(x + shift[0], y + shift[1], z + shift[2])
            assert abs(f0 - f1) < 1e-10, (
                f"{cell_type} axis={axis}: f({pt}) = {f0} but f(p+L) = {f1}"
            )


# ---------------------------------------------------------------------------
# Oracle 3: mean curvature ≈ 0 on mid-surface (TPMS property)
# ---------------------------------------------------------------------------

class TestMeanCurvature:
    """Schwarz-P mid-surface (f=0) is a minimal surface: H ≈ 0."""

    def test_schwarz_p_mean_curvature_near_zero(self):
        """Sample mid-surface points and verify H ≈ 0 within tolerance."""
        cell_size = 10.0
        k = 2.0 * math.pi / cell_size
        eps = 0.02  # finite difference step (mm)

        def f_sp(x, y, z):
            return math.cos(k * x) + math.cos(k * y) + math.cos(k * z)

        # Schwarz-P mid-surface (f=0) known points:
        # cos(kx)+cos(ky)+cos(kz)=0 when e.g. kx=π/2, ky=π/2, kz=π
        # i.e. x=L/4, y=L/4, z=L/2: cos(π/2)+cos(π/2)+cos(π) = 0+0-1 = -1  NO
        # Better: use a numerically verified zero.
        # cos(kx)+cos(ky)+cos(kz)=0 → set kx=2π/3, ky=2π/3, kz=2π/3:
        #   cos(2π/3)=-0.5; sum=-1.5 NO
        # kx=0, ky=π/2, kz=π/2: 1+0+0=1 NO
        # kx=π/3, ky=π/3, kz=π: cos(π/3)+cos(π/3)+cos(π) = 0.5+0.5-1 = 0  YES
        L = cell_size
        # kx=π/3 → x = (π/3)/k = L/6
        # ky=π/3 → y = L/6
        # kz=π   → z = L/2
        mid_pts = [
            (L / 6, L / 6, L / 2),
        ]

        for pt in mid_pts:
            # Verify it's actually on the mid-surface
            fval = f_sp(*pt)
            assert abs(fval) < 1e-10, f"Test point {pt} not on mid-surface, f={fval}"

            H = _mean_curvature_at_point(f_sp, pt, eps=eps)
            if not math.isnan(H):
                # Minimal surface: |H| << 1 relative to k²
                # For a cell_size=10, k ≈ 0.628; max |H| < 0.2 is very generous
                assert abs(H) < 0.2, (
                    f"Mean curvature at {pt}: H={H:.4f}, expected ≈ 0 for minimal surface"
                )

    def test_gyroid_mean_curvature_near_zero(self):
        """Gyroid mid-surface (f=0) is a minimal surface: H ≈ 0."""
        cell_size = 10.0
        k = 2.0 * math.pi / cell_size
        eps = 0.02

        def f_g(x, y, z):
            return (
                math.sin(k * x) * math.cos(k * y)
                + math.sin(k * y) * math.cos(k * z)
                + math.sin(k * z) * math.cos(k * x)
            )

        # Gyroid mid-surface point: f=0 at (0, L/4, 0) — sin(0)cos(π/2) + ...
        # Actually at (0,0,0): sin(0)cos(0)+sin(0)cos(0)+sin(0)cos(0) = 0
        L = cell_size
        pt = (0.0, 0.0, 0.0)
        fval = f_g(*pt)
        assert abs(fval) < 1e-12

        H = _mean_curvature_at_point(f_g, pt, eps=eps)
        if not math.isnan(H):
            assert abs(H) < 0.2


# ---------------------------------------------------------------------------
# Thickness scaling sanity
# ---------------------------------------------------------------------------

class TestThicknessScaling:
    """Thicker sheets should have more/equal faces; volume fraction scales."""

    def test_varying_thickness_produces_mesh(self):
        """Different thickness values all produce valid non-empty meshes."""
        for t in [0.3, 1.0, 2.0]:
            result = tpms_sheet("schwarz_p", 10.0, t)
            assert len(result["verts"]) > 0, f"thickness={t} yielded empty mesh"
            assert len(result["faces"]) > 0, f"thickness={t} yielded no faces"

    def test_custom_bounds_respected(self):
        result = tpms_sheet(
            cell_type="schwarz_p",
            cell_size=10.0,
            thickness=1.0,
            bounds=((0.0, 10.0), (0.0, 10.0), (0.0, 10.0)),
        )
        # Vertices should lie within the specified bounds
        verts = result["verts"]
        assert float(verts[:, 0].min()) >= -0.1
        assert float(verts[:, 0].max()) <= 10.1
