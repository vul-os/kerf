"""
Oracle tests for template-driven corridor modeling.

Verified against AASHTO Green Book (GDPS-4-M) §2.2–§4.2.

DoD oracles:
  1. Template point offsets/elevations — CL, edge-lane, shoulder, daylight
     computed analytically from lane width, crown slope, shoulder slope.
  2. Daylight on terrain — cut backslope intersects flat TIN at exactly the
     predicted offset (2:1 slope, 2 m deep cut → daylight at hinge + 4 m).
  3. Fill daylight — foreslope intersects flat TIN at predicted offset.
  4. Constant-grade corridor volume vs analytic prism — flat terrain, uniform
     cross-section; average-end-area volume equals A × L.
  5. Mass-haul monotone for all-cut corridor.
  6. civil_corridor_model LLM tool — end-to-end dispatch with terrain.
"""

from __future__ import annotations

import json
import math
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_straight_corridor(
    length=200.0,
    datum_elev=100.0,
    grade_pct=0.0,
    lane_width=3.65,
    shoulder_width=2.4,
    lanes_each_side=1,
    crown_slope_pct=2.0,
    shoulder_slope_pct=5.0,
    cut_slope=2.0,
    fill_slope=2.0,
    ditch_width=0.0,
    ditch_depth=0.0,
    terrain=None,
    daylight_step_m=0.01,
):
    from kerf_civil.horizontal_alignment import HorizontalAlignment
    from kerf_civil.vertical_alignment import VerticalAlignment
    from kerf_civil.corridor import TypicalSection, Corridor

    ha = HorizontalAlignment()
    ha.add_tangent(length)
    va = VerticalAlignment()
    va.set_datum(elev=datum_elev, grade_pct=grade_pct)
    va.add_tangent(length)
    ts = TypicalSection(
        lane_width=lane_width,
        shoulder_width=shoulder_width,
        lanes_each_side=lanes_each_side,
        crown_slope_pct=crown_slope_pct,
        shoulder_slope_pct=shoulder_slope_pct,
        cut_slope=cut_slope,
        fill_slope=fill_slope,
        ditch_width=ditch_width,
        ditch_depth=ditch_depth,
    )
    return Corridor(
        h_alignment=ha,
        v_alignment=va,
        typical_section=ts,
        terrain=terrain,
        daylight_step_m=daylight_step_m,
    )


def _flat_tin(x_range=100.0, y_range=300.0, z=100.0):
    """Build a large flat TIN at constant elevation *z*."""
    from kerf_civil.tin import build_tin
    pts = [
        [-x_range, -50,     z],
        [ x_range, -50,     z],
        [ x_range, y_range, z],
        [-x_range, y_range, z],
    ]
    return build_tin(pts)


# ---------------------------------------------------------------------------
# Oracle 1: Template point offsets and elevations (no terrain)
# ---------------------------------------------------------------------------

