"""
T-50  Architecture: spaces + primitives — end-to-end building programs.

Scope: arch/spaces.py + arch/primitives.py
File:  packages/kerf-cad-core/tests/test_feature_arch_spaces.py

Success criteria
----------------
- 25 building programs (multi-room schedules)
- Area / volume tallies verified
- Room adjacency graph (shared-edge detection)

Pure-Python, hermetic — no OCC, no DB, no network, no on-disk fixtures.
All dimensions in millimetres; areas in mm²; volumes in mm³.

Programs P01–P25:
  P01  Single-room office box — area/load/egress sanity
  P02  Two-room office + meeting room on same level
  P03  Three-level office tower — by_level rollup
  P04  Mixed-occupancy retail ground / office upper
  P05  Assembly hall + lobby — high-load programme
  P06  Residential apartment — 4 rooms, two levels
  P07  Hospital ward cluster — healthcare_inpatient load
  P08  Library reading room + stacks — library_reading_room
  P09  School two classrooms + corridor
  P10  Industrial factory bay + office mezzanine
  P11  Commercial kitchen + dining
  P12  Car-park level + stair core
  P13  Mall anchor + food court
  P14  Locker-room + gym floor
  P15  Mixed-use podium: ground retail, upper office, roof terrace
  P16  Warehouse storage block
  P17  Data-centre server hall (storage load factor)
  P18  Assembly — standing-room concert foyer
  P19  Open-plan office with wall-thickness net area
  P20  L-shaped boardroom — non-rectangular plan
  P21  Boundary-condition: one-room per level, 10 levels
  P22  Idempotency: same programme computed twice → identical results
  P23  Malformed programme: one bad room in otherwise valid list
  P24  Adjacency graph: shared-edge rooms detected as adjacent
  P25  Volume tallies: wall + slab volumes cross-checked across primitive
       builders (primitives.py) for a complete 4-room building model
"""
from __future__ import annotations

import math
import uuid
from typing import Any

import pytest

from kerf_cad_core.arch.spaces import (
    OCCUPANCY_LOAD_FACTORS,
    _MM2_PER_M2,
    compute_area_schedule,
    compute_occupancy_load,
    compute_room,
    shoelace_area,
)
from kerf_cad_core.arch.primitives import (
    build_door,
    build_slab,
    build_wall,
    build_window,
    compose_wall_with_openings,
)


# ---------------------------------------------------------------------------
# Polygon helpers
# ---------------------------------------------------------------------------

def _rect(w: float, h: float, ox: float = 0.0, oy: float = 0.0) -> list:
    """Axis-aligned rectangle (CCW), millimetres."""
    return [
        [ox, oy],
        [ox + w, oy],
        [ox + w, oy + h],
        [ox, oy + h],
    ]


def _l_shape(a: float, b: float, c: float, d: float) -> list:
    """L-shape: a×b rectangle minus upper-right c×d corner (CCW)."""
    return [
        [0.0, 0.0],
        [a, 0.0],
        [a, b - d],
        [a - c, b - d],
        [a - c, b],
        [0.0, b],
    ]


def _room(w: float, h: float, name: str, occ: str,
          level: str = "L1", wall_t: float = 0.0) -> dict:
    """Convenience: compute_room for an axis-aligned rectangle."""
    return compute_room(_rect(w, h), name, occ, wall_thickness=wall_t, level=level)


def _assert_ok(r: dict) -> None:
    assert r.get("ok") is True, f"Expected ok=True, errors={r.get('errors')}"


def _total_load(rooms: list[dict]) -> int:
    return sum(r["occupant_load"] for r in rooms)


def _total_gross_mm2(rooms: list[dict]) -> float:
    return sum(r["gross_area_mm2"] for r in rooms)


# ---------------------------------------------------------------------------
# Adjacency graph helper
# ---------------------------------------------------------------------------

def _shared_edge(poly_a: list, poly_b: list, tol: float = 1.0) -> bool:
    """
    Return True if poly_a and poly_b share at least one edge (same pair of
    vertices within *tol* mm).  Handles reversed orientation.
    """
    def _edges(poly):
        n = len(poly)
        return [
            (
                (min(poly[i][0], poly[(i + 1) % n][0]),
                 min(poly[i][1], poly[(i + 1) % n][1])),
                (max(poly[i][0], poly[(i + 1) % n][0]),
                 max(poly[i][1], poly[(i + 1) % n][1])),
            )
            for i in range(n)
        ]

    def _close(a, b) -> bool:
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    ea = _edges(poly_a)
    eb = _edges(poly_b)
    for (a0, a1) in ea:
        for (b0, b1) in eb:
            if _close(a0, b0) and _close(a1, b1):
                return True
    return False


def _adjacency_graph(rooms_with_poly: list[tuple[dict, list]]) -> dict[str, list[str]]:
    """
    Build an adjacency graph: {room_name: [adjacent_room_names]}.
    Two rooms are adjacent when their polygons share an edge.
    """
    graph: dict[str, list[str]] = {r["name"]: [] for r, _ in rooms_with_poly}
    n = len(rooms_with_poly)
    for i in range(n):
        ri, pi = rooms_with_poly[i]
        for j in range(i + 1, n):
            rj, pj = rooms_with_poly[j]
            if _shared_edge(pi, pj):
                graph[ri["name"]].append(rj["name"])
                graph[rj["name"]].append(ri["name"])
    return graph


