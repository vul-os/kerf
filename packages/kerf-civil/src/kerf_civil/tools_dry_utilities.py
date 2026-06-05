"""
tools_dry_utilities.py — LLM tools for dry-utility network design.

Exposes:
  civil_dry_utility_network_create  — build a DryUtilityNetwork from JSON nodes/links
  civil_dry_utility_clearance_check — detect separation + cover violations
  civil_gas_pressure_drop           — Weymouth (compressible) or Darcy-Weisbach
  civil_elec_duct_fill              — NEC conduit fill-ratio check
"""
from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_civil._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Tool: civil_dry_utility_network_create
# ---------------------------------------------------------------------------

civil_dry_utility_network_create_spec = ToolSpec(
    name="civil_dry_utility_network_create",
    description=(
        "Build and validate a dry-utility network (gas, electrical, telecom) from "
        "structured node and link data.\n"
        "\n"
        "A 'dry utility' is any underground utility that does not carry liquids: "
        "gas distribution/transmission mains, electrical duct banks, and "
        "telecom/fiber conduits. This is distinct from 'wet utilities' (water mains, "
        "sewers) handled by civil_water_network_solve / civil_gravity_network_solve.\n"
        "\n"
        "Node fields:\n"
        "  id           : str  — unique identifier\n"
        "  x, y         : float — plan position [m]\n"
        "  z_surface_m  : float — finished-grade elevation [m]\n"
        "  node_type    : str  — 'manhole' | 'handhole' | 'valve' | 'regulator' | 'splice'\n"
        "\n"
        "Link fields:\n"
        "  id              : str\n"
        "  node_from       : str  — start node ID\n"
        "  node_to         : str  — end node ID\n"
        "  length_m        : float\n"
        "  depth_of_cover_m: float — cover from finished grade to top of pipe/conduit\n"
        "  corridor_offset_m: float — lateral offset from road CL or reference line\n"
        "  wet_utility_offset_m : float (optional) — measured separation to nearest wet utility\n"
        "  asset: {\n"
        "    kind: 'gas' | 'electrical' | 'telecom'\n"
        "    -- Gas --\n"
        "    diameter_mm, material ('PE'/'steel'/'CI'), mop_kPa, roughness_mm (opt)\n"
        "    -- Electrical --\n"
        "    conduit_id_mm, n_conduits, voltage_class ('LV'/'MV'/'HV'), cables_per_conduit\n"
        "    -- Telecom --\n"
        "    conduit_id_mm, n_conduits, fiber_count (opt)\n"
        "  }\n"
        "\n"
        "Returns:\n"
        "  ok          : bool\n"
        "  n_nodes     : int\n"
        "  n_links     : int\n"
        "  asset_kinds : dict — count of gas/electrical/telecom links\n"
        "  summary     : str\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "description": "List of utility-network node dicts.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":           {"type": "string"},
                        "x":            {"type": "number"},
                        "y":            {"type": "number"},
                        "z_surface_m":  {"type": "number"},
                        "node_type":    {"type": "string"},
                    },
                    "required": ["id", "x", "y", "z_surface_m"],
                },
            },
            "links": {
                "type": "array",
                "description": "List of corridor link dicts.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":                  {"type": "string"},
                        "node_from":           {"type": "string"},
                        "node_to":             {"type": "string"},
                        "length_m":            {"type": "number"},
                        "depth_of_cover_m":    {"type": "number"},
                        "corridor_offset_m":   {"type": "number"},
                        "wet_utility_offset_m":{"type": "number"},
                        "asset":               {"type": "object"},
                    },
                    "required": ["id", "node_from", "node_to", "length_m",
                                 "depth_of_cover_m", "corridor_offset_m", "asset"],
                },
            },
        },
        "required": ["nodes", "links"],
    },
)


