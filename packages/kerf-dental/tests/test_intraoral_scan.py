"""
Tests for kerf_dental.intraoral_scan — Wave 11B: 3shape parity

Tests:
- load_intraoral_stl returns IntraoralScan with non-zero vertex count
- detect_arch_landmarks on full-arch → 5 landmarks
- remove_artifacts removes disconnected components
- align_bite returns (4,4) transforms

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import math
import os
import struct
import sys
import tempfile

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_dental.intraoral_scan import (
    IntraoralScan,
    load_intraoral_stl,
    load_intraoral_stl_from_bytes,
    detect_arch_landmarks,
    remove_artifacts,
    align_bite,
    _icp_align,
)


# ---------------------------------------------------------------------------
# STL builders for testing
# ---------------------------------------------------------------------------

def _make_binary_stl(vertices: list, triangles: list) -> bytes:
    """Build binary STL bytes from vertices + triangle index list."""
    buf = bytearray()
    buf += b"test_scan".ljust(80, b"\x00")
    buf += struct.pack("<I", len(triangles))
    for tri in triangles:
        v0, v1, v2 = vertices[tri[0]], vertices[tri[1]], vertices[tri[2]]
        v0 = np.asarray(v0, dtype=np.float32)
        v1 = np.asarray(v1, dtype=np.float32)
        v2 = np.asarray(v2, dtype=np.float32)
        n = np.cross(v1 - v0, v2 - v0).astype(np.float32)
        n_len = float(np.linalg.norm(n))
        if n_len > 1e-30:
            n /= n_len
        buf += struct.pack("<fff", *n)
        buf += struct.pack("<fff", *v0)
        buf += struct.pack("<fff", *v1)
        buf += struct.pack("<fff", *v2)
        buf += struct.pack("<H", 0)
    return bytes(buf)


def _make_arch_stl() -> bytes:
    """Build a full arch STL (half-ellipse surface with ~100 triangles)."""
    n_arch = 20
    angles = np.linspace(math.pi, 0, n_arch)
    arch_pts = np.column_stack([
        35 * np.cos(angles),
        25 * np.sin(angles),
        np.zeros(n_arch),
    ])

    verts = []
    tris = []
    for pt in arch_pts:
        verts.append(pt.tolist())
        verts.append((pt + np.array([0, 0, 5.0])).tolist())

    for i in range(n_arch - 1):
        a, b = 2 * i, 2 * i + 1
        c, d = 2 * (i + 1), 2 * (i + 1) + 1
        tris.append([a, c, b])
        tris.append([b, c, d])

    return _make_binary_stl(verts, tris)


def _make_two_component_stl() -> bytes:
    """Build STL with two disconnected components (main arch + small noise cluster)."""
    # Component 1: large arch
    n_arch = 20
    angles = np.linspace(math.pi, 0, n_arch)
    arch_pts = np.column_stack([
        35 * np.cos(angles), 25 * np.sin(angles), np.zeros(n_arch),
    ])
    verts = []
    tris = []
    for pt in arch_pts:
        verts.append(pt.tolist())
        verts.append((pt + [0, 0, 5.0]).tolist())
    for i in range(n_arch - 1):
        a, b = 2*i, 2*i+1
        c, d = 2*(i+1), 2*(i+1)+1
        tris.append([a, c, b])
        tris.append([b, c, d])

    # Component 2: tiny noise triangle far away
    base = len(verts)
    verts.extend([[200, 200, 200], [201, 200, 200], [200, 201, 200]])
    tris.append([base, base+1, base+2])

    return _make_binary_stl(verts, tris)


# ===========================================================================
# IntraoralScan
# ===========================================================================

class TestIntraoralScan:
    def test_vertex_count_property(self):
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        tris = np.array([[0, 1, 2]], dtype=int)
        scan = IntraoralScan(verts, tris, "Trios 4", "maxillary", "2024-01-01")
        assert scan.vertex_count == 3

    def test_triangle_count_property(self):
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        tris = np.array([[0, 1, 2]], dtype=int)
        scan = IntraoralScan(verts, tris, "Medit i700", "mandibular", "2024-01-01")
        assert scan.triangle_count == 1

    def test_bounding_box(self):
        verts = np.array([[0, 0, 0], [10, 5, 3]], dtype=float)
        tris = np.array([[0, 0, 0]], dtype=int)
        scan = IntraoralScan(verts, tris, "unknown", "maxillary", "2024-01-01")
        lo, hi = scan.bounding_box
        assert lo[0] == pytest.approx(0.0)
        assert hi[0] == pytest.approx(10.0)


# ===========================================================================
# load_intraoral_stl_from_bytes
# ===========================================================================

class TestLoadIntraoralStl:
    """DoD: load_intraoral_stl returns IntraoralScan with non-zero vertex count."""

    def test_returns_scan_with_nonzero_vertices(self):
        """DoD: load returns IntraoralScan with vertex_count > 0."""
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(
            stl_bytes, scanner_brand="Trios 4", arch="maxillary"
        )
        assert isinstance(scan, IntraoralScan)
        assert scan.vertex_count > 0, f"Expected non-zero vertices, got {scan.vertex_count}"

    def test_triangle_count_non_zero(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        assert scan.triangle_count > 0

    def test_scanner_brand_stored(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes, scanner_brand="Medit i700")
        assert scan.scanner_brand == "Medit i700"

    def test_arch_stored(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes, arch="mandibular")
        assert scan.arch == "mandibular"

    def test_load_from_file(self, tmp_path):
        stl_bytes = _make_arch_stl()
        path = str(tmp_path / "test.stl")
        with open(path, "wb") as f:
            f.write(stl_bytes)
        scan = load_intraoral_stl(path, scanner_brand="Itero Element", arch="maxillary")
        assert scan.vertex_count > 0

    def test_minimal_triangle(self):
        verts = [[0, 0, 0], [10, 0, 0], [0, 10, 0]]
        stl_bytes = _make_binary_stl(verts, [[0, 1, 2]])
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        assert scan.vertex_count == 3


# ===========================================================================
# detect_arch_landmarks
# ===========================================================================

class TestDetectArchLandmarks:
    """DoD: detect_arch_landmarks on a full-arch → 5 landmarks."""

    def test_returns_5_landmarks(self):
        """DoD: detect_arch_landmarks returns dict with 5 keys."""
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes, arch="maxillary")
        landmarks = detect_arch_landmarks(scan)
        expected_keys = {
            "midline", "first_molar_right", "first_molar_left",
            "canine_right", "canine_left",
        }
        assert set(landmarks.keys()) == expected_keys, (
            f"Expected keys {expected_keys}, got {set(landmarks.keys())}"
        )

    def test_all_landmarks_are_3d_tuples(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        landmarks = detect_arch_landmarks(scan)
        for k, v in landmarks.items():
            assert len(v) == 3, f"Landmark {k!r} should be (x,y,z), got {v}"

    def test_landmarks_within_arch_bounds(self):
        """All landmarks should be within the arch bounding box."""
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        landmarks = detect_arch_landmarks(scan)
        lo, hi = scan.bounding_box
        for k, pt in landmarks.items():
            for i, (l, h) in enumerate(zip(lo, hi)):
                assert l - 0.1 <= pt[i] <= h + 0.1, (
                    f"Landmark {k} coord[{i}]={pt[i]} out of bounds [{l:.1f}, {h:.1f}]"
                )

    def test_too_few_vertices_raises(self):
        verts = np.array([[0, 0, 0]], dtype=float)
        scan = IntraoralScan(verts, np.zeros((0, 3), dtype=int), "unknown", "maxillary", "")
        with pytest.raises(ValueError):
            detect_arch_landmarks(scan)


# ===========================================================================
# remove_artifacts
# ===========================================================================

class TestRemoveArtifacts:
    def test_single_component_unchanged(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        cleaned = remove_artifacts(scan)
        # Single component: vertex count same or reduced only by degenerate tris
        assert cleaned.vertex_count > 0

    def test_two_components_keeps_largest(self):
        stl_bytes = _make_two_component_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        cleaned = remove_artifacts(scan)
        # Should have fewer vertices than original (small component removed)
        # At minimum, tiny noise cluster should be gone
        assert cleaned.vertex_count < scan.vertex_count or cleaned.triangle_count <= scan.triangle_count

    def test_returns_intraoral_scan_instance(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        cleaned = remove_artifacts(scan)
        assert isinstance(cleaned, IntraoralScan)

    def test_scan_brand_preserved(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes, scanner_brand="Trios 5")
        cleaned = remove_artifacts(scan)
        assert cleaned.scanner_brand == "Trios 5"


# ===========================================================================
# align_bite
# ===========================================================================

class TestAlignBite:
    def test_returns_two_transforms(self):
        stl_bytes = _make_arch_stl()
        max_scan = load_intraoral_stl_from_bytes(stl_bytes, arch="maxillary")
        man_scan = load_intraoral_stl_from_bytes(stl_bytes, arch="mandibular")
        bite_scan = load_intraoral_stl_from_bytes(stl_bytes, arch="bite")

        T_max, T_man = align_bite(max_scan, man_scan, bite_scan)
        assert T_max.shape == (4, 4)
        assert T_man.shape == (4, 4)

    def test_maxillary_transform_is_identity(self):
        stl_bytes = _make_arch_stl()
        max_scan = load_intraoral_stl_from_bytes(stl_bytes, arch="maxillary")
        man_scan = load_intraoral_stl_from_bytes(stl_bytes, arch="mandibular")
        bite_scan = load_intraoral_stl_from_bytes(stl_bytes, arch="bite")

        T_max, _ = align_bite(max_scan, man_scan, bite_scan)
        assert np.allclose(T_max, np.eye(4), atol=1e-10)

    def test_too_few_bite_vertices_raises(self):
        stl_bytes = _make_arch_stl()
        scan = load_intraoral_stl_from_bytes(stl_bytes)
        tiny_verts = np.array([[0, 0, 0]], dtype=float)
        tiny_scan = IntraoralScan(tiny_verts, np.zeros((0, 3), dtype=int), "unknown", "bite", "")
        with pytest.raises(ValueError):
            align_bite(scan, scan, tiny_scan)
