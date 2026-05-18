"""
Tests for T-111: compound walls, parametric doors/windows, sloped slabs.

DoD: each parametric type flexes across a realistic parameter range and
IFC-exports correctly; pytest.
"""
from __future__ import annotations

import math
import pytest

from kerf_bim.walls import (
    CompoundWall,
    WallLayer,
    WallInstance,
    WallValidationError,
    make_compound_wall,
    make_wall_instance,
    wall_to_ifc_dict,
    PRESET_WALLS,
)
from kerf_bim.openings import (
    DoorType,
    DoorInstance,
    WindowType,
    WindowInstance,
    OpeningValidationError,
    make_door_type,
    make_door_instance,
    make_window_type,
    make_window_instance,
    door_to_ifc_dict,
    window_to_ifc_dict,
    PRESET_DOOR_TYPES,
    PRESET_WINDOW_TYPES,
)
from kerf_bim.slabs import (
    SlabLayer,
    SlabType,
    SlabInstance,
    SlabValidationError,
    make_slab_type,
    make_slab_instance,
    slab_to_ifc_dict,
    PRESET_SLAB_TYPES,
)


# =============================================================================
# T-111A  Compound walls
# =============================================================================

class TestCompoundWall:
    def _brick_veneer(self) -> CompoundWall:
        return make_compound_wall(
            "Ext - Brick Veneer 350",
            [
                ("brick_clay",         110.0, "finish1"),
                ("air_gap",             50.0, "air_gap"),
                ("insulation_rockwool", 90.0, "thermal"),
                ("concrete_reinforced", 100.0, "structure"),
            ],
        )

    def test_total_thickness(self):
        w = self._brick_veneer()
        assert abs(w.total_thickness - 350.0) < 1e-6

    def test_structure_thickness(self):
        w = self._brick_veneer()
        assert abs(w.structure_thickness - 100.0) < 1e-6

    def test_layer_summary_length(self):
        w = self._brick_veneer()
        s = w.layer_summary()
        assert len(s) == 4

    def test_layer_summary_keys(self):
        w = self._brick_veneer()
        for lay_dict in w.layer_summary():
            assert "function" in lay_dict
            assert "material" in lay_dict
            assert "thickness_mm" in lay_dict

    def test_no_structure_layer_raises(self):
        with pytest.raises(WallValidationError):
            make_compound_wall("Bad", [("brick_clay", 100.0, "finish1")])

    def test_empty_layers_raises(self):
        with pytest.raises(WallValidationError):
            CompoundWall(name="X", layers=[])

    def test_negative_thickness_raises(self):
        with pytest.raises(WallValidationError):
            WallLayer(material="brick_clay", thickness=-10.0, function="structure")

    def test_invalid_function_raises(self):
        with pytest.raises(WallValidationError):
            WallLayer(material="brick_clay", thickness=100.0, function="bad_func")

    def test_thermal_resistance_type(self):
        w = self._brick_veneer()
        r = w.thermal_resistance
        # Returns float or None — if catalogue available, should be positive float
        if r is not None:
            assert r > 0


