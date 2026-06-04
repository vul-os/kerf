# robotics

*Module: `kerf_cad_core.robotics.tools` · Domain: cad*

This module registers **9** LLM tool(s):

- [`robot_fk`](#robot-fk)
- [`robot_end_effector_pose`](#robot-end-effector-pose)
- [`robot_ik_2r_planar`](#robot-ik-2r-planar)
- [`robot_ik_3r_planar`](#robot-ik-3r-planar)
- [`robot_jacobian`](#robot-jacobian)
- [`robot_manipulability`](#robot-manipulability)
- [`robot_workspace`](#robot-workspace)
- [`robot_trajectory_trapezoidal`](#robot-trajectory-trapezoidal)
- [`robot_ik_spatial_dls`](#robot-ik-spatial-dls)

---

## `robot_fk`

Denavit-Hartenberg forward kinematics for a serial robot arm.

Computes the 4×4 homogeneous end-effector transform T_0n by chaining individual DH matrices for each joint.

Standard DH convention (Craig):
  T_i = Rz(theta_i) · Tz(d_i) · Tx(a_i) · Rx(alpha_i)

dh_params: list of n rows, each [a_i, alpha_i_deg, d_i, theta_offset_deg].
joint_angles_deg: list of n joint angles (degrees) added to theta_offset.

Returns the 4×4 transform matrix and any joint-limit warnings.

Errors: {ok:false, reason} for mismatched array lengths.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "dh_params": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 4,
        "maxItems": 4
      },
      "description": "List of n DH rows: [[a_i, alpha_i_deg, d_i, theta_offset_deg], ...]."
    },
    "joint_angles_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "List of n joint angles (degrees)."
    },
    "joint_limits_deg": {
      "type": "array",
      "items": {
        "type": [
          "array",
          "null"
        ],
        "items": {
          "type": "number"
        }
      },
      "description": "Optional list of [lo_deg, hi_deg] per joint, or null to skip. Warnings emitted for out-of-limit joints."
    }
  },
  "required": [
    "dh_params",
    "joint_angles_deg"
  ]
}
```

---

## `robot_end_effector_pose`

Extract end-effector position and ZYX Euler angles from a 4×4 homogeneous transform matrix.

ZYX convention: R = Rz(yaw) · Ry(pitch) · Rx(roll).

Typically used after robot_fk to get the human-readable pose.

Returns x, y, z (metres) and roll_deg, pitch_deg, yaw_deg.

Errors: {ok:false, reason} for invalid matrix.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "matrix": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 4,
        "maxItems": 4
      },
      "minItems": 4,
      "maxItems": 4,
      "description": "4\u00d74 homogeneous transform matrix (list of 4 rows \u00d7 4 columns)."
    }
  },
  "required": [
    "matrix"
  ]
}
```

---

## `robot_ik_2r_planar`

Closed-form inverse kinematics for a planar 2R robot arm.

Solves for joint angles (q1, q2) such that the end-effector reaches (px, py) in the plane.

Two solutions exist (elbow-up and elbow-down).  The requested solution is returned; if the target is outside the reachable workspace, the nearest boundary point is used and 'reachable: false' is set.

Returns q1_deg, q2_deg (and radians), reachable flag, and warnings.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "l1": {
      "type": "number",
      "description": "Length of link 1 (metres, > 0)."
    },
    "l2": {
      "type": "number",
      "description": "Length of link 2 (metres, > 0)."
    },
    "px": {
      "type": "number",
      "description": "Target x position (metres)."
    },
    "py": {
      "type": "number",
      "description": "Target y position (metres)."
    },
    "elbow_up": {
      "type": "boolean",
      "description": "True (default) for elbow-up; False for elbow-down."
    },
    "joint_limits_deg": {
      "type": "array",
      "items": {
        "type": [
          "array",
          "null"
        ],
        "items": {
          "type": "number"
        }
      },
      "description": "Optional [[lo1,hi1],[lo2,hi2]] joint limits in degrees. Warnings emitted for violations."
    }
  },
  "required": [
    "l1",
    "l2",
    "px",
    "py"
  ]
}
```

---

## `robot_ik_3r_planar`

Closed-form inverse kinematics for a planar 3R robot arm.

Solves for (q1, q2, q3) such that the end-effector reaches (px, py) with orientation phi_deg (total arm angle from x-axis, degrees).

The problem is decomposed: the wrist centre (base of link 3) is found analytically, then a 2R sub-problem is solved.

Returns q1_deg, q2_deg, q3_deg (and radians), reachable flag, warnings.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "l1": {
      "type": "number",
      "description": "Link 1 length (metres, > 0)."
    },
    "l2": {
      "type": "number",
      "description": "Link 2 length (metres, > 0)."
    },
    "l3": {
      "type": "number",
      "description": "Link 3 length (metres, > 0)."
    },
    "px": {
      "type": "number",
      "description": "Target x position (metres)."
    },
    "py": {
      "type": "number",
      "description": "Target y position (metres)."
    },
    "phi_deg": {
      "type": "number",
      "description": "Desired end-effector angle from x-axis (degrees, default 0)."
    },
    "joint_limits_deg": {
      "type": "array",
      "items": {
        "type": [
          "array",
          "null"
        ],
        "items": {
          "type": "number"
        }
      },
      "description": "Optional joint limits [[lo,hi]\u00d73] in degrees."
    }
  },
  "required": [
    "l1",
    "l2",
    "l3",
    "px",
    "py"
  ]
}
```

---

## `robot_jacobian`

Compute the 6×n geometric Jacobian for a serial robot arm.

Maps joint velocities to end-effector spatial velocity [v; omega].
For revolute joint i:
  J_v_i = z_{i-1} × (p_n - p_{i-1})
  J_w_i = z_{i-1}

dh_params: [[a_i, alpha_i_deg, d_i, theta_offset_deg], ...]
joint_angles_deg: n joint angles (degrees).

Returns the 6×n Jacobian matrix, singularity flag, and warnings.

Errors: {ok:false, reason} for mismatched lengths.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "dh_params": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 4,
        "maxItems": 4
      },
      "description": "DH parameter rows: [[a_i, alpha_i_deg, d_i, theta_offset_deg], ...]."
    },
    "joint_angles_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Joint angles (degrees)."
    }
  },
  "required": [
    "dh_params",
    "joint_angles_deg"
  ]
}
```

---

## `robot_manipulability`

Compute the Yoshikawa manipulability measure for a robot at a given configuration.

w = sqrt(det(J · J^T))

w = 0 indicates a singular configuration (no motion in some direction).
Higher w indicates greater dexterity.

Accepts the 6×n Jacobian directly (as returned by robot_jacobian).

Errors: {ok:false, reason} for invalid Jacobian.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "J": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      },
      "description": "6\u00d7n Jacobian matrix (list of 6 rows)."
    }
  },
  "required": [
    "J"
  ]
}
```

