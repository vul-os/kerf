"""
Tests for kerf_silicon.parasitics.rc_extract

Analytic reference values
--------------------------
met1 parameters:
  ρ  = 0.125 Ω/□            (sheet resistance)
  cap_aF_um2 = 80 aF/μm²   (area cap to substrate)

1-net wire 10 μm long, 0.14 μm wide on met1
  Aspect ratio = 10 / 0.14 ≈ 71.429 squares
  R = ρ × (L/W) = 0.125 × (10/0.14) ≈ 8.9286 Ω

Parallel-plate capacitance of 1 μm × 10 μm patch on met1
  C_plate = 80 aF/μm² × 10 μm² = 800 aF = 800 × 10⁻¹⁸ F

ε₀ direct formula cross-check (for custom tech with explicit d and ε):
  C = ε₀·εr·A / d
"""
from __future__ import annotations

import math
import os
import sys

# Ensure the source tree is on the path when running directly from the repo.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_silicon.parasitics.rc_extract import (
    Layout,
    Wire,
    ParasiticReport,
    NetParasitics,
    _DEFAULT_TECH,
    extract_rc,
)

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_EPSILON_0 = 8.854187817e-12   # F/m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _single_wire_layout(
    net: str = "net_A",
    layer: str = "met1",
    length_um: float = 10.0,
    width_um: float = 0.14,
) -> Layout:
    """Return a Layout with one horizontal wire."""
    w = Wire(
        net=net,
        layer=layer,
        x0=0.0,
        y0=0.0,
        x1=length_um,
        y1=width_um,
    )
    return Layout(wires=[w])


# ---------------------------------------------------------------------------
# Resistance tests
# ---------------------------------------------------------------------------

class TestResistance:
    def test_single_wire_met1_resistance(self):
        """10 μm long, 0.14 μm wide met1 → R ≈ 8.93 Ω (analytic)."""
        layout = _single_wire_layout(length_um=10.0, width_um=0.14)
        report = extract_rc(layout)

        assert "net_A" in report.nets
        net = report.nets["net_A"]
        # ρ=0.125, L/W = 10/0.14 ≈ 71.4286 → R ≈ 8.9286 Ω
        expected_R = 0.125 * (10.0 / 0.14)
        assert abs(net.R_total_ohm - expected_R) < 1e-4, (
            f"R = {net.R_total_ohm:.4f} Ω, expected ≈ {expected_R:.4f} Ω"
        )

    def test_resistance_approximately_8_93_ohm(self):
        """Explicit check that the result is near the stated 8.93 Ω target."""
        layout = _single_wire_layout(length_um=10.0, width_um=0.14)
        report = extract_rc(layout)
        R = report.nets["net_A"].R_total_ohm
        assert abs(R - 8.93) < 0.01, f"R = {R:.4f} Ω, wanted ≈ 8.93 Ω"

    def test_resistance_scales_with_length(self):
        """Doubling wire length doubles resistance."""
        r1 = extract_rc(_single_wire_layout(length_um=5.0, width_um=0.14))
        r2 = extract_rc(_single_wire_layout(length_um=10.0, width_um=0.14))
        R1 = r1.nets["net_A"].R_total_ohm
        R2 = r2.nets["net_A"].R_total_ohm
        assert abs(R2 / R1 - 2.0) < 1e-6

    def test_resistance_inversely_proportional_to_width(self):
        """Doubling wire width halves resistance."""
        r1 = extract_rc(_single_wire_layout(length_um=10.0, width_um=0.14))
        r2 = extract_rc(_single_wire_layout(length_um=10.0, width_um=0.28))
        R1 = r1.nets["net_A"].R_total_ohm
        R2 = r2.nets["net_A"].R_total_ohm
        assert abs(R1 / R2 - 2.0) < 1e-6

    def test_resistance_segments_list(self):
        """R_segments should have exactly one entry for a single wire."""
        layout = _single_wire_layout()
        report = extract_rc(layout)
        assert len(report.nets["net_A"].R_segments) == 1

    def test_met2_lower_sheet_resistance(self):
        """met2 has lower sheet resistance than met1 → lower R for same geometry."""
        r1 = extract_rc(_single_wire_layout(layer="met1"))
        r2 = extract_rc(_single_wire_layout(layer="met2"))
        assert r2.nets["net_A"].R_total_ohm < r1.nets["net_A"].R_total_ohm

    def test_resistance_formula_custom_tech(self):
        """Custom tech parameter is applied correctly: R = ρ·L/W."""
        custom_tech = {
            "met1": {
                "rho_sq": 1.0,        # 1 Ω/□ for easy arithmetic
                "cap_aF_um2": 0.0,
                "thickness_nm": 100.0,
                "height_nm": 100.0,
                "epsilon_r": 1.0,
            }
        }
        layout = _single_wire_layout(length_um=5.0, width_um=1.0)
        report = extract_rc(layout, tech=custom_tech)
        # L/W = 5 → R = 1.0 × 5 = 5 Ω
        assert abs(report.nets["net_A"].R_total_ohm - 5.0) < 1e-9

    def test_square_wire_one_square(self):
        """1 μm × 1 μm met1 square = 0.125 Ω (exactly 1 square)."""
        layout = _single_wire_layout(length_um=1.0, width_um=1.0)
        report = extract_rc(layout)
        rho = _DEFAULT_TECH["met1"]["rho_sq"]
        assert abs(report.nets["net_A"].R_total_ohm - rho) < 1e-9


