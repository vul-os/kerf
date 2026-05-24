"""Tests for GK-P34 — Toposolid.to_brep() closed Body from TIN + cut_fill_volume.

DoD:
  - to_brep() returns a Body with is_closed=True shell
  - Body has faces: #simplices (top) + #boundary_edges*2 (sides) + #simplices (base)
  - cut_fill_volume returns correct positive/negative volumes
"""
from __future__ import annotations
import pytest

import numpy as np

pytest.importorskip("kerf_cad_core", reason="kerf_cad_core not available")

from kerf_bim.site import Toposolid, cut_fill_volume


def _flat_toposolid(size: float = 10.0, thickness: float = 1.0) -> Toposolid:
    """Flat 10×10 terrain at z=0 with 4 corner points."""
    return Toposolid(
        boundary=[(0, 0), (size, 0), (size, size), (0, size)],
        points=[(0, 0, 0), (size, 0, 0), (size, size, 0), (0, size, 0),
                (size / 2, size / 2, 0)],  # interior point for well-conditioned TIN
        thickness=thickness,
    )


def _sloped_toposolid(size: float = 10.0) -> Toposolid:
    """Simple slope: z=0 at x=0, z=2 at x=10."""
    return Toposolid(
        boundary=[(0, 0), (size, 0), (size, size), (0, size)],
        points=[
            (0, 0, 0), (size, 0, 2.0), (size, size, 2.0), (0, size, 0),
            (size / 2, size / 2, 1.0),
        ],
        thickness=1.0,
    )


class TestToposolidBrepClosed:
    def test_returns_body(self):
        ts = _flat_toposolid()
        body = ts.to_brep()
        assert body is not None

    def test_shell_is_closed(self):
        ts = _flat_toposolid()
        body = ts.to_brep()
        # Body should have a solid with an outer shell
        assert len(body.solids) >= 1
        solid = body.solids[0]
        assert len(solid.shells) >= 1
        shell = solid.shells[0]
        assert shell.is_closed, "Toposolid B-rep shell should be marked closed"

    def test_face_count_reasonable(self):
        """Face count = top_tris + side_pairs*2 + base_tris >= 3 * n_tris."""
        ts = _flat_toposolid()
        body = ts.to_brep()
        shell = body.solids[0].shells[0]
        n_faces = len(shell.faces)
        n_tris = len(ts.simplices)
        # At minimum: top + base = 2 * n_tris
        assert n_faces >= 2 * n_tris, (
            f"Expected at least {2*n_tris} faces, got {n_faces}"
        )

    def test_all_faces_have_loops(self):
        ts = _flat_toposolid()
        body = ts.to_brep()
        shell = body.solids[0].shells[0]
        for face in shell.faces:
            assert len(face.loops) >= 1

    def test_sloped_terrain_closed(self):
        ts = _sloped_toposolid()
        body = ts.to_brep()
        assert body is not None
        shell = body.solids[0].shells[0]
        assert shell.is_closed


class TestCutFillVolume:
    def test_flat_vs_flat_zero(self):
        """Identical terrains → net = 0."""
        ts = _flat_toposolid()
        result = cut_fill_volume(ts, ts)
        assert abs(result["net"]) < 1e-3

    def test_raised_terrain_is_fill(self):
        """Proposed higher than existing → fill > 0, cut = 0."""
        existing = Toposolid(
            boundary=[(0, 0), (10, 0), (10, 10), (0, 10)],
            points=[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                    (5, 5, 0)],
        )
        proposed = Toposolid(
            boundary=[(0, 0), (10, 0), (10, 10), (0, 10)],
            points=[(0, 0, 1), (10, 0, 1), (10, 10, 1), (0, 10, 1),
                    (5, 5, 1)],
        )
        result = cut_fill_volume(existing, proposed, grid_spacing=1.0)
        assert result["fill"] > 0
        assert result["cut"] < 1e-6
        assert result["net"] > 0

    def test_lowered_terrain_is_cut(self):
        """Proposed lower than existing → cut > 0, fill = 0."""
        existing = Toposolid(
            boundary=[(0, 0), (10, 0), (10, 10), (0, 10)],
            points=[(0, 0, 1), (10, 0, 1), (10, 10, 1), (0, 10, 1),
                    (5, 5, 1)],
        )
        proposed = Toposolid(
            boundary=[(0, 0), (10, 0), (10, 10), (0, 10)],
            points=[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                    (5, 5, 0)],
        )
        result = cut_fill_volume(existing, proposed, grid_spacing=1.0)
        assert result["cut"] > 0
        assert result["fill"] < 1e-6
        assert result["net"] < 0

    def test_net_equals_fill_minus_cut(self):
        ts_a = _flat_toposolid()
        ts_b = _sloped_toposolid()
        result = cut_fill_volume(ts_a, ts_b)
        assert abs(result["net"] - (result["fill"] - result["cut"])) < 1e-9

    def test_invalid_grid_spacing_raises(self):
        ts = _flat_toposolid()
        with pytest.raises(ValueError):
            cut_fill_volume(ts, ts, grid_spacing=0.0)