# ---------------------------------------------------------------------------
# P01 – Single-room office box
# ---------------------------------------------------------------------------

class TestP01SingleRoomOffice:
    def test_area_tally(self):
        r = _room(8_000.0, 6_000.0, "Main Office", "business")
        _assert_ok(r)
        assert r["gross_area_mm2"] == pytest.approx(8_000.0 * 6_000.0)
        assert r["gross_area_m2"] == pytest.approx(8_000.0 * 6_000.0 / _MM2_PER_M2)

    def test_occupant_load(self):
        r = _room(8_000.0, 6_000.0, "Main Office", "business")
        factor = OCCUPANCY_LOAD_FACTORS["business"]
        expected = math.ceil((8_000.0 * 6_000.0 / _MM2_PER_M2) / factor)
        assert r["occupant_load"] == expected

    def test_egress_stairways(self):
        r = _room(8_000.0, 6_000.0, "Main Office", "business")
        assert r["egress_width"]["stairways_mm"] == pytest.approx(r["occupant_load"] * 0.3)

    def test_schedule_single_room(self):
        r = _room(8_000.0, 6_000.0, "Main Office", "business")
        s = compute_area_schedule([r])
        _assert_ok(s)
        assert s["total_gross_area_mm2"] == pytest.approx(r["gross_area_mm2"])
        assert s["total_occupant_load"] == r["occupant_load"]


# ---------------------------------------------------------------------------
# P02 – Two-room office + meeting room
# ---------------------------------------------------------------------------

class TestP02TwoRoomOffice:
    def _rooms(self):
        r1 = _room(8_000.0, 6_000.0, "Open Plan", "business", "L1")
        r2 = _room(4_000.0, 3_000.0, "Meeting Room", "business", "L1")
        return r1, r2

    def test_schedule_totals(self):
        r1, r2 = self._rooms()
        s = compute_area_schedule([r1, r2])
        _assert_ok(s)
        assert s["total_gross_area_mm2"] == pytest.approx(
            r1["gross_area_mm2"] + r2["gross_area_mm2"]
        )

    def test_by_level_l1_room_count(self):
        r1, r2 = self._rooms()
        s = compute_area_schedule([r1, r2])
        assert s["by_level"]["L1"]["room_count"] == 2

    def test_total_load_is_sum(self):
        r1, r2 = self._rooms()
        s = compute_area_schedule([r1, r2])
        assert s["total_occupant_load"] == r1["occupant_load"] + r2["occupant_load"]


# ---------------------------------------------------------------------------
# P03 – Three-level office tower
# ---------------------------------------------------------------------------

class TestP03ThreeLevelTower:
    _FLOOR_W, _FLOOR_H = 20_000.0, 15_000.0

    def _levels(self):
        return [
            _room(self._FLOOR_W, self._FLOOR_H, f"Floor {lvl}", "business", lvl)
            for lvl in ("L1", "L2", "L3")
        ]

    def test_by_level_keys(self):
        s = compute_area_schedule(self._levels())
        assert set(s["by_level"]) == {"L1", "L2", "L3"}

    def test_each_level_gross_area(self):
        s = compute_area_schedule(self._levels())
        expected = self._FLOOR_W * self._FLOOR_H
        for lvl in ("L1", "L2", "L3"):
            assert s["by_level"][lvl]["gross_area_mm2"] == pytest.approx(expected)

    def test_total_gross_area_three_floors(self):
        s = compute_area_schedule(self._levels())
        expected = 3 * self._FLOOR_W * self._FLOOR_H
        assert s["total_gross_area_mm2"] == pytest.approx(expected)

    def test_total_load_three_floors(self):
        rooms = self._levels()
        s = compute_area_schedule(rooms)
        assert s["total_occupant_load"] == _total_load(rooms)


# ---------------------------------------------------------------------------
# P04 – Mixed-occupancy retail/office
# ---------------------------------------------------------------------------

class TestP04MixedOccupancy:
    def _programme(self):
        retail = _room(15_000.0, 10_000.0, "Retail Floor", "mercantile", "L1")
        office = _room(15_000.0, 10_000.0, "Office Floor", "business", "L2")
        return retail, office

    def test_by_occupancy_keys(self):
        retail, office = self._programme()
        s = compute_area_schedule([retail, office])
        assert "mercantile" in s["by_occupancy"]
        assert "business" in s["by_occupancy"]

    def test_retail_higher_load_density(self):
        retail, office = self._programme()
        # Mercantile factor (2.79) < business factor (9.30)
        # so same area → more occupants for retail
        assert retail["occupant_load"] > office["occupant_load"]

    def test_total_gross_area(self):
        retail, office = self._programme()
        s = compute_area_schedule([retail, office])
        assert s["total_gross_area_mm2"] == pytest.approx(
            retail["gross_area_mm2"] + office["gross_area_mm2"]
        )

    def test_gross_area_m2_conversion(self):
        retail, office = self._programme()
        s = compute_area_schedule([retail, office])
        assert s["total_gross_area_m2"] == pytest.approx(
            s["total_gross_area_mm2"] / _MM2_PER_M2
        )


