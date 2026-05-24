"""Tests for kerf_bim.spaces — BIM space / zone / room module."""

import math
import pytest
from kerf_bim.spaces import (
    Space,
    SpaceValidationError,
    space_area,
    space_volume,
    space_schedule,
)


# ---------------------------------------------------------------------------
# space_area
# ---------------------------------------------------------------------------

def test_space_area_rectangle():
    # 4 m × 3 m = 12 m²
    boundary = [[0, 0], [4, 0], [4, 3], [0, 3]]
    assert abs(space_area(boundary) - 12.0) < 1e-10


def test_space_area_triangle():
    # Right triangle: base=6, height=4 → area = 12 m²
    boundary = [[0, 0], [6, 0], [0, 4]]
    assert abs(space_area(boundary) - 12.0) < 1e-10


def test_space_area_l_shape():
    # L-shape: 6×2 lower strip + 3×2 upper strip = 12+6 = 18 m²
    boundary = [[0, 0], [6, 0], [6, 2], [3, 2], [3, 4], [0, 4]]
    assert abs(space_area(boundary) - 18.0) < 1e-10


def test_space_area_too_few_points():
    assert space_area([[0, 0], [1, 0]]) == 0.0


def test_space_area_single_point():
    assert space_area([[0, 0]]) == 0.0


# ---------------------------------------------------------------------------
# space_volume
# ---------------------------------------------------------------------------

def test_space_volume_basic():
    boundary = [[0, 0], [5, 0], [5, 4], [0, 4]]  # 20 m²
    vol = space_volume(boundary, 2.7)
    assert abs(vol - 54.0) < 1e-9


def test_space_volume_zero_height():
    boundary = [[0, 0], [5, 0], [5, 4], [0, 4]]
    assert space_volume(boundary, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Space dataclass
# ---------------------------------------------------------------------------

def test_space_basic_construction():
    sp = Space(name="Living Room", boundary=[[0,0],[5,0],[5,4],[0,4]])
    assert abs(sp.area_m2 - 20.0) < 1e-9
    assert abs(sp.volume_m3 - 20.0 * 2.7) < 1e-9
    assert sp.level == "L1"
    assert sp.program == "residential"
    assert sp.occupancy is None


def test_space_with_occupancy():
    sp = Space(
        name="Conference Room",
        boundary=[[0,0],[8,0],[8,6],[0,6]],
        level="L2",
        height_m=3.2,
        program="office",
        occupancy_per_m2=0.05,
    )
    area = sp.area_m2   # 48 m²
    assert abs(area - 48.0) < 1e-9
    expected_occ = math.ceil(48.0 * 0.05)   # ceil(2.4) = 3
    assert sp.occupancy == expected_occ


def test_space_to_dict_fields():
    sp = Space(
        name="Bedroom",
        boundary=[[0,0],[4,0],[4,3],[0,3]],
        level="L1",
        global_id="abc123",
    )
    d = sp.to_dict()
    assert d["name"] == "Bedroom"
    assert d["level"] == "L1"
    assert "area_m2" in d
    assert "volume_m3" in d
    assert d["global_id"] == "abc123"


def test_space_validation_empty_name():
    with pytest.raises(SpaceValidationError, match="name"):
        Space(name="", boundary=[[0,0],[1,0],[1,1]])


def test_space_validation_too_few_points():
    with pytest.raises(SpaceValidationError, match="boundary"):
        Space(name="X", boundary=[[0,0],[1,0]])


def test_space_validation_negative_height():
    with pytest.raises(SpaceValidationError, match="height"):
        Space(name="X", boundary=[[0,0],[1,0],[1,1]], height_m=-1.0)


# ---------------------------------------------------------------------------
# space_schedule
# ---------------------------------------------------------------------------

def test_space_schedule_basic():
    spaces = [
        Space("Kitchen",  [[0,0],[4,0],[4,3],[0,3]], level="L1"),
        Space("Bedroom",  [[0,0],[4,0],[4,4],[0,4]], level="L1"),
        Space("Hallway",  [[0,0],[6,0],[6,1],[0,1]], level="L2"),
    ]
    result = space_schedule(spaces)
    assert result["ok"] is True
    assert len(result["rows"]) == 3
    # Totals area: 12 + 16 + 6 = 34 m²
    assert abs(result["totals"]["area_m2"] - 34.0) < 1e-6
    assert "L1" in result["by_level"]
    assert "L2" in result["by_level"]
    assert result["by_level"]["L1"]["count"] == 2
    assert result["by_level"]["L2"]["count"] == 1


def test_space_schedule_with_occupancy():
    spaces = [
        Space("Office", [[0,0],[10,0],[10,5],[0,5]],
              occupancy_per_m2=0.1, program="office"),
    ]
    result = space_schedule(spaces)
    assert result["totals"].get("occupancy") == math.ceil(50.0 * 0.1)  # ceil(5) = 5
