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
4. Channel cross-section optimizer — four analytical-oracle tests (Bruus 2008).
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
from kerf_microfluidics.channel_optimizer import (
    pressure_drop_rect,
    pressure_drop_trapezoidal,
    pressure_drop_semicircular,
    reynolds_number,
    optimize_cross_section,
    _rect_friction_factor,
)


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


# ---------------------------------------------------------------------------
# 5. Channel cross-section optimizer — analytical-oracle tests (Bruus 2008)
# ---------------------------------------------------------------------------

class TestFrictionFactor:
    """Verify Bruus eq. 3.27 Fourier-series friction factor."""

    def test_square_limit(self):
        """Square channel (α=1): f ≈ 0.4217 (well-known tabulated value)."""
        f = _rect_friction_factor(1.0, n_terms=20)
        # Published value for square channel: ~0.4217 (Bruus 2008 §3 Table 3.1)
        assert abs(f - 0.4217) < 0.001, f"f(1.0) = {f:.6f}, expected ~0.4217"

    def test_thin_slit_limit(self):
        """Very flat channel (α→0): f → 1 (pure 2D Poiseuille)."""
        f = _rect_friction_factor(0.01, n_terms=20)
        assert f > 0.99, f"f(0.01) = {f:.6f}, expected close to 1.0"

    def test_monotone_decrease(self):
        """f(α) must be strictly decreasing: wider channels are more efficient."""
        alphas = [0.1, 0.2, 0.5, 0.8, 1.0]
        factors = [_rect_friction_factor(a, n_terms=15) for a in alphas]
        for i in range(len(factors) - 1):
            assert factors[i] > factors[i + 1], (
                f"f not monotone: f({alphas[i]})={factors[i]:.5f} >= "
                f"f({alphas[i+1]})={factors[i+1]:.5f}"
            )


class TestPressureDropRect:
    """
    Test 1 — Square rectangular ΔP (Bruus 2008 oracle).

    100 µm × 100 µm × 10 mm channel, Q = 1 µL/min.

    Full formula: ΔP = 12·µ·Q·L / (w·h³·f(α)) where f(α=1) ≈ 0.4217.
    Expected: ΔP = 12·1e-3·Q_SI·10e-3 / (100e-6·(100e-6)³·0.4217)
    """

    W = 100.0   # µm
    H = 100.0   # µm
    L = 10_000.0  # µm  (10 mm)
    Q = 1.0     # µL/min
    MU = 1e-3   # Pa·s

    def _oracle(self):
        """Reproduce formula directly from Bruus eq. 3.27."""
        import math as _math
        w = self.W * 1e-6
        h = self.H * 1e-6
        L = self.L * 1e-6
        Q = self.Q * 1e-9 / 60.0
        mu = self.MU
        f = _rect_friction_factor(1.0, n_terms=20)  # α = h/w = 1.0
        return 12.0 * mu * Q * L / (w * h**3 * f)

    def test_square_pressure_drop_within_1pct_of_bruus(self):
        """ΔP must match Bruus eq. 3.27 oracle to within 1%."""
        dp = pressure_drop_rect(self.W, self.H, self.L, self.Q, self.MU)
        dp_oracle = self._oracle()
        rel_err = abs(dp - dp_oracle) / dp_oracle
        assert rel_err < 0.01, (
            f"ΔP={dp:.4f} Pa, oracle={dp_oracle:.4f} Pa, rel_err={rel_err*100:.3f}%"
        )

    def test_pressure_drop_positive(self):
        dp = pressure_drop_rect(self.W, self.H, self.L, self.Q, self.MU)
        assert dp > 0.0

    def test_invalid_height_gt_width_raises(self):
        with pytest.raises(ValueError, match="width_um"):
            pressure_drop_rect(50.0, 200.0, 10_000.0, 1.0)

    def test_invalid_zero_flow_raises(self):
        with pytest.raises(ValueError, match="flow_rate"):
            pressure_drop_rect(100.0, 100.0, 10_000.0, 0.0)