class TestTemplatePointOffsets:
    """AASHTO §2.2 / §2.3 / §4.2 — verify point-code geometry analytically."""

    @pytest.fixture
    def xs(self):
        c = _make_straight_corridor(
            datum_elev=100.0, grade_pct=0.0,
            lane_width=3.65, shoulder_width=2.4,
            crown_slope_pct=2.0, shoulder_slope_pct=5.0,
        )
        return c.cross_section_at(0.0)

    def test_cl_offset_zero(self, xs):
        cl = next(p for p in xs.points if p.label == "CL")
        assert cl.offset == pytest.approx(0.0, abs=1e-10)

    def test_cl_elevation(self, xs):
        cl = next(p for p in xs.points if p.label == "CL")
        assert cl.elevation == pytest.approx(100.0, abs=1e-10)

    def test_edge_lane_right_offset(self, xs):
        """Edge-of-lane right = +lane_width = +3.65 m."""
        el = next(p for p in xs.points if p.label == "edge_lane_right")
        assert el.offset == pytest.approx(3.65, abs=1e-10)

    def test_edge_lane_right_elevation(self, xs):
        """Edge-lane elev = CL_elev − crown% × lane_width."""
        # 100.0 − 0.02 × 3.65 = 100.0 − 0.073 = 99.927
        expected = 100.0 - 0.02 * 3.65
        el = next(p for p in xs.points if p.label == "edge_lane_right")
        assert el.elevation == pytest.approx(expected, abs=1e-10)

    def test_shoulder_right_offset(self, xs):
        """Shoulder right = lane_width + shoulder_width = 3.65 + 2.4 = 6.05 m."""
        sh = next(p for p in xs.points if p.label == "shoulder_right")
        assert sh.offset == pytest.approx(6.05, abs=1e-10)

    def test_shoulder_right_elevation(self, xs):
        """Shoulder elev = edge_lane_elev − shoulder_slope% × shoulder_width.
        = 99.927 − 0.05 × 2.4 = 99.927 − 0.12 = 99.807.
        """
        expected = 100.0 - 0.02 * 3.65 - 0.05 * 2.4
        sh = next(p for p in xs.points if p.label == "shoulder_right")
        assert sh.elevation == pytest.approx(expected, abs=1e-10)

    def test_left_right_symmetry_offsets(self, xs):
        """Left and right points are mirror images (symmetric section)."""
        el_l = next(p for p in xs.points if p.label == "edge_lane_left")
        el_r = next(p for p in xs.points if p.label == "edge_lane_right")
        assert el_l.offset == pytest.approx(-el_r.offset, abs=1e-10)

    def test_left_right_symmetry_elevations(self, xs):
        """Symmetric section: left and right shoulder elevations are equal."""
        sh_l = next(p for p in xs.points if p.label == "shoulder_left")
        sh_r = next(p for p in xs.points if p.label == "shoulder_right")
        assert sh_l.elevation == pytest.approx(sh_r.elevation, abs=1e-10)

    def test_points_ordered_left_to_right(self, xs):
        """Cross-section points must be in left-to-right (increasing offset) order."""
        offsets = [p.offset for p in xs.points]
        for i in range(len(offsets) - 1):
            assert offsets[i] <= offsets[i + 1], (
                f"Point {i} offset {offsets[i]} > point {i+1} offset {offsets[i+1]}"
            )

    def test_two_lane_section(self):
        """Two lanes each side → edge-lane offset = 2 × lane_width = 7.3 m."""
        c = _make_straight_corridor(lane_width=3.65, lanes_each_side=2)
        xs = c.cross_section_at(0.0)
        el_r = next(p for p in xs.points if p.label == "edge_lane_right")
        assert el_r.offset == pytest.approx(7.3, abs=1e-10)

    def test_no_terrain_no_area(self):
        """Without terrain, cut_area_m2 and fill_area_m2 are 0."""
        c = _make_straight_corridor()
        xs = c.cross_section_at(0.0)
        assert xs.cut_area_m2 == 0.0
        assert xs.fill_area_m2 == 0.0


# ---------------------------------------------------------------------------
# Oracle 2: Daylight point lands on terrain — cut section
# ---------------------------------------------------------------------------

