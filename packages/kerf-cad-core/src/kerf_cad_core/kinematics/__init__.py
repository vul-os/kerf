"""
kerf_cad_core.kinematics — planar mechanism/linkage kinematics.

Public API (re-exported for convenience):

    from kerf_cad_core.kinematics import (
        four_bar_grashof,
        four_bar_position,
        four_bar_transmission_angle,
        four_bar_coupler_curve,
        slider_crank,
        cam_follower_cycloidal,
        cam_follower_harmonic,
    )

References
----------
Norton, R.L. "Design of Machinery", 5th ed.
Shigley, J.E. & Uicker, J.J. "Theory of Machines & Mechanisms", 4th ed.
Freudenstein, F. (1955). "An Analytical Approach to the Design of Four-Link Mechanisms"

Author: imranparuk
"""

from kerf_cad_core.kinematics.linkage import (
    four_bar_grashof,
    four_bar_position,
    four_bar_transmission_angle,
    four_bar_coupler_curve,
    slider_crank,
    cam_follower_cycloidal,
    cam_follower_harmonic,
)

__all__ = [
    "four_bar_grashof",
    "four_bar_position",
    "four_bar_transmission_angle",
    "four_bar_coupler_curve",
    "slider_crank",
    "cam_follower_cycloidal",
    "cam_follower_harmonic",
]
