"""
kerf_aero.flight_dynamics — 6-DOF flight dynamics and atmosphere model.

Sub-modules
-----------
atmosphere
    U.S. Standard Atmosphere 1976 model (0–86 km).
sixdof
    Quaternion-attitude 6-DOF equations of motion with RK4 integrator.
coefficients
    Aerodynamic coefficient tables (CL, CD, Cm) with bilinear interpolation;
    includes a Cessna 172-class example dataset.

Quick-start
-----------
>>> from kerf_aero.flight_dynamics import atmosphere, sixdof, coefficients
>>> state = atmosphere.atmosphere(0.0)           # sea level
>>> state.temperature_K
288.15
>>> body = sixdof.RigidBody(mass_kg=1111.0, Ixx=1285.0, Iyy=1825.0,
...                         Izz=2667.0, Ixz=0.0)
>>> s0 = sixdof.level_flight_state(50.0, 1000.0)
"""

from . import atmosphere, coefficients, sixdof
from .atmosphere import AtmosphereState, atmosphere as std_atmosphere
from .sixdof import (
    Forces,
    RigidBody,
    SixDOFState,
    eom,
    euler_to_quat,
    integrate,
    level_flight_state,
    quat_to_euler,
    rk4_step,
    state_from_array,
    state_to_array,
)
from .coefficients import AircraftCoefficients, CESSNA172, get_coefficients

__all__ = [
    # sub-modules
    "atmosphere",
    "sixdof",
    "coefficients",
    # atmosphere
    "AtmosphereState",
    "std_atmosphere",
    # sixdof
    "Forces",
    "RigidBody",
    "SixDOFState",
    "eom",
    "euler_to_quat",
    "integrate",
    "level_flight_state",
    "quat_to_euler",
    "rk4_step",
    "state_from_array",
    "state_to_array",
    # coefficients
    "AircraftCoefficients",
    "CESSNA172",
    "get_coefficients",
]
