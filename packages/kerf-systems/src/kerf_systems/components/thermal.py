"""
kerf_systems.components.thermal
================================

Thermal lumped-parameter components.

All components follow the kerf_systems component convention:

    Component.residuals(t, x_local, dx_local) -> list[float]

where x_local / dx_local are the component's own state/derivative slice.

Modelica analogues
------------------
  ThermalMass         — Modelica.Thermal.HeatTransfer.Components.HeatCapacitor
  ThermalResistance   — Modelica.Thermal.HeatTransfer.Components.ThermalResistor
  ThermalCapacitance  — Modelica.Thermal.HeatTransfer.Components.HeatCapacitor
  ThermalSource       — fixed temperature or prescribed heat-flow source
  TemperatureSensor   — algebraic temperature measurement
"""

from __future__ import annotations

import math
from typing import Callable, Sequence


class ThermalMass:
    """
    Thermal mass (heat capacitor).

    ODE:  m*cp * dT/dt = Q_net

    State variables (x_local):
      0  T      — temperature [K or °C]
      1  Q_net  — net heat flow into mass [W]  (algebraic; set by network)

    Residuals:
      0  m*cp * dT/dt - Q_net
      1  (connectivity — Q_net set by parent network)

    Parameters
    ----------
    m : float
        Mass [kg]
    cp : float
        Specific heat capacity [J/(kg·K)]
    T0 : float
        Initial temperature.  Default 293.15 K.
    """

    n_vars = 2

    def __init__(self, m: float, cp: float, T0: float = 293.15) -> None:
        if m <= 0:
            raise ValueError(f"ThermalMass: m must be > 0, got {m}")
        if cp <= 0:
            raise ValueError(f"ThermalMass: cp must be > 0, got {cp}")
        self.m = float(m)
        self.cp = float(cp)
        self.T0 = float(T0)

    @property
    def default_x0(self) -> list[float]:
        return [self.T0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["T", "Q_net"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        T, Q_net = x[0], x[1]
        dT = dx[0]
        return [self.m * self.cp * dT - Q_net]


class ThermalResistance:
    """
    Thermal resistance (conduction / convection path).

    Algebraic:  Q = (T_hot - T_cold) / R_th

    State variables (x_local):
      0  T_hot  — hot-side temperature [K]
      1  T_cold — cold-side temperature [K]
      2  Q      — heat flow from hot to cold [W]

    Residual:
      Q - (T_hot - T_cold) / R_th

    Parameters
    ----------
    R_th : float
        Thermal resistance [K/W]
    """

    n_vars = 3

    def __init__(self, R_th: float) -> None:
        if R_th <= 0:
            raise ValueError(f"ThermalResistance: R_th must be > 0, got {R_th}")
        self.R_th = float(R_th)

    @property
    def default_x0(self) -> list[float]:
        return [400.0, 300.0, 100.0 / self.R_th]

    @property
    def var_names(self) -> list[str]:
        return ["T_hot", "T_cold", "Q"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        T_hot, T_cold, Q = x[0], x[1], x[2]
        return [Q - (T_hot - T_cold) / self.R_th]


class ThermalCapacitance:
    """
    Thermal capacitance (identical to ThermalMass but expressed directly
    as thermal capacitance C_th = m * cp).

    ODE:  C_th * dT/dt = Q_net

    State variables (x_local):
      0  T      — temperature [K]
      1  Q_net  — net heat flow [W]

    Parameters
    ----------
    C_th : float
        Thermal capacitance [J/K]
    T0 : float
        Initial temperature [K].  Default 293.15.
    """

    n_vars = 2

    def __init__(self, C_th: float, T0: float = 293.15) -> None:
        if C_th <= 0:
            raise ValueError(f"ThermalCapacitance: C_th must be > 0, got {C_th}")
        self.C_th = float(C_th)
        self.T0 = float(T0)

    @property
    def default_x0(self) -> list[float]:
        return [self.T0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["T", "Q_net"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        T, Q_net = x[0], x[1]
        dT = dx[0]
        return [self.C_th * dT - Q_net]


class ThermalSource:
    """
    Fixed-temperature or prescribed heat-flow source.

    Mode 'temperature': enforces T = T_prescribed (algebraic)
    Mode 'heatflow':    provides Q = Q_prescribed

    State variables (x_local):
      mode='temperature': [T, Q_out]  (T fixed; Q_out = network heat extracted)
      mode='heatflow':    [T_port, Q] (Q fixed; T_port is result)

    For simplicity, both modes have 2 variables.

    Parameters
    ----------
    mode : str
        'temperature' or 'heatflow'
    value : float or callable(t) -> float
        Prescribed temperature [K] or heat flow [W].
    """

    n_vars = 2

    def __init__(self, mode: str = "temperature", value=293.15) -> None:
        if mode not in ("temperature", "heatflow"):
            raise ValueError(f"ThermalSource: mode must be 'temperature' or 'heatflow', got {mode!r}")
        self.mode = mode
        self._value = value

    def _get_value(self, t: float) -> float:
        if callable(self._value):
            return float(self._value(t))
        return float(self._value)

    @property
    def default_x0(self) -> list[float]:
        v = self._get_value(0.0)
        if self.mode == "temperature":
            return [v, 0.0]
        return [v, v]

    @property
    def var_names(self) -> list[str]:
        if self.mode == "temperature":
            return ["T_src", "Q_out"]
        return ["T_port", "Q_src"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        v = self._get_value(t)
        if self.mode == "temperature":
            T_src = x[0]
            return [T_src - v]
        else:
            Q_src = x[1]
            return [Q_src - v]


class TemperatureSensor:
    """
    Ideal temperature sensor — algebraic passthrough.

    Variables (x_local):
      0  T_in    — input temperature [K]
      1  T_meas  — measured temperature [K]

    Residual:
      T_meas - T_in == 0
    """

    n_vars = 2

    @property
    def default_x0(self) -> list[float]:
        return [293.15, 293.15]

    @property
    def var_names(self) -> list[str]:
        return ["T_in", "T_meas"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        T_in, T_meas = x[0], x[1]
        return [T_meas - T_in]
