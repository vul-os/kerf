"""
kerf_systems.components.hydraulic
===================================

Hydraulic lumped-parameter components.

All flows are volumetric [m³/s], pressures [Pa].

Modelica analogues
------------------
  HydraulicOrifice    — Modelica.Fluid.Fittings.SimpleGenericOrifice
  HydraulicPump       — ideal fixed-displacement pump
  HydraulicTank       — Modelica.Fluid.Vessels.OpenTank (linearised)
  HydraulicResistance — Hagen-Poiseuille pipe resistance
  HydraulicCapacitance — fluid/vessel compliance dV/dp
"""

from __future__ import annotations

import math
from typing import Callable, Sequence


class HydraulicOrifice:
    """
    Turbulent orifice (Torricelli / square-root law).

    q = Cd * A * sqrt(2 * |dp| / rho) * sign(dp)

    Variables (x_local):
      0  p_in   — inlet pressure [Pa]
      1  p_out  — outlet pressure [Pa]
      2  q      — volumetric flow [m³/s]  (positive: in → out)

    Residual:
      q - Cd * A * sqrt(2 * |dp| / rho) * sign(dp)

    Parameters
    ----------
    Cd : float
        Discharge coefficient (0 < Cd ≤ 1).  Default 0.611.
    A : float
        Orifice area [m²].
    rho : float
        Fluid density [kg/m³].  Default 870 (hydraulic oil).
    """

    n_vars = 3

    def __init__(self, A: float, Cd: float = 0.611, rho: float = 870.0) -> None:
        if A <= 0:
            raise ValueError(f"HydraulicOrifice: A must be > 0, got {A}")
        if Cd <= 0 or Cd > 1:
            raise ValueError(f"HydraulicOrifice: Cd must be in (0,1], got {Cd}")
        if rho <= 0:
            raise ValueError(f"HydraulicOrifice: rho must be > 0, got {rho}")
        self.A = float(A)
        self.Cd = float(Cd)
        self.rho = float(rho)

    @property
    def default_x0(self) -> list[float]:
        return [1e5, 0.0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["p_in", "p_out", "q"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        p_in, p_out, q = x[0], x[1], x[2]
        dp = p_in - p_out
        # Regularised sqrt to avoid discontinuity at dp=0
        eps = 1.0  # Pa
        q_ideal = self.Cd * self.A * math.sqrt(2.0 * math.sqrt(dp * dp + eps * eps) / self.rho)
        q_signed = q_ideal * (1.0 if dp >= 0 else -1.0)
        return [q - q_signed]


class HydraulicPump:
    """
    Ideal fixed-displacement pump / motor.

    Delivers: dp = p_out - p_in = delta_p_pump  (prescribed or computed from torque)
    Flow:     q = D * omega  (positive-displacement kinematics)

    For a simple pressure-source model, prescribe delta_p_pump.

    Variables (x_local):
      0  p_in   — inlet pressure [Pa]
      1  p_out  — outlet pressure [Pa]
      2  q      — flow rate [m³/s]

    Residuals:
      (p_out - p_in) - dp_pump
      q - D_pump * omega

    Parameters
    ----------
    D_pump : float
        Displacement [m³/rad].
    omega : float or callable(t)
        Angular velocity [rad/s].
    dp_pump : float or None
        If set, the pump maintains this pressure rise regardless of omega.
    """

    n_vars = 3

    def __init__(self, D_pump: float, omega=100.0, dp_pump=None) -> None:
        if D_pump <= 0:
            raise ValueError(f"HydraulicPump: D_pump must be > 0, got {D_pump}")
        self.D_pump = float(D_pump)
        self._omega = omega
        self._dp_pump = dp_pump

    def _get_omega(self, t: float) -> float:
        if callable(self._omega):
            return float(self._omega(t))
        return float(self._omega)

    def _get_dp(self, t: float) -> float | None:
        if self._dp_pump is None:
            return None
        if callable(self._dp_pump):
            return float(self._dp_pump(t))
        return float(self._dp_pump)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, 1e5, self.D_pump * float(self._omega if not callable(self._omega) else 100.0)]

    @property
    def var_names(self) -> list[str]:
        return ["p_in", "p_out", "q"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        p_in, p_out, q = x[0], x[1], x[2]
        omega = self._get_omega(t)
        dp_prescribed = self._get_dp(t)
        residuals = []
        if dp_prescribed is not None:
            residuals.append((p_out - p_in) - dp_prescribed)
        else:
            residuals.append(q - self.D_pump * omega)
        # Flow equation always present
        if dp_prescribed is not None:
            residuals.append(q - self.D_pump * omega)
        else:
            residuals.append(0.0)  # placeholder, flow already from kinematics
        return residuals[:1]  # single residual for the matched variable


class HydraulicTank:
    """
    Open hydraulic tank — pressure-source boundary condition.

    Tank pressure: p_tank = p_atm + rho * g * h(t)
    where h is the fluid height (can vary if finite volume is tracked).

    For a simple boundary, p is prescribed.

    Variables (x_local):
      0  p_tank  — tank pressure [Pa]
      1  q_in    — net inflow [m³/s]

    Residual:
      p_tank - p_prescribed
      (q_in from network)

    Parameters
    ----------
    p_prescribed : float or callable(t)
        Prescribed tank pressure.  Default 1e5 Pa (atmospheric).
    """

    n_vars = 2

    def __init__(self, p_prescribed=1e5) -> None:
        self._p = p_prescribed

    def _get_p(self, t: float) -> float:
        if callable(self._p):
            return float(self._p(t))
        return float(self._p)

    @property
    def default_x0(self) -> list[float]:
        return [self._get_p(0.0), 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["p_tank", "q_in"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        p_tank = x[0]
        return [p_tank - self._get_p(t)]


class HydraulicResistance:
    """
    Linearised pipe resistance (Hagen-Poiseuille or custom).

    q = (p_in - p_out) / Rf

    Variables (x_local):
      0  p_in   — inlet pressure [Pa]
      1  p_out  — outlet pressure [Pa]
      2  q      — volumetric flow [m³/s]

    Residual:
      q - (p_in - p_out) / Rf

    Parameters
    ----------
    Rf : float
        Fluid resistance [Pa·s/m³]
    """

    n_vars = 3

    def __init__(self, Rf: float) -> None:
        if Rf <= 0:
            raise ValueError(f"HydraulicResistance: Rf must be > 0, got {Rf}")
        self.Rf = float(Rf)

    @property
    def default_x0(self) -> list[float]:
        return [1e5, 0.0, 1e5 / self.Rf]

    @property
    def var_names(self) -> list[str]:
        return ["p_in", "p_out", "q"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        p_in, p_out, q = x[0], x[1], x[2]
        return [q - (p_in - p_out) / self.Rf]


class HydraulicCapacitance:
    """
    Hydraulic capacitance / fluid compressibility.

    C_h * dp/dt = q_in - q_out

    Variables (x_local):
      0  p     — pressure [Pa]
      1  q_net — net inflow [m³/s]

    Residual:
      C_h * dp/dt - q_net

    Parameters
    ----------
    C_h : float
        Hydraulic capacitance [m³/Pa]  (= V / beta, where beta = bulk modulus)
    p0 : float
        Initial pressure [Pa].  Default 1e5.
    """

    n_vars = 2

    def __init__(self, C_h: float, p0: float = 1e5) -> None:
        if C_h <= 0:
            raise ValueError(f"HydraulicCapacitance: C_h must be > 0, got {C_h}")
        self.C_h = float(C_h)
        self.p0 = float(p0)

    @property
    def default_x0(self) -> list[float]:
        return [self.p0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["p", "q_net"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        p, q_net = x[0], x[1]
        dp = dx[0]
        return [self.C_h * dp - q_net]