# ---------------------------------------------------------------------------
# P05 – Assembly hall + lobby
# ---------------------------------------------------------------------------

class TestP05AssemblyHall:
    def _programme(self):
        hall = _room(25_000.0, 20_000.0, "Main Hall", "assembly_concentrated", "L1")
        lobby = _room(10_000.0, 5_000.0, "Lobby", "assembly_standing", "L1")
        return hall, lobby

    def test_high_occupant_load(self):
        hall, lobby = self._programme()
        # 25m × 20m = 500 m², factor 0.65 → ceil(500/0.65) = 770
        factor = OCCUPANCY_LOAD_FACTORS["assembly_concentrated"]
        expected = math.ceil((25_000.0 * 20_000.0 / _MM2_PER_M2) / factor)
        assert hall["occupant_load"] == expected

    def test_lobby_standing_load(self):
        hall, lobby = self._programme()
        factor = OCCUPANCY_LOAD_FACTORS["assembly_standing"]
        expected = math.ceil((10_000.0 * 5_000.0 / _MM2_PER_M2) / factor)
        assert lobby["occupant_load"] == expected

    def test_schedule_total_load(self):
        hall, lobby = self._programme()
        s = compute_area_schedule([hall, lobby])
        assert s["total_occupant_load"] == hall["occupant_load"] + lobby["occupant_load"]


# ---------------------------------------------------------------------------
# P06 – Residential apartment
# ---------------------------------------------------------------------------

class TestP06Residential:
    def _programme(self):
        living = _room(5_000.0, 4_000.0, "Living Room", "residential", "L1")
        kitchen = _room(3_000.0, 3_000.0, "Kitchen", "kitchen_commercial", "L1")
        bed1 = _room(4_000.0, 3_500.0, "Bedroom 1", "residential", "L2")
        bed2 = _room(3_000.0, 3_000.0, "Bedroom 2", "residential", "L2")
        return [living, kitchen, bed1, bed2]

    def test_schedule_ok(self):
        s = compute_area_schedule(self._programme())
        _assert_ok(s)

    def test_by_level_two_levels(self):
        s = compute_area_schedule(self._programme())
        assert set(s["by_level"]) == {"L1", "L2"}

    def test_l2_room_count(self):
        s = compute_area_schedule(self._programme())
        assert s["by_level"]["L2"]["room_count"] == 2

    def test_total_gross_area(self):
        rooms = self._programme()
        s = compute_area_schedule(rooms)
        assert s["total_gross_area_mm2"] == pytest.approx(_total_gross_mm2(rooms))


# ---------------------------------------------------------------------------
# P07 – Hospital ward cluster
# ---------------------------------------------------------------------------

class TestP07Hospital:
    def _wards(self):
        return [
            _room(8_000.0, 6_000.0, f"Ward {i}", "healthcare_inpatient", "L1")
            for i in range(1, 5)
        ]

    def test_four_ward_loads(self):
        wards = self._wards()
        factor = OCCUPANCY_LOAD_FACTORS["healthcare_inpatient"]
        for w in wards:
            expected = math.ceil((8_000.0 * 6_000.0 / _MM2_PER_M2) / factor)
            assert w["occupant_load"] == expected

    def test_schedule_total_occupants(self):
        wards = self._wards()
        s = compute_area_schedule(wards)
        assert s["total_occupant_load"] == _total_load(wards)

    def test_by_occupancy_key(self):
        s = compute_area_schedule(self._wards())
        assert "healthcare_inpatient" in s["by_occupancy"]


# ---------------------------------------------------------------------------
# P08 – Library reading room + stacks
# ---------------------------------------------------------------------------

class TestP08Library:
    def _programme(self):
        reading = _room(12_000.0, 8_000.0, "Reading Room", "library_reading_room", "L1")
        stacks = _room(8_000.0, 6_000.0, "Book Stacks", "storage", "L1")
        return reading, stacks

    def test_reading_room_load(self):
        reading, _ = self._programme()
        factor = OCCUPANCY_LOAD_FACTORS["library_reading_room"]
        expected = math.ceil((12_000.0 * 8_000.0 / _MM2_PER_M2) / factor)
        assert reading["occupant_load"] == expected

    def test_storage_lower_load_density(self):
        reading, stacks = self._programme()
        # reading room factor (4.65) == storage factor (11.15), so for same area
        # stacks should have fewer occupants (larger factor = fewer people)
        # stacks: 8000×6000=48m², factor 11.15 → ceil(48/11.15)=5
        # reading: 12000×8000=96m², factor 4.65 → ceil(96/4.65)=21
        assert reading["occupant_load"] > stacks["occupant_load"]

    def test_schedule_totals(self):
        reading, stacks = self._programme()
        s = compute_area_schedule([reading, stacks])
        _assert_ok(s)
        assert s["total_gross_area_mm2"] == pytest.approx(
            reading["gross_area_mm2"] + stacks["gross_area_mm2"]
        )


# ---------------------------------------------------------------------------
# P09 – School two classrooms + corridor
# ---------------------------------------------------------------------------