class TestAspectRatioDependence:
    """
    Test 2 — Aspect-ratio dependence.

    Two rectangular channels at 1:1 vs 1:5 aspect ratio with the SAME
    cross-sectional area.  The 1:5 channel should have higher ΔP because
    a square (1:1) maximises the hydraulic efficiency for fixed area.

    Fixed area A = 10_000 µm².  Square: 100×100.  Elongated: 224×44.7 (5:1 w/h).
    """

    L = 10_000.0   # µm  (10 mm)
    Q = 1.0        # µL/min
    AREA_UM2 = 10_000.0

    def _make_dims(self, aspect_h_over_w: float):
        """Return (w, h) in µm such that w·h = AREA and h/w = aspect_h_over_w."""
        # w * h = A, h = ar * w  →  w² * ar = A  →  w = sqrt(A/ar)
        w = (self.AREA_UM2 / aspect_h_over_w) ** 0.5
        h = w * aspect_h_over_w
        return w, h

    def test_elongated_has_higher_pressure_drop_than_square(self):
        """
        A 1:5 elongated channel (h/w = 0.2) at the same area as a square
        must have HIGHER ΔP (less hydraulically efficient).
        """
        w_sq, h_sq = self._make_dims(1.0)          # square
        w_el, h_el = self._make_dims(0.2)           # elongated 5:1

        dp_square = pressure_drop_rect(w_sq, h_sq, self.L, self.Q)
        dp_elongated = pressure_drop_rect(w_el, h_el, self.L, self.Q)

        assert dp_elongated > dp_square, (
            f"Expected elongated ({dp_elongated:.2f} Pa) > square ({dp_square:.2f} Pa)"
        )

    def test_aspect_ratio_monotone_pressure(self):
        """
        Holding area constant, ΔP should increase as channel becomes more
        elongated (h/w decreases from 1.0 toward 0).
        """
        aspect_ratios = [1.0, 0.5, 0.3, 0.2, 0.1]
        dps = []
        for ar in aspect_ratios:
            w, h = self._make_dims(ar)
            dps.append(pressure_drop_rect(w, h, self.L, self.Q))

        for i in range(len(dps) - 1):
            assert dps[i] < dps[i + 1], (
                f"ΔP not monotone at ar={aspect_ratios[i]}: {dps[i]:.4f} >= {dps[i+1]:.4f}"
            )


class TestOptimizerRoundTrip:
    """
    Test 3 — Optimizer round-trip.

    optimize_cross_section(Q=1, L=10 mm, ΔP_max=1000 Pa) must:
    - return a result without raising
    - satisfy ΔP ≤ max_pressure_pa
    - return minimum footprint (verified by comparing against a wider channel)
    """

    Q = 1.0          # µL/min
    L = 10_000.0     # µm  (10 mm)
    DP_MAX = 1000.0  # Pa

    def test_feasible_result_returned(self):
        result = optimize_cross_section(
            flow_rate_ul_min=self.Q,
            length_um=self.L,
            max_pressure_pa=self.DP_MAX,
            candidate_shapes=["rectangular"],
        )
        assert result is not None
        assert result.pressure_drop_pa <= self.DP_MAX
        assert result.footprint_m2 > 0.0

    def test_returned_dimensions_satisfy_constraint(self):
        result = optimize_cross_section(
            flow_rate_ul_min=self.Q,
            length_um=self.L,
            max_pressure_pa=self.DP_MAX,
            candidate_shapes=["rectangular"],
        )
        # Independently verify pressure drop from returned dimensions
        dims = result.dimensions
        dp_check = pressure_drop_rect(
            dims["width_um"],
            dims["height_um"],
            dims["length_um"],
            self.Q,
        )
        assert dp_check <= self.DP_MAX * 1.001, (
            f"Returned dims give ΔP={dp_check:.2f} Pa > budget {self.DP_MAX} Pa"
        )

    def test_all_shapes_optimizer(self):
        """Test with all three shapes; result must satisfy constraint."""
        result = optimize_cross_section(
            flow_rate_ul_min=self.Q,
            length_um=self.L,
            max_pressure_pa=self.DP_MAX,
            candidate_shapes=["rectangular", "trapezoidal", "semicircular"],
        )
        assert result.shape in {"rectangular", "trapezoidal", "semicircular"}
        assert result.pressure_drop_pa <= self.DP_MAX

    def test_infeasible_raises(self):
        """Impossibly tight constraint → ValueError."""
        with pytest.raises(ValueError, match="No feasible"):
            optimize_cross_section(
                flow_rate_ul_min=1000.0,    # very high flow
                length_um=1_000_000.0,      # very long channel
                max_pressure_pa=0.001,      # impossibly low pressure
                candidate_shapes=["rectangular"],
                size_range_um=(1.0, 10.0),  # tiny channels
            )


