"""
tools_hydraulics.py — LLM tools for the civil hydraulics engines.

Exposes:
  civil_landxml_import     — Parse a LandXML 1.2 string → alignment/TIN/parcel dicts
  civil_landxml_export     — Serialise alignment/TIN/parcel geometry to LandXML 1.2 XML
  civil_water_network_solve — Steady-state pipe-network solver (GGA, HW or DW)
  civil_sewer_manning_capacity — Manning's equation for circular sewers + trapezoids
  civil_storm_rational     — Rational method peak runoff
  civil_culvert_capacity   — HDS-5 inlet-control headwater / capacity
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_civil._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Tool: civil_landxml_import
# ---------------------------------------------------------------------------

civil_landxml_import_spec = ToolSpec(
    name="civil_landxml_import",
    description=(
        "Parse a LandXML 1.2 string and return structured alignment, TIN surface, "
        "and parcel geometry.\n"
        "\n"
        "Supports:\n"
        "  <Alignments>  — CoordGeom Line/Curve elements + ProfAlign profile\n"
        "  <Surfaces>    — TIN via <Pnts> + <Faces>\n"
        "  <Parcels>     — boundary line geometry\n"
        "\n"
        "Returns:\n"
        "  ok         : bool\n"
        "  alignments : list of alignment dicts\n"
        "  surfaces   : list of TIN surface dicts\n"
        "  parcels    : list of parcel dicts\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "xml_str": {
                "type": "string",
                "description": "LandXML 1.2 XML string to parse.",
            },
        },
        "required": ["xml_str"],
    },
)


async def run_civil_landxml_import(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.landxml import import_landxml
        xml_str = params.get("xml_str", "")
        result = import_landxml(xml_str)
        return ok_payload({"ok": True, **result})
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_LANDXML_IMPORT_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_landxml_export
# ---------------------------------------------------------------------------

civil_landxml_export_spec = ToolSpec(
    name="civil_landxml_export",
    description=(
        "Export alignment, TIN surface, and parcel geometry to a LandXML 1.2 XML string.\n"
        "\n"
        "Alignment elements:\n"
        "  type 'Line'  : start, end (each [x, y])\n"
        "  type 'Curve' : start, end, center ([x, y]), radius (m), dir ('CCW'/'CW')\n"
        "Profile elements:\n"
        "  type 'PVI'       : station (m), elevation (m)\n"
        "  type 'ParaCurve' : station (m), elevation (m), length (m)\n"
        "Surface: points [[x,y,z]…], faces [[i0,i1,i2]…] (1-based)\n"
        "Parcel : lines [{'start':[x,y],'end':[x,y]}…]\n"
        "\n"
        "Returns:\n"
        "  ok      : bool\n"
        "  xml_str : LandXML 1.2 XML string\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alignments": {
                "type": "array",
                "description": "List of alignment dicts.",
                "items": {"type": "object"},
            },
            "surfaces": {
                "type": "array",
                "description": "List of TIN surface dicts.",
                "items": {"type": "object"},
            },
            "parcels": {
                "type": "array",
                "description": "List of parcel dicts.",
                "items": {"type": "object"},
            },
        },
    },
)


async def run_civil_landxml_export(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.landxml import export_landxml
        xml_str = export_landxml(
            alignments=params.get("alignments"),
            surfaces=params.get("surfaces"),
            parcels=params.get("parcels"),
        )
        return ok_payload({"ok": True, "xml_str": xml_str})
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_LANDXML_EXPORT_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_water_network_solve
# ---------------------------------------------------------------------------

civil_water_network_solve_spec = ToolSpec(
    name="civil_water_network_solve",
    description=(
        "Solve a steady-state pressurised water-distribution network using the "
        "Global Gradient Algorithm (Todini & Pilati, 1988).\n"
        "\n"
        "Head-loss formulae:\n"
        "  'HW' (default) — Hazen-Williams\n"
        "  'DW'           — Darcy-Weisbach with Swamee-Jain friction factor\n"
        "\n"
        "Inputs:\n"
        "  nodes       : [{id, elevation_m, demand_m3s}, …]\n"
        "  reservoirs  : [{id, head_m}, …]  (fixed-head sources)\n"
        "  pipes       : [{id, node_a, node_b, length_m, diameter_m, roughness}, …]\n"
        "               roughness = C (HW) or ε in metres (DW)\n"
        "\n"
        "Returns:\n"
        "  ok                 : bool\n"
        "  pipe_flows_m3s     : {pipe_id: flow}  (positive = node_a → node_b)\n"
        "  nodal_heads_m      : {node_id: head}\n"
        "  nodal_pressures_m  : {node_id: head - elevation}\n"
        "  converged          : bool\n"
        "  iterations         : int\n"
        "  residual           : float\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "elevation_m": {"type": "number"},
                        "demand_m3s": {"type": "number"},
                    },
                    "required": ["id", "elevation_m"],
                },
            },
            "reservoirs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "head_m": {"type": "number"},
                    },
                    "required": ["id", "head_m"],
                },
            },
            "pipes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "node_a": {"type": "string"},
                        "node_b": {"type": "string"},
                        "length_m": {"type": "number"},
                        "diameter_m": {"type": "number"},
                        "roughness": {"type": "number"},
                    },
                    "required": ["id", "node_a", "node_b", "length_m", "diameter_m", "roughness"],
                },
            },
            "formula": {
                "type": "string",
                "enum": ["HW", "DW"],
                "description": "Head-loss formula: 'HW' = Hazen-Williams, 'DW' = Darcy-Weisbach.",
                "default": "HW",
            },
            "max_iter": {"type": "integer", "default": 100},
            "tol": {"type": "number", "default": 1e-6},
        },
        "required": ["nodes", "reservoirs", "pipes"],
    },
)


async def run_civil_water_network_solve(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.hydraulics_pressure import (
            Node, Reservoir, Pipe, solve_network, check_mass_balance
        )

        nodes = [
            Node(
                id=n["id"],
                elevation_m=float(n["elevation_m"]),
                demand_m3s=float(n.get("demand_m3s", 0.0)),
            )
            for n in params.get("nodes", [])
        ]
        reservoirs = [
            Reservoir(id=r["id"], head_m=float(r["head_m"]))
            for r in params.get("reservoirs", [])
        ]
        pipes = [
            Pipe(
                id=p["id"],
                node_a=p["node_a"],
                node_b=p["node_b"],
                length_m=float(p["length_m"]),
                diameter_m=float(p["diameter_m"]),
                roughness=float(p["roughness"]),
            )
            for p in params.get("pipes", [])
        ]

        formula = params.get("formula", "HW")
        max_iter = int(params.get("max_iter", 100))
        tol = float(params.get("tol", 1e-6))

        result = solve_network(nodes, reservoirs, pipes, formula=formula,
                               max_iter=max_iter, tol=tol)

        balance = check_mass_balance(nodes, reservoirs, pipes, result)

        return ok_payload({
            "ok": True,
            "pipe_flows_m3s": {k: round(v, 8) for k, v in result.pipe_flows_m3s.items()},
            "nodal_heads_m": {k: round(v, 6) for k, v in result.nodal_heads_m.items()},
            "nodal_pressures_m": {k: round(v, 6) for k, v in result.nodal_pressures_m.items()},
            "converged": result.converged,
            "iterations": result.iterations,
            "residual": result.residual,
            "mass_balance": {k: round(v, 8) for k, v in balance.items()},
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_WATER_NETWORK_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_sewer_manning_capacity
# ---------------------------------------------------------------------------

civil_sewer_manning_capacity_spec = ToolSpec(
    name="civil_sewer_manning_capacity",
    description=(
        "Manning's equation for gravity flow in sewers and open channels.\n"
        "\n"
        "Sections supported:\n"
        "  'circular'     — full or part-full circular pipe\n"
        "  'trapezoidal'  — open channel (bottom width + side slopes)\n"
        "\n"
        "Operations:\n"
        "  'full_flow'     — full-flow (pipe-full) discharge\n"
        "  'capacity'      — discharge at specified depth\n"
        "  'normal_depth'  — depth (y/d for circular, y for trap) for given Q\n"
        "  'geometry'      — section geometry at given depth\n"
        "\n"
        "Parameters:\n"
        "  section  : 'circular' | 'trapezoidal'\n"
        "  op       : 'full_flow' | 'capacity' | 'normal_depth' | 'geometry'\n"
        "  d        : pipe diameter (m) — circular only\n"
        "  b        : bottom width (m) — trapezoidal only\n"
        "  z        : side slope H:1V  — trapezoidal only\n"
        "  y        : water depth (m) — capacity / geometry ops\n"
        "  n        : Manning's n\n"
        "  slope    : hydraulic gradient (m/m)\n"
        "  Q        : design discharge (m³/s) — normal_depth op\n"
        "\n"
        "Reference: Manning (1891); Chaudhry (2008) Open-Channel Hydraulics.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string", "enum": ["circular", "trapezoidal"]},
            "op": {"type": "string", "enum": ["full_flow", "capacity", "normal_depth", "geometry"]},
            "d": {"type": "number", "description": "Pipe diameter (m) — circular section."},
            "b": {"type": "number", "description": "Bottom width (m) — trapezoidal section."},
            "z": {"type": "number", "description": "Side slope H:1V — trapezoidal section."},
            "y": {"type": "number", "description": "Water depth (m) — capacity/geometry ops."},
            "n": {"type": "number", "description": "Manning's roughness n."},
            "slope": {"type": "number", "description": "Hydraulic slope (m/m)."},
            "Q": {"type": "number", "description": "Discharge (m³/s) — normal_depth op."},
        },
        "required": ["section", "op"],
    },
)


async def run_civil_sewer_manning_capacity(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.hydraulics_gravity import (
            circular_section_geometry, circular_full_flow,
            circular_capacity_at_depth, circular_normal_depth,
            trapezoidal_geometry, trapezoidal_capacity, trapezoidal_normal_depth,
        )

        section = params["section"]
        op = params["op"]
        n = float(params.get("n", 0.013))
        slope = float(params.get("slope", 0.001))

        if section == "circular":
            d = float(params["d"])
            if op == "full_flow":
                Q = circular_full_flow(d, n, slope)
                return ok_payload({"ok": True, "Q_full_m3s": round(Q, 8)})
            elif op == "capacity":
                y = float(params["y"])
                Q = circular_capacity_at_depth(d, n, slope, y)
                return ok_payload({"ok": True, "Q_m3s": round(Q, 8), "depth_m": y})
            elif op == "normal_depth":
                Q = float(params["Q"])
                yd_ratio = circular_normal_depth(d, n, slope, Q)
                return ok_payload({
                    "ok": True,
                    "y_over_d": round(yd_ratio, 8),
                    "y_m": round(yd_ratio * d, 6),
                })
            elif op == "geometry":
                y = float(params["y"])
                geom = circular_section_geometry(d, y)
                return ok_payload({"ok": True, **{k: round(v, 8) for k, v in geom.items()}})

        elif section == "trapezoidal":
            b = float(params["b"])
            z = float(params.get("z", 0.0))
            if op == "capacity":
                y = float(params["y"])
                Q = trapezoidal_capacity(b, z, n, slope, y)
                return ok_payload({"ok": True, "Q_m3s": round(Q, 8)})
            elif op == "normal_depth":
                Q = float(params["Q"])
                y_n = trapezoidal_normal_depth(b, z, n, slope, Q)
                return ok_payload({"ok": True, "y_m": round(y_n, 6)})
            elif op == "geometry":
                y = float(params["y"])
                geom = trapezoidal_geometry(b, z, y)
                return ok_payload({"ok": True, **{k: round(v, 8) for k, v in geom.items()}})
            elif op == "full_flow":
                return err_payload("full_flow not applicable to trapezoidal section", "BAD_ARGS")

        return err_payload(f"unknown section/op combination: {section}/{op}", "BAD_ARGS")

    except Exception as exc:
        return err_payload(str(exc), "CIVIL_SEWER_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_storm_rational
# ---------------------------------------------------------------------------

civil_storm_rational_spec = ToolSpec(
    name="civil_storm_rational",
    description=(
        "Rational method peak runoff: Q = C · i · A / 360\n"
        "(where A in hectares, i in mm/hr, Q in m³/s)\n"
        "\n"
        "Reference: Kuichling (1889); ASCE/EWRI 77-17.\n"
        "\n"
        "Parameters:\n"
        "  C        : runoff coefficient (0–1)\n"
        "  i_mm_hr  : rainfall intensity (mm/hr)\n"
        "  area_ha  : drainage area (hectares)\n"
        "\n"
        "Returns:\n"
        "  ok   : bool\n"
        "  Q_m3s: peak discharge (m³/s)\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {"type": "number", "description": "Runoff coefficient (0–1)."},
            "i_mm_hr": {"type": "number", "description": "Rainfall intensity (mm/hr)."},
            "area_ha": {"type": "number", "description": "Drainage area (ha)."},
        },
        "required": ["C", "i_mm_hr", "area_ha"],
    },
)


async def run_civil_storm_rational(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.storm import rational_method
        C = float(params["C"])
        i_mm_hr = float(params["i_mm_hr"])
        area_ha = float(params["area_ha"])
        Q = rational_method(C, i_mm_hr, area_ha)
        return ok_payload({"ok": True, "Q_m3s": round(Q, 8)})
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_STORM_RATIONAL_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_culvert_capacity
# ---------------------------------------------------------------------------

civil_culvert_capacity_spec = ToolSpec(
    name="civil_culvert_capacity",
    description=(
        "HDS-5 culvert inlet-control analysis for circular concrete culverts.\n"
        "\n"
        "Operations:\n"
        "  'headwater'  — given Q and culvert geometry, compute headwater H (m)\n"
        "  'capacity'   — given headwater H, solve for maximum discharge Q (m³/s)\n"
        "\n"
        "Uses FHWA HDS-5 (2012) Table 3-1 inlet-control equations:\n"
        "  Unsubmerged: H/D = K·(Q/(A·√D))^M + K_s\n"
        "  Submerged:   H/D = c·(Q/(A·√D))² + Y - 0.5S\n"
        "\n"
        "Parameters:\n"
        "  op           : 'headwater' | 'capacity'\n"
        "  d            : culvert diameter (m)\n"
        "  Q            : discharge (m³/s)  — headwater op\n"
        "  HW           : headwater depth (m) — capacity op\n"
        "  slope        : barrel slope (m/m, default 0.01)\n"
        "  K, M, c, Y   : HDS-5 coefficients (defaults: square-edge concrete)\n"
        "\n"
        "Returns:\n"
        "  ok     : bool\n"
        "  H_m    : headwater above inlet invert (m)  — headwater op\n"
        "  Q_m3s  : max discharge (m³/s)              — capacity op\n"
        "  HW_D   : headwater-to-diameter ratio\n"
        "  regime : 'unsubmerged', 'transition', 'submerged'\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["headwater", "capacity"]},
            "d": {"type": "number", "description": "Culvert diameter (m)."},
            "Q": {"type": "number", "description": "Discharge (m³/s)."},
            "HW": {"type": "number", "description": "Headwater depth above invert (m)."},
            "slope": {"type": "number", "default": 0.01},
            "K": {"type": "number", "description": "HDS-5 K coefficient."},
            "M": {"type": "number", "description": "HDS-5 M coefficient."},
            "c": {"type": "number", "description": "HDS-5 c coefficient."},
            "Y": {"type": "number", "description": "HDS-5 Y coefficient."},
        },
        "required": ["op", "d"],
    },
)


async def run_civil_culvert_capacity(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.storm import culvert_inlet_control, culvert_capacity

        op = params["op"]
        d = float(params["d"])
        slope = float(params.get("slope", 0.01))

        kwargs = {}
        if params.get("K") is not None:
            kwargs["K"] = float(params["K"])
        if params.get("M") is not None:
            kwargs["M"] = float(params["M"])
        if params.get("c") is not None:
            kwargs["c"] = float(params["c"])
        if params.get("Y") is not None:
            kwargs["Y"] = float(params["Y"])

        if op == "headwater":
            Q = float(params["Q"])
            result = culvert_inlet_control(Q, d, slope=slope, **kwargs)
            return ok_payload({"ok": True, **result})
        elif op == "capacity":
            HW = float(params["HW"])
            result = culvert_capacity(d, HW, slope=slope, **kwargs)
            return ok_payload({"ok": True, **result})
        else:
            return err_payload(f"unknown op {op!r}", "BAD_ARGS")

    except Exception as exc:
        return err_payload(str(exc), "CIVIL_CULVERT_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin.py
# ---------------------------------------------------------------------------

TOOLS = [
    ("civil_landxml_import",          civil_landxml_import_spec,          run_civil_landxml_import),
    ("civil_landxml_export",          civil_landxml_export_spec,          run_civil_landxml_export),
    ("civil_water_network_solve",     civil_water_network_solve_spec,     run_civil_water_network_solve),
    ("civil_sewer_manning_capacity",  civil_sewer_manning_capacity_spec,  run_civil_sewer_manning_capacity),
    ("civil_storm_rational",          civil_storm_rational_spec,          run_civil_storm_rational),
    ("civil_culvert_capacity",        civil_culvert_capacity_spec,        run_civil_culvert_capacity),
]
