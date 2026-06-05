"""
kerf_motion.assembly_motion_study
==================================
Wire the MBD (multibody dynamics) solver to the assembly model so that a
motion study can be defined and solved on a real kerf_cad_core Assembly.

Overview
--------
An ``AssemblyMotionStudy`` takes:
  - A ``kerf_cad_core.assembly.model.Assembly`` (component transforms)
  - A list of ``BodySpec`` dicts — one per moving part — that augment each
    Component with mass / inertia / bounding-box geometry required by the
    MBD and clash engines.
  - Force-field specifications (gravity, applied forces, spring-dampers).
  - Integration parameters (dt, n_steps).

What it does
------------
1. Builds ``RigidBody`` objects from the assembly component transforms +
   BodySpec mass/inertia data.
2. Runs ``kerf_motion.integrator.simulate`` to integrate the rigid-body
   equations of motion.
3. At each recorded step, converts body poses back to 4×4 world transforms
   and feeds them to ``kerf_cad_core.brep.motion_interference.sweep_motion_interference``
   to detect clashes.
4. Returns a structured result: per-body trajectories + interference report.

This module is the missing bridge between:
  - kerf_cad_core.assembly  (component graph, mate constraints)
  - kerf_motion.integrator  (RK4 MBD)
  - kerf_cad_core.brep.motion_interference (clash-over-time)

LLM tool
--------
``assembly_run_motion_study`` — registered via plugin.py.

Units
-----
  - Linear positions / bboxes: mm (assembly model convention)
  - Forces: N  (MBD convention)
  - Angular velocities: rad/s
  - Time: s

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Quat → 4×4 row-major matrix helpers (pure Python)
# ---------------------------------------------------------------------------

def _quat_to_rot16(q: Tuple[float, float, float, float]) -> List[float]:
    """Convert a unit quaternion (w, x, y, z) to a 4×4 row-major rotation matrix."""
    w, x, y, z = q
    xx = x * x; yy = y * y; zz = z * z
    xy = x * y; xz = x * z; yz = y * z
    wx = w * x; wy = w * y; wz = w * z
    return [
        1 - 2*(yy+zz),  2*(xy-wz),      2*(xz+wy),      0.0,
        2*(xy+wz),       1 - 2*(xx+zz),  2*(yz-wx),      0.0,
        2*(xz-wy),       2*(yz+wx),       1 - 2*(xx+yy), 0.0,
        0.0,             0.0,             0.0,            1.0,
    ]


def _body_pose_to_transform(
    position: Tuple[float, float, float],
    orientation: Tuple[float, float, float, float],
    scale_pos: float = 1.0,
) -> List[float]:
    """
    Build a 4×4 row-major world transform from a body position + quaternion.

    Parameters
    ----------
    position    : (x, y, z) in metres (MBD convention).  Scaled by scale_pos.
    orientation : (w, x, y, z) unit quaternion.
    scale_pos   : unit conversion multiplier on position (e.g. 1000.0 to
                  convert m → mm when the assembly model uses mm).

    Returns a 16-element flat list.
    """
    rot = _quat_to_rot16(orientation)
    px = position[0] * scale_pos
    py = position[1] * scale_pos
    pz = position[2] * scale_pos
    # Insert translation into row-major 4×4: [R|t; 0 0 0 1]
    rot[3]  = px
    rot[7]  = py
    rot[11] = pz
    return rot


# ---------------------------------------------------------------------------
# AssemblyMotionStudy
# ---------------------------------------------------------------------------

class AssemblyMotionStudy:
    """
    Connect a ``kerf_cad_core.assembly.model.Assembly`` to the MBD solver
    and interference sweep.

    Parameters
    ----------
    assembly_dict:
        Serialised Assembly dict (from ``Assembly.to_dict()``).
    body_specs:
        List of dicts — one per component to simulate.  Each entry:
          instance_id   : str  — must match a component in the assembly
          mass          : float   — kg
          inertia       : [[3×3]] — inertia tensor (kg·m²), 3 rows of 3 floats
          bbox_min      : [x,y,z] — local-frame AABB min (mm)
          bbox_max      : [x,y,z] — local-frame AABB max (mm)
          initial_pos   : [x,y,z] — initial position override (m). Optional;
                          defaults to component transform translation / 1000.
          initial_vel   : [x,y,z] — initial velocity (m/s). Default [0,0,0].
          triangles     : optional mesh for narrow-phase clash.
    forces:
        List of force-field specs (same format as ``run_simulate_motion``).
    dt:
        Integration time step (s).
    n_steps:
        Number of RK4 steps.
    record_every:
        Record a snapshot every N steps (default 1).
    pos_unit_scale:
        Multiplier to convert MBD position units (m) to assembly units (mm).
        Default 1000.0 (standard: MBD uses m, assembly uses mm).
    coarse_bbox_only:
        Pass to ``sweep_motion_interference`` for faster but approximate
        clash detection.  Default False.
    """

    def __init__(
        self,
        assembly_dict: Dict[str, Any],
        body_specs: List[Dict[str, Any]],
        forces: Optional[List[Dict[str, Any]]] = None,
        dt: float = 0.01,
        n_steps: int = 100,
        record_every: int = 1,
        pos_unit_scale: float = 1000.0,
        coarse_bbox_only: bool = False,
    ) -> None:
        self.assembly_dict = assembly_dict
        self.body_specs = body_specs
        self.forces_specs = forces or []
        self.dt = dt
        self.n_steps = n_steps
        self.record_every = record_every
        self.pos_unit_scale = pos_unit_scale
        self.coarse_bbox_only = coarse_bbox_only

    def run(self) -> Dict[str, Any]:
        """
        Execute the motion study.

        Returns
        -------
        dict with keys:
            ok               : bool
            trajectories     : [{"instance_id", "t", "positions", "velocities"}]
            interference     : MotionInterferenceReport.to_dict()
            n_steps          : int
            dt               : float
            errors           : [str]
        """
        from kerf_cad_core.assembly.model import Assembly
        from kerf_motion.body import RigidBody
        from kerf_motion.forces import gravity as gravity_ff, applied_force, spring_damper
        from kerf_motion.integrator import simulate
        from kerf_cad_core.brep.motion_interference import (
            MotionFrame, sweep_motion_interference,
        )

        errors: List[str] = []

        # ── Parse assembly ────────────────────────────────────────────────
        try:
            assembly = Assembly.from_dict(self.assembly_dict)
        except Exception as exc:
            return {"ok": False, "errors": [f"invalid assembly: {exc}"]}

        # Index components by instance_id
        comp_map = {c.instance_id: c for c in assembly.all_components()}

        # ── Parse body specs ──────────────────────────────────────────────
        bodies: List[RigidBody] = []
        instance_ids: List[str] = []
        body_geom: Dict[str, Dict[str, Any]] = {}  # instance_id → bbox + triangles

        for spec in self.body_specs:
            iid = str(spec.get("instance_id", "")).strip()
            if not iid:
                errors.append("body_spec missing instance_id")
                continue
            if iid not in comp_map:
                errors.append(f"body_spec instance_id '{iid}' not in assembly")
                continue

            comp = comp_map[iid]
            mass = float(spec.get("mass", 1.0))
            inertia_raw = spec.get("inertia", [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
            I = tuple(tuple(float(v) for v in row) for row in inertia_raw)

            # Initial position: explicit override or extract from component transform
            if "initial_pos" in spec:
                pos = tuple(float(v) for v in spec["initial_pos"])
            else:
                # Extract translation from 4×4 row-major transform (indices 3, 7, 11)
                T = comp.transform
                pos = (T[3] / self.pos_unit_scale,
                       T[7] / self.pos_unit_scale,
                       T[11] / self.pos_unit_scale)

            vel = tuple(float(v) for v in spec.get("initial_vel", [0.0, 0.0, 0.0]))

            try:
                rb = RigidBody(
                    mass=mass,
                    inertia_tensor=I,  # type: ignore[arg-type]
                    position=pos,      # type: ignore[arg-type]
                    velocity=vel,      # type: ignore[arg-type]
                    name=comp.name or iid,
                )
            except Exception as exc:
                errors.append(f"body '{iid}': {exc}")
                continue

            bodies.append(rb)
            instance_ids.append(iid)

            bbox_min = list(spec.get("bbox_min", [0.0, 0.0, 0.0]))
            bbox_max = list(spec.get("bbox_max", [1.0, 1.0, 1.0]))
            triangles = spec.get("triangles")
            body_geom[iid] = {
                "bbox_min": bbox_min,
                "bbox_max": bbox_max,
            }
            if triangles is not None:
                body_geom[iid]["triangles"] = triangles

        if not bodies:
            return {
                "ok": False,
                "errors": errors or ["no valid bodies in body_specs"],
            }

        # ── Build force fields ────────────────────────────────────────────
        force_fields = []
        for fspec in self.forces_specs:
            ftype = fspec.get("type", "")
            try:
                if ftype == "gravity":
                    g_val = float(fspec.get("g", 9.80665))
                    force_fields.append(gravity_ff(g=g_val, axis=1, sign=-1))
                elif ftype == "applied":
                    bidx = int(fspec.get("body_idx", 0))
                    fv = tuple(float(v) for v in fspec.get("force", [0, 0, 0]))
                    tv = tuple(float(v) for v in fspec.get("torque", [0, 0, 0]))
                    force_fields.append(applied_force(bidx, fv, tv))  # type: ignore[arg-type]
                elif ftype == "spring_damper":
                    force_fields.append(spring_damper(
                        body_a_idx=int(fspec["body_a"]),
                        body_b_idx=int(fspec.get("body_b", -1)),
                        k=float(fspec["k"]),
                        c=float(fspec.get("c", 0.0)),
                        natural_length=float(fspec.get("natural_length", 1.0)),
                    ))
                else:
                    errors.append(f"unknown force type '{ftype}'; skipping")
            except Exception as exc:
                errors.append(f"force spec '{ftype}': {exc}")

        # ── Integrate ────────────────────────────────────────────────────
        sim_result = simulate(
            bodies, [], force_fields, self.dt, self.n_steps,
            record_every=self.record_every,
        )

        if not sim_result["ok"]:
            return {
                "ok": False,
                "errors": errors + [sim_result.get("reason", "simulation failed")],
            }

        # ── Convert trajectories to MotionFrames ────────────────────────
        times: List[float] = sim_result["t"]
        traj_list: List[List] = sim_result["trajectories"]  # traj_list[body_idx][step_idx]

        # Build MotionFrame objects for the interference sweep
        motion_frames: List[MotionFrame] = []
        n_recorded = len(times)
        for step_idx in range(n_recorded):
            transforms: Dict[str, List[float]] = {}
            for body_idx, iid in enumerate(instance_ids):
                snap = traj_list[body_idx][step_idx]
                T16 = _body_pose_to_transform(
                    snap.position, snap.orientation,
                    scale_pos=self.pos_unit_scale,
                )
                transforms[iid] = T16
            motion_frames.append(
                MotionFrame(t=times[step_idx], component_transforms=transforms)
            )

        # ── Interference sweep ───────────────────────────────────────────
        interference_report = None
        if len(motion_frames) >= 2:
            try:
                report = sweep_motion_interference(
                    bodies=body_geom,
                    frames=motion_frames,
                    coarse_bbox_only=self.coarse_bbox_only,
                )
                interference_report = report.to_dict()
            except Exception as exc:
                errors.append(f"interference sweep: {exc}")
        else:
            # Single-frame or empty — no interference to detect
            interference_report = {
                "events": [],
                "frames_swept": len(motion_frames),
                "total_collision_frames": 0,
                "clearance_min_mm": None,
                "bodies_at_min_clearance": None,
            }

        # ── Serialise trajectories ───────────────────────────────────────
        traj_out = []
        for body_idx, iid in enumerate(instance_ids):
            body_traj = traj_list[body_idx]
            traj_out.append({
                "instance_id": iid,
                "t": [snap.t for snap in body_traj],
                "positions": [list(snap.position) for snap in body_traj],
                "velocities": [list(snap.velocity) for snap in body_traj],
            })

        return {
            "ok": True,
            "trajectories": traj_out,
            "interference": interference_report,
            "n_steps": self.n_steps,
            "dt": self.dt,
            "n_bodies": len(bodies),
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# LLM tool spec + handler
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_motion._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


assembly_motion_study_spec = ToolSpec(
    name="assembly_run_motion_study",
    description=(
        "Run a rigid-body multibody dynamics (MBD) motion study on a kerf "
        "Assembly and detect interference between moving components over time.\n"
        "\n"
        "Connects the assembly component graph to the RK4 MBD integrator "
        "(kerf_motion) and sweeps the assembly clash detector over each "
        "recorded time step to report collision events.\n"
        "\n"
        "Inputs:\n"
        "  assembly     — Assembly dict from assembly_create/assembly_add_component.\n"
        "  body_specs   — List of body descriptors (one per moving component):\n"
        "                   instance_id: str  — must match an assembly component.\n"
        "                   mass:        float (kg).\n"
        "                   inertia:     3×3 inertia tensor [[…],…] (kg·m²).\n"
        "                   bbox_min:    [x,y,z] local-frame AABB min (mm).\n"
        "                   bbox_max:    [x,y,z] local-frame AABB max (mm).\n"
        "                   initial_pos: [x,y,z] optional override (m). "
        "Defaults to component transform translation ÷ 1000.\n"
        "                   initial_vel: [x,y,z] initial velocity (m/s). Default [0,0,0].\n"
        "  forces       — List of force-field specs (gravity/applied/spring_damper).\n"
        "  dt           — Integration time step (s). Default 0.01.\n"
        "  n_steps      — Number of RK4 steps. Default 100.\n"
        "  record_every — Record a snapshot every N steps. Default 1.\n"
        "  coarse_bbox_only — Fast AABB-only clash detection. Default false.\n"
        "\n"
        "Returns:\n"
        "  trajectories — per-body time-series: instance_id, t[], positions[], velocities[]\n"
        "  interference — MotionInterferenceReport with events (t_start, t_end,\n"
        "                 max_penetration_mm), frames_swept, clearance_min_mm.\n"
        "  errors       — non-fatal input issues.\n"
        "\n"
        "Units: positions in m (MBD), converted to mm for interference detection. "
        "Forces in N. Inertia in kg·m²."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly": {
                "type": "object",
                "description": "Assembly dict (from assembly_create / assembly_add_component).",
            },
            "body_specs": {
                "type": "array",
                "description": "One body descriptor per component to simulate.",
                "items": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string"},
                        "mass": {"type": "number", "description": "Mass in kg."},
                        "inertia": {
                            "type": "array",
                            "description": "3×3 inertia tensor as list of 3 rows (kg·m²).",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "bbox_min": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Local-frame AABB min [x,y,z] in mm.",
                        },
                        "bbox_max": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Local-frame AABB max [x,y,z] in mm.",
                        },
                        "initial_pos": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Initial position [x,y,z] in m. Optional.",
                        },
                        "initial_vel": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Initial velocity [x,y,z] in m/s. Default [0,0,0].",
                        },
                        "triangles": {
                            "type": "array",
                            "description": "Optional triangle mesh [[v0,v1,v2],…] in local frame for narrow-phase clash.",
                        },
                    },
                    "required": ["instance_id", "mass", "bbox_min", "bbox_max"],
                },
            },
            "forces": {
                "type": "array",
                "description": "Force-field specs (same format as simulate_motion forces).",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["gravity", "applied", "spring_damper"]},
                        "g": {"type": "number"},
                        "body_idx": {"type": "integer"},
                        "force": {"type": "array", "items": {"type": "number"}},
                        "torque": {"type": "array", "items": {"type": "number"}},
                        "body_a": {"type": "integer"},
                        "body_b": {"type": "integer"},
                        "k": {"type": "number"},
                        "c": {"type": "number"},
                        "natural_length": {"type": "number"},
                    },
                    "required": ["type"],
                },
            },
            "dt": {"type": "number", "description": "Integration time step (s). Default 0.01."},
            "n_steps": {"type": "integer", "description": "Number of integration steps. Default 100."},
            "record_every": {"type": "integer", "description": "Record every N steps. Default 1."},
            "coarse_bbox_only": {
                "type": "boolean",
                "description": "AABB-only interference check (fast). Default false.",
            },
        },
        "required": ["assembly", "body_specs"],
    },
)


async def run_assembly_motion_study(params: Dict, ctx: "ProjectCtx") -> str:
    """LLM-callable handler for assembly_run_motion_study."""
    try:
        asm_raw = params.get("assembly")
        body_specs = params.get("body_specs", [])
        if not asm_raw:
            return err_payload("assembly is required", "BAD_ARGS")
        if not isinstance(body_specs, list):
            return err_payload("body_specs must be an array", "BAD_ARGS")

        study = AssemblyMotionStudy(
            assembly_dict=asm_raw,
            body_specs=body_specs,
            forces=params.get("forces"),
            dt=float(params.get("dt", 0.01)),
            n_steps=int(params.get("n_steps", 100)),
            record_every=int(params.get("record_every", 1)),
            coarse_bbox_only=bool(params.get("coarse_bbox_only", False)),
        )
        result = study.run()
        if not result["ok"]:
            return err_payload(
                "; ".join(result.get("errors", ["unknown error"])),
                "MOTION_STUDY_ERROR",
            )
        return ok_payload(result)

    except Exception as exc:
        return err_payload(str(exc), "MOTION_STUDY_ERROR")


# ---------------------------------------------------------------------------
# 3D MBD constraint enforcement tool
# ---------------------------------------------------------------------------

assembly_mbd_constraint_spec = ToolSpec(
    name="assembly_mbd_constraint_enforce",
    description=(
        "Evaluate joint constraint enforcement for a 3-D multibody assembly.\n"
        "\n"
        "For each joint in the kinematic chain, computes:\n"
        "  - Current generalised coordinates (DOF values)\n"
        "  - Constraint violation: how far the current state deviates from\n"
        "    the joint constraint (e.g. revolute axis drift, prismatic limit violation)\n"
        "  - Whether limit constraints (joint.limits) are active\n"
        "\n"
        "Joints supported: FixedJoint, RevoluteJoint, PrismaticJoint,\n"
        "CylindricalJoint, UniversalJoint, SphericalJoint.\n"
        "\n"
        "Input:\n"
        "  joints — list of joint descriptors:\n"
        "    type         : 'fixed'|'revolute'|'prismatic'|'cylindrical'|"
        "'universal'|'spherical'\n"
        "    parent_idx   : int\n"
        "    child_idx    : int\n"
        "    dof_values   : list of floats (current DOF state)\n"
        "    axis         : [x,y,z] for revolute/prismatic/cylindrical\n"
        "    limits       : [lo, hi] for revolute/prismatic (optional)\n"
        "    name         : str (optional)\n"
        "\n"
        "Returns per-joint enforcement status and any limit violations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "joints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["fixed", "revolute", "prismatic",
                                     "cylindrical", "universal", "spherical"],
                        },
                        "parent_idx": {"type": "integer"},
                        "child_idx": {"type": "integer"},
                        "dof_values": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Current DOF values (angles in rad, translations in m).",
                        },
                        "axis": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Joint axis [x,y,z]. Default [0,0,1].",
                        },
                        "limits": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "[lo, hi] limits for revolute (rad) or prismatic (m).",
                        },
                        "name": {"type": "string"},
                    },
                    "required": ["type", "parent_idx", "child_idx"],
                },
            },
        },
        "required": ["joints"],
    },
)


async def run_assembly_mbd_constraint_enforce(params: Dict, ctx: "ProjectCtx") -> str:
    """Evaluate 3D MBD joint constraint enforcement."""
    try:
        from kerf_motion.joints import (
            FixedJoint, RevoluteJoint, PrismaticJoint,
            CylindricalJoint, UniversalJoint, SphericalJoint,
        )

        joints_raw = params.get("joints", [])
        if not isinstance(joints_raw, list):
            return err_payload("joints must be an array", "BAD_ARGS")

        results = []
        errors_list: List[str] = []

        for i, jspec in enumerate(joints_raw):
            jtype = str(jspec.get("type", "")).strip().lower()
            parent_idx = int(jspec.get("parent_idx", 0))
            child_idx = int(jspec.get("child_idx", 1))
            name = str(jspec.get("name", f"joint_{i}"))
            dof_values = [float(v) for v in jspec.get("dof_values", [])]
            axis_raw = jspec.get("axis", [0.0, 0.0, 1.0])
            axis = tuple(float(v) for v in axis_raw)
            limits_raw = jspec.get("limits")
            limits = (float(limits_raw[0]), float(limits_raw[1])) if limits_raw else None

            try:
                if jtype == "fixed":
                    j = FixedJoint(parent_idx, child_idx, name=name)
                elif jtype == "revolute":
                    j = RevoluteJoint(
                        parent_idx, child_idx,
                        axis=axis,  # type: ignore[arg-type]
                        limits=limits,
                        name=name,
                    )
                elif jtype == "prismatic":
                    j = PrismaticJoint(
                        parent_idx, child_idx,
                        axis=axis,  # type: ignore[arg-type]
                        limits=limits,
                        name=name,
                    )
                elif jtype == "cylindrical":
                    j = CylindricalJoint(
                        parent_idx, child_idx,
                        axis=axis,  # type: ignore[arg-type]
                        name=name,
                    )
                elif jtype == "universal":
                    j = UniversalJoint(
                        parent_idx, child_idx,
                        name=name,
                    )
                elif jtype == "spherical":
                    j = SphericalJoint(parent_idx, child_idx, name=name)
                else:
                    errors_list.append(f"joints[{i}]: unknown type '{jtype}'")
                    continue
            except Exception as exc:
                errors_list.append(f"joints[{i}] init error: {exc}")
                continue

            # Apply DOF values if provided
            limit_active = False
            constraint_violation = 0.0
            applied_dof: List[float] = []

            if dof_values and j.n_dof > 0:
                if len(dof_values) < j.n_dof:
                    errors_list.append(
                        f"joints[{i}]: expected {j.n_dof} dof_values, got {len(dof_values)}"
                    )
                    dof_values = dof_values + [0.0] * (j.n_dof - len(dof_values))
                try:
                    j.set_dof(dof_values[:j.n_dof])
                    applied_dof = j.get_dof()

                    # Check limit enforcement for revolute and prismatic joints
                    if hasattr(j, "limits") and j.limits is not None:
                        lo, hi = j.limits
                        if hasattr(j, "angle"):
                            raw_val = dof_values[0]
                            clamped_val = applied_dof[0]
                            if raw_val < lo or raw_val > hi:
                                limit_active = True
                                constraint_violation = max(lo - raw_val, raw_val - hi)
                        elif hasattr(j, "position"):
                            raw_val = dof_values[0]
                            clamped_val = applied_dof[0]
                            if raw_val < lo or raw_val > hi:
                                limit_active = True
                                constraint_violation = max(lo - raw_val, raw_val - hi)
                except Exception as exc:
                    errors_list.append(f"joints[{i}] set_dof error: {exc}")

            # Compute joint transform
            try:
                jt = j.transform()
                trans_list = list(jt.translation)
                rot_list = list(jt.rotation)
            except Exception as exc:
                errors_list.append(f"joints[{i}] transform error: {exc}")
                trans_list = [0.0, 0.0, 0.0]
                rot_list = [1.0, 0.0, 0.0, 0.0]

            results.append({
                "index": i,
                "name": name,
                "type": jtype,
                "n_dof": j.n_dof,
                "dof_values": applied_dof if applied_dof else j.get_dof(),
                "limit_active": limit_active,
                "constraint_violation": constraint_violation,
                "translation": trans_list,
                "rotation_quat": rot_list,  # (w, x, y, z)
            })

        return ok_payload({
            "ok": True,
            "n_joints": len(results),
            "joints": results,
            "errors": errors_list,
        })

    except Exception as exc:
        return err_payload(str(exc), "MBD_CONSTRAINT_ERROR")


__all__ = [
    "AssemblyMotionStudy",
    "assembly_motion_study_spec",
    "run_assembly_motion_study",
    "assembly_mbd_constraint_spec",
    "run_assembly_mbd_constraint_enforce",
]
