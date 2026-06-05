"""
Tests for kerf-entertainment: lighting plot + DMX patch + rigging load analysis.

Oracle values
-------------
DMX conflict:
  Fixture A: universe 0, addr 10, footprint 3  → occupies 10-12
  Fixture B: universe 0, addr 11, footprint 2  → occupies 11-12
  → conflict at addresses 11-12

Circuit load:
  Two fixtures on dimmer 1: 575 W + 575 W = 1150 W  (< 2400 W capacity)
  Three fixtures on dimmer 2: 1000 W × 3 = 3000 W   (> 2400 W → overloaded)

Bridle leg tension (T = W / (2 cos θ)):
  W = 1000 N, spread = 4 m, height = 3.464 m
  half_h = 2 m, θ = arctan(2/3.464) ≈ 30°
  T = 1000 / (2 × cos 30°) = 1000 / (2 × 0.866) ≈ 577.4 N

  Wider angle: spread = 8 m, height = 3.464 m
  half_h = 4 m, θ = arctan(4/3.464) ≈ 49.1°
  T = 1000 / (2 × cos 49.1°) ≈ 763.8 N  (> 577.4 N — wider angle = more tension)

Hoist overload:
  Truss F34, 10 m, single mid-point load 5000 N, two equal hoists at 0 and 10 m
  Hoist capacity = 2000 N
  Reaction at each hoist = 5000/2 + (73.6×10)/2 = 2500 + 368 = 2868 N
  → both hoists overloaded (2868 > 2000)

Truss reactions balance:
  sum(reactions) ≈ total_load (self-weight + point loads)
"""

from __future__ import annotations

import math
import pytest