class TestP09School:
    def _programme(self):
        c1 = _room(9_000.0, 7_000.0, "Classroom A", "educational_classroom", "L1")
        c2 = _room(9_000.0, 7_000.0, "Classroom B", "educational_classroom", "L1")
        corridor = _room(18_000.0, 2_000.0, "Corridor", "business", "L1")
        return [c1, c2, corridor]

    def test_classroom_loads_equal(self):
        rooms = self._programme()
        assert rooms[0]["occupant_load"] == rooms[1]["occupant_load"]

    def test_schedule_room_count(self):
        s = compute_area_schedule(self._programme())
        assert s["by_level"]["L1"]["room_count"] == 3

    def test_corridor_business_factor(self):
        rooms = self._programme()
        corridor = rooms[2]
        factor = OCCUPANCY_LOAD_FACTORS["business"]
        expected = math.ceil((18_000.0 * 2_000.0 / _MM2_PER_M2) / factor)
        assert corridor["occupant_load"] == expected


# ---------------------------------------------------------------------------
# P10 – Industrial factory + office mezzanine
# ---------------------------------------------------------------------------

class TestP10Industrial:
    def _programme(self):
        bay = _room(30_000.0, 20_000.0, "Factory Bay", "factory_industrial", "L1")
        mez = _room(10_000.0, 8_000.0, "Office Mezzanine", "business", "L2")
        return bay, mez

    def test_factory_load(self):
        bay, _ = self._programme()
        factor = OCCUPANCY_LOAD_FACTORS["factory_industrial"]
        expected = math.ceil((30_000.0 * 20_000.0 / _MM2_PER_M2) / factor)
        assert bay["occupant_load"] == expected

    def test_mezzanine_level(self):
        _, mez = self._programme()
        assert mez["level"] == "L2"

    def test_schedule_two_levels(self):
        bay, mez = self._programme()
        s = compute_area_schedule([bay, mez])
        assert set(s["by_level"]) == {"L1", "L2"}


# ---------------------------------------------------------------------------
# P11 – Commercial kitchen + dining
# ---------------------------------------------------------------------------

class TestP11Kitchen:
    def _programme(self):
        kitchen = _room(6_000.0, 5_000.0, "Kitchen", "kitchen_commercial", "L1")
        dining = _room(12_000.0, 8_000.0, "Dining Hall", "assembly_unconcentrated", "L1")
        return kitchen, dining

    def test_kitchen_load(self):
        kitchen, _ = self._programme()
        factor = OCCUPANCY_LOAD_FACTORS["kitchen_commercial"]
        expected = math.ceil((6_000.0 * 5_000.0 / _MM2_PER_M2) / factor)
        assert kitchen["occupant_load"] == expected

    def test_dining_higher_density_than_kitchen(self):
        kitchen, dining = self._programme()
        # dining area is 12×8=96m² with factor 1.39 → ceil(69)=70
        # kitchen is 6×5=30m² with factor 4.65 → ceil(6.45)=7
        assert dining["occupant_load"] > kitchen["occupant_load"]

    def test_schedule_ok(self):
        kitchen, dining = self._programme()
        s = compute_area_schedule([kitchen, dining])
        _assert_ok(s)


# ---------------------------------------------------------------------------
# P12 – Car park + stair core
# ---------------------------------------------------------------------------

class TestP12CarPark:
    def _programme(self):
        park = _room(50_000.0, 20_000.0, "Car Park", "parking", "B1")
        stair = _room(3_000.0, 2_000.0, "Stair Core", "business", "B1")
        return park, stair

    def test_parking_load_factor(self):
        park, _ = self._programme()
        factor = OCCUPANCY_LOAD_FACTORS["parking"]
        expected = math.ceil((50_000.0 * 20_000.0 / _MM2_PER_M2) / factor)
        assert park["occupant_load"] == expected

    def test_by_level_b1(self):
        park, stair = self._programme()
        s = compute_area_schedule([park, stair])
        assert "B1" in s["by_level"]
        assert s["by_level"]["B1"]["room_count"] == 2


# ---------------------------------------------------------------------------
# P13 – Mall anchor + food court
# ---------------------------------------------------------------------------

class TestP13Mall:
    def _programme(self):
        anchor = _room(40_000.0, 30_000.0, "Anchor Store", "mall_covered", "L1")
        food = _room(15_000.0, 10_000.0, "Food Court", "assembly_unconcentrated", "L1")
        return anchor, food

    def test_mall_by_occupancy(self):
        anchor, food = self._programme()
        s = compute_area_schedule([anchor, food])
        assert "mall_covered" in s["by_occupancy"]
        assert "assembly_unconcentrated" in s["by_occupancy"]

    def test_total_gross_area(self):
        anchor, food = self._programme()
        s = compute_area_schedule([anchor, food])
        assert s["total_gross_area_mm2"] == pytest.approx(
            anchor["gross_area_mm2"] + food["gross_area_mm2"]
        )


# ---------------------------------------------------------------------------
# P14 – Locker room + gym
# ---------------------------------------------------------------------------

