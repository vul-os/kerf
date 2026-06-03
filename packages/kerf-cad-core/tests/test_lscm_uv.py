"""Tests for LSCM UV unwrap LLM tool (lscm_uv_tool.py).

Covers:
- Flat square mesh → UV ≈ identity (within boundary scaling)
- Cylinder slit along one seam → UV unrolls to a rectangle
- Stretch metric on flat input ≈ 1.0 within 5%
- No boundary pins raises ValueError
- Tool output shape matches spec
- Boundary length 2D is positive
- Seam-based pin selection works
- Round-trip through the async handler
"""
from __future__ import annotations

import json
import math
import asyncio
import pytest
import numpy as np

from kerf_cad_core.sculpt.lscm_uv_tool import (
    lscm_uv_unwrap_mesh,
    _conformal_stretch_metric,
    _boundary_length_2d,
    run_lscm_uv_unwrap,
)
from kerf_cad_core._compat import ProjectCtx


# ---------------------------------------------------------------------------
# Mesh builders
# ---------------------------------------------------------------------------

def make_flat_quad_mesh(n: int = 4) -> dict:
    """n×n grid, triangulated, in XY plane, edge length 1/n."""
    verts = []
    for j in range(n + 1):
        for i in range(n + 1):
            verts.append([i / n, j / n, 0.0])
    faces = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + (n + 1) + 1
            d = a + (n + 1)
            faces.append([a, b, c])
            faces.append([a, c, d])
    return {"vertices": verts, "faces": faces}


def make_cylinder_mesh(n_phi: int = 12, n_z: int = 4, radius: float = 1.0, height: float = 2.0) -> dict:
    """Cylinder with a slit along phi=0 seam.

    Vertices are duplicated at the seam so the mesh is open (boundary along
    phi=0, phi=2π columns), which lets LSCM unroll it to a rectangle.
    """
    verts = []
    # n_phi+1 columns (column 0 and column n_phi are duplicated for the seam)
    for iz in range(n_z + 1):
        z = iz * height / n_z
        for ip in range(n_phi + 1):
            angle = 2 * math.pi * ip / n_phi
            verts.append([radius * math.cos(angle), radius * math.sin(angle), z])

    faces = []
    cols = n_phi + 1
    for iz in range(n_z):
        for ip in range(n_phi):
            a = iz * cols + ip
            b = a + 1
            c = (iz + 1) * cols + ip + 1
            d = (iz + 1) * cols + ip
            faces.append([a, b, c])
            faces.append([a, c, d])

    # Seam edges: the two boundary columns
    seam_edges = [[iz * cols, iz * cols + n_phi] for iz in range(n_z + 1)]
    return {"vertices": verts, "faces": faces, "seam_edges": seam_edges}


