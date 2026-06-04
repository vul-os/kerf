# Robot Arm Kinematics (DH, IK, Jacobian)

*Domain: Mechanical · Module: `packages/kerf-cad-core/src/kerf_cad_core/robotics/arm.py` · Shipped: Wave 9*

## Overview

Serial robot arm kinematics using Denavit-Hartenberg (DH) parameters: forward kinematics chain, end-effector pose, analytical IK for 2-R and 3-R planar arms, spatial damped-least-squares IK for 6-DOF arms, geometric Jacobian, manipulability index, and joint-space trapezoidal trajectory planning. All pure Python; no ROS required.

## When to use

- Computing the workspace and reachability of a robot arm.
- Generating joint-space trajectories for a pick-and-place motion.
- Checking manipulability near singularities before deploying a motion plan.
- Prototyping an IK solution for a custom arm configuration.

## API

```python
from kerf_cad_core.robotics.arm import (
    dh_matrix, fk_chain, end_effector_pose,
    ik_2r_planar, ik_spatial_dls,
    geometric_jacobian, manipulability,
    joint_trajectory_trapezoidal,
)

# DH parameters: [a, alpha, d, theta_offset] per joint
dh = [
    [0.0, 0.0,    0.1, 0.0],
    [0.4, 0.0,    0.0, 0.0],
    [0.3, 0.0,    0.0, 0.0],
]
q = [0.1, 0.5, -0.3]   # joint angles (rad)

T_chain = fk_chain(dh_params=dh, joint_angles=q)
pose = end_effector_pose(T_chain[-1])

J = geometric_jacobian(dh, q)
m = manipulability(J)
print(m["manipulability_index"])
```

## LLM tools

`feature_robot_fk`, `feature_robot_ik`, `feature_robot_trajectory`

## References

- Craig, *Introduction to Robotics: Mechanics and Control*, 3rd ed. (2004).
- Nakamura, *Advanced Robotics: Redundancy and Optimization* (1991).

## Honest caveats

Analytical IK solutions are provided for 2-R and 3-R planar arms only. The spatial DLS IK is iterative and may not converge for configurations near singularities or outside the workspace. Joint limits are not enforced — add limit clamping after each IK iteration. The DH convention used is the standard (non-modified) Craig convention.