class TestP14LockerGym:
    def _programme(self):
        locker = _room(4_000.0, 3_000.0, "Locker Room", "locker_room", "L1")
        gym = _room(15_000.0, 10_000.0, "Gym Floor", "assembly_unconcentrated", "L1")
        return locker, gym

    def test_locker_load(self):
        locker, _ = self._programme()
        factor = OCCUPANCY_LOAD_FACTORS["locker_room"]
        expected = math.ceil((4_000.0 * 3_000.0 / _MM2_PER_M2) / factor)
        assert locker["occupant_load"] == expected

    def test_schedule_total(self):
        locker, gym = self._programme()
        s = compute_area_schedule([locker, gym])
        _assert_ok(s)
        assert s["total_occupant_load"] == locker["occupant_load"] + gym["occupant_load"]


# ---------------------------------------------------------------------------
# P15 – Mixed-use podium: ground retail + office + roof terrace
# ---------------------------------------------------------------------------

class TestP15MixedUsePodium:
    def _programme(self):
        gf_retail = _room(20_000.0, 12_000.0, "Ground Retail", "mercantile", "L1")
        l2_office = _room(20_000.0, 12_000.0, "Office L2", "business", "L2")
        l3_office = _room(20_000.0, 12_000.0, "Office L3", "business", "L3")
        roof = _room(10_000.0, 8_000.0, "Roof Terrace", "assembly_standing", "L4")
        return [gf_retail, l2_office, l3_office, roof]

    def test_four_level_keys(self):
        s = compute_area_schedule(self._programme())
        assert set(s["by_level"]) == {"L1", "L2", "L3", "L4"}

    def test_three_occupancy_types(self):
        s = compute_area_schedule(self._programme())
        assert set(s["by_occupancy"]) == {"mercantile", "business", "assembly_standing"}

    def test_office_floors_equal_load(self):
        rooms = self._programme()
        assert rooms[1]["occupant_load"] == rooms[2]["occupant_load"]


# ---------------------------------------------------------------------------
# P16 – Warehouse storage
# ---------------------------------------------------------------------------

class TestP16Warehouse:
    def test_storage_load(self):
        r = _room(60_000.0, 40_000.0, "Warehouse", "storage", "L1")
        _assert_ok(r)
        factor = OCCUPANCY_LOAD_FACTORS["storage"]
        expected = math.ceil((60_000.0 * 40_000.0 / _MM2_PER_M2) / factor)
        assert r["occupant_load"] == expected

    def test_schedule_single_room(self):
        r = _room(60_000.0, 40_000.0, "Warehouse", "storage", "L1")
        s = compute_area_schedule([r])
        _assert_ok(s)
        assert s["total_gross_area_m2"] == pytest.approx(60_000.0 * 40_000.0 / _MM2_PER_M2)


# ---------------------------------------------------------------------------
# P17 – Data centre server hall
# ---------------------------------------------------------------------------

class TestP17DataCentre:
    def test_server_hall_as_storage(self):
        r = _room(10_000.0, 8_000.0, "Server Hall", "storage", "L1")
        _assert_ok(r)

    def test_net_area_equals_gross_no_walls(self):
        r = _room(10_000.0, 8_000.0, "Server Hall", "storage", "L1", wall_t=0.0)
        assert r["net_area_mm2"] == pytest.approx(r["gross_area_mm2"])


# ---------------------------------------------------------------------------
# P18 – Assembly standing-room foyer
# ---------------------------------------------------------------------------

class TestP18AssemblyStanding:
    def test_standing_load_high_density(self):
        r = _room(10_000.0, 5_000.0, "Concert Foyer", "assembly_standing", "L1")
        factor = OCCUPANCY_LOAD_FACTORS["assembly_standing"]
        expected = math.ceil((10_000.0 * 5_000.0 / _MM2_PER_M2) / factor)
        assert r["occupant_load"] == expected

    def test_egress_proportional_to_load(self):
        r = _room(10_000.0, 5_000.0, "Concert Foyer", "assembly_standing", "L1")
        assert r["egress_width"]["other_means_mm"] == pytest.approx(r["occupant_load"] * 0.2)


# ---------------------------------------------------------------------------
# P19 – Open-plan office with wall thickness
# ---------------------------------------------------------------------------

class TestP19WallThickness:
    def test_net_less_than_gross(self):
        r = _room(10_000.0, 8_000.0, "Open Plan", "business", "L1", wall_t=200.0)
        assert r["net_area_mm2"] < r["gross_area_mm2"]

    def test_net_area_band_formula(self):
        w, h, t = 10_000.0, 8_000.0, 200.0
        r = compute_room(_rect(w, h), "Open Plan", "business", wall_thickness=t, level="L1")
        gross = w * h
        perim = 2 * (w + h)
        expected_net = gross - perim * (t / 2.0)
        assert r["net_area_mm2"] == pytest.approx(expected_net)

    def test_load_computed_on_net_area(self):
        w, h, t = 10_000.0, 8_000.0, 200.0
        r = compute_room(_rect(w, h), "Open Plan", "business", wall_thickness=t, level="L1")
        factor = OCCUPANCY_LOAD_FACTORS["business"]
        expected = math.ceil(r["net_area_mm2"] / _MM2_PER_M2 / factor)
        assert r["occupant_load"] == expected

    def test_schedule_uses_net_area(self):
        w, h, t = 10_000.0, 8_000.0, 200.0
        r = compute_room(_rect(w, h), "Open Plan", "business", wall_thickness=t, level="L1")
        s = compute_area_schedule([r])
        assert s["total_net_area_mm2"] == pytest.approx(r["net_area_mm2"])