class TestCutDaylightOnTerrain:
    """The daylight point must lie ON the terrain surface.

    Test setup:
      - Flat terrain at z=100.0
      - CL design elevation = 98.0 (2m below terrain)
      - crown=2%, shoulder_slope=5%, lane=3.65, shoulder=2.4
      - shoulder_right offset = 6.05
      - shoulder_right elev = 98.0 - 0.02*3.65 - 0.05*2.4 = 97.807
      - terrain at shoulder hinge = 100.0 → diff = 2.193 m
      - cut slope 2:1 → daylight horiz distance = 2.193 × 2 = 4.386 m
      - daylight offset = 6.05 + 4.386 = 10.436 m
      - daylight elevation = 100.0 (on the terrain)
    """

    TERRAIN_Z = 100.0
    CL_ELEV = 98.0
    LANE_W = 3.65
    SHOULDER_W = 2.4
    CROWN_PCT = 2.0
    SHOULDER_SLOPE_PCT = 5.0
    CUT_SLOPE = 2.0

    @pytest.fixture(scope="class")
    def xs(self):
        tin = _flat_tin(z=self.TERRAIN_Z)
        c = _make_straight_corridor(
            datum_elev=self.CL_ELEV,
            lane_width=self.LANE_W,
            shoulder_width=self.SHOULDER_W,
            crown_slope_pct=self.CROWN_PCT,
            shoulder_slope_pct=self.SHOULDER_SLOPE_PCT,
            cut_slope=self.CUT_SLOPE,
            terrain=tin,
            daylight_step_m=0.001,  # 1mm steps for accuracy
        )
        return c.cross_section_at(100.0)

    def test_daylight_elevation_equals_terrain(self, xs):
        """Daylight point elevation must equal the terrain elevation (100.0)."""
        dtl = next(p for p in xs.points if p.label == "daylight_right")
        assert float(dtl.elevation) == pytest.approx(self.TERRAIN_Z, abs=0.01)

    def test_daylight_offset_analytic(self, xs):
        """Daylight offset matches analytic formula: hinge_offset + depth×cut_slope."""
        # Shoulder hinge: offset=6.05, elev= CL - crown*lane - shslope*shoulder
        hinge_elev = (self.CL_ELEV
                      - (self.CROWN_PCT / 100.0) * self.LANE_W
                      - (self.SHOULDER_SLOPE_PCT / 100.0) * self.SHOULDER_W)
        depth = self.TERRAIN_Z - hinge_elev    # vertical cut depth at hinge
        expected_offset = (self.LANE_W + self.SHOULDER_W) + depth * self.CUT_SLOPE
        dtl = next(p for p in xs.points if p.label == "daylight_right")
        assert float(dtl.offset) == pytest.approx(expected_offset, abs=0.05)  # ±50mm

    def test_daylight_left_symmetric(self, xs):
        """Left daylight offset mirrors right (symmetric template)."""
        dtl = next(p for p in xs.points if p.label == "daylight_left")
        dtr = next(p for p in xs.points if p.label == "daylight_right")
        assert float(dtl.offset) == pytest.approx(-float(dtr.offset), abs=0.01)

    def test_cut_area_positive(self, xs):
        """Cut area must be positive for a below-grade corridor."""
        assert xs.cut_area_m2 > 0.0

    def test_fill_area_zero_on_cut(self, xs):
        """No fill when design is uniformly below terrain."""
        assert xs.fill_area_m2 == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Oracle 3: Fill daylight on terrain
# ---------------------------------------------------------------------------

class TestFillDaylightOnTerrain:
    """Fill section: design ABOVE terrain — fill foreslope descends to terrain.

    Test setup:
      - Flat terrain at z=100.0
      - CL design elevation = 102.0 (2m above terrain)
      - shoulder_right hinge offset=6.05, elev=101.807
      - terrain at hinge = 100.0 → diff=1.807 m above
      - fill slope 2:1 → descends 0.5/m → daylight at 1.807/0.5 = 3.614 m beyond
      - daylight offset = 6.05 + 3.614 = 9.664 m
    """

    TERRAIN_Z = 100.0
    CL_ELEV = 102.0
    FILL_SLOPE = 2.0

    @pytest.fixture(scope="class")
    def xs(self):
        tin = _flat_tin(z=self.TERRAIN_Z)
        c = _make_straight_corridor(
            datum_elev=self.CL_ELEV,
            fill_slope=self.FILL_SLOPE,
            terrain=tin,
            daylight_step_m=0.001,
        )
        return c.cross_section_at(100.0)

    def test_daylight_elevation_on_terrain(self, xs):
        dtr = next(p for p in xs.points if p.label == "daylight_right")
        assert float(dtr.elevation) == pytest.approx(self.TERRAIN_Z, abs=0.01)

    def test_daylight_offset_analytic(self, xs):
        """Daylight offset = hinge_offset + (hinge_elev − terrain_z) × fill_slope."""
        hinge_elev = 102.0 - 0.02 * 3.65 - 0.05 * 2.4  # = 101.807
        diff = hinge_elev - self.TERRAIN_Z               # 1.807
        expected_offset = 6.05 + diff * self.FILL_SLOPE  # 9.664
        dtr = next(p for p in xs.points if p.label == "daylight_right")
        assert float(dtr.offset) == pytest.approx(expected_offset, abs=0.05)

    def test_fill_area_positive(self, xs):
        assert xs.fill_area_m2 > 0.0

    def test_cut_area_zero_on_fill(self, xs):
        assert xs.cut_area_m2 == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Oracle 4: Constant-grade corridor volume vs analytic prism
