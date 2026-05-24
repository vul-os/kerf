"""Tests for GK-P35 — Corridor swept solid B-rep + volume + IfcAlignmentProduct.

DoD:
  - corridor.to_brep() returns a B-rep Body with faces
  - corridor.volume() returns a positive float
  - corridor.ifc_alignment_dict() returns IfcAlignmentProduct dict
"""
from __future__ import annotations
import math
import pytest

pytest.importorskip("kerf_cad_core", reason="kerf_cad_core not available")

from kerf_civil.horizontal_alignment import HorizontalAlignment
from kerf_civil.vertical_alignment import VerticalAlignment
from kerf_civil.corridor import TypicalSection, Corridor


def _simple_corridor(length=200.0, grade=0.0, lane_width=3.65) -> Corridor:
    ha = HorizontalAlignment()
    ha.add_tangent(length)
    va = VerticalAlignment()
    va.set_datum(elev=10.0, grade_pct=grade)
    va.add_tangent(length)
    ts = TypicalSection(lane_width=lane_width, shoulder_width=2.4, lanes_each_side=1)
    return Corridor(h_alignment=ha, v_alignment=va, typical_section=ts)


class TestCorridorBrepGeneration:
    def test_to_brep_returns_body(self):
        c = _simple_corridor()
        body = c.to_brep(interval=50.0)
        assert body is not None

    def test_body_has_shells(self):
        from kerf_cad_core.geom.brep import Body
        c = _simple_corridor()
        body = c.to_brep(interval=50.0)
        assert isinstance(body, Body)
        # Open surface body stored in shells (not solids)
        total_shells = len(body.shells) + sum(len(s.shells) for s in body.solids)
        assert total_shells >= 1

    def test_body_has_faces(self):
        c = _simple_corridor()
        body = c.to_brep(interval=50.0)
        # Collect all faces
        all_faces = []
        for shell in body.shells:
            all_faces.extend(shell.faces)
        for solid in body.solids:
            for shell in solid.shells:
                all_faces.extend(shell.faces)
        assert len(all_faces) > 0

    def test_face_count_increases_with_finer_interval(self):
        """Finer station interval → more cross-section strips → more faces."""
        c = _simple_corridor(length=200.0)
        body_coarse = c.to_brep(interval=100.0)
        body_fine   = c.to_brep(interval=25.0)

        def count_faces(b):
            n = 0
            for sh in b.shells: n += len(sh.faces)
            for sol in b.solids:
                for sh in sol.shells: n += len(sh.faces)
            return n

        assert count_faces(body_fine) > count_faces(body_coarse)

    def test_all_face_loops_have_coedges(self):
        c = _simple_corridor()
        body = c.to_brep(interval=50.0)
        for sh in body.shells:
            for face in sh.faces:
                for loop in face.loops:
                    assert len(loop.coedges) >= 3


class TestCorridorVolume:
    def test_volume_positive(self):
        c = _simple_corridor()
        vol = c.volume(interval=20.0)
        assert vol > 0.0, f"Expected positive volume, got {vol}"

    def test_volume_scales_with_length(self):
        """Longer corridor → larger volume (proportional)."""
        c1 = _simple_corridor(length=100.0)
        c2 = _simple_corridor(length=200.0)
        v1 = c1.volume(interval=20.0)
        v2 = c2.volume(interval=20.0)
        assert v2 > v1

    def test_volume_scales_with_lane_width(self):
        """Wider lane → larger volume."""
        c_narrow = _simple_corridor(lane_width=3.0)
        c_wide   = _simple_corridor(lane_width=4.5)
        v_narrow = c_narrow.volume(interval=20.0)
        v_wide   = c_wide.volume(interval=20.0)
        assert v_wide > v_narrow


class TestIfcAlignmentDict:
    def test_returns_dict_with_type(self):
        c = _simple_corridor()
        d = c.ifc_alignment_dict()
        assert d["type"] == "IfcAlignmentProduct"

    def test_total_length_matches(self):
        c = _simple_corridor(length=300.0)
        d = c.ifc_alignment_dict()
        assert abs(d["total_length_m"] - 300.0) < 1e-3

    def test_lane_width_present(self):
        c = _simple_corridor(lane_width=3.65)
        d = c.ifc_alignment_dict()
        assert abs(d["lane_width_m"] - 3.65) < 1e-6

    def test_all_expected_keys_present(self):
        c = _simple_corridor()
        d = c.ifc_alignment_dict()
        for key in ("type", "total_length_m", "lane_width_m",
                    "shoulder_width_m", "lanes_each_side",
                    "cut_slope_h_v", "fill_slope_h_v", "crown_slope_pct"):
            assert key in d, f"Missing key: {key}"
