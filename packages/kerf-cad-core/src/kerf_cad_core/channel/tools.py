"""
kerf_cad_core.channel.tools — LLM tool wrappers for open-channel hydraulics.

Registers the following tools with the Kerf tool registry:

  channel_section_properties   — geometry + hydraulic props for any section shape
  channel_normal_depth         — Manning / Chezy normal depth (bisection)
  channel_critical_depth       — critical depth + min specific energy
  channel_froude_number        — Froude number + flow regime at a given depth
  channel_specific_energy      — specific energy E = y + V²/(2g)
  channel_momentum_function    — specific force M = Q²/(gA) + ȳA
  channel_hydraulic_jump       — sequent depth, energy loss, jump length
  channel_gvf_profile_type     — M/S/C/H/A profile classification per Chow
  channel_gvf_direct_step      — water-surface profile by direct-step method
  channel_best_hydraulic_section — most-efficient section dimensions
  channel_weir_broad_crested   — broad-crested weir discharge
  channel_weir_sharp_crested   — sharp-crested rectangular weir discharge
  channel_weir_vnotch          — V-notch (triangular) weir discharge
  channel_culvert_control      — inlet vs outlet culvert control + capacity
  channel_transition           — depth at channel contraction / expansion

All tools are pure-Python; no OCC dependency.
Errors → {"ok": False, "reason": ...} — tools never raise.

Units: SI (metres, m³/s) throughout.

References
----------
Chow, V.T. (1959) Open-Channel Hydraulics.  McGraw-Hill.
Henderson, F.M. (1966) Open Channel Flow.  Macmillan.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.channel.flow import (
    section_properties,
    normal_depth,
    critical_depth,
    froude_number,
    specific_energy,
    momentum_function,
    hydraulic_jump,
    gvf_profile_type,
    gvf_direct_step,
    best_hydraulic_section,
    weir_broad_crested,
    weir_sharp_crested,
    weir_vnotch,
    culvert_control,
    channel_transition,
)


# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

_SHAPE_ENUM = ["rectangular", "trapezoidal", "triangular", "circular", "parabolic"]
_SHAPE_DESC = (
    "Cross-section shape: 'rectangular' (needs b), 'trapezoidal' (needs b, z), "
    "'triangular' (needs z), 'circular' (needs D), 'parabolic' (needs T_top)."
)
_SHAPE_PARAMS = {
    "b": {
        "type": "number",
        "description": "Bottom width (m) — rectangular / trapezoidal. Must be > 0.",
    },
    "z": {
        "type": "number",
        "description": "Side slope H:V — trapezoidal / triangular. Must be >= 0.",
    },
    "D": {
        "type": "number",
        "description": "Diameter (m) — circular. Must be > 0.",
    },
    "T_top": {
        "type": "number",
        "description": (
            "Parabolic shape coefficient (m^0.5): top width = T_top * sqrt(y). "
            "Must be > 0."
        ),
    },
}


def _extract_shape_kwargs(a: dict) -> dict:
    """Pull recognised shape keyword args from the input dict."""
    out = {}
    for key in ("b", "z", "D", "T_top"):
        if key in a:
            out[key] = float(a[key])
    return out


# ---------------------------------------------------------------------------
# Tool: channel_section_properties
# ---------------------------------------------------------------------------

_section_props_spec = ToolSpec(
    name="channel_section_properties",
    description=(
        "Compute geometric and hydraulic properties of an open-channel "
        "cross-section at a given flow depth.\n"
        "\n"
        "Returns flow area A (m²), wetted perimeter P (m), top width T (m), "
        "hydraulic radius R = A/P (m), hydraulic depth D_h = A/T (m), "
        "and section factor Z = A√D_h (m^(5/2)).\n"
        "\n"
        "Sections supported: rectangular, trapezoidal, triangular, circular "
        "(partial-flow), parabolic.\n"
        "\n"
        "Reference: Chow (1959) Table 2-1."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "y": {"type": "number", "description": "Flow depth (m), > 0."},
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "y"],
    },
)


@register(_section_props_spec, write=False)
async def run_channel_section_properties(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    shape = a.get("shape")
    y = a.get("y")
    if not shape:
        return json.dumps({"ok": False, "reason": "shape is required"})
    if y is None:
        return json.dumps({"ok": False, "reason": "y is required"})
    result = section_properties(shape, float(y), **_extract_shape_kwargs(a))
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_normal_depth
# ---------------------------------------------------------------------------

_normal_depth_spec = ToolSpec(
    name="channel_normal_depth",
    description=(
        "Solve for the normal depth of a prismatic open channel by bisection.\n"
        "\n"
        "Manning's equation (SI):  Q = (1/n) · A · R^(2/3) · S^(1/2)\n"
        "Chezy equation:           Q = C · A · √(R·S)\n"
        "Provide exactly one of manning_n or chezy_C.\n"
        "\n"
        "Returns normal_depth_m, velocity_m_per_s, flow_area_m2, "
        "wetted_perimeter_m, hydraulic_radius_m, top_width_m, hydraulic_depth_m, "
        "froude_number, flow_regime, channel_full, warnings.\n"
        "\n"
        "flow_regime: 'subcritical' | 'critical' | 'supercritical' | 'channel_full'.\n"
        "Supercritical normal flow is flagged in warnings (not an error).\n"
        "\n"
        "Typical Manning's n: 0.010 PVC, 0.013 concrete, 0.015 brick, "
        "0.025 earth, 0.035 vegetated.\n"
        "\n"
        "Reference: Manning (1891); Chow (1959) §5-3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Design discharge (m³/s), > 0."},
            "slope": {"type": "number", "description": "Longitudinal bed slope (m/m), > 0."},
            "manning_n": {
                "type": "number",
                "description": "Manning's roughness n (dimensionless), > 0. Mutually exclusive with chezy_C.",
            },
            "chezy_C": {
                "type": "number",
                "description": "Chezy coefficient C (m^0.5/s), > 0. Mutually exclusive with manning_n.",
            },
            "max_depth_m": {
                "type": "number",
                "description": "Upper search bound for bisection (m, default 20). channel_full returned if exceeded.",
            },
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s", "slope"],
    },
)


@register(_normal_depth_spec, write=False)
async def run_channel_normal_depth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    shape = a.get("shape")
    flow = a.get("flow_m3s")
    slope = a.get("slope")
    if not shape:
        return json.dumps({"ok": False, "reason": "shape is required"})
    if flow is None:
        return json.dumps({"ok": False, "reason": "flow_m3s is required"})
    if slope is None:
        return json.dumps({"ok": False, "reason": "slope is required"})
    kwargs = _extract_shape_kwargs(a)
    mn = a.get("manning_n")
    cc = a.get("chezy_C")
    max_d = float(a.get("max_depth_m", 20.0))
    result = normal_depth(
        shape, float(flow), float(slope),
        manning_n=float(mn) if mn is not None else None,
        chezy_C=float(cc) if cc is not None else None,
        max_depth_m=max_d,
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_critical_depth
# ---------------------------------------------------------------------------

_critical_depth_spec = ToolSpec(
    name="channel_critical_depth",
    description=(
        "Compute the critical depth of an open channel for a given discharge.\n"
        "\n"
        "At critical depth the Froude number Fr = 1 and specific energy is minimum.\n"
        "Solved by bisection on the section factor Z = A·√D_h = Q/√g.\n"
        "\n"
        "Returns critical_depth_m, critical_velocity_m_per_s, critical_area_m2, "
        "froude_number (≈1.0), min_specific_energy_m, warnings.\n"
        "\n"
        "Reference: Chow (1959) §4-1."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "max_depth_m": {
                "type": "number",
                "description": "Search upper bound (m, default 20).",
            },
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s"],
    },
)


@register(_critical_depth_spec, write=False)
async def run_channel_critical_depth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    shape = a.get("shape")
    flow = a.get("flow_m3s")
    if not shape:
        return json.dumps({"ok": False, "reason": "shape is required"})
    if flow is None:
        return json.dumps({"ok": False, "reason": "flow_m3s is required"})
    max_d = float(a.get("max_depth_m", 20.0))
    result = critical_depth(shape, float(flow), max_depth_m=max_d, **_extract_shape_kwargs(a))
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_froude_number
# ---------------------------------------------------------------------------

_froude_spec = ToolSpec(
    name="channel_froude_number",
    description=(
        "Compute the Froude number and flow regime at a known depth.\n"
        "\n"
        "Fr = V / √(g · D_h)  where D_h = A/T (hydraulic depth).\n"
        "\n"
        "flow_regime: 'subcritical' (Fr < 0.95), 'critical' (0.95 ≤ Fr ≤ 1.05), "
        "'supercritical' (Fr > 1.05).\n"
        "\n"
        "Reference: Chow (1959) §3-5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "depth_m": {"type": "number", "description": "Flow depth (m), > 0."},
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s", "depth_m"],
    },
)


@register(_froude_spec, write=False)
async def run_channel_froude_number(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    shape = a.get("shape")
    flow = a.get("flow_m3s")
    depth = a.get("depth_m")
    for name, val in [("shape", shape), ("flow_m3s", flow), ("depth_m", depth)]:
        if val is None:
            return json.dumps({"ok": False, "reason": f"{name} is required"})
    result = froude_number(shape, float(flow), float(depth), **_extract_shape_kwargs(a))
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_specific_energy
# ---------------------------------------------------------------------------

_specific_energy_spec = ToolSpec(
    name="channel_specific_energy",
    description=(
        "Compute specific energy E = y + V²/(2g) at a given flow depth.\n"
        "\n"
        "Returns specific_energy_m, velocity_head_m, velocity_m_per_s.\n"
        "\n"
        "The minimum specific energy occurs at critical depth (Fr=1).\n"
        "For E < E_min no real solution exists — the channel is choked.\n"
        "\n"
        "Reference: Chow (1959) §4-2."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "depth_m": {"type": "number", "description": "Flow depth (m), > 0."},
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s", "depth_m"],
    },
)


@register(_specific_energy_spec, write=False)
async def run_channel_specific_energy(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    shape = a.get("shape")
    flow = a.get("flow_m3s")
    depth = a.get("depth_m")
    for name, val in [("shape", shape), ("flow_m3s", flow), ("depth_m", depth)]:
        if val is None:
            return json.dumps({"ok": False, "reason": f"{name} is required"})
    result = specific_energy(shape, float(flow), float(depth), **_extract_shape_kwargs(a))
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_momentum_function
# ---------------------------------------------------------------------------

_momentum_spec = ToolSpec(
    name="channel_momentum_function",
    description=(
        "Compute the specific-force (momentum) function M = Q²/(gA) + ȳ·A.\n"
        "\n"
        "The momentum function is conserved across a hydraulic jump (neglecting "
        "wall friction) and is used to locate the sequent depth.\n"
        "\n"
        "ȳ is the depth to the centroid of the flow area below the free surface.\n"
        "\n"
        "Reference: Henderson (1966) §2-5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "depth_m": {"type": "number", "description": "Flow depth (m), > 0."},
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s", "depth_m"],
    },
)


@register(_momentum_spec, write=False)
async def run_channel_momentum_function(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    shape = a.get("shape")
    flow = a.get("flow_m3s")
    depth = a.get("depth_m")
    for name, val in [("shape", shape), ("flow_m3s", flow), ("depth_m", depth)]:
        if val is None:
            return json.dumps({"ok": False, "reason": f"{name} is required"})
    result = momentum_function(shape, float(flow), float(depth), **_extract_shape_kwargs(a))
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_hydraulic_jump
# ---------------------------------------------------------------------------

_jump_spec = ToolSpec(
    name="channel_hydraulic_jump",
    description=(
        "Compute the sequent (conjugate) depth, energy loss, and estimated length "
        "of a hydraulic jump.\n"
        "\n"
        "For rectangular channels: exact Bélanger equation\n"
        "  y₂ = (y₁/2) · (√(1 + 8·Fr₁²) − 1)\n"
        "For other shapes: bisection on the momentum function M(y₁) = M(y₂).\n"
        "\n"
        "Jump length estimate: L ≈ 6·(y₂ − y₁)  (Chow 1959, valid for Fr₁ ≈ 1.7–17).\n"
        "\n"
        "If upstream depth is subcritical (Fr₁ < 1) the jump cannot form; a "
        "warning is added but results are still returned.\n"
        "\n"
        "Returns depth1_m, depth2_m, froude1, froude2, energy_loss_m, "
        "relative_energy_loss, length_estimate_m, warnings.\n"
        "\n"
        "Reference: Chow (1959) §15-1; Bélanger (1828)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "depth1_m": {
                "type": "number",
                "description": "Upstream (supercritical) depth (m), > 0.",
            },
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s", "depth1_m"],
    },
)


@register(_jump_spec, write=False)
async def run_channel_hydraulic_jump(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    shape = a.get("shape")
    flow = a.get("flow_m3s")
    d1 = a.get("depth1_m")
    for name, val in [("shape", shape), ("flow_m3s", flow), ("depth1_m", d1)]:
        if val is None:
            return json.dumps({"ok": False, "reason": f"{name} is required"})
    result = hydraulic_jump(shape, float(flow), float(d1), **_extract_shape_kwargs(a))
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_gvf_profile_type
# ---------------------------------------------------------------------------

_gvf_type_spec = ToolSpec(
    name="channel_gvf_profile_type",
    description=(
        "Classify the gradually-varied-flow (GVF) water-surface profile type.\n"
        "\n"
        "Channel classes and profile types (Chow 1959):\n"
        "  Mild (M):     yn > yc  → M1 (y > yn), M2 (yc < y < yn), M3 (y < yc)\n"
        "  Steep (S):    yn < yc  → S1 (y > yc), S2 (yn < y < yc), S3 (y < yn)\n"
        "  Critical (C): yn ≈ yc  → C1 (y > yc), C3 (y < yc)\n"
        "  Horizontal (H): S₀=0   → H2 (y > yc), H3 (y < yc)\n"
        "  Adverse (A):  S₀ < 0  → A2 (y > yc), A3 (y < yc)\n"
        "\n"
        "Returns profile_type, channel_class, normal_depth_m, critical_depth_m, "
        "depth_m, froude_number.\n"
        "\n"
        "Reference: Chow (1959) Chapter 9."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "slope": {"type": "number", "description": "Bed slope (m/m). Use 0 for horizontal, negative for adverse."},
            "manning_n": {"type": "number", "description": "Manning's roughness n, > 0."},
            "depth_m": {"type": "number", "description": "Actual flow depth at the point of interest (m), > 0."},
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s", "slope", "manning_n", "depth_m"],
    },
)


@register(_gvf_type_spec, write=False)
async def run_channel_gvf_profile_type(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for req in ("shape", "flow_m3s", "slope", "manning_n", "depth_m"):
        if a.get(req) is None:
            return json.dumps({"ok": False, "reason": f"{req} is required"})
    result = gvf_profile_type(
        a["shape"], float(a["flow_m3s"]), float(a["slope"]),
        float(a["manning_n"]), float(a["depth_m"]),
        **_extract_shape_kwargs(a),
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_gvf_direct_step
# ---------------------------------------------------------------------------

_gvf_step_spec = ToolSpec(
    name="channel_gvf_direct_step",
    description=(
        "Compute a gradually-varied-flow water-surface profile by the direct-step "
        "method.\n"
        "\n"
        "The direct-step method advances from a known boundary depth to a target "
        "depth, computing the streamwise distance Δx between successive depth "
        "increments:\n"
        "  Δx = (E₂ − E₁) / (S₀ − S̄_f)\n"
        "where S̄_f is the average friction slope between steps.\n"
        "\n"
        "Returns a profile list of {x_m, depth_m, specific_energy_m, "
        "velocity_m_per_s, froude_number, friction_slope} plus total_length_m "
        "and warnings.\n"
        "\n"
        "Critical-zone steps (S₀ ≈ S_f) are skipped with a warning.\n"
        "\n"
        "Reference: Chow (1959) §12-2."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "slope": {"type": "number", "description": "Bed slope S₀ (m/m), >= 0."},
            "manning_n": {"type": "number", "description": "Manning's n, > 0."},
            "depth_start_m": {"type": "number", "description": "Known boundary depth (m), > 0."},
            "depth_end_m": {"type": "number", "description": "Target end depth (m), > 0."},
            "n_steps": {
                "type": "integer",
                "description": "Number of depth increments (default 100, min 2).",
            },
            **_SHAPE_PARAMS,
        },
        "required": ["shape", "flow_m3s", "slope", "manning_n", "depth_start_m", "depth_end_m"],
    },
)


@register(_gvf_step_spec, write=False)
async def run_channel_gvf_direct_step(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for req in ("shape", "flow_m3s", "slope", "manning_n", "depth_start_m", "depth_end_m"):
        if a.get(req) is None:
            return json.dumps({"ok": False, "reason": f"{req} is required"})
    result = gvf_direct_step(
        a["shape"], float(a["flow_m3s"]), float(a["slope"]),
        float(a["manning_n"]), float(a["depth_start_m"]), float(a["depth_end_m"]),
        n_steps=int(a.get("n_steps", 100)),
        **_extract_shape_kwargs(a),
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_best_hydraulic_section
# ---------------------------------------------------------------------------

_best_section_spec = ToolSpec(
    name="channel_best_hydraulic_section",
    description=(
        "Compute the dimensions of the most-hydraulically-efficient ("
        "\"best\") cross-section for a given flow, slope, and roughness.\n"
        "\n"
        "The best hydraulic section minimises wetted perimeter for a given flow "
        "area, maximising hydraulic radius and thereby minimising excavation cost.\n"
        "\n"
        "Analytical solutions (Chow 1959 §6-5):\n"
        "  rectangular : b = 2y  (half-hexagon)\n"
        "  trapezoidal : z = 1/√3 ≈ 0.577, b = 2y/√3  (true half-hexagon)\n"
        "  triangular  : z = 1  (45°)\n"
        "  circular    : y/D ≈ 0.938  (max-Q condition)\n"
        "  parabolic   : T = 2√2·√y  (T proportional to √y)\n"
        "\n"
        "Returns optimal_depth_m plus shape-specific optimal dimensions, "
        "wetted_perimeter_m, hydraulic_radius_m, flow_area_m2.\n"
        "\n"
        "Reference: Chow (1959) §6-5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": _SHAPE_ENUM, "description": _SHAPE_DESC},
            "flow_m3s": {"type": "number", "description": "Design discharge (m³/s), > 0."},
            "slope": {"type": "number", "description": "Bed slope (m/m), > 0."},
            "manning_n": {"type": "number", "description": "Manning's n, > 0."},
        },
        "required": ["shape", "flow_m3s", "slope", "manning_n"],
    },
)


@register(_best_section_spec, write=False)
async def run_channel_best_hydraulic_section(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for req in ("shape", "flow_m3s", "slope", "manning_n"):
        if a.get(req) is None:
            return json.dumps({"ok": False, "reason": f"{req} is required"})
    result = best_hydraulic_section(
        a["shape"], float(a["flow_m3s"]), float(a["slope"]), float(a["manning_n"]),
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_weir_broad_crested
# ---------------------------------------------------------------------------

_broad_weir_spec = ToolSpec(
    name="channel_weir_broad_crested",
    description=(
        "Compute discharge over a broad-crested (overflow) weir.\n"
        "\n"
        "Formula: Q = Cd · L · H^(3/2)\n"
        "  L  — crest length (m)\n"
        "  H  — head above crest (m)\n"
        "  Cd — discharge coefficient (default 1.7, SI; range typically 1.5–1.8)\n"
        "\n"
        "The broad-crested weir acts as a critical-flow control; Cd accounts for "
        "approach velocity, geometry, and submergence.\n"
        "\n"
        "Returns discharge_m3s, head_m, crest_length_m, Cd.\n"
        "\n"
        "Reference: Henderson (1966) §6-2; BS EN ISO 4374."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "head_m": {"type": "number", "description": "Head above weir crest (m), > 0."},
            "crest_length_m": {"type": "number", "description": "Weir crest length (m), > 0."},
            "Cd": {
                "type": "number",
                "description": "Discharge coefficient (default 1.7, SI form Q=Cd·L·H^1.5). Range 1.5–2.2 typical.",
            },
        },
        "required": ["head_m", "crest_length_m"],
    },
)


@register(_broad_weir_spec, write=False)
async def run_channel_weir_broad_crested(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    head = a.get("head_m")
    length = a.get("crest_length_m")
    if head is None:
        return json.dumps({"ok": False, "reason": "head_m is required"})
    if length is None:
        return json.dumps({"ok": False, "reason": "crest_length_m is required"})
    kwargs: dict = {}
    if "Cd" in a:
        kwargs["Cd"] = float(a["Cd"])
    result = weir_broad_crested(float(head), float(length), **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_weir_sharp_crested
# ---------------------------------------------------------------------------

_sharp_weir_spec = ToolSpec(
    name="channel_weir_sharp_crested",
    description=(
        "Compute discharge over a sharp-crested (thin-plate) rectangular weir.\n"
        "\n"
        "Formula: Q = (2/3) · Cd · L · √(2g) · H^(3/2)\n"
        "  Cd — dimensionless discharge coefficient (default 0.611, Francis)\n"
        "\n"
        "Valid for free-nappe conditions (tailwater below weir crest).\n"
        "Use Francis formula correction (±0.1 for end contractions if applicable).\n"
        "\n"
        "Returns discharge_m3s, head_m, crest_length_m, Cd.\n"
        "\n"
        "Reference: Francis (1855); Chow (1959) §14-1."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "head_m": {"type": "number", "description": "Head above weir crest (m), > 0."},
            "crest_length_m": {"type": "number", "description": "Weir crest length (m), > 0."},
            "Cd": {
                "type": "number",
                "description": "Discharge coefficient (default 0.611). Range 0.59–0.65.",
            },
        },
        "required": ["head_m", "crest_length_m"],
    },
)


@register(_sharp_weir_spec, write=False)
async def run_channel_weir_sharp_crested(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    head = a.get("head_m")
    length = a.get("crest_length_m")
    if head is None:
        return json.dumps({"ok": False, "reason": "head_m is required"})
    if length is None:
        return json.dumps({"ok": False, "reason": "crest_length_m is required"})
    kwargs: dict = {}
    if "Cd" in a:
        kwargs["Cd"] = float(a["Cd"])
    result = weir_sharp_crested(float(head), float(length), **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_weir_vnotch
# ---------------------------------------------------------------------------

_vnotch_spec = ToolSpec(
    name="channel_weir_vnotch",
    description=(
        "Compute discharge through a V-notch (triangular) weir.\n"
        "\n"
        "Formula: Q = (8/15) · Cd · tan(θ/2) · √(2g) · H^(5/2)\n"
        "  θ  — notch angle (default 90°)\n"
        "  Cd — discharge coefficient (default 0.611)\n"
        "\n"
        "V-notch weirs are accurate at low flows; the 90° V-notch is the most "
        "common standard.\n"
        "\n"
        "Returns discharge_m3s, head_m, notch_angle_deg, Cd.\n"
        "\n"
        "Reference: ISO 1438:2017; Chow (1959) §14-2."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "head_m": {"type": "number", "description": "Head above notch apex (m), > 0."},
            "notch_angle_deg": {
                "type": "number",
                "description": "Full notch angle in degrees (default 90). Range: (0, 180).",
            },
            "Cd": {
                "type": "number",
                "description": "Discharge coefficient (default 0.611).",
            },
        },
        "required": ["head_m"],
    },
)


@register(_vnotch_spec, write=False)
async def run_channel_weir_vnotch(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    head = a.get("head_m")
    if head is None:
        return json.dumps({"ok": False, "reason": "head_m is required"})
    kwargs: dict = {}
    if "notch_angle_deg" in a:
        kwargs["notch_angle_deg"] = float(a["notch_angle_deg"])
    if "Cd" in a:
        kwargs["Cd"] = float(a["Cd"])
    result = weir_vnotch(float(head), **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_culvert_control
# ---------------------------------------------------------------------------

_culvert_spec = ToolSpec(
    name="channel_culvert_control",
    description=(
        "Estimate culvert capacity and identify the controlling condition "
        "(inlet control vs outlet control) per FHWA HDS-5.\n"
        "\n"
        "Inlet control:  Q = Cd · A · √(2g · HW)   (Cd ≈ 0.6)\n"
        "Outlet control: energy balance including entrance, friction, exit losses;\n"
        "  K = 1 + Ke + (2g·n²/R^(4/3)) · L/D\n"
        "  Q = A · √(2g·ΔH / K)\n"
        "\n"
        "The governing (lower) Q is the design capacity.\n"
        "\n"
        "Entrance loss coefficients Ke: 0.2 (well-rounded), 0.5 (square-edge, "
        "default), 0.9 (projecting).\n"
        "\n"
        "Returns controlling_condition, capacity_m3s, inlet_control_Q_m3s, "
        "outlet_control_Q_m3s, warnings.\n"
        "\n"
        "Reference: FHWA HDS-5 (2012)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "diameter_m": {"type": "number", "description": "Culvert diameter (m), > 0."},
            "length_m": {"type": "number", "description": "Culvert barrel length (m), > 0."},
            "slope": {"type": "number", "description": "Barrel slope (m/m), >= 0."},
            "manning_n": {"type": "number", "description": "Manning's n for barrel, > 0."},
            "headwater_m": {"type": "number", "description": "Headwater depth above inlet invert (m), > 0."},
            "tailwater_m": {
                "type": "number",
                "description": "Tailwater depth above outlet invert (m, default 0).",
            },
            "Ke": {
                "type": "number",
                "description": "Entrance loss coefficient (default 0.5 for square-edge).",
            },
        },
        "required": ["diameter_m", "length_m", "slope", "manning_n", "headwater_m"],
    },
)


@register(_culvert_spec, write=False)
async def run_channel_culvert_control(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for req in ("diameter_m", "length_m", "slope", "manning_n", "headwater_m"):
        if a.get(req) is None:
            return json.dumps({"ok": False, "reason": f"{req} is required"})
    kwargs: dict = {}
    if "tailwater_m" in a:
        kwargs["tailwater_m"] = float(a["tailwater_m"])
    if "Ke" in a:
        kwargs["Ke"] = float(a["Ke"])
    result = culvert_control(
        float(a["diameter_m"]), float(a["length_m"]),
        float(a["slope"]), float(a["manning_n"]),
        float(a["headwater_m"]), **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: channel_transition
# ---------------------------------------------------------------------------

_transition_spec = ToolSpec(
    name="channel_transition",
    description=(
        "Compute depth at a channel transition (contraction or expansion) using "
        "the energy equation with head-loss coefficient.\n"
        "\n"
        "Energy equation:  E₁ = E₂ + K · |ΔV²/(2g)|\n"
        "  K = contraction_loss_coeff if velocity increases (contraction)\n"
        "  K = expansion_loss_coeff   if velocity decreases (expansion)\n"
        "\n"
        "Typical K values:\n"
        "  Contraction: 0.0 (ideal), 0.1 (gradual), 0.3 (abrupt)\n"
        "  Expansion:   0.0 (ideal), 0.3 (gradual), 0.8 (abrupt)\n"
        "\n"
        "Shape parameters for the downstream section are suffixed '_2' "
        "(e.g. b_2=1.5 for a narrower downstream width).\n"
        "\n"
        "Returns depth2_m, velocity1_m_per_s, velocity2_m_per_s, "
        "energy1_m, energy2_m, head_loss_m, transition_type, warnings.\n"
        "\n"
        "Choked-flow warning issued if downstream Fr ≥ 0.95.\n"
        "\n"
        "Reference: Chow (1959) §11-1; French (1985) §2-6."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape1": {"type": "string", "enum": _SHAPE_ENUM, "description": "Upstream section shape."},
            "shape2": {"type": "string", "enum": _SHAPE_ENUM, "description": "Downstream section shape."},
            "flow_m3s": {"type": "number", "description": "Discharge (m³/s), > 0."},
            "depth1_m": {"type": "number", "description": "Known upstream depth (m), > 0."},
            "contraction_loss_coeff": {
                "type": "number",
                "description": "Head-loss coefficient for contraction (default 0.1).",
            },
            "expansion_loss_coeff": {
                "type": "number",
                "description": "Head-loss coefficient for expansion (default 0.3).",
            },
            "b": {"type": "number", "description": "Upstream bottom width (m) — rectangular/trapezoidal."},
            "z": {"type": "number", "description": "Upstream side slope H:V — trapezoidal/triangular."},
            "D": {"type": "number", "description": "Upstream diameter (m) — circular."},
            "T_top": {"type": "number", "description": "Upstream T_top coefficient — parabolic."},
            "b_2": {"type": "number", "description": "Downstream bottom width (m)."},
            "z_2": {"type": "number", "description": "Downstream side slope H:V."},
            "D_2": {"type": "number", "description": "Downstream diameter (m)."},
            "T_top_2": {"type": "number", "description": "Downstream T_top coefficient."},
        },
        "required": ["shape1", "shape2", "flow_m3s", "depth1_m"],
    },
)


@register(_transition_spec, write=False)
async def run_channel_transition(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for req in ("shape1", "shape2", "flow_m3s", "depth1_m"):
        if a.get(req) is None:
            return json.dumps({"ok": False, "reason": f"{req} is required"})
    kwargs: dict = {}
    # Upstream shape params
    for k in ("b", "z", "D", "T_top"):
        if k in a:
            kwargs[k] = float(a[k])
    # Downstream params (with _2 suffix)
    for k in ("b_2", "z_2", "D_2", "T_top_2"):
        if k in a:
            kwargs[k] = float(a[k])
    # Loss coefficients
    loss_kwargs: dict = {}
    if "contraction_loss_coeff" in a:
        loss_kwargs["contraction_loss_coeff"] = float(a["contraction_loss_coeff"])
    if "expansion_loss_coeff" in a:
        loss_kwargs["expansion_loss_coeff"] = float(a["expansion_loss_coeff"])
    result = channel_transition(
        a["shape1"], float(a["flow_m3s"]), float(a["depth1_m"]),
        a["shape2"], **loss_kwargs, **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)