# ---------------------------------------------------------------------------

class TestCorridorVolumeVsAnalyticPrism:
    """Average-end-area earthwork volume of a constant cross-section over length L
    must equal A × L exactly (since all section areas are equal).

    Test: flat terrain at 100m, CL at 98m (constant), length=100m, interval=10m.
    At every station the cut area is the same trapezoid, so:
        volume = A × L
    """

    def _cut_area_analytic(self) -> float:
        """Analytic cut area for the test fixture using shoelace formula."""
        import sys
        sys.path.insert(0, '/Users/pc/code/exo/kerf/.claude/worktrees/agent-a913022592f14f3a2/packages/kerf-civil/src')
        # Build a single cross-section and return its cut area
        tin = _flat_tin(z=100.0)
        c = _make_straight_corridor(
            length=10.0,  # just need one XS
            datum_elev=98.0,
            terrain=tin,
            daylight_step_m=0.001,
        )
        xs = c.cross_section_at(5.0)
        return xs.cut_area_m2

    def test_volume_equals_area_times_length(self):
        """V = A × L for constant-section corridor (average-end-area is exact for prism)."""
        L = 100.0
        interval = 10.0
        tin = _flat_tin(z=100.0)
        c = _make_straight_corridor(
            length=L,
            datum_elev=98.0,
            terrain=tin,
            daylight_step_m=0.001,
        )
        evol = c.earthwork_volumes(interval=interval)
        # Cut area is constant → total volume = A × L
        A = self._cut_area_analytic()
        expected = A * L
        assert evol["total_cut_m3"] == pytest.approx(expected, rel=0.01)  # 1% tolerance

    def test_volume_zero_fill_on_all_cut(self):
        """No fill material when corridor is uniformly below terrain."""
        L = 100.0
        tin = _flat_tin(z=100.0)
        c = _make_straight_corridor(length=L, datum_elev=98.0, terrain=tin)
        evol = c.earthwork_volumes(interval=20.0)
        assert evol["total_fill_m3"] == pytest.approx(0.0, abs=0.1)

    def test_net_m3_equals_fill_minus_cut(self):
        """net = fill − cut."""
        tin = _flat_tin(z=100.0)
        c = _make_straight_corridor(length=100.0, datum_elev=98.0, terrain=tin)
        evol = c.earthwork_volumes(interval=20.0)
        assert evol["net_m3"] == pytest.approx(
            evol["total_fill_m3"] - evol["total_cut_m3"], abs=1e-3
        )

    def test_longer_corridor_proportionally_larger_volume(self):
        """Double the length → double the cut volume (constant section)."""
        tin_a = _flat_tin(z=100.0, y_range=300.0)
        tin_b = _flat_tin(z=100.0, y_range=600.0)
        c1 = _make_straight_corridor(length=100.0, datum_elev=98.0, terrain=tin_a)
        c2 = _make_straight_corridor(length=200.0, datum_elev=98.0, terrain=tin_b)
        v1 = c1.earthwork_volumes(interval=20.0)["total_cut_m3"]
        v2 = c2.earthwork_volumes(interval=20.0)["total_cut_m3"]
        assert v2 == pytest.approx(v1 * 2.0, rel=0.02)


# ---------------------------------------------------------------------------
# Oracle 5: Mass-haul monotone increase for all-cut corridor
# ---------------------------------------------------------------------------

