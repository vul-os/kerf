"""
kerf_motion.trajectory_timeline
================================
Clean per-frame body-pose timeline for the AssemblyMotionStudio viewer.

The raw ``simulate`` / ``assembly_run_motion_study`` output carries
``BodySnapshot`` lists which contain quaternion orientation state.  The
viewer needs:

  1. A *flat*, JSON-serialisable structure — one object per (body, frame).
  2. Quaternion orientation expressed as *both* a raw ``[w, x, y, z]`` tuple
     **and** a pre-computed Euler ZYX ``[rx, ry, rz]`` (radians) for the
     THREE.js ``Euler.setFromQuaternion`` path.
  3. A convenience ``FrameTimeline`` that lets callers query by frame index or
     time.

This module has **zero** dependencies beyond the Python stdlib and other
``kerf_motion`` submodules — no NumPy, no SciPy.

Public API
----------
build_frame_timeline(sim_result, body_names)
    Convert the dict returned by ``kerf_motion.integrator.simulate`` (or the
    ``trajectories`` list inside it) into a ``FrameTimeline``.

FrameTimeline
    Lightweight value object::

        timeline.frames          # list[BodyFrame]
        timeline.body_names      # list[str]
        timeline.t               # list[float]  — recorded times
        timeline.frame_count     # int
        timeline.at(frame_idx)   # list[BodyPose]
        timeline.to_dict()       # JSON-serialisable dict

BodyPose
    Named tuple: (body_name, t, position, orientation_quat, orientation_euler)

assembly_run_motion_timeline (LLM tool handler)
    Wraps ``assembly_run_motion_study`` + ``build_frame_timeline`` in one
    round-trip call and returns a viewer-ready JSON payload.

Units
-----
Positions are in the same units as the MBD solver (typically metres).  The
caller is responsible for any mm ↔ m conversion needed at the rendering layer.

Euler convention
----------------
ZYX intrinsic (same as THREE.js ``Euler`` default order ``'XYZ'`` applied as
``setFromQuaternion(q, 'ZYX')``).  This maps to roll/pitch/yaw intuitively
for most mechanical assemblies.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Quat helpers (pure Python; no numpy)
# ---------------------------------------------------------------------------

def _quat_normalize(q: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    return (w / n, x / n, y / n, z / n)


def _quat_to_euler_zyx(q: Tuple[float, float, float, float]) -> Tuple[float, float, float]:
    """
    Convert a unit quaternion (w, x, y, z) to ZYX Euler angles (rx, ry, rz)
    in radians.

    ZYX intrinsic convention — also called 'yaw-pitch-roll':
        rz = yaw   (rotation about Z)
        ry = pitch (rotation about new Y)
        rx = roll  (rotation about new X)

    Returns (rx, ry, rz).  Gimbal-lock singularity at ry = ±π/2 is handled
    by clamping sinp to [-1, 1].
    """
    w, x, y, z = _quat_normalize(q)

    # Roll (rx) — X-axis rotation
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    rx = math.atan2(sinr_cosp, cosr_cosp)

    # Pitch (ry) — Y-axis rotation
    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))  # clamp for numerical safety
    ry = math.asin(sinp)

    # Yaw (rz) — Z-axis rotation
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    rz = math.atan2(siny_cosp, cosy_cosp)

    return (rx, ry, rz)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class BodyPose(NamedTuple):
    """Pose of a single body at a single time step."""
    body_name: str
    t: float
    position: Tuple[float, float, float]
    orientation_quat: Tuple[float, float, float, float]   # (w, x, y, z)
    orientation_euler: Tuple[float, float, float]          # (rx, ry, rz) ZYX rad


class BodyFrame(NamedTuple):
    """All body poses at a single frame."""
    frame_idx: int
    t: float
    poses: List[BodyPose]


class FrameTimeline:
    """
    Viewer-ready timeline built from a simulate() result.

    Attributes
    ----------
    body_names  : ordered list of body name strings
    t           : list of recorded time stamps (one per frame)
    frames      : list of BodyFrame objects
    frame_count : total number of frames
    """

    def __init__(
        self,
        body_names: List[str],
        t: List[float],
        frames: List[BodyFrame],
    ) -> None:
        self.body_names = body_names
        self.t = t
        self.frames = frames
        self.frame_count = len(frames)

    # ── Query ──────────────────────────────────────────────────────────────

    def at(self, frame_idx: int) -> List[BodyPose]:
        """Return all body poses at ``frame_idx`` (clamped to valid range).

        Negative indices are supported Python-style: -1 → last frame,
        -2 → second-to-last, etc.  Values beyond bounds are clamped.
        """
        if not self.frames:
            return []
        # Python-style negative index support
        if frame_idx < 0:
            frame_idx = self.frame_count + frame_idx
        idx = max(0, min(frame_idx, self.frame_count - 1))
        return list(self.frames[idx].poses)

    def at_time(self, t: float) -> List[BodyPose]:
        """Return poses at the frame whose time is closest to ``t``."""
        if not self.frames:
            return []
        best_idx = 0
        best_dt = abs(self.t[0] - t) if self.t else float("inf")
        for i, ti in enumerate(self.t):
            dt = abs(ti - t)
            if dt < best_dt:
                best_dt = dt
                best_idx = i
        return self.at(best_idx)

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """
        Return a JSON-serialisable dict suitable for the motion viewer.

        Schema::

            {
              "body_names": ["body_0", ...],
              "t":          [0.0, 0.01, ...],
              "frame_count": 101,
              "frames": [
                {
                  "frame_idx": 0,
                  "t": 0.0,
                  "poses": [
                    {
                      "body_name": "body_0",
                      "t": 0.0,
                      "position": [0.0, 0.0, 0.0],
                      "orientation_quat": [1.0, 0.0, 0.0, 0.0],
                      "orientation_euler": [0.0, 0.0, 0.0]
                    },
                    ...
                  ]
                },
                ...
              ]
            }
        """
        frames_out = []
        for bf in self.frames:
            poses_out = []
            for bp in bf.poses:
                poses_out.append({
                    "body_name": bp.body_name,
                    "t": bp.t,
                    "position": list(bp.position),
                    "orientation_quat": list(bp.orientation_quat),
                    "orientation_euler": list(bp.orientation_euler),
                })
            frames_out.append({
                "frame_idx": bf.frame_idx,
                "t": bf.t,
                "poses": poses_out,
            })
        return {
            "body_names": list(self.body_names),
            "t": list(self.t),
            "frame_count": self.frame_count,
            "frames": frames_out,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_frame_timeline(
    sim_result: Dict[str, Any],
    body_names: Optional[Sequence[str]] = None,
) -> FrameTimeline:
    """
    Convert a ``kerf_motion.integrator.simulate`` result dict into a
    ``FrameTimeline``.

    Parameters
    ----------
    sim_result:
        Dict returned by ``simulate()`` — must have keys ``"trajectories"``
        (list of list of BodySnapshot) and ``"t"`` (list of floats).

        Alternatively, if the dict has a ``"result"`` wrapper (as produced by
        ``ok_payload``), the inner dict is unwrapped automatically.

    body_names:
        Optional ordered list of body names.  If omitted, names are inferred
        from the snapshots (``snap.body_name`` if present) or fall back to
        ``"body_0"``, ``"body_1"``, …

    Returns
    -------
    FrameTimeline
    """
    # Unwrap ok_payload wrapper if present
    if "result" in sim_result and "trajectories" not in sim_result:
        sim_result = sim_result["result"]

    raw_trajs = sim_result.get("trajectories", [])
    raw_t = sim_result.get("t", [])

    if not raw_trajs:
        return FrameTimeline(body_names=[], t=[], frames=[])

    n_bodies = len(raw_trajs)

    # ── Resolve body names ────────────────────────────────────────────────
    if body_names is not None:
        names = list(body_names)
        # Pad with auto-names if fewer names than bodies
        while len(names) < n_bodies:
            names.append(f"body_{len(names)}")
    else:
        names = []
        for i, traj in enumerate(raw_trajs):
            if traj:
                snap = traj[0]
                # BodySnapshot objects have no .body_name; fall back to index
                names.append(getattr(snap, "body_name", f"body_{i}"))
            else:
                names.append(f"body_{i}")

    # ── Resolve time axis ─────────────────────────────────────────────────
    # raw_t comes from the outer simulate() call; len(raw_t) == n_frames.
    # If it's empty, reconstruct from the first trajectory's .t fields.
    if raw_t:
        times: List[float] = [float(v) for v in raw_t]
    elif raw_trajs[0]:
        times = [float(getattr(s, "t", 0.0)) for s in raw_trajs[0]]
    else:
        times = []

    n_frames = len(times)

    # ── Build frames ──────────────────────────────────────────────────────
    frames: List[BodyFrame] = []
    for fi in range(n_frames):
        t_fi = times[fi]
        poses: List[BodyPose] = []
        for bi, traj in enumerate(raw_trajs):
            snap = traj[min(fi, len(traj) - 1)] if traj else None
            if snap is None:
                poses.append(BodyPose(
                    body_name=names[bi],
                    t=t_fi,
                    position=(0.0, 0.0, 0.0),
                    orientation_quat=(1.0, 0.0, 0.0, 0.0),
                    orientation_euler=(0.0, 0.0, 0.0),
                ))
            else:
                pos = tuple(getattr(snap, "position", (0.0, 0.0, 0.0)))[:3]
                ori_raw = getattr(snap, "orientation", (1.0, 0.0, 0.0, 0.0))
                # Support both (w,x,y,z) tuples and lists
                ori: Tuple[float, float, float, float] = tuple(float(v) for v in ori_raw[:4])  # type: ignore[assignment]
                if len(ori) < 4:
                    ori = (1.0, 0.0, 0.0, 0.0)
                euler = _quat_to_euler_zyx(ori)
                poses.append(BodyPose(
                    body_name=names[bi],
                    t=t_fi,
                    position=(float(pos[0]), float(pos[1]), float(pos[2])),
                    orientation_quat=ori,
                    orientation_euler=euler,
                ))
        frames.append(BodyFrame(frame_idx=fi, t=t_fi, poses=poses))

    return FrameTimeline(body_names=names, t=times, frames=frames)


# ---------------------------------------------------------------------------
# LLM tool: motion_frame_timeline
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_motion._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


motion_frame_timeline_spec = ToolSpec(
    name="motion_frame_timeline",
    description=(
        "Run a rigid-body dynamics simulation and return a clean per-frame body-pose "
        "timeline for the AssemblyMotionStudio viewer.  "
        "Each frame contains position, quaternion orientation, and ZYX Euler angles "
        "for every simulated body.  "
        "Use this instead of simulate_motion when you need viewer-ready frame data."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bodies": {
                "type": "array",
                "description": "Rigid body definitions (same format as simulate_motion).",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "mass": {"type": "number"},
                        "inertia": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "position": {"type": "array", "items": {"type": "number"}},
                        "velocity": {"type": "array", "items": {"type": "number"}},
                    },
                    "required": ["mass"],
                },
            },
            "forces": {
                "type": "array",
                "description": "Force field specs (same format as simulate_motion).",
                "items": {"type": "object"},
            },
            "dt": {"type": "number", "description": "Time step (s)."},
            "n_steps": {"type": "integer", "description": "Number of integration steps."},
            "record_every": {"type": "integer", "default": 1},
        },
        "required": ["bodies", "dt", "n_steps"],
    },
)


async def run_motion_frame_timeline(params: Dict, ctx: "ProjectCtx") -> str:
    """
    LLM-callable handler: simulate + build viewer timeline in one call.
    """
    try:
        from kerf_motion.body import RigidBody
        from kerf_motion.forces import gravity as gravity_ff, applied_force, spring_damper, table_driver_torque
        from kerf_motion.integrator import simulate

        bodies_raw = params.get("bodies", [])
        if not bodies_raw:
            return err_payload("bodies is required and must be non-empty", "BAD_ARGS")

        bodies = []
        body_names = []
        for bd in bodies_raw:
            mass = float(bd["mass"])
            inertia_raw = bd.get("inertia", [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
            I = tuple(tuple(float(v) for v in row) for row in inertia_raw)
            pos = tuple(float(v) for v in bd.get("position", [0, 0, 0]))
            vel = tuple(float(v) for v in bd.get("velocity", [0, 0, 0]))
            name = bd.get("name", f"body_{len(bodies)}")
            body_names.append(name)
            bodies.append(RigidBody(
                mass=mass,
                inertia_tensor=I,  # type: ignore[arg-type]
                position=pos,      # type: ignore[arg-type]
                velocity=vel,      # type: ignore[arg-type]
                name=name,
            ))

        force_fields = []
        for fspec in params.get("forces", []):
            ftype = fspec["type"]
            if ftype == "gravity":
                force_fields.append(gravity_ff(g=fspec.get("g", 9.80665), axis=1, sign=-1))
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
            elif ftype == "table_driver":
                bidx = int(fspec.get("body_idx", 0))
                t_times = [float(v) for v in fspec.get("table_times", [])]
                t_thetas = [float(v) for v in fspec.get("table_thetas", [])]
                inertia_val = float(fspec.get("inertia", 1.0))
                damping_val = float(fspec.get("damping", 0.0))
                axis_val = tuple(float(v) for v in fspec.get("axis", [0.0, 0.0, 1.0]))
                force_fields.append(table_driver_torque(
                    bidx, t_times, t_thetas,
                    inertia=inertia_val, damping=damping_val, axis=axis_val,  # type: ignore[arg-type]
                ))

        dt = float(params["dt"])
        n_steps = int(params["n_steps"])
        record_every = int(params.get("record_every", 1))

        sim_result = simulate(bodies, [], force_fields, dt, n_steps, record_every=record_every)

        if not sim_result["ok"]:
            return err_payload(sim_result.get("reason", "simulation failed"), "MOTION_SIM_ERROR")

        timeline = build_frame_timeline(sim_result, body_names=body_names)
        return ok_payload(timeline.to_dict())

    except Exception as exc:
        return err_payload(str(exc), "MOTION_TIMELINE_ERROR")
