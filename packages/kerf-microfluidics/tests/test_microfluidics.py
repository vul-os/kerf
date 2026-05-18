"""
Microfluidics / MEMS unit tests.

Oracles
-------
1. Rectangular channel hydraulic resistance — formula match to 1e-9 relative
   tolerance.
2. Microfluidic network: two parallel equal-resistance channels give R_eq =
   R/2, tested to 1e-12 relative tolerance.
3. MEMS Si cantilever resonance — lumped-mass model vs. exact Euler-Bernoulli
   within 1%.
"""

from __future__ import annotations

import math

import pytest

from kerf_microfluidics.channels import (
    circ_channel_resistance,
    flow_rate,
    pressure_drop,
    rect_channel_resistance,
)
from kerf_microfluidics.mems_cantilever import (
    cantilever_resonance,
    cantilever_resonance_lumped,
    cantilever_stiffness,
)
from kerf_microfluidics.mixers import herringbone_geometry, serpentine_geometry
from kerf_microfluidics.networks import MicrofluidicNetwork, equivalent_resistance


# ---------------------------------------------------------------------------
# 1. Rectangular channel resistance — match formula to 1e-9
# ---------------------------------------------------------------------------

class TestRectChannelResistance:
    """Verify R = 12 μL / (wh³(1−0.63h/w)) to relative tolerance 1e-9."""

    def _oracle(self, mu, L, w, h):
        return 12.0 * mu * L / (w * h**3 * (1.0 - 0.63 * h / w))

    def test_basic(self):
        mu, L, w, h = 1e-3, 1e-3, 100e-6, 50e-6
        R = rect_channel_resistance(mu, L, w, h)
        R_oracle = self._oracle(mu, L, w, h)
        assert abs(R - R_oracle) / R_oracle < 1e-9, (
            f"R={R:.12e}, oracle={R_oracle:.12e}, "
            f"rel_err={abs(R-R_oracle)/R_oracle:.3e}"
        )

    def test_square_cross_section(self):
        """h == w is the degenerate square case."""
        mu, L, w, h = 1e-3, 500e-6, 80e-6, 80e-6
        R = rect_channel_resistance(mu, L, w, h)
        R_oracle = self._oracle(mu, L, w, h)
        assert abs(R - R_oracle) / R_oracle < 1e-9

    def test_narrow_channel(self):
        """Very high aspect ratio (h << w)."""
        mu, L, w, h = 1e-3, 2e-3, 200e-6, 10e-6
        R = rect_channel_resistance(mu, L, w, h)
        R_oracle = self._oracle(mu, L, w, h)
        assert abs(R - R_oracle) / R_oracle < 1e-9

    def test_different_viscosity(self):
        """Glycerol at ~25°C: μ ≈ 0.95 Pa·s."""
        mu, L, w, h = 0.95, 1e-3, 100e-6, 50e-6
        R = rect_channel_resistance(mu, L, w, h)
        R_oracle = self._oracle(mu, L, w, h)
        assert abs(R - R_oracle) / R_oracle < 1e-9

    def test_pressure_drop(self):
        """ΔP = QR round-trip."""
        mu, L, w, h = 1e-3, 1e-3, 100e-6, 50e-6
        R = rect_channel_resistance(mu, L, w, h)
        Q = 1e-12  # 1 pL/s
        dP = pressure_drop(Q, R)
        assert abs(dP - Q * R) < 1e-30 * abs(Q * R) + 1e-60

    def test_flow_from_pressure(self):
        """Q = ΔP/R inverse."""
        mu, L, w, h = 1e-3, 1e-3, 100e-6, 50e-6
        R = rect_channel_resistance(mu, L, w, h)
        dP = 1000.0  # 1 kPa
        Q = flow_rate(dP, R)
        assert abs(Q * R - dP) / dP < 1e-12

    def test_invalid_h_gt_w(self):
        with pytest.raises(ValueError, match="h.*must be.*w"):
            rect_channel_resistance(1e-3, 1e-3, 50e-6, 100e-6)

    def test_invalid_negative_mu(self):
        with pytest.raises(ValueError):
            rect_channel_resistance(-1e-3, 1e-3, 100e-6, 50e-6)


class TestCircChannelResistance:
    def test_hagen_poiseuille(self):
        mu, L, r = 1e-3, 1e-3, 25e-6
        R = circ_channel_resistance(mu, L, r)
        R_oracle = 8.0 * mu * L / (math.pi * r**4)
        assert abs(R - R_oracle) / R_oracle < 1e-12