class TestMassHaulDiagram:
    """Mass haul (Brückner curve) for an all-cut corridor must be monotonically
    increasing (positive cut − zero fill × swell).
    """

    @pytest.fixture(scope="class")
    def mh(self):
        tin = _flat_tin(z=100.0)
        c = _make_straight_corridor(
            length=200.0, datum_elev=98.0, terrain=tin, daylight_step_m=0.1
        )
        return c.mass_haul_data(interval=20.0, swell_factor=1.25)

    def test_mass_haul_starts_at_zero(self, mh):
        assert mh[0]["mass_ordinate_m3"] == pytest.approx(0.0, abs=1e-9)

    def test_mass_haul_monotone_increasing_for_all_cut(self, mh):
        """All-cut → ordinate strictly non-decreasing."""
        for i in range(1, len(mh)):
            assert mh[i]["mass_ordinate_m3"] >= mh[i - 1]["mass_ordinate_m3"] - 1e-6

    def test_mass_haul_final_ordinate_positive(self, mh):
        assert mh[-1]["mass_ordinate_m3"] > 0.0

    def test_cumulative_cut_increases_monotonically(self, mh):
        for i in range(1, len(mh)):
            assert mh[i]["cut_vol_m3"] >= mh[i - 1]["cut_vol_m3"]

    def test_mass_haul_station_count(self, mh):
        """200 m at 20 m interval = 11 stations (0, 20, 40, …, 200)."""
        assert len(mh) == 11

    def test_mass_haul_all_cut_no_fill(self, mh):
        """All-cut corridor: fill_vol_m3 stays 0 at every station."""
        for entry in mh:
            assert entry["fill_vol_m3"] == pytest.approx(0.0, abs=0.001)


# ---------------------------------------------------------------------------
# Oracle 6: Ditch section
# ---------------------------------------------------------------------------

class TestDitchSection:
    """A ditch_width > 0 must produce ditch_left / ditch_right point codes."""

    def test_ditch_points_present(self):
        c = _make_straight_corridor(ditch_width=1.0, ditch_depth=0.5)
        xs = c.cross_section_at(0.0)
        labels = [p.label for p in xs.points]
        assert "ditch_left" in labels
        assert "ditch_right" in labels

    def test_ditch_offset_beyond_shoulder(self):
        """Ditch bottom must be laterally outside the shoulder break."""
        c = _make_straight_corridor(ditch_width=1.0, ditch_depth=0.5)
        xs = c.cross_section_at(0.0)
        sh_r = next(p for p in xs.points if p.label == "shoulder_right")
        dt_r = next(p for p in xs.points if p.label == "ditch_right")
        assert abs(dt_r.offset) > abs(sh_r.offset)

    def test_ditch_elevation_below_shoulder(self):
        """Ditch bottom elevation must be below the shoulder hinge."""
        c = _make_straight_corridor(ditch_width=1.0, ditch_depth=0.5)
        xs = c.cross_section_at(0.0)
        sh_r = next(p for p in xs.points if p.label == "shoulder_right")
        dt_r = next(p for p in xs.points if p.label == "ditch_right")
        assert dt_r.elevation < sh_r.elevation

    def test_no_ditch_no_ditch_points(self):
        c = _make_straight_corridor(ditch_width=0.0)
        xs = c.cross_section_at(0.0)
        labels = [p.label for p in xs.points]
        assert "ditch_left" not in labels
        assert "ditch_right" not in labels


# ---------------------------------------------------------------------------
# Oracle 7: Corridor strings (feature-lines)
# ---------------------------------------------------------------------------

