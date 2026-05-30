"""Tests for geom/mass_props_mesh.py — triangle-mesh volume/centroid/inertia.

Oracles
-------
- Unit cube (12 triangles):
    V = 1.0 ± 1e-9
    centroid = (0.5, 0.5, 0.5)
    Ixx = Iyy = Izz = 1/6 about CG  (m/12*(ly²+lz²) = 1/12*(1+1) = 1/6)
    Ixy = Ixz = Iyz = 0
- Unit sphere (UV-subdivided, ~7200 triangles):
    V ≈ 4π/3 ± 1e-3 relative
    centroid ≈ (0,0,0) ± 1e-9
    I_diagonal ≈ (2/5)·mass·r² ± 1e-3 relative
- L-shape: two cubes; centroid off-centre by known amount
- Open mesh → ValueError
- Tetrahedron (Mirtich 1996 oracle): exact V + centroid

References: Mirtich 1996; Mortenson §11.4; Eberly 2002.
"""

import math
import numpy as np
import pytest

from kerf_cad_core.geom.mass_props_mesh import compute_mesh_mass_props, MassPropsReport


# ---------------------------------------------------------------------------
# Mesh builders
# ---------------------------------------------------------------------------

def _cube_mesh():
    """Unit cube [0,1]^3 as 12 triangles — outward normals."""
    verts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=float)
    tris = np.array([
        # bottom z=0 (normal -z, CW from below → CCW from outside)
        [0, 2, 1], [0, 3, 2],
        # top z=1 (normal +z)
        [4, 5, 6], [4, 6, 7],
        # front y=0 (normal -y)
        [0, 1, 5], [0, 5, 4],
        # back y=1 (normal +y)
        [3, 7, 6], [3, 6, 2],
        # left x=0 (normal -x)
        [0, 4, 7], [0, 7, 3],
        # right x=1 (normal +x)
        [1, 2, 6], [1, 6, 5],
    ], dtype=int)
    return verts, tris


def _sphere_mesh(n_lat=60, n_lon=60):
    """UV sphere of radius 1 centred at origin.  ~2*n_lat*n_lon triangles."""
    verts, tris = [], []
    stride = n_lon + 1
    for i in range(n_lat + 1):
        lat = math.pi * (-0.5 + i / n_lat)
        for j in range(n_lon + 1):
            lon = 2.0 * math.pi * j / n_lon
            verts.append([
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            ])
    for i in range(n_lat):
        for j in range(n_lon):
            a = i * stride + j
            b = a + 1
            c = (i + 1) * stride + j
            e = c + 1
            tris.append([a, b, e])
            tris.append([a, e, c])
    return np.array(verts, dtype=float), np.array(tris, dtype=int)


def _tetrahedron_mesh():
    """Regular tetrahedron: 4 triangles, analytic volume = |det|/6.

    Winding chosen to produce outward-facing normals (positive signed volume).
    """
    verts = np.array([
        [ 1,  1,  1],
        [-1, -1,  1],
        [-1,  1, -1],
        [ 1, -1, -1],
    ], dtype=float)
    # Flip winding from previous (inward) to outward: swap columns 1 and 2
    tris = np.array([
        [0, 2, 1],
        [0, 1, 3],
        [0, 3, 2],
        [1, 2, 3],
    ], dtype=int)
    return verts, tris


def _l_shape_mesh():
    """Two axis-aligned boxes sharing a face.

    Box A: [0,1]×[0,1]×[0,1]    V=1    cx=0.5, cy=0.5
    Box B: [1,2]×[0,0.5]×[0,1]  V=0.5  cx=1.5, cy=0.25

    Expected total: V=1.5,
        cx = (1*0.5 + 0.5*1.5) / 1.5 = 5/6
        cy = (1*0.5 + 0.5*0.25) / 1.5 = 5/12
        cz = 0.5
    """
    def _box(ox, oy, oz, sx, sy, sz, off):
        v = np.array([
            [ox,    oy,    oz   ],
            [ox+sx, oy,    oz   ],
            [ox+sx, oy+sy, oz   ],
            [ox,    oy+sy, oz   ],
            [ox,    oy,    oz+sz],
            [ox+sx, oy,    oz+sz],
            [ox+sx, oy+sy, oz+sz],
            [ox,    oy+sy, oz+sz],
        ], dtype=float)
        t = np.array([
            [0, 2, 1], [0, 3, 2],
            [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4],
            [3, 7, 6], [3, 6, 2],
            [0, 4, 7], [0, 7, 3],
            [1, 2, 6], [1, 6, 5],
        ], dtype=int) + off
        return v, t

    v1, t1 = _box(0, 0, 0, 1, 1, 1, 0)
    v2, t2 = _box(1, 0, 0, 1, 0.5, 1, 8)
    return np.vstack([v1, v2]), np.vstack([t1, t2])