# ---------------------------------------------------------------------------
# Capacitance tests — plate
# ---------------------------------------------------------------------------

class TestCapacitancePlate:
    def test_plate_cap_1x10_patch_met1(self):
        """1 μm × 10 μm met1 patch → C_plate = 80 aF/μm² × 10 μm² = 800 aF."""
        layout = _single_wire_layout(length_um=10.0, width_um=1.0)
        report = extract_rc(layout)
        net = report.nets["net_A"]
        c_seg = net.C_segments[0]

        cap_aF_um2 = _DEFAULT_TECH["met1"]["cap_aF_um2"]  # 80
        expected_C = cap_aF_um2 * 1e-18 * (10.0 * 1.0)   # 800 × 10⁻¹⁸ F
        # Allow 1 % tolerance (plate only; lateral may add a small amount)
        assert abs(c_seg.C_plate_F - expected_C) < expected_C * 0.01

    def test_plate_cap_matches_epsilon_formula(self):
        """
        C = ε₀·εr·A/d for a fully specified layer should match
        cap_aF_um2 × A.

        The default met1 cap_aF_um2 = 80 aF/μm² is a compact model value.
        Here we cross-check using a custom tech where cap_aF_um2 is derived
        from ε₀·εr/d so the two approaches agree numerically.

        ε₀ = 8.854e-12 F/m, εr = 3.9 (SiO₂), d = 230 nm = 230e-9 m
        cap = ε₀·εr/d = 8.854e-12×3.9/230e-9 ≈ 0.15014 F/m²
                       = 150.14 aF/μm²  (1 F/m² = 1e-6 aF/μm²... let's compute)
        1 F/m² = 1e-18 F/μm² → / 1e-18 = 1e18 aF/m² → × (1e-6)² = 1 aF/μm²
        So 0.15014 F/m² → 0.15014 aF/μm²  ... wait, units:
          F/m² → aF/μm²: multiply by (1e-6)²/1e-18 = 1e-12/1e-18 = 1e6 → wrong
          Let's be explicit:
            1 F/m² = 1 F/(1 m)² = 1e-18 F / (1e-6 m)² = 1 aF/μm²  ... no:
            (1e-6 m)² = 1e-12 m²
            1 F/m² × 1e-12 m²/μm² = 1e-12 F/μm² = 1e-12/1e-18 aF/μm² = 1e6 aF/μm²
          So: 0.15014 F/m² × 1e6 aF·m²/μm²/F = 150140 aF/μm²  → that can't be right.

        Let's recompute carefully:
          C = ε₀·εr·A/d
          ε₀·εr = 8.854e-12 × 3.9 = 3.453e-11 F/m
          d = 230e-9 m → area cap density = 3.453e-11/230e-9 = 1.501e-4 F/m²
          In aF/μm²:
            1 F/m² = 1 C/(V·m²)
            1 μm² = 1e-12 m²
            1 F/m² × 1e-12 m²/μm² = 1e-12 F/μm² = 1e6 aF/μm²
          So 1.501e-4 F/m² × 1e6 aF/μm² per F/m² = 150.1 aF/μm²

        The default met1 is 80 aF/μm² (fitted PDK value).
        Here we build a custom tech where cap_aF_um2 = ε₀·εr/d × 1e6.
        """
        eps_r = 3.9
        d_m = 230e-9
        # area capacitance density in F/m²
        cap_density_F_m2 = _EPSILON_0 * eps_r / d_m
        # convert to aF/μm²: 1 F/m² = 1e6 aF/μm²  (shown above)
        cap_aF_um2_derived = cap_density_F_m2 * 1e6

        custom_tech = {
            "met1": {
                "rho_sq":       0.125,
                "cap_aF_um2":   cap_aF_um2_derived,
                "thickness_nm": 300.0,
                "height_nm":    230.0,
                "epsilon_r":    eps_r,
            }
        }
        L_um = 10.0
        W_um = 1.0
        area_um2 = L_um * W_um
        area_m2 = area_um2 * 1e-12

        layout = _single_wire_layout(length_um=L_um, width_um=W_um)
        report = extract_rc(layout, tech=custom_tech)
        c_seg = report.nets["net_A"].C_segments[0]

        expected_C = _EPSILON_0 * eps_r * area_m2 / d_m
        assert abs(c_seg.C_plate_F - expected_C) / expected_C < 0.01, (
            f"C_plate = {c_seg.C_plate_F:.4e} F, expected {expected_C:.4e} F"
        )

    def test_cap_scales_with_area(self):
        """Doubling wire area doubles plate capacitance."""
        r1 = extract_rc(_single_wire_layout(length_um=5.0, width_um=1.0))
        r2 = extract_rc(_single_wire_layout(length_um=10.0, width_um=1.0))
        c1 = r1.nets["net_A"].C_segments[0].C_plate_F
        c2 = r2.nets["net_A"].C_segments[0].C_plate_F
        assert abs(c2 / c1 - 2.0) < 1e-6

    def test_cap_segments_list_populated(self):
        """C_segments list should have one entry per wire."""
        layout = _single_wire_layout()
        report = extract_rc(layout)
        assert len(report.nets["net_A"].C_segments) == 1


