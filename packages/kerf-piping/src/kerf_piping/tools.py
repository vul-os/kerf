"""
kerf_piping LLM tools — P&ID routing + import + ASME B31 pressure-loss.

Tools
-----
piping_route_isometric  Route a pipe between equipment nozzles and return fitting counts.
piping_import_pid       Parse a text-format P&ID specification into the data model.
piping_export_svg       Export a P&ID diagram as an SVG string.
piping_pressure_loss    Darcy-Weisbach + Crane TP-410 K-factor pressure loss for a single run.
piping_pipeline_drop    Total ASME B31 pipeline pressure drop (segments + fittings).
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_piping._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# piping_route_isometric
# ---------------------------------------------------------------------------

piping_route_isometric_spec = ToolSpec(
    name="piping_route_isometric",
    description=(
        "Route a pipe isometrically between two 3D nozzle positions using "
        "orthogonal (axis-aligned) segments. Returns the segment list, "
        "elbow count, tee count, and total straight pipe length. "
        "All positions in metres."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "start": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "[x, y, z] start nozzle position (metres).",
            },
            "end": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "[x, y, z] end nozzle position (metres).",
            },
            "diameter_mm": {
                "type": "number",
                "description": "Nominal pipe diameter (mm). Default 50.",
            },
            "schedule": {
                "type": "string",
                "enum": ["40", "80", "160", "XS", "XXS"],
                "description": "Pipe schedule. Default '40'.",
            },
            "prefer_axis": {
                "type": "string",
                "enum": ["Z", "X", "Y"],
                "description": "Which axis to travel first. Default 'Z' (vertical first).",
            },
        },
        "required": ["start", "end"],
    },
)


async def run_piping_route_isometric(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.pid import Point3, PipeSchedule
        from kerf_piping.isometric import (
            route_orthogonal,
            count_fittings,
            pipe_length,
            FittingType,
        )

        start_raw = args["start"]
        end_raw = args["end"]
        diam = float(args.get("diameter_mm", 50.0))
        sched_str = str(args.get("schedule", "40"))
        prefer = str(args.get("prefer_axis", "Z"))

        try:
            sched = PipeSchedule(sched_str)
        except ValueError:
            sched = PipeSchedule.SCH_40

        start = Point3(*[float(v) for v in start_raw])
        end = Point3(*[float(v) for v in end_raw])

        segments = route_orthogonal(
            start, end,
            diameter_mm=diam,
            schedule=sched,
            prefer_axis=prefer,
        )
        fc = count_fittings(segments)
        total_len = pipe_length(segments)

        serialised = [
            {
                "from": list(s.start.as_tuple()),
                "to": list(s.end.as_tuple()),
                "fitting": s.fitting.value,
                "length_m": round(s.length, 4),
                "direction": list(round(v, 4) for v in s.direction),
            }
            for s in segments
        ]

        payload = {
            "segment_count": len(segments),
            "elbows_90": fc.elbows_90,
            "elbows_45": fc.elbows_45,
            "tees": fc.tees,
            "total_pipe_length_m": round(total_len, 4),
            "diameter_mm": diam,
            "schedule": sched.value,
            "segments": serialised,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "PIPING_ROUTE_ERROR")


# ---------------------------------------------------------------------------
# piping_import_pid
# ---------------------------------------------------------------------------

piping_import_pid_spec = ToolSpec(
    name="piping_import_pid",
    description=(
        "Parse a text-format P&ID specification into the Kerf P&ID data model. "
        "The input is a structured text description listing equipment items and "
        "pipe connections. Returns a summary of the parsed diagram. "
        "\n\nExpected text format (each line one directive):\n"
        "  VESSEL <tag> [type=<type>] [d=<m>] [L=<m>]\n"
        "  PUMP <tag> [type=<type>] [flow=<m3h>] [head=<m>]\n"
        "  HX <tag> [type=<type>] [duty=<kW>]\n"
        "  VALVE <tag> [type=<valve_type>] [dn=<mm>]\n"
        "  INSTRUMENT <tag>\n"
        "  PIPE <line_tag> <from_equip>.<from_nozzle> <to_equip>.<to_nozzle> "
        "[dn=<mm>] [sched=<sched>] [fluid=<fluid>]\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "P&ID specification text.",
            },
            "diagram_name": {
                "type": "string",
                "description": "Optional diagram name / drawing number.",
            },
        },
        "required": ["text"],
    },
)


async def run_piping_import_pid(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.pid import (
            PIDDiagram, Vessel, Pump, HeatExchanger, Valve, Instrument,
            ValveType, Pipe, PipeSchedule,
        )

        text: str = args["text"]
        name: str = str(args.get("diagram_name", "P&ID-001"))

        diagram, warnings = _parse_pid_text(text, name)

        payload = {
            "diagram": diagram.summary(),
            "warnings": warnings,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "PIPING_IMPORT_ERROR")


def _parse_pid_text(text: str, name: str) -> "tuple[PIDDiagram, list[str]]":
    """
    Parse a text P&ID specification.

    Returns (PIDDiagram, warnings).
    """
    from kerf_piping.pid import (
        PIDDiagram, Vessel, Pump, HeatExchanger, Valve, Instrument,
        ValveType, Pipe, PipeSchedule,
    )

    diagram = PIDDiagram(name)
    warnings: list[str] = []
    pipe_lines: list[str] = []  # defer pipe lines until all equipment is parsed

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        tokens = line.split()
        directive = tokens[0].upper()
        rest = tokens[1:]

        try:
            if directive == "VESSEL":
                kv = _parse_kv(rest[1:])
                comp = Vessel(
                    tag=rest[0],
                    vessel_type=kv.get("type", "drum"),
                    diameter_m=float(kv.get("d", 1.0)),
                    length_m=float(kv.get("l", 2.0)),
                )
                diagram.add_component(comp)

            elif directive == "PUMP":
                kv = _parse_kv(rest[1:])
                comp = Pump(
                    tag=rest[0],
                    pump_type=kv.get("type", "centrifugal"),
                    flow_m3h=float(kv.get("flow", 10.0)),
                    head_m=float(kv.get("head", 30.0)),
                )
                diagram.add_component(comp)

            elif directive == "HX":
                kv = _parse_kv(rest[1:])
                comp = HeatExchanger(
                    tag=rest[0],
                    hx_type=kv.get("type", "shell_tube"),
                    duty_kw=float(kv.get("duty", 500.0)),
                )
                diagram.add_component(comp)

            elif directive == "VALVE":
                kv = _parse_kv(rest[1:])
                vtype_str = kv.get("type", "gate").lower()
                try:
                    vtype = ValveType(vtype_str)
                except ValueError:
                    vtype = ValveType.GATE
                comp = Valve(
                    tag=rest[0],
                    valve_type=vtype,
                    diameter_mm=float(kv.get("dn", 50.0)),
                )
                diagram.add_component(comp)

            elif directive == "INSTRUMENT":
                comp = Instrument(tag=rest[0])
                diagram.add_component(comp)

            elif directive == "PIPE":
                pipe_lines.append(line)  # defer

            else:
                warnings.append(f"Unknown directive: {directive!r} — skipped")

        except (IndexError, ValueError, KeyError) as exc:
            warnings.append(f"Parse error on line {line!r}: {exc}")

    # Second pass: pipes
    for line in pipe_lines:
        tokens = line.split()
        rest = tokens[1:]
        try:
            pipe_tag = rest[0]
            from_str = rest[1]  # equip.nozzle
            to_str = rest[2]    # equip.nozzle
            kv = _parse_kv(rest[3:])

            from_eq, from_nz = from_str.split(".", 1)
            to_eq, to_nz = to_str.split(".", 1)

            sched_str = kv.get("sched", "40")
            try:
                sched = PipeSchedule(sched_str)
            except ValueError:
                sched = PipeSchedule.SCH_40

            pipe = Pipe(
                tag=pipe_tag,
                from_equipment=from_eq.upper(),
                from_nozzle=from_nz,
                to_equipment=to_eq.upper(),
                to_nozzle=to_nz,
                diameter_mm=float(kv.get("dn", 50.0)),
                schedule=sched,
                fluid=kv.get("fluid", "process"),
            )
            diagram.add_pipe(pipe)
        except (IndexError, ValueError, KeyError) as exc:
            warnings.append(f"Pipe parse error on line {line!r}: {exc}")

    return diagram, warnings


def _parse_kv(tokens: list[str]) -> dict[str, str]:
    """Parse key=value tokens into a dict."""
    result: dict[str, str] = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            result[k.strip().lower()] = v.strip()
    return result


# ---------------------------------------------------------------------------
# piping_export_svg
# ---------------------------------------------------------------------------

piping_export_svg_spec = ToolSpec(
    name="piping_export_svg",
    description=(
        "Export a P&ID text specification as an SVG schematic. "
        "Parses the text spec, then returns the SVG string."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "P&ID specification text (same format as piping_import_pid).",
            },
            "diagram_name": {
                "type": "string",
                "description": "Optional diagram name.",
            },
            "width": {
                "type": "integer",
                "description": "SVG canvas width in pixels. Default 800.",
            },
            "height": {
                "type": "integer",
                "description": "SVG canvas height in pixels. Default 300.",
            },
        },
        "required": ["text"],
    },
)


async def run_piping_export_svg(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.symbols import pid_diagram_svg

        text: str = args["text"]
        name: str = str(args.get("diagram_name", "P&ID-001"))
        width: int = int(args.get("width", 800))
        height: int = int(args.get("height", 300))

        diagram, warnings = _parse_pid_text(text, name)
        svg = pid_diagram_svg(diagram, width=width, height=height)

        payload = {
            "svg": svg,
            "warnings": warnings,
            "component_count": len(diagram.components),
            "pipe_count": len(diagram.pipes),
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "PIPING_SVG_ERROR")


# ---------------------------------------------------------------------------
# piping_pipe_spec_check  (ASME B31.3)
# ---------------------------------------------------------------------------

piping_pipe_spec_check_spec = ToolSpec(
    name="piping_pipe_spec_check",
    description=(
        "Check whether a pipe (nominal diameter + schedule) complies with an "
        "ASME B31.3 pipe class specification.  "
        "Validates: (1) DN in permitted list, (2) schedule vs spec-driven selection, "
        "(3) actual wall ≥ Barlow/B31.3 minimum, (4) design pressure ≤ class limit, "
        "(5) design temperature ≤ material maximum.  "
        "Returns: compliant (bool), violations, warnings, actual_wall_mm, "
        "min_required_wall_mm.  "
        "Material grades: A106-B (carbon steel), A312-316L/304L (stainless), "
        "A333-6 (low-temp), API5L-X42/X52/X65 (line pipe)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dn": {
                "type": "integer",
                "description": "Nominal pipe diameter (DN, mm). E.g. 50, 100, 150, 200, 250, 300.",
            },
            "schedule": {
                "type": "string",
                "description": "Pipe schedule code. E.g. '40', '80', 'STD', 'XS', '160'.",
            },
            "design_pressure_barg": {
                "type": "number",
                "description": "Design gauge pressure (barg).",
            },
            "design_temp_c": {
                "type": "number",
                "description": "Design temperature (°C).",
            },
            "material_spec": {
                "type": "string",
                "enum": ["A106", "A53", "A312", "A333", "API5L"],
                "description": "ASME/API material specification. Default 'A106'.",
            },
            "material_grade": {
                "type": "string",
                "description": "Material grade (e.g. 'B', '316L', '304L', '6', 'X52'). Default 'B'.",
            },
            "corrosion_allowance_mm": {
                "type": "number",
                "description": "Corrosion allowance to add to minimum wall (mm). Default 1.5.",
            },
            "class_name": {
                "type": "string",
                "description": "Pipe class identifier for the report. Default 'CS-A'.",
            },
            "class_pressure_barg": {
                "type": "number",
                "description": "Maximum pressure this pipe class is rated for (barg). Default = design_pressure_barg.",
            },
            "permitted_dn": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Permitted DN sizes for this class. Empty = no restriction.",
            },
            "default_schedule": {
                "type": "string",
                "description": "Default schedule for this pipe class. Default '40'.",
            },
        },
        "required": ["dn", "schedule", "design_pressure_barg", "design_temp_c"],
    },
)


async def run_piping_pipe_spec_check(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.pipe_spec import (
            MaterialSpec,
            PipeSpec,
            check_spec_compliance,
            ALLOWABLE_STRESS_MPA,
        )

        dn = int(args["dn"])
        schedule = str(args["schedule"]).upper()
        design_pressure_barg = float(args["design_pressure_barg"])
        design_temp_c = float(args["design_temp_c"])
        mat_spec = str(args.get("material_spec", "A106")).upper()
        mat_grade = str(args.get("material_grade", "B")).upper()
        ca_mm = float(args.get("corrosion_allowance_mm", 1.5))
        class_name = str(args.get("class_name", "CS-A"))
        class_pressure = float(args.get("class_pressure_barg", design_pressure_barg))
        permitted_dn = [int(d) for d in args.get("permitted_dn", [])]
        default_sched = str(args.get("default_schedule", "40")).upper()

        # Build MaterialSpec
        try:
            material = MaterialSpec.from_designation(
                spec=mat_spec,
                grade=mat_grade,
                corrosion_allowance_mm=ca_mm,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_MATERIAL")

        # Build PipeSpec
        spec = PipeSpec(
            name=class_name,
            material=material,
            design_pressure_barg=class_pressure,
            design_temp_c=design_temp_c,
            permitted_dn=permitted_dn,
            default_schedule=default_sched,
        )

        # Run compliance check
        result = check_spec_compliance(
            dn=dn,
            schedule=schedule,
            design_pressure_barg=design_pressure_barg,
            design_temp_c=design_temp_c,
            spec=spec,
        )

        payload: dict[str, Any] = result.as_dict()
        payload["ok"] = True
        payload["dn"] = dn
        payload["schedule"] = schedule
        payload["material_spec"] = mat_spec
        payload["material_grade"] = mat_grade
        payload["class_name"] = class_name

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_SPEC_ERROR")


# ---------------------------------------------------------------------------
# piping_pressure_loss  (ASME B31 / Crane TP-410)
# ---------------------------------------------------------------------------

piping_pressure_loss_spec = ToolSpec(
    name="piping_pressure_loss",
    description=(
        "Compute frictional pressure loss for a straight pipe run using "
        "Darcy-Weisbach with Colebrook-White friction factor (Crane Technical "
        "Paper 410 §1).  Optionally add fitting K-factor losses for one fitting "
        "type per call.  Returns ΔP in psi.\n\n"
        "DISCLAIMER: values from ASME B31 / Crane TP-410 — NOT certified "
        "compliance.  Have results reviewed by a licensed engineer.\n\n"
        "Supported fluids: 'water' (default), 'oil', 'air', 'steam'.\n"
        "Default roughness 0.00015 ft = commercial steel per Crane TP-410 App. B.\n\n"
        "Known fitting_kind values (Crane TP-410 §3 K-factors):\n"
        "  90_elbow_threaded (K=0.50), 90_elbow_welded (K=0.30),\n"
        "  45_elbow_threaded (K=0.38), 45_elbow_welded (K=0.20),\n"
        "  tee_through (K=0.40), tee_branch (K=1.00),\n"
        "  gate_valve_open (K=0.15), globe_valve (K=10.0),\n"
        "  check_valve (K=2.00), ball_valve_open (K=0.07),\n"
        "  butterfly_valve_open (K=0.30), angle_valve_open (K=2.00),\n"
        "  reducer_sudden (K=0.5·(1−β²)²), expander_sudden (K=(1−β²)²)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "diameter_in": {
                "type": "number",
                "description": "Internal pipe diameter (inches).",
            },
            "length_ft": {
                "type": "number",
                "description": "Pipe run length (feet).",
            },
            "flow_gpm": {
                "type": "number",
                "description": "Volumetric flow rate (US gallons per minute).",
            },
            "fluid": {
                "type": "string",
                "enum": ["water", "oil", "air", "steam"],
                "description": "Fluid type. Default 'water'.",
            },
            "roughness": {
                "type": "number",
                "description": (
                    "Absolute pipe wall roughness (feet). "
                    "Default 0.00015 ft (commercial steel)."
                ),
            },
            "fitting_kind": {
                "type": "string",
                "description": (
                    "Optional: include one fitting type to add its K-factor ΔP. "
                    "See tool description for valid values."
                ),
            },
            "fitting_qty": {
                "type": "integer",
                "description": "Number of fittings of fitting_kind. Default 1.",
            },
            "fitting_beta": {
                "type": "number",
                "description": (
                    "Diameter ratio (d_small/d_large) for reducer/expander. "
                    "Required only for 'reducer_sudden' and 'expander_sudden'."
                ),
            },
        },
        "required": ["diameter_in", "length_ft", "flow_gpm"],
    },
)


async def run_piping_pressure_loss(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.asme_pressure import (
            darcy_weisbach_loss,
            fitting_k_factor,
            _k_to_psi,
        )

        d_in    = float(args["diameter_in"])
        l_ft    = float(args["length_ft"])
        q_gpm   = float(args["flow_gpm"])
        fluid   = str(args.get("fluid", "water")).lower()
        rough   = float(args.get("roughness", 0.00015))

        pipe_dp = darcy_weisbach_loss(d_in, l_ft, q_gpm, fluid, rough)

        fitting_dp = 0.0
        fitting_detail: dict[str, Any] = {}
        if "fitting_kind" in args and args["fitting_kind"]:
            fk   = str(args["fitting_kind"])
            qty  = int(args.get("fitting_qty", 1))
            beta = float(args.get("fitting_beta", 1.0))
            k    = fitting_k_factor(fk, d_in, beta)
            fitting_dp = _k_to_psi(k, d_in, q_gpm, fluid) * qty
            fitting_detail = {
                "fitting_kind": fk,
                "quantity": qty,
                "K": round(k, 5),
                "fitting_dp_psi": round(fitting_dp, 6),
            }

        total_dp = pipe_dp + fitting_dp

        payload: dict[str, Any] = {
            "pipe_dp_psi": round(pipe_dp, 6),
            "fitting_dp_psi": round(fitting_dp, 6),
            "total_dp_psi": round(total_dp, 4),
            "diameter_in": d_in,
            "length_ft": l_ft,
            "flow_gpm": q_gpm,
            "fluid": fluid,
            "disclaimer": (
                "Values from ASME B31 / Crane TP-410 — NOT certified compliance."
            ),
        }
        if fitting_detail:
            payload["fitting"] = fitting_detail

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_PRESSURE_LOSS_ERROR")


# ---------------------------------------------------------------------------
# piping_pipeline_drop  (ASME B31 total pipeline ΔP)
# ---------------------------------------------------------------------------

piping_pipeline_drop_spec = ToolSpec(
    name="piping_pipeline_drop",
    description=(
        "Compute the total ASME B31 pressure drop for a complete pipeline: "
        "sum of Darcy-Weisbach straight-pipe losses over all segments plus "
        "Crane TP-410 §3 K-factor losses for all fittings.  Assumes "
        "incompressible, single-phase, steady-state flow at constant GPM.\n\n"
        "DISCLAIMER: values from ASME B31 / Crane TP-410 — NOT certified "
        "compliance.  Have results reviewed by a licensed engineer.\n\n"
        "Segment dict keys: diameter_in (float), length_ft (float), "
        "roughness (float, optional, ft), fluid (str, optional).\n"
        "Fitting dict keys: fitting_kind (str), diameter_in (float), "
        "beta (float, optional), quantity (int, optional), fluid (str, optional).\n\n"
        "Known fitting_kind values: 90_elbow_threaded (0.50), 90_elbow_welded (0.30), "
        "tee_through (0.40), tee_branch (1.00), gate_valve_open (0.15), "
        "globe_valve (10.0), check_valve (2.00), reducer_sudden, expander_sudden."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "diameter_in": {"type": "number"},
                        "length_ft":   {"type": "number"},
                        "roughness":   {"type": "number"},
                        "fluid":       {"type": "string"},
                    },
                    "required": ["diameter_in", "length_ft"],
                },
                "description": "List of straight-pipe segments.",
            },
            "fittings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fitting_kind": {"type": "string"},
                        "diameter_in":  {"type": "number"},
                        "beta":         {"type": "number"},
                        "quantity":     {"type": "integer"},
                        "fluid":        {"type": "string"},
                    },
                    "required": ["fitting_kind", "diameter_in"],
                },
                "description": "List of fittings (valves, elbows, tees, etc.).",
            },
            "flow_gpm": {
                "type": "number",
                "description": "Total flow rate (US gallons per minute).",
            },
            "fluid": {
                "type": "string",
                "enum": ["water", "oil", "air", "steam"],
                "description": "Default fluid for all segments/fittings. Default 'water'.",
            },
        },
        "required": ["segments", "fittings", "flow_gpm"],
    },
)


async def run_piping_pipeline_drop(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.asme_pressure import compute_pipeline_pressure_drop

        segments = args.get("segments", [])
        fittings = args.get("fittings", [])
        q_gpm    = float(args["flow_gpm"])
        fluid    = str(args.get("fluid", "water")).lower()

        result = compute_pipeline_pressure_drop(segments, fittings, q_gpm, fluid)
        return ok_payload(result)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_PIPELINE_DROP_ERROR")
