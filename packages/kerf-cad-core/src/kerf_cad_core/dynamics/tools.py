"""
kerf_cad_core.dynamics.tools — LLM tool wrappers for rigid-body dynamics.

Registers tools with the Kerf tool registry:

  dynamics_rectilinear_kinematics     — s, v for constant-acceleration motion
  dynamics_projectile_motion          — x, y, vx, vy, range for projectile
  dynamics_rotational_kinematics      — θ, ω for constant angular acceleration
  dynamics_relative_motion_velocity   — v_B = v_A + v_B/A
  dynamics_newton_translation         — a from ΣF = ma
  dynamics_euler_rotation             — α from ΣM = Iα
  dynamics_general_plane_motion       — ax, ay, α from combined translation+rotation
  dynamics_kinetic_energy             — T = ½mv² + ½Iω²
  dynamics_work_energy_theorem        — energy balance T1 + W_nc = T2
  dynamics_spring_pe                  — V_s = ½kx²
  dynamics_power_torque               — P = M·ω
  dynamics_power_force                — P = F·v
  dynamics_linear_impulse             — mv2 = mv1 + F·Δt
  dynamics_angular_impulse            — L2 = L1 + M·Δt
  dynamics_direct_impact              — post-impact velocities (central impact)
  dynamics_oblique_impact             — 2-D oblique impact
  dynamics_moi_solid_cylinder         — I = ½mr²
  dynamics_moi_hollow_cylinder        — I = ½m(r_o²+r_i²)
  dynamics_moi_solid_sphere           — I = 2/5 mr²
  dynamics_moi_thin_rod               — I about centroid or end
  dynamics_moi_rectangular_plate      — polar and planar MOI
  dynamics_parallel_axis              — I = I_cm + md²
  dynamics_flywheel_sizing            — I from energy fluctuation
  dynamics_flywheel_rim               — rim cross-section from I
  dynamics_static_balance             — single-plane resultant + correction
  dynamics_dynamic_balance_two_plane  — two-plane correction masses
  dynamics_residual_unbalance         — U = m·e (g·mm)
  dynamics_iso1940_grade              — ISO 1940 balance grade check
  dynamics_shaking_force_primary      — primary reciprocating shaking force
  dynamics_shaking_force_secondary    — secondary reciprocating shaking force
  dynamics_gyroscopic_moment          — M = I·ωs·ωp

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Hibbeler, R.C. "Engineering Mechanics: Dynamics", 14th ed.
Beer, F.P. & Johnston, E.R. "Vector Mechanics for Engineers: Dynamics", 12th ed.
ISO 1940-1:2003

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

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


# ---------------------------------------------------------------------------
# Tool: dynamics_rectilinear_kinematics
# ---------------------------------------------------------------------------

_rectilinear_spec = ToolSpec(
    name="dynamics_rectilinear_kinematics",
    description=(
        "Constant-acceleration rectilinear kinematics.\n\n"
        "s = s0 + v0·t + ½·a·t²,   v = v0 + a·t\n\n"
        "Returns position s (m), velocity v (m/s), and v² (m²/s²).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v0": {"type": "number", "description": "Initial velocity (m/s)."},
            "a": {"type": "number", "description": "Constant acceleration (m/s²)."},
            "t": {"type": "number", "description": "Time elapsed (s). Must be >= 0."},
            "s0": {"type": "number", "description": "Initial position (m). Default 0."},
        },
        "required": ["v0", "a", "t"],
    },
)


@register(_rectilinear_spec, write=False)
async def run_rectilinear_kinematics(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("v0", "a", "t"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "s0" in a:
        kwargs["s0"] = a["s0"]

    return ok_payload(rectilinear_kinematics(a["v0"], a["a"], a["t"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_projectile_motion
# ---------------------------------------------------------------------------

_projectile_spec = ToolSpec(
    name="dynamics_projectile_motion",
    description=(
        "Projectile motion (no air resistance).\n\n"
        "Returns x, y (m), vx, vy (m/s), speed, time-to-peak, and range.\n\n"
        "theta_deg: launch angle above horizontal [-90, 90].\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v0": {"type": "number", "description": "Initial speed (m/s). Must be > 0."},
            "theta_deg": {
                "type": "number",
                "description": "Launch angle above horizontal (degrees). [-90, 90].",
            },
            "t": {"type": "number", "description": "Time elapsed (s). Must be >= 0."},
            "g": {
                "type": "number",
                "description": "Gravitational acceleration (m/s²). Default 9.80665.",
            },
        },
        "required": ["v0", "theta_deg", "t"],
    },
)


@register(_projectile_spec, write=False)
async def run_projectile_motion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("v0", "theta_deg", "t"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "g" in a:
        kwargs["g"] = a["g"]

    return ok_payload(projectile_motion(a["v0"], a["theta_deg"], a["t"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_rotational_kinematics
# ---------------------------------------------------------------------------

_rotational_spec = ToolSpec(
    name="dynamics_rotational_kinematics",
    description=(
        "Constant angular-acceleration rotational kinematics.\n\n"
        "θ = θ0 + ω0·t + ½·α·t²,   ω = ω0 + α·t\n\n"
        "Returns angular position θ (rad), angular velocity ω (rad/s), ω².\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "omega0": {"type": "number", "description": "Initial angular velocity (rad/s)."},
            "alpha": {"type": "number", "description": "Angular acceleration (rad/s²)."},
            "t": {"type": "number", "description": "Time elapsed (s). Must be >= 0."},
            "theta0": {"type": "number", "description": "Initial angle (rad). Default 0."},
        },
        "required": ["omega0", "alpha", "t"],
    },
)


@register(_rotational_spec, write=False)
async def run_rotational_kinematics(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("omega0", "alpha", "t"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "theta0" in a:
        kwargs["theta0"] = a["theta0"]

    return ok_payload(rotational_kinematics(a["omega0"], a["alpha"], a["t"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_relative_motion_velocity
# ---------------------------------------------------------------------------

_rel_vel_spec = ToolSpec(
    name="dynamics_relative_motion_velocity",
    description=(
        "Compute absolute velocity of B from relative motion: v_B = v_A + v_B/A.\n\n"
        "Accepts 2-D [vx, vy] or 3-D [vx, vy, vz] vectors.\n\n"
        "Returns v_B vector and magnitude.\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v_A": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Absolute velocity of reference point A (m/s), 2 or 3 components.",
            },
            "v_B_A": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Velocity of B relative to A (m/s), same dimension as v_A.",
            },
        },
        "required": ["v_A", "v_B_A"],
    },
)


@register(_rel_vel_spec, write=False)
async def run_relative_motion_velocity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("v_A", "v_B_A"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(relative_motion_velocity(a["v_A"], a["v_B_A"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_newton_translation
# ---------------------------------------------------------------------------

_newton_spec = ToolSpec(
    name="dynamics_newton_translation",
    description=(
        "Newton's second law: a = ΣF / m.\n\n"
        "Returns linear acceleration (m/s²).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "F_net": {"type": "number", "description": "Net force ΣF (N). Any finite value."},
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
        },
        "required": ["F_net", "m"],
    },
)


@register(_newton_spec, write=False)
async def run_newton_translation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("F_net", "m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(newton_translation(a["F_net"], a["m"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_euler_rotation
# ---------------------------------------------------------------------------

_euler_spec = ToolSpec(
    name="dynamics_euler_rotation",
    description=(
        "Euler's rotation equation: α = ΣM / I.\n\n"
        "Returns angular acceleration α (rad/s²).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "M_net": {"type": "number", "description": "Net moment ΣM (N·m). Any finite value."},
            "I": {"type": "number", "description": "Mass moment of inertia (kg·m²). Must be > 0."},
        },
        "required": ["M_net", "I"],
    },
)


@register(_euler_spec, write=False)
async def run_euler_rotation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("M_net", "I"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(euler_rotation(a["M_net"], a["I"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_general_plane_motion
# ---------------------------------------------------------------------------

_gpm_spec = ToolSpec(
    name="dynamics_general_plane_motion",
    description=(
        "General plane motion of a rigid body: ΣFx=m·ax, ΣFy=m·ay, ΣM_G=I_G·α.\n\n"
        "Returns ax (m/s²), ay (m/s²), α (rad/s²).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "F_x": {"type": "number", "description": "Net force in x-direction (N)."},
            "F_y": {"type": "number", "description": "Net force in y-direction (N)."},
            "M_G": {"type": "number", "description": "Net moment about mass centre G (N·m)."},
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "I_G": {"type": "number", "description": "MOI about centroid G (kg·m²). Must be > 0."},
        },
        "required": ["F_x", "F_y", "M_G", "m", "I_G"],
    },
)


@register(_gpm_spec, write=False)
async def run_general_plane_motion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("F_x", "F_y", "M_G", "m", "I_G"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(
        general_plane_motion(a["F_x"], a["F_y"], a["M_G"], a["m"], a["I_G"])
    )


# ---------------------------------------------------------------------------
# Tool: dynamics_kinetic_energy
# ---------------------------------------------------------------------------

_ke_spec = ToolSpec(
    name="dynamics_kinetic_energy",
    description=(
        "Total kinetic energy: T = ½·m·v² + ½·I·ω².\n\n"
        "Returns T_trans, T_rot, T_total (J).\n\n"
        "I and omega default to 0 (pure translation).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "v": {"type": "number", "description": "Speed (m/s). Must be >= 0."},
            "I": {"type": "number", "description": "MOI (kg·m²). Default 0. Must be >= 0."},
            "omega": {"type": "number", "description": "Angular velocity (rad/s). Default 0. Must be >= 0."},
        },
        "required": ["m", "v"],
    },
)


@register(_ke_spec, write=False)
async def run_kinetic_energy(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m", "v"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "I" in a:
        kwargs["I"] = a["I"]
    if "omega" in a:
        kwargs["omega"] = a["omega"]

    return ok_payload(kinetic_energy(a["m"], a["v"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_work_energy_theorem
# ---------------------------------------------------------------------------

_wet_spec = ToolSpec(
    name="dynamics_work_energy_theorem",
    description=(
        "Work-energy principle check: T2 - (T1 + W_nc) should equal zero.\n\n"
        "Returns balance residual and satisfied flag.\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "KE1": {"type": "number", "description": "Initial kinetic energy (J). Must be >= 0."},
            "KE2": {"type": "number", "description": "Final kinetic energy (J). Must be >= 0."},
            "W_nc": {"type": "number", "description": "Net work by non-conservative forces (J)."},
        },
        "required": ["KE1", "KE2", "W_nc"],
    },
)


@register(_wet_spec, write=False)
async def run_work_energy_theorem(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("KE1", "KE2", "W_nc"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(work_energy_theorem(a["KE1"], a["KE2"], a["W_nc"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_spring_pe
# ---------------------------------------------------------------------------

_spring_pe_spec = ToolSpec(
    name="dynamics_spring_pe",
    description=(
        "Spring potential energy: V_s = ½·k·x².\n\n"
        "Returns V_s (J).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "k": {"type": "number", "description": "Spring stiffness (N/m). Must be > 0."},
            "x": {"type": "number", "description": "Deformation from natural length (m)."},
        },
        "required": ["k", "x"],
    },
)


@register(_spring_pe_spec, write=False)
async def run_spring_pe(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("k", "x"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(spring_potential_energy(a["k"], a["x"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_power_torque
# ---------------------------------------------------------------------------

_power_torque_spec = ToolSpec(
    name="dynamics_power_torque",
    description=(
        "Power from torque and angular velocity: P = M·ω (W).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "M": {"type": "number", "description": "Torque (N·m)."},
            "omega": {"type": "number", "description": "Angular velocity (rad/s)."},
        },
        "required": ["M", "omega"],
    },
)


@register(_power_torque_spec, write=False)
async def run_power_torque(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("M", "omega"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(power_from_torque(a["M"], a["omega"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_power_force
# ---------------------------------------------------------------------------

_power_force_spec = ToolSpec(
    name="dynamics_power_force",
    description=(
        "Power from force and velocity: P = F·v (W).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "F": {"type": "number", "description": "Force (N)."},
            "v": {"type": "number", "description": "Velocity (m/s)."},
        },
        "required": ["F", "v"],
    },
)


@register(_power_force_spec, write=False)
async def run_power_force(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("F", "v"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(power_from_force(a["F"], a["v"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_linear_impulse
# ---------------------------------------------------------------------------

_lin_imp_spec = ToolSpec(
    name="dynamics_linear_impulse",
    description=(
        "Linear impulse-momentum: mv2 = mv1 + F·Δt.\n\n"
        "Returns impulse (N·s) and final momentum mv2 (kg·m/s).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "F": {"type": "number", "description": "Average net force (N)."},
            "dt": {"type": "number", "description": "Time interval (s). Must be > 0."},
            "mv1": {"type": "number", "description": "Initial momentum m·v1 (kg·m/s). Default 0."},
        },
        "required": ["F", "dt"],
    },
)


@register(_lin_imp_spec, write=False)
async def run_linear_impulse(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("F", "dt"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "mv1" in a:
        kwargs["mv1"] = a["mv1"]

    return ok_payload(linear_impulse(a["F"], a["dt"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_angular_impulse
# ---------------------------------------------------------------------------

_ang_imp_spec = ToolSpec(
    name="dynamics_angular_impulse",
    description=(
        "Angular impulse-momentum: L2 = L1 + M·Δt.\n\n"
        "Returns angular impulse (N·m·s) and final angular momentum L2 (kg·m²/s).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "M": {"type": "number", "description": "Average net moment (N·m)."},
            "dt": {"type": "number", "description": "Time interval (s). Must be > 0."},
            "L1": {"type": "number", "description": "Initial angular momentum (kg·m²/s). Default 0."},
        },
        "required": ["M", "dt"],
    },
)


@register(_ang_imp_spec, write=False)
async def run_angular_impulse(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("M", "dt"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "L1" in a:
        kwargs["L1"] = a["L1"]

    return ok_payload(angular_impulse(a["M"], a["dt"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_direct_impact
# ---------------------------------------------------------------------------

_direct_impact_spec = ToolSpec(
    name="dynamics_direct_impact",
    description=(
        "Direct central impact: compute post-impact velocities.\n\n"
        "Uses conservation of momentum + coefficient of restitution e.\n"
        "e = 0: perfectly plastic; e = 1: perfectly elastic.\n\n"
        "Warns if e > 1 (physically impossible, clamps to 1).\n\n"
        "Returns v1', v2' (m/s) and kinetic energy loss (J).\n\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m1": {"type": "number", "description": "Mass of body 1 (kg). Must be > 0."},
            "v1": {"type": "number", "description": "Pre-impact velocity of body 1 (m/s)."},
            "m2": {"type": "number", "description": "Mass of body 2 (kg). Must be > 0."},
            "v2": {"type": "number", "description": "Pre-impact velocity of body 2 (m/s)."},
            "e": {"type": "number", "description": "Coefficient of restitution [0, 1]. Must be >= 0."},
        },
        "required": ["m1", "v1", "m2", "v2", "e"],
    },
)


@register(_direct_impact_spec, write=False)
async def run_direct_impact(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m1", "v1", "m2", "v2", "e"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(direct_impact(a["m1"], a["v1"], a["m2"], a["v2"], a["e"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_oblique_impact
# ---------------------------------------------------------------------------

_oblique_impact_spec = ToolSpec(
    name="dynamics_oblique_impact",
    description=(
        "2-D oblique impact with line of impact along x-axis.\n\n"
        "Normal (x) components obey momentum + COR; tangential (y) unchanged.\n\n"
        "Returns v1x', v1y', v2x', v2y' (m/s) and energy loss (J).\n\n"
        "Warns if e > 1.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m1": {"type": "number", "description": "Mass of body 1 (kg). Must be > 0."},
            "v1x": {"type": "number", "description": "Pre-impact x-velocity of body 1 (m/s)."},
            "v1y": {"type": "number", "description": "Pre-impact y-velocity of body 1 (m/s)."},
            "m2": {"type": "number", "description": "Mass of body 2 (kg). Must be > 0."},
            "v2x": {"type": "number", "description": "Pre-impact x-velocity of body 2 (m/s)."},
            "v2y": {"type": "number", "description": "Pre-impact y-velocity of body 2 (m/s)."},
            "e": {"type": "number", "description": "Coefficient of restitution [0, 1]."},
        },
        "required": ["m1", "v1x", "v1y", "m2", "v2x", "v2y", "e"],
    },
)


@register(_oblique_impact_spec, write=False)
async def run_oblique_impact(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m1", "v1x", "v1y", "m2", "v2x", "v2y", "e"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(
        oblique_impact(a["m1"], a["v1x"], a["v1y"], a["m2"], a["v2x"], a["v2y"], a["e"])
    )


# ---------------------------------------------------------------------------
# Tool: dynamics_moi_solid_cylinder
# ---------------------------------------------------------------------------

_moi_cyl_spec = ToolSpec(
    name="dynamics_moi_solid_cylinder",
    description=(
        "Mass moment of inertia of a solid cylinder about its longitudinal axis.\n\n"
        "I = ½·m·r²\n\n"
        "Returns I (kg·m²).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "r": {"type": "number", "description": "Radius (m). Must be > 0."},
        },
        "required": ["m", "r"],
    },
)


@register(_moi_cyl_spec, write=False)
async def run_moi_solid_cylinder(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m", "r"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(moi_solid_cylinder(a["m"], a["r"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_moi_hollow_cylinder
# ---------------------------------------------------------------------------

_moi_hcyl_spec = ToolSpec(
    name="dynamics_moi_hollow_cylinder",
    description=(
        "Mass moment of inertia of a hollow cylinder about its longitudinal axis.\n\n"
        "I = ½·m·(r_o² + r_i²)\n\n"
        "Returns I (kg·m²).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "r_o": {"type": "number", "description": "Outer radius (m). Must be > 0."},
            "r_i": {"type": "number", "description": "Inner radius (m). Must be >= 0 and < r_o."},
        },
        "required": ["m", "r_o", "r_i"],
    },
)


@register(_moi_hcyl_spec, write=False)
async def run_moi_hollow_cylinder(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m", "r_o", "r_i"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(moi_hollow_cylinder(a["m"], a["r_o"], a["r_i"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_moi_solid_sphere
# ---------------------------------------------------------------------------

_moi_sphere_spec = ToolSpec(
    name="dynamics_moi_solid_sphere",
    description=(
        "Mass moment of inertia of a solid sphere about a diameter.\n\n"
        "I = 2/5·m·r²\n\n"
        "Returns I (kg·m²).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "r": {"type": "number", "description": "Radius (m). Must be > 0."},
        },
        "required": ["m", "r"],
    },
)


@register(_moi_sphere_spec, write=False)
async def run_moi_solid_sphere(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m", "r"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(moi_solid_sphere(a["m"], a["r"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_moi_thin_rod
# ---------------------------------------------------------------------------

_moi_rod_spec = ToolSpec(
    name="dynamics_moi_thin_rod",
    description=(
        "Mass moment of inertia of a thin rod perpendicular to its length.\n\n"
        "axis='centroid': I = 1/12·m·L²\n"
        "axis='end':      I = 1/3·m·L²\n\n"
        "Returns I (kg·m²).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "L": {"type": "number", "description": "Length (m). Must be > 0."},
            "axis": {
                "type": "string",
                "enum": ["centroid", "end"],
                "description": "Axis: 'centroid' (default) or 'end'.",
            },
        },
        "required": ["m", "L"],
    },
)


@register(_moi_rod_spec, write=False)
async def run_moi_thin_rod(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m", "L"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "axis" in a:
        kwargs["axis"] = a["axis"]

    return ok_payload(moi_thin_rod(a["m"], a["L"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_moi_rectangular_plate
# ---------------------------------------------------------------------------

_moi_rect_spec = ToolSpec(
    name="dynamics_moi_rectangular_plate",
    description=(
        "Mass moment of inertia of a thin rectangular plate about centroidal axes.\n\n"
        "I_z (polar) = 1/12·m·(a²+b²),  I_x = 1/12·m·b²,  I_y = 1/12·m·a²\n\n"
        "Returns I_z, I_x, I_y (kg·m²).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "a": {"type": "number", "description": "Width (m). Must be > 0."},
            "b": {"type": "number", "description": "Height (m). Must be > 0."},
        },
        "required": ["m", "a", "b"],
    },
)


@register(_moi_rect_spec, write=False)
async def run_moi_rectangular_plate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m", "a", "b"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(moi_rectangular_plate(a["m"], a["a"], a["b"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_parallel_axis
# ---------------------------------------------------------------------------

_parallel_axis_spec = ToolSpec(
    name="dynamics_parallel_axis",
    description=(
        "Parallel-axis (Steiner) theorem: I = I_cm + m·d².\n\n"
        "Returns I (kg·m²).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "I_cm": {"type": "number", "description": "MOI about centroidal axis (kg·m²). Must be >= 0."},
            "m": {"type": "number", "description": "Mass (kg). Must be > 0."},
            "d": {"type": "number", "description": "Distance between axes (m). Must be >= 0."},
        },
        "required": ["I_cm", "m", "d"],
    },
)


@register(_parallel_axis_spec, write=False)
async def run_parallel_axis(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("I_cm", "m", "d"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(parallel_axis(a["I_cm"], a["m"], a["d"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_flywheel_sizing
# ---------------------------------------------------------------------------

_flywheel_sizing_spec = ToolSpec(
    name="dynamics_flywheel_sizing",
    description=(
        "Required flywheel mass moment of inertia from energy fluctuation.\n\n"
        "I = ΔE / (ω_mean² · Cs)\n\n"
        "Cs = (ω_max - ω_min) / ω_mean — coefficient of fluctuation of speed.\n"
        "Typical Cs: 0.01 (precision machinery) to 0.20 (pumps).\n\n"
        "Warns if Cs > 0.2.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "E_fluctuation": {"type": "number", "description": "Energy fluctuation per cycle ΔE (J). Must be > 0."},
            "omega_mean": {"type": "number", "description": "Mean angular velocity (rad/s). Must be > 0."},
            "Cs": {"type": "number", "description": "Coefficient of fluctuation of speed. Must be > 0."},
        },
        "required": ["E_fluctuation", "omega_mean", "Cs"],
    },
)


@register(_flywheel_sizing_spec, write=False)
async def run_flywheel_sizing(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("E_fluctuation", "omega_mean", "Cs"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(flywheel_sizing(a["E_fluctuation"], a["omega_mean"], a["Cs"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_flywheel_rim
# ---------------------------------------------------------------------------

_flywheel_rim_spec = ToolSpec(
    name="dynamics_flywheel_rim",
    description=(
        "Required rim cross-section for a rim-type flywheel.\n\n"
        "A_cs = I / (2π·ρ·r_mean³),   t = A_cs / b\n\n"
        "Returns cross-sectional area (m²), radial thickness t (m), and rim mass (kg).\n\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "I_required": {"type": "number", "description": "Required MOI (kg·m²). Must be > 0."},
            "rho": {"type": "number", "description": "Material density (kg/m³). Must be > 0. Cast iron ≈ 7200."},
            "r_mean": {"type": "number", "description": "Mean rim radius (m). Must be > 0."},
            "b": {"type": "number", "description": "Axial width of rim (m). Must be > 0."},
        },
        "required": ["I_required", "rho", "r_mean", "b"],
    },
)


@register(_flywheel_rim_spec, write=False)
async def run_flywheel_rim(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("I_required", "rho", "r_mean", "b"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(flywheel_rim(a["I_required"], a["rho"], a["r_mean"], a["b"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_static_balance
# ---------------------------------------------------------------------------

_static_bal_spec = ToolSpec(
    name="dynamics_static_balance",
    description=(
        "Single-plane static balancing of rotating masses.\n\n"
        "Computes the resultant unbalance Σmᵢrᵢ and the correction mass·radius "
        "product required to achieve static balance.\n\n"
        "Returns resultant_mr (kg·m), resultant_angle_deg, correction_mr, correction_angle_deg.\n\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "masses": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Unbalance masses (kg). All > 0.",
            },
            "radii": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Radii of each mass from axis (m). All > 0.",
            },
            "angles_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Angular positions of each mass (degrees).",
            },
        },
        "required": ["masses", "radii", "angles_deg"],
    },
)


@register(_static_bal_spec, write=False)
async def run_static_balance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("masses", "radii", "angles_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(static_balance(a["masses"], a["radii"], a["angles_deg"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_dynamic_balance_two_plane
# ---------------------------------------------------------------------------

_dyn_bal_spec = ToolSpec(
    name="dynamics_dynamic_balance_two_plane",
    description=(
        "Two-plane (dynamic) balancing of rotating masses.\n\n"
        "Solves for correction mass·radius products in planes A and B using "
        "force and moment equilibrium.\n\n"
        "Returns correction_A_mr, correction_A_angle (deg), "
        "correction_B_mr, correction_B_angle (deg).\n\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "masses": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Unbalance masses (kg). All > 0.",
            },
            "radii": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Radii (m). All > 0.",
            },
            "angles_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Angular positions (degrees).",
            },
            "axial_positions": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Axial positions of each mass along rotor axis (m).",
            },
            "plane_a_pos": {
                "type": "number",
                "description": "Axial position of correction plane A (m).",
            },
            "plane_b_pos": {
                "type": "number",
                "description": "Axial position of correction plane B (m). Must differ from plane_a_pos.",
            },
        },
        "required": ["masses", "radii", "angles_deg", "axial_positions", "plane_a_pos", "plane_b_pos"],
    },
)


@register(_dyn_bal_spec, write=False)
async def run_dynamic_balance_two_plane(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("masses", "radii", "angles_deg", "axial_positions", "plane_a_pos", "plane_b_pos"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(
        dynamic_balance_two_plane(
            a["masses"],
            a["radii"],
            a["angles_deg"],
            a["axial_positions"],
            a["plane_a_pos"],
            a["plane_b_pos"],
        )
    )


# ---------------------------------------------------------------------------
# Tool: dynamics_residual_unbalance
# ---------------------------------------------------------------------------

_resid_unbal_spec = ToolSpec(
    name="dynamics_residual_unbalance",
    description=(
        "Compute residual specific unbalance U = m·e (g·mm) per ISO 1940.\n\n"
        "Parameters in grams and millimetres.\n\n"
        "Returns U_g_mm.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m_correction": {"type": "number", "description": "Correction mass (g). Must be > 0."},
            "e": {"type": "number", "description": "Eccentricity (mm). Must be > 0."},
        },
        "required": ["m_correction", "e"],
    },
)


@register(_resid_unbal_spec, write=False)
async def run_residual_unbalance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m_correction", "e"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(residual_unbalance(a["m_correction"], a["e"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_iso1940_grade
# ---------------------------------------------------------------------------

_iso1940_spec = ToolSpec(
    name="dynamics_iso1940_grade",
    description=(
        "ISO 1940-1 balance quality grade check.\n\n"
        "Grades: G0.4, G1, G2.5 (precision), G6.3 (default, general machinery), "
        "G16, G40, G100, G250, G630, G1600, G4000 (rough machinery).\n\n"
        "Returns within_grade flag, eper_mm (actual), eper_permissible_mm, "
        "and U_permissible_g_mm.  Warns if unbalance exceeds grade.\n\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "U_g_mm": {"type": "number", "description": "Actual residual unbalance (g·mm). Must be >= 0."},
            "m_rotor_kg": {"type": "number", "description": "Rotor mass (kg). Must be > 0."},
            "omega_rad_s": {"type": "number", "description": "Max operating angular velocity (rad/s). Must be > 0."},
            "grade": {
                "type": "string",
                "description": "ISO 1940 grade, e.g. 'G6.3'. Default 'G6.3'.",
            },
        },
        "required": ["U_g_mm", "m_rotor_kg", "omega_rad_s"],
    },
)


@register(_iso1940_spec, write=False)
async def run_iso1940_grade(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("U_g_mm", "m_rotor_kg", "omega_rad_s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "grade" in a:
        kwargs["grade"] = a["grade"]

    return ok_payload(iso1940_grade(a["U_g_mm"], a["m_rotor_kg"], a["omega_rad_s"], **kwargs))


# ---------------------------------------------------------------------------
# Tool: dynamics_shaking_force_primary
# ---------------------------------------------------------------------------

_shaking_primary_spec = ToolSpec(
    name="dynamics_shaking_force_primary",
    description=(
        "Primary shaking force from a reciprocating mass.\n\n"
        "F_primary = m_recip · r · ω² · cos(θ)\n\n"
        "Returns F_primary (N) at crank angle θ from TDC.\n\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m_recip": {"type": "number", "description": "Reciprocating mass (kg). Must be > 0."},
            "r": {"type": "number", "description": "Crank radius (m). Must be > 0."},
            "omega": {"type": "number", "description": "Crank angular velocity (rad/s). Must be > 0."},
            "theta_deg": {"type": "number", "description": "Crank angle from TDC (degrees)."},
        },
        "required": ["m_recip", "r", "omega", "theta_deg"],
    },
)


@register(_shaking_primary_spec, write=False)
async def run_shaking_force_primary(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m_recip", "r", "omega", "theta_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(shaking_force_primary(a["m_recip"], a["r"], a["omega"], a["theta_deg"]))


# ---------------------------------------------------------------------------
# Tool: dynamics_shaking_force_secondary
# ---------------------------------------------------------------------------

_shaking_secondary_spec = ToolSpec(
    name="dynamics_shaking_force_secondary",
    description=(
        "Secondary shaking force from a reciprocating mass.\n\n"
        "F_secondary = m_recip · r · ω² · (1/n) · cos(2θ)\n\n"
        "where n = L/r is the connecting-rod ratio.\n\n"
        "Returns F_secondary (N).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m_recip": {"type": "number", "description": "Reciprocating mass (kg). Must be > 0."},
            "r": {"type": "number", "description": "Crank radius (m). Must be > 0."},
            "omega": {"type": "number", "description": "Crank angular velocity (rad/s). Must be > 0."},
            "n": {"type": "number", "description": "Connecting-rod ratio n = L/r. Must be > 1."},
            "theta_deg": {"type": "number", "description": "Crank angle from TDC (degrees)."},
        },
        "required": ["m_recip", "r", "omega", "n", "theta_deg"],
    },
)


@register(_shaking_secondary_spec, write=False)
async def run_shaking_force_secondary(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m_recip", "r", "omega", "n", "theta_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(
        shaking_force_secondary(a["m_recip"], a["r"], a["omega"], a["n"], a["theta_deg"])
    )


# ---------------------------------------------------------------------------
# Tool: dynamics_gyroscopic_moment
# ---------------------------------------------------------------------------

_gyro_spec = ToolSpec(
    name="dynamics_gyroscopic_moment",
    description=(
        "Gyroscopic reaction moment for perpendicular spin and precession axes.\n\n"
        "M_gyro = I_spin · ω_spin · ω_precession\n\n"
        "Returns M_gyro (N·m).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "I_spin": {"type": "number", "description": "Spin-axis MOI (kg·m²). Must be > 0."},
            "omega_spin": {"type": "number", "description": "Spin angular velocity (rad/s). Must be > 0."},
            "omega_precession": {"type": "number", "description": "Precession angular velocity (rad/s). Must be > 0."},
        },
        "required": ["I_spin", "omega_spin", "omega_precession"],
    },
)


@register(_gyro_spec, write=False)
async def run_gyroscopic_moment(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("I_spin", "omega_spin", "omega_precession"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    return ok_payload(gyroscopic_moment(a["I_spin"], a["omega_spin"], a["omega_precession"]))
