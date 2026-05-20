"""
Tests for kerf_systems component library.

Covers all 20+ components:
  - Electrical: Resistor, Capacitor, Inductor, VoltageSource, CurrentSource, Ground
  - Thermal: ThermalMass, ThermalResistance, ThermalCapacitance, ThermalSource, TemperatureSensor
  - Hydraulic: HydraulicOrifice, HydraulicPump, HydraulicTank, HydraulicResistance, HydraulicCapacitance
  - Control: PController, PIController, PIDController, Integrator, Gain, TransferFunction1
"""

from __future__ import annotations

import math
import pytest


# ---------------------------------------------------------------------------
# Electrical components
# ---------------------------------------------------------------------------

class TestResistor:
    def test_ohm_law(self):
        from kerf_systems.components.electrical import Resistor
        r = Resistor(R=100.0)
        # v = R*i = 100*2 = 200 → residual = 200 - 100*2 = 0
        res = r.residuals(0.0, [200.0, 2.0], [0.0, 0.0])
        assert len(res) == 1
        assert abs(res[0]) < 1e-12

    def test_bad_R(self):
        from kerf_systems.components.electrical import Resistor
        with pytest.raises(ValueError):
            Resistor(R=-1.0)
        with pytest.raises(ValueError):
            Resistor(R=0.0)

    def test_var_names(self):
        from kerf_systems.components.electrical import Resistor
        r = Resistor(R=1.0)
        assert "v" in r.var_names
        assert "i" in r.var_names
        assert r.n_vars == 2

    def test_nonzero_residual(self):
        from kerf_systems.components.electrical import Resistor
        r = Resistor(R=10.0)
        # v=5, i=1 → residual = 5 - 10*1 = -5
        res = r.residuals(0.0, [5.0, 1.0], [0.0, 0.0])
        assert abs(res[0] - (-5.0)) < 1e-12


class TestCapacitor:
    def test_residual_zero(self):
        from kerf_systems.components.electrical import Capacitor
        # C=1e-6, dv=1e6 A/s, i=1A → C*dv/dt - i = 1e-6*1e6 - 1 = 0
        c = Capacitor(C=1e-6)
        res = c.residuals(0.0, [0.0, 1.0], [1e6, 0.0])
        assert abs(res[0]) < 1e-10

    def test_bad_C(self):
        from kerf_systems.components.electrical import Capacitor
        with pytest.raises(ValueError):
            Capacitor(C=0.0)

    def test_initial_voltage(self):
        from kerf_systems.components.electrical import Capacitor
        c = Capacitor(C=1e-3, v0=5.0)
        assert abs(c.default_x0[0] - 5.0) < 1e-12


class TestInductor:
    def test_residual_zero(self):
        from kerf_systems.components.electrical import Inductor
        # L=1e-3, di/dt=1000 A/s, v=1V → L*di/dt - v = 1e-3*1000 - 1 = 0
        l = Inductor(L=1e-3)
        res = l.residuals(0.0, [1.0, 0.0], [0.0, 1000.0])
        assert abs(res[0]) < 1e-10

    def test_bad_L(self):
        from kerf_systems.components.electrical import Inductor
        with pytest.raises(ValueError):
            Inductor(L=0.0)


