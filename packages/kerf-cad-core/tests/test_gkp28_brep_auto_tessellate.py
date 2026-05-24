"""Tests for GK-P28 — B-rep → 2D auto-tessellate (brep_to_make2d_input).

DoD: a B-rep solid yields a hidden-line drawing with no part["mesh"]
(i.e. brep_to_make2d_input + make2d_from_brep work without caller-supplied mesh).
"""
from __future__ import annotations
import pytest

pytest.importorskip("kerf_cad_core", reason="kerf_cad_core not available")

import numpy as np
from kerf_cad_core.geom.make2d import (
    brep_to_make2d_input,
    make2d_from_brep,
    Make2DInput,
    Make2DResult,
    ViewParams,
    standard_views,
    make2d,
)
from kerf_cad_core.geom.brep import (
    Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane,
)


def _make_brep_box(sx=2.0, sy=1.0, sz=0.5) -> Body:
    """Build a B-rep box manually (6 faces, 12 triangles)."""
    def _face(pts, orientation=True):
        """Triangular or quad planar face."""
        n = len(pts)
        vertices = [Vertex(p) for p in pts]
        coedges = []
        for i in range(n):
            p0, p1 = pts[i], pts[(i + 1) % n]
            v0, v1 = vertices[i], vertices[(i + 1) % n]
            line = Line3(p0=p0, p1=p1)
            edge = Edge(curve=line, t0=0.0, t1=1.0, v_start=v0, v_end=v1)
            coedges.append(Coedge(edge=edge, orientation=True))
        loop = Loop(coedges=coedges, is_outer=True)
        x_ax = pts[1] - pts[0]
        n_x = np.linalg.norm(x_ax)
        if n_x > 1e-14:
            x_ax = x_ax / n_x
        y_ax = pts[2] - pts[0]
        surf = Plane(origin=pts[0], x_axis=x_ax, y_axis=y_ax)
        return Face(surface=surf, loops=[loop], orientation=orientation)

    x, y, z = sx, sy, sz
    p000 = np.array([0, 0, 0], dtype=float)
    p100 = np.array([x, 0, 0], dtype=float)
    p110 = np.array([x, y, 0], dtype=float)
    p010 = np.array([0, y, 0], dtype=float)
    p001 = np.array([0, 0, z], dtype=float)
    p101 = np.array([x, 0, z], dtype=float)
    p111 = np.array([x, y, z], dtype=float)
    p011 = np.array([0, y, z], dtype=float)

    # 6 faces (each as a quad = 4-point loop)
    faces = [
        _face([p000, p100, p110, p010]),   # bottom
        _face([p001, p011, p111, p101]),   # top
        _face([p000, p001, p101, p100]),   # front
        _face([p110, p111, p011, p010]),   # back
        _face([p000, p010, p011, p001]),   # left
        _face([p100, p101, p111, p110]),   # right
    ]
    shell = Shell(faces=faces, is_closed=True)
    return Body(solids=[Solid(shells=[shell])])


class TestBrepToMake2DInput:
    def test_returns_make2d_input(self):
        body = _make_brep_box()
        mesh_input = brep_to_make2d_input(body)
        assert isinstance(mesh_input, Make2DInput)

    def test_vertices_non_empty(self):
        body = _make_brep_box()
        mesh_input = brep_to_make2d_input(body)
        assert mesh_input.vertices.shape[0] > 0

    def test_triangles_non_empty(self):
        body = _make_brep_box()
        mesh_input = brep_to_make2d_input(body)
        assert mesh_input.triangles.shape[0] > 0

    def test_input_is_valid(self):
        body = _make_brep_box()
        mesh_input = brep_to_make2d_input(body)
        valid, reason = mesh_input.is_valid()
        assert valid, f"Make2DInput invalid: {reason}"

    def test_triangle_indices_in_range(self):
        body = _make_brep_box()
        mesh_input = brep_to_make2d_input(body)
        n_verts = mesh_input.vertices.shape[0]
        assert mesh_input.triangles.max() < n_verts
        assert mesh_input.triangles.min() >= 0


class TestMake2dFromBrep:
    def test_returns_make2d_result(self):
        body = _make_brep_box()
        result = make2d_from_brep(body)
        assert isinstance(result, Make2DResult)

    def test_no_part_mesh_required(self):
        """The whole point: body → drawing without part['mesh']."""
        body = _make_brep_box(sx=5.0, sy=3.0, sz=2.0)
        result = make2d_from_brep(body)
        # Should have visible edges (silhouette / feature lines)
        assert isinstance(result.visible, list)
        assert isinstance(result.hidden, list)

    def test_visible_or_hidden_not_both_empty(self):
        body = _make_brep_box(sx=2.0, sy=2.0, sz=1.0)
        result = make2d_from_brep(body)
        total = len(result.visible) + len(result.hidden)
        assert total > 0, "Expected at least some visible or hidden lines"

    def test_custom_view(self):
        body = _make_brep_box()
        views = standard_views()
        for view_name in ("top", "front", "right", "iso"):
            result = make2d_from_brep(body, view=views[view_name])
            assert isinstance(result, Make2DResult)

    def test_empty_body_raises(self):
        body = Body(solids=[], shells=[])
        with pytest.raises(ValueError):
            brep_to_make2d_input(body)

    def test_output_coordinates_are_2d(self):
        body = _make_brep_box()
        result = make2d_from_brep(body)
        for pl in result.visible + result.hidden:
            for pt in pl:
                assert len(pt) == 2, f"Expected 2D point, got {len(pt)}D: {pt}"