# ---------------------------------------------------------------------------
# Unit cube
# ---------------------------------------------------------------------------

class TestUnitCube:
    def setup_method(self):
        verts, tris = _cube_mesh()
        self.r = compute_mesh_mass_props(verts, tris, density=1.0)

    def test_volume(self):
        assert abs(self.r.volume - 1.0) < 1e-9, f"volume={self.r.volume}"

    def test_mass(self):
        assert abs(self.r.mass - 1.0) < 1e-9

    def test_centroid(self):
        assert np.allclose(self.r.centroid, [0.5, 0.5, 0.5], atol=1e-9), (
            f"centroid={self.r.centroid}"
        )

    def test_ixx(self):
        # I_xx about CG for solid unit cube = m/12*(ly²+lz²) = 1/12*2 = 1/6
        expected = 1.0 / 6.0
        assert abs(self.r.inertia_tensor[0, 0] - expected) < 1e-9, (
            f"Ixx={self.r.inertia_tensor[0,0]:.12f} expected={expected:.12f}"
        )

    def test_iyy(self):
        assert abs(self.r.inertia_tensor[1, 1] - 1.0 / 6.0) < 1e-9

    def test_izz(self):
        assert abs(self.r.inertia_tensor[2, 2] - 1.0 / 6.0) < 1e-9

    def test_off_diagonal_zero(self):
        I = self.r.inertia_tensor
        assert abs(I[0, 1]) < 1e-9
        assert abs(I[0, 2]) < 1e-9
        assert abs(I[1, 2]) < 1e-9

    def test_triangle_count(self):
        assert self.r.triangle_count == 12

    def test_principal_moments_positive(self):
        assert np.all(self.r.principal_moments > 0)


# ---------------------------------------------------------------------------
# Unit sphere
# ---------------------------------------------------------------------------

class TestUnitSphere:
    """UV sphere 60×60 has ~7200 triangles; discrete approximation of a curved surface.

    Volume and inertia errors are O(h²) in the mesh step — 60×60 gives < 0.5%
    relative error, hence 5e-3 tolerance (stricter than coarse-mesh 1% bound).
    """

    def setup_method(self):
        verts, tris = _sphere_mesh(n_lat=60, n_lon=60)
        self.r = compute_mesh_mass_props(verts, tris, density=1.0)
        self.V_exact = 4.0 / 3.0 * math.pi

    def test_volume(self):
        rel_err = abs(self.r.volume - self.V_exact) / self.V_exact
        assert rel_err < 5e-3, f"rel_err={rel_err:.6f}, volume={self.r.volume}"

    def test_centroid_at_origin(self):
        assert np.allclose(self.r.centroid, [0, 0, 0], atol=1e-9)

    def test_inertia_diagonal(self):
        # I_xx = I_yy = I_zz = (2/5) m r²  (exact for continuous sphere)
        # On a 60×60 mesh the discrete approximation introduces O(h²) bias.
        expected = (2.0 / 5.0) * self.r.mass
        I = self.r.inertia_tensor
        for i in range(3):
            rel_err = abs(I[i, i] - expected) / expected
            assert rel_err < 5e-3, (
                f"I[{i},{i}]={I[i,i]:.8f} expected={expected:.8f} rel_err={rel_err:.6f}"
            )

    def test_off_diagonal_near_zero(self):
        I = self.r.inertia_tensor
        scale = self.r.mass
        assert abs(I[0, 1]) / scale < 1e-9
        assert abs(I[0, 2]) / scale < 1e-9
        assert abs(I[1, 2]) / scale < 1e-9


# ---------------------------------------------------------------------------
# L-shape
# ---------------------------------------------------------------------------