# ---------------------------------------------------------------------------
# P20 – L-shaped boardroom
# ---------------------------------------------------------------------------

class TestP20LShapedBoardroom:
    # Main 10 m × 8 m minus upper-right 4 m × 3 m corner
    _A, _B, _C, _D = 10_000.0, 8_000.0, 4_000.0, 3_000.0

    def test_l_shape_gross_area(self):
        poly = _l_shape(self._A, self._B, self._C, self._D)
        r = compute_room(poly, "Boardroom", "business", level="L1")
        _assert_ok(r)
        expected = self._A * self._B - self._C * self._D
        assert r["gross_area_mm2"] == pytest.approx(expected)

    def test_l_shape_gross_area_m2(self):
        poly = _l_shape(self._A, self._B, self._C, self._D)
        r = compute_room(poly, "Boardroom", "business", level="L1")
        expected_m2 = (self._A * self._B - self._C * self._D) / _MM2_PER_M2
        assert r["gross_area_m2"] == pytest.approx(expected_m2)

    def test_l_shape_occupant_load(self):
        poly = _l_shape(self._A, self._B, self._C, self._D)
        r = compute_room(poly, "Boardroom", "business", level="L1")
        factor = OCCUPANCY_LOAD_FACTORS["business"]
        area_m2 = (self._A * self._B - self._C * self._D) / _MM2_PER_M2
        expected = math.ceil(area_m2 / factor)
        assert r["occupant_load"] == expected

    def test_l_shape_in_schedule(self):
        poly = _l_shape(self._A, self._B, self._C, self._D)
        r = compute_room(poly, "Boardroom", "business", level="L1")
        s = compute_area_schedule([r])
        _assert_ok(s)
        assert s["total_gross_area_mm2"] == pytest.approx(r["gross_area_mm2"])


# ---------------------------------------------------------------------------
# P21 – Boundary condition: 10 levels, one room per level
# ---------------------------------------------------------------------------

class TestP21TenLevels:
    _LEVELS = [f"L{i}" for i in range(1, 11)]
    _W, _H = 12_000.0, 10_000.0

    def _programme(self):
        return [
            _room(self._W, self._H, f"Floor {lvl}", "business", lvl)
            for lvl in self._LEVELS
        ]

    def test_ten_level_keys(self):
        s = compute_area_schedule(self._programme())
        assert set(s["by_level"]) == set(self._LEVELS)

    def test_ten_levels_total_area(self):
        s = compute_area_schedule(self._programme())
        expected = 10 * self._W * self._H
        assert s["total_gross_area_mm2"] == pytest.approx(expected)

    def test_ten_levels_total_load(self):
        rooms = self._programme()
        s = compute_area_schedule(rooms)
        assert s["total_occupant_load"] == _total_load(rooms)


# ---------------------------------------------------------------------------
# P22 – Idempotency: same programme computed twice → identical results
# ---------------------------------------------------------------------------

class TestP22Idempotency:
    def _programme(self):
        r1 = _room(8_000.0, 6_000.0, "Office A", "business", "L1")
        r2 = _room(5_000.0, 4_000.0, "Office B", "business", "L1")
        r3 = _room(10_000.0, 8_000.0, "Hall", "assembly_concentrated", "L2")
        return [r1, r2, r3]

    def test_deterministic_room_output(self):
        rooms_a = self._programme()
        rooms_b = self._programme()
        for a, b in zip(rooms_a, rooms_b):
            assert a["gross_area_mm2"] == pytest.approx(b["gross_area_mm2"])
            assert a["occupant_load"] == b["occupant_load"]

    def test_deterministic_schedule_output(self):
        s1 = compute_area_schedule(self._programme())
        s2 = compute_area_schedule(self._programme())
        assert s1["total_gross_area_mm2"] == pytest.approx(s2["total_gross_area_mm2"])
        assert s1["total_occupant_load"] == s2["total_occupant_load"]

    def test_idempotent_occupancy_load(self):
        r1 = compute_occupancy_load(100.0, "business")
        r2 = compute_occupancy_load(100.0, "business")
        assert r1["occupant_load"] == r2["occupant_load"]
        assert r1["egress_width"] == r2["egress_width"]


# ---------------------------------------------------------------------------
# P23 – Malformed programme: one bad room in otherwise valid list
# ---------------------------------------------------------------------------