from kerf_entertainment.lighting_plot import (
    FixtureType, FixtureInstance,
    check_dmx_conflicts, circuit_schedule, lighting_plot_summary,
    patch_sheet, magic_sheet,
)
from kerf_entertainment.rigging import (
    TrussSegment, RiggingPoint, PointLoad,
    analyse_truss, bridle_leg_tension,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_fixture(
    fid: str,
    dmx_address: int,
    *,
    footprint: int = 1,
    universe: int = 0,
    wattage: float = 575.0,
    channel: int = 1,
    dimmer: int = 1,
    position: str = "Pipe 1",
    type_name: str = "Source Four",
) -> FixtureInstance:
    ft = FixtureType(
        type_name=type_name,
        wattage=wattage,
        dmx_footprint=footprint,
    )
    return FixtureInstance(
        fixture_id=fid,
        fixture_type=ft,
        dmx_universe=universe,
        dmx_address=dmx_address,
        channel=channel,
        dimmer=dimmer,
        position=position,
    )


# ─────────────────────────────────────────────────────────────────────────────
# DMX conflict detection
# ─────────────────────────────────────────────────────────────────────────────

class TestDmxConflicts:

    def test_overlapping_fixtures_detected(self):
        """Two fixtures with overlapping footprints in the same universe → conflict."""
        f_a = make_fixture("A", dmx_address=10, footprint=3)   # 10-12
        f_b = make_fixture("B", dmx_address=11, footprint=2)   # 11-12
        conflicts = check_dmx_conflicts([f_a, f_b])
        assert len(conflicts) == 1
        assert conflicts[0].fixture_a == "A"
        assert conflicts[0].fixture_b == "B"
        assert conflicts[0].address_range == (11, 12)

    def test_non_overlapping_no_conflict(self):
        """Adjacent but non-overlapping fixtures → no conflict."""
        f_a = make_fixture("A", dmx_address=10, footprint=3)   # 10-12
        f_b = make_fixture("B", dmx_address=13, footprint=2)   # 13-14
        assert check_dmx_conflicts([f_a, f_b]) == []

    def test_different_universes_no_conflict(self):
        """Same address range in different universes → no conflict."""
        f_a = make_fixture("A", dmx_address=10, footprint=3, universe=0)
        f_b = make_fixture("B", dmx_address=10, footprint=3, universe=1)
        assert check_dmx_conflicts([f_a, f_b]) == []

    def test_exact_same_address_conflict(self):
        """Two single-channel fixtures at the same address."""
        f_a = make_fixture("A", dmx_address=50, footprint=1)
        f_b = make_fixture("B", dmx_address=50, footprint=1)
        conflicts = check_dmx_conflicts([f_a, f_b])
        assert len(conflicts) == 1
        assert conflicts[0].address_range == (50, 50)

    def test_three_way_conflict(self):
        """Three fixtures where two pairs overlap."""
        f_a = make_fixture("A", dmx_address=1, footprint=5)   # 1-5
        f_b = make_fixture("B", dmx_address=3, footprint=5)   # 3-7
        f_c = make_fixture("C", dmx_address=6, footprint=3)   # 6-8
        conflicts = check_dmx_conflicts([f_a, f_b, f_c])
        # A-B overlap at 3-5, B-C overlap at 6-7
        assert len(conflicts) == 2

    def test_no_conflict_empty_list(self):
        assert check_dmx_conflicts([]) == []

    def test_no_conflict_single_fixture(self):
        f = make_fixture("A", dmx_address=100, footprint=4)
        assert check_dmx_conflicts([f]) == []


# ─────────────────────────────────────────────────────────────────────────────
# Circuit / dimmer schedule and load sums
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitSchedule:

    def test_circuit_load_sum(self):
        """Two fixtures on dimmer 1: total wattage = sum of individual wattages."""
        f1 = make_fixture("F1", 1, wattage=575.0, dimmer=1)
        f2 = make_fixture("F2", 2, wattage=575.0, dimmer=1)
        schedule = circuit_schedule([f1, f2], dimmer_capacity_W=2400)
        assert len(schedule) == 1
        row = schedule[0]
        assert row.dimmer == 1
        assert abs(row.total_wattage - 1150.0) < 0.01
        assert not row.overloaded

    def test_overloaded_circuit_flagged(self):
        """Three 1000 W fixtures on one dimmer (cap 2400 W) → overloaded."""
        f1 = make_fixture("F1", 1, wattage=1000.0, dimmer=2)
        f2 = make_fixture("F2", 2, wattage=1000.0, dimmer=2)
        f3 = make_fixture("F3", 3, wattage=1000.0, dimmer=2)
        schedule = circuit_schedule([f1, f2, f3], dimmer_capacity_W=2400)
        row = schedule[0]
        assert row.total_wattage == 3000.0
        assert row.overloaded
        assert row.overload_margin_W == pytest.approx(-600.0)

    def test_multiple_dimmers(self):
        """Fixtures on different dimmers produce separate rows."""
        fixtures = [
            make_fixture("F1", 1, wattage=500.0, dimmer=1),
            make_fixture("F2", 2, wattage=300.0, dimmer=1),
            make_fixture("F3", 3, wattage=800.0, dimmer=2),
        ]
        schedule = circuit_schedule(fixtures, dimmer_capacity_W=2400)
        assert len(schedule) == 2
        totals = {row.dimmer: row.total_wattage for row in schedule}
        assert totals[1] == pytest.approx(800.0)
        assert totals[2] == pytest.approx(800.0)

    def test_amperage_calculation(self):
        """Total amperage = total wattage / supply voltage."""
        f1 = make_fixture("F1", 1, wattage=1200.0, dimmer=1)
        schedule = circuit_schedule([f1], supply_voltage=120.0)
        row = schedule[0]
        assert row.total_amperage == pytest.approx(10.0)

    def test_eu_voltage(self):
        """230 V supply."""
        f1 = make_fixture("F1", 1, wattage=2300.0, dimmer=1)
        schedule = circuit_schedule([f1], supply_voltage=230.0)
        row = schedule[0]
        assert row.total_amperage == pytest.approx(10.0)

    def test_overload_summary_in_lighting_plot_summary(self):
        """lighting_plot_summary correctly lists overloaded circuits."""
        fixtures = [
            make_fixture("F1", 1, wattage=1000.0, dimmer=5),
            make_fixture("F2", 2, wattage=1000.0, dimmer=5),
            make_fixture("F3", 3, wattage=1000.0, dimmer=5),
        ]
        summary = lighting_plot_summary(fixtures, dimmer_capacity_W=2400)
        assert 5 in summary.overloaded_circuits


# ─────────────────────────────────────────────────────────────────────────────
# Patch sheet and magic sheet
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchSheet:

    def _make_rig(self):
        return [
            make_fixture("F1", 10, channel=1, dimmer=1),
            make_fixture("F2", 20, channel=2, dimmer=2),
            make_fixture("F3", 30, channel=3, dimmer=3),
        ]

    def test_patch_sheet_channel_order(self):
        rows = patch_sheet(self._make_rig(), sort_by="channel")
        channels = [r.channel for r in rows]
        assert channels == sorted(channels)

    def test_patch_sheet_dimmer_order(self):
        rows = patch_sheet(self._make_rig(), sort_by="dimmer")
        dimmers = [r.dimmer for r in rows]
        assert dimmers == sorted(dimmers)

    def test_magic_sheet_channel_sorted(self):
        ms = magic_sheet(self._make_rig())
        channels = [e.channel for e in ms]
        assert channels == sorted(channels)


# ─────────────────────────────────────────────────────────────────────────────
# Bridle leg tension
# ─────────────────────────────────────────────────────────────────────────────

class TestBridleTension:

    def test_30_degree_half_angle(self):
        """
        Symmetric bridle: spread=4m, height=2*sqrt(3)≈3.464m → θ≈30°
        T = 1000 / (2 cos 30°) ≈ 577.35 N
        """
        height = 2.0 * math.sqrt(3.0)   # ≈ 3.464 m → half_h=2, θ=30°
        br = bridle_leg_tension(1000.0, 4.0, height)
        assert br.half_angle_deg == pytest.approx(30.0, abs=0.05)
        assert br.leg_tension_N == pytest.approx(1000.0 / (2.0 * math.cos(math.radians(30.0))), rel=1e-4)

    def test_wider_angle_more_tension(self):
        """
        Wider horizontal spread → larger half-angle → higher leg tension.
        T(wide) > T(narrow) for same load and height.
        """
        load = 1000.0
        height = 3.464
        br_narrow = bridle_leg_tension(load, 4.0, height)   # θ ≈ 30°
        br_wide   = bridle_leg_tension(load, 8.0, height)   # θ ≈ 49°
        assert br_wide.leg_tension_N > br_narrow.leg_tension_N

    def test_angle_proportional_to_spread(self):
        """Half angle increases as spread increases for fixed height."""
        br_a = bridle_leg_tension(500.0, 2.0, 3.0)
        br_b = bridle_leg_tension(500.0, 4.0, 3.0)
        assert br_b.half_angle_deg > br_a.half_angle_deg

    def test_bridle_overload_flagged(self):
        """Leg tension > leg_capacity_N → overloaded=True."""
        br = bridle_leg_tension(2000.0, 6.0, 2.0, leg_capacity_N=500.0)
        assert br.overloaded

    def test_bridle_no_overload_below_capacity(self):
        """Leg tension < leg_capacity_N → overloaded=False."""
        br = bridle_leg_tension(100.0, 1.0, 10.0, leg_capacity_N=5000.0)
        assert not br.overloaded

    def test_wide_angle_warning(self):
        """Half-angle > 60° triggers ESTA E1.6 warning."""
        br = bridle_leg_tension(1000.0, 20.0, 3.0)   # very wide
        assert any("60°" in w for w in br.warnings)

    def test_formula_exactness(self):
        """T = W / (2 cos θ) holds to within floating-point precision."""
        load = 750.0
        spread = 5.0
        height = 4.0
        br = bridle_leg_tension(load, spread, height)
        half_h = spread / 2.0
        theta = math.atan2(half_h, height)
        expected_T = load / (2.0 * math.cos(theta))
        assert br.leg_tension_N == pytest.approx(expected_T, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Truss reaction analysis
# ─────────────────────────────────────────────────────────────────────────────

class TestTrussAnalysis:

    def _simple_truss(
        self,
        length: float = 10.0,
        truss_type: str = "F34",
        hoist_cap: float = 0.0,
        point_loads: list | None = None,
    ) -> TrussSegment:
        rpts = [
            RiggingPoint(0.0, "Hoist L", hoist_cap),
            RiggingPoint(length, "Hoist R", hoist_cap),
        ]
        pls = [PointLoad(**p) for p in (point_loads or [])]
        return TrussSegment(
            label="Test Truss",
            length_m=length,
            truss_type=truss_type,
            rigging_points=rpts,
            point_loads=pls,
        )

    def test_reactions_balance_self_weight(self):
        """Sum of reactions = total load (self-weight only, no point loads)."""
        seg = self._simple_truss()
        res = analyse_truss(seg)
        assert res.equilibrium_check
        sum_R = sum(hr.reaction_N for hr in res.hoist_results)
        assert abs(sum_R - res.total_load_N) < 0.01

    def test_reactions_balance_with_point_load(self):
        """Equilibrium holds when a point load is applied at mid-span."""
        seg = self._simple_truss(point_loads=[{"position_m": 5.0, "load_N": 2000.0}])
        res = analyse_truss(seg)
        assert res.equilibrium_check
        sum_R = sum(hr.reaction_N for hr in res.hoist_results)
        assert abs(sum_R - res.total_load_N) < 0.1

    def test_symmetric_midspan_point_load_equal_reactions(self):
        """Point load at mid-span of symmetric truss → equal reactions at both hoists."""
        seg = self._simple_truss(point_loads=[{"position_m": 5.0, "load_N": 1000.0}])
        res = analyse_truss(seg)
        R = [hr.reaction_N for hr in res.hoist_results]
        # Both hoists should share point load equally; self-weight also equal
        assert abs(R[0] - R[1]) < 0.1

    def test_hoist_overload_detected(self):
        """
        F34 10 m truss, mid-point load 5000 N, hoist capacity 2000 N.
        Each hoist sees ≈ 5000/2 + 73.6×10/2 = 2868 N > 2000 N → overloaded.
        """
        seg = self._simple_truss(
            hoist_cap=2000.0,
            point_loads=[{"position_m": 5.0, "load_N": 5000.0}],
        )
        res = analyse_truss(seg)
        assert len(res.overloaded_hoists) > 0

    def test_adequate_capacity_no_overload(self):
        """Generous hoist capacity → no overload flag."""
        seg = self._simple_truss(
            hoist_cap=10000.0,
            point_loads=[{"position_m": 5.0, "load_N": 500.0}],
        )
        res = analyse_truss(seg)
        assert res.overloaded_hoists == []

    def test_asymmetric_load_larger_reaction_near_load(self):
        """
        Point load at 25% of span → closer hoist carries more load.
        For span=10m, load at 2.5m: R_L = P×(10-2.5)/10 = 0.75P, R_R = 0.25P
        """
        P = 1000.0
        seg = TrussSegment(
            label="Asym",
            length_m=10.0,
            truss_type="",
            self_weight_N_per_m=0.0,  # zero self-weight to isolate
            rigging_points=[
                RiggingPoint(0.0, "Left", 0.0),
                RiggingPoint(10.0, "Right", 0.0),
            ],
            point_loads=[PointLoad(2.5, P, "Load")],
        )
        res = analyse_truss(seg)
        R_L = res.hoist_results[0].reaction_N   # should be 0.75 P = 750
        R_R = res.hoist_results[1].reaction_N   # should be 0.25 P = 250
        assert R_L == pytest.approx(750.0, rel=1e-4)
        assert R_R == pytest.approx(250.0, rel=1e-4)

    def test_three_hoist_reactions_balance(self):
        """Three hoists on a truss — equilibrium holds."""
        seg = TrussSegment(
            label="3-hoist",
            length_m=12.0,
            truss_type="F34",
            rigging_points=[
                RiggingPoint(0.0, "H1"),
                RiggingPoint(6.0, "H2"),
                RiggingPoint(12.0, "H3"),
            ],
            point_loads=[PointLoad(3.0, 800.0, "Wash"), PointLoad(9.0, 600.0, "Spot")],
        )
        res = analyse_truss(seg)
        sum_R = sum(hr.reaction_N for hr in res.hoist_results)
        assert abs(sum_R - res.total_load_N) < res.total_load_N * 0.001 + 1.0

    def test_total_load_components(self):
        """total_load_N = total_self_weight_N + total_point_load_N."""
        seg = self._simple_truss(point_loads=[{"position_m": 5.0, "load_N": 1000.0}])
        res = analyse_truss(seg)
        assert abs(res.total_load_N - (res.total_self_weight_N + res.total_point_load_N)) < 0.01

    def test_f34_self_weight(self):
        """F34 truss linear weight = 73.6 N/m."""
        seg = self._simple_truss()
        res = analyse_truss(seg)
        assert res.self_weight_N_per_m == pytest.approx(73.6, abs=0.01)
        assert res.total_self_weight_N == pytest.approx(73.6 * 10.0, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool smoke tests (run without a live backend)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import json

from kerf_entertainment._compat import ProjectCtx


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestTools:

    def test_lighting_plot_patch_tool(self):
        from kerf_entertainment.tools import run_lighting_plot_patch
        ctx = ProjectCtx()
        payload = json.dumps({
            "fixtures": [
                {"fixture_id": "101", "type_name": "Source Four", "wattage": 575,
                 "dmx_footprint": 1, "channel": 1, "dimmer": 1, "dmx_universe": 0,
                 "dmx_address": 1, "position": "FOH"},
                {"fixture_id": "102", "type_name": "Source Four", "wattage": 575,
                 "dmx_footprint": 1, "channel": 2, "dimmer": 1, "dmx_universe": 0,
                 "dmx_address": 5, "position": "FOH"},
            ],
        }).encode()
        result = _run(run_lighting_plot_patch(ctx, payload))
        data = json.loads(result)
        assert data["total_fixtures"] == 2
        assert data["total_wattage_W"] == pytest.approx(1150.0)
        assert data["dmx_conflicts"] == []

    def test_lighting_dmx_check_tool_conflict(self):
        from kerf_entertainment.tools import run_lighting_dmx_check
        ctx = ProjectCtx()
        payload = json.dumps({
            "fixtures": [
                {"fixture_id": "A", "dmx_universe": 0, "dmx_address": 10, "dmx_footprint": 3},
                {"fixture_id": "B", "dmx_universe": 0, "dmx_address": 11, "dmx_footprint": 2},
            ],
        }).encode()
        result = _run(run_lighting_dmx_check(ctx, payload))
        data = json.loads(result)
        assert data["conflicts_detected"]
        assert data["conflict_count"] == 1

    def test_rigging_tool_overload(self):
        from kerf_entertainment.tools import run_rigging_load_analysis
        ctx = ProjectCtx()
        payload = json.dumps({
            "trusses": [{
                "label": "DS Truss",
                "length_m": 10.0,
                "truss_type": "F34",
                "rigging_points": [
                    {"position_m": 0.0, "label": "H1", "hoist_capacity_N": 2000.0},
                    {"position_m": 10.0, "label": "H2", "hoist_capacity_N": 2000.0},
                ],
                "point_loads": [
                    {"position_m": 5.0, "load_N": 5000.0, "label": "wash pack"},
                ],
            }],
        }).encode()
        result = _run(run_rigging_load_analysis(ctx, payload))
        data = json.loads(result)
        assert data["any_overload"]
        assert len(data["trusses"][0]["overloaded_hoists"]) > 0

    def test_rigging_tool_bridle(self):
        from kerf_entertainment.tools import run_rigging_load_analysis
        ctx = ProjectCtx()
        height = 2.0 * math.sqrt(3.0)
        payload = json.dumps({
            "bridles": [{
                "label": "DS Pick",
                "load_N": 1000.0,
                "horizontal_spread_m": 4.0,
                "vertical_height_m": height,
            }],
        }).encode()
        result = _run(run_rigging_load_analysis(ctx, payload))
        data = json.loads(result)
        br = data["bridles"][0]
        expected_T = 1000.0 / (2.0 * math.cos(math.radians(30.0)))
        assert abs(br["leg_tension_N"] - expected_T) < 1.0