# ---------------------------------------------------------------------------
# Lateral coupling tests
# ---------------------------------------------------------------------------

class TestLateralCoupling:
    def test_no_coupling_when_no_neighbours(self):
        """A single isolated wire has zero lateral capacitance."""
        layout = _single_wire_layout()
        report = extract_rc(layout)
        c_seg = report.nets["net_A"].C_segments[0]
        assert c_seg.C_lateral_F == 0.0

    def test_lateral_coupling_two_parallel_wires(self):
        """Two parallel wires close together → non-zero lateral coupling."""
        w1 = Wire(net="A", layer="met1", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
        w2 = Wire(net="B", layer="met1", x0=0.0, y0=0.28, x1=10.0, y1=0.42)
        layout = Layout(wires=[w1, w2])
        report = extract_rc(layout)
        # Each net should have non-zero lateral cap
        c_A = report.nets["A"].C_segments[0].C_lateral_F
        c_B = report.nets["B"].C_segments[0].C_lateral_F
        assert c_A > 0.0
        assert c_B > 0.0

    def test_lateral_coupling_far_apart(self):
        """Wires > max_coupling_um apart → zero lateral coupling."""
        w1 = Wire(net="A", layer="met1", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
        # 5 μm gap — well beyond 2 μm default threshold
        w2 = Wire(net="B", layer="met1", x0=0.0, y0=5.14, x1=10.0, y1=5.28)
        layout = Layout(wires=[w1, w2])
        report = extract_rc(layout)
        c_A = report.nets["A"].C_segments[0].C_lateral_F
        assert c_A == 0.0

    def test_perpendicular_wires_no_coupling(self):
        """Perpendicular wires do not couple laterally."""
        w1 = Wire(net="A", layer="met1", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
        w2 = Wire(net="B", layer="met1", x0=0.5, y0=0.0, x1=0.64, y1=10.0)
        layout = Layout(wires=[w1, w2])
        report = extract_rc(layout)
        c_A = report.nets["A"].C_segments[0].C_lateral_F
        assert c_A == 0.0


# ---------------------------------------------------------------------------
# Multi-net layout tests
# ---------------------------------------------------------------------------

class TestMultiNet:
    def test_two_nets_independent(self):
        """Two non-adjacent nets should each have their own R/C data."""
        w1 = Wire(net="VDD", layer="met1", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
        w2 = Wire(net="GND", layer="met1", x0=0.0, y0=10.0, x1=20.0, y1=10.14)
        layout = Layout(wires=[w1, w2])
        report = extract_rc(layout)
        assert "VDD" in report.nets
        assert "GND" in report.nets
        # VDD is 10 μm long 0.14 μm wide
        R_vdd = 0.125 * (10.0 / 0.14)
        assert abs(report.nets["VDD"].R_total_ohm - R_vdd) < 1e-4
        # GND is 20 μm long 0.14 μm wide
        R_gnd = 0.125 * (20.0 / 0.14)
        assert abs(report.nets["GND"].R_total_ohm - R_gnd) < 1e-4

    def test_multiple_segments_same_net(self):
        """Multiple wires on the same net accumulate R and C."""
        w1 = Wire(net="CLK", layer="met1", x0=0.0, y0=0.0, x1=5.0, y1=0.14)
        w2 = Wire(net="CLK", layer="met1", x0=5.0, y0=0.0, x1=10.0, y1=0.14)
        layout = Layout(wires=[w1, w2])
        report = extract_rc(layout)
        net = report.nets["CLK"]
        # Each wire is 5 μm; total should equal a 10 μm wire
        R_expected = 0.125 * (10.0 / 0.14)
        assert abs(net.R_total_ohm - R_expected) < 1e-4
        assert len(net.R_segments) == 2

    def test_multiple_layers_same_net(self):
        """Wires on met1 and met2 both contribute to the same net."""
        w1 = Wire(net="SIG", layer="met1", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
        w2 = Wire(net="SIG", layer="met2", x0=0.0, y0=0.0, x1=5.0, y1=0.14)
        layout = Layout(wires=[w1, w2])
        report = extract_rc(layout)
        net = report.nets["SIG"]
        R_met1 = _DEFAULT_TECH["met1"]["rho_sq"] * (10.0 / 0.14)
        R_met2 = _DEFAULT_TECH["met2"]["rho_sq"] * (5.0 / 0.14)
        assert abs(net.R_total_ohm - (R_met1 + R_met2)) < 1e-4


# ---------------------------------------------------------------------------
# Layer filtering tests
# ---------------------------------------------------------------------------

class TestLayerFiltering:
    def test_layer_not_in_extract_list_ignored(self):
        """Wire on met3 ignored when layers_to_extract=['met1','met2']."""
        w = Wire(net="SIG", layer="met3", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
        layout = Layout(wires=[w])
        report = extract_rc(layout, layers_to_extract=["met1", "met2"])
        assert len(report.nets) == 0

    def test_unknown_layer_ignored(self):
        """Wire on an unknown layer (not in tech) is silently skipped."""
        w = Wire(net="SIG", layer="polysi", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
        layout = Layout(wires=[w])
        report = extract_rc(layout)
        assert len(report.nets) == 0


# ---------------------------------------------------------------------------
# Empty layout test
# ---------------------------------------------------------------------------

class TestEmptyLayout:
    def test_empty_layout_returns_empty_report(self):
        """Empty layout → ParasiticReport with no nets."""
        report = extract_rc(Layout())
        assert isinstance(report, ParasiticReport)
        assert len(report.nets) == 0

    def test_empty_layout_nets_is_dict(self):
        """Empty layout → report.nets is a dict."""
        report = extract_rc(Layout())
        assert isinstance(report.nets, dict)


# ---------------------------------------------------------------------------
# ParasiticReport structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_net_parasitic_fields_present(self):
        """NetParasitics exposes R_total_ohm, C_total_F, R_segments, C_segments."""
        report = extract_rc(_single_wire_layout())
        net = report.nets["net_A"]
        assert hasattr(net, "R_total_ohm")
        assert hasattr(net, "C_total_F")
        assert hasattr(net, "R_segments")
        assert hasattr(net, "C_segments")

    def test_c_total_includes_plate(self):
        """C_total_F should be at least the plate component."""
        report = extract_rc(_single_wire_layout(length_um=10.0, width_um=1.0))
        net = report.nets["net_A"]
        c_seg = net.C_segments[0]
        assert net.C_total_F >= c_seg.C_plate_F

    def test_r_segment_attributes(self):
        """RSegment has layer, length_um, width_um, R_ohm."""
        report = extract_rc(_single_wire_layout())
        r_seg = report.nets["net_A"].R_segments[0]
        assert r_seg.layer == "met1"
        assert r_seg.length_um == pytest.approx(10.0)
        assert r_seg.width_um == pytest.approx(0.14)
        assert r_seg.R_ohm > 0.0