class TestP23MalformedProgramme:
    def test_bad_room_makes_schedule_fail(self):
        good = _room(5_000.0, 4_000.0, "Good Room", "business", "L1")
        bad = compute_room([[0, 0], [1000, 0]], "Too few verts", "business")
        assert bad["ok"] is False
        s = compute_area_schedule([good, bad])
        assert s["ok"] is False

    def test_unknown_occupancy_room_fails(self):
        r = compute_room(_rect(3_000.0, 3_000.0), "Room", "discotheque")
        assert r["ok"] is False
        assert any("discotheque" in e or "occupancy" in e.lower() for e in r["errors"])

    def test_negative_wall_thickness_fails(self):
        r = compute_room(_rect(4_000.0, 3_000.0), "Office", "business",
                         wall_thickness=-100.0)
        assert r["ok"] is False
        assert any("wall_thickness" in e.lower() for e in r["errors"])

    def test_self_intersecting_polygon_fails(self):
        bow_tie = [[0.0, 0.0], [2000.0, 2000.0], [2000.0, 0.0], [0.0, 2000.0]]
        r = compute_room(bow_tie, "Twisted", "business")
        assert r["ok"] is False

    def test_non_dict_in_rooms_list(self):
        good = _room(5_000.0, 4_000.0, "Good Room", "business", "L1")
        s = compute_area_schedule([good, "not_a_dict"])
        assert s["ok"] is False

    def test_negative_area_occupancy_load_fails(self):
        r = compute_occupancy_load(-50.0, "business")
        assert r["ok"] is False

    def test_empty_name_fails(self):
        r = compute_room(_rect(3_000.0, 2_000.0), "  ", "business")
        assert r["ok"] is False
        assert any("name" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# P24 – Adjacency graph: shared-edge rooms detected
# ---------------------------------------------------------------------------

class TestP24AdjacencyGraph:
    """
    Floor plan layout (all in mm):

        Room A [0,0]→[6000,4000]   Room B [6000,0]→[12000,4000]
        Room C [0,4000]→[6000,8000] Room D [6000,4000]→[12000,8000]

    Expected adjacency:
      A — B  (shared vertical edge x=6000, y=0..4000)
      A — C  (shared horizontal edge y=4000, x=0..6000)
      B — D  (shared horizontal edge y=4000, x=6000..12000)
      C — D  (shared vertical edge x=6000, y=4000..8000)
      A — D  NOT adjacent (only share corner point, not edge)
      B — C  NOT adjacent (only share corner point, not edge)
    """
    _PA = [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]
    _PB = [[6000, 0], [12000, 0], [12000, 4000], [6000, 4000]]
    _PC = [[0, 4000], [6000, 4000], [6000, 8000], [0, 8000]]
    _PD = [[6000, 4000], [12000, 4000], [12000, 8000], [6000, 8000]]

    def _rooms_with_polys(self):
        ra = compute_room(self._PA, "Room A", "business", level="L1")
        rb = compute_room(self._PB, "Room B", "business", level="L1")
        rc = compute_room(self._PC, "Room C", "business", level="L1")
        rd = compute_room(self._PD, "Room D", "business", level="L1")
        return [
            (ra, self._PA),
            (rb, self._PB),
            (rc, self._PC),
            (rd, self._PD),
        ]

    def test_rooms_all_valid(self):
        for r, _ in self._rooms_with_polys():
            _assert_ok(r)

    def test_a_adjacent_to_b(self):
        assert _shared_edge(self._PA, self._PB) is True

    def test_a_adjacent_to_c(self):
        assert _shared_edge(self._PA, self._PC) is True

    def test_b_adjacent_to_d(self):
        assert _shared_edge(self._PB, self._PD) is True

    def test_c_adjacent_to_d(self):
        assert _shared_edge(self._PC, self._PD) is True

    def test_a_not_adjacent_to_d(self):
        # A and D share only a corner point, not a full edge
        assert _shared_edge(self._PA, self._PD) is False

    def test_b_not_adjacent_to_c(self):
        assert _shared_edge(self._PB, self._PC) is False

    def test_adjacency_graph_structure(self):
        rooms_with_poly = self._rooms_with_polys()
        graph = _adjacency_graph(rooms_with_poly)
        assert "Room B" in graph["Room A"]
        assert "Room C" in graph["Room A"]
        assert "Room A" in graph["Room B"]
        assert "Room D" in graph["Room B"]
        assert "Room A" in graph["Room C"]
        assert "Room D" in graph["Room C"]
        assert "Room B" in graph["Room D"]
        assert "Room C" in graph["Room D"]
        assert "Room D" not in graph["Room A"]
        assert "Room C" not in graph["Room B"]

    def test_adjacency_schedule_total_area(self):
        rooms_with_poly = self._rooms_with_polys()
        rooms = [r for r, _ in rooms_with_poly]
        s = compute_area_schedule(rooms)
        _assert_ok(s)
        # Total: 4 rooms, each 6000×4000 = 24_000_000 mm², total = 96_000_000 mm²
        assert s["total_gross_area_mm2"] == pytest.approx(4 * 6_000.0 * 4_000.0)


# ---------------------------------------------------------------------------
# P25 – Volume tallies: wall + slab + spaces cross-checked
# ---------------------------------------------------------------------------

class TestP25VolumeTallies:
    """
    A complete 4-room single-storey building:
      - 4 rooms arranged in a 2×2 grid (from P24 layout but single-storey)
      - Perimeter walls + floor slabs built via primitives.py
      - Space programme validated against primitive volumes
    """
    _W, _H_ROOM = 6_000.0, 4_000.0   # each room: 6m × 4m
    _WALL_H = 3_000.0                 # wall height
    _WALL_T = 200.0                   # wall thickness
    _SLAB_T = 200.0                   # slab thickness

    # Polygon definitions (same as P24)
    _PA = [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]
    _PB = [[6000, 0], [12000, 0], [12000, 4000], [6000, 4000]]
    _PC = [[0, 4000], [6000, 4000], [6000, 8000], [0, 8000]]
    _PD = [[6000, 4000], [12000, 4000], [12000, 8000], [6000, 8000]]

    def _build_slabs(self):
        slabs = [
            build_slab(outline=p, thickness=self._SLAB_T, level=0.0)
            for p in (self._PA, self._PB, self._PC, self._PD)
        ]
        return slabs

    def _build_walls(self):
        """Perimeter walls of the full 12m×8m building (outer envelope only)."""
        pts = [
            ([0, 0], [12000, 0]),
            ([12000, 0], [12000, 8000]),
            ([12000, 8000], [0, 8000]),
            ([0, 8000], [0, 0]),
        ]
        return [
            build_wall(
                start=s, end=e,
                height=self._WALL_H,
                thickness=self._WALL_T,
            )
            for s, e in pts
        ]

    def _space_rooms(self):
        return [
            compute_room(p, f"Room {i}", "business", level="L1")
            for i, p in enumerate(
                (self._PA, self._PB, self._PC, self._PD), start=1
            )
        ]

    def test_slab_areas_match_rooms(self):
        slabs = self._build_slabs()
        rooms = self._space_rooms()
        for slab, room in zip(slabs, rooms):
            assert slab["ok"] is True
            assert slab["area_mm2"] == pytest.approx(room["gross_area_mm2"])

    def test_slab_volumes(self):
        slabs = self._build_slabs()
        for slab in slabs:
            expected_vol = self._W * self._H_ROOM * self._SLAB_T
            assert slab["volume_mm3"] == pytest.approx(expected_vol)

    def test_total_slab_volume(self):
        slabs = self._build_slabs()
        total = sum(s["volume_mm3"] for s in slabs)
        # 4 rooms × 6000×4000×200
        expected = 4 * self._W * self._H_ROOM * self._SLAB_T
        assert total == pytest.approx(expected)

    def test_perimeter_wall_lengths(self):
        """Perimeter walls: 2 walls of 12m + 2 walls of 8m."""
        walls = self._build_walls()
        lengths = [w["length_mm"] for w in walls]
        assert sorted(lengths) == pytest.approx(sorted([12_000.0, 8_000.0, 12_000.0, 8_000.0]))

    def test_perimeter_wall_gross_volumes(self):
        walls = self._build_walls()
        expected_vols = [
            12_000.0 * self._WALL_H * self._WALL_T,  # south
            8_000.0 * self._WALL_H * self._WALL_T,   # east
            12_000.0 * self._WALL_H * self._WALL_T,  # north
            8_000.0 * self._WALL_H * self._WALL_T,   # west
        ]
        for w, ev in zip(walls, expected_vols):
            assert w["gross_volume_mm3"] == pytest.approx(ev)

    def test_wall_with_door_net_volume(self):
        """A 12m south wall with a 900×2100 door reduces net volume."""
        wall = build_wall(
            start=[0, 0], end=[12_000.0, 0],
            height=self._WALL_H, thickness=self._WALL_T,
        )
        door = build_door(
            width=900, height=2100,
            wall_ref="south",
            position_along_wall=1_000.0,
            wall_length=12_000.0,
            wall_height=self._WALL_H,
            wall_thickness=self._WALL_T,
        )
        composed = compose_wall_with_openings(wall, [door])
        assert composed["ok"] is True
        expected_net = 12_000.0 * self._WALL_H * self._WALL_T - 900 * 2100 * self._WALL_T
        assert composed["net_volume_mm3"] == pytest.approx(expected_net)

    def test_wall_with_window_net_volume(self):
        wall = build_wall(
            start=[12_000.0, 0], end=[12_000.0, 8_000.0],
            height=self._WALL_H, thickness=self._WALL_T,
        )
        win = build_window(
            width=1_200.0, height=1_500.0, sill_height=900.0,
            wall_ref="east",
            position_along_wall=500.0,
            wall_length=8_000.0,
            wall_height=self._WALL_H,
            wall_thickness=self._WALL_T,
        )
        composed = compose_wall_with_openings(wall, [win])
        assert composed["ok"] is True
        expected_net = 8_000.0 * self._WALL_H * self._WALL_T - 1_200.0 * 1_500.0 * self._WALL_T
        assert composed["net_volume_mm3"] == pytest.approx(expected_net)

    def test_space_schedule_total_gross_area(self):
        rooms = self._space_rooms()
        s = compute_area_schedule(rooms)
        _assert_ok(s)
        expected = 4 * self._W * self._H_ROOM
        assert s["total_gross_area_mm2"] == pytest.approx(expected)

    def test_slab_total_area_matches_schedule_gross_area(self):
        slabs = self._build_slabs()
        rooms = self._space_rooms()
        slab_total = sum(sl["area_mm2"] for sl in slabs)
        s = compute_area_schedule(rooms)
        assert slab_total == pytest.approx(s["total_gross_area_mm2"])
