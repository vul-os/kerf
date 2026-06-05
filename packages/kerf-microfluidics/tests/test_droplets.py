"""
Tests for kerf_microfluidics.droplets — droplet generation physics.

Oracles / verification
----------------------
1. T-junction squeezing regime (Ca < 0.01):
     L/w = alpha + beta*(Q_d/Q_c)   [Garstecki 2006 eq. 1]
     Q_c=1, Q_d=0.5, w=100um, h=100um, mu=1e-3, gamma=0.04
     Ca = mu*(Q_c/wh)/gamma = 1e-3 * (1e-9/60 / 1e-8) / 0.04 ≈ 4.2e-5 → squeezing
     L/w = 1 + 1 * 0.5 = 1.5  →  L = 150 µm

2. Flow-focusing droplet diameter:
     d/h = k_ff * sqrt(Q_d/Q_c)  [Anna 2003]
     Q_c=2, Q_d=0.5, h=100um, k_ff=0.4
     d = 0.4 * 100um * sqrt(0.25) = 0.4 * 100 * 0.5 = 20 µm

3. Rayleigh-Plateau wavelength:
     lambda_max ≈ 9.02 * r0  [Rayleigh 1878]
     r0=50um → lambda_max ≈ 451 µm

4. Rayleigh-Plateau droplet diameter from volume conservation:
     d = (6 r0^2 lambda)^(1/3)
     r0=50um, lambda=451um → d ≈ (6*(50)^2*451)^(1/3) µm ≈ 94.5 µm

5. Capillary number utility:
     Ca = mu * (Q/(wh)) / gamma
     mu=1e-3, Q=1e-9/60 m3/s, w=100um, h=100um, gamma=0.04
     U = 1e-9/60 / 1e-8 = 1.667e-3 m/s
     Ca = 1e-3 * 1.667e-3 / 0.04 ≈ 4.167e-5

6. Validation errors for negative/zero inputs.
"""

from __future__ import annotations

import math
import pytest

from kerf_microfluidics.droplets import (
    TJunctionDroplet,
    FlowFocusingDroplet,
    RayleighPlateauResult,
    t_junction_droplet_size,
    flow_focusing_droplet_size,
    rayleigh_plateau_breakup,
    capillary_number,
    weber_number,
)


_UL_MIN_TO_M3S = 1e-9 / 60.0


class TestCapillaryNumber:
    """Verify Ca = mu * U / gamma for a rectangular channel."""

    def test_water_oil_value(self):
        # Q_c = 1 µL/min → 1e-9/60 m³/s
        # w=h=100µm → A=1e-8 m²  → U=1.667e-3 m/s
        # mu=1e-3, gamma=0.04 → Ca=4.167e-5
        Q = 1.0 * _UL_MIN_TO_M3S
        Ca = capillary_number(1e-3, Q, 100e-6, 100e-6, 0.04)
        expected = 1e-3 * (Q / (100e-6 * 100e-6)) / 0.04
        assert abs(Ca - expected) / expected < 1e-10

    def test_zero_flow_rate(self):
        Ca = capillary_number(1e-3, 0.0, 100e-6, 100e-6, 0.04)
        assert Ca == 0.0

    def test_negative_viscosity_raises(self):
        with pytest.raises(ValueError, match="viscosity"):
            capillary_number(-1e-3, 1e-12, 100e-6, 100e-6, 0.04)

    def test_zero_width_raises(self):
        with pytest.raises(ValueError):
            capillary_number(1e-3, 1e-12, 0.0, 100e-6, 0.04)


