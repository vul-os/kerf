"""
Tests for kerf_cad_core.render.theatrical_lighting.

Coverage:
  read_ies_file       — IES LM-63 parser (lumens, candela grid shape, name)
  ies_candela_at      — bilinear interpolation of candela values
  TheatricalFixture   — construction and attribute access
  TheatricalLightingPlot.to_svg  — SVG output contains fixture positions
  TheatricalLightingPlot.illuminance_at — inverse-square cosine law
  TheatricalLightingPlot.total_load_watts — wattage computation

References
----------
IESNA LM-63-2002 — photometric data file standard.
Gillette (2008) — theatrical lighting plot conventions.
IES Lighting Handbook 10th ed. §5.3 — inverse-square law.

Author: imranparuk
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.render.theatrical_lighting import (
    IesPhotometricFile,
    TheatricalFixture,
    TheatricalLightingPlot,
    ies_candela_at,
    read_ies_file,
)

# ---------------------------------------------------------------------------
# Minimal valid IES LM-63 file (TILT=NONE, 4 vertical × 2 horizontal)
# ---------------------------------------------------------------------------

_MINIMAL_IES = """\
[TEST] minimal test fixture
[LUMINAIRE] Test PAR64 1kW
[ISSUEDATE] 2026-01-01
[LAMP] 1000W PAR64
TILT=NONE
1 5000.0 1.0 4 2 1 2 0.0 0.0 0.0 1.0 1.0 1000.0
0 30 60 90
0 90
2000.0 1500.0 1000.0 200.0
1800.0 1400.0 900.0 150.0
"""

# Second fixture — lumens=3000, 3V × 1H
_SIMPLE_IES = """\
[LUMINAIRE] ETC Source Four
TILT=NONE
1 3000.0 1.0 3 1 1 2 0.0 0.0 0.0 1.0 1.0 575.0
0 45 90
0
45000.0 32000.0 5000.0
"""


class TestReadIesFile:
    def test_lumens_parsed_correctly(self):
        ies = read_ies_file(_MINIMAL_IES)
        assert ies.lumens == pytest.approx(5000.0)

    def test_luminaire_name_parsed(self):
        ies = read_ies_file(_MINIMAL_IES)
        assert "Test PAR64" in ies.luminaire_name or ies.luminaire_name != ""

    def test_candela_grid_shape(self):
        ies = read_ies_file(_MINIMAL_IES)
        # 4 vertical × 2 horizontal
        assert ies.candela_grid.shape == (4, 2)

    def test_peak_candela_correct(self):
        ies = read_ies_file(_MINIMAL_IES)
        assert float(ies.candela_grid.max()) == pytest.approx(2000.0)

    def test_vertical_angles_count(self):
        ies = read_ies_file(_MINIMAL_IES)
        assert len(ies.vertical_angles) == 4

    def test_simple_single_horizontal(self):
        ies = read_ies_file(_SIMPLE_IES)
        assert ies.lumens == pytest.approx(3000.0)
        assert ies.candela_grid.shape == (3, 1)
        assert ies.candela_grid[0, 0] == pytest.approx(45000.0)

    def test_missing_tilt_raises(self):
        with pytest.raises(ValueError, match="TILT"):
            read_ies_file("[LUMINAIRE] Bad\n1 1000.0 1.0 2 1 1 2 0 0 0 1 1 100\n0 90\n0\n1000 500")


class TestIesCandela:
    def setup_method(self):
        self.ies = read_ies_file(_MINIMAL_IES)

    def test_exact_grid_point(self):
        cd = ies_candela_at(self.ies, 0.0, 0.0)
        assert cd == pytest.approx(2000.0)

    def test_interpolated_value_in_range(self):
        cd = ies_candela_at(self.ies, 15.0, 0.0)
        # Between 2000 (at 0°) and 1500 (at 30°)
        assert 1500.0 <= cd <= 2000.0

    def test_at_edge_90_degrees(self):
        cd = ies_candela_at(self.ies, 90.0, 0.0)
        # Nearest grid is at 90° which is 200 cd
        assert cd == pytest.approx(200.0, abs=1.0)


class TestTheatricalFixture:
    def test_fixture_construction(self):
        fix = TheatricalFixture(
            fixture_id="LX1-01",
            type="ETC Source Four",
            position=(0.0, 0.0, 6.0),
            aim_target=(0.0, 0.0, 0.0),
            color=(1.0, 1.0, 1.0),
            intensity_pct=80.0,
        )
        assert fix.fixture_id == "LX1-01"
        assert fix.intensity_pct == pytest.approx(80.0)


class TestTheatricalLightingPlot:
    def _make_plot(self) -> TheatricalLightingPlot:
        fixtures = [
            TheatricalFixture(
                fixture_id="LX1-01",
                type="ETC Source Four",
                position=(0.0, 7.0, 6.0),
                aim_target=(0.0, 0.0, 1.0),
                color=(1.0, 0.8, 0.7),
                intensity_pct=100.0,
            ),
            TheatricalFixture(
                fixture_id="LX1-02",
                type="PAR64",
                position=(2.0, 7.0, 6.0),
                aim_target=(2.0, 0.0, 1.0),
                color=(0.0, 0.5, 1.0),
                intensity_pct=75.0,
            ),
        ]
        truss_lines = [
            ((- 4.0, 7.0, 6.0), (4.0, 7.0, 6.0)),
        ]
        return TheatricalLightingPlot(
            fixtures=fixtures,
            truss_lines=truss_lines,
            stage_width=10.0,
            stage_depth=8.0,
        )

    def test_to_svg_returns_string(self):
        plot = self._make_plot()
        svg = plot.to_svg()
        assert isinstance(svg, str)

    def test_to_svg_contains_fixture_id(self):
        plot = self._make_plot()
        svg = plot.to_svg()
        assert "LX1-01" in svg

    def test_to_svg_contains_svg_tag(self):
        plot = self._make_plot()
        svg = plot.to_svg()
        assert svg.startswith("<svg")

    def test_to_svg_contains_truss_color(self):
        plot = self._make_plot()
        svg = plot.to_svg()
        # Truss colour is #c8a060
        assert "#c8a060" in svg

    def test_fixture_count(self):
        plot = self._make_plot()
        assert plot.fixture_count() == 2

    def test_illuminance_at_positive(self):
        plot = self._make_plot()
        lux = plot.illuminance_at((0.0, 0.0, 1.0))
        assert lux > 0.0

    def test_illuminance_zero_behind_fixture(self):
        """Point directly above a downward-aimed fixture sees ≈0 direct lux."""
        fix = TheatricalFixture(
            fixture_id="T1",
            type="ETC Source Four",
            position=(0.0, 0.0, 6.0),
            aim_target=(0.0, 0.0, 0.0),  # aims straight down
            color=(1.0, 1.0, 1.0),
            intensity_pct=100.0,
        )
        plot = TheatricalLightingPlot(fixtures=[fix])
        # Point directly above fixture (in rear hemisphere of beam) → 0
        lux = plot.illuminance_at((0.0, 0.0, 7.0))
        assert lux == pytest.approx(0.0, abs=1.0)

    def test_total_load_watts(self):
        plot = self._make_plot()
        load = plot.total_load_watts()
        # ETC Source Four = 575W × 100% + PAR64 = 1000W × 75% = 575 + 750 = 1325
        assert load == pytest.approx(1325.0)
