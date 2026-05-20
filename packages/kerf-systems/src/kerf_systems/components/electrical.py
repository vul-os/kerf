"""
kerf_systems.components.electrical
====================================

Electrical lumped-parameter components.

Conventions: voltage [V], current [A], positive current into + terminal.

Modelica analogues
------------------
  Resistor      — Modelica.Electrical.Analog.Basic.Resistor
  Capacitor     — Modelica.Electrical.Analog.Basic.Capacitor
  Inductor      — Modelica.Electrical.Analog.Basic.Inductor
  VoltageSource — Modelica.Electrical.Analog.Sources.ConstantVoltage
  CurrentSource — Modelica.Electrical.Analog.Sources.ConstantCurrent
  Ground        — Modelica.Electrical.Analog.Basic.Ground
"""

from __future__ import annotations

import math
from typing import Callable, Sequence


class Resistor:
    """
    Ideal resistor — Ohm's law.

    v = R * i

    Variables (x_local):
      0  v — voltage across resistor [V]
      1  i — current through resistor [A]

    Residual:
      v - R * i

    Parameters
    ----------
    R : float
        Resistance [Ohm]
    """

    n_vars = 2

    def __init__(self, R: float) -> None:
        if R <= 0:
            raise ValueError(f"Resistor: R must be > 0, got {R}")
        self.R = float(R)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["v", "i"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        v, i = x[0], x[1]
        return [v - self.R * i]


class Capacitor:
    """
    Ideal capacitor — C * dv/dt = i.

    Variables (x_local):
      0  v — voltage [V]
      1  i — current [A]

    Residual:
      C * dv/dt - i

    Parameters
    ----------
    C : float
        Capacitance [F]
    v0 : float
        Initial voltage [V].  Default 0.
    """

    n_vars = 2

    def __init__(self, C: float, v0: float = 0.0) -> None:
        if C <= 0:
            raise ValueError(f"Capacitor: C must be > 0, got {C}")
        self.C = float(C)
        self.v0 = float(v0)

    @property
    def default_x0(self) -> list[float]:
        return [self.v0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["v", "i"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        v, i = x[0], x[1]
        dv = dx[0]
        return [self.C * dv - i]


class Inductor:
    """
    Ideal inductor — L * di/dt = v.

    Variables (x_local):
      0  v — voltage [V]
      1  i — current [A]

    Residual:
      L * di/dt - v

    Parameters
    ----------
    L : float
        Inductance [H]
    i0 : float
        Initial current [A].  Default 0.
    """

    n_vars = 2

    def __init__(self, L: float, i0: float = 0.0) -> None:
        if L <= 0:
            raise ValueError(f"Inductor: L must be > 0, got {L}")
        self.L = float(L)
        self.i0 = float(i0)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, self.i0]

    @property
    def var_names(self) -> list[str]:
        return ["v", "i"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        v, i = x[0], x[1]
        di = dx[1]
        return [self.L * di - v]


class VoltageSource:
    """
    Ideal voltage source.

    v = V_src(t)

    Variables (x_local):
      0  v     — source voltage [V]
      1  i_src — current delivered [A]  (sign: positive out of + terminal)

    Residual:
      v - V_src(t)

    Parameters
    ----------
    V : float or callable(t)
        Source voltage [V].
    """

    n_vars = 2

    def __init__(self, V=1.0) -> None:
        self._V = V

    def _get_V(self, t: float) -> float:
        if callable(self._V):
            return float(self._V(t))
        return float(self._V)

    @property
    def default_x0(self) -> list[float]:
        return [self._get_V(0.0), 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["v_src", "i_src"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        v_src = x[0]
        return [v_src - self._get_V(t)]


class CurrentSource:
    """
    Ideal current source.

    i = I_src(t)

    Variables (x_local):
      0  v_src — terminal voltage [V]
      1  i     — delivered current [A]

    Residual:
      i - I_src(t)

    Parameters
    ----------
    I : float or callable(t)
        Source current [A].
    """

    n_vars = 2

    def __init__(self, I=1.0) -> None:
        self._I = I

    def _get_I(self, t: float) -> float:
        if callable(self._I):
            return float(self._I(t))
        return float(self._I)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, self._get_I(0.0)]

    @property
    def var_names(self) -> list[str]:
        return ["v_src", "i_src"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        i = x[1]
        return [i - self._get_I(t)]


class Ground:
    """
    Ground node — sets voltage to zero.

    Variables (x_local):
      0  v_gnd — ground node voltage [V]  (= 0)
      1  i_gnd — current into ground [A]

    Residual:
      v_gnd
    """

    n_vars = 2

    @property
    def default_x0(self) -> list[float]:
        return [0.0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["v_gnd", "i_gnd"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        v_gnd = x[0]
        return [v_gnd]