---

## `robot_workspace`

Estimate workspace radius bounds for a serial robot arm from DH parameters.

r_max = sum of effective link lengths (Euclidean of a_i and d_i).
r_min = max(0, r_max - 2 × min_link), the inner void radius.

dh_params: [[a_i, alpha_i_deg, d_i, theta_offset_deg], ...]

Returns r_max and r_min in metres.

Errors: {ok:false, reason} for invalid input.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "dh_params": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 4,
        "maxItems": 4
      },
      "description": "DH parameter rows: [[a_i, alpha_i_deg, d_i, theta_offset_deg], ...]."
    }
  },
  "required": [
    "dh_params"
  ]
}
```

---

## `robot_trajectory_trapezoidal`

Generate a joint-space trapezoidal velocity trajectory.

All joints are time-scaled to the same duration T_sync (the joint requiring the longest motion drives the duration).  Each joint follows an individual trapezoidal or triangular velocity profile.

Returns sampled times, positions, and velocities for all joints.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "q_start_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Start joint angles (degrees)."
    },
    "q_end_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "End joint angles (degrees)."
    },
    "v_max_deg_s": {
      "type": "number",
      "description": "Maximum joint velocity (degrees/s, > 0)."
    },
    "a_max_deg_s2": {
      "type": "number",
      "description": "Maximum joint acceleration (degrees/s\u00b2, > 0)."
    },
    "dt_s": {
      "type": "number",
      "description": "Time step (seconds, default 0.01)."
    }
  },
  "required": [
    "q_start_deg",
    "q_end_deg",
    "v_max_deg_s",
    "a_max_deg_s2"
  ]
}
```

---

## `robot_ik_spatial_dls`

Numerical inverse kinematics for a general n-DOF DH chain via damped least-squares (Levenberg-Marquardt) on the geometric Jacobian.

Iterates q ← q + α Jᵀ(JJᵀ + λ²I)⁻¹ e until the 6-D task error e = [Δposition; Δorientation] falls below tolerance.

dh_params rows: [a_i, alpha_i_deg, d_i, theta_offset_deg].
q_init_deg: initial joint angles (degrees).
target_T: 4×4 target homogeneous transform.

Returns q_rad, q_deg, converged, iterations, pos_error_m, rot_error_rad.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "dh_params": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 4,
        "maxItems": 4
      },
      "description": "List of n DH rows [a_i, alpha_i_deg, d_i, theta_offset_deg]."
    },
    "q_init_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Initial joint angles (degrees), length n."
    },
    "target_T": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      },
      "description": "4\u00d74 target end-effector homogeneous transform."
    },
    "lam": {
      "type": "number",
      "description": "Damping factor \u03bb (default 0.05). Larger = more regularisation."
    },
    "pos_tol": {
      "type": "number",
      "description": "Position tolerance (m, default 1e-4)."
    },
    "rot_tol": {
      "type": "number",
      "description": "Rotation tolerance (rad, default 1e-3)."
    },
    "max_iter": {
      "type": "integer",
      "description": "Maximum iterations (default 200)."
    },
    "alpha_gain": {
      "type": "number",
      "description": "Step size gain (default 1.0)."
    }
  },
  "required": [
    "dh_params",
    "q_init_deg",
    "target_T"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