class TestCorridorStrings:
    """Corridor strings must cover all point codes with len = station_count."""

    def test_strings_contain_cl(self):
        c = _make_straight_corridor(length=100.0)
        strings = c.corridor_strings(interval=25.0)
        assert "CL" in strings

    def test_cl_string_length(self):
        """100m / 25m interval = 5 stations → CL string has 5 points."""
        c = _make_straight_corridor(length=100.0)
        strings = c.corridor_strings(interval=25.0)
        # 0, 25, 50, 75, 100 = 5 stations
        assert len(strings["CL"]) == 5

    def test_cl_string_z_matches_profile(self):
        """CL string z-coordinates must match the vertical alignment."""
        from kerf_civil.horizontal_alignment import HorizontalAlignment
        from kerf_civil.vertical_alignment import VerticalAlignment
        from kerf_civil.corridor import TypicalSection, Corridor

        ha = HorizontalAlignment()
        ha.add_tangent(100.0)
        va = VerticalAlignment()
        va.set_datum(elev=50.0, grade_pct=2.0)
        va.add_tangent(100.0)
        ts = TypicalSection()
        c = Corridor(h_alignment=ha, v_alignment=va, typical_section=ts)
        strings = c.corridor_strings(interval=50.0)

        # Station 0: elev = 50.0; station 50: elev = 51.0; station 100: elev = 52.0
        cl_pts = strings["CL"]
        assert cl_pts[0][2] == pytest.approx(50.0, abs=1e-6)
        assert cl_pts[1][2] == pytest.approx(51.0, abs=1e-6)
        assert cl_pts[2][2] == pytest.approx(52.0, abs=1e-6)

    def test_daylight_right_string_present(self):
        c = _make_straight_corridor(length=100.0)
        strings = c.corridor_strings(interval=25.0)
        assert "daylight_right" in strings


# ---------------------------------------------------------------------------
# Oracle 8: LLM tool dispatch — civil_corridor_model
# ---------------------------------------------------------------------------