class TestVoltageSource:
    def test_constant(self):
        from kerf_systems.components.electrical import VoltageSource
        vs = VoltageSource(V=12.0)
        # v_src should equal 12
        res = vs.residuals(0.0, [12.0, 1.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_residual_nonzero(self):
        from kerf_systems.components.electrical import VoltageSource
        vs = VoltageSource(V=12.0)
        res = vs.residuals(0.0, [10.0, 1.0], [0.0, 0.0])
        assert abs(res[0] - (-2.0)) < 1e-12

    def test_callable(self):
        from kerf_systems.components.electrical import VoltageSource
        vs = VoltageSource(V=lambda t: math.sin(t))
        res = vs.residuals(math.pi / 2, [1.0, 0.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12


class TestCurrentSource:
    def test_constant(self):
        from kerf_systems.components.electrical import CurrentSource
        cs = CurrentSource(I=5.0)
        res = cs.residuals(0.0, [0.0, 5.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12


class TestGround:
    def test_ground_zero(self):
        from kerf_systems.components.electrical import Ground
        g = Ground()
        res = g.residuals(0.0, [0.0, 0.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_ground_nonzero(self):
        from kerf_systems.components.electrical import Ground
        g = Ground()
        res = g.residuals(0.0, [1.5, 0.0], [0.0, 0.0])
        assert abs(res[0] - 1.5) < 1e-12


# ---------------------------------------------------------------------------
# Thermal components
# ---------------------------------------------------------------------------

class TestThermalMass:
    def test_residual_zero(self):
        from kerf_systems.components.thermal import ThermalMass
        # m=1, cp=1000, dT/dt=0.1, Q_net=100 → 1*1000*0.1 - 100 = 0
        tm = ThermalMass(m=1.0, cp=1000.0)
        res = tm.residuals(0.0, [300.0, 100.0], [0.1, 0.0])
        assert abs(res[0]) < 1e-10

    def test_bad_params(self):
        from kerf_systems.components.thermal import ThermalMass
        with pytest.raises(ValueError):
            ThermalMass(m=0.0, cp=1000.0)
        with pytest.raises(ValueError):
            ThermalMass(m=1.0, cp=0.0)

    def test_initial_temp(self):
        from kerf_systems.components.thermal import ThermalMass
        tm = ThermalMass(m=1.0, cp=1000.0, T0=350.0)
        assert abs(tm.default_x0[0] - 350.0) < 1e-12


class TestThermalResistance:
    def test_heat_flow(self):
        from kerf_systems.components.thermal import ThermalResistance
        # R_th=0.5, T_hot=100, T_cold=20 → Q = (100-20)/0.5 = 160
        tr = ThermalResistance(R_th=0.5)
        res = tr.residuals(0.0, [100.0, 20.0, 160.0], [0.0, 0.0, 0.0])
        assert abs(res[0]) < 1e-10

    def test_bad_R_th(self):
        from kerf_systems.components.thermal import ThermalResistance
        with pytest.raises(ValueError):
            ThermalResistance(R_th=0.0)


class TestThermalCapacitance:
    def test_residual(self):
        from kerf_systems.components.thermal import ThermalCapacitance
        # C_th=500, dT/dt=0.2, Q=100 → 500*0.2 - 100 = 0
        tc = ThermalCapacitance(C_th=500.0)
        res = tc.residuals(0.0, [300.0, 100.0], [0.2, 0.0])
        assert abs(res[0]) < 1e-10

    def test_bad_C_th(self):
        from kerf_systems.components.thermal import ThermalCapacitance
        with pytest.raises(ValueError):
            ThermalCapacitance(C_th=0.0)


class TestThermalSource:
    def test_temperature_mode(self):
        from kerf_systems.components.thermal import ThermalSource
        ts = ThermalSource(mode="temperature", value=400.0)
        res = ts.residuals(0.0, [400.0, 10.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_heatflow_mode(self):
        from kerf_systems.components.thermal import ThermalSource
        ts = ThermalSource(mode="heatflow", value=500.0)
        res = ts.residuals(0.0, [300.0, 500.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_bad_mode(self):
        from kerf_systems.components.thermal import ThermalSource
        with pytest.raises(ValueError):
            ThermalSource(mode="invalid")


class TestTemperatureSensor:
    def test_passthrough(self):
        from kerf_systems.components.thermal import TemperatureSensor
        ts = TemperatureSensor()
        res = ts.residuals(0.0, [350.0, 350.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_nonzero(self):
        from kerf_systems.components.thermal import TemperatureSensor
        ts = TemperatureSensor()
        res = ts.residuals(0.0, [350.0, 340.0], [0.0, 0.0])
        assert abs(res[0] - (-10.0)) < 1e-12


# ---------------------------------------------------------------------------
# Hydraulic components
# ---------------------------------------------------------------------------

class TestHydraulicOrifice:
    def test_flow_direction_positive(self):
        from kerf_systems.components.hydraulic import HydraulicOrifice
        # Large A to get simple case
        h = HydraulicOrifice(A=1e-4, Cd=1.0, rho=1000.0)
        # For dp=1e4 Pa, q_expected ≈ A * sqrt(2*dp/rho) = 1e-4 * sqrt(20) ≈ 4.47e-4
        dp = 1e4
        q_exp = 1e-4 * math.sqrt(2 * dp / 1000.0)
        res = h.residuals(0.0, [1e4, 0.0, q_exp], [0.0, 0.0, 0.0])
        assert abs(res[0]) < q_exp * 0.01  # within 1%

    def test_bad_params(self):
        from kerf_systems.components.hydraulic import HydraulicOrifice
        with pytest.raises(ValueError):
            HydraulicOrifice(A=0.0)
        with pytest.raises(ValueError):
            HydraulicOrifice(A=1e-4, Cd=0.0)


class TestHydraulicPump:
    def test_kinematics(self):
        from kerf_systems.components.hydraulic import HydraulicPump
        # D=1e-5 m³/rad, omega=100 rad/s → q = 1e-3 m³/s
        pump = HydraulicPump(D_pump=1e-5, omega=100.0)
        res = pump.residuals(0.0, [0.0, 1e5, 1e-3], [0.0, 0.0, 0.0])
        assert abs(res[0]) < 1e-10

    def test_bad_D(self):
        from kerf_systems.components.hydraulic import HydraulicPump
        with pytest.raises(ValueError):
            HydraulicPump(D_pump=0.0)


class TestHydraulicTank:
    def test_pressure_source(self):
        from kerf_systems.components.hydraulic import HydraulicTank
        tank = HydraulicTank(p_prescribed=1e5)
        res = tank.residuals(0.0, [1e5, 0.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-10

    def test_pressure_deviation(self):
        from kerf_systems.components.hydraulic import HydraulicTank
        tank = HydraulicTank(p_prescribed=1e5)
        res = tank.residuals(0.0, [2e5, 0.0], [0.0, 0.0])
        assert abs(res[0] - 1e5) < 1.0


class TestHydraulicResistance:
    def test_flow(self):
        from kerf_systems.components.hydraulic import HydraulicResistance
        # Rf=1e6, p_in=1e5, p_out=0 → q = 1e5/1e6 = 0.1
        hr = HydraulicResistance(Rf=1e6)
        res = hr.residuals(0.0, [1e5, 0.0, 0.1], [0.0, 0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_bad_Rf(self):
        from kerf_systems.components.hydraulic import HydraulicResistance
        with pytest.raises(ValueError):
            HydraulicResistance(Rf=0.0)


class TestHydraulicCapacitance:
    def test_residual(self):
        from kerf_systems.components.hydraulic import HydraulicCapacitance
        # C_h=1e-9, dp/dt=1e6 Pa/s, q=1e-3 → 1e-9*1e6 - 1e-3 = 0
        hc = HydraulicCapacitance(C_h=1e-9)
        res = hc.residuals(0.0, [1e5, 1e-3], [1e6, 0.0])
        assert abs(res[0]) < 1e-12

    def test_bad_C(self):
        from kerf_systems.components.hydraulic import HydraulicCapacitance
        with pytest.raises(ValueError):
            HydraulicCapacitance(C_h=0.0)


# ---------------------------------------------------------------------------
# Control components
# ---------------------------------------------------------------------------

class TestPController:
    def test_output(self):
        from kerf_systems.components.control import PController
        # Kp=5, e=2 → u=10
        p = PController(Kp=5.0)
        res = p.residuals(0.0, [2.0, 10.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_nonzero(self):
        from kerf_systems.components.control import PController
        p = PController(Kp=5.0)
        res = p.residuals(0.0, [2.0, 5.0], [0.0, 0.0])
        assert abs(res[0] - (-5.0)) < 1e-12


class TestPIController:
    def test_residuals(self):
        from kerf_systems.components.control import PIController
        # Kp=2, Ki=1, e=1, xi=1 → u=2*1+1*1=3; dxi=e=1
        pi = PIController(Kp=2.0, Ki=1.0)
        res = pi.residuals(0.0, [1.0, 1.0, 3.0], [0.0, 1.0, 0.0])
        assert len(res) == 2
        assert abs(res[0]) < 1e-12  # dxi - e
        assert abs(res[1]) < 1e-12  # u - (Kp*e + Ki*xi)

    def test_n_vars(self):
        from kerf_systems.components.control import PIController
        pi = PIController(Kp=1.0, Ki=1.0)
        assert pi.n_vars == 3


class TestPIDController:
    def test_residuals_ideal_d(self):
        from kerf_systems.components.control import PIDController
        # tau_f=0 (ideal D), Kp=1, Ki=1, Kd=0.1
        # e=1, xi=0.5, xd=0.1*1=0.1, u = 1*1 + 1*0.5 + 0.1 = 1.6
        pid = PIDController(Kp=1.0, Ki=1.0, Kd=0.1, tau_f=0.0)
        res = pid.residuals(0.0, [1.0, 0.5, 0.1, 1.6], [0.0, 1.0, 0.0, 0.0])
        assert len(res) == 3
        for r in res:
            assert abs(r) < 1e-12

    def test_n_vars(self):
        from kerf_systems.components.control import PIDController
        pid = PIDController(Kp=1.0, Ki=1.0, Kd=0.1)
        assert pid.n_vars == 4


class TestIntegrator:
    def test_residual(self):
        from kerf_systems.components.control import Integrator
        # k=1, u=3, dy/dt=3 → 3 - 3 = 0
        ig = Integrator(k=1.0)
        res = ig.residuals(0.0, [3.0, 0.0], [0.0, 3.0])
        assert abs(res[0]) < 1e-12

    def test_gain(self):
        from kerf_systems.components.control import Integrator
        ig = Integrator(k=2.0)
        res = ig.residuals(0.0, [1.0, 0.0], [0.0, 2.0])
        assert abs(res[0]) < 1e-12


class TestGain:
    def test_gain(self):
        from kerf_systems.components.control import Gain
        g = Gain(k=3.0)
        res = g.residuals(0.0, [4.0, 12.0], [0.0, 0.0])
        assert abs(res[0]) < 1e-12

    def test_nonzero(self):
        from kerf_systems.components.control import Gain
        g = Gain(k=3.0)
        res = g.residuals(0.0, [4.0, 10.0], [0.0, 0.0])
        assert abs(res[0] - (-2.0)) < 1e-12


class TestTransferFunction1:
    def test_residual_zero(self):
        from kerf_systems.components.control import TransferFunction1
        # tau*dy/dt + y = k*u → 2*1 + 3 = 2*1 + 2*1.5  → check specific values
        # tau=2, k=2, u=1.5 → steady: y=k*u=3; at steady state dy/dt=0 → 0 + 3 = 2*1.5=3 ✓
        tf = TransferFunction1(k=2.0, tau=2.0)
        res = tf.residuals(0.0, [1.5, 3.0], [0.0, 0.0])
        # tau*dy/dt + y - k*u = 2*0 + 3 - 2*1.5 = 0
        assert abs(res[0]) < 1e-12

    def test_bad_tau(self):
        from kerf_systems.components.control import TransferFunction1
        with pytest.raises(ValueError):
            TransferFunction1(k=1.0, tau=0.0)


# ---------------------------------------------------------------------------
# Component count
# ---------------------------------------------------------------------------

class TestComponentCount:
    def test_at_least_20_components(self):
        """The component library must have >= 20 components."""
        from kerf_systems import components
        comp_names = components.__all__
        assert len(comp_names) >= 20, (
            f"Expected >= 20 components, got {len(comp_names)}: {comp_names}"
        )
