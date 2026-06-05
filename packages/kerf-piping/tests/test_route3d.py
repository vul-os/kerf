"""
Tests for kerf_piping.route3d — 3D intelligent piping route + ASME component catalogue.

DoD assertions:
  1. Route with a 90° direction change inserts an elbow.
  2. Total pipe length = sum of orthogonal run lengths.
  3. Routing around an obstacle increases total length vs straight.
  4. ASME B16.9 catalogue elbow centre-to-face matches known B16.9 values.
  5. BOM aggregates fittings correctly.
  6. Catalogue components expose correct port geometry.
  7. Tool functions (async) return valid JSON.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

# Path bootstrap
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_piping.pid import Point3
from kerf_piping.route3d import (
    AABB,
    Route3DResult,
    CatalogueComponent,
    ComponentType,
    route_3d,
    catalogue_component,
    aggregate_bom,
)
from kerf_piping.b16_catalogue import _LR_ELBOW_A_MM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeCtx:
    pass


# ===========================================================================
# AABB
# ===========================================================================

class TestAABB:
    def test_contains_point_inside(self):
        box = AABB((0, 0, 0), (2, 2, 2))
        assert box.contains_point(Point3(1, 1, 1))

    def test_contains_point_outside(self):
        box = AABB((0, 0, 0), (2, 2, 2))
        assert not box.contains_point(Point3(3, 1, 1))

    def test_contains_point_with_clearance(self):
        box = AABB((0, 0, 0), (2, 2, 2))
        # Point at 2.1,1,1 is outside without clearance but inside with 0.2
        assert not box.contains_point(Point3(2.1, 1.0, 1.0), clearance=0.0)
        assert box.contains_point(Point3(2.1, 1.0, 1.0), clearance=0.2)

    def test_intersects_segment_crossing(self):
        box = AABB((1, 0, 0), (3, 2, 2))
        a = Point3(0, 1, 1)
        b = Point3(4, 1, 1)
        assert box.intersects_segment(a, b)

    def test_intersects_segment_no_hit(self):
        box = AABB((10, 10, 10), (12, 12, 12))
        a = Point3(0, 0, 0)
        b = Point3(0, 0, 5)
        assert not box.intersects_segment(a, b)


# ===========================================================================
# route_3d — DoD assertion 1: elbow at 90° turn
# ===========================================================================

class TestRoute3D:
    def test_elbow_at_90_turn(self):
        """DoD 1: Route with direction change inserts at least one 90° elbow."""
        result = route_3d(
            Point3(0, 0, 0),
            Point3(5, 0, 3),   # Z then X → L-shape
            dn=50,
        )
        assert isinstance(result, Route3DResult)
        assert result.elbows_90 >= 1, (
            f"Expected ≥1 elbow for L-shaped route, got {result.elbows_90}"
        )

    def test_straight_route_no_elbows(self):
        """Straight Z run → 0 elbows."""
        result = route_3d(Point3(0, 0, 0), Point3(0, 0, 10), dn=50)
        assert result.elbows_90 == 0
        assert result.elbows_45 == 0

    def test_three_axis_two_elbows(self):
        """3D offset (X+Y+Z) → 2 elbows."""
        result = route_3d(
            Point3(0, 0, 0),
            Point3(5, 4, 3),
            dn=50,
        )
        assert result.elbows_90 == 2

    def test_total_length_sum_of_runs(self):
        """DoD 2: Total length = sum of orthogonal offsets (Z=3, X=4 → 7)."""
        result = route_3d(
            Point3(0, 0, 0),
            Point3(4, 0, 3),
            dn=50,
            prefer_axis="Z",
        )
        expected = 3.0 + 4.0  # Z run + X run
        assert result.total_length_m == pytest.approx(expected, abs=1e-9), (
            f"Expected total_length_m={expected}, got {result.total_length_m}"
        )

    def test_total_length_general(self):
        """Total length = |dx| + |dy| + |dz| for 3D route."""
        dx, dy, dz = 6.0, 5.0, 4.0
        result = route_3d(
            Point3(0, 0, 0),
            Point3(dx, dy, dz),
            dn=100,
        )
        expected = dx + dy + dz
        assert result.total_length_m == pytest.approx(expected, abs=1e-9)

    def test_obstacle_increases_length(self):
        """DoD 3: Routing around an obstacle increases total length vs straight."""
        # Straight route from (0,0,0) to (10,0,0) = 10 m
        start = Point3(0.0, 0.0, 0.0)
        end   = Point3(10.0, 0.0, 0.0)
        direct = route_3d(start, end, dn=50, prefer_axis="X")
        direct_len = direct.total_length_m

        # Place an obstacle directly in the path
        obs = AABB(min_pt=(3.0, -1.0, -1.0), max_pt=(7.0, 1.0, 1.0), label="tank")
        detoured = route_3d(
            start, end, dn=50, prefer_axis="X",
            obstacles=[obs], clearance_m=0.5,
        )
        detoured_len = detoured.total_length_m

        assert detoured_len > direct_len, (
            f"Detoured route ({detoured_len:.3f} m) should be longer than direct "
            f"({direct_len:.3f} m) when obstacle is in path"
        )
        assert detoured.clashes_avoided >= 1, (
            "clashes_avoided should be ≥1 when an obstacle is bypassed"
        )

    def test_centerline_starts_at_start(self):
        result = route_3d(Point3(1, 2, 3), Point3(4, 5, 6), dn=50)
        assert len(result.centerline) >= 2
        assert result.centerline[0] == pytest.approx([1.0, 2.0, 3.0], abs=1e-9)

    def test_centerline_ends_at_end(self):
        result = route_3d(Point3(0, 0, 0), Point3(3, 4, 5), dn=50)
        assert result.centerline[-1] == pytest.approx([3.0, 4.0, 5.0], abs=1e-9)

    def test_bom_has_pipe_entry(self):
        result = route_3d(Point3(0, 0, 0), Point3(3, 0, 4), dn=100)
        types = [b["item"] for b in result.bom]
        assert "straight_pipe" in types

    def test_bom_has_elbow_entry(self):
        result = route_3d(Point3(0, 0, 0), Point3(3, 0, 4), dn=50)
        types = [b["item"] for b in result.bom]
        assert "90lr_elbow" in types

    def test_spec_driven_schedule(self):
        """Spec CS-A should select Sch 40 for DN50."""
        from kerf_piping.pipe_spec import standard_class_cs_a
        spec = standard_class_cs_a()
        result = route_3d(Point3(0, 0, 0), Point3(0, 0, 5), dn=50, spec=spec)
        assert result.schedule == "40"

    def test_as_dict_keys(self):
        result = route_3d(Point3(0, 0, 0), Point3(3, 4, 5), dn=50)
        d = result.as_dict()
        for key in ["segment_count", "elbows_90", "total_length_m", "bom", "centerline"]:
            assert key in d, f"Missing key: {key}"

    def test_elbow_radius_positive(self):
        """Elbow radius must be positive (ASME B16.9 LR = 1.5D)."""
        result = route_3d(Point3(0, 0, 0), Point3(5, 0, 3), dn=100)
        assert result.elbow_radius_mm > 0
        # LR ≈ 1.5 × (DN/2) = 1.5 × 50 = 75 mm for DN100 (r ≈ radius not OD)
        assert result.elbow_radius_mm == pytest.approx(152.0, abs=1.0)

    def test_no_obstacle_no_detour(self):
        """No obstacles → clashes_avoided == 0."""
        result = route_3d(Point3(0, 0, 0), Point3(5, 0, 3), dn=50)
        assert result.clashes_avoided == 0


# ===========================================================================
# catalogue_component — DoD assertion 4: B16.9 elbow C-to-F dimensions
# ===========================================================================

class TestCatalogueComponent:
    def test_90lr_elbow_dn100_center_to_face(self):
        """DoD 4: ASME B16.9 LR elbow DN100 A=152 mm."""
        comp = catalogue_component("elbow_90_lr", 100)
        # B16.9 Table 1: DN100 (NPS 4") A = 152 mm
        assert comp.center_to_face_mm == pytest.approx(152.0, abs=1.0), (
            f"DN100 LR elbow: expected A=152 mm, got {comp.center_to_face_mm}"
        )

    def test_90lr_elbow_dn50_center_to_face(self):
        """ASME B16.9 LR elbow DN50 (NPS 2") A = 76 mm."""
        comp = catalogue_component("elbow_90_lr", 50)
        assert comp.center_to_face_mm == pytest.approx(76.0, abs=1.0)

    def test_90lr_elbow_dn150_center_to_face(self):
        """ASME B16.9 LR elbow DN150 (NPS 6") A = 229 mm."""
        comp = catalogue_component("elbow_90_lr", 150)
        assert comp.center_to_face_mm == pytest.approx(229.0, abs=1.0)

    def test_90lr_elbow_dn200(self):
        """ASME B16.9 LR elbow DN200 (NPS 8") A = 305 mm."""
        comp = catalogue_component("elbow_90_lr", 200)
        assert comp.center_to_face_mm == pytest.approx(305.0, abs=1.0)

    def test_90lr_has_two_ports(self):
        comp = catalogue_component("elbow_90_lr", 100)
        assert len(comp.ports) == 2
        labels = {p.label for p in comp.ports}
        assert "in" in labels
        assert "out" in labels

    def test_90sr_elbow_dn100(self):
        """ASME B16.9 SR elbow DN100 A = 102 mm."""
        comp = catalogue_component("elbow_90_sr", 100)
        assert comp.center_to_face_mm == pytest.approx(102.0, abs=1.0)

    def test_45lr_elbow_dn100(self):
        """ASME B16.9 45° LR elbow DN100 A = 102 mm."""
        comp = catalogue_component("elbow_45_lr", 100)
        assert comp.center_to_face_mm == pytest.approx(102.0, abs=1.0)

    def test_tee_equal_dn100(self):
        comp = catalogue_component("tee_equal", 100)
        assert len(comp.ports) == 3
        labels = {p.label for p in comp.ports}
        assert "branch" in labels

    def test_reducer_concentric_dn100_50(self):
        comp = catalogue_component("reducer_concentric", 100, dn_branch=50)
        # ASME B16.9: H = 127 mm for DN100 reducer
        assert comp.face_to_face_mm == pytest.approx(127.0, abs=1.0)
        assert len(comp.ports) == 2

    def test_flange_weldneck_class150_dn100(self):
        comp = catalogue_component("flange_weldneck", 100, flange_class=150)
        assert comp.standard == "ASME B16.5-2017"
        assert comp.face_to_face_mm > 0

    def test_valve_gate_dn100_ftf(self):
        comp = catalogue_component("valve_gate", 100)
        # ASME B16.10 Table 1: DN100 gate valve F-to-F = 229 mm
        assert comp.face_to_face_mm == pytest.approx(229.0, abs=1.0)

    def test_valve_ball_dn100_ftf(self):
        comp = catalogue_component("valve_ball", 100)
        assert comp.face_to_face_mm == pytest.approx(152.0, abs=1.0)

    def test_cap_dn100(self):
        comp = catalogue_component("cap", 100)
        # ASME B16.9: E = 102 mm for DN100 cap
        assert comp.face_to_face_mm == pytest.approx(102.0, abs=1.0)

    def test_cap_dn50(self):
        comp = catalogue_component("cap", 50)
        # ASME B16.9: E = 67 mm for DN50 cap
        assert comp.face_to_face_mm == pytest.approx(67.0, abs=1.0)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown component type"):
            catalogue_component("xyz_widget", 100)

    def test_as_dict_keys(self):
        comp = catalogue_component("elbow_90_lr", 100)
        d = comp.as_dict()
        for k in ["component_type", "dn", "od_mm", "center_to_face_mm",
                  "face_to_face_mm", "standard", "notes", "ports"]:
            assert k in d, f"Missing key: {k}"

    def test_bom_line(self):
        comp = catalogue_component("90lr_elbow" if False else "elbow_90_lr", 100)
        bom = comp.bom_line(quantity=3)
        assert bom["quantity"] == 3
        assert bom["dn"] == 100

    def test_od_mm_from_b36_10m(self):
        """OD from ASME B36.10M: DN100 = 114.300 mm."""
        comp = catalogue_component("elbow_90_lr", 100)
        assert comp.od_mm == pytest.approx(114.300, abs=0.001)

    def test_standard_reference(self):
        comp = catalogue_component("elbow_90_lr", 100)
        assert "B16.9" in comp.standard

    def test_all_component_types_instantiate(self):
        """All component types should instantiate without error."""
        for ct in ComponentType:
            if ct == ComponentType.REDUCER_CONC:
                comp = catalogue_component(ct.value, 100, dn_branch=50)
            elif ct == ComponentType.FLANGE_WN:
                comp = catalogue_component(ct.value, 100, flange_class=150)
            else:
                comp = catalogue_component(ct.value, 100)
            assert comp is not None


# ===========================================================================
# aggregate_bom — DoD assertion 5
# ===========================================================================

class TestAggregateBOM:
    def test_bom_aggregates_same_type(self):
        """DoD 5: BOM aggregates identical fittings."""
        comp_a = catalogue_component("elbow_90_lr", 100)
        comp_b = catalogue_component("elbow_90_lr", 100)
        bom = aggregate_bom([(comp_a, 2), (comp_b, 3)])
        assert len(bom) == 1
        assert bom[0]["quantity"] == 5

    def test_bom_separates_different_types(self):
        """Different types stay separate in BOM."""
        comp_elbow = catalogue_component("elbow_90_lr", 100)
        comp_tee   = catalogue_component("tee_equal", 100)
        bom = aggregate_bom([(comp_elbow, 2), (comp_tee, 1)])
        assert len(bom) == 2
        qtys = {b["item"]: b["quantity"] for b in bom}
        assert qtys["elbow_90_lr"] == 2
        assert qtys["tee_equal"] == 1

    def test_bom_separates_different_dn(self):
        """Same type, different DN → separate BOM lines."""
        comp_50 = catalogue_component("elbow_90_lr", 50)
        comp_100 = catalogue_component("elbow_90_lr", 100)
        bom = aggregate_bom([(comp_50, 1), (comp_100, 1)])
        assert len(bom) == 2

    def test_bom_empty(self):
        bom = aggregate_bom([])
        assert bom == []


# ===========================================================================
# Tool functions — async JSON payloads
# ===========================================================================

class TestPipingRoute3DTool:
    def test_basic_l_shape(self):
        from kerf_piping.tools import run_piping_route_3d
        args = {
            "start": [0.0, 0.0, 0.0],
            "end":   [5.0, 0.0, 3.0],
            "dn":    50,
            "prefer_axis": "Z",
        }
        result = _run(run_piping_route_3d(args, FakeCtx()))
        data = json.loads(result)
        assert data.get("ok") is True
        assert "elbows_90" in data
        assert data["elbows_90"] >= 1

    def test_straight_route(self):
        from kerf_piping.tools import run_piping_route_3d
        args = {"start": [0.0, 0.0, 0.0], "end": [0.0, 0.0, 10.0], "dn": 100}
        result = _run(run_piping_route_3d(args, FakeCtx()))
        data = json.loads(result)
        assert data["elbows_90"] == 0
        assert data["total_length_m"] == pytest.approx(10.0)

    def test_with_obstacle(self):
        from kerf_piping.tools import run_piping_route_3d
        args = {
            "start": [0.0, 0.0, 0.0],
            "end":   [10.0, 0.0, 0.0],
            "dn":    50,
            "prefer_axis": "X",
            "obstacles": [
                {"min": [3.0, -1.0, -1.0], "max": [7.0, 1.0, 1.0], "label": "vessel"},
            ],
            "clearance_m": 0.5,
        }
        result = _run(run_piping_route_3d(args, FakeCtx()))
        data = json.loads(result)
        assert data.get("ok") is True
        # With obstacle the route should be longer than 10 m
        assert data["total_length_m"] > 10.0

    def test_spec_driven(self):
        from kerf_piping.tools import run_piping_route_3d
        args = {
            "start": [0.0, 0.0, 0.0],
            "end":   [0.0, 0.0, 5.0],
            "dn":    50,
            "pipe_spec": "CS-A",
        }
        result = _run(run_piping_route_3d(args, FakeCtx()))
        data = json.loads(result)
        assert data.get("ok") is True
        assert data["schedule"] == "40"

    def test_bom_in_payload(self):
        from kerf_piping.tools import run_piping_route_3d
        args = {
            "start": [0.0, 0.0, 0.0],
            "end":   [3.0, 0.0, 4.0],
            "dn":    100,
        }
        result = _run(run_piping_route_3d(args, FakeCtx()))
        data = json.loads(result)
        assert "bom" in data
        assert isinstance(data["bom"], list)

    def test_centerline_in_payload(self):
        from kerf_piping.tools import run_piping_route_3d
        args = {"start": [1.0, 2.0, 3.0], "end": [4.0, 5.0, 6.0], "dn": 50}
        result = _run(run_piping_route_3d(args, FakeCtx()))
        data = json.loads(result)
        assert "centerline" in data
        assert len(data["centerline"]) >= 2


class TestPipingCatalogueTool:
    def test_elbow_90lr_dn100(self):
        from kerf_piping.tools import run_piping_catalogue_component
        args = {"component_type": "elbow_90_lr", "dn": 100}
        result = _run(run_piping_catalogue_component(args, FakeCtx()))
        data = json.loads(result)
        assert data.get("ok") is True
        assert data["center_to_face_mm"] == pytest.approx(152.0, abs=1.0)
        assert "ports" in data
        assert "bom_line" in data

    def test_reducer_dn200_dn100(self):
        from kerf_piping.tools import run_piping_catalogue_component
        args = {
            "component_type": "reducer_concentric",
            "dn": 200,
            "dn_branch": 100,
        }
        result = _run(run_piping_catalogue_component(args, FakeCtx()))
        data = json.loads(result)
        assert data.get("ok") is True
        # ASME B16.9: H = 203 mm for DN200 reducer
        assert data["face_to_face_mm"] == pytest.approx(203.0, abs=1.0)

    def test_flange_class150_dn100(self):
        from kerf_piping.tools import run_piping_catalogue_component
        args = {
            "component_type": "flange_weldneck",
            "dn": 100,
            "flange_class": 150,
        }
        result = _run(run_piping_catalogue_component(args, FakeCtx()))
        data = json.loads(result)
        assert data.get("ok") is True
        assert "B16.5" in data.get("standard", "")

    def test_unknown_type_error(self):
        from kerf_piping.tools import run_piping_catalogue_component
        args = {"component_type": "magic_pipe", "dn": 100}
        result = _run(run_piping_catalogue_component(args, FakeCtx()))
        data = json.loads(result)
        assert "error" in data

    def test_bom_line_quantity(self):
        from kerf_piping.tools import run_piping_catalogue_component
        args = {"component_type": "elbow_90_lr", "dn": 50, "quantity": 4}
        result = _run(run_piping_catalogue_component(args, FakeCtx()))
        data = json.loads(result)
        assert data.get("ok") is True
        assert data["bom_line"]["quantity"] == 4


# ===========================================================================
# Module smoke tests
# ===========================================================================

class TestModuleImports:
    def test_route3d_imports(self):
        import kerf_piping.route3d  # noqa: F401

    def test_plugin_imports_new_tools(self):
        import kerf_piping.plugin  # noqa: F401
