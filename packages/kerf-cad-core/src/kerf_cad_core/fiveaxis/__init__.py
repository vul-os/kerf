"""
kerf_cad_core.fiveaxis — 5-axis machine-tool kinematics & post-processing.

Provides pure-Python models for table-table (AC trunnion), head-head (BC spindle),
and table-head machine configurations.  Includes forward kinematics (rotary + linear
axes → tool tip & axis in part frame), inverse post-processing (tool tip + tool axis
vector → rotary angles + XYZ with RTCP/TCP pivot-length compensation), multiple
inverse solutions, shortest-angular-path selection, singularity/over-travel detection,
linearisation-error estimation, and simple collision-cone clearance checks.

Author: imranparuk
"""
from kerf_cad_core.fiveaxis.kinematics import (
    MachineConfig,
    MachineType,
    forward_kinematics,
    inverse_post,
    tool_axis_from_lead_lag,
    linearisation_segments,
    rotary_feedrate,
    collision_cone_check,
)

__all__ = [
    "MachineConfig",
    "MachineType",
    "forward_kinematics",
    "inverse_post",
    "tool_axis_from_lead_lag",
    "linearisation_segments",
    "rotary_feedrate",
    "collision_cone_check",
]