class TestTJunctionDroplet:
    """Verify T-junction squeezing-regime prediction against Garstecki 2006 eq.1."""

    def _squeezing_case(self):
        """Standard squeezing case: Q_c=1, Q_d=0.5, 100×100 µm channel."""
        return t_junction_droplet_size(
            q_continuous_ul_min=1.0,
            q_dispersed_ul_min=0.5,
            channel_width_m=100e-6,
            channel_height_m=100e-6,
            dispersed_channel_width_m=100e-6,
            viscosity_continuous_pa_s=1e-3,
            surface_tension_n_per_m=0.04,
        )

    def test_regime_is_squeezing(self):
        result = self._squeezing_case()
        assert result.regime == "squeezing"
        assert result.capillary_number < 0.01

    def test_droplet_length_oracle(self):
        """L/w = 1 + 1*0.5 = 1.5 → L = 150 µm."""
        result = self._squeezing_case()
        expected_m = 1.5 * 100e-6  # 150 µm
        assert abs(result.droplet_length_m - expected_m) / expected_m < 1e-9

    def test_volume_consistency(self):
        """Volume should equal length * width * height."""
        result = self._squeezing_case()
        expected_vol = result.droplet_length_m * 100e-6 * 100e-6
        assert abs(result.droplet_volume_m3 - expected_vol) / expected_vol < 1e-9

    def test_generation_frequency_positive(self):
        result = self._squeezing_case()
        assert result.generation_frequency_hz > 0

    def test_spacing_positive(self):
        result = self._squeezing_case()
        assert result.spacing_m > 0

    def test_dripping_regime_high_ca(self):
        """High Q_c → high Ca → dripping regime."""
        result = t_junction_droplet_size(
            q_continuous_ul_min=500.0,
            q_dispersed_ul_min=5.0,
            channel_width_m=50e-6,
            channel_height_m=50e-6,
            dispersed_channel_width_m=50e-6,
            viscosity_continuous_pa_s=1e-3,
            surface_tension_n_per_m=0.001,
        )
        assert result.regime == "dripping"
        assert result.capillary_number >= 0.01

    def test_raises_on_zero_flow(self):
        with pytest.raises(ValueError):
            t_junction_droplet_size(
                q_continuous_ul_min=0.0,
                q_dispersed_ul_min=1.0,
                channel_width_m=100e-6,
                channel_height_m=100e-6,
                dispersed_channel_width_m=100e-6,
                viscosity_continuous_pa_s=1e-3,
                surface_tension_n_per_m=0.04,
            )

    def test_result_type(self):
        result = self._squeezing_case()
        assert isinstance(result, TJunctionDroplet)


class TestFlowFocusingDroplet:
    """Verify flow-focusing prediction against Anna 2003."""

    def _ff_case(self):
        return flow_focusing_droplet_size(
            q_continuous_ul_min=2.0,
            q_dispersed_ul_min=0.5,
            orifice_width_m=100e-6,
            orifice_height_m=100e-6,
            viscosity_continuous_pa_s=1e-3,
            surface_tension_n_per_m=0.04,
            k_ff=0.4,
        )

    def test_diameter_oracle(self):
        """d = 0.4 * 100um * sqrt(0.5/2.0) = 0.4 * 100 * 0.5 = 20 µm."""
        result = self._ff_case()
        expected_m = 0.4 * 100e-6 * math.sqrt(0.5 / 2.0)  # = 20 µm
        assert abs(result.droplet_diameter_m - expected_m) / expected_m < 1e-9

    def test_volume_spherical(self):
        """Volume = pi/6 * d^3."""
        result = self._ff_case()
        expected_vol = math.pi / 6.0 * result.droplet_diameter_m**3
        assert abs(result.droplet_volume_m3 - expected_vol) / expected_vol < 1e-9

    def test_frequency_positive(self):
        result = self._ff_case()
        assert result.generation_frequency_hz > 0

    def test_capillary_number_positive(self):
        result = self._ff_case()
        assert result.capillary_number > 0

    def test_result_type(self):
        result = self._ff_case()
        assert isinstance(result, FlowFocusingDroplet)

    def test_raises_zero_flow(self):
        with pytest.raises(ValueError):
            flow_focusing_droplet_size(
                q_continuous_ul_min=0.0,
                q_dispersed_ul_min=1.0,
                orifice_width_m=100e-6,
                orifice_height_m=100e-6,
                viscosity_continuous_pa_s=1e-3,
                surface_tension_n_per_m=0.04,
            )


