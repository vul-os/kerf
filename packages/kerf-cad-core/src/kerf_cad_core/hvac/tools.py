"""
kerf_cad_core.hvac.tools — LLM tool wrappers for HVAC duct sizing.

Registers nine tools with the Kerf tool registry:

  hvac_cfm_from_sensible_load     — airflow from sensible BTU/h load
  hvac_round_duct_diameter        — round duct diameter from CFM + velocity
  hvac_rect_equiv_diameter        — Huebscher rectangular equivalent diameter
  hvac_duct_friction_loss         — Darcy-Weisbach friction loss for straight duct
  hvac_duct_fitting_loss          — dynamic loss coefficient fitting
  hvac_size_equal_friction        — equal-friction duct sizing
  hvac_size_velocity_reduction    — velocity-reduction duct sizing
  hvac_branch_static_pressure     — total static pressure for a branch path
  hvac_fan_law_scale              — fan-law affinity scaling

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
ASHRAE Handbook — Fundamentals (2021), Chapter 21: Duct Design
Huebscher (1948) ASHVE Trans. 54

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.hvac.ducts import (
    cfm_from_sensible_load,
    round_duct_diameter,
    rect_equiv_diameter,
    duct_friction_loss,
    duct_fitting_loss,
    size_duct_equal_friction,
    size_duct_velocity_reduction,
    branch_static_pressure,
    fan_law_scale,
)


# ---------------------------------------------------------------------------
# Tool: hvac_cfm_from_sensible_load
# ---------------------------------------------------------------------------

_cfm_load_spec = ToolSpec(
    name="hvac_cfm_from_sensible_load",
    description=(
        "Calculate required airflow (CFM) from a sensible cooling or heating load.\n"
        "\n"
        "Uses the ASHRAE standard-air sensible-heat formula:\n"
        "    Q_btuh = 1.08 × CFM × ΔT\n"
        "\n"
        "Returns cfm (CFM).  Typical ΔT: 15–25 °F for cooling, 30–70 °F for heating.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_btuh": {
                "type": "number",
                "description": "Sensible thermal load (BTU/h). Must be > 0.",
            },
            "delta_T_F": {
                "type": "number",
                "description": (
                    "Supply-air temperature differential (°F). Must be > 0. "
                    "Typical: 20 °F for cooling, 50 °F for heating."
                ),
            },
        },
        "required": ["Q_btuh", "delta_T_F"],
    },
)


@register(_cfm_load_spec, write=False)
async def run_cfm_from_sensible_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    Q = a.get("Q_btuh")
    dT = a.get("delta_T_F")
    if Q is None:
        return json.dumps({"ok": False, "reason": "Q_btuh is required"})
    if dT is None:
        return json.dumps({"ok": False, "reason": "delta_T_F is required"})

    result = cfm_from_sensible_load(Q, dT)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_round_duct_diameter
# ---------------------------------------------------------------------------

_round_duct_spec = ToolSpec(
    name="hvac_round_duct_diameter",
    description=(
        "Calculate round duct diameter from airflow (CFM) and target velocity (fpm).\n"
        "\n"
        "Area = CFM / V  →  D = 2·√(Area/π)  (converted to inches).\n"
        "\n"
        "Issues a warning when velocity exceeds ASHRAE guidelines:\n"
        "  > 800 fpm: over the branch-duct guideline.\n"
        "  > 1500 fpm: over the main-trunk guideline.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cfm": {
                "type": "number",
                "description": "Airflow (CFM). Must be > 0.",
            },
            "velocity_fpm": {
                "type": "number",
                "description": (
                    "Target mean duct velocity (fpm). Must be > 0. "
                    "Typical branch: 400–800 fpm; trunk: 800–1500 fpm."
                ),
            },
        },
        "required": ["cfm", "velocity_fpm"],
    },
)


@register(_round_duct_spec, write=False)
async def run_round_duct_diameter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    cfm = a.get("cfm")
    vel = a.get("velocity_fpm")
    if cfm is None:
        return json.dumps({"ok": False, "reason": "cfm is required"})
    if vel is None:
        return json.dumps({"ok": False, "reason": "velocity_fpm is required"})

    result = round_duct_diameter(cfm, vel)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_rect_equiv_diameter
# ---------------------------------------------------------------------------

_rect_equiv_spec = ToolSpec(
    name="hvac_rect_equiv_diameter",
    description=(
        "Compute the Huebscher equivalent diameter for a rectangular duct.\n"
        "\n"
        "The equivalent diameter is the round-duct diameter that gives the same "
        "friction loss per unit length at the same flow.\n"
        "\n"
        "Formula (ASHRAE Fundamentals Ch. 21, Eq. 3):\n"
        "    D_e = 1.30 × (a × b)^0.625 / (a + b)^0.25   [inches]\n"
        "\n"
        "Warns when aspect ratio exceeds 4:1 (ASHRAE guidance).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "a_in": {
                "type": "number",
                "description": "Duct width (inches). Must be > 0.",
            },
            "b_in": {
                "type": "number",
                "description": "Duct height (inches). Must be > 0.",
            },
        },
        "required": ["a_in", "b_in"],
    },
)


@register(_rect_equiv_spec, write=False)
async def run_rect_equiv_diameter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    a_in = a.get("a_in")
    b_in = a.get("b_in")
    if a_in is None:
        return json.dumps({"ok": False, "reason": "a_in is required"})
    if b_in is None:
        return json.dumps({"ok": False, "reason": "b_in is required"})

    result = rect_equiv_diameter(a_in, b_in)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_duct_friction_loss
# ---------------------------------------------------------------------------

_friction_loss_spec = ToolSpec(
    name="hvac_duct_friction_loss",
    description=(
        "Calculate Darcy-Weisbach friction pressure loss for a straight round duct.\n"
        "\n"
        "Friction factor from Colebrook-White (seeded by Swamee-Jain), "
        "consistent with the Altshul approach for sheet-metal ducts.\n"
        "\n"
        "Returns loss in in. w.g. and Pa, plus the friction rate (in. w.g./100 ft).\n"
        "Warns when velocity exceeds ASHRAE duct-velocity guidelines.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cfm": {
                "type": "number",
                "description": "Airflow (CFM). Must be > 0.",
            },
            "diameter_in": {
                "type": "number",
                "description": "Round duct inside diameter (inches). Must be > 0.",
            },
            "length_ft": {
                "type": "number",
                "description": "Duct section length (feet). Must be > 0.",
            },
            "roughness_ft": {
                "type": "number",
                "description": (
                    "Absolute roughness (feet). Default 0.00015 ft (sheet metal, "
                    "ASHRAE Table 2). Must be >= 0."
                ),
            },
        },
        "required": ["cfm", "diameter_in", "length_ft"],
    },
)


@register(_friction_loss_spec, write=False)
async def run_duct_friction_loss(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("cfm", "diameter_in", "length_ft"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "roughness_ft" in a:
        kwargs["roughness_ft"] = a["roughness_ft"]

    result = duct_friction_loss(a["cfm"], a["diameter_in"], a["length_ft"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_duct_fitting_loss
# ---------------------------------------------------------------------------

_fitting_loss_spec = ToolSpec(
    name="hvac_duct_fitting_loss",
    description=(
        "Calculate dynamic pressure loss for a single duct fitting.\n"
        "\n"
        "Formula (ASHRAE Fundamentals Ch. 21, Eq. 9):\n"
        "    ΔP = C × (V/4005)²   [in. w.g.]\n"
        "\n"
        "Typical C values:\n"
        "  90° elbow (round, radius=1.5D): 0.22\n"
        "  90° elbow (square with vanes):  0.15\n"
        "  Tee, branch:                    0.70–1.2\n"
        "  Abrupt contraction:             0.5\n"
        "  Bell-mouth entry:               0.04\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cfm": {
                "type": "number",
                "description": "Airflow through fitting (CFM). Must be > 0.",
            },
            "diameter_in": {
                "type": "number",
                "description": "Round duct diameter at fitting (inches). Must be > 0.",
            },
            "C": {
                "type": "number",
                "description": "Loss coefficient (dimensionless). Must be >= 0.",
            },
        },
        "required": ["cfm", "diameter_in", "C"],
    },
)


@register(_fitting_loss_spec, write=False)
async def run_duct_fitting_loss(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("cfm", "diameter_in", "C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = duct_fitting_loss(a["cfm"], a["diameter_in"], a["C"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_size_equal_friction
# ---------------------------------------------------------------------------

_size_ef_spec = ToolSpec(
    name="hvac_size_equal_friction",
    description=(
        "Size a round duct by the equal-friction method: find the diameter "
        "that produces the target friction rate (in. w.g./100 ft).\n"
        "\n"
        "Design friction rates (ASHRAE):\n"
        "  Low-velocity commercial    : 0.08–0.10 in. w.g./100 ft\n"
        "  Medium-velocity commercial : 0.10–0.15 in. w.g./100 ft\n"
        "\n"
        "Warns when resulting velocity exceeds ASHRAE guidelines.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cfm": {
                "type": "number",
                "description": "Airflow (CFM). Must be > 0.",
            },
            "friction_rate_in_per_100ft": {
                "type": "number",
                "description": "Target friction rate (in. w.g./100 ft). Must be > 0.",
            },
            "roughness_ft": {
                "type": "number",
                "description": "Absolute roughness (ft). Default 0.00015 ft.",
            },
        },
        "required": ["cfm", "friction_rate_in_per_100ft"],
    },
)


@register(_size_ef_spec, write=False)
async def run_size_equal_friction(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("cfm", "friction_rate_in_per_100ft"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "roughness_ft" in a:
        kwargs["roughness_ft"] = a["roughness_ft"]

    result = size_duct_equal_friction(
        a["cfm"], a["friction_rate_in_per_100ft"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_size_velocity_reduction
# ---------------------------------------------------------------------------

_size_vr_spec = ToolSpec(
    name="hvac_size_velocity_reduction",
    description=(
        "Size a duct system by the velocity-reduction method.\n"
        "\n"
        "Each section's diameter is found directly from its CFM and target velocity. "
        "Velocities decrease from trunk to branches, e.g. [1200, 900, 700, 500] fpm.\n"
        "\n"
        "Returns a list of sections, each with diameter_in and velocity_fpm.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cfm_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Airflow for each section (CFM). Each must be > 0.",
            },
            "velocity_fpm_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Target velocity for each section (fpm). Each must be > 0. "
                    "Must be same length as cfm_list."
                ),
            },
        },
        "required": ["cfm_list", "velocity_fpm_list"],
    },
)


@register(_size_vr_spec, write=False)
async def run_size_velocity_reduction(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    cfm_list = a.get("cfm_list")
    vel_list = a.get("velocity_fpm_list")
    if cfm_list is None:
        return json.dumps({"ok": False, "reason": "cfm_list is required"})
    if vel_list is None:
        return json.dumps({"ok": False, "reason": "velocity_fpm_list is required"})

    result = size_duct_velocity_reduction(cfm_list, vel_list)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_branch_static_pressure
# ---------------------------------------------------------------------------

_branch_sp_spec = ToolSpec(
    name="hvac_branch_static_pressure",
    description=(
        "Calculate total static pressure for a duct branch path.\n"
        "\n"
        "Sums straight-duct friction losses and fitting dynamic losses for each "
        "section from fan to terminal.  The result is the minimum required fan "
        "static pressure for that branch.\n"
        "\n"
        "Each section object:\n"
        "  cfm         : float (required) — airflow (CFM)\n"
        "  diameter_in : float (required) — round duct diameter (inches)\n"
        "  length_ft   : float (required) — straight duct length (feet)\n"
        "  fittings    : list of {C: float, diameter_in: float (optional)}\n"
        "  roughness_ft: float (optional, default 0.00015 ft)\n"
        "\n"
        "Returns total_static_pressure_in_wg and Pa, plus per-section breakdown.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cfm": {"type": "number"},
                        "diameter_in": {"type": "number"},
                        "length_ft": {"type": "number"},
                        "roughness_ft": {"type": "number"},
                        "fittings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "C": {"type": "number"},
                                    "diameter_in": {"type": "number"},
                                },
                                "required": ["C"],
                            },
                        },
                    },
                    "required": ["cfm", "diameter_in", "length_ft"],
                },
                "description": "Ordered list of duct sections from fan to terminal.",
            },
        },
        "required": ["sections"],
    },
)


@register(_branch_sp_spec, write=False)
async def run_branch_static_pressure(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    secs = a.get("sections")
    if secs is None:
        return json.dumps({"ok": False, "reason": "sections is required"})

    result = branch_static_pressure(secs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hvac_fan_law_scale
# ---------------------------------------------------------------------------

_fan_law_spec = ToolSpec(
    name="hvac_fan_law_scale",
    description=(
        "Scale fan performance to a new airflow using fan-law affinity laws.\n"
        "\n"
        "Assumes the same fan at changed speed (or geometrically similar fan):\n"
        "    SP₂  = SP₁  × (CFM₂/CFM₁)²\n"
        "    BHP₂ = BHP₁ × (CFM₂/CFM₁)³\n"
        "\n"
        "Warns when speed ratio > 1.2 (fan-law accuracy degrades) or < 0.5.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cfm1": {
                "type": "number",
                "description": "Original airflow (CFM). Must be > 0.",
            },
            "sp1": {
                "type": "number",
                "description": "Original static pressure (in. w.g.). Must be > 0.",
            },
            "bhp1": {
                "type": "number",
                "description": "Original brake horsepower (BHP). Must be > 0.",
            },
            "cfm2": {
                "type": "number",
                "description": "New target airflow (CFM). Must be > 0.",
            },
        },
        "required": ["cfm1", "sp1", "bhp1", "cfm2"],
    },
)


@register(_fan_law_spec, write=False)
async def run_fan_law_scale(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("cfm1", "sp1", "bhp1", "cfm2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = fan_law_scale(a["cfm1"], a["sp1"], a["bhp1"], a["cfm2"])
    return ok_payload(result)