# ---------------------------------------------------------------------------
# 2. Network solver — two parallel equal-R channels give R_eq = R/2
# ---------------------------------------------------------------------------

class TestNetwork:
    def test_two_parallel_equal_resistance(self):
        """
        Two parallel channels of equal R from 'in' to 'out'.
        Equivalent resistance must be R/2, tested to 1e-12 relative tolerance.
        """
        mu, L, w, h = 1e-3, 1e-3, 100e-6, 50e-6
        R = rect_channel_resistance(mu, L, w, h)

        net = MicrofluidicNetwork()
        for node in ["in", "out"]:
            net.add_node(node)
        net.add_channel("in", "out", resistance=R, label="ch1")
        net.add_channel("in", "out", resistance=R, label="ch2")
        net.set_pressure("in", 1000.0)
        net.set_pressure("out", 0.0)

        result = net.solve()

        # Total flow = sum of flows from 'in' toward 'out'
        Q_total = 0.0
        for (a, b, _lbl), Q in result["flows"].items():
            if a == "in" and b == "out":
                Q_total += Q
            elif a == "out" and b == "in":
                Q_total -= Q

        dP = 1000.0
        R_eq_computed = dP / Q_total
        R_eq_expected = R / 2.0

        rel_err = abs(R_eq_computed - R_eq_expected) / R_eq_expected
        assert rel_err < 1e-12, (
            f"R_eq={R_eq_computed:.15e}, expected={R_eq_expected:.15e}, "
            f"rel_err={rel_err:.3e}"
        )

    def test_two_series_channels(self):
        """Two channels in series → R_eq = 2R."""
        R = 1e12
        net = MicrofluidicNetwork()
        for node in ["in", "mid", "out"]:
            net.add_node(node)
        net.add_channel("in", "mid", resistance=R)
        net.add_channel("mid", "out", resistance=R)
        net.set_pressure("in", 1000.0)
        net.set_pressure("out", 0.0)

        result = net.solve()
        # mid pressure should be 500 Pa
        assert abs(result["pressures"]["mid"] - 500.0) < 1e-9

    def test_equivalent_resistance_parallel(self):
        """equivalent_resistance() utility: two parallel channels."""
        R = 5e11
        channels = [
            {"node_a": "in", "node_b": "out", "resistance": R},
            {"node_a": "in", "node_b": "out", "resistance": R},
        ]
        R_eq = equivalent_resistance(channels, "in", "out")
        assert abs(R_eq - R / 2.0) / (R / 2.0) < 1e-12

    def test_missing_bc_raises(self):
        net = MicrofluidicNetwork()
        net.add_node("a")
        net.add_node("b")
        net.add_channel("a", "b", resistance=1e12)
        with pytest.raises(ValueError, match="pressure boundary"):
            net.solve()

    def test_duplicate_node_raises(self):
        net = MicrofluidicNetwork()
        net.add_node("a")
        with pytest.raises(ValueError):
            net.add_node("a")


# ---------------------------------------------------------------------------
# 3. MEMS cantilever — Si beam resonance within 1% of Euler-Bernoulli
# ---------------------------------------------------------------------------