async def run_civil_dry_utility_network_create(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.dry_utilities import build_network, DryUtilityKind

        nodes = params.get("nodes", [])
        links = params.get("links", [])

        net = build_network(nodes, links)

        # Count assets
        asset_counts: dict[str, int] = {k.value: 0 for k in DryUtilityKind}
        for lk in net.links:
            asset_counts[lk.asset.kind] += 1

        return ok_payload({
            "ok": True,
            "n_nodes": len(net.nodes),
            "n_links": len(net.links),
            "asset_kinds": asset_counts,
            "summary": (
                f"{len(net.nodes)} nodes, {len(net.links)} links "
                f"({asset_counts['gas']} gas, {asset_counts['electrical']} electrical, "
                f"{asset_counts['telecom']} telecom)"
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_DRY_UTIL_CREATE_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_dry_utility_clearance_check
# ---------------------------------------------------------------------------

civil_dry_utility_clearance_check_spec = ToolSpec(
    name="civil_dry_utility_clearance_check",
    description=(
        "Detect separation and cover-depth violations in a dry-utility corridor.\n"
        "\n"
        "Checks applied:\n"
        "  1. Cover depth — minimum cover per asset kind:\n"
        "       Gas:           600 mm (ASME B31.8 §841.1)\n"
        "       Elec HV/MV:   600 mm (NEC Table 300.5)\n"
        "       Elec LV:      450 mm (NEC Table 300.5)\n"
        "       Telecom:      450 mm (Telcordia GR-771)\n"
        "  2. Inter-utility separation — lateral offset between co-routed utilities:\n"
        "       Gas ↔ Electrical:   ≥ 300 mm (NFPA 54 / IGEM PL2)\n"
        "       Gas ↔ Telecom:      ≥ 300 mm (IGEM PL2)\n"
        "       Electrical ↔ Telecom: ≥ 300 mm (NEC Art 800)\n"
        "  3. Wet-utility separation — if wet_utility_offset_m supplied per link:\n"
        "       Any dry ↔ water/sewer: ≥ 300 mm (AWWA M23 §7.5)\n"
        "\n"
        "Input: same nodes + links as civil_dry_utility_network_create.\n"
        "Additionally accepts:\n"
        "  global_wet_utility_offset_m : float (optional) — applied to all links\n"
        "    lacking a per-link wet_utility_offset_m value.\n"
        "\n"
        "Returns:\n"
        "  ok              : bool\n"
        "  n_violations    : int\n"
        "  violations      : list — per-violation dicts:\n"
        "      violation_type, link_id, link_id_b (if pair), required_m,\n"
        "      actual_m, deficit_m, description\n"
        "  clearance_ok    : bool — true iff n_violations == 0\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Utility network nodes (same schema as civil_dry_utility_network_create).",
            },
            "links": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Corridor links (same schema as civil_dry_utility_network_create).",
            },
            "global_wet_utility_offset_m": {
                "type": "number",
                "description": (
                    "Global measured separation (m) from all dry utilities to nearest "
                    "wet utility, applied to links without their own wet_utility_offset_m."
                ),
            },
        },
        "required": ["nodes", "links"],
    },
)


async def run_civil_dry_utility_clearance_check(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.dry_utilities import build_network, check_corridor_clearances

        nodes = params.get("nodes", [])
        links = params.get("links", [])
        global_wet = params.get("global_wet_utility_offset_m")

        net = build_network(nodes, links)
        violations = check_corridor_clearances(
            net,
            wet_utility_offset_m=global_wet,
        )

        return ok_payload({
            "ok": True,
            "n_violations": len(violations),
            "violations": violations,
            "clearance_ok": len(violations) == 0,
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_DRY_UTIL_CLEARANCE_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_gas_pressure_drop
# ---------------------------------------------------------------------------

civil_gas_pressure_drop_spec = ToolSpec(
    name="civil_gas_pressure_drop",
    description=(
        "Compute gas pressure drop in a distribution or transmission main.\n"
        "\n"
        "Two solver options:\n"
        "\n"
        "  'weymouth' (default) — Weymouth (1912) compressible steady-state equation.\n"
        "      Suited for transmission and intermediate-pressure mains.\n"
        "      Reference: Menon (2005) Gas Pipeline Hydraulics, CRC Press, §3.3.\n"
        "\n"
        "  'darcy' — Darcy-Weisbach with Swamee-Jain friction factor (1976).\n"
        "      Incompressible approximation — suitable for low-pressure (<7 kPa)\n"
        "      distribution networks.\n"
        "      Reference: Swamee & Jain (1976) J. Hydraulics Div. ASCE 102(5).\n"
        "\n"
        "Parameters:\n"
        "  solver        : 'weymouth' | 'darcy'  (default: 'weymouth')\n"
        "  Q_m3s         : volumetric flow [m³/s std conditions]\n"
        "  D_m           : pipe inside diameter [m]\n"
        "  L_m           : pipe segment length [m]\n"
        "  P1_kPa        : upstream absolute pressure [kPa]\n"
        "\n"
        "Weymouth-only:\n"
        "  T_K           : average gas temperature [K] (default 288.15)\n"
        "  SG            : specific gravity vs air (default 0.6 for natural gas)\n"
        "  efficiency    : pipeline efficiency E, 0–1 (default 1.0)\n"
        "  Z             : compressibility factor (default 1.0)\n"
        "\n"
        "Darcy-only:\n"
        "  mu_Pa_s       : dynamic viscosity [Pa·s] (default 1.1e-5)\n"
        "  rho_kg_m3     : gas density at line conditions [kg/m³] (default 0.72)\n"
        "  roughness_m   : pipe wall roughness [m] (default 4.6e-5 for steel)\n"
        "\n"
        "Returns:\n"
        "  ok           : bool\n"
        "  solver       : str\n"
        "  P2_kPa       : downstream pressure [kPa]  (Weymouth only)\n"
        "  dP_kPa       : pressure drop [kPa]\n"
        "  dP_bar       : pressure drop [bar]\n"
        "  velocity_m_s : average flow velocity [m/s]\n"
        "  reynolds     : Reynolds number\n"
        "  regime       : 'laminar' | 'turbulent'\n"
        "  warnings     : list[str]\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "solver":     {"type": "string", "enum": ["weymouth", "darcy"], "default": "weymouth"},
            "Q_m3s":      {"type": "number", "description": "Volumetric flow rate [m³/s std]."},
            "D_m":        {"type": "number", "description": "Pipe inside diameter [m]."},
            "L_m":        {"type": "number", "description": "Pipe length [m]."},
            "P1_kPa":     {"type": "number", "description": "Upstream absolute pressure [kPa]."},
            "T_K":        {"type": "number", "default": 288.15},
            "SG":         {"type": "number", "default": 0.6},
            "efficiency": {"type": "number", "default": 1.0},
            "Z":          {"type": "number", "default": 1.0},
            "mu_Pa_s":    {"type": "number", "default": 1.1e-5},
            "rho_kg_m3":  {"type": "number", "default": 0.72},
            "roughness_m":{"type": "number", "default": 4.6e-5},
        },
        "required": ["Q_m3s", "D_m", "L_m", "P1_kPa"],
    },
)


async def run_civil_gas_pressure_drop(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.dry_utilities import (
            gas_pressure_drop_weymouth,
            gas_pressure_drop_darcy,
        )

        solver = params.get("solver", "weymouth")
        Q     = float(params["Q_m3s"])
        D     = float(params["D_m"])
        L     = float(params["L_m"])
        P1    = float(params["P1_kPa"])

        if solver == "weymouth":
            result = gas_pressure_drop_weymouth(
                Q_m3s=Q, D_m=D, L_m=L, P1_kPa=P1,
                T_K=float(params.get("T_K", 288.15)),
                SG=float(params.get("SG", 0.6)),
                efficiency=float(params.get("efficiency", 1.0)),
                Z=float(params.get("Z", 1.0)),
            )
        elif solver == "darcy":
            result = gas_pressure_drop_darcy(
                Q_m3s=Q, D_m=D, L_m=L, P_kPa=P1,
                mu_Pa_s=float(params.get("mu_Pa_s", 1.1e-5)),
                rho_kg_m3=float(params.get("rho_kg_m3", 0.72)),
                roughness_m=float(params.get("roughness_m", 4.6e-5)),
            )
        else:
            return err_payload(f"Unknown solver {solver!r}", "BAD_ARGS")

        result["solver"] = solver
        return ok_payload(result)

    except Exception as exc:
        return err_payload(str(exc), "CIVIL_GAS_PRESSURE_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_elec_duct_fill
# ---------------------------------------------------------------------------

civil_elec_duct_fill_spec = ToolSpec(
    name="civil_elec_duct_fill",
    description=(
        "Check electrical conduit / duct fill ratio per NEC Chapter 9, Table 1 (2020 NEC).\n"
        "\n"
        "NEC Table 1 maximum fill ratios (conduit cross-sectional area):\n"
        "  1 cable:    53 %\n"
        "  2 cables:   31 %\n"
        "  ≥ 3 cables: 40 %\n"
        "\n"
        "Cable outside diameter can be supplied directly (od_mm) or via AWG\n"
        "size string (e.g. '12AWG', '4/0AWG') for automatic lookup.\n"
        "\n"
        "Parameters:\n"
        "  conduit_id_mm : float — conduit inside diameter [mm]\n"
        "  cables        : list of { count: int, od_mm: float }\n"
        "                  or { count: int, awg: str }\n"
        "\n"
        "Returns:\n"
        "  ok                   : bool\n"
        "  fill_pct             : float — actual fill (%)\n"
        "  fill_limit_pct       : float — NEC Table 1 limit (%)\n"
        "  total_cable_area_mm2 : float\n"
        "  conduit_area_mm2     : float\n"
        "  n_cables             : int\n"
        "  pass_fail            : 'PASS' | 'FAIL'\n"
        "  cables               : list — resolved per-cable areas\n"
        "  warnings             : list[str]\n"
        "\n"
        "Reference: NFPA 70 (NEC) 2020, Chapter 9, Table 1.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "conduit_id_mm": {
                "type": "number",
                "description": "Conduit inside diameter [mm].",
            },
            "cables": {
                "type": "array",
                "description": "List of cable specs.",
                "items": {
                    "type": "object",
                    "properties": {
                        "count":  {"type": "integer", "minimum": 1},
                        "od_mm":  {"type": "number"},
                        "awg":    {"type": "string"},
                    },
                    "required": ["count"],
                },
            },
        },
        "required": ["conduit_id_mm", "cables"],
    },
)


async def run_civil_elec_duct_fill(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.dry_utilities import electrical_duct_fill_check

        conduit_id_mm = float(params["conduit_id_mm"])
        cables = params.get("cables", [])

        result = electrical_duct_fill_check(conduit_id_mm, cables)
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_ELEC_DUCT_FILL_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin.py
# ---------------------------------------------------------------------------

TOOLS = [
    ("civil_dry_utility_network_create",  civil_dry_utility_network_create_spec,  run_civil_dry_utility_network_create),
    ("civil_dry_utility_clearance_check", civil_dry_utility_clearance_check_spec, run_civil_dry_utility_clearance_check),
    ("civil_gas_pressure_drop",           civil_gas_pressure_drop_spec,           run_civil_gas_pressure_drop),
    ("civil_elec_duct_fill",              civil_elec_duct_fill_spec,              run_civil_elec_duct_fill),
]