class TestReynoldsNumber:
    """
    Test 4 — Reynolds number in laminar regime.

    At Q = 1 µL/min in a 100 µm diameter channel, Re must be << 1 (well laminar).
    """

    def test_well_laminar_at_1ul_min(self):
        """
        Q = 1 µL/min, D = 100 µm (water).
        V̄ = Q/A = (1e-9/60) / (π·(50e-6)²) ≈ 2.12e-3 m/s
        Re = ρVD/µ = 1000·2.12e-3·100e-6/1e-3 ≈ 0.212  (well < 1)
        """
        re = reynolds_number(
            diameter_um=100.0,
            flow_rate_ul_min=1.0,
            density_kg_m3=1000.0,
            viscosity_pa_s=1e-3,
        )
        assert re < 1.0, f"Re={re:.4f} expected < 1 for Q=1 µL/min in 100 µm channel"

    def test_re_scales_linearly_with_flow_rate(self):
        """Re ∝ Q for fixed geometry."""
        re1 = reynolds_number(100.0, 1.0)
        re10 = reynolds_number(100.0, 10.0)
        assert abs(re10 / re1 - 10.0) < 1e-9, (
            f"Expected Re linear in Q; got ratio {re10/re1:.6f}, expected 10.0"
        )

    def test_re_scales_inversely_with_viscosity(self):
        """Re ∝ 1/µ for fixed geometry and flow."""
        re_water = reynolds_number(100.0, 1.0, viscosity_pa_s=1e-3)
        re_glycerol = reynolds_number(100.0, 1.0, viscosity_pa_s=1.0)
        ratio = re_water / re_glycerol
        assert abs(ratio - 1000.0) < 1.0, (
            f"Expected Re ratio 1000 (µ ratio 1000); got {ratio:.2f}"
        )

    def test_large_channel_high_flow_can_be_turbulent(self):
        """
        A 1 mm diameter channel at very high flow can be in turbulent regime.

        Threshold: Re > 2300.
        Re = ρ·V̄·D/µ, V̄ = 4Q/(πD²)
        For Re = 2300: Q_crit = Re·µ·π·D / (4·ρ) = 2300·1e-3·π·1e-3/(4·1000)
                              = 1.806e-6 m³/s = 108_333 µL/min
        Use Q = 200_000 µL/min to be safely above threshold.
        """
        re = reynolds_number(
            diameter_um=1000.0,
            flow_rate_ul_min=200_000.0,
            density_kg_m3=1000.0,
            viscosity_pa_s=1e-3,
        )
        assert re > 2300, f"Expected turbulent (Re > 2300) for large flow; got Re={re:.1f}"

    def test_invalid_args_raise(self):
        with pytest.raises(ValueError):
            reynolds_number(0.0, 1.0)
        with pytest.raises(ValueError):
            reynolds_number(100.0, -1.0)
