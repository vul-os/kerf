"""
kerf_cad_core.dynamics — rigid-body dynamics & rotating-machinery balancing.

Public API (re-exported for convenience):

    from kerf_cad_core.dynamics import (
        rectilinear_kinematics,
        projectile_motion,
        rotational_kinematics,
        relative_motion_velocity,
        newton_translation,
        euler_rotation,
        general_plane_motion,
        kinetic_energy,
        work_energy_theorem,
        spring_potential_energy,
        power_from_torque,
        power_from_force,
        linear_impulse,
        angular_impulse,
        direct_impact,
        oblique_impact,
        moi_solid_cylinder,
        moi_hollow_cylinder,
        moi_solid_sphere,
        moi_thin_rod,
        moi_rectangular_plate,
        parallel_axis,
        flywheel_sizing,
        flywheel_rim,
        static_balance,
        dynamic_balance_two_plane,
        residual_unbalance,
        iso1940_grade,
        shaking_force_primary,
        shaking_force_secondary,
        gyroscopic_moment,
    )

Distinct from:
  - kinematics/  : linkage geometry and cam follower motion
  - vibration/   : SDOF/MDOF vibration analysis
  - robotics/    : robot kinematics and dynamics

References
----------
Hibbeler, R.C. "Engineering Mechanics: Dynamics", 14th ed. (Pearson)
Beer, F.P. & Johnston, E.R. "Vector Mechanics for Engineers: Dynamics",
    12th ed. (McGraw-Hill)
ISO 1940-1:2003 — Balance quality requirements for rotors

Author: imranparuk
"""

from kerf_cad_core.dynamics.rigidbody import (
    rectilinear_kinematics,
    projectile_motion,
    rotational_kinematics,
    relative_motion_velocity,
    newton_translation,
    euler_rotation,
    general_plane_motion,
    kinetic_energy,
    work_energy_theorem,
    spring_potential_energy,
    power_from_torque,
    power_from_force,
    linear_impulse,
    angular_impulse,
    direct_impact,
    oblique_impact,
    moi_solid_cylinder,
    moi_hollow_cylinder,
    moi_solid_sphere,
    moi_thin_rod,
    moi_rectangular_plate,
    parallel_axis,
    flywheel_sizing,
    flywheel_rim,
    static_balance,
    dynamic_balance_two_plane,
    residual_unbalance,
    iso1940_grade,
    shaking_force_primary,
    shaking_force_secondary,
    gyroscopic_moment,
)

__all__ = [
    "rectilinear_kinematics",
    "projectile_motion",
    "rotational_kinematics",
    "relative_motion_velocity",
    "newton_translation",
    "euler_rotation",
    "general_plane_motion",
    "kinetic_energy",
    "work_energy_theorem",
    "spring_potential_energy",
    "power_from_torque",
    "power_from_force",
    "linear_impulse",
    "angular_impulse",
    "direct_impact",
    "oblique_impact",
    "moi_solid_cylinder",
    "moi_hollow_cylinder",
    "moi_solid_sphere",
    "moi_thin_rod",
    "moi_rectangular_plate",
    "parallel_axis",
    "flywheel_sizing",
    "flywheel_rim",
    "static_balance",
    "dynamic_balance_two_plane",
    "residual_unbalance",
    "iso1940_grade",
    "shaking_force_primary",
    "shaking_force_secondary",
    "gyroscopic_moment",
]