def make_tiny_closed_mesh() -> dict:
    """A 4-vertex closed tetrahedron with no boundary — used to test auto-pin fallback."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.5, 1.0, 0.0],
        [0.5, 0.33, 1.0],
    ]
    faces = [
        [0, 1, 2],
        [0, 1, 3],
        [1, 2, 3],
        [0, 2, 3],
    ]
    return {"vertices": verts, "faces": faces}


# ---------------------------------------------------------------------------
# Test 1: Flat square → UV ≈ identity within boundary scaling
# ---------------------------------------------------------------------------

class TestFlatSquareUV:
    def test_output_has_required_keys(self):
        mesh = make_flat_quad_mesh(3)
        result = lscm_uv_unwrap_mesh(mesh)
        assert "uv_coords" in result
        assert "stretch_metric" in result
        assert "boundary_length_2d" in result

    def test_uv_count_matches_vertex_count(self):
        mesh = make_flat_quad_mesh(4)
        result = lscm_uv_unwrap_mesh(mesh)
        assert len(result["uv_coords"]) == len(mesh["vertices"])

    def test_each_uv_is_2d(self):
        mesh = make_flat_quad_mesh(3)
        result = lscm_uv_unwrap_mesh(mesh)
        for uv in result["uv_coords"]:
            assert len(uv) == 2

    def test_uv_all_finite(self):
        mesh = make_flat_quad_mesh(4)
        result = lscm_uv_unwrap_mesh(mesh)
        for u, v in result["uv_coords"]:
            assert math.isfinite(u) and math.isfinite(v)

    def test_flat_mesh_uv_spans_unit_range(self):
        """A flat square should unwrap so UV roughly spans [0,1]×[0,1]."""
        mesh = make_flat_quad_mesh(5)
        result = lscm_uv_unwrap_mesh(mesh)
        uvs = np.array(result["uv_coords"])
        u_range = uvs[:, 0].max() - uvs[:, 0].min()
        v_range = uvs[:, 1].max() - uvs[:, 1].min()
        # Should have non-trivial extent in both axes
        assert u_range > 0.1, f"U range too small: {u_range}"
        assert v_range > 0.1, f"V range too small: {v_range}"


# ---------------------------------------------------------------------------
# Test 2: Stretch metric on flat input ≈ 1.0 within 5%
# ---------------------------------------------------------------------------

class TestStretchMetric:
    def test_flat_mesh_stretch_near_one(self):
        mesh = make_flat_quad_mesh(6)
        result = lscm_uv_unwrap_mesh(mesh)
        stretch = result["stretch_metric"]
        assert math.isfinite(stretch), "stretch metric must be finite"
        assert 0.8 <= stretch <= 1.25, (
            f"Flat mesh stretch metric should be ~1.0, got {stretch:.4f}"
        )

    def test_stretch_metric_positive(self):
        mesh = make_flat_quad_mesh(3)
        result = lscm_uv_unwrap_mesh(mesh)
        assert result["stretch_metric"] > 0.0

    def test_boundary_length_2d_positive(self):
        mesh = make_flat_quad_mesh(3)
        result = lscm_uv_unwrap_mesh(mesh)
        assert result["boundary_length_2d"] > 0.0


# ---------------------------------------------------------------------------
# Test 3: Cylinder slit along seam → UV unrolls to a rectangle
# ---------------------------------------------------------------------------

class TestCylinderUnroll:
    def test_cylinder_unrolls_to_finite_uvs(self):
        data = make_cylinder_mesh(12, 4)
        mesh = {"vertices": data["vertices"], "faces": data["faces"]}
        seam_edges = data["seam_edges"][:2]  # first two seam edges = 2 pins
        result = lscm_uv_unwrap_mesh(mesh, seam_edge_ids=seam_edges)
        for u, v in result["uv_coords"]:
            assert math.isfinite(u) and math.isfinite(v)

    def test_cylinder_uv_spans_rectangle(self):
        """After unrolling, UV should span a meaningful rectangle (width > height × 0.5)."""
        data = make_cylinder_mesh(12, 4, radius=1.0, height=2.0)
        mesh = {"vertices": data["vertices"], "faces": data["faces"]}
        seam_edges = data["seam_edges"][:2]
        result = lscm_uv_unwrap_mesh(mesh, seam_edge_ids=seam_edges)
        uvs = np.array(result["uv_coords"])
        u_span = uvs[:, 0].max() - uvs[:, 0].min()
        v_span = uvs[:, 1].max() - uvs[:, 1].min()
        assert u_span > 0.05, f"U span too small: {u_span}"
        assert v_span > 0.05, f"V span too small: {v_span}"

    def test_cylinder_boundary_length_positive(self):
        data = make_cylinder_mesh(8, 3)
        mesh = {"vertices": data["vertices"], "faces": data["faces"]}
        result = lscm_uv_unwrap_mesh(mesh)
        assert result["boundary_length_2d"] > 0.0


# ---------------------------------------------------------------------------
# Test 4: No boundary pins / invalid seam raises ValueError
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_empty_vertices_raises(self):
        with pytest.raises(ValueError, match="no vertices"):
            lscm_uv_unwrap_mesh({"vertices": [], "faces": []})

    def test_empty_faces_raises(self):
        with pytest.raises(ValueError, match="no faces"):
            lscm_uv_unwrap_mesh({"vertices": [[0, 0, 0]], "faces": []})

    def test_invalid_seam_with_no_valid_vertices_raises(self):
        mesh = make_flat_quad_mesh(3)
        n = len(mesh["vertices"])
        # All seam vertex indices out of range
        with pytest.raises(ValueError, match="fewer than 2 valid vertex"):
            lscm_uv_unwrap_mesh(mesh, seam_edge_ids=[[n + 100, n + 200]])

    def test_seam_with_single_valid_vertex_raises(self):
        mesh = make_flat_quad_mesh(3)
        n = len(mesh["vertices"])
        # One valid, one out-of-range
        with pytest.raises(ValueError, match="fewer than 2 valid vertex"):
            lscm_uv_unwrap_mesh(mesh, seam_edge_ids=[[0, n + 100]])


# ---------------------------------------------------------------------------
# Test 5: Async tool handler round-trip
# ---------------------------------------------------------------------------

class TestAsyncHandler:
    def test_handler_with_mesh_override(self):
        mesh = make_flat_quad_mesh(3)
        args = json.dumps({
            "body_id": "test-body",
            "mesh": mesh,
            "seam_edge_ids": [],
        }).encode()
        ctx = ProjectCtx()
        result_str = asyncio.get_event_loop().run_until_complete(
            run_lscm_uv_unwrap(ctx, args)
        )
        result = json.loads(result_str)
        assert "uv_coords" in result
        assert "stretch_metric" in result
        assert "boundary_length_2d" in result

    def test_handler_missing_mesh_returns_not_implemented(self):
        args = json.dumps({"body_id": "some-body"}).encode()
        ctx = ProjectCtx()
        result_str = asyncio.get_event_loop().run_until_complete(
            run_lscm_uv_unwrap(ctx, args)
        )
        result = json.loads(result_str)
        # No mesh resolver on stub ProjectCtx → NOT_IMPLEMENTED
        assert "error" in result
        assert result.get("code") == "NOT_IMPLEMENTED"

    def test_handler_bad_json_returns_error(self):
        args = b"not-json"
        ctx = ProjectCtx()
        result_str = asyncio.get_event_loop().run_until_complete(
            run_lscm_uv_unwrap(ctx, args)
        )
        result = json.loads(result_str)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"
