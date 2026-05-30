"""
kerf_motion.tools
=================
LLM-callable tool surface for the motion plugin.

Tools
-----
simulate_motion   — run a multibody dynamics simulation
solve_ik          — inverse kinematics for a serial arm
compute_workspace — 2-D workspace cloud for a serial arm

All tools return JSON-serialisable dicts.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_motion._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# simulate_motion
# ---------------------------------------------------------------------------

simulate_motion_spec = ToolSpec(
    name="simulate_motion",
    description=(
        "Run a multibody rigid-body dynamics simulation using RK4 integration. "
        "Supports gravity, spring-damper, and applied force/torque fields. "
        "Returns time-series trajectories (position, velocity) for each body."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bodies": {
                "type": "array",
                "description": "List of rigid body definitions.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "mass": {"type": "number"},
                        "inertia": {
                            "type": "array",
                            "description": "3x3 inertia tensor as list of 3 rows, each with 3 values",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                        "velocity": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    },
                    "required": ["mass"],
                },
            },
            "forces": {
                "type": "array",
                "description": "List of force field specifications.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["gravity", "applied", "spring_damper", "table_driver"]},
                        "g": {"type": "number"},
                        "body_idx": {"type": "integer"},
                        "force": {"type": "array", "items": {"type": "number"}},
                        "torque": {"type": "array", "items": {"type": "number"}},
                        "body_a": {"type": "integer"},
                        "body_b": {"type": "integer"},
                        "k": {"type": "number"},
                        "c": {"type": "number"},
                        "natural_length": {"type": "number"},
                        "table_times": {"type": "array", "items": {"type": "number"},
                                        "description": "Time stamps for position-vs-time table driver (s)."},
                        "table_thetas": {"type": "array", "items": {"type": "number"},
                                         "description": "Target angular positions (rad) at each table time."},
                        "inertia": {"type": "number",
                                    "description": "Scalar moment of inertia for inverse-dynamics torque (kg·m²)."},
                        "damping": {"type": "number",
                                    "description": "Viscous damping coefficient (N·m·s/rad). Default 0."},
                        "axis": {"type": "array", "items": {"type": "number"},
                                 "description": "Drive axis [ax, ay, az]. Default [0,0,1]."},
                    },
                    "required": ["type"],
                },
            },
            "dt": {"type": "number", "description": "Time step in seconds."},
            "n_steps": {"type": "integer", "description": "Number of integration steps."},
            "record_every": {"type": "integer", "default": 1},
        },
        "required": ["bodies", "dt", "n_steps"],
    },
)


async def run_simulate_motion(params: Dict, ctx: ProjectCtx) -> str:
    try:
        from kerf_motion.body import RigidBody
        from kerf_motion.forces import gravity as gravity_ff, applied_force, spring_damper, table_driver_torque
        from kerf_motion.integrator import simulate

        # Build bodies
        bodies = []
        for bd in params["bodies"]:
            mass = bd["mass"]
            inertia_raw = bd.get("inertia", [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
            I = tuple(tuple(float(v) for v in row) for row in inertia_raw)
            pos = tuple(bd.get("position", [0, 0, 0]))
            vel = tuple(bd.get("velocity", [0, 0, 0]))
            name = bd.get("name", f"body_{len(bodies)}")
            bodies.append(RigidBody(
                mass=mass,
                inertia_tensor=I,  # type: ignore[arg-type]
                position=pos,  # type: ignore[arg-type]
                velocity=vel,  # type: ignore[arg-type]
                name=name,
            ))

        # Build force fields
        force_fields = []
        for fspec in params.get("forces", []):
            ftype = fspec["type"]
            if ftype == "gravity":
                g_val = fspec.get("g", 9.80665)
                force_fields.append(gravity_ff(g=g_val, axis=1, sign=-1))
            elif ftype == "applied":
                bidx = fspec.get("body_idx", 0)
                fv = tuple(fspec.get("force", [0, 0, 0]))
                tv = tuple(fspec.get("torque", [0, 0, 0]))
                force_fields.append(applied_force(bidx, fv, tv))  # type: ignore[arg-type]
            elif ftype == "spring_damper":
                force_fields.append(spring_damper(
                    body_a_idx=fspec["body_a"],
                    body_b_idx=fspec.get("body_b", -1),
                    k=fspec["k"],
                    c=fspec.get("c", 0.0),
                    natural_length=fspec.get("natural_length", 1.0),
                ))
            elif ftype == "table_driver":
                bidx = int(fspec.get("body_idx", 0))
                t_times = [float(v) for v in fspec.get("table_times", [])]
                t_thetas = [float(v) for v in fspec.get("table_thetas", [])]
                inertia_val = float(fspec.get("inertia", 1.0))
                damping_val = float(fspec.get("damping", 0.0))
                axis_raw = fspec.get("axis", [0.0, 0.0, 1.0])
                axis_val = tuple(float(v) for v in axis_raw)
                force_fields.append(table_driver_torque(
                    bidx,
                    t_times,
                    t_thetas,
                    inertia=inertia_val,
                    damping=damping_val,
                    axis=axis_val,  # type: ignore[arg-type]
                ))

        dt = float(params["dt"])
        n_steps = int(params["n_steps"])
        record_every = int(params.get("record_every", 1))

        result = simulate(bodies, [], force_fields, dt, n_steps, record_every=record_every)

        if not result["ok"]:
            return err_payload(result.get("reason", "simulation failed"), "MOTION_SIM_ERROR")

        # Serialise trajectories
        traj_out = []
        for body_traj in result["trajectories"]:
            traj_out.append([
                {
                    "t": snap.t,
                    "position": list(snap.position),
                    "velocity": list(snap.velocity),
                }
                for snap in body_traj
            ])

        return ok_payload({
            "ok": True,
            "t": result["t"],
            "trajectories": traj_out,
            "n_steps": result["n_steps"],
            "dt": result["dt"],
        })

    except Exception as exc:
        return err_payload(str(exc), "MOTION_SIM_ERROR")


# ---------------------------------------------------------------------------
# solve_ik
# ---------------------------------------------------------------------------

solve_ik_spec = ToolSpec(
    name="solve_ik",
    description=(
        "Compute joint angles for a serial robot arm to reach a target end-effector position. "
        "Supports analytic 2-link planar arm or numerical Jacobian-transpose for n-DOF chains."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["analytic_2link", "jacobian_transpose"],
                "description": "IK solver method.",
            },
            "links": {
                "type": "array",
                "description": "Link lengths [l1, l2, ...] in metres.",
                "items": {"type": "number"},
            },
            "target": {
                "type": "array",
                "description": "Target end-effector position [x, y, z] in metres.",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 3,
            },
            "elbow_up": {"type": "boolean", "default": True},
            "tol": {"type": "number", "default": 1e-6},
            "max_iterations": {"type": "integer", "default": 1000},
        },
        "required": ["method", "links", "target"],
    },
)


async def run_solve_ik(params: Dict, ctx: ProjectCtx) -> str:
    try:
        from kerf_motion.joints import RevoluteJoint
        from kerf_motion.inverse_kinematics import analytic_ik_2link, jacobian_transpose_ik

        method = params["method"]
        links = params["links"]
        target_raw = params["target"]
        target = (
            float(target_raw[0]),
            float(target_raw[1]),
            float(target_raw[2]) if len(target_raw) > 2 else 0.0,
        )

        if method == "analytic_2link":
            if len(links) < 2:
                return err_payload("analytic_2link requires at least 2 link lengths", "IK_ERROR")
            result = analytic_ik_2link(
                links[0], links[1],
                target[0], target[1],
                elbow_up=bool(params.get("elbow_up", True)),
            )
            if not result["ok"]:
                return err_payload(result.get("reason", "IK failed"), "IK_UNREACHABLE")
            return ok_payload(result)

        elif method == "jacobian_transpose":
            # Build revolute joints for each link, then a fixed offset for the
            # last link segment so the end-effector is at the tip of the last link.
            from kerf_motion.joints import FixedJoint

            joints = []
            offset = 0.0
            for i, l in enumerate(links):
                j = RevoluteJoint(
                    parent_idx=i,
                    child_idx=i + 1,
                    axis=(0.0, 0.0, 1.0),
                    parent_offset=(offset, 0.0, 0.0),
                    name=f"j{i}",
                )
                joints.append(j)
                offset = l  # next joint at end of this link
            # Final link segment: fixed offset = last link length along local X
            joints.append(FixedJoint(
                parent_idx=len(links),
                child_idx=len(links) + 1,
                parent_offset=(links[-1], 0.0, 0.0),
                name="ee",
            ))

            result = jacobian_transpose_ik(
                joints, target,
                tol=float(params.get("tol", 1e-6)),
                max_iterations=int(params.get("max_iterations", 1000)),
            )
            if not result["ok"]:
                return err_payload(
                    result.get("reason", "IK did not converge"),
                    "IK_NO_CONVERGENCE",
                )
            return ok_payload(result)

        else:
            return err_payload(f"Unknown IK method: {method}", "IK_BAD_METHOD")

    except Exception as exc:
        return err_payload(str(exc), "IK_ERROR")


# ---------------------------------------------------------------------------
# compute_workspace
# ---------------------------------------------------------------------------

compute_workspace_spec = ToolSpec(
    name="compute_workspace",
    description=(
        "Sample the reachable workspace of a serial robot arm by sweeping all joint angles. "
        "Returns a cloud of end-effector positions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "links": {
                "type": "array",
                "description": "Link lengths in metres.",
                "items": {"type": "number"},
            },
            "n_samples": {
                "type": "integer",
                "default": 200,
                "description": "Approximate total number of sampled configurations.",
            },
            "limits": {
                "type": "array",
                "description": "Optional joint limits [[lo1,hi1], [lo2,hi2], ...] in radians.",
                "items": {"type": "array", "items": {"type": "number"}},
            },
        },
        "required": ["links"],
    },
)


async def run_compute_workspace(params: Dict, ctx: ProjectCtx) -> str:
    try:
        from kerf_motion.joints import RevoluteJoint
        from kerf_motion.inverse_kinematics import compute_workspace_2d

        from kerf_motion.joints import FixedJoint

        links = params["links"]
        limits_raw = params.get("limits", [])

        joints = []
        offset = 0.0
        for i, l in enumerate(links):
            lim = None
            if i < len(limits_raw):
                lim = (float(limits_raw[i][0]), float(limits_raw[i][1]))
            j = RevoluteJoint(
                parent_idx=i,
                child_idx=i + 1,
                axis=(0.0, 0.0, 1.0),
                parent_offset=(offset, 0.0, 0.0),
                limits=lim,
                name=f"j{i}",
            )
            joints.append(j)
            offset = l
        # Final link segment
        joints.append(FixedJoint(
            parent_idx=len(links),
            child_idx=len(links) + 1,
            parent_offset=(links[-1], 0.0, 0.0),
            name="ee",
        ))

        n_samples = int(params.get("n_samples", 200))
        result = compute_workspace_2d(joints, n_samples=n_samples)

        if not result["ok"]:
            return err_payload(result.get("reason", "workspace failed"), "WORKSPACE_ERROR")

        return ok_payload({
            "ok": True,
            "count": result["count"],
            "points": [list(p) for p in result["points"]],
        })

    except Exception as exc:
        return err_payload(str(exc), "WORKSPACE_ERROR")


# ---------------------------------------------------------------------------
# motion_inverse_dynamics
# ---------------------------------------------------------------------------

motion_inverse_dynamics_spec = ToolSpec(
    name="motion_inverse_dynamics",
    description=(
        "Compute joint torques required to produce a given motion trajectory "
        "using the Recursive Newton-Euler algorithm (Featherstone 2008 §5.3). "
        "Given joint positions q, velocities q̇, and accelerations q̈, returns "
        "the joint torques τ that produce the specified motion. "
        "Supports revolute and prismatic joints in serial kinematic chains. "
        "The two-pass RNE forward pass propagates kinematics base→tip; "
        "the backward pass propagates forces tip→base to extract torques."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "links": {
                "type": "array",
                "description": (
                    "List of link descriptors, one per joint (base→tip). "
                    "Each has: mass (kg), length (m), inertia (optional 3×3 matrix, "
                    "defaults to uniform rod), com_offset (optional [x,y,z] in link "
                    "frame, defaults to [length/2, 0, 0])."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "mass": {"type": "number"},
                        "length": {"type": "number"},
                        "inertia": {
                            "type": "array",
                            "description": "3×3 inertia tensor as list of 3 rows.",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "com_offset": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                    },
                    "required": ["mass", "length"],
                },
            },
            "joint_axes": {
                "type": "array",
                "description": "Rotation axis for each revolute joint, e.g. [[0,0,1], [0,0,1]]. Defaults to [0,0,1] for each joint.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "trajectory": {
                "type": "array",
                "description": (
                    "Trajectory as a list of time-steps. Each element: "
                    "[t, q, q_dot, q_ddot] where q/q_dot/q_ddot are arrays "
                    "of length n_joints."
                ),
                "items": {
                    "type": "array",
                    "description": "[t, [q...], [q_dot...], [q_ddot...]]",
                },
            },
            "gravity": {
                "type": "array",
                "description": "Gravity vector [gx,gy,gz] in m/s². Default [0,0,-9.81].",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
        },
        "required": ["links", "trajectory"],
    },
)


async def run_motion_inverse_dynamics(params: Dict, ctx: ProjectCtx) -> str:
    try:
        from kerf_motion.joints import RevoluteJoint
        from kerf_motion.inverse_dynamics import (
            Robot, compute_joint_torques_from_trajectory,
        )

        links_raw = params["links"]
        n = len(links_raw)
        axes_raw = params.get("joint_axes", [[0.0, 0.0, 1.0]] * n)

        # Build joints
        joints = []
        offset = 0.0
        for i, link_def in enumerate(links_raw):
            length = float(link_def["length"])
            ax = tuple(float(v) for v in axes_raw[i]) if i < len(axes_raw) else (0.0, 0.0, 1.0)
            j = RevoluteJoint(
                parent_idx=i,
                child_idx=i + 1,
                axis=ax,  # type: ignore[arg-type]
                parent_offset=(offset, 0.0, 0.0),
                name=f"j{i}",
            )
            joints.append(j)
            offset = length

        # Build masses, inertias, CoM offsets
        masses = []
        inertias = []
        com_offsets = []
        for link_def in links_raw:
            m = float(link_def["mass"])
            L = float(link_def["length"])
            masses.append(m)
            if "inertia" in link_def:
                I_raw = link_def["inertia"]
                I = tuple(tuple(float(v) for v in row) for row in I_raw)
            else:
                # Uniform rod default: I_zz = mL²/12 about CoM
                Izz = m * L ** 2 / 12.0
                I = ((Izz, 0.0, 0.0), (0.0, Izz, 0.0), (0.0, 0.0, Izz))
            inertias.append(I)  # type: ignore[arg-type]
            if "com_offset" in link_def:
                com_offsets.append(tuple(float(v) for v in link_def["com_offset"]))
            else:
                com_offsets.append((L / 2.0, 0.0, 0.0))

        robot = Robot(
            joints=joints,
            link_masses=masses,
            link_inertias=inertias,  # type: ignore[arg-type]
            com_offsets=com_offsets,  # type: ignore[arg-type]
        )

        grav_raw = params.get("gravity", [0.0, 0.0, -9.81])
        gravity = tuple(float(v) for v in grav_raw)  # type: ignore[arg-type]

        # Build trajectory
        traj = []
        for step in params["trajectory"]:
            t, q, qd, qdd = step[0], step[1], step[2], step[3]
            traj.append((float(t), [float(v) for v in q],
                         [float(v) for v in qd], [float(v) for v in qdd]))

        torques = compute_joint_torques_from_trajectory(robot, traj, gravity=gravity)

        return ok_payload({
            "ok": True,
            "n_steps": len(torques),
            "n_joints": n,
            "torques": torques,
        })

    except Exception as exc:
        return err_payload(str(exc), "INVERSE_DYNAMICS_ERROR")


# ---------------------------------------------------------------------------
# motion_gravity_compensation
# ---------------------------------------------------------------------------

motion_gravity_compensation_spec = ToolSpec(
    name="motion_gravity_compensation",
    description=(
        "Compute joint torques required to hold a robot stationary at a given "
        "configuration against gravity (gravity compensation / static equilibrium). "
        "Uses the Recursive Newton-Euler algorithm with zero velocity and "
        "acceleration: τ = RNE(robot, q, 0, 0, gravity). "
        "Returns the torque each joint must apply to balance the weight of all "
        "links distal to it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "links": {
                "type": "array",
                "description": "List of link descriptors (mass, length, optional inertia/com_offset).",
                "items": {
                    "type": "object",
                    "properties": {
                        "mass": {"type": "number"},
                        "length": {"type": "number"},
                        "inertia": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "com_offset": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                    },
                    "required": ["mass", "length"],
                },
            },
            "joint_axes": {
                "type": "array",
                "description": "Rotation axis per joint [[x,y,z], ...]. Default [0,0,1].",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "q": {
                "type": "array",
                "description": "Joint angles (rad) for static configuration.",
                "items": {"type": "number"},
            },
            "gravity": {
                "type": "array",
                "description": "Gravity vector [gx,gy,gz] in m/s². Default [0,0,-9.81].",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
        },
        "required": ["links", "q"],
    },
)


async def run_motion_gravity_compensation(params: Dict, ctx: ProjectCtx) -> str:
    try:
        from kerf_motion.joints import RevoluteJoint
        from kerf_motion.inverse_dynamics import Robot, gravity_compensation

        links_raw = params["links"]
        n = len(links_raw)
        axes_raw = params.get("joint_axes", [[0.0, 0.0, 1.0]] * n)

        joints = []
        offset = 0.0
        for i, link_def in enumerate(links_raw):
            length = float(link_def["length"])
            ax = tuple(float(v) for v in axes_raw[i]) if i < len(axes_raw) else (0.0, 0.0, 1.0)
            j = RevoluteJoint(
                parent_idx=i,
                child_idx=i + 1,
                axis=ax,  # type: ignore[arg-type]
                parent_offset=(offset, 0.0, 0.0),
                name=f"j{i}",
            )
            joints.append(j)
            offset = length

        masses = []
        inertias = []
        com_offsets = []
        for link_def in links_raw:
            m = float(link_def["mass"])
            L = float(link_def["length"])
            masses.append(m)
            if "inertia" in link_def:
                I_raw = link_def["inertia"]
                I = tuple(tuple(float(v) for v in row) for row in I_raw)
            else:
                Izz = m * L ** 2 / 12.0
                I = ((Izz, 0.0, 0.0), (0.0, Izz, 0.0), (0.0, 0.0, Izz))
            inertias.append(I)  # type: ignore[arg-type]
            if "com_offset" in link_def:
                com_offsets.append(tuple(float(v) for v in link_def["com_offset"]))
            else:
                com_offsets.append((L / 2.0, 0.0, 0.0))

        robot = Robot(
            joints=joints,
            link_masses=masses,
            link_inertias=inertias,  # type: ignore[arg-type]
            com_offsets=com_offsets,  # type: ignore[arg-type]
        )

        q_vals = [float(v) for v in params["q"]]
        grav_raw = params.get("gravity", [0.0, 0.0, -9.81])
        gravity_vec = tuple(float(v) for v in grav_raw)  # type: ignore[arg-type]

        tau = gravity_compensation(robot, q_vals, gravity=gravity_vec)

        return ok_payload({
            "ok": True,
            "n_joints": n,
            "q": q_vals,
            "tau": tau,
            "gravity": list(gravity_vec),
        })

    except Exception as exc:
        return err_payload(str(exc), "GRAVITY_COMP_ERROR")