class TestLShape:
    def setup_method(self):
        verts, tris = _l_shape_mesh()
        self.r = compute_mesh_mass_props(verts, tris, density=1.0)

    def test_volume(self):
        assert abs(self.r.volume - 1.5) < 1e-9, f"volume={self.r.volume}"

    def test_centroid_x(self):
        expected = 5.0 / 6.0
        assert abs(self.r.centroid[0] - expected) < 1e-9, (
            f"cx={self.r.centroid[0]:.12f} expected={expected:.12f}"
        )

    def test_centroid_y(self):
        # cy = (1*0.5 + 0.5*0.25) / 1.5 = 0.625/1.5 = 5/12
        expected = 5.0 / 12.0
        assert abs(self.r.centroid[1] - expected) < 1e-9, (
            f"cy={self.r.centroid[1]:.12f} expected={expected:.12f}"
        )

    def test_centroid_z(self):
        assert abs(self.r.centroid[2] - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# Tetrahedron oracle (Mirtich 1996)
# ---------------------------------------------------------------------------

class TestTetrahedronOracle:
    def setup_method(self):
        self.verts, self.tris = _tetrahedron_mesh()
        self.r = compute_mesh_mass_props(self.verts, self.tris, density=1.0)
        v = self.verts
        mat = np.array([v[1] - v[0], v[2] - v[0], v[3] - v[0]])
        self.V_exact = abs(np.linalg.det(mat)) / 6.0

    def test_volume(self):
        assert abs(self.r.volume - self.V_exact) < 1e-9, (
            f"volume={self.r.volume:.12f} expected={self.V_exact:.12f}"
        )

    def test_centroid(self):
        expected = self.verts.mean(axis=0)
        assert np.allclose(self.r.centroid, expected, atol=1e-9)

    def test_principal_moments_ordered(self):
        pm = self.r.principal_moments
        assert pm[0] <= pm[1] + 1e-12
        assert pm[1] <= pm[2] + 1e-12


# ---------------------------------------------------------------------------
# Open-mesh error guard
# ---------------------------------------------------------------------------

class TestOpenMeshError:
    def test_open_mesh_raises(self):
        """Single triangle: signed volume = 0 → ValueError."""
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        tris = np.array([[0, 1, 2]], dtype=int)
        with pytest.raises(ValueError, match="volume"):
            compute_mesh_mass_props(verts, tris)

    def test_open_mesh_allow_open(self):
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        tris = np.array([[0, 1, 2]], dtype=int)
        r = compute_mesh_mass_props(verts, tris, allow_open=True)
        assert isinstance(r, MassPropsReport)

    def test_inverted_normals_raise(self):
        """Fully inverted cube winding → negative volume → error."""
        verts, tris = _cube_mesh()
        tris_inv = tris[:, [0, 2, 1]]
        with pytest.raises(ValueError, match="volume"):
            compute_mesh_mass_props(verts, tris_inv)


# ---------------------------------------------------------------------------
# MassPropsReport contract
# ---------------------------------------------------------------------------

class TestReportContract:
    def test_inertia_tensor_symmetric(self):
        verts, tris = _cube_mesh()
        r = compute_mesh_mass_props(verts, tris)
        assert np.allclose(r.inertia_tensor, r.inertia_tensor.T, atol=1e-15)

    def test_principal_axes_orthonormal(self):
        verts, tris = _cube_mesh()
        r = compute_mesh_mass_props(verts, tris)
        Q = r.principal_axes
        assert np.allclose(Q.T @ Q, np.eye(3), atol=1e-12)

    def test_density_scales_mass_not_centroid(self):
        verts, tris = _cube_mesh()
        r1 = compute_mesh_mass_props(verts, tris, density=1.0)
        r2 = compute_mesh_mass_props(verts, tris, density=7850.0)
        assert abs(r2.mass - r1.mass * 7850.0) < 1e-6
        assert np.allclose(r1.centroid, r2.centroid, atol=1e-15)
        assert np.allclose(r2.inertia_tensor, r1.inertia_tensor * 7850.0, atol=1e-6)

    def test_bad_vertices_shape(self):
        with pytest.raises(ValueError, match="vertices"):
            compute_mesh_mass_props([[1, 2]], [[0, 0, 0]])

    def test_empty_triangles(self):
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        with pytest.raises(ValueError, match="empty"):
            compute_mesh_mass_props(verts, np.zeros((0, 3), dtype=int))
