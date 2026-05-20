"""
kerf_systems.components.control
=================================

Control-law lumped-parameter components.

All components operate in continuous time.

Modelica analogues
------------------
  PController          — Modelica.Blocks.Continuous.P
  PIController         — Modelica.Blocks.Continuous.PI
  PIDController        — Modelica.Blocks.Continuous.PID (parallel form)
  Integrator           — Modelica.Blocks.Continuous.Integrator
  Gain                 — Modelica.Blocks.Math.Gain
  TransferFunction1    — first-order lag G(s) = k / (tau*s + 1)
"""

from __future__ import annotations

from typing import Sequence


class PController:
    """
    Proportional controller:  u = Kp * e

    Variables (x_local):
      0  e — error signal (input)
      1  u — control output

    Residual:
      u - Kp * e

    Parameters
    ----------
    Kp : float
        Proportional gain.
    """

    n_vars = 2

    def __init__(self, Kp: float) -> None:
        self.Kp = float(Kp)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["e", "u"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        e, u = x[0], x[1]
        return [u - self.Kp * e]


class PIController:
    """
    Proportional-Integral controller (parallel form):

      u = Kp * e + Ki * xi
      dxi/dt = e   (integral state)

    Variables (x_local):
      0  e   — error
      1  xi  — integral of error
      2  u   — output

    Residuals:
      dxi/dt - e
      u - (Kp*e + Ki*xi)

    Parameters
    ----------
    Kp : float
        Proportional gain.
    Ki : float
        Integral gain (= Kp / Ti).
    """

    n_vars = 3

    def __init__(self, Kp: float, Ki: float) -> None:
        self.Kp = float(Kp)
        self.Ki = float(Ki)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, 0.0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["e", "xi", "u"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        e, xi, u = x[0], x[1], x[2]
        dxi = dx[1]
        return [
            dxi - e,
            u - (self.Kp * e + self.Ki * xi),
        ]


class PIDController:
    """
    Proportional-Integral-Derivative controller (parallel form with
    filtered derivative):

      u = Kp*e + Ki*xi + Kd*xd
      dxi/dt = e
      tau_f * dxd/dt + xd = Kd * de/dt   (first-order derivative filter)

    For simplicity we use the ideal derivative (no filter; set tau_f=0 to
    get ideal D).  With tau_f > 0, xd is a filtered derivative state.

    Variables (x_local):
      0  e   — error
      1  xi  — integral state
      2  xd  — derivative filter state
      3  u   — output

    Residuals:
      dxi/dt - e
      tau_f * dxd/dt + xd - Kd * de/dt   (if tau_f > 0)
      xd - Kd * e                          (ideal, if tau_f == 0)
      u - (Kp*e + Ki*xi + xd)

    Parameters
    ----------
    Kp, Ki, Kd : float
        Parallel PID gains.
    tau_f : float
        Derivative filter time constant [s].  Default 0.0 (ideal D).
    """

    n_vars = 4

    def __init__(self, Kp: float, Ki: float, Kd: float, tau_f: float = 0.0) -> None:
        self.Kp = float(Kp)
        self.Ki = float(Ki)
        self.Kd = float(Kd)
        self.tau_f = float(tau_f)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, 0.0, 0.0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["e", "xi", "xd", "u"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        e, xi, xd, u = x[0], x[1], x[2], x[3]
        dxi = dx[1]
        dxd = dx[2]
        de = dx[0]

        # Integral residual
        r_int = dxi - e

        # Derivative residual
        if self.tau_f > 0.0:
            r_der = self.tau_f * dxd + xd - self.Kd * de
        else:
            r_der = xd - self.Kd * e

        # Output residual
        r_out = u - (self.Kp * e + self.Ki * xi + xd)

        return [r_int, r_der, r_out]


class Integrator:
    """
    Pure integrator:  y = (1/s) * u  →  dy/dt = u

    Variables (x_local):
      0  u — input signal
      1  y — integrated output

    Residual:
      dy/dt - u

    Parameters
    ----------
    k : float
        Integrator gain (default 1.0).
    y0 : float
        Initial output state.
    """

    n_vars = 2

    def __init__(self, k: float = 1.0, y0: float = 0.0) -> None:
        self.k = float(k)
        self.y0 = float(y0)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, self.y0]

    @property
    def var_names(self) -> list[str]:
        return ["u", "y"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        u, y = x[0], x[1]
        dy = dx[1]
        return [dy - self.k * u]


class Gain:
    """
    Static gain block:  y = k * u

    Variables (x_local):
      0  u — input
      1  y — output

    Residual:
      y - k * u

    Parameters
    ----------
    k : float
        Gain.
    """

    n_vars = 2

    def __init__(self, k: float) -> None:
        self.k = float(k)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, 0.0]

    @property
    def var_names(self) -> list[str]:
        return ["u", "y"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        u, y = x[0], x[1]
        return [y - self.k * u]


class TransferFunction1:
    """
    First-order lag transfer function:  G(s) = k / (tau*s + 1)

    Differential form:  tau * dy/dt + y = k * u

    Variables (x_local):
      0  u — input
      1  y — output state

    Residual:
      tau * dy/dt + y - k * u

    Parameters
    ----------
    k : float
        Static gain.
    tau : float
        Time constant [s].
    y0 : float
        Initial output.  Default 0.
    """

    n_vars = 2

    def __init__(self, k: float, tau: float, y0: float = 0.0) -> None:
        if tau <= 0:
            raise ValueError(f"TransferFunction1: tau must be > 0, got {tau}")
        self.k = float(k)
        self.tau = float(tau)
        self.y0 = float(y0)

    @property
    def default_x0(self) -> list[float]:
        return [0.0, self.y0]

    @property
    def var_names(self) -> list[str]:
        return ["u", "y"]

    def residuals(self, t: float, x: Sequence[float], dx: Sequence[float]) -> list[float]:
        u, y = x[0], x[1]
        dy = dx[1]
        return [self.tau * dy + y - self.k * u]