class TestMemsCantilever:
    """
    Silicon MEMS cantilever: E = 170 GPa, rho = 2330 kg/m³.
    Geometry: t = 1 µm, w = 10 µm, L = 100 µm.
    """

    E_SI = 170e9       # Pa
    RHO_SI = 2330.0    # kg/m³
    T = 1e-6           # m  thickness
    W = 10e-6          # m  width
    L = 100e-6         # m  length

    def test_stiffness(self):
        k = cantilever_stiffness(self.E_SI, self.T, self.W, self.L)
        k_oracle = self.E_SI * self.T**3 * self.W / (4.0 * self.L**3)
        assert abs(k - k_oracle) / k_oracle < 1e-12, (
            f"k={k:.8e}, oracle={k_oracle:.8e}"
        )

    def test_resonance_exact_euler_bernoulli(self):
        """
        cantilever_resonance() returns the exact Euler-Bernoulli result.
        Compare against the closed-form expression derived from the same theory
        to ensure implementation correctness.
        """
        E, rho, t, w, L = self.E_SI, self.RHO_SI, self.T, self.W, self.L
        f1 = cantilever_resonance(E, rho, t, w, L)

        # Reproduce the formula directly
        beta1L = 1.8751040631351359
        I = w * t**3 / 12.0
        A = w * t
        f1_ref = (beta1L**2 / (2.0 * math.pi * L**2)) * math.sqrt(E * I / (rho * A))

        assert abs(f1 - f1_ref) / f1_ref < 1e-12, (
            f"f1={f1:.8e}, ref={f1_ref:.8e}"
        )

    def test_resonance_lumped_vs_exact_within_1pct(self):
        """
        Lumped-mass model must match the exact Euler-Bernoulli result to 1%.
        """
        E, rho, t, w, L = self.E_SI, self.RHO_SI, self.T, self.W, self.L
        f1_exact = cantilever_resonance(E, rho, t, w, L)
        f1_lumped = cantilever_resonance_lumped(E, rho, t, w, L)
        rel_err = abs(f1_lumped - f1_exact) / f1_exact
        assert rel_err < 0.01, (
            f"Lumped {f1_lumped:.4e} Hz vs exact {f1_exact:.4e} Hz — "
            f"relative error {rel_err*100:.3f}% exceeds 1%"
        )

    def test_resonance_scales_with_thickness(self):
        """f1 ∝ t for fixed w, L (from the formula)."""
        E, rho, w, L = self.E_SI, self.RHO_SI, self.W, self.L
        f1_1um = cantilever_resonance(E, rho, 1e-6, w, L)
        f1_2um = cantilever_resonance(E, rho, 2e-6, w, L)
        ratio = f1_2um / f1_1um
        assert abs(ratio - 2.0) < 1e-10, (
            f"Expected f ∝ t ratio=2, got {ratio:.8f}"
        )

    def test_resonance_scales_with_length(self):
        """f1 ∝ 1/L² for fixed cross-section."""
        E, rho, t, w = self.E_SI, self.RHO_SI, self.T, self.W
        f1_100um = cantilever_resonance(E, rho, t, w, 100e-6)
        f1_200um = cantilever_resonance(E, rho, t, w, 200e-6)
        ratio = f1_100um / f1_200um
        assert abs(ratio - 4.0) < 1e-10, (
            f"Expected f ∝ 1/L² ratio=4, got {ratio:.8f}"
        )

    def test_invalid_args(self):
        with pytest.raises(ValueError):
            cantilever_stiffness(-1.0, 1e-6, 10e-6, 100e-6)
        with pytest.raises(ValueError):
            cantilever_resonance(170e9, 2330.0, 0.0, 10e-6, 100e-6)


# ---------------------------------------------------------------------------
# 4. Mixer geometry sanity checks
# ---------------------------------------------------------------------------

class TestMixers:
    def test_serpentine_waypoints_non_empty(self):
        geom = serpentine_geometry(
            n_turns=4,
            channel_width=100e-6,
            straight_length=1e-3,
        )
        assert len(geom["waypoints"]) > 4
        assert geom["n_turns"] == 4
        assert geom["total_length"] > 0.0

    def test_serpentine_start_point(self):
        geom = serpentine_geometry(
            n_turns=2,
            channel_width=100e-6,
            straight_length=500e-6,
            start_x=1e-3,
            start_y=2e-3,
        )
        assert geom["waypoints"][0] == pytest.approx((1e-3, 2e-3))

    def test_serpentine_total_length_approx(self):
        """Total length should be approximately (n_turns+1)*straight_length."""
        n = 3
        sl = 1e-3
        geom = serpentine_geometry(n_turns=n, channel_width=50e-6, straight_length=sl)
        # At minimum the straights contribute (n+1)*sl
        assert geom["total_length"] >= (n + 1) * sl * 0.99

    def test_herringbone_grooves_non_empty(self):
        geom = herringbone_geometry(
            channel_length=5e-3,
            channel_width=200e-6,
            groove_depth=50e-6,
            groove_width=30e-6,
            groove_pitch=200e-6,
        )
        assert len(geom["grooves"]) > 0
        assert len(geom["centreline"]) == 2

    def test_herringbone_groove_positions_in_channel(self):
        cl = 5e-3
        geom = herringbone_geometry(
            channel_length=cl,
            channel_width=200e-6,
            groove_depth=50e-6,
            groove_width=30e-6,
            groove_pitch=200e-6,
        )
        for g in geom["grooves"]:
            assert 0.0 <= g["x"] <= cl

    def test_serpentine_invalid_turns(self):
        with pytest.raises(ValueError):
            serpentine_geometry(n_turns=0, channel_width=100e-6, straight_length=1e-3)