class TestWallInstance:
    def _simple_wall_type(self) -> CompoundWall:
        return make_compound_wall(
            "Simple",
            [("concrete_reinforced", 200.0, "structure")],
        )

    def test_basic_instance(self):
        wt = self._simple_wall_type()
        wi = make_wall_instance(wt, [0, 0], [5000, 0], height=3000.0)
        assert abs(wi.length - 5000.0) < 1e-6
        assert abs(wi.thickness - 200.0) < 1e-6
        assert abs(wi.effective_height - 3000.0) < 1e-6

    def test_offsets_applied(self):
        wt = self._simple_wall_type()
        wi = make_wall_instance(wt, [0, 0], [5000, 0], height=3000.0,
                                base_offset=100.0, top_offset=-50.0)
        assert abs(wi.effective_height - (3000.0 - 50.0 - 100.0)) < 1e-6

    def test_zero_height_raises(self):
        wt = self._simple_wall_type()
        with pytest.raises(WallValidationError):
            WallInstance(wall_type=wt, start=[0, 0], end=[5000, 0], height=0.0)

    def test_ifc_dict_keys(self):
        wt = self._simple_wall_type()
        wi = make_wall_instance(wt, [0, 0], [5000, 0], height=3000.0)
        d = wall_to_ifc_dict(wi)
        for key in ("from", "to", "height", "thickness", "level", "name",
                    "wall_type", "layers"):
            assert key in d, f"Missing key '{key}' in wall IFC dict"

    def test_ifc_dict_dimensions(self):
        wt = self._simple_wall_type()
        wi = make_wall_instance(wt, [1000, 2000], [6000, 2000], height=3000.0)
        d = wall_to_ifc_dict(wi)
        assert d["thickness"] == pytest.approx(200.0)
        assert d["height"] == pytest.approx(3000.0)
        assert d["from"] == [1000.0, 2000.0]
        assert d["to"] == [6000.0, 2000.0]


class TestPresetWalls:
    def test_preset_walls_count(self):
        assert len(PRESET_WALLS) >= 4

    def test_all_have_structure_layer(self):
        for name, w in PRESET_WALLS.items():
            assert any(lay.function == "structure" for lay in w.layers), (
                f"Preset wall '{name}' has no structure layer"
            )

    def test_all_export_ifc(self):
        for name, wt in PRESET_WALLS.items():
            wi = make_wall_instance(wt, [0, 0], [5000, 0], height=3000.0)
            d = wall_to_ifc_dict(wi)
            assert d["thickness"] > 0
            assert d["height"] > 0

    def test_parametric_range(self):
        """Wall flexes across height range 2400..4800 mm."""
        wt = next(iter(PRESET_WALLS.values()))
        for h in (2400.0, 3000.0, 3600.0, 4200.0, 4800.0):
            wi = make_wall_instance(wt, [0, 0], [5000, 0], height=h)
            d = wall_to_ifc_dict(wi)
            assert d["height"] == pytest.approx(h)


# =============================================================================
# T-111B  Doors and windows
# =============================================================================

class TestDoorType:
    def test_default_door(self):
        dt = make_door_type("Single Swing - 900 × 2100", width=900.0, height=2100.0)
        assert dt.width == 900.0
        assert dt.height == 2100.0
        assert dt.rough_opening_width > dt.width
        assert dt.rough_opening_height > dt.height

    def test_invalid_operation(self):
        with pytest.raises(Exception):
            DoorType(name="X", operation="bad_op", width=900.0, height=2100.0)

    def test_zero_width_raises(self):
        with pytest.raises(Exception):
            DoorType(name="X", operation="single_swing", width=0.0, height=2100.0)

    def test_fire_rated_door(self):
        dt = make_door_type("Fire Door", width=900.0, height=2100.0,
                            fire_rating="60 min",
                            panel_material="steel_a36")
        assert dt.fire_rating == "60 min"
        assert dt.panel_material == "steel_a36"


class TestDoorInstance:
    def _dt(self) -> DoorType:
        return make_door_type("Test", width=900.0, height=2100.0)

    def test_basic_instance(self):
        di = make_door_instance(self._dt(), position=[5000.0, 0.0, 0.0])
        assert di.position == [5000.0, 0.0, 0.0]
        assert di.hand == "right"

    def test_hand_left(self):
        di = make_door_instance(self._dt(), [0, 0, 0], hand="left")
        assert di.hand == "left"

    def test_invalid_hand_raises(self):
        with pytest.raises(Exception):
            DoorInstance(door_type=self._dt(), position=[0, 0, 0], hand="up")

    def test_ifc_dict_keys(self):
        di = make_door_instance(self._dt(), [5000, 0, 0])
        d = door_to_ifc_dict(di)
        for key in ("kind", "level", "position", "width", "height", "name",
                    "operation", "hand", "panel_material", "frame_material"):
            assert key in d

    def test_ifc_dict_kind(self):
        di = make_door_instance(self._dt(), [0, 0, 0])
        assert door_to_ifc_dict(di)["kind"] == "door"