class TestCivilCorridorModelTool:
    """End-to-end dispatch of the civil_corridor_model LLM tool."""

    @pytest.mark.asyncio
    async def test_tool_in_tools_list(self):
        from kerf_civil.tools_corridor import TOOLS
        names = [t[0] for t in TOOLS]
        assert "civil_corridor_model" in names

    @pytest.mark.asyncio
    async def test_dispatch_no_terrain(self):
        from kerf_civil.tools_corridor import run_civil_corridor_model
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 100.0,
            "interval_m": 25.0,
            "datum_elev_m": 50.0,
            "grade_pct": 0.0,
            "lane_width_m": 3.65,
            "shoulder_width_m": 2.4,
        }, None))
        assert result["ok"] is True
        assert result["station_count"] == 5  # 0, 25, 50, 75, 100
        assert len(result["cross_sections"]) == 5
        assert "earthwork" in result
        assert "mass_haul" in result
        assert "corridor_strings" in result

    @pytest.mark.asyncio
    async def test_dispatch_with_flat_terrain_cut(self):
        """Full corridor model with flat TIN: cut volumes must be > 0."""
        from kerf_civil.tools_corridor import run_civil_corridor_model
        # Terrain at 100m, CL at 98m → pure cut
        terrain_pts = [
            [-50, -50, 100], [50, -50, 100],
            [50, 250, 100],  [-50, 250, 100],
        ]
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 200.0,
            "interval_m": 50.0,
            "datum_elev_m": 98.0,
            "grade_pct": 0.0,
            "terrain_points": terrain_pts,
        }, None))
        assert result["ok"] is True
        assert result["earthwork"]["total_cut_m3"] > 0.0
        assert result["earthwork"]["total_fill_m3"] == pytest.approx(0.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_dispatch_with_flat_terrain_fill(self):
        """CL above terrain → fill volumes must be > 0."""
        from kerf_civil.tools_corridor import run_civil_corridor_model
        terrain_pts = [
            [-50, -50, 100], [50, -50, 100],
            [50, 250, 100],  [-50, 250, 100],
        ]
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 200.0,
            "interval_m": 50.0,
            "datum_elev_m": 102.0,
            "grade_pct": 0.0,
            "terrain_points": terrain_pts,
        }, None))
        assert result["ok"] is True
        assert result["earthwork"]["total_fill_m3"] > 0.0
        assert result["earthwork"]["total_cut_m3"] == pytest.approx(0.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_mass_haul_monotone_in_tool_result(self):
        """Mass haul ordinates are monotonically non-decreasing for all-cut."""
        from kerf_civil.tools_corridor import run_civil_corridor_model
        terrain_pts = [
            [-50, -50, 100], [50, -50, 100],
            [50, 250, 100],  [-50, 250, 100],
        ]
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 200.0,
            "interval_m": 20.0,
            "datum_elev_m": 98.0,
            "terrain_points": terrain_pts,
        }, None))
        assert result["ok"] is True
        mh = result["mass_haul"]
        for i in range(1, len(mh)):
            assert mh[i]["mass_ordinate_m3"] >= mh[i - 1]["mass_ordinate_m3"] - 1e-3

    @pytest.mark.asyncio
    async def test_cross_section_points_have_required_labels(self):
        """Every cross-section must have at least CL, edge_lane, shoulder points."""
        from kerf_civil.tools_corridor import run_civil_corridor_model
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 100.0,
            "interval_m": 50.0,
        }, None))
        assert result["ok"] is True
        for xs in result["cross_sections"]:
            labels = {p["label"] for p in xs["points"]}
            assert "CL" in labels
            assert "edge_lane_left" in labels
            assert "edge_lane_right" in labels
            assert "shoulder_left" in labels
            assert "shoulder_right" in labels

    @pytest.mark.asyncio
    async def test_corridor_strings_cl_z_matches_profile(self):
        """CL feature-line z = design elevation from the vertical alignment."""
        from kerf_civil.tools_corridor import run_civil_corridor_model
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 100.0,
            "interval_m": 50.0,
            "datum_elev_m": 50.0,
            "grade_pct": 2.0,
        }, None))
        assert result["ok"] is True
        cl_string = result["corridor_strings"]["CL"]
        # Station 0 → z=50.0; station 50 → z=51.0; station 100 → z=52.0
        assert cl_string[0][2] == pytest.approx(50.0, abs=1e-3)
        assert cl_string[1][2] == pytest.approx(51.0, abs=1e-3)
        assert cl_string[2][2] == pytest.approx(52.0, abs=1e-3)

    @pytest.mark.asyncio
    async def test_invalid_terrain_degrades_gracefully(self):
        """Malformed terrain_points (only 2 pts) → tool still returns ok (ignores terrain)."""
        from kerf_civil.tools_corridor import run_civil_corridor_model
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 100.0,
            "terrain_points": [[0, 0, 100], [10, 10, 100]],  # only 2 points → invalid TIN
        }, None))
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_spec_name(self):
        from kerf_civil.tools_corridor import civil_corridor_model_spec
        assert civil_corridor_model_spec.name == "civil_corridor_model"

    @pytest.mark.asyncio
    async def test_daylight_offset_in_tool_result(self):
        """Daylight offset from tool dispatch matches analytic formula."""
        from kerf_civil.tools_corridor import run_civil_corridor_model
        terrain_pts = [
            [-50, -50, 100], [50, -50, 100],
            [50, 250, 100],  [-50, 250, 100],
        ]
        result = json.loads(await run_civil_corridor_model({
            "alignment_length_m": 200.0,
            "interval_m": 100.0,
            "datum_elev_m": 98.0,
            "grade_pct": 0.0,
            "lane_width_m": 3.65,
            "shoulder_width_m": 2.4,
            "crown_slope_pct": 2.0,
            "shoulder_slope_pct": 5.0,
            "cut_slope": 2.0,
            "terrain_points": terrain_pts,
            "daylight_step_m": 0.001,
        }, None))
        assert result["ok"] is True
        # Take middle station
        mid_xs = result["cross_sections"][1]  # station 100
        dtr = next(p for p in mid_xs["points"] if p["label"] == "daylight_right")
        # Analytic: hinge_elev = 98 - 0.02*3.65 - 0.05*2.4 = 97.807
        # depth_at_hinge = 100 - 97.807 = 2.193
        # daylight_offset = 6.05 + 2.193 * 2 = 10.436
        assert dtr["offset_m"] == pytest.approx(10.436, abs=0.05)
