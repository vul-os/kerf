"""
kerf_cad_core.spillway.tools — LLM tool wrappers for dam & spillway hydraulics.

Registers ten tools with the Kerf tool registry:

  spillway_ogee_discharge        — WES ogee spillway Q with C correction, contractions, submergence
  spillway_ogee_crest_profile    — WES standard crest (x, y) coordinate table
  spillway_orifice_discharge     — gated / submerged orifice discharge
  spillway_chute_velocity        — chute normal depth, terminal velocity, downstream velocity
  spillway_stilling_basin        — USBR Type I–IV selection, sequent depth, basin length
  spillway_energy_dissipation    — energy at toe, required apron length
  spillway_scour_depth           — downstream scour depth (Lacey / Mason)
  spillway_flood_routing_puls    — modified-Puls level-pool reservoir routing
  spillway_dam_freeboard         — wind setup + wave runup freeboard requirement
  spillway_gravity_dam_stability — overturning / sliding / uplift / middle-third check

All tools are pure-Python; no OCC dependency.
Errors → {"ok": False, "reason": ...} — tools never raise.

Units: SI (metres, m³/s, seconds) throughout.

References
----------
USBR (1977) Design of Small Dams, 3rd ed.
US Army Corps of Engineers EM 1110-2-1601 (1994).
Chaudhry, M.H. (2008) Open-Channel Hydraulics, 2nd ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.spillway.design import (
    ogee_discharge,
    ogee_crest_profile,
    orifice_discharge,
    chute_velocity,
    stilling_basin,
    energy_dissipation,
    scour_depth,
    flood_routing_puls,
    dam_freeboard,
    gravity_dam_stability,
)


# ---------------------------------------------------------------------------
# Tool: spillway_ogee_discharge
# ---------------------------------------------------------------------------

_ogee_discharge_spec = ToolSpec(
    name="spillway_ogee_discharge",
    description=(
        "Compute discharge over a WES standard ogee (overflow) spillway crest.\n"
        "\n"
        "Basic formula:  Q = C · L_eff · He^1.5\n"
        "\n"
        "The discharge coefficient C is automatically adjusted for:\n"
        "  - Head ratio He/Hd  (WES head-correction factor)\n"
        "  - Approach-velocity head  (added to He)\n"
        "  - End contractions  (reduce effective length L_eff by 0.1·n·He)\n"
        "  - Submergence  (Villemonte 1947 when tailwater > 0)\n"
        "\n"
        "Returns discharge_m3s, C_effective, L_eff_m, He_m (total energy head),\n"
        "approach_velocity_head_m, submergence_ratio, submergence_factor, warnings.\n"
        "\n"
        "Warnings issued for:\n"
        "  - He/Hd > 1.33 (cavitation risk)\n"
        "  - He/Hd < 0.50 (sub-atmospheric pressure on crest)\n"
        "  - High submergence (> 0.7)\n"
        "\n"
        "Reference: USBR Design of Small Dams (1977), Fig. 9-21.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "design_head_m": {
                "type": "number",
                "description": "Design head Hd (m) for which the crest was optimised.  Must be > 0.",
            },
            "actual_head_m": {
                "type": "number",
                "description": "Actual operating head He (m) above crest.  Must be > 0.",
            },
            "crest_length_m": {
                "type": "number",
                "description": "Gross crest length L (m).  Must be > 0.",
            },
            "approach_depth_m": {
                "type": "number",
                "description": (
                    "Approach channel depth P (m) from crest datum.  "
                    "Used to compute approach-velocity head.  Default 0 (ignore)."
                ),
            },
            "num_end_contractions": {
                "type": "integer",
                "enum": [0, 1, 2],
                "description": "Number of end pier contractions (0, 1, or 2).  Default 0.",
            },
            "tailwater_m": {
                "type": "number",
                "description": "Tailwater elevation above crest (m).  > 0 = submerged.  Default 0.",
            },
            "C0": {
                "type": "number",
                "description": (
                    "Base discharge coefficient at design head (SI m^0.5/s).  "
                    "Default 2.21 (USBR).  Metric: 2.18.  US customary: 3.97."
                ),
            },
        },
        "required": ["design_head_m", "actual_head_m", "crest_length_m"],
    },
)


@register(_ogee_discharge_spec, write=False)
async def run_spillway_ogee_discharge(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("design_head_m", "actual_head_m", "crest_length_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    for key in ("approach_depth_m", "tailwater_m", "C0"):
        if key in a:
            kwargs[key] = float(a[key])
    if "num_end_contractions" in a:
        kwargs["num_end_contractions"] = int(a["num_end_contractions"])

    result = ogee_discharge(
        float(a["design_head_m"]),
        float(a["actual_head_m"]),
        float(a["crest_length_m"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_ogee_crest_profile
# ---------------------------------------------------------------------------

_ogee_profile_spec = ToolSpec(
    name="spillway_ogee_crest_profile",
    description=(
        "Generate (x, y) coordinates of a WES standard ogee crest profile.\n"
        "\n"
        "Downstream quadrant (x ≥ 0):  y/Hd = −0.5 · (x/Hd)^1.85\n"
        "Upstream quadrant: circular-arc approximation (R = 0.5·Hd).\n"
        "Origin at crest apex; positive x is downstream, positive y is upward.\n"
        "\n"
        "Returns design_head_m and profile (list of {x_m, y_m}).\n"
        "\n"
        "Reference: USBR Design of Small Dams (1977), Fig. 9-7;\n"
        "USACE EM 1110-2-1603.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "design_head_m": {
                "type": "number",
                "description": "Design head Hd (m).  Must be > 0.",
            },
            "n_upstream": {
                "type": "integer",
                "description": "Number of upstream profile points (default 10).",
            },
            "n_downstream": {
                "type": "integer",
                "description": "Number of downstream profile points (default 40).",
            },
        },
        "required": ["design_head_m"],
    },
)


@register(_ogee_profile_spec, write=False)
async def run_spillway_ogee_crest_profile(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("design_head_m") is None:
        return json.dumps({"ok": False, "reason": "design_head_m is required"})

    kwargs: dict = {}
    if "n_upstream" in a:
        kwargs["n_upstream"] = int(a["n_upstream"])
    if "n_downstream" in a:
        kwargs["n_downstream"] = int(a["n_downstream"])

    result = ogee_crest_profile(float(a["design_head_m"]), **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_orifice_discharge
# ---------------------------------------------------------------------------

_orifice_spec = ToolSpec(
    name="spillway_orifice_discharge",
    description=(
        "Compute discharge through a gated or submerged orifice spillway gate.\n"
        "\n"
        "Free-flow:    Q = Cd · a · W · sqrt(2g · (Hu − a/2))\n"
        "Submerged:    Q = Cd · a · W · sqrt(2g · (Hu − Hd))\n"
        "\n"
        "Flow condition switches to 'submerged' when tailwater > gate opening.\n"
        "\n"
        "Returns discharge_m3s, velocity_m_s, gate_area_m2,\n"
        "effective_head_m, flow_condition ('free'|'submerged'|'reverse'), warnings.\n"
        "\n"
        "Reference: USBR Design of Small Dams (1977).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gate_opening_m": {
                "type": "number",
                "description": "Gate opening height a (m).  Must be > 0.",
            },
            "gate_width_m": {
                "type": "number",
                "description": "Gate width W (m).  Must be > 0.",
            },
            "head_upstream_m": {
                "type": "number",
                "description": "Upstream head above gate sill (m).  Must be > 0.",
            },
            "head_downstream_m": {
                "type": "number",
                "description": "Downstream (tailwater) head above gate sill (m).  Default 0.",
            },
            "Cd": {
                "type": "number",
                "description": (
                    "Discharge coefficient (default 0.61 for sharp-crested orifice; "
                    "0.74–0.80 for radial/drum gates)."
                ),
            },
            "gate_type": {
                "type": "string",
                "enum": ["sluice", "radial", "drum"],
                "description": "Gate type (informational).  Default 'sluice'.",
            },
        },
        "required": ["gate_opening_m", "gate_width_m", "head_upstream_m"],
    },
)


@register(_orifice_spec, write=False)
async def run_spillway_orifice_discharge(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("gate_opening_m", "gate_width_m", "head_upstream_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    for key in ("head_downstream_m", "Cd"):
        if key in a:
            kwargs[key] = float(a[key])
    if "gate_type" in a:
        kwargs["gate_type"] = str(a["gate_type"])

    result = orifice_discharge(
        float(a["gate_opening_m"]),
        float(a["gate_width_m"]),
        float(a["head_upstream_m"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_chute_velocity
# ---------------------------------------------------------------------------

_chute_spec = ToolSpec(
    name="spillway_chute_velocity",
    description=(
        "Compute normal (terminal) depth and velocity in a rectangular spillway chute.\n"
        "\n"
        "Manning's equation for the rectangular cross-section is solved by bisection "
        "to find the normal depth and terminal (uniform-flow) velocity.\n"
        "\n"
        "If chute_length_m is provided, the downstream velocity is estimated by\n"
        "energy conservation:  V_ds = sqrt(V_n² + 2g·L·S).\n"
        "\n"
        "Returns normal_depth_m, terminal_velocity_m_s, froude_number,\n"
        "flow_area_m2, hydraulic_radius_m,\n"
        "downstream_velocity_m_s (if chute_length_m provided), warnings.\n"
        "\n"
        "Warnings: supercritical chute (Fr > 1.5), steep slope (S > 0.3),\n"
        "high downstream velocity (> 30 m/s).\n"
        "\n"
        "Reference: Chaudhry (2008) Open-Channel Hydraulics.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "flow_m3s": {
                "type": "number",
                "description": "Design discharge Q (m³/s).  Must be > 0.",
            },
            "chute_width_m": {
                "type": "number",
                "description": "Chute width W (m).  Must be > 0.",
            },
            "chute_slope": {
                "type": "number",
                "description": "Longitudinal slope S (m/m).  Must be > 0.",
            },
            "manning_n": {
                "type": "number",
                "description": "Manning's roughness n (default ~0.015 for concrete).",
            },
            "chute_length_m": {
                "type": "number",
                "description": "Chute length (m) for downstream velocity estimate.  0 = skip.",
            },
        },
        "required": ["flow_m3s", "chute_width_m", "chute_slope", "manning_n"],
    },
)


@register(_chute_spec, write=False)
async def run_spillway_chute_velocity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("flow_m3s", "chute_width_m", "chute_slope", "manning_n"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "chute_length_m" in a:
        kwargs["chute_length_m"] = float(a["chute_length_m"])

    result = chute_velocity(
        float(a["flow_m3s"]),
        float(a["chute_width_m"]),
        float(a["chute_slope"]),
        float(a["manning_n"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_stilling_basin
# ---------------------------------------------------------------------------

_stilling_basin_spec = ToolSpec(
    name="spillway_stilling_basin",
    description=(
        "Design a USBR stilling basin for hydraulic-jump energy dissipation.\n"
        "\n"
        "Computes Froude number Fr1, sequent depth y2 (Bélanger equation),\n"
        "USBR basin type, basin length, end-sill height, and tailwater match.\n"
        "\n"
        "USBR Type selection:\n"
        "  Type I   : Fr1 > 4.5 (standard jump; floor protection only)\n"
        "  Type II  : Fr1 2.5–4.5 (chute blocks + end sill)\n"
        "  Type III : Fr1 4.5–9  (chute blocks + baffle piers + end sill)\n"
        "  Type IV  : Fr1 1.7–2.5 (wave suppressors; oscillating jump)\n"
        "  undular  : Fr1 < 1.7  (jump may not form)\n"
        "\n"
        "Warnings: jump sweepout (TW < y2), submerged jump (TW > 1.1·y2),\n"
        "undular / oscillating flow.\n"
        "\n"
        "Reference: USBR Design of Small Dams (1977), p. 213.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "upstream_depth_m": {
                "type": "number",
                "description": "Flow depth y1 at jump toe (m).  Must be > 0.",
            },
            "flow_m3s": {
                "type": "number",
                "description": "Total discharge Q (m³/s).  Must be > 0.",
            },
            "chute_width_m": {
                "type": "number",
                "description": "Basin width W (m).  Must be > 0.",
            },
            "tailwater_depth_m": {
                "type": "number",
                "description": "Tailwater depth TW (m) from basin floor.  Must be >= 0.",
            },
            "elevation_drop_m": {
                "type": "number",
                "description": "Available energy head for floor depression (m).  Default 0.",
            },
        },
        "required": ["upstream_depth_m", "flow_m3s", "chute_width_m", "tailwater_depth_m"],
    },
)


@register(_stilling_basin_spec, write=False)
async def run_spillway_stilling_basin(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("upstream_depth_m", "flow_m3s", "chute_width_m", "tailwater_depth_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "elevation_drop_m" in a:
        kwargs["elevation_drop_m"] = float(a["elevation_drop_m"])

    result = stilling_basin(
        float(a["upstream_depth_m"]),
        float(a["flow_m3s"]),
        float(a["chute_width_m"]),
        float(a["tailwater_depth_m"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_energy_dissipation
# ---------------------------------------------------------------------------

_energy_diss_spec = ToolSpec(
    name="spillway_energy_dissipation",
    description=(
        "Compute energy at the spillway toe and required apron / stilling-basin length.\n"
        "\n"
        "Energy at toe:  E_toe = y_ds + V_toe²/(2g)\n"
        "  V_toe = sqrt(2g · (H_up − y_ds))  (energy conservation)\n"
        "\n"
        "Returns energy_at_toe_m, velocity_at_toe_m_s, froude_at_toe,\n"
        "energy_available_for_dissipation_m, apron_length_m (basin + protection),\n"
        "basin_length_m, downstream_protection_length_m, warnings.\n"
        "\n"
        "Reference: USBR 6·y2 basin rule.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "upstream_head_m": {
                "type": "number",
                "description": "Total upstream head above apron floor (m).  Must be > 0.",
            },
            "downstream_depth_m": {
                "type": "number",
                "description": "Normal depth in downstream channel (m).  Must be > 0.",
            },
            "flow_m3s": {
                "type": "number",
                "description": "Discharge Q (m³/s).  Must be > 0.",
            },
            "basin_width_m": {
                "type": "number",
                "description": "Basin / apron width W (m).  Must be > 0.",
            },
            "basin_roughness_n": {
                "type": "number",
                "description": "Manning's n for apron surface (default 0.015).",
            },
        },
        "required": ["upstream_head_m", "downstream_depth_m", "flow_m3s", "basin_width_m"],
    },
)


@register(_energy_diss_spec, write=False)
async def run_spillway_energy_dissipation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("upstream_head_m", "downstream_depth_m", "flow_m3s", "basin_width_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "basin_roughness_n" in a:
        kwargs["basin_roughness_n"] = float(a["basin_roughness_n"])

    result = energy_dissipation(
        float(a["upstream_head_m"]),
        float(a["downstream_depth_m"]),
        float(a["flow_m3s"]),
        float(a["basin_width_m"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_scour_depth
# ---------------------------------------------------------------------------

_scour_spec = ToolSpec(
    name="spillway_scour_depth",
    description=(
        "Estimate scour depth downstream of a dam or energy dissipator.\n"
        "\n"
        "Two methods:\n"
        "  'lacey' (default) — regime scour: d_s = 0.47·(Q/f)^(1/3)\n"
        "    Lacey silt factor f = 1.76·sqrt(d50_mm).\n"
        "    Suitable for rivers with alluvial beds.\n"
        "  'mason' — Mason & Arumugam (1985) plunge-pool scour:\n"
        "    d_s = 1.9·Q^0.6·H^0.5/d50^0.06\n"
        "    Requires head_drop_m.  Suitable for ski-jump / plunge pool.\n"
        "\n"
        "Returns scour_depth_m, method, unit_discharge_m2s,\n"
        "lacey_silt_factor (lacey only), warnings.\n"
        "\n"
        "Reference: Lacey (1930); Mason & Arumugam (1985).  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "flow_m3s": {
                "type": "number",
                "description": "Discharge Q (m³/s).  Must be > 0.",
            },
            "channel_width_m": {
                "type": "number",
                "description": "Channel width W (m).  Must be > 0.",
            },
            "d50_mm": {
                "type": "number",
                "description": "Median grain size d50 (mm).  Must be > 0.",
            },
            "method": {
                "type": "string",
                "enum": ["lacey", "mason"],
                "description": "Scour method: 'lacey' (default) or 'mason'.",
            },
            "head_drop_m": {
                "type": "number",
                "description": "Total head drop (m).  Required for 'mason' method.",
            },
        },
        "required": ["flow_m3s", "channel_width_m", "d50_mm"],
    },
)


@register(_scour_spec, write=False)
async def run_spillway_scour_depth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("flow_m3s", "channel_width_m", "d50_mm"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "method" in a:
        kwargs["method"] = str(a["method"])
    if "head_drop_m" in a:
        kwargs["head_drop_m"] = float(a["head_drop_m"])

    result = scour_depth(
        float(a["flow_m3s"]),
        float(a["channel_width_m"]),
        float(a["d50_mm"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_flood_routing_puls
# ---------------------------------------------------------------------------

_puls_spec = ToolSpec(
    name="spillway_flood_routing_puls",
    description=(
        "Route a flood hydrograph through a reservoir using the modified-Puls "
        "(level-pool) method.\n"
        "\n"
        "Routing equation (per time step):\n"
        "  (2S_n/Δt + Q_n) + I_n + I_{n+1} = 2S_{n+1}/Δt + Q_{n+1}\n"
        "\n"
        "The storage-discharge relationship is provided as a table; outflow Q "
        "is interpolated from storage S by bisection.\n"
        "\n"
        "Parameters:\n"
        "  inflow_hydrograph        — list of [t_s, I_m3s] pairs\n"
        "  storage_discharge_pairs  — list of [S_m3, Q_m3s] pairs\n"
        "  dt_s                     — routing time step (s)\n"
        "\n"
        "Returns outflow_hydrograph (list of {t_s, outflow_m3s, storage_m3}),\n"
        "peak_outflow_m3s, peak_outflow_time_s, peak_storage_m3,\n"
        "attenuation_m3s, warnings.\n"
        "\n"
        "Reference: Chaudhry (2008) Open-Channel Hydraulics, §10-4.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "inflow_hydrograph": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": (
                    "Inflow hydrograph as list of [time_s, inflow_m3s] pairs.  "
                    "Time must be strictly increasing.  Minimum 2 points."
                ),
            },
            "storage_discharge_pairs": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": (
                    "Storage-discharge table as list of [storage_m3, discharge_m3s] pairs.  "
                    "Storage must be strictly increasing.  Minimum 2 points."
                ),
            },
            "dt_s": {
                "type": "number",
                "description": "Routing time step (s).  Must be > 0.",
            },
            "initial_storage_m3": {
                "type": "number",
                "description": "Initial reservoir storage at start of routing (m³).  Default 0.",
            },
        },
        "required": ["inflow_hydrograph", "storage_discharge_pairs", "dt_s"],
    },
)


@register(_puls_spec, write=False)
async def run_spillway_flood_routing_puls(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("inflow_hydrograph", "storage_discharge_pairs", "dt_s"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    try:
        hydro = [tuple(p) for p in a["inflow_hydrograph"]]
        sd = [tuple(p) for p in a["storage_discharge_pairs"]]
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid list format: {exc}"})

    kwargs: dict = {}
    if "initial_storage_m3" in a:
        kwargs["initial_storage_m3"] = float(a["initial_storage_m3"])

    result = flood_routing_puls(hydro, sd, float(a["dt_s"]), **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_dam_freeboard
# ---------------------------------------------------------------------------

_freeboard_spec = ToolSpec(
    name="spillway_dam_freeboard",
    description=(
        "Estimate required dam freeboard from wind setup and wave runup.\n"
        "\n"
        "Significant wave height (Bretschneider/SMB):\n"
        "  Hs = 0.0248 · U² · F^0.5   (U in m/s, F in km)\n"
        "Wind setup:\n"
        "  Sw = U² · F / (61000 · d)  (d = reservoir depth, m)\n"
        "Wave runup:\n"
        "  Ru ≈ 2.0 · Hs / sqrt(H:V slope)\n"
        "Required freeboard = Sw + Ru + safety_margin\n"
        "\n"
        "Returns significant_wave_height_m, wave_period_s, wind_setup_m,\n"
        "wave_runup_m, required_freeboard_m, warnings.\n"
        "\n"
        "Warnings: inadequate freeboard (< 1.0 m), large waves (Hs > 1.5 m),\n"
        "extreme wind speed (> 35 m/s).\n"
        "\n"
        "Reference: USBR Design of Small Dams (1977); Linsley & Franzini (1979).\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reservoir_fetch_km": {
                "type": "number",
                "description": "Effective fetch F (km).  Must be > 0.",
            },
            "wind_speed_m_s": {
                "type": "number",
                "description": "Design wind speed U (m/s).  Must be > 0.  Typical: 20–40 m/s.",
            },
            "dam_height_m": {
                "type": "number",
                "description": "Dam height above foundation (m).  Must be > 0.",
            },
            "reservoir_depth_m": {
                "type": "number",
                "description": "Average reservoir depth (m).  Default 10.",
            },
            "embankment_slope_v_to_h": {
                "type": "number",
                "description": (
                    "Upstream slope expressed as horizontal:vertical ratio H:V "
                    "(e.g. 3 means 3H:1V, slope = 1/3).  Default 3."
                ),
            },
            "freeboard_safety_m": {
                "type": "number",
                "description": "Additional safety margin (m).  Default 0.5.",
            },
        },
        "required": ["reservoir_fetch_km", "wind_speed_m_s", "dam_height_m"],
    },
)


@register(_freeboard_spec, write=False)
async def run_spillway_dam_freeboard(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("reservoir_fetch_km", "wind_speed_m_s", "dam_height_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    for key in ("reservoir_depth_m", "embankment_slope_v_to_h", "freeboard_safety_m"):
        if key in a:
            kwargs[key] = float(a[key])

    result = dam_freeboard(
        float(a["reservoir_fetch_km"]),
        float(a["wind_speed_m_s"]),
        float(a["dam_height_m"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spillway_gravity_dam_stability
# ---------------------------------------------------------------------------

_dam_stability_spec = ToolSpec(
    name="spillway_gravity_dam_stability",
    description=(
        "Gravity-dam stability quick-check per USBR / ICOLD criteria.\n"
        "\n"
        "Checks per unit length of dam (default 1 m):\n"
        "  1. Overturning:  FOS = RM / OTM  ≥ 1.5 recommended\n"
        "  2. Uplift:  U = α · γ_w · (Hu + Hd)/2 · B\n"
        "  3. Sliding:  FOS = (μ · (W − U) + Ph_ds) / Ph  ≥ 1.0 min\n"
        "  4. Middle-third rule:  eccentricity e ≤ B/6\n"
        "\n"
        "Simplified rectangular section.  Silt, seismic, and tension crack\n"
        "not included.\n"
        "\n"
        "Returns weight_kN, uplift_kN, net_vertical_kN,\n"
        "horizontal_hydrostatic_kN, overturning_moment_kNm, resisting_moment_kNm,\n"
        "FOS_overturning, FOS_sliding, eccentricity_m, base_width_m,\n"
        "middle_third_ok, stable, warnings.\n"
        "\n"
        "Warnings: FOS_overturning < 1.5, FOS_sliding < 1.5 / < 1.0 (critical),\n"
        "eccentricity outside middle third, overtopping.\n"
        "\n"
        "Reference: USBR Design of Small Dams (1977); ICOLD Bulletin 167.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dam_height_m": {
                "type": "number",
                "description": "Dam height H (m).  Must be > 0.",
            },
            "dam_base_width_m": {
                "type": "number",
                "description": "Base width B (m).  Must be > 0.",
            },
            "upstream_water_depth_m": {
                "type": "number",
                "description": "Upstream water depth above foundation (m).  Must be > 0.",
            },
            "concrete_density_kg_m3": {
                "type": "number",
                "description": "Concrete unit weight (kg/m³).  Default 2400.",
            },
            "downstream_water_depth_m": {
                "type": "number",
                "description": "Downstream tailwater depth (m).  Default 0.",
            },
            "uplift_fraction": {
                "type": "number",
                "description": (
                    "Uplift intensity factor α (0–1).  "
                    "0.667 = drains at 1/3 from heel; 1.0 = no drainage.  Default 0.667."
                ),
            },
            "friction_coefficient": {
                "type": "number",
                "description": "Base sliding friction coefficient μ.  Default 0.75 (concrete on rock).",
            },
            "unit_length_m": {
                "type": "number",
                "description": "Unit dam length analysed (m).  Default 1.",
            },
            "crest_width_m": {
                "type": "number",
                "description": "Crest width (m).  Default: max(0.15·H, 0.1·B).",
            },
        },
        "required": ["dam_height_m", "dam_base_width_m", "upstream_water_depth_m"],
    },
)


@register(_dam_stability_spec, write=False)
async def run_spillway_gravity_dam_stability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for f in ("dam_height_m", "dam_base_width_m", "upstream_water_depth_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    for key in (
        "concrete_density_kg_m3",
        "downstream_water_depth_m",
        "uplift_fraction",
        "friction_coefficient",
        "unit_length_m",
        "crest_width_m",
    ):
        if key in a:
            kwargs[key] = float(a[key])

    result = gravity_dam_stability(
        float(a["dam_height_m"]),
        float(a["dam_base_width_m"]),
        float(a["upstream_water_depth_m"]),
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)