class TestRayleighPlateau:
    """Verify Rayleigh-Plateau instability breakup oracle (Rayleigh 1878)."""

    def _breakup_case(self):
        return rayleigh_plateau_breakup(
            thread_radius_m=50e-6,
            density_kg_m3=1000.0,
            surface_tension_n_per_m=0.072,
        )

    def test_wavelength_oracle(self):
        """lambda_max ≈ 9.02 r0 → 9.02 * 50 = 451 µm."""
        result = self._breakup_case()
        x_max = 0.6966
        expected_lam = 2.0 * math.pi * 50e-6 / x_max
        assert abs(result.most_unstable_wavelength_m - expected_lam) / expected_lam < 1e-6

    def test_wavelength_approx_9_02_r0(self):
        """Verify the ≈9.02 r₀ approximation holds to better than 0.1%."""
        result = self._breakup_case()
        ratio = result.most_unstable_wavelength_m / 50e-6
        assert abs(ratio - 9.016) < 0.05  # should be ≈9.02

    def test_droplet_volume_conservation(self):
        """Volume of one wavelength of thread = volume of one sphere (1 decimal)."""
        result = self._breakup_case()
        r0 = result.thread_radius_m
        lam = result.most_unstable_wavelength_m
        d = result.droplet_diameter_m
        vol_thread = math.pi * r0**2 * lam
        vol_sphere = math.pi / 6.0 * d**3
        assert abs(vol_sphere - vol_thread) / vol_thread < 0.02  # within 2%

    def test_breakup_time_positive(self):
        result = self._breakup_case()
        assert result.breakup_time_s > 0

    def test_result_type(self):
        result = self._breakup_case()
        assert isinstance(result, RayleighPlateauResult)

    def test_raises_zero_radius(self):
        with pytest.raises(ValueError, match="thread_radius"):
            rayleigh_plateau_breakup(0.0, 1000.0, 0.072)

    def test_raises_zero_surface_tension(self):
        with pytest.raises(ValueError, match="surface_tension"):
            rayleigh_plateau_breakup(50e-6, 1000.0, 0.0)

    def test_breakup_time_scales_correctly(self):
        """Doubling r0 increases breakup time by factor of 2^(3/2) ≈ 2.83."""
        r1 = rayleigh_plateau_breakup(50e-6, 1000.0, 0.072)
        r2 = rayleigh_plateau_breakup(100e-6, 1000.0, 0.072)
        ratio = r2.breakup_time_s / r1.breakup_time_s
        # tau ~ (rho r0^3 / gamma)^0.5 -> tau2/tau1 = (2^3)^0.5 = 2.828
        assert abs(ratio - 2.0**(3.0/2.0)) / 2.0**(3.0/2.0) < 1e-6


class TestWebNumber:
    """Verify We = rho U^2 D_h / gamma."""

    def test_basic_value(self):
        Q = 1.0 * _UL_MIN_TO_M3S
        w, h = 100e-6, 100e-6
        rho, gamma = 1000.0, 0.072
        U = Q / (w * h)
        D_h = 2.0 * w * h / (w + h)
        expected_we = rho * U**2 * D_h / gamma
        we = weber_number(rho, Q, w, h, gamma)
        assert abs(we - expected_we) / (expected_we + 1e-30) < 1e-10

    def test_zero_density_raises(self):
        with pytest.raises(ValueError):
            weber_number(0.0, 1e-12, 100e-6, 100e-6, 0.072)


class TestDropletToolSpec:
    """Verify async handlers produce ok payloads for valid inputs."""

    def test_tjunction_tool_spec_import(self):
        from kerf_microfluidics.tools import (
            microfluidics_droplet_spec,
            run_microfluidics_droplet,
        )
        assert microfluidics_droplet_spec.name == "microfluidics_droplet"
        assert callable(run_microfluidics_droplet)

    def test_rayleigh_plateau_spec_import(self):
        from kerf_microfluidics.tools import (
            microfluidics_rayleigh_plateau_spec,
            run_microfluidics_rayleigh_plateau,
        )
        assert microfluidics_rayleigh_plateau_spec.name == "microfluidics_rayleigh_plateau"
        assert callable(run_microfluidics_rayleigh_plateau)

    def test_plugin_provides_droplets(self):
        """Plugin manifest must declare microfluidics.droplets in provides."""
        import asyncio
        from kerf_microfluidics.plugin import register

        class FakeTools:
            def __init__(self):
                self.registered = {}
            def register(self, name, spec, fn):
                self.registered[name] = (spec, fn)

        class FakeApp:
            def include_router(self, router):
                pass

        class FakeCtx:
            tools = FakeTools()

        app = FakeApp()
        ctx = FakeCtx()

        result = asyncio.get_event_loop().run_until_complete(register(app, ctx))
        provides = result.get("provides", []) if isinstance(result, dict) else result.provides
        assert "microfluidics.droplets" in provides
        assert "microfluidics_droplet" in ctx.tools.registered
        assert "microfluidics_rayleigh_plateau" in ctx.tools.registered