class TestWindowType:
    def test_default_window(self):
        wt = make_window_type("Fixed 1200", width=1200.0, height=1500.0)
        assert wt.clear_opening_width < wt.width
        assert wt.clear_opening_height < wt.height

    def test_invalid_operation(self):
        with pytest.raises(Exception):
            WindowType(name="X", operation="bad_op", width=1200.0, height=1500.0)

    def test_u_value_negative_raises(self):
        with pytest.raises(Exception):
            WindowType(name="X", width=1200.0, height=1500.0, u_value=-1.0)

    def test_shgc_out_of_range_raises(self):
        with pytest.raises(Exception):
            WindowType(name="X", width=1200.0, height=1500.0, shgc=1.5)


class TestWindowInstance:
    def _wt(self) -> WindowType:
        return make_window_type("Test Fixed", width=1200.0, height=1500.0)

    def test_basic_instance(self):
        wi = make_window_instance(self._wt(), [3000.0, 0.0, 900.0])
        assert wi.position[2] == 900.0

    def test_ifc_dict_keys(self):
        wi = make_window_instance(self._wt(), [0, 0, 900])
        d = window_to_ifc_dict(wi)
        for key in ("kind", "level", "position", "width", "height", "name",
                    "operation", "glazing_type", "frame_material"):
            assert key in d

    def test_ifc_dict_kind(self):
        wi = make_window_instance(self._wt(), [0, 0, 900])
        assert window_to_ifc_dict(wi)["kind"] == "window"


class TestPresetOpenings:
    def test_preset_doors_count(self):
        assert len(PRESET_DOOR_TYPES) >= 8

    def test_preset_windows_count(self):
        assert len(PRESET_WINDOW_TYPES) >= 5

    def test_all_doors_export(self):
        for name, dt in PRESET_DOOR_TYPES.items():
            di = make_door_instance(dt, [0, 0, 0])
            d = door_to_ifc_dict(di)
            assert d["width"] > 0
            assert d["height"] > 0

    def test_all_windows_export(self):
        for name, wt in PRESET_WINDOW_TYPES.items():
            wi = make_window_instance(wt, [0, 0, 900])
            d = window_to_ifc_dict(wi)
            assert d["width"] > 0
            assert d["height"] > 0

    def test_parametric_range_doors(self):
        """Door width flexes from 610 to 2000 mm."""
        for w in (610.0, 762.0, 914.4, 1200.0, 1800.0, 2000.0):
            dt = make_door_type(f"Test {w}", width=w, height=2100.0)
            di = make_door_instance(dt, [0, 0, 0])
            d = door_to_ifc_dict(di)
            assert d["width"] == pytest.approx(w)

    def test_parametric_range_windows(self):
        """Window height flexes from 600 to 2400 mm."""
        for h in (600.0, 900.0, 1200.0, 1800.0, 2400.0):
            wt = make_window_type(f"Test {h}", width=1200.0, height=h)
            wi = make_window_instance(wt, [0, 0, 900])
            d = window_to_ifc_dict(wi)
            assert d["height"] == pytest.approx(h)


# =============================================================================
# T-111C  Slabs
# =============================================================================

