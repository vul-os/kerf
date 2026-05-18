"""ADCS — Attitude Determination and Control System.

Submodules:
    attitude          : Quaternion math + Euler's rotation equation + RK4
    reaction_wheels   : Reaction wheel cluster model
    magnetorquer      : Magnetorquer model + simplified WMM B-field
    control_allocation: Control allocation (pseudo-inverse, mixed actuators)
"""

from .attitude import (
    qnorm,
    qnormalize,
    qconjugate,
    qmultiply,
    qrotate,
    qslerp,
    qfrom_axis_angle,
    qto_euler,
    qfrom_dcm,
    qto_dcm,
    rk4_step,
    propagate,
)
from .reaction_wheels import ReactionWheel, ReactionWheelCluster
from .magnetorquer import (
    Magnetorquer,
    MagnetorquerCluster,
    earth_magnetic_field_body,
    leo_circular_orbit_position,
)
from .control_allocation import (
    pseudo_inverse_allocation,
    null_space_projection,
    MixedActuatorAllocator,
    WheelAllocator,
)

__all__ = [
    # Quaternion
    "qnorm",
    "qnormalize",
    "qconjugate",
    "qmultiply",
    "qrotate",
    "qslerp",
    "qfrom_axis_angle",
    "qto_euler",
    "qfrom_dcm",
    "qto_dcm",
    # Dynamics
    "rk4_step",
    "propagate",
    # Actuators
    "ReactionWheel",
    "ReactionWheelCluster",
    "Magnetorquer",
    "MagnetorquerCluster",
    "earth_magnetic_field_body",
    "leo_circular_orbit_position",
    # Control allocation
    "pseudo_inverse_allocation",
    "null_space_projection",
    "MixedActuatorAllocator",
    "WheelAllocator",
]
