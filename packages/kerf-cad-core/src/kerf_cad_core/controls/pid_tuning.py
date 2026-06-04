"""
kerf_cad_core.controls.pid_tuning — PID controller tuning methods.

Public API
----------
PidParams              — Kp, Ki, Kd + setpoint + output_limits dataclass
step_pid               — one PID step with integrator anti-windup
ziegler_nichols_open_loop  — Z-N step-test (open-loop) tuning
ziegler_nichols_closed_loop — Z-N ultimate-gain (closed-loop) tuning
imc_tuning             — IMC / Lambda tuning (Skogestad 2003)
lambda_tuning          — Lambda tuning alias

All pure Python.  No numpy, no scipy.

References
----------
Ziegler, J.G. & Nichols, N.B. (1942). "Optimum Settings for Automatic Controllers."
    Trans. ASME 64, 759–768.
Skogestad, S. (2003). "Simple analytic rules for model reduction and PID
    controller tuning." J. Process Control 13, 291–309.
Åström, K.J. & Hägglund, T. (2006). "Advanced PID Control." ISA.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# PidParams dataclass
# ---------------------------------------------------------------------------

@dataclass
class PidParams:
    """
    PID controller parameters.

    The standard parallel form:
        u(t) = Kp·e + Ki·∫e dt + Kd·de/dt

    Attributes
    ----------
    Kp            : proportional gain
    Ki            : integral gain  (= Kp / Ti)
    Kd            : derivative gain (= Kp · Td)
    setpoint      : desired output value
    output_limits : (min, max) clamp for anti-windup
    """
    Kp: float
    Ki: float
    Kd: float
    setpoint: float = 0.0
    output_limits: tuple[float, float] = (-1e6, 1e6)

    def __post_init__(self) -> None:
        self.Kp = float(self.Kp)
        self.Ki = float(self.Ki)
        self.Kd = float(self.Kd)
        lo, hi = self.output_limits
        if lo > hi:
            raise ValueError("output_limits: min must be <= max")


# ---------------------------------------------------------------------------
# PID step function with anti-windup
# ---------------------------------------------------------------------------

def step_pid(
    state: dict,
    params: PidParams,
    measurement: float,
    dt: float,
) -> tuple[float, dict]:
    """
    Execute one PID controller step using the positional form with
    back-calculation anti-windup.

    Parameters
    ----------
    state       : dict with keys 'integral', 'prev_error' (initialised to 0
                  on first call; pass {} for initial state)
    params      : PidParams
    measurement : current process variable
    dt          : time step (s), must be > 0

    Returns
    -------
    (control_output, new_state)
        new_state keys: 'integral', 'prev_error'

    Anti-windup: integrator is clamped when output saturates
    (back-calculation method).

    References: Åström & Hägglund (2006) §3.5.
    """
    integral = float(state.get("integral", 0.0))
    prev_error = float(state.get("prev_error", 0.0))

    error = params.setpoint - float(measurement)
    lo, hi = params.output_limits

    # Proportional term
    p_term = params.Kp * error

    # Integral term (with anti-windup: don't accumulate if saturated)
    integral += params.Ki * error * dt

    # Derivative term (on measurement to avoid derivative kick on setpoint changes)
    if dt > 0:
        d_term = params.Kd * (error - prev_error) / dt
    else:
        d_term = 0.0

    # Raw output
    output_raw = p_term + integral + d_term

    # Clamp output
    output = max(lo, min(hi, output_raw))

    # Anti-windup: back-calculation — remove the amount that saturated
    if output_raw != output:
        integral -= (output_raw - output)

    new_state = {
        "integral": integral,
        "prev_error": error,
    }
    return output, new_state


# ---------------------------------------------------------------------------
# Ziegler-Nichols open-loop (process reaction curve) tuning
# ---------------------------------------------------------------------------

def ziegler_nichols_open_loop(
    K_process: float,
    tau: float,
    theta: float,
) -> PidParams:
    """
    Ziegler-Nichols open-loop (step-test) PID tuning.

    FOPDT model: G(s) = K e^{-θs} / (τs + 1)

    Z-N formulas (Ziegler & Nichols, 1942):
        Kp = 1.2 · τ / (K · θ)
        Ti = 2 · θ        (integral time)
        Td = 0.5 · θ      (derivative time)
        Ki = Kp / Ti,  Kd = Kp · Td

    Parameters
    ----------
    K_process : process (DC) gain
    tau       : process time constant (s)
    theta     : dead time (s)

    Returns
    -------
    PidParams

    References: Ziegler & Nichols (1942); Ogata (2010) §8-6.
    """
    K_process = float(K_process)
    tau = float(tau)
    theta = float(theta)

    if abs(K_process) < 1e-15:
        raise ValueError("K_process must be non-zero")
    if tau <= 0:
        raise ValueError("tau must be > 0")
    if theta <= 0:
        raise ValueError("theta must be > 0")

    Kp = 1.2 * tau / (K_process * theta)
    Ti = 2.0 * theta
    Td = 0.5 * theta
    Ki = Kp / Ti
    Kd = Kp * Td

    return PidParams(Kp=Kp, Ki=Ki, Kd=Kd)


# ---------------------------------------------------------------------------
# Ziegler-Nichols closed-loop (ultimate gain) tuning
# ---------------------------------------------------------------------------

def ziegler_nichols_closed_loop(
    K_u: float,
    T_u: float,
) -> PidParams:
    """
    Ziegler-Nichols closed-loop (ultimate gain) PID tuning.

    K_u = ultimate gain (proportional gain at stability boundary)
    T_u = ultimate period (s) at stability boundary

    Z-N formulas:
        Kp = 0.6 · K_u
        Ti = 0.5 · T_u,  Ki = Kp / Ti
        Td = 0.125 · T_u, Kd = Kp · Td

    Parameters
    ----------
    K_u : ultimate gain
    T_u : ultimate period (s)

    Returns
    -------
    PidParams

    References: Ziegler & Nichols (1942); Ogata (2010) §8-7.
    """
    K_u = float(K_u)
    T_u = float(T_u)

    if K_u <= 0:
        raise ValueError("K_u must be > 0")
    if T_u <= 0:
        raise ValueError("T_u must be > 0")

    Kp = 0.6 * K_u
    Ti = 0.5 * T_u
    Td = 0.125 * T_u
    Ki = Kp / Ti
    Kd = Kp * Td

    return PidParams(Kp=Kp, Ki=Ki, Kd=Kd)


# ---------------------------------------------------------------------------
# IMC / Lambda tuning (Skogestad 2003)
# ---------------------------------------------------------------------------

def imc_tuning(
    K_process: float,
    tau: float,
    theta: float,
    lambda_c: float,
) -> PidParams:
    """
    Internal Model Control (IMC) based PID tuning.

    FOPDT model: G(s) = K e^{-θs} / (τs + 1)

    Skogestad (2003) IMC-PID formulas:
        Kp = τ / (K · (λ + θ))
        Ti = τ                    (integral time)
        Td = θ / 2               (derivative time, Pade half)
        Ki = Kp / Ti,  Kd = Kp · Td

    The tuning parameter λ (lambda_c) is the desired closed-loop time constant.
    Recommended: λ ≥ max(0.25·τ, θ).

    Parameters
    ----------
    K_process : process gain
    tau       : process time constant (s)
    theta     : dead time (s)
    lambda_c  : desired closed-loop time constant (s)

    Returns
    -------
    PidParams

    References: Skogestad (2003); Åström & Hägglund (2006) §8.3.
    """
    K_process = float(K_process)
    tau = float(tau)
    theta = float(theta)
    lambda_c = float(lambda_c)

    if abs(K_process) < 1e-15:
        raise ValueError("K_process must be non-zero")
    if tau <= 0:
        raise ValueError("tau must be > 0")
    if theta <= 0:
        raise ValueError("theta must be > 0")
    if lambda_c <= 0:
        raise ValueError("lambda_c must be > 0")

    Kp = tau / (K_process * (lambda_c + theta))
    Ti = tau
    Td = theta / 2.0
    Ki = Kp / Ti
    Kd = Kp * Td

    return PidParams(Kp=Kp, Ki=Ki, Kd=Kd)


# ---------------------------------------------------------------------------
# Lambda tuning (alias / variant)
# ---------------------------------------------------------------------------

def lambda_tuning(
    K_process: float,
    tau: float,
    theta: float,
    tau_c: float,
) -> PidParams:
    """
    Lambda tuning method (first-order closed-loop).

    Identical to IMC tuning (imc_tuning) but uses the conventional notation
    τ_c for the desired closed-loop time constant.

    Kp = τ / (K · (τ_c + θ))
    Ti = τ
    Td = θ / 2

    Parameters
    ----------
    K_process : process gain
    tau       : process time constant (s)
    theta     : dead time (s)
    tau_c     : desired closed-loop time constant (s)

    Returns
    -------
    PidParams

    References: Skogestad (2003); Åström & Hägglund (2006).
    """
    return imc_tuning(K_process, tau, theta, tau_c)