class TestSlabType:
    def _flat_slab(self) -> SlabType:
        return make_slab_type(
            "RC 200",
            [("concrete_reinforced", 200.0, "structure")],
        )

    def _composite_slab(self) -> SlabType:
        return make_slab_type(
            "RC 180 + Screed 40",
            [
                ("concrete_reinforced", 180.0, "structure"),
                ("plaster_cement", 40.0, "substrate"),
            ],
        )

    def test_total_thickness_flat(self):
        st = self._flat_slab()
        assert abs(st.total_thickness - 200.0) < 1e-6

    def test_total_thickness_composite(self):
        st = self._composite_slab()
        assert abs(st.total_thickness - 220.0) < 1e-6

    def test_structure_thickness(self):
        st = self._composite_slab()
        assert abs(st.structure_thickness - 180.0) < 1e-6

    def test_no_structure_raises(self):
        with pytest.raises(SlabValidationError):
            make_slab_type("Bad", [("concrete_reinforced", 200.0, "substrate")])

    def test_slope_stored(self):
        st = make_slab_type("Ramp", [("concrete_reinforced", 200.0, "structure")],
                            slope=5.0)
        assert abs(st.slope - 5.0) < 1e-9

    def test_slope_out_of_range_raises(self):
        with pytest.raises(SlabValidationError):
            make_slab_type("Bad", [("concrete_reinforced", 200.0, "structure")],
                           slope=50.0)


class TestSlabInstance:
    def _flat_slab_type(self) -> SlabType:
        return make_slab_type("RC 200", [("concrete_reinforced", 200.0, "structure")])

    def _boundary(self):
        return [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]

    def test_plan_area(self):
        st = self._flat_slab_type()
        si = make_slab_instance(st, self._boundary())
        assert abs(si.plan_area - 5000.0 * 4000.0) < 1.0

    def test_flat_slab_height_constant(self):
        st = self._flat_slab_type()
        si = make_slab_instance(st, self._boundary())
        assert si.height_at_point(0, 0) == pytest.approx(0.0)
        assert si.height_at_point(5000, 4000) == pytest.approx(0.0)

    def test_sloped_slab_height_varies(self):
        st = make_slab_type("Ramp 5°", [("concrete_reinforced", 200.0, "structure")],
                            slope=5.0)
        boundary = [[0, 0], [10000, 0], [10000, 4000], [0, 4000]]
        si = make_slab_instance(st, boundary, slope_direction=[1.0, 0.0])
        # At centroid x=5000, height=0; further along slope it rises
        h_near = si.height_at_point(0, 2000)     # before centroid
        h_far  = si.height_at_point(10000, 2000) # after centroid
        assert h_far > h_near, "Sloped slab height should increase in slope direction"

    def test_too_few_boundary_points_raises(self):
        st = self._flat_slab_type()
        with pytest.raises(SlabValidationError):
            make_slab_instance(st, [[0, 0], [5000, 0]])

    def test_ifc_dict_keys(self):
        st = self._flat_slab_type()
        si = make_slab_instance(st, self._boundary())
        d = slab_to_ifc_dict(si)
        for key in ("boundary", "thickness", "level", "name", "slab_type",
                    "function", "slope_deg", "layers"):
            assert key in d

    def test_ifc_dict_ifc_compatible(self):
        """IFC dict must have at least 3 boundary points."""
        st = self._flat_slab_type()
        si = make_slab_instance(st, self._boundary())
        d = slab_to_ifc_dict(si)
        assert len(d["boundary"]) >= 3
        assert d["thickness"] > 0


class TestPresetSlabs:
    def test_preset_slabs_count(self):
        assert len(PRESET_SLAB_TYPES) >= 4

    def test_all_export(self):
        boundary = [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]
        for name, st in PRESET_SLAB_TYPES.items():
            si = make_slab_instance(st, boundary)
            d = slab_to_ifc_dict(si)
            assert d["thickness"] > 0

    def test_roof_type_present(self):
        roofs = [st for st in PRESET_SLAB_TYPES.values() if st.function == "roof"]
        assert len(roofs) >= 1

    def test_ramp_slab_has_slope(self):
        ramps = [st for st in PRESET_SLAB_TYPES.values() if st.slope != 0.0]
        assert len(ramps) >= 1
